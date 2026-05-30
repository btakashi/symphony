"""Command-line entry points for Symphony."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, cast

import typer

from symphony.log_events import StatusSnapshotStore
from symphony.models import RunMetadata, StatusSnapshot
from symphony.orchestrator import OrchestratorCycleResult
from symphony.run_ledger import RunLedger, RunLedgerError
from symphony.runner.claude_headless import ClaudeHeadlessRunnerError, parse_structured_handoff
from symphony.runtime import (
    RuntimeCheck,
    check_workflow,
    find_workflow_path,
    run_daemon_from_workflow,
    run_once_from_workflow,
)
from symphony.runtime_paths import RUN_LEDGER_DIR, STATUS_SNAPSHOT_PATH

app = typer.Typer(help="Python implementation of Symphony.")
run_app = typer.Typer(help="Inspect and manage individual runs.")
app.add_typer(run_app, name="run")


@app.callback()
def root() -> None:
    """Run the Symphony command-line interface."""


@app.command("run-once")
def run_once(
    workflow_path: Annotated[
        Path | None,
        typer.Option(
            "--workflow",
            help="Path to WORKFLOW.md. Defaults to searching from the current directory.",
        ),
    ] = None,
) -> None:
    """Run one ready issue through the configured local Symphony workflow."""

    workflow = workflow_path or find_workflow_path(Path.cwd())
    result = asyncio.run(run_once_from_workflow(workflow))
    if result is None:
        typer.echo("No ready issues.")
        return

    typer.echo(f"{result.issue.identifier}: {result.status} ({result.run_id})")
    if result.status == "failed":
        raise typer.Exit(code=1)


@app.command("daemon")
def daemon(
    workflow_path: Annotated[
        Path | None,
        typer.Option(
            "--workflow",
            help="Path to WORKFLOW.md. Defaults to searching from the current directory.",
        ),
    ] = None,
    cycles: Annotated[
        int | None,
        typer.Option("--cycles", help="Stop after this many poll cycles."),
    ] = None,
) -> None:
    """Poll the configured tracker and run eligible issues until stopped."""

    workflow = workflow_path or find_workflow_path(Path.cwd())

    def report(cycle: int, result: OrchestratorCycleResult | None) -> None:
        prefix = f"cycle {cycle}:"
        if result is None:
            typer.echo(f"{prefix} no ready issues")
            return
        typer.echo(f"{prefix} {result.issue.identifier}: {result.status} ({result.run_id})")

    asyncio.run(run_daemon_from_workflow(workflow, cycles=cycles, on_cycle=report))


@app.command("doctor")
def doctor(
    workflow_path: Annotated[
        Path | None,
        typer.Option(
            "--workflow",
            help="Path to WORKFLOW.md. Defaults to searching from the current directory.",
        ),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
) -> None:
    """Check whether a workflow is ready for local daemon execution."""

    workflow = workflow_path or find_workflow_path(Path.cwd())
    checks = asyncio.run(check_workflow(workflow))
    if json_output:
        typer.echo(_json({"checks": [_check_json(check) for check in checks]}))
    else:
        typer.echo(_format_checks(checks))

    if any(check.status == "fail" for check in checks):
        raise typer.Exit(code=1)


@app.command("runs")
def runs(
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
    limit: Annotated[int, typer.Option("--limit", help="Maximum runs to show.")] = 20,
    ledger_dir: Annotated[
        Path,
        typer.Option("--ledger-dir", help="Directory containing run ledger JSON files."),
    ] = RUN_LEDGER_DIR,
) -> None:
    """List recent run attempts with workspace paths."""

    recent_runs = _recent_runs(RunLedger(ledger_dir).list(), limit=limit)
    if json_output:
        typer.echo(_json({"runs": recent_runs}))
        return
    typer.echo(_format_runs(recent_runs))


@run_app.command("show")
def run_show(
    run_id: Annotated[str, typer.Argument(help="Run ID to inspect.")],
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
    ledger_dir: Annotated[
        Path,
        typer.Option("--ledger-dir", help="Directory containing run ledger JSON files."),
    ] = RUN_LEDGER_DIR,
) -> None:
    """Show run metadata, logs, handoff, and workspace git status."""

    try:
        run = RunLedger(ledger_dir).read(run_id)
    except RunLedgerError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    details = _run_details(run)
    if json_output:
        typer.echo(_json(details))
        return
    typer.echo(_format_run_details(details))


@run_app.command("publish")
def run_publish(
    run_id: Annotated[str, typer.Argument(help="Succeeded run ID to publish.")],
    commit_message: Annotated[
        str | None,
        typer.Option("--commit-message", help="Commit message for workspace changes."),
    ] = None,
    title: Annotated[
        str | None,
        typer.Option("--title", help="Draft pull request title."),
    ] = None,
    ledger_dir: Annotated[
        Path,
        typer.Option("--ledger-dir", help="Directory containing run ledger JSON files."),
    ] = RUN_LEDGER_DIR,
) -> None:
    """Commit a succeeded run's workspace changes and open a draft PR."""

    try:
        run = RunLedger(ledger_dir).read(run_id)
        result = _publish_run(
            run,
            commit_message=commit_message,
            title=title,
        )
    except (RunLedgerError, PublishError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"branch: {result.branch}")
    typer.echo(f"commit: {result.commit_sha}")
    typer.echo(f"pull_request: {result.pr_url}")


@run_app.command("fail")
def run_fail(
    run_id: Annotated[str, typer.Argument(help="Run ID to mark failed.")],
    reason: Annotated[
        str,
        typer.Option("--reason", help="Reason to record on the failed run."),
    ] = "Marked failed manually",
    force: Annotated[
        bool,
        typer.Option("--force", help="Allow updating a terminal run."),
    ] = False,
    ledger_dir: Annotated[
        Path,
        typer.Option("--ledger-dir", help="Directory containing run ledger JSON files."),
    ] = RUN_LEDGER_DIR,
) -> None:
    """Mark a stale or abandoned run ledger entry as failed."""

    try:
        updated = _fail_run(RunLedger(ledger_dir), run_id, reason=reason, force=force)
    except (RunLedgerError, RunStateError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"{updated.run_id}: failed")
    typer.echo(f"error: {updated.error}")


@run_app.command("recover")
def run_recover(
    older_than_minutes: Annotated[
        int,
        typer.Option(
            "--older-than-minutes",
            help="Only recover active runs not updated within this many minutes.",
            min=1,
        ),
    ] = 60,
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Mark matching stale active runs failed."),
    ] = False,
    ledger_dir: Annotated[
        Path,
        typer.Option("--ledger-dir", help="Directory containing run ledger JSON files."),
    ] = RUN_LEDGER_DIR,
) -> None:
    """Find stale active run ledger entries and optionally mark them failed."""

    try:
        recovered = _recover_stale_runs(
            RunLedger(ledger_dir),
            older_than_minutes=older_than_minutes,
            apply=apply,
        )
    except RunLedgerError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if not recovered:
        typer.echo("No stale active runs.")
        return

    action = "marked failed" if apply else "would mark failed"
    for run in recovered:
        typer.echo(
            f"{run.run_id} {run.issue_identifier}: {action}; "
            f"status={run.status} updated_at={run.updated_at.isoformat()} "
            f"workspace={run.workspace_path}"
        )


@app.command("status")
def status(
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
    status_path: Annotated[
        Path,
        typer.Option("--status-path", help="Path to the latest status snapshot."),
    ] = STATUS_SNAPSHOT_PATH,
    ledger_dir: Annotated[
        Path,
        typer.Option("--ledger-dir", help="Directory containing run ledger JSON files."),
    ] = RUN_LEDGER_DIR,
) -> None:
    """Report active runs from the status snapshot or fall back to the run ledger."""

    snapshot = StatusSnapshotStore(status_path).read()
    if snapshot is not None:
        if json_output:
            typer.echo(_json({"source": "snapshot", "snapshot": snapshot}))
            return
        typer.echo(_format_snapshot(snapshot))
        return

    runs = RunLedger(ledger_dir).list()
    if json_output:
        typer.echo(_json({"source": "ledger", "runs": runs}))
        return
    typer.echo(_format_ledger(runs))


def main() -> None:
    """Run the Symphony command-line interface."""
    app()


def _json(payload: dict[str, object]) -> str:
    return json.dumps(payload, default=_json_default, indent=2, sort_keys=True)


def _json_default(value: object) -> object:
    if isinstance(value, StatusSnapshot | RunMetadata):
        return value.model_dump(mode="json")
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _check_json(check: RuntimeCheck) -> dict[str, str]:
    return {
        "name": check.name,
        "status": check.status,
        "message": check.message,
    }


def _format_checks(checks: list[RuntimeCheck]) -> str:
    return "\n".join(f"{check.status.upper():4} {check.name}: {check.message}" for check in checks)


class PublishError(RuntimeError):
    """Raised when a run workspace cannot be published."""


class RunStateError(RuntimeError):
    """Raised when a run ledger state transition is invalid."""


class CleanupError(RuntimeError):
    """Raised when a run workspace cannot be cleaned safely."""


@dataclass(frozen=True)
class PublishResult:
    branch: str
    commit_sha: str
    pr_url: str


@dataclass(frozen=True)
class CleanupResult:
    workspace_path: Path
    removed: bool
    method: str


_TERMINAL_RUN_STATUSES = {"succeeded", "failed", "cancelled"}
_ACTIVE_RUN_STATUSES = {"queued", "starting", "running", "waiting_for_permission"}


@run_app.command("cleanup")
def run_cleanup(
    run_id: Annotated[str, typer.Argument(help="Run ID whose workspace should be removed.")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Remove even if the workspace is dirty or not a git repo."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Report what would be removed without deleting it."),
    ] = False,
    ledger_dir: Annotated[
        Path,
        typer.Option("--ledger-dir", help="Directory containing run ledger JSON files."),
    ] = RUN_LEDGER_DIR,
) -> None:
    """Remove a terminal run's workspace after safety checks."""

    try:
        run = RunLedger(ledger_dir).read(run_id)
        result = _cleanup_run_workspace(run, force=force, dry_run=dry_run)
    except (RunLedgerError, CleanupError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"workspace: {result.workspace_path}")
    typer.echo(f"removed: {str(result.removed).lower()}")
    typer.echo(f"method: {result.method}")


def _recent_runs(runs: list[RunMetadata], *, limit: int) -> list[RunMetadata]:
    return sorted(runs, key=lambda run: run.updated_at, reverse=True)[:limit]


def _fail_run(
    ledger: RunLedger,
    run_id: str,
    *,
    reason: str,
    force: bool = False,
    now: datetime | None = None,
) -> RunMetadata:
    run = ledger.read(run_id)
    if run.status in {"succeeded", "failed", "cancelled"} and not force:
        raise RunStateError(f"Run is already terminal with status {run.status}")

    timestamp = now or _utc_now()
    updated = run.model_copy(
        update={
            "status": "failed",
            "updated_at": timestamp,
            "completed_at": timestamp,
            "error": reason,
        }
    )
    ledger.write(updated)
    return updated


def _recover_stale_runs(
    ledger: RunLedger,
    *,
    older_than_minutes: int,
    apply: bool = False,
    now: datetime | None = None,
) -> list[RunMetadata]:
    if older_than_minutes < 1:
        raise RunStateError("older_than_minutes must be at least 1")

    timestamp = now or _utc_now()
    stale_runs = [
        run
        for run in ledger.list()
        if run.status in _ACTIVE_RUN_STATUSES
        and (timestamp - run.updated_at).total_seconds() >= older_than_minutes * 60
    ]
    if not apply:
        return stale_runs

    recovered: list[RunMetadata] = []
    for run in stale_runs:
        reason = (
            "Recovered stale active run: "
            f"status {run.status} unchanged since {run.updated_at.isoformat()}"
        )
        updated = run.model_copy(
            update={
                "status": "failed",
                "updated_at": timestamp,
                "completed_at": timestamp,
                "error": reason,
            }
        )
        ledger.write(updated)
        recovered.append(updated)
    return recovered


def _cleanup_run_workspace(
    run: RunMetadata,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> CleanupResult:
    if run.status not in _TERMINAL_RUN_STATUSES:
        raise CleanupError(f"Run is not cleanable because status is {run.status}")
    if not run.workspace_path.exists():
        raise CleanupError(f"Workspace unavailable: {run.workspace_path}")
    if not run.workspace_path.is_dir():
        raise CleanupError(f"Workspace path is not a directory: {run.workspace_path}")

    git_status = _workspace_git_status(run.workspace_path)
    if isinstance(git_status, list):
        if git_status and not force:
            raise CleanupError(
                f"Workspace has uncommitted changes; use --force to remove: {run.workspace_path}"
            )
    elif not force:
        raise CleanupError(
            f"Unable to verify workspace is clean; use --force to remove: {git_status}"
        )

    method = _cleanup_method(run.workspace_path)
    if dry_run:
        return CleanupResult(workspace_path=run.workspace_path, removed=False, method=method)

    if method == "git worktree remove":
        _remove_git_worktree(run.workspace_path, force=force)
    else:
        shutil.rmtree(run.workspace_path)
    return CleanupResult(workspace_path=run.workspace_path, removed=True, method=method)


def _cleanup_method(workspace_path: Path) -> str:
    git_file = workspace_path / ".git"
    if git_file.is_file():
        return "git worktree remove"
    return "rmtree"


def _remove_git_worktree(workspace_path: Path, *, force: bool) -> None:
    try:
        common_dir = _command_stdout(
            ["git", "-C", workspace_path.as_posix(), "rev-parse", "--git-common-dir"],
            cwd=workspace_path,
            failure_message="Unable to find git worktree metadata",
        )
        command = ["git", "worktree", "remove"]
        if force:
            command.append("--force")
        command.append(workspace_path.as_posix())
        _run_command(command, cwd=Path(common_dir).resolve().parent)
    except PublishError as exc:
        raise CleanupError(str(exc)) from exc


def _run_details(run: RunMetadata) -> dict[str, object]:
    stdout_path = _metadata_path(run, "stdout_log_path")
    stderr_path = _metadata_path(run, "stderr_log_path")
    return {
        "run": run,
        "logs": {
            "stdout": stdout_path.as_posix() if stdout_path is not None else None,
            "stderr": stderr_path.as_posix() if stderr_path is not None else None,
        },
        "handoff": _read_handoff(stdout_path),
        "workspace_git_status": _workspace_git_status(run.workspace_path),
    }


def _format_run_details(details: dict[str, object]) -> str:
    run = details["run"]
    assert isinstance(run, RunMetadata)
    logs = cast(dict[str, str | None], details["logs"])
    handoff = details["handoff"]
    git_status = details["workspace_git_status"]

    lines = [
        f"run: {run.run_id}",
        f"issue: {run.issue_identifier}",
        f"status: {run.status}",
        f"workspace: {run.workspace_path}",
        f"started_at: {run.started_at.isoformat()}",
        f"updated_at: {run.updated_at.isoformat()}",
    ]
    if run.completed_at is not None:
        lines.append(f"completed_at: {run.completed_at.isoformat()}")
    if run.error:
        lines.append(f"error: {run.error}")
    lines.extend(
        [
            f"stdout: {logs.get('stdout') or '-'}",
            f"stderr: {logs.get('stderr') or '-'}",
        ]
    )

    lines.append("handoff:")
    if isinstance(handoff, dict):
        handoff_data = cast(dict[str, object], handoff)
        status = handoff_data.get("status", "-")
        summary = handoff_data.get("summary")
        lines.append(f"  status: {status}")
        if isinstance(summary, str) and summary:
            lines.append(f"  summary: {summary}")
        for key in ("artifacts", "validation", "errors"):
            value = handoff_data.get(key)
            if value:
                lines.append(f"  {key}: {json.dumps(value, sort_keys=True)}")
    else:
        lines.append(f"  {handoff}")

    lines.append("workspace_git_status:")
    if isinstance(git_status, list):
        status_lines = cast(list[str], git_status)
        if status_lines:
            lines.extend(f"  {line}" for line in status_lines)
        else:
            lines.append("  clean")
    else:
        lines.append(f"  {git_status}")
    return "\n".join(lines)


def _format_runs(runs: list[RunMetadata]) -> str:
    lines = [f"runs: {len(runs)}"]
    for run in runs:
        completed = run.completed_at.isoformat() if run.completed_at is not None else "-"
        lines.append(
            "  - "
            f"{run.run_id} {run.issue_identifier} status={run.status} "
            f"updated_at={run.updated_at.isoformat()} completed_at={completed}"
        )
        lines.append(f"    workspace={run.workspace_path}")
        if run.error:
            lines.append(f"    error={run.error}")
    return "\n".join(lines)


def _metadata_path(run: RunMetadata, key: str) -> Path | None:
    value = run.metadata.get(key)
    if not isinstance(value, str) or not value:
        return None
    return Path(value)


def _read_handoff(stdout_path: Path | None) -> dict[str, object] | str:
    if stdout_path is None:
        return "stdout log path not recorded"
    try:
        stdout = stdout_path.read_text(encoding="utf-8")
    except OSError:
        return "stdout log unavailable"
    try:
        return parse_structured_handoff(stdout).model_dump(mode="json")
    except ClaudeHeadlessRunnerError as exc:
        return str(exc)


def _workspace_git_status(workspace_path: Path) -> list[str] | str:
    if not workspace_path.exists():
        return "workspace unavailable"
    try:
        result = subprocess.run(
            ["git", "-C", workspace_path.as_posix(), "status", "--short"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unable to read git status: {exc}"
    if result.returncode != 0:
        return (result.stderr or result.stdout or "git status failed").strip()
    return [line for line in result.stdout.splitlines() if line]


def _publish_run(
    run: RunMetadata,
    *,
    commit_message: str | None = None,
    title: str | None = None,
) -> PublishResult:
    if run.status != "succeeded":
        raise PublishError(f"Run is not publishable because status is {run.status}")
    if not run.workspace_path.exists():
        raise PublishError(f"Workspace unavailable: {run.workspace_path}")

    status = _git_status_porcelain(run.workspace_path)
    if not status:
        raise PublishError(f"Workspace has no changes to publish: {run.workspace_path}")

    branch = _command_stdout(
        ["git", "branch", "--show-current"],
        cwd=run.workspace_path,
        failure_message="Unable to determine workspace branch",
    )
    if not branch:
        raise PublishError("Workspace is not on a named branch")

    message = commit_message or f"{run.issue_identifier}: publish completed run"
    pr_title = title or f"{run.issue_identifier}: publish completed run"
    body = _publish_pr_body(run, status)

    _run_command(["git", "add", "-A"], cwd=run.workspace_path)
    _run_command(["git", "commit", "-m", message], cwd=run.workspace_path)
    commit_sha = _command_stdout(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=run.workspace_path,
        failure_message="Unable to read published commit",
    )
    _run_command(["git", "push", "-u", "origin", "HEAD"], cwd=run.workspace_path)
    pr_url = _ensure_draft_pr(run.workspace_path, pr_title, body)
    return PublishResult(branch=branch, commit_sha=commit_sha, pr_url=pr_url)


def _git_status_porcelain(workspace_path: Path) -> list[str]:
    result = _run_command(["git", "status", "--porcelain"], cwd=workspace_path)
    return [line for line in result.stdout.splitlines() if line]


def _ensure_draft_pr(workspace_path: Path, title: str, body: str) -> str:
    existing = subprocess.run(
        ["gh", "pr", "view", "--json", "url", "-q", ".url"],
        cwd=workspace_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if existing.returncode == 0 and existing.stdout.strip():
        return existing.stdout.strip()

    return _command_stdout(
        ["gh", "pr", "create", "--draft", "--title", title, "--body", body],
        cwd=workspace_path,
        failure_message="Unable to create draft pull request",
    )


def _publish_pr_body(run: RunMetadata, status: list[str]) -> str:
    handoff = _read_handoff(_metadata_path(run, "stdout_log_path"))
    summary = handoff.get("summary") if isinstance(handoff, dict) else None
    summary_text = summary if isinstance(summary, str) and summary else "Completed Symphony run."
    status_text = "\n".join(f"- `{line}`" for line in status)
    return f"""#### Context

Published from Symphony run `{run.run_id}` for Beads issue `{run.issue_identifier}`.

#### TL;DR

*{summary_text[:120]}*

#### Summary

- Commit workspace changes produced by the completed run
- Preserve the run handoff and workspace branch for review
- Publish as a draft PR for human inspection

#### Workspace Changes

{status_text}

#### Test Plan

- [ ] `make -C elixir all`
- [ ] Review the run handoff and workspace diff
"""


def _command_stdout(command: list[str], *, cwd: Path, failure_message: str) -> str:
    return _run_command(command, cwd=cwd, failure_message=failure_message).stdout.strip()


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    failure_message: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        message = failure_message or f"Command failed: {' '.join(command)}"
        raise PublishError(f"{message}: {exc}") from exc
    if result.returncode != 0:
        message = failure_message or f"Command failed: {' '.join(command)}"
        detail = (result.stderr or result.stdout).strip()
        raise PublishError(f"{message}: {detail}")
    return result


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _format_snapshot(snapshot: StatusSnapshot) -> str:
    lines = [
        "source: snapshot",
        f"generated_at: {snapshot.generated_at.isoformat()}",
        f"active_runs: {len(snapshot.active_runs)}",
    ]
    for run in snapshot.active_runs:
        lines.append(
            "  - "
            f"{run.issue_identifier} status={run.status} "
            f"attempt={run.attempt or 1} workspace={run.workspace_path}"
        )
        if run.error:
            lines.append(f"    error={run.error}")

    lines.append(f"retry_queue: {len(snapshot.retry_queue)}")
    for retry in snapshot.retry_queue:
        lines.append(f"  - {retry.identifier} attempt={retry.attempt} due_at_ms={retry.due_at_ms}")
        if retry.error:
            lines.append(f"    error={retry.error}")

    return "\n".join(lines)


def _format_ledger(runs: list[RunMetadata]) -> str:
    lines = ["source: ledger", f"runs: {len(runs)}"]
    for run in runs:
        completed = run.completed_at.isoformat() if run.completed_at is not None else "-"
        lines.append(
            "  - "
            f"{run.run_id} {run.issue_identifier} status={run.status} "
            f"updated_at={run.updated_at.isoformat()} completed_at={completed} "
            f"workspace={run.workspace_path}"
        )
        if run.error:
            lines.append(f"    error={run.error}")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
