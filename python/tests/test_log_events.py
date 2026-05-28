from datetime import UTC, datetime
from pathlib import Path

import pytest

from symphony.log_events import EventLogError, EventLogger, StatusSnapshotStore
from symphony.models import RunAttempt, RunEvent, StatusSnapshot
from symphony.runtime_paths import (
    EVENT_LOG_PATH,
    STATUS_SNAPSHOT_PATH,
    stderr_log_path,
    stdout_log_path,
)


def event(tmp_path: Path, run_id: str = "run-1") -> RunEvent:
    return RunEvent(
        provider="fake",
        mode="fake",
        tracker_kind="beads",
        issue_id="issue-1",
        issue_identifier="symphony-1",
        run_id=run_id,
        workspace_path=tmp_path / "workspace" / "symphony-1",
        event_type="run_started",
        message="started",
        metadata={"attempt": None},
        timestamp=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
    )


def test_event_logger_appends_jsonl_events(tmp_path: Path) -> None:
    logger = EventLogger(tmp_path / "log" / "events.jsonl")

    logger.append(event(tmp_path, "run-1"))
    logger.append(event(tmp_path, "run-2").model_copy(update={"event_type": "run_succeeded"}))

    lines = logger.path.read_text(encoding="utf-8").splitlines()
    loaded = logger.read_all()

    assert len(lines) == 2
    assert [loaded_event.run_id for loaded_event in loaded] == ["run-1", "run-2"]
    assert loaded[1].event_type == "run_succeeded"


def test_event_logger_returns_empty_list_for_missing_log(tmp_path: Path) -> None:
    assert EventLogger(tmp_path / "missing.jsonl").read_all() == []


def test_event_logger_reports_invalid_jsonl_line(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("{\n", encoding="utf-8")

    with pytest.raises(EventLogError, match="Invalid event JSON"):
        EventLogger(path).read_all()


def test_status_snapshot_store_writes_and_reads_snapshot(tmp_path: Path) -> None:
    now = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)
    snapshot = StatusSnapshot(
        generated_at=now,
        active_runs=(
            RunAttempt(
                issue_id="issue-1",
                issue_identifier="symphony-1",
                workspace_path=tmp_path / "workspace" / "symphony-1",
                started_at=now,
                status="running",
            ),
        ),
    )
    store = StatusSnapshotStore(tmp_path / "log" / "status.json")

    path = store.write(snapshot)

    assert path == tmp_path / "log" / "status.json"
    assert store.read() == snapshot


def test_default_runtime_paths_are_defined_under_python_project() -> None:
    assert EVENT_LOG_PATH.name == "events.jsonl"
    assert STATUS_SNAPSHOT_PATH.name == "status.json"
    assert stdout_log_path("run-1").as_posix().endswith("log/runs/run-1/stdout.log")
    assert stderr_log_path("run-1").as_posix().endswith("log/runs/run-1/stderr.log")
