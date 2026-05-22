"""Provider-neutral runner protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from symphony.models import Issue, RunEvent, RunRef, RunStatus, SymphonyModel


class RunOptions(SymphonyModel):
    """Options supplied to a runner for a single attempt."""

    tracker_kind: str
    workspace_path: Path
    attempt: int | None = None


class Runner(Protocol):
    """Async runner boundary used by the orchestrator."""

    async def start_run(self, issue: Issue, prompt: str, opts: RunOptions) -> RunRef:
        """Start a run for an issue and return its runner reference."""
        ...

    async def poll_run(self, run_ref: RunRef) -> RunStatus:
        """Return the normalized status for a run."""
        ...

    async def cancel_run(self, run_ref: RunRef) -> None:
        """Cancel a run if it is still active."""
        ...

    async def fetch_events(self, run_ref: RunRef) -> list[RunEvent]:
        """Return events emitted for a run."""
        ...
