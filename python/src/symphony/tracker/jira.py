"""Jira Cloud tracker adapter backed by REST API v3."""

from __future__ import annotations

import asyncio
import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from symphony.config import TrackerConfig
from symphony.models import Issue


class JiraTrackerError(RuntimeError):
    """Raised when the Jira adapter cannot complete an operation."""


HttpMethod = Literal["GET", "POST"]


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: str


HttpRunner = Callable[
    [HttpMethod, str, Mapping[str, str], dict[str, object] | None],
    Awaitable[HttpResult],
]


class JiraPriorityPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None


class JiraStatusPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str


class JiraFieldsPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    summary: str
    description: Any | None = None
    status: JiraStatusPayload
    labels: list[str] = Field(default_factory=list)
    priority: JiraPriorityPayload | None = None
    created: datetime | None = None
    updated: datetime | None = None


class JiraIssuePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    key: str
    self: str | None = None
    fields: JiraFieldsPayload


class JiraSearchPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    issues: list[JiraIssuePayload] = Field(default_factory=list)


class JiraTransitionPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str


class JiraTransitionsPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    transitions: list[JiraTransitionPayload] = Field(default_factory=list)


class JiraTracker:
    """Tracker adapter backed by Jira Cloud REST API v3."""

    def __init__(
        self,
        config: TrackerConfig,
        *,
        http_runner: HttpRunner | None = None,
    ) -> None:
        if config.kind != "jira":
            raise ValueError("JiraTracker requires tracker.kind=jira")
        if not config.url or not config.project or not config.username or not config.api_token:
            raise ValueError("JiraTracker requires url, project, username, and api_token")
        self._config = config
        self._runner = http_runner or run_http

    async def check_supported_version(self) -> None:
        await self._json("GET", "/rest/api/3/myself")

    async def fetch_candidate_issues(self) -> list[Issue]:
        return await self.fetch_issues_by_states(["open"])

    async def fetch_issues_by_states(self, state_names: list[str]) -> list[Issue]:
        del state_names
        payload = await self._json(
            "GET",
            "/rest/api/3/search/jql",
            params={
                "jql": self._jql,
                "maxResults": "100",
                "fields": "summary,description,status,priority,labels,created,updated",
            },
        )
        try:
            search = JiraSearchPayload.model_validate(payload)
        except ValidationError as exc:
            raise JiraTrackerError("Jira search payload is missing required fields") from exc
        return [_normalize_issue(issue) for issue in search.issues]

    async def fetch_issue_states_by_ids(self, issue_ids: list[str]) -> dict[str, str]:
        states: dict[str, str] = {}
        for issue_id in issue_ids:
            issue = await self._fetch_issue(issue_id, fields="status")
            states[issue_id] = issue.state
        return states

    async def create_comment(self, issue_id: str, body: str) -> None:
        await self._json(
            "POST",
            f"/rest/api/3/issue/{urllib.parse.quote(issue_id)}/comment",
            body={"body": _adf_doc(body)},
        )

    async def update_issue_state(self, issue_id: str, state_name: str) -> None:
        transition_name = self._transition_name_for_state(state_name)
        transition_id = await self._transition_id(issue_id, transition_name)
        await self._json(
            "POST",
            f"/rest/api/3/issue/{urllib.parse.quote(issue_id)}/transitions",
            body={"transition": {"id": transition_id}},
        )

    async def _fetch_issue(self, issue_id: str, *, fields: str) -> Issue:
        payload = await self._json(
            "GET",
            f"/rest/api/3/issue/{urllib.parse.quote(issue_id)}",
            params={"fields": fields},
        )
        try:
            return _normalize_issue(JiraIssuePayload.model_validate(payload))
        except ValidationError as exc:
            raise JiraTrackerError("Jira issue payload is missing required fields") from exc

    async def _transition_id(self, issue_id: str, transition_name: str) -> str:
        payload = await self._json(
            "GET", f"/rest/api/3/issue/{urllib.parse.quote(issue_id)}/transitions"
        )
        try:
            transitions = JiraTransitionsPayload.model_validate(payload)
        except ValidationError as exc:
            raise JiraTrackerError("Jira transitions payload is missing required fields") from exc
        for transition in transitions.transitions:
            if transition.name.lower() == transition_name.lower():
                return transition.id
        raise JiraTrackerError(f"Jira transition not found: {transition_name}")

    async def _json(
        self,
        method: HttpMethod,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> Any:
        result = await self._runner(method, _url(self._base_url, path, params), self._headers, body)
        if result.status < 200 or result.status >= 300:
            raise JiraTrackerError(f"Jira API returned HTTP {result.status}: {result.body}")
        if not result.body:
            return None
        try:
            return json.loads(result.body)
        except json.JSONDecodeError as exc:
            raise JiraTrackerError("Jira API returned malformed JSON") from exc

    def _transition_name_for_state(self, state_name: str) -> str:
        if state_name == "in_progress":
            return self._config.in_progress_transition
        if state_name == "closed":
            return self._config.closed_transition
        return state_name

    @property
    def _base_url(self) -> str:
        assert self._config.url is not None
        return self._config.url.rstrip("/")

    @property
    def _jql(self) -> str:
        if self._config.jql:
            return self._config.jql
        assert self._config.project is not None
        return (
            f'project = "{self._config.project}" AND statusCategory != Done '
            "ORDER BY priority DESC, updated ASC"
        )

    @property
    def _headers(self) -> dict[str, str]:
        assert self._config.username is not None
        assert self._config.api_token is not None
        token = base64.b64encode(
            f"{self._config.username}:{self._config.api_token}".encode()
        ).decode()
        return {
            "Accept": "application/json",
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        }


async def run_http(
    method: HttpMethod,
    url: str,
    headers: Mapping[str, str],
    body: dict[str, object] | None,
) -> HttpResult:
    """Run a Jira HTTP request in a worker thread."""

    return await asyncio.to_thread(_run_http_sync, method, url, headers, body)


def _run_http_sync(
    method: HttpMethod,
    url: str,
    headers: Mapping[str, str],
    body: dict[str, object] | None,
) -> HttpResult:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return HttpResult(
                status=response.status,
                body=response.read().decode(),
            )
    except urllib.error.HTTPError as exc:
        return HttpResult(status=exc.code, body=exc.read().decode())
    except urllib.error.URLError as exc:
        raise JiraTrackerError(f"Jira API request failed: {exc}") from exc


def _normalize_issue(issue: JiraIssuePayload) -> Issue:
    description = issue.fields.description
    return Issue(
        id=issue.id,
        identifier=issue.key,
        title=issue.fields.summary,
        description=description if isinstance(description, str) else None,
        priority=_normalize_priority(issue.fields.priority.name if issue.fields.priority else None),
        state=_normalize_state(issue.fields.status.name),
        url=issue.self,
        labels=tuple(label.lower() for label in issue.fields.labels),
        created_at=issue.fields.created,
        updated_at=issue.fields.updated,
    )


def _normalize_state(state_name: str) -> str:
    normalized = state_name.lower().replace(" ", "_").replace("-", "_")
    if normalized in {"done", "closed", "resolved"}:
        return "closed"
    if normalized in {"in_progress", "doing"}:
        return "in_progress"
    return normalized


def _normalize_priority(priority: str | None) -> int | None:
    if priority is None:
        return None
    normalized = priority.lower()
    if normalized in {"highest", "p0"}:
        return 0
    if normalized in {"high", "p1"}:
        return 1
    if normalized in {"medium", "p2"}:
        return 2
    if normalized in {"low", "p3"}:
        return 3
    if normalized in {"lowest", "p4"}:
        return 4
    return None


def _adf_doc(text: str) -> dict[str, object]:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def _url(base_url: str, path: str, params: Mapping[str, str] | None = None) -> str:
    url = f"{base_url}{path}"
    if not params:
        return url
    return f"{url}?{urllib.parse.urlencode(params)}"
