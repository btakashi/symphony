"""Command-line entry points for Symphony."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Annotated, cast

import typer

from symphony.log_events import StatusSnapshotStore
from symphony.models import RunMetadata, StatusSnapshot
from symphony.run_ledger import RunLedger, RunLedgerError
from symphony.runner.claude_headless import ClaudeHeadlessRunnerError, parse_structured_handoff
from symphony.runtime import find_workflow_path, run_once_from_workflow
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


def _recent_runs(runs: list[RunMetadata], *, limit: int) -> list[RunMetadata]:
    return sorted(runs, key=lambda run: run.updated_at, reverse=True)[:limit]


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
