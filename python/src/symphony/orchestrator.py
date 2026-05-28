"""Minimal orchestration loop over tracker, workspace, prompt, and runner."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from symphony.log_events import EventLogger, StatusSnapshotStore
from symphony.models import (
    Issue,
    RunAttempt,
    RunEvent,
    RunMetadata,
    RunRef,
    RunStatus,
    StatusSnapshot,
    WorkflowDefinition,
    Workspace,
)
from symphony.prompt import build_prompt
from symphony.run_ledger import RunLedger
from symphony.runner.base import Runner, RunOptions
from symphony.tracker.base import Tracker
from symphony.workspace import WorkspaceManager

Clock = Callable[[], datetime]
WorkspacePreparer = Callable[[Workspace], Awaitable[None]]
_ACTIVE_STATUSES: set[RunStatus] = {"queued", "starting", "running", "waiting_for_permission"}
_TERMINAL_STATUSES: set[RunStatus] = {"succeeded", "failed", "cancelled"}


@dataclass(frozen=True)
class OrchestratorCycleResult:
    """Result of one poll/dispatch cycle."""

    issue: Issue
    run_id: str
    status: RunStatus


class Orchestrator:
    """Single-cycle orchestrator for the Python MVP path."""

    def __init__(
        self,
        *,
        tracker: Tracker,
        tracker_kind: str,
        workspace_manager: WorkspaceManager,
        workflow: WorkflowDefinition,
        runner: Runner,
        run_ledger: RunLedger,
        event_logger: EventLogger,
        status_store: StatusSnapshotStore,
        workspace_preparer: WorkspacePreparer | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._tracker = tracker
        self._tracker_kind = tracker_kind
        self._workspace_manager = workspace_manager
        self._workflow = workflow
        self._runner = runner
        self._run_ledger = run_ledger
        self._event_logger = event_logger
        self._status_store = status_store
        self._workspace_preparer = workspace_preparer
        self._clock = clock or _utc_now

    async def run_once(self, *, attempt: int | None = None) -> OrchestratorCycleResult | None:
        """Dispatch the first ready issue and persist the resulting run state."""

        issues = await self._tracker.fetch_candidate_issues()
        if not issues:
            self._write_snapshot(())
            return None

        issue = issues[0]
        await self._tracker.update_issue_state(issue.id, "in_progress")

        workspace = self._workspace_manager.create_for_issue(issue.identifier)
        if workspace.created_now and self._workspace_preparer is not None:
            await self._workspace_preparer(workspace)
        prompt = build_prompt(self._workflow, issue, attempt=attempt)
        started_at = self._clock()
        run_ref = await self._runner.start_run(
            issue,
            prompt,
            RunOptions(
                tracker_kind=self._tracker_kind,
                workspace_path=workspace.path,
                attempt=attempt,
            ),
        )

        metadata = RunMetadata(
            provider=run_ref.provider,
            mode=run_ref.mode,
            tracker_kind=self._tracker_kind,
            issue_id=issue.id,
            issue_identifier=issue.identifier,
            run_id=run_ref.run_id,
            attempt=attempt,
            workspace_path=workspace.path,
            status="running",
            started_at=started_at,
            updated_at=started_at,
        )
        self._run_ledger.write(metadata)

        events_seen = await self._append_new_events(run_ref, events_seen=0)
        status = await self._runner.poll_run(run_ref)
        events_seen = await self._append_new_events(run_ref, events_seen=events_seen)
        del events_seen

        now = self._clock()
        updated_metadata = metadata.model_copy(
            update={
                "status": status,
                "updated_at": now,
                "completed_at": now if status in _TERMINAL_STATUSES else None,
                "error": _latest_error(await self._runner.fetch_events(run_ref), status),
            }
        )
        self._run_ledger.write(updated_metadata)

        if status == "succeeded":
            await self._tracker.update_issue_state(issue.id, "closed")

        active_runs = (
            (
                RunAttempt(
                    issue_id=issue.id,
                    issue_identifier=issue.identifier,
                    attempt=attempt,
                    workspace_path=workspace.path,
                    started_at=started_at,
                    status=status,
                    error=updated_metadata.error,
                ),
            )
            if status in _ACTIVE_STATUSES
            else ()
        )
        self._write_snapshot(active_runs)

        return OrchestratorCycleResult(issue=issue, run_id=run_ref.run_id, status=status)

    async def _append_new_events(self, run_ref: RunRef, *, events_seen: int) -> int:
        events = await self._runner.fetch_events(run_ref)
        for event in events[events_seen:]:
            self._event_logger.append(event)
        return len(events)

    def _write_snapshot(self, active_runs: tuple[RunAttempt, ...]) -> None:
        self._status_store.write(
            StatusSnapshot(generated_at=self._clock(), active_runs=active_runs)
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _latest_error(events: list[RunEvent], status: RunStatus) -> str | None:
    if status != "failed":
        return None
    return events[-1].message if events else "Run failed"
