from pathlib import Path

import pytest

from symphony.models import Issue
from symphony.orchestrator import OrchestratorCycleResult
from symphony.runtime import SymphonyRuntimeError, find_workflow_path, run_daemon_from_workflow

WORKFLOW_TEXT = """---
tracker:
  kind: memory
polling:
  interval_ms: 250
workspace:
  root: /tmp/symphony-workspaces
agent:
  provider: claude
  mode: headless
claude:
  headless:
    executable: claude
---

Do work.
"""


def test_find_workflow_path_searches_upward(tmp_path: Path) -> None:
    workflow = tmp_path / "WORKFLOW.md"
    workflow.write_text("---\n---\n\nDo work.\n", encoding="utf-8")
    nested = tmp_path / "one" / "two"
    nested.mkdir(parents=True)

    assert find_workflow_path(nested) == workflow


def test_find_workflow_path_accepts_file_start_path(tmp_path: Path) -> None:
    workflow = tmp_path / "WORKFLOW.md"
    workflow.write_text("---\n---\n\nDo work.\n", encoding="utf-8")
    child = tmp_path / "child.txt"
    child.write_text("", encoding="utf-8")

    assert find_workflow_path(child) == workflow


def test_find_workflow_path_reports_missing_workflow(tmp_path: Path) -> None:
    with pytest.raises(SymphonyRuntimeError, match=r"Unable to find WORKFLOW\.md"):
        find_workflow_path(tmp_path)


@pytest.mark.asyncio
async def test_run_daemon_from_workflow_runs_bounded_cycles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = tmp_path / "WORKFLOW.md"
    workflow.write_text(WORKFLOW_TEXT, encoding="utf-8")
    results = [
        OrchestratorCycleResult(
            issue=Issue(id="1", identifier="ONE", title="One", state="open"),
            run_id="run-1",
            status="succeeded",
        ),
        None,
    ]
    observed_cycles: list[tuple[int, OrchestratorCycleResult | None]] = []
    sleeps: list[float] = []

    class FakeTracker:
        async def check_supported_version(self) -> None:
            return None

    class FakeOrchestrator:
        def __init__(self) -> None:
            self.calls = 0

        async def run_once(
            self,
            *,
            wait_for_completion: bool,
            poll_interval_seconds: float,
        ) -> OrchestratorCycleResult | None:
            assert wait_for_completion is True
            assert poll_interval_seconds == 0.25
            result = results[self.calls]
            self.calls += 1
            return result

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def fake_build_tracker(_config: object) -> FakeTracker:
        return FakeTracker()

    def fake_build_orchestrator(
        _workflow: object, _config: object, _tracker: object
    ) -> FakeOrchestrator:
        return FakeOrchestrator()

    monkeypatch.setattr("symphony.runtime._build_tracker", fake_build_tracker)
    monkeypatch.setattr(
        "symphony.runtime._build_orchestrator",
        fake_build_orchestrator,
    )

    result = await run_daemon_from_workflow(
        workflow,
        cycles=2,
        on_cycle=lambda cycle, cycle_result: observed_cycles.append((cycle, cycle_result)),
        sleep=fake_sleep,
    )

    assert result.cycles == 2
    observed = [
        (cycle, cycle_result.run_id if cycle_result else None)
        for cycle, cycle_result in observed_cycles
    ]
    assert observed == [
        (1, "run-1"),
        (2, None),
    ]
    assert sleeps == [0.25]


@pytest.mark.asyncio
async def test_run_daemon_from_workflow_rejects_invalid_cycle_limit(tmp_path: Path) -> None:
    workflow = tmp_path / "WORKFLOW.md"
    workflow.write_text(WORKFLOW_TEXT, encoding="utf-8")

    with pytest.raises(SymphonyRuntimeError, match="cycles"):
        await run_daemon_from_workflow(workflow, cycles=0)
