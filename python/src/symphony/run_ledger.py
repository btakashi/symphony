"""JSON-backed run metadata ledger."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from symphony.models import RunMetadata
from symphony.runtime_paths import RUN_LEDGER_DIR


class RunLedgerError(RuntimeError):
    """Raised when run metadata cannot be read or written."""


class RunLedger:
    """Persist one JSON metadata document per runner attempt."""

    def __init__(self, root: Path = RUN_LEDGER_DIR) -> None:
        self.root = root

    def path_for(self, run_id: str) -> Path:
        """Return the metadata path for a run ID."""

        if not run_id or "/" in run_id or "\\" in run_id:
            raise RunLedgerError(f"Invalid run_id for ledger path: {run_id!r}")
        return self.root / f"{run_id}.json"

    def write(self, metadata: RunMetadata) -> Path:
        """Write metadata for a run and return the path."""

        path = self.path_for(metadata.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(metadata.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return path

    def read(self, run_id: str) -> RunMetadata:
        """Read metadata for a run."""

        path = self.path_for(run_id)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RunLedgerError(f"Unable to read run metadata: {path}") from exc

        try:
            return RunMetadata.model_validate_json(raw)
        except ValidationError as exc:
            raise RunLedgerError(f"Invalid run metadata: {path}") from exc

    def list(self) -> list[RunMetadata]:
        """Read all run metadata documents ordered by path."""

        if not self.root.exists():
            return []
        return [self.read(path.stem) for path in sorted(self.root.glob("*.json"))]
