"""JSONL event logging for Symphony runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from symphony.models import RunEvent, StatusSnapshot
from symphony.runtime_paths import EVENT_LOG_PATH, STATUS_SNAPSHOT_PATH


class EventLogError(RuntimeError):
    """Raised when a runtime log cannot be read or written."""


class EventLogger:
    """Append and read normalized run events as newline-delimited JSON."""

    def __init__(self, path: Path = EVENT_LOG_PATH) -> None:
        self.path = path

    def append(self, event: RunEvent) -> None:
        """Append one event to the JSONL log."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(event.model_dump_json())
            stream.write("\n")

    def read_all(self) -> list[RunEvent]:
        """Read every event currently in the JSONL log."""

        if not self.path.exists():
            return []

        events: list[RunEvent] = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                events.append(RunEvent.model_validate_json(line))
            except ValidationError as exc:
                raise EventLogError(f"Invalid event JSON at {self.path}:{line_number}") from exc
        return events


class StatusSnapshotStore:
    """Persist the latest operator-facing status snapshot."""

    def __init__(self, path: Path = STATUS_SNAPSHOT_PATH) -> None:
        self.path = path

    def write(self, snapshot: StatusSnapshot) -> Path:
        """Write the current status snapshot and return the path."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(snapshot.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return self.path

    def read(self) -> StatusSnapshot | None:
        """Read the latest status snapshot if one exists."""

        if not self.path.exists():
            return None
        try:
            data = cast(dict[str, Any], json.loads(self.path.read_text(encoding="utf-8")))
            return StatusSnapshot.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise EventLogError(f"Invalid status snapshot: {self.path}") from exc
