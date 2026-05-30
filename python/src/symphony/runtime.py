"""Runtime assembly for local Symphony commands."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from symphony.config import ServiceConfig, load_config
from symphony.hooks import run_workspace_hook
from symphony.log_events import EventLogger, StatusSnapshotStore
from symphony.models import WorkflowDefinition, Workspace
from symphony.orchestrator import Orchestrator, OrchestratorCycleResult, WorkspacePreparer
from symphony.run_ledger import RunLedger
from symphony.runner.claude_headless import ClaudeHeadlessRunner
from symphony.tracker.base import Tracker
from symphony.tracker.beads import BeadsTracker
from symphony.tracker.github import GitHubTracker
from symphony.tracker.jira import JiraTracker
from symphony.workflow import load_workflow
from symphony.workspace import WorkspaceManager


class SymphonyRuntimeError(RuntimeError):
    """Raised when a runtime command cannot be assembled."""


DaemonCycleCallback = Callable[[int, OrchestratorCycleResult | None], None]
SleepFn = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class DaemonResult:
    """Summary returned when a bounded daemon run exits."""

    cycles: int


async def run_once_from_workflow(
    workflow_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> OrchestratorCycleResult | None:
    """Load a workflow file and run one eligible issue through the configured local path."""

    workflow = load_workflow(workflow_path)
    config = load_config(workflow.config, environ)
    tracker = _build_tracker(config)
    await tracker.check_supported_version()
    orchestrator = _build_orchestrator(workflow, config, tracker)
    return await orchestrator.run_once(wait_for_completion=True)


async def run_daemon_from_workflow(
    workflow_path: Path,
    *,
    cycles: int | None = None,
    environ: Mapping[str, str] | None = None,
    on_cycle: DaemonCycleCallback | None = None,
    sleep: SleepFn = asyncio.sleep,
) -> DaemonResult:
    """Run the configured workflow repeatedly until stopped or the cycle limit is reached."""

    if cycles is not None and cycles < 1:
        raise SymphonyRuntimeError("cycles must be at least 1")

    workflow = load_workflow(workflow_path)
    config = load_config(workflow.config, environ)
    tracker = _build_tracker(config)
    await tracker.check_supported_version()
    orchestrator = _build_orchestrator(workflow, config, tracker)
    poll_interval_seconds = config.polling.interval_ms / 1000

    completed_cycles = 0
    while cycles is None or completed_cycles < cycles:
        result = await orchestrator.run_once(
            wait_for_completion=True,
            poll_interval_seconds=poll_interval_seconds,
        )
        completed_cycles += 1
        if on_cycle is not None:
            on_cycle(completed_cycles, result)
        if cycles is not None and completed_cycles >= cycles:
            break
        await sleep(poll_interval_seconds)

    return DaemonResult(cycles=completed_cycles)


def find_workflow_path(start: Path) -> Path:
    """Find WORKFLOW.md at or above a starting path."""

    current = start.resolve(strict=False)
    if current.is_file():
        current = current.parent

    for directory in (current, *current.parents):
        candidate = directory / "WORKFLOW.md"
        if candidate.is_file():
            return candidate
    raise SymphonyRuntimeError(f"Unable to find WORKFLOW.md at or above {start}")


def _build_orchestrator(
    workflow: WorkflowDefinition,
    config: ServiceConfig,
    tracker: Tracker,
) -> Orchestrator:
    if config.agent.provider != "claude" or config.agent.mode != "headless":
        raise SymphonyRuntimeError(
            "run-once currently supports only agent.provider=claude mode=headless"
        )
    if config.claude.headless is None:
        raise SymphonyRuntimeError("agent.mode=headless requires claude.headless config")

    return Orchestrator(
        tracker=tracker,
        tracker_kind=config.tracker.kind,
        workspace_manager=WorkspaceManager(config.workspace),
        workflow=workflow,
        runner=ClaudeHeadlessRunner(config.claude.headless, environment=config.environment),
        run_ledger=RunLedger(),
        event_logger=EventLogger(),
        status_store=StatusSnapshotStore(),
        workspace_preparer=_workspace_preparer(config),
    )


def _build_tracker(config: ServiceConfig) -> Tracker:
    if config.tracker.kind == "beads":
        return BeadsTracker(config.tracker)
    if config.tracker.kind == "github":
        return GitHubTracker(config.tracker)
    if config.tracker.kind == "jira":
        return JiraTracker(config.tracker)
    raise SymphonyRuntimeError(f"Unsupported tracker.kind for run-once: {config.tracker.kind}")


def _workspace_preparer(config: ServiceConfig) -> WorkspacePreparer | None:
    if config.hooks.after_create is None:
        return None

    async def prepare(workspace: Workspace) -> None:
        await run_workspace_hook(config.hooks.after_create or "", workspace_path=workspace.path)

    return prepare
