"""Beads tracker adapter."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from symphony.config import TrackerConfig
from symphony.models import Issue


class BeadsTrackerError(RuntimeError):
    """Raised when the Beads CLI adapter cannot complete an operation."""


SUPPORTED_BEADS_VERSION = (1, 0)
_VERSION_RE = re.compile(r"bd version (?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], Path | None, str | None], Awaitable[CommandResult]]


class BeadsIssuePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    status: str
    issue_type: str = "task"
    description: str | None = None
    priority: int | str | None = None
    labels: list[str] = Field(default_factory=list)
    external_ref: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BeadsTracker:
    """Tracker adapter backed by the local ``bd`` CLI."""

    def __init__(
        self,
        config: TrackerConfig,
        *,
        command_runner: CommandRunner | None = None,
    ) -> None:
        if config.kind != "beads":
            raise ValueError("BeadsTracker requires tracker.kind=beads")
        self._config = config
        self._runner = command_runner or run_command

    async def fetch_candidate_issues(self) -> list[Issue]:
        payload = await self._json(["ready", "--json"])
        return [issue for issue in _normalize_issue_list(payload) if issue.issue_type != "epic"]

    async def check_supported_version(self) -> None:
        result = await self._runner(
            [self._config.command, "--version"], self._config.working_directory, None
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "Beads version check failed"
            raise BeadsTrackerError(message)
        version = parse_beads_version(result.stdout)
        if version[:2] != SUPPORTED_BEADS_VERSION:
            supported = ".".join(str(part) for part in SUPPORTED_BEADS_VERSION)
            actual = ".".join(str(part) for part in version)
            raise BeadsTrackerError(f"Unsupported Beads version {actual}; expected {supported}.x")

    async def fetch_issues_by_states(self, state_names: list[str]) -> list[Issue]:
        issues: list[Issue] = []
        for state_name in state_names:
            payload = await self._json(["list", "--status", state_name, "--json"])
            issues.extend(_normalize_issue_list(payload))
        return issues

    async def fetch_issue_states_by_ids(self, issue_ids: list[str]) -> dict[str, str]:
        states: dict[str, str] = {}
        for issue_id in issue_ids:
            issues = _normalize_issue_list(await self._json(["show", issue_id, "--json"]))
            if not issues:
                raise BeadsTrackerError(f"Beads issue not found: {issue_id}")
            states[issue_id] = issues[0].state
        return states

    async def create_comment(self, issue_id: str, body: str) -> None:
        await self._json(["comment", issue_id, "--stdin", "--json"], stdin=body)

    async def update_issue_state(self, issue_id: str, state_name: str) -> None:
        if state_name == "in_progress":
            await self.claim_issue(issue_id)
        elif state_name == "closed":
            await self.close_issue(issue_id)
        else:
            await self._json(["update", issue_id, "--status", state_name, "--json"])

    async def claim_issue(self, issue_id: str) -> Issue:
        issues = _normalize_issue_list(await self._json(["update", issue_id, "--claim", "--json"]))
        if not issues:
            raise BeadsTrackerError(f"Beads claim returned no issue: {issue_id}")
        return issues[0]

    async def close_issue(self, issue_id: str) -> None:
        await self._json(["close", issue_id, "--json"])

    async def _json(self, args: Sequence[str], *, stdin: str | None = None) -> Any:
        command = [self._config.command, *args]
        result = await self._runner(command, self._config.working_directory, stdin)
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "Beads command failed"
            raise BeadsTrackerError(message)
        if not result.stdout.strip():
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise BeadsTrackerError("Beads command returned malformed JSON") from exc


async def run_command(
    command: Sequence[str], cwd: Path | None, stdin: str | None = None
) -> CommandResult:
    """Run a Beads command and capture output."""

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise BeadsTrackerError(f"Beads command not found: {command[0]}") from exc

    stdin_bytes = stdin.encode() if stdin is not None else None
    stdout_bytes, stderr_bytes = await process.communicate(stdin_bytes)
    if process.returncode is None:
        raise BeadsTrackerError("Beads command exited without a return code")
    return CommandResult(
        returncode=process.returncode,
        stdout=stdout_bytes.decode(),
        stderr=stderr_bytes.decode(),
    )


def _normalize_issue_list(payload: Any) -> list[Issue]:
    if payload is None:
        return []
    if isinstance(payload, list):
        raw_issues = cast(list[object], payload)
    elif isinstance(payload, dict):
        raw_issues = [cast(dict[object, object], payload)]
    else:
        raise BeadsTrackerError("Beads JSON payload must be an object or list")

    issues: list[Issue] = []
    for raw_issue in raw_issues:
        try:
            issue = BeadsIssuePayload.model_validate(raw_issue)
        except ValidationError as exc:
            raise BeadsTrackerError("Beads issue payload is missing required fields") from exc
        issues.append(
            Issue(
                id=issue.id,
                identifier=issue.id,
                title=issue.title,
                issue_type=issue.issue_type,
                description=issue.description,
                priority=_normalize_priority(issue.priority),
                state=issue.status,
                url=issue.external_ref,
                labels=tuple(label.lower() for label in issue.labels),
                created_at=issue.created_at,
                updated_at=issue.updated_at,
            )
        )
    return issues


def _normalize_priority(priority: int | str | None) -> int | None:
    if priority is None:
        return None
    if isinstance(priority, int):
        return priority
    priority_value = priority.removeprefix("P").removeprefix("p")
    try:
        return int(priority_value)
    except ValueError:
        return None


def parse_beads_version(output: str) -> tuple[int, int, int]:
    match = _VERSION_RE.search(output)
    if match is None:
        raise BeadsTrackerError(f"Unable to parse Beads version output: {output.strip()}")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )
