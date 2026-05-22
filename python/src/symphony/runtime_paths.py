"""Default paths for durable local Symphony runtime state."""

from __future__ import annotations

from pathlib import Path

PYTHON_PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_STATE_DIR = PYTHON_PROJECT_ROOT / ".symphony"
RUN_LEDGER_DIR = RUNTIME_STATE_DIR / "runs"
LOG_DIR = PYTHON_PROJECT_ROOT / "log"
EVENT_LOG_PATH = LOG_DIR / "events.jsonl"
STATUS_SNAPSHOT_PATH = LOG_DIR / "status.json"
RUN_LOG_DIR = LOG_DIR / "runs"


def stdout_log_path(run_id: str) -> Path:
    """Return the default stdout log path for a run."""

    return RUN_LOG_DIR / run_id / "stdout.log"


def stderr_log_path(run_id: str) -> Path:
    """Return the default stderr log path for a run."""

    return RUN_LOG_DIR / run_id / "stderr.log"
