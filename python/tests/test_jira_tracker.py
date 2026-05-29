import json
from collections.abc import Mapping

import pytest

from symphony.config import TrackerConfig
from symphony.tracker.jira import HttpMethod, HttpResult, JiraTracker, JiraTrackerError


def tracker_config() -> TrackerConfig:
    return TrackerConfig(
        kind="jira",
        url="https://example.atlassian.net",
        project="SYMP",
        username="person@example.com",
        api_token="token",
    )


def jira_issue(
    *,
    issue_id: str = "10001",
    key: str = "SYMP-1",
    status: str = "To Do",
    priority: str = "High",
) -> dict[str, object]:
    return {
        "id": issue_id,
        "key": key,
        "self": f"https://example.atlassian.net/rest/api/3/issue/{issue_id}",
        "fields": {
            "summary": "Implement Jira tracker",
            "description": "Do the work",
            "status": {"name": status},
            "priority": {"name": priority},
            "labels": ["symphony"],
            "created": "2026-05-29T10:00:00.000+0000",
            "updated": "2026-05-29T11:00:00.000+0000",
        },
    }


class FakeHttp:
    def __init__(self, results: list[HttpResult]) -> None:
        self.results = results
        self.requests: list[
            tuple[HttpMethod, str, Mapping[str, str], dict[str, object] | None]
        ] = []

    async def __call__(
        self,
        method: HttpMethod,
        url: str,
        headers: Mapping[str, str],
        body: dict[str, object] | None,
    ) -> HttpResult:
        self.requests.append((method, url, headers, body))
        if not self.results:
            raise AssertionError(f"Unexpected request: {method} {url}")
        return self.results.pop(0)


def json_result(payload: object, *, status: int = 200) -> HttpResult:
    return HttpResult(status=status, body=json.dumps(payload))


@pytest.mark.asyncio
async def test_check_supported_version_calls_myself() -> None:
    http = FakeHttp([json_result({"accountId": "abc"})])
    tracker = JiraTracker(tracker_config(), http_runner=http)

    await tracker.check_supported_version()

    method, url, headers, body = http.requests[0]
    assert method == "GET"
    assert url == "https://example.atlassian.net/rest/api/3/myself"
    assert headers["Authorization"].startswith("Basic ")
    assert body is None


@pytest.mark.asyncio
async def test_fetch_candidate_issues_searches_configured_project() -> None:
    http = FakeHttp([json_result({"issues": [jira_issue()]})])
    tracker = JiraTracker(tracker_config(), http_runner=http)

    issues = await tracker.fetch_candidate_issues()

    assert [issue.identifier for issue in issues] == ["SYMP-1"]
    assert issues[0].id == "10001"
    assert issues[0].priority == 1
    assert issues[0].state == "to_do"
    method, url, _, _ = http.requests[0]
    assert method == "GET"
    assert url.startswith("https://example.atlassian.net/rest/api/3/search/jql?")
    assert "project+%3D+%22SYMP%22" in url


@pytest.mark.asyncio
async def test_fetch_issue_states_by_ids_normalizes_closed_state() -> None:
    http = FakeHttp([json_result(jira_issue(status="Done"))])
    tracker = JiraTracker(tracker_config(), http_runner=http)

    states = await tracker.fetch_issue_states_by_ids(["SYMP-1"])

    assert states == {"SYMP-1": "closed"}
    assert (
        http.requests[0][1] == "https://example.atlassian.net/rest/api/3/issue/SYMP-1?fields=status"
    )


@pytest.mark.asyncio
async def test_create_comment_posts_adf_body() -> None:
    http = FakeHttp([json_result({"id": "1"})])
    tracker = JiraTracker(tracker_config(), http_runner=http)

    await tracker.create_comment("SYMP-1", "hello")

    method, url, _, body = http.requests[0]
    assert method == "POST"
    assert url == "https://example.atlassian.net/rest/api/3/issue/SYMP-1/comment"
    assert body is not None
    assert body["body"] == {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "hello"}]}],
    }


@pytest.mark.asyncio
async def test_update_issue_state_uses_named_transition() -> None:
    http = FakeHttp(
        [
            json_result({"transitions": [{"id": "31", "name": "In Progress"}]}),
            json_result({}),
        ]
    )
    tracker = JiraTracker(tracker_config(), http_runner=http)

    await tracker.update_issue_state("SYMP-1", "in_progress")

    assert (
        http.requests[0][1] == "https://example.atlassian.net/rest/api/3/issue/SYMP-1/transitions"
    )
    assert http.requests[1] == (
        "POST",
        "https://example.atlassian.net/rest/api/3/issue/SYMP-1/transitions",
        http.requests[1][2],
        {"transition": {"id": "31"}},
    )


@pytest.mark.asyncio
async def test_update_issue_state_raises_when_transition_missing() -> None:
    http = FakeHttp([json_result({"transitions": [{"id": "1", "name": "Blocked"}]})])
    tracker = JiraTracker(tracker_config(), http_runner=http)

    with pytest.raises(JiraTrackerError, match="transition not found"):
        await tracker.update_issue_state("SYMP-1", "closed")


@pytest.mark.asyncio
async def test_http_error_raises_tracker_error() -> None:
    http = FakeHttp([HttpResult(status=401, body="unauthorized")])
    tracker = JiraTracker(tracker_config(), http_runner=http)

    with pytest.raises(JiraTrackerError, match="HTTP 401"):
        await tracker.fetch_candidate_issues()
