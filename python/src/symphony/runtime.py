"""Runtime assembly for local Symphony commands."""

from __future__ import annotations

from collections.abc import Mapping
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
from symphony.workflow import load_workflow
from symphony.workspace import WorkspaceManager


class SymphonyRuntimeError(RuntimeError):
    """Raised when a runtime command cannot be assembled."""


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
    raise SymphonyRuntimeError(f"Unsupported tracker.kind for run-once: {config.tracker.kind}")


def _workspace_preparer(config: ServiceConfig) -> WorkspacePreparer | None:
    if config.hooks.after_create is None:
        return None

    async def prepare(workspace: Workspace) -> None:
        await run_workspace_hook(config.hooks.after_create or "", workspace_path=workspace.path)

    return prepare
