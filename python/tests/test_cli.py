import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from symphony.cli import app
from symphony.log_events import StatusSnapshotStore
from symphony.models import Issue, RunAttempt, RunMetadata, StatusSnapshot
from symphony.orchestrator import OrchestratorCycleResult
from symphony.run_ledger import RunLedger


def test_cli_help() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Python implementation of Symphony" in result.output


def test_run_once_reports_no_ready_issues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workflow = tmp_path / "WORKFLOW.md"
    workflow.write_text("---\n---\n\nDo work.\n", encoding="utf-8")

    async def fake_run_once(workflow_path: Path) -> None:
        assert workflow_path == workflow
        return None

    monkeypatch.setattr("symphony.cli.run_once_from_workflow", fake_run_once)
    runner = CliRunner()

    result = runner.invoke(app, ["run-once", "--workflow", str(workflow)])

    assert result.exit_code == 0
    assert "No ready issues." in result.output


def test_run_once_reports_dispatched_issue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workflow = tmp_path / "WORKFLOW.md"
    workflow.write_text("---\n---\n\nDo work.\n", encoding="utf-8")

    async def fake_run_once(workflow_path: Path) -> OrchestratorCycleResult:
        assert workflow_path == workflow
        return OrchestratorCycleResult(
            issue=Issue(id="issue-1", identifier="SYMP-1", title="Do work", state="open"),
            run_id="run-1",
            status="succeeded",
        )

    monkeypatch.setattr("symphony.cli.run_once_from_workflow", fake_run_once)
    runner = CliRunner()

    result = runner.invoke(app, ["run-once", "--workflow", str(workflow)])

    assert result.exit_code == 0
    assert "SYMP-1: succeeded (run-1)" in result.output


def test_runs_lists_recent_runs_newest_first(tmp_path: Path) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    RunLedger(ledger_dir).write(
        _metadata(tmp_path, "run-old").model_copy(
            update={"issue_identifier": "symphony-old", "updated_at": _dt(12, 0)}
        )
    )
    RunLedger(ledger_dir).write(
        _metadata(tmp_path, "run-new").model_copy(
            update={
                "issue_identifier": "symphony-new",
                "status": "succeeded",
                "updated_at": _dt(12, 2),
                "completed_at": _dt(12, 2),
            }
        )
    )
    runner = CliRunner()

    result = runner.invoke(app, ["runs", "--ledger-dir", str(ledger_dir)])

    assert result.exit_code == 0
    assert result.output.index("run-new symphony-new") < result.output.index("run-old symphony-old")
    assert "status=succeeded" in result.output
    assert f"workspace={tmp_path / 'workspaces' / 'symphony-1'}" in result.output


def test_runs_json_honors_limit(tmp_path: Path) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    RunLedger(ledger_dir).write(_metadata(tmp_path, "run-old"))
    RunLedger(ledger_dir).write(
        _metadata(tmp_path, "run-new").model_copy(update={"updated_at": _dt(12, 2)})
    )
    runner = CliRunner()

    result = runner.invoke(app, ["runs", "--json", "--limit", "1", "--ledger-dir", str(ledger_dir)])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [run["run_id"] for run in payload["runs"]] == ["run-new"]


def test_status_reads_snapshot_before_ledger(tmp_path: Path) -> None:
    now = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)
    status_path = tmp_path / "log" / "status.json"
    ledger_dir = tmp_path / ".symphony" / "runs"
    StatusSnapshotStore(status_path).write(
        StatusSnapshot(
            generated_at=now,
            active_runs=(
                RunAttempt(
                    issue_id="issue-1",
                    issue_identifier="symphony-1",
                    workspace_path=tmp_path / "workspaces" / "symphony-1",
                    started_at=now,
                    status="running",
                ),
            ),
        )
    )
    RunLedger(ledger_dir).write(_metadata(tmp_path, "run-1"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "status",
            "--status-path",
            str(status_path),
            "--ledger-dir",
            str(ledger_dir),
        ],
    )

    assert result.exit_code == 0
    assert "source: snapshot" in result.output
    assert "active_runs: 1" in result.output
    assert "symphony-1 status=running" in result.output
    assert "\nruns:" not in result.output


def test_status_falls_back_to_run_ledger(tmp_path: Path) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    RunLedger(ledger_dir).write(
        _metadata(tmp_path, "run-1").model_copy(update={"status": "failed", "error": "boom"})
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "status",
            "--status-path",
            str(tmp_path / "missing-status.json"),
            "--ledger-dir",
            str(ledger_dir),
        ],
    )

    assert result.exit_code == 0
    assert "source: ledger" in result.output
    assert "runs: 1" in result.output
    assert "run-1 symphony-1 status=failed" in result.output
    assert "error=boom" in result.output


def test_status_json_reports_snapshot(tmp_path: Path) -> None:
    now = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)
    status_path = tmp_path / "log" / "status.json"
    StatusSnapshotStore(status_path).write(StatusSnapshot(generated_at=now))
    runner = CliRunner()

    result = runner.invoke(app, ["status", "--json", "--status-path", str(status_path)])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["source"] == "snapshot"
    assert payload["snapshot"]["generated_at"] == "2026-05-19T12:00:00Z"
    assert payload["snapshot"]["active_runs"] == []


def test_status_json_reports_ledger_fallback(tmp_path: Path) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    RunLedger(ledger_dir).write(_metadata(tmp_path, "run-1"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "status",
            "--json",
            "--status-path",
            str(tmp_path / "missing-status.json"),
            "--ledger-dir",
            str(ledger_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["source"] == "ledger"
    assert payload["runs"][0]["run_id"] == "run-1"
    assert payload["runs"][0]["workspace_path"].endswith("/workspaces/symphony-1")


def _metadata(tmp_path: Path, run_id: str) -> RunMetadata:
    return RunMetadata(
        provider="fake",
        mode="fake",
        tracker_kind="beads",
        issue_id="issue-1",
        issue_identifier="symphony-1",
        run_id=run_id,
        workspace_path=tmp_path / "workspaces" / "symphony-1",
        status="running",
        started_at=_dt(12, 0),
        updated_at=_dt(12, 0),
    )


def _dt(hour: int, minute: int) -> datetime:
    return datetime(2026, 5, 19, hour, minute, tzinfo=UTC)
