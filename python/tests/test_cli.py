import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from symphony.cli import app
from symphony.log_events import StatusSnapshotStore
from symphony.models import Issue, RunAttempt, RunMetadata, StatusSnapshot
from symphony.orchestrator import OrchestratorCycleResult
from symphony.run_ledger import RunLedger
from symphony.runtime import RuntimeCheck


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


def test_daemon_reports_bounded_cycles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workflow = tmp_path / "WORKFLOW.md"
    workflow.write_text("---\n---\n\nDo work.\n", encoding="utf-8")

    async def fake_daemon(
        workflow_path: Path,
        *,
        cycles: int | None,
        on_cycle: Callable[[int, OrchestratorCycleResult | None], None],
    ) -> object:
        assert workflow_path == workflow
        assert cycles == 2
        on_cycle(
            1,
            OrchestratorCycleResult(
                issue=Issue(id="issue-1", identifier="SYMP-1", title="Do work", state="open"),
                run_id="run-1",
                status="succeeded",
            ),
        )
        on_cycle(2, None)
        return object()

    monkeypatch.setattr("symphony.cli.run_daemon_from_workflow", fake_daemon)
    runner = CliRunner()

    result = runner.invoke(app, ["daemon", "--workflow", str(workflow), "--cycles", "2"])

    assert result.exit_code == 0
    assert "cycle 1: SYMP-1: succeeded (run-1)" in result.output
    assert "cycle 2: no ready issues" in result.output


def test_doctor_reports_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workflow = tmp_path / "WORKFLOW.md"
    workflow.write_text("---\n---\n\nDo work.\n", encoding="utf-8")

    async def fake_check_workflow(workflow_path: Path) -> list[RuntimeCheck]:
        assert workflow_path == workflow
        return [
            RuntimeCheck("workflow", "pass", "loaded"),
            RuntimeCheck("environment", "warn", "PATH is not in environment.allow"),
        ]

    monkeypatch.setattr("symphony.cli.check_workflow", fake_check_workflow)
    runner = CliRunner()

    result = runner.invoke(app, ["doctor", "--workflow", str(workflow)])

    assert result.exit_code == 0
    assert "PASS workflow: loaded" in result.output
    assert "WARN environment: PATH is not in environment.allow" in result.output


def test_doctor_exits_nonzero_on_failed_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = tmp_path / "WORKFLOW.md"
    workflow.write_text("---\n---\n\nDo work.\n", encoding="utf-8")

    async def fake_check_workflow(_workflow_path: Path) -> list[RuntimeCheck]:
        return [RuntimeCheck("tracker", "fail", "not authenticated")]

    monkeypatch.setattr("symphony.cli.check_workflow", fake_check_workflow)
    runner = CliRunner()

    result = runner.invoke(app, ["doctor", "--workflow", str(workflow)])

    assert result.exit_code == 1
    assert "FAIL tracker: not authenticated" in result.output


def test_doctor_json_reports_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workflow = tmp_path / "WORKFLOW.md"
    workflow.write_text("---\n---\n\nDo work.\n", encoding="utf-8")

    async def fake_check_workflow(_workflow_path: Path) -> list[RuntimeCheck]:
        return [RuntimeCheck("workflow", "pass", "loaded")]

    monkeypatch.setattr("symphony.cli.check_workflow", fake_check_workflow)
    runner = CliRunner()

    result = runner.invoke(app, ["doctor", "--workflow", str(workflow), "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "checks": [{"message": "loaded", "name": "workflow", "status": "pass"}]
    }


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


def test_run_show_reports_handoff_logs_and_workspace_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    stdout_path = tmp_path / "log" / "runs" / "run-1" / "stdout.log"
    stderr_path = tmp_path / "log" / "runs" / "run-1" / "stderr.log"
    stdout_path.parent.mkdir(parents=True)
    stdout_path.write_text(
        "\n".join(
            [
                "SYMPHONY_HANDOFF_START",
                '{"status":"succeeded","summary":"implemented","artifacts":["README.md"],'
                '"validation":["pytest"],"errors":[]}',
                "SYMPHONY_HANDOFF_END",
            ]
        ),
        encoding="utf-8",
    )
    stderr_path.write_text("", encoding="utf-8")
    RunLedger(ledger_dir).write(
        _metadata(tmp_path, "run-1").model_copy(
            update={
                "status": "succeeded",
                "completed_at": _dt(12, 1),
                "metadata": {
                    "stdout_log_path": stdout_path.as_posix(),
                    "stderr_log_path": stderr_path.as_posix(),
                },
            }
        )
    )

    def fake_workspace_git_status(_workspace: Path) -> list[str]:
        return [" M README.md"]

    monkeypatch.setattr("symphony.cli._workspace_git_status", fake_workspace_git_status)
    runner = CliRunner()

    result = runner.invoke(app, ["run", "show", "run-1", "--ledger-dir", str(ledger_dir)])

    assert result.exit_code == 0
    assert "run: run-1" in result.output
    assert f"stdout: {stdout_path}" in result.output
    assert "summary: implemented" in result.output
    assert 'artifacts: ["README.md"]' in result.output
    assert " M README.md" in result.output


def test_run_show_json_reports_handoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    stdout_path = tmp_path / "stdout.log"
    stdout_path.write_text(
        'SYMPHONY_HANDOFF_START\n{"status":"succeeded","summary":"done"}\nSYMPHONY_HANDOFF_END\n',
        encoding="utf-8",
    )
    RunLedger(ledger_dir).write(
        _metadata(tmp_path, "run-1").model_copy(
            update={"metadata": {"stdout_log_path": stdout_path.as_posix()}}
        )
    )

    def fake_workspace_git_status(_workspace: Path) -> list[str]:
        return []

    monkeypatch.setattr("symphony.cli._workspace_git_status", fake_workspace_git_status)
    runner = CliRunner()

    result = runner.invoke(app, ["run", "show", "run-1", "--json", "--ledger-dir", str(ledger_dir)])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["run"]["run_id"] == "run-1"
    assert payload["handoff"]["summary"] == "done"
    assert payload["workspace_git_status"] == []


def test_run_publish_commits_pushes_and_creates_draft_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    workspace = tmp_path / "workspaces" / "symphony-1"
    workspace.mkdir(parents=True)
    stdout_path = tmp_path / "stdout.log"
    stdout_path.write_text(
        'SYMPHONY_HANDOFF_START\n{"status":"succeeded","summary":"implemented"}\n'
        "SYMPHONY_HANDOFF_END\n",
        encoding="utf-8",
    )
    RunLedger(ledger_dir).write(
        _metadata(tmp_path, "run-1").model_copy(
            update={
                "status": "succeeded",
                "completed_at": _dt(12, 1),
                "metadata": {"stdout_log_path": stdout_path.as_posix()},
            }
        )
    )
    commands: list[list[str]] = []

    def fake_run_command(
        command: list[str], *, cwd: Path, failure_message: str | None = None
    ) -> object:
        del failure_message
        assert cwd == workspace
        commands.append(command)
        stdout = ""
        if command == ["git", "status", "--porcelain"]:
            stdout = " M README.md\n"
        elif command == ["git", "branch", "--show-current"]:
            stdout = "symphony-workspace-symphony-1\n"
        elif command == ["git", "rev-parse", "--short", "HEAD"]:
            stdout = "abc1234\n"
        return _CommandResult(stdout=stdout)

    monkeypatch.setattr("symphony.cli._run_command", fake_run_command)

    def fake_ensure_draft_pr(_workspace: Path, _title: str, _body: str) -> str:
        return "https://github.com/example/repo/pull/1"

    monkeypatch.setattr("symphony.cli._ensure_draft_pr", fake_ensure_draft_pr)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            "publish",
            "run-1",
            "--ledger-dir",
            str(ledger_dir),
            "--commit-message",
            "Publish run",
            "--title",
            "Publish run PR",
        ],
    )

    assert result.exit_code == 0
    assert "branch: symphony-workspace-symphony-1" in result.output
    assert "commit: abc1234" in result.output
    assert "pull_request: https://github.com/example/repo/pull/1" in result.output
    assert commands == [
        ["git", "status", "--porcelain"],
        ["git", "branch", "--show-current"],
        ["git", "add", "-A"],
        ["git", "commit", "-m", "Publish run"],
        ["git", "rev-parse", "--short", "HEAD"],
        ["git", "push", "-u", "origin", "HEAD"],
    ]


def test_run_publish_rejects_non_succeeded_run(tmp_path: Path) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    RunLedger(ledger_dir).write(_metadata(tmp_path, "run-1"))
    runner = CliRunner()

    result = runner.invoke(app, ["run", "publish", "run-1", "--ledger-dir", str(ledger_dir)])

    assert result.exit_code == 1
    assert "Run is not publishable because status is running" in result.output


def test_run_cleanup_removes_clean_terminal_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    workspace = tmp_path / "workspaces" / "symphony-1"
    workspace.mkdir(parents=True)
    (workspace / "output.txt").write_text("done\n", encoding="utf-8")
    RunLedger(ledger_dir).write(
        _metadata(tmp_path, "run-1").model_copy(
            update={"status": "succeeded", "completed_at": _dt(12, 1)}
        )
    )

    def fake_workspace_git_status(_workspace: Path) -> list[str]:
        return []

    monkeypatch.setattr("symphony.cli._workspace_git_status", fake_workspace_git_status)
    runner = CliRunner()

    result = runner.invoke(app, ["run", "cleanup", "run-1", "--ledger-dir", str(ledger_dir)])

    assert result.exit_code == 0
    assert f"workspace: {workspace}" in result.output
    assert "removed: true" in result.output
    assert "method: rmtree" in result.output
    assert not workspace.exists()


def test_run_cleanup_dry_run_keeps_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    workspace = tmp_path / "workspaces" / "symphony-1"
    workspace.mkdir(parents=True)
    RunLedger(ledger_dir).write(
        _metadata(tmp_path, "run-1").model_copy(
            update={"status": "failed", "completed_at": _dt(12, 1)}
        )
    )

    def fake_workspace_git_status(_workspace: Path) -> list[str]:
        return []

    monkeypatch.setattr("symphony.cli._workspace_git_status", fake_workspace_git_status)
    runner = CliRunner()

    result = runner.invoke(
        app, ["run", "cleanup", "run-1", "--dry-run", "--ledger-dir", str(ledger_dir)]
    )

    assert result.exit_code == 0
    assert "removed: false" in result.output
    assert workspace.exists()


def test_run_cleanup_rejects_non_terminal_run(tmp_path: Path) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    workspace = tmp_path / "workspaces" / "symphony-1"
    workspace.mkdir(parents=True)
    RunLedger(ledger_dir).write(_metadata(tmp_path, "run-1"))
    runner = CliRunner()

    result = runner.invoke(app, ["run", "cleanup", "run-1", "--ledger-dir", str(ledger_dir)])

    assert result.exit_code == 1
    assert "Run is not cleanable because status is running" in result.output
    assert workspace.exists()


def test_run_cleanup_rejects_dirty_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    workspace = tmp_path / "workspaces" / "symphony-1"
    workspace.mkdir(parents=True)
    RunLedger(ledger_dir).write(
        _metadata(tmp_path, "run-1").model_copy(
            update={"status": "succeeded", "completed_at": _dt(12, 1)}
        )
    )

    def fake_workspace_git_status(_workspace: Path) -> list[str]:
        return [" M output.txt"]

    monkeypatch.setattr("symphony.cli._workspace_git_status", fake_workspace_git_status)
    runner = CliRunner()

    result = runner.invoke(app, ["run", "cleanup", "run-1", "--ledger-dir", str(ledger_dir)])

    assert result.exit_code == 1
    assert "Workspace has uncommitted changes" in result.output
    assert workspace.exists()


def test_run_cleanup_uses_git_worktree_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    workspace = tmp_path / "workspaces" / "symphony-1"
    workspace.mkdir(parents=True)
    (workspace / ".git").write_text("gitdir: /repo/.git/worktrees/symphony-1\n", encoding="utf-8")
    RunLedger(ledger_dir).write(
        _metadata(tmp_path, "run-1").model_copy(
            update={"status": "succeeded", "completed_at": _dt(12, 1)}
        )
    )
    commands: list[tuple[list[str], Path]] = []

    def fake_workspace_git_status(_workspace: Path) -> list[str]:
        return []

    def fake_run_command(
        command: list[str], *, cwd: Path, failure_message: str | None = None
    ) -> object:
        del failure_message
        commands.append((command, cwd))
        if command == ["git", "-C", workspace.as_posix(), "status", "--short"]:
            return _CommandResult(stdout="")
        if command == [
            "git",
            "-C",
            workspace.as_posix(),
            "rev-parse",
            "--git-common-dir",
        ]:
            return _CommandResult(stdout=(tmp_path / "repo" / ".git").as_posix() + "\n")
        if command == ["git", "worktree", "remove", workspace.as_posix()]:
            return _CommandResult(stdout="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("symphony.cli._workspace_git_status", fake_workspace_git_status)
    monkeypatch.setattr("symphony.cli._run_command", fake_run_command)
    runner = CliRunner()

    result = runner.invoke(app, ["run", "cleanup", "run-1", "--ledger-dir", str(ledger_dir)])

    assert result.exit_code == 0
    assert "method: git worktree remove" in result.output
    assert commands[-1] == (
        ["git", "worktree", "remove", workspace.as_posix()],
        tmp_path / "repo",
    )


def test_run_fail_marks_active_run_failed(tmp_path: Path) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    RunLedger(ledger_dir).write(_metadata(tmp_path, "run-1"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            "fail",
            "run-1",
            "--reason",
            "stale process",
            "--ledger-dir",
            str(ledger_dir),
        ],
    )

    assert result.exit_code == 0
    assert "run-1: failed" in result.output
    updated = RunLedger(ledger_dir).read("run-1")
    assert updated.status == "failed"
    assert updated.error == "stale process"
    assert updated.completed_at is not None


def test_run_fail_rejects_terminal_run_without_force(tmp_path: Path) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    RunLedger(ledger_dir).write(
        _metadata(tmp_path, "run-1").model_copy(
            update={"status": "succeeded", "completed_at": _dt(12, 1)}
        )
    )
    runner = CliRunner()

    result = runner.invoke(app, ["run", "fail", "run-1", "--ledger-dir", str(ledger_dir)])

    assert result.exit_code == 1
    assert "Run is already terminal with status succeeded" in result.output


def test_run_recover_reports_stale_active_runs_without_applying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    stale = _metadata(tmp_path, "run-stale").model_copy(update={"updated_at": _dt(10, 0)})
    fresh = _metadata(tmp_path, "run-fresh").model_copy(update={"updated_at": _dt(11, 45)})
    terminal = _metadata(tmp_path, "run-done").model_copy(
        update={"status": "succeeded", "updated_at": _dt(9, 0), "completed_at": _dt(9, 0)}
    )
    ledger = RunLedger(ledger_dir)
    ledger.write(stale)
    ledger.write(fresh)
    ledger.write(terminal)
    monkeypatch.setattr("symphony.cli._utc_now", lambda: _dt(12, 0))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            "recover",
            "--older-than-minutes",
            "60",
            "--ledger-dir",
            str(ledger_dir),
        ],
    )

    assert result.exit_code == 0
    assert "run-stale symphony-1: would mark failed" in result.output
    assert "run-fresh" not in result.output
    assert "run-done" not in result.output
    assert ledger.read("run-stale").status == "running"


def test_run_recover_marks_stale_active_runs_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    RunLedger(ledger_dir).write(
        _metadata(tmp_path, "run-stale").model_copy(update={"updated_at": _dt(10, 0)})
    )
    monkeypatch.setattr("symphony.cli._utc_now", lambda: _dt(12, 0))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            "recover",
            "--older-than-minutes",
            "60",
            "--apply",
            "--ledger-dir",
            str(ledger_dir),
        ],
    )

    assert result.exit_code == 0
    assert "run-stale symphony-1: marked failed" in result.output
    updated = RunLedger(ledger_dir).read("run-stale")
    assert updated.status == "failed"
    assert updated.completed_at is not None
    assert updated.error is not None
    assert "Recovered stale active run" in updated.error


def test_run_recover_reports_no_stale_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger_dir = tmp_path / ".symphony" / "runs"
    RunLedger(ledger_dir).write(
        _metadata(tmp_path, "run-fresh").model_copy(update={"updated_at": _dt(11, 45)})
    )
    monkeypatch.setattr("symphony.cli._utc_now", lambda: _dt(12, 0))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            "recover",
            "--older-than-minutes",
            "60",
            "--ledger-dir",
            str(ledger_dir),
        ],
    )

    assert result.exit_code == 0
    assert "No stale active runs." in result.output


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


class _CommandResult:
    def __init__(self, *, stdout: str) -> None:
        self.stdout = stdout
