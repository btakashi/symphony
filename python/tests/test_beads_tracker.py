from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from symphony.config import TrackerConfig
from symphony.tracker.beads import (
    BeadsTracker,
    BeadsTrackerError,
    CommandResult,
    parse_beads_version,
)


class FakeRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = responses
        self.calls: list[tuple[list[str], Path | None, str | None]] = []

    async def __call__(
        self,
        command: Sequence[str],
        cwd: Path | None,
        stdin: str | None,
    ) -> CommandResult:
        self.calls.append((list(command), cwd, stdin))
        return self.responses.pop(0)


def tracker_config(tmp_path: Path) -> TrackerConfig:
    return TrackerConfig(kind="beads", command="bd", working_directory=tmp_path)


def command_ok(payload: object) -> CommandResult:
    return CommandResult(returncode=0, stdout=json.dumps(payload), stderr="")


@pytest.mark.asyncio
async def test_fetch_candidate_issues_normalizes_ready_output(tmp_path: Path) -> None:
    runner = FakeRunner(
        [
            command_ok(
                [
                    {
                        "id": "symphony-123",
                        "title": "Do work",
                        "description": "Details",
                        "status": "open",
                        "priority": "P2",
                        "labels": ["Backend", "Python"],
                        "external_ref": "https://example.test/issue",
                        "created_at": "2026-05-17T13:21:58Z",
                        "updated_at": "2026-05-17T13:22:58Z",
                    }
                ]
            )
        ]
    )
    tracker = BeadsTracker(tracker_config(tmp_path), command_runner=runner)

    issues = await tracker.fetch_candidate_issues()

    assert runner.calls == [(["bd", "ready", "--json"], tmp_path, None)]
    assert len(issues) == 1
    assert issues[0].id == "symphony-123"
    assert issues[0].identifier == "symphony-123"
    assert issues[0].title == "Do work"
    assert issues[0].description == "Details"
    assert issues[0].state == "open"
    assert issues[0].priority == 2
    assert issues[0].labels == ("backend", "python")
    assert issues[0].url == "https://example.test/issue"


@pytest.mark.asyncio
async def test_check_supported_version_accepts_current_major_minor(tmp_path: Path) -> None:
    runner = FakeRunner(
        [CommandResult(returncode=0, stdout="bd version 1.0.4 (Homebrew)", stderr="")]
    )
    tracker = BeadsTracker(tracker_config(tmp_path), command_runner=runner)

    await tracker.check_supported_version()

    assert runner.calls == [(["bd", "--version"], tmp_path, None)]


@pytest.mark.asyncio
async def test_check_supported_version_rejects_other_major_minor(tmp_path: Path) -> None:
    runner = FakeRunner([CommandResult(returncode=0, stdout="bd version 2.0.0", stderr="")])
    tracker = BeadsTracker(tracker_config(tmp_path), command_runner=runner)

    with pytest.raises(BeadsTrackerError, match="Unsupported Beads version"):
        await tracker.check_supported_version()


def test_parse_beads_version() -> None:
    assert parse_beads_version("bd version 1.0.4 (Homebrew)") == (1, 0, 4)


@pytest.mark.asyncio
async def test_fetch_issues_by_states_calls_beads_list_for_each_state(tmp_path: Path) -> None:
    runner = FakeRunner(
        [
            command_ok([{"id": "symphony-1", "title": "One", "status": "open"}]),
            command_ok([{"id": "symphony-2", "title": "Two", "status": "in_progress"}]),
        ]
    )
    tracker = BeadsTracker(tracker_config(tmp_path), command_runner=runner)

    issues = await tracker.fetch_issues_by_states(["open", "in_progress"])

    assert [issue.id for issue in issues] == ["symphony-1", "symphony-2"]
    assert runner.calls == [
        (["bd", "list", "--status", "open", "--json"], tmp_path, None),
        (["bd", "list", "--status", "in_progress", "--json"], tmp_path, None),
    ]


@pytest.mark.asyncio
async def test_fetch_issue_states_by_ids_uses_show(tmp_path: Path) -> None:
    runner = FakeRunner([command_ok([{"id": "symphony-1", "title": "One", "status": "closed"}])])
    tracker = BeadsTracker(tracker_config(tmp_path), command_runner=runner)

    states = await tracker.fetch_issue_states_by_ids(["symphony-1"])

    assert states == {"symphony-1": "closed"}
    assert runner.calls == [(["bd", "show", "symphony-1", "--json"], tmp_path, None)]


@pytest.mark.asyncio
async def test_create_comment_uses_stdin(tmp_path: Path) -> None:
    runner = FakeRunner([command_ok({"id": "comment-1"})])
    tracker = BeadsTracker(tracker_config(tmp_path), command_runner=runner)

    await tracker.create_comment("symphony-1", "hello")

    assert runner.calls == [
        (["bd", "comment", "symphony-1", "--stdin", "--json"], tmp_path, "hello")
    ]


@pytest.mark.asyncio
async def test_update_issue_state_claims_in_progress(tmp_path: Path) -> None:
    runner = FakeRunner(
        [command_ok([{"id": "symphony-1", "title": "One", "status": "in_progress"}])]
    )
    tracker = BeadsTracker(tracker_config(tmp_path), command_runner=runner)

    await tracker.update_issue_state("symphony-1", "in_progress")

    assert runner.calls == [(["bd", "update", "symphony-1", "--claim", "--json"], tmp_path, None)]


@pytest.mark.asyncio
async def test_update_issue_state_closes_closed(tmp_path: Path) -> None:
    runner = FakeRunner([command_ok([{"id": "symphony-1", "title": "One", "status": "closed"}])])
    tracker = BeadsTracker(tracker_config(tmp_path), command_runner=runner)

    await tracker.update_issue_state("symphony-1", "closed")

    assert runner.calls == [(["bd", "close", "symphony-1", "--json"], tmp_path, None)]


@pytest.mark.asyncio
async def test_nonzero_exit_raises(tmp_path: Path) -> None:
    runner = FakeRunner([CommandResult(returncode=1, stdout="", stderr="no beads")])
    tracker = BeadsTracker(tracker_config(tmp_path), command_runner=runner)

    with pytest.raises(BeadsTrackerError, match="no beads"):
        await tracker.fetch_candidate_issues()


@pytest.mark.asyncio
async def test_malformed_json_raises(tmp_path: Path) -> None:
    runner = FakeRunner([CommandResult(returncode=0, stdout="{", stderr="")])
    tracker = BeadsTracker(tracker_config(tmp_path), command_runner=runner)

    with pytest.raises(BeadsTrackerError, match="malformed JSON"):
        await tracker.fetch_candidate_issues()


@pytest.mark.asyncio
async def test_missing_issue_fields_raise(tmp_path: Path) -> None:
    runner = FakeRunner([command_ok([{"id": "symphony-1"}])])
    tracker = BeadsTracker(tracker_config(tmp_path), command_runner=runner)

    with pytest.raises(BeadsTrackerError, match="missing required fields"):
        await tracker.fetch_candidate_issues()
