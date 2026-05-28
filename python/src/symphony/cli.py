"""Command-line entry points for Symphony."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from symphony.log_events import StatusSnapshotStore
from symphony.models import RunMetadata, StatusSnapshot
from symphony.run_ledger import RunLedger
from symphony.runtime import find_workflow_path, run_once_from_workflow
from symphony.runtime_paths import RUN_LEDGER_DIR, STATUS_SNAPSHOT_PATH

app = typer.Typer(help="Python implementation of Symphony.")


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
