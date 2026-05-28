from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from symphony.config import WorkspaceConfig
from symphony.log_events import EventLogger, StatusSnapshotStore
from symphony.models import Issue, WorkflowDefinition, Workspace
from symphony.orchestrator import Orchestrator
from symphony.run_ledger import RunLedger
from symphony.runner.fake import FakeRunner, FakeRunScript
from symphony.workspace import WorkspaceManager


class MemoryTracker:
    def __init__(self, issues: list[Issue]) -> None:
        self.issues = issues
        self.state_updates: list[tuple[str, str]] = []

    async def fetch_candidate_issues(self) -> list[Issue]:
        return self.issues

    async def fetch_issues_by_states(self, state_names: list[str]) -> list[Issue]:
        del state_names
        return []

    async def fetch_issue_states_by_ids(self, issue_ids: list[str]) -> dict[str, str]:
        return {issue_id: "open" for issue_id in issue_ids}

    async def create_comment(self, issue_id: str, body: str) -> None:
        del issue_id, body

    async def update_issue_state(self, issue_id: str, state_name: str) -> None:
        self.state_updates.append((issue_id, state_name))


class Clock:
    def __init__(self) -> None:
        self._current = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self._current
        self._current += timedelta(seconds=1)
        return value


def issue() -> Issue:
    return Issue(
        id="symphony-123",
        identifier="symphony-123",
        title="Implement orchestrator",
        description="Wire the fake runner path",
        state="open",
    )


def workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        config={},
        prompt_template="Work on {{ issue.identifier }}: {{ issue.title }}",
    )


def orchestrator(
    tmp_path: Path,
    *,
    tracker: MemoryTracker,
    runner: FakeRunner | None = None,
) -> Orchestrator:
    return Orchestrator(
        tracker=tracker,
        tracker_kind="beads",
        workspace_manager=WorkspaceManager(WorkspaceConfig(root=tmp_path / "workspaces")),
        workflow=workflow(),
        runner=runner or FakeRunner(),
        run_ledger=RunLedger(tmp_path / ".symphony" / "runs"),
        event_logger=EventLogger(tmp_path / "log" / "events.jsonl"),
        status_store=StatusSnapshotStore(tmp_path / "log" / "status.json"),
        clock=Clock(),
    )


@pytest.mark.asyncio
async def test_orchestrator_writes_empty_status_snapshot_when_no_issue(tmp_path: Path) -> None:
    status_store = StatusSnapshotStore(tmp_path / "log" / "status.json")
    orch = Orchestrator(
        tracker=MemoryTracker([]),
        tracker_kind="beads",
        workspace_manager=WorkspaceManager(WorkspaceConfig(root=tmp_path / "workspaces")),
        workflow=workflow(),
        runner=FakeRunner(),
        run_ledger=RunLedger(tmp_path / ".symphony" / "runs"),
        event_logger=EventLogger(tmp_path / "log" / "events.jsonl"),
        status_store=status_store,
        clock=Clock(),
    )

    result = await orch.run_once()

    assert result is None
    snapshot = status_store.read()
    assert snapshot is not None
    assert snapshot.active_runs == ()


@pytest.mark.asyncio
async def test_orchestrator_runs_ready_issue_through_fake_runner(tmp_path: Path) -> None:
    tracker = MemoryTracker([issue()])
    runner = FakeRunner()
    orch = orchestrator(tmp_path, tracker=tracker, runner=runner)

    result = await orch.run_once()

    assert result is not None
    assert result.status == "succeeded"
    assert tracker.state_updates == [("symphony-123", "in_progress"), ("symphony-123", "closed")]

    ledger = RunLedger(tmp_path / ".symphony" / "runs")
    metadata = ledger.read(result.run_id)
    assert metadata.status == "succeeded"
    assert metadata.issue_identifier == "symphony-123"
    assert metadata.workspace_path == tmp_path / "workspaces" / "symphony-123"
    assert metadata.completed_at is not None

    events = EventLogger(tmp_path / "log" / "events.jsonl").read_all()
    assert [event.event_type for event in events] == ["run_started", "run_succeeded"]
    assert events[0].workspace_path == tmp_path / "workspaces" / "symphony-123"
    assert runner.started_prompts[result.run_id] == "Work on symphony-123: Implement orchestrator"

    snapshot = StatusSnapshotStore(tmp_path / "log" / "status.json").read()
    assert snapshot is not None
    assert snapshot.active_runs == ()


@pytest.mark.asyncio
async def test_orchestrator_prepares_new_workspace_before_runner(tmp_path: Path) -> None:
    tracker = MemoryTracker([issue()])
    runner = FakeRunner()
    prepared_paths: list[Path] = []

    async def prepare(workspace: Workspace) -> None:
        prepared_paths.append(workspace.path)
        (workspace.path / "prepared.txt").write_text("ready", encoding="utf-8")

    orch = Orchestrator(
        tracker=tracker,
        tracker_kind="beads",
        workspace_manager=WorkspaceManager(WorkspaceConfig(root=tmp_path / "workspaces")),
        workflow=workflow(),
        runner=runner,
        run_ledger=RunLedger(tmp_path / ".symphony" / "runs"),
        event_logger=EventLogger(tmp_path / "log" / "events.jsonl"),
        status_store=StatusSnapshotStore(tmp_path / "log" / "status.json"),
        workspace_preparer=prepare,
        clock=Clock(),
    )

    result = await orch.run_once()

    assert result is not None
    workspace_path = tmp_path / "workspaces" / "symphony-123"
    assert prepared_paths == [workspace_path]
    assert (workspace_path / "prepared.txt").read_text(encoding="utf-8") == "ready"


@pytest.mark.asyncio
async def test_orchestrator_keeps_waiting_run_active_in_status_snapshot(tmp_path: Path) -> None:
    tracker = MemoryTracker([issue()])
    runner = FakeRunner(scripts_by_identifier={"symphony-123": [FakeRunScript(outcome="waiting")]})
    orch = orchestrator(tmp_path, tracker=tracker, runner=runner)

    result = await orch.run_once()

    assert result is not None
    assert result.status == "waiting_for_permission"
    assert tracker.state_updates == [("symphony-123", "in_progress")]

    metadata = RunLedger(tmp_path / ".symphony" / "runs").read(result.run_id)
    assert metadata.status == "waiting_for_permission"
    assert metadata.completed_at is None

    snapshot = StatusSnapshotStore(tmp_path / "log" / "status.json").read()
    assert snapshot is not None
    assert len(snapshot.active_runs) == 1
    assert snapshot.active_runs[0].status == "waiting_for_permission"
