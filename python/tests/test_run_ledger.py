from datetime import UTC, datetime
from pathlib import Path

import pytest

from symphony.models import RunMetadata
from symphony.run_ledger import RunLedger, RunLedgerError


def metadata(tmp_path: Path) -> RunMetadata:
    now = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)
    return RunMetadata(
        provider="fake",
        mode="fake",
        tracker_kind="beads",
        issue_id="issue-1",
        issue_identifier="symphony-1",
        run_id="run-1",
        attempt=None,
        workspace_path=tmp_path / "workspaces" / "symphony-1",
        status="running",
        started_at=now,
        updated_at=now,
        metadata={"pid": 123, "stdout_log_path": "log/runs/run-1/stdout.log"},
    )


def test_run_ledger_writes_and_reads_metadata_json(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / ".symphony" / "runs")
    original = metadata(tmp_path)

    path = ledger.write(original)
    loaded = ledger.read("run-1")

    assert path == tmp_path / ".symphony" / "runs" / "run-1.json"
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert loaded == original


def test_run_ledger_lists_metadata_in_path_order(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / "runs")
    run_b = metadata(tmp_path).model_copy(update={"run_id": "run-b"})
    run_a = metadata(tmp_path).model_copy(update={"run_id": "run-a"})

    ledger.write(run_b)
    ledger.write(run_a)

    assert [run.run_id for run in ledger.list()] == ["run-a", "run-b"]


@pytest.mark.parametrize("run_id", ["", "../run-1", "nested/run-1", "nested\\run-1"])
def test_run_ledger_rejects_run_ids_that_escape_the_ledger(tmp_path: Path, run_id: str) -> None:
    ledger = RunLedger(tmp_path / "runs")

    with pytest.raises(RunLedgerError, match="Invalid run_id"):
        ledger.path_for(run_id)
