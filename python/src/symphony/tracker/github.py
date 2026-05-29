"""GitHub Issues tracker adapter backed by the local ``gh`` CLI."""

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


class GitHubTrackerError(RuntimeError):
    """Raised when the GitHub CLI adapter cannot complete an operation."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], Path | None, str | None], Awaitable[CommandResult]]


class GitHubLabelPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str


class GitHubIssuePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    number: int
    title: str
    state: str = "OPEN"
    body: str | None = None
    labels: list[GitHubLabelPayload] = Field(default_factory=list)
    url: str | None = None
    createdAt: datetime | None = None
    updatedAt: datetime | None = None


class GitHubTracker:
    """Tracker adapter backed by the local ``gh`` CLI."""

    def __init__(
        self,
        config: TrackerConfig,
        *,
        command_runner: CommandRunner | None = None,
    ) -> None:
        if config.kind != "github":
            raise ValueError("GitHubTracker requires tracker.kind=github")
        if not config.repository:
            raise ValueError("GitHubTracker requires tracker.repository")
        self._config = config
        self._runner = command_runner or run_command

    async def fetch_candidate_issues(self) -> list[Issue]:
        issues = await self.fetch_issues_by_states(["open"])
        in_progress = self._config.in_progress_label.lower()
        return [issue for issue in issues if in_progress not in issue.labels]

    async def check_supported_version(self) -> None:
        version_result = await self._runner(
            [self._config.command, "--version"], self._config.working_directory, None
        )
        if version_result.returncode != 0:
            message = (
                version_result.stderr.strip()
                or version_result.stdout.strip()
                or "GitHub CLI version check failed"
            )
            raise GitHubTrackerError(message)

        auth_result = await self._runner(
            [self._config.command, "auth", "status"], self._config.working_directory, None
        )
        if auth_result.returncode != 0:
            message = (
                auth_result.stderr.strip()
                or auth_result.stdout.strip()
                or "GitHub CLI authentication check failed"
            )
            raise GitHubTrackerError(message)

    async def fetch_issues_by_states(self, state_names: list[str]) -> list[Issue]:
        issues: list[Issue] = []
        for state_name in state_names:
            payload = await self._json(
                [
                    "issue",
                    "list",
                    "--repo",
                    self._repository,
                    "--state",
                    _github_state(state_name),
                    "--limit",
                    "100",
                    "--json",
                    "number,title,body,state,labels,url,createdAt,updatedAt",
                ]
            )
            issues.extend(_normalize_issue_list(payload, in_progress_label=self._in_progress_label))
        return issues

    async def fetch_issue_states_by_ids(self, issue_ids: list[str]) -> dict[str, str]:
        states: dict[str, str] = {}
        for issue_id in issue_ids:
            payload = await self._json(
                [
                    "issue",
                    "view",
                    _issue_number(issue_id),
                    "--repo",
                    self._repository,
                    "--json",
                    "number,state,labels,title",
                ]
            )
            issues = _normalize_issue_list(payload, in_progress_label=self._in_progress_label)
            if not issues:
                raise GitHubTrackerError(f"GitHub issue not found: {issue_id}")
            states[issue_id] = issues[0].state
        return states

    async def create_comment(self, issue_id: str, body: str) -> None:
        await self._text(
            [
                "issue",
                "comment",
                _issue_number(issue_id),
                "--repo",
                self._repository,
                "--body",
                body,
            ]
        )

    async def update_issue_state(self, issue_id: str, state_name: str) -> None:
        if state_name == "in_progress":
            await self._text(
                [
                    "issue",
                    "edit",
                    _issue_number(issue_id),
                    "--repo",
                    self._repository,
                    "--add-label",
                    self._config.in_progress_label,
                ]
            )
            return
        if state_name == "closed":
            await self._text(
                [
                    "issue",
                    "close",
                    _issue_number(issue_id),
                    "--repo",
                    self._repository,
                    "--comment",
                    "Closed by Symphony after a succeeded run.",
                ]
            )
            return
        raise GitHubTrackerError(f"Unsupported GitHub issue state update: {state_name}")

    async def _json(self, args: Sequence[str], *, stdin: str | None = None) -> Any:
        result = await self._run(args, stdin=stdin)
        if not result.stdout.strip():
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubTrackerError("GitHub CLI returned malformed JSON") from exc

    async def _text(self, args: Sequence[str], *, stdin: str | None = None) -> None:
        await self._run(args, stdin=stdin)

    async def _run(self, args: Sequence[str], *, stdin: str | None = None) -> CommandResult:
        command = [self._config.command, *args]
        result = await self._runner(command, self._config.working_directory, stdin)
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "GitHub CLI command failed"
            raise GitHubTrackerError(message)
        return result

    @property
    def _repository(self) -> str:
        assert self._config.repository is not None
        return self._config.repository

    @property
    def _in_progress_label(self) -> str:
        return self._config.in_progress_label.lower()


async def run_command(
    command: Sequence[str], cwd: Path | None, stdin: str | None = None
) -> CommandResult:
    """Run a GitHub CLI command and capture output."""

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise GitHubTrackerError(f"GitHub CLI command not found: {command[0]}") from exc

    stdin_bytes = stdin.encode() if stdin is not None else None
    stdout_bytes, stderr_bytes = await process.communicate(stdin_bytes)
    if process.returncode is None:
        raise GitHubTrackerError("GitHub CLI command exited without a return code")
    return CommandResult(
        returncode=process.returncode,
        stdout=stdout_bytes.decode(),
        stderr=stderr_bytes.decode(),
    )


def _normalize_issue_list(payload: Any, *, in_progress_label: str) -> list[Issue]:
    if payload is None:
        return []
    if isinstance(payload, list):
        raw_issues = cast(list[object], payload)
    elif isinstance(payload, dict):
        raw_issues = [cast(dict[object, object], payload)]
    else:
        raise GitHubTrackerError("GitHub JSON payload must be an object or list")

    issues: list[Issue] = []
    for raw_issue in raw_issues:
        try:
            issue = GitHubIssuePayload.model_validate(raw_issue)
        except ValidationError as exc:
            raise GitHubTrackerError("GitHub issue payload is missing required fields") from exc
        labels = tuple(label.name.lower() for label in issue.labels)
        state = _normalize_state(issue.state, labels=labels, in_progress_label=in_progress_label)
        issues.append(
            Issue(
                id=str(issue.number),
                identifier=f"#{issue.number}",
                title=issue.title,
                description=issue.body,
                priority=_priority_from_labels(labels),
                state=state,
                url=issue.url,
                labels=labels,
                created_at=issue.createdAt,
                updated_at=issue.updatedAt,
            )
        )
    return issues


def _normalize_state(state: str, *, labels: tuple[str, ...], in_progress_label: str) -> str:
    if state.lower() == "closed":
        return "closed"
    if in_progress_label in labels:
        return "in_progress"
    return "open"


def _github_state(state_name: str) -> str:
    if state_name == "closed":
        return "closed"
    return "open"


def _priority_from_labels(labels: tuple[str, ...]) -> int | None:
    for label in labels:
        match = re.fullmatch(r"p(?P<priority>[0-4])", label)
        if match is not None:
            return int(match.group("priority"))
    return None


def _issue_number(issue_id: str) -> str:
    return issue_id.removeprefix("#")
