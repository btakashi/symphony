"""Tracker adapter protocol."""

from __future__ import annotations

from typing import Protocol

from symphony.models import Issue


class Tracker(Protocol):
    """Issue tracker operations used by the orchestrator."""

    async def check_supported_version(self) -> None:
        """Check whether the backing tracker client is available and supported."""
        ...

    async def fetch_candidate_issues(self) -> list[Issue]:
        """Fetch issues eligible for dispatch."""
        ...

    async def fetch_issues_by_states(self, state_names: list[str]) -> list[Issue]:
        """Fetch issues in the given states."""
        ...

    async def fetch_issue_states_by_ids(self, issue_ids: list[str]) -> dict[str, str]:
        """Fetch current state names for issue IDs."""
        ...

    async def create_comment(self, issue_id: str, body: str) -> None:
        """Create a comment on an issue."""
        ...

    async def update_issue_state(self, issue_id: str, state_name: str) -> None:
        """Update an issue state."""
        ...
