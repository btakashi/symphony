import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from symphony.config import TrackerConfig
from symphony.tracker.github import CommandResult, GitHubTracker, GitHubTrackerError


def tracker_config(tmp_path: Path) -> TrackerConfig:
    return TrackerConfig(
        kind="github",
        command="gh",
        repository="owner/repo",
        working_directory=tmp_path,
    )


def issue_payload(
    *,
    number: int = 12,
    state: str = "OPEN",
    labels: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "number": number,
        "title": "Implement GitHub tracker",
        "body": "Do the work",
        "state": state,
        "labels": labels or [{"name": "P1"}],
        "url": f"https://github.com/owner/repo/issues/{number}",
        "createdAt": "2026-05-29T00:00:00Z",
        "updatedAt": "2026-05-29T01:00:00Z",
    }


class FakeRunner:
    def __init__(self, results: Sequence[CommandResult]) -> None:
        self.results = list(results)
        self.commands: list[list[str]] = []
        self.stdins: list[str | None] = []

    async def __call__(
        self, command: Sequence[str], cwd: Path | None, stdin: str | None
    ) -> CommandResult:
        self.commands.append(list(command))
        self.stdins.append(stdin)
        if not self.results:
            raise AssertionError(f"Unexpected command: {command}")
        return self.results.pop(0)


def json_result(payload: object) -> CommandResult:
    return CommandResult(returncode=0, stdout=json.dumps(payload), stderr="")


@pytest.mark.asyncio
async def test_check_supported_version_requires_gh_auth(tmp_path: Path) -> None:
    runner = FakeRunner(
        [
            CommandResult(returncode=0, stdout="gh version 2.0.0\n", stderr=""),
            CommandResult(returncode=0, stdout="Logged in to github.com\n", stderr=""),
        ]
    )
    tracker = GitHubTracker(tracker_config(tmp_path), command_runner=runner)

    await tracker.check_supported_version()

    assert runner.commands == [["gh", "--version"], ["gh", "auth", "status"]]


@pytest.mark.asyncio
async def test_check_supported_version_rejects_missing_auth(tmp_path: Path) -> None:
    runner = FakeRunner(
        [
            CommandResult(returncode=0, stdout="gh version 2.0.0\n", stderr=""),
            CommandResult(returncode=1, stdout="", stderr="not logged in"),
        ]
    )
    tracker = GitHubTracker(tracker_config(tmp_path), command_runner=runner)

    with pytest.raises(GitHubTrackerError, match="not logged in"):
        await tracker.check_supported_version()


@pytest.mark.asyncio
async def test_fetch_candidate_issues_filters_in_progress_label(tmp_path: Path) -> None:
    runner = FakeRunner(
        [
            json_result(
                [
                    issue_payload(number=12),
                    issue_payload(
                        number=13, labels=[{"name": "P0"}, {"name": "symphony:in-progress"}]
                    ),
                ]
            )
        ]
    )
    tracker = GitHubTracker(tracker_config(tmp_path), command_runner=runner)

    issues = await tracker.fetch_candidate_issues()

    assert [issue.identifier for issue in issues] == ["#12"]
    assert issues[0].id == "12"
    assert issues[0].priority == 1
    assert issues[0].state == "open"
    assert runner.commands == [
        [
            "gh",
            "issue",
            "list",
            "--repo",
            "owner/repo",
            "--state",
            "open",
            "--limit",
            "100",
            "--json",
            "number,title,body,state,labels,url,createdAt,updatedAt",
        ]
    ]


@pytest.mark.asyncio
async def test_fetch_issue_states_maps_in_progress_and_closed(tmp_path: Path) -> None:
    runner = FakeRunner(
        [
            json_result(issue_payload(labels=[{"name": "symphony:in-progress"}])),
            json_result(issue_payload(number=13, state="CLOSED")),
        ]
    )
    tracker = GitHubTracker(tracker_config(tmp_path), command_runner=runner)

    states = await tracker.fetch_issue_states_by_ids(["12", "#13"])

    assert states == {"12": "in_progress", "#13": "closed"}


@pytest.mark.asyncio
async def test_update_issue_state_adds_in_progress_label(tmp_path: Path) -> None:
    runner = FakeRunner([CommandResult(returncode=0, stdout="", stderr="")])
    tracker = GitHubTracker(tracker_config(tmp_path), command_runner=runner)

    await tracker.update_issue_state("12", "in_progress")

    assert runner.commands == [
        [
            "gh",
            "issue",
            "edit",
            "12",
            "--repo",
            "owner/repo",
            "--add-label",
            "symphony:in-progress",
        ]
    ]


@pytest.mark.asyncio
async def test_update_issue_state_closes_issue_with_comment(tmp_path: Path) -> None:
    runner = FakeRunner([CommandResult(returncode=0, stdout="", stderr="")])
    tracker = GitHubTracker(tracker_config(tmp_path), command_runner=runner)

    await tracker.update_issue_state("#12", "closed")

    assert runner.commands == [
        [
            "gh",
            "issue",
            "close",
            "12",
            "--repo",
            "owner/repo",
            "--comment",
            "Closed by Symphony after a succeeded run.",
        ]
    ]


@pytest.mark.asyncio
async def test_create_comment_posts_body(tmp_path: Path) -> None:
    runner = FakeRunner([CommandResult(returncode=0, stdout="", stderr="")])
    tracker = GitHubTracker(tracker_config(tmp_path), command_runner=runner)

    await tracker.create_comment("12", "hello")

    assert runner.commands == [
        ["gh", "issue", "comment", "12", "--repo", "owner/repo", "--body", "hello"]
    ]


@pytest.mark.asyncio
async def test_malformed_json_raises_tracker_error(tmp_path: Path) -> None:
    runner = FakeRunner([CommandResult(returncode=0, stdout="{", stderr="")])
    tracker = GitHubTracker(tracker_config(tmp_path), command_runner=runner)

    with pytest.raises(GitHubTrackerError, match="malformed JSON"):
        await tracker.fetch_candidate_issues()
