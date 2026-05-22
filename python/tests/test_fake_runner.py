from pathlib import Path

import pytest

from symphony.models import Issue, RunRef
from symphony.runner.base import Runner, RunOptions
from symphony.runner.fake import FakeRunner, FakeRunnerError, FakeRunScript


def issue() -> Issue:
    return Issue(
        id="issue-internal-1",
        identifier="symphony-123",
        title="Implement runner",
        state="open",
    )


def run_options(tmp_path: Path) -> RunOptions:
    return RunOptions(tracker_kind="beads", workspace_path=tmp_path / "symphony-123")


def accepts_runner(runner: Runner) -> Runner:
    return runner


def test_fake_runner_satisfies_runner_protocol() -> None:
    runner = FakeRunner()

    assert accepts_runner(runner) is runner


@pytest.mark.asyncio
async def test_fake_runner_success_flow(tmp_path: Path) -> None:
    runner = FakeRunner()

    run_ref = await runner.start_run(issue(), "prompt text", run_options(tmp_path))
    status = await runner.poll_run(run_ref)
    events = await runner.fetch_events(run_ref)

    assert run_ref.provider == "fake"
    assert run_ref.mode == "fake"
    assert status == "succeeded"
    assert [event.event_type for event in events] == ["run_started", "run_succeeded"]
    assert events[0].tracker_kind == "beads"
    assert events[0].issue_id == "issue-internal-1"
    assert events[0].issue_identifier == "symphony-123"
    assert events[0].workspace_path == tmp_path / "symphony-123"
    assert events[1].message == "Fake runner succeeded symphony-123"
    assert runner.started_prompts[run_ref.run_id] == "prompt text"


@pytest.mark.asyncio
async def test_fake_runner_failure_flow(tmp_path: Path) -> None:
    runner = FakeRunner(
        scripts_by_identifier={
            "symphony-123": [FakeRunScript(outcome="failure", message="scripted failure")]
        }
    )

    run_ref = await runner.start_run(issue(), "prompt text", run_options(tmp_path))
    status = await runner.poll_run(run_ref)
    events = await runner.fetch_events(run_ref)

    assert status == "failed"
    assert events[-1].event_type == "run_failed"
    assert events[-1].message == "scripted failure"


@pytest.mark.asyncio
async def test_fake_runner_cancel_flow(tmp_path: Path) -> None:
    runner = FakeRunner(
        scripts_by_identifier={"symphony-123": [FakeRunScript(outcome="success", running_polls=2)]}
    )

    run_ref = await runner.start_run(issue(), "prompt text", run_options(tmp_path))
    assert await runner.poll_run(run_ref) == "running"

    await runner.cancel_run(run_ref)

    assert await runner.poll_run(run_ref) == "cancelled"
    events = await runner.fetch_events(run_ref)
    assert [event.event_type for event in events] == ["run_started", "run_cancelled"]


@pytest.mark.asyncio
async def test_fake_runner_waiting_for_permission_flow(tmp_path: Path) -> None:
    runner = FakeRunner(scripts_by_identifier={"symphony-123": [FakeRunScript(outcome="waiting")]})

    run_ref = await runner.start_run(issue(), "prompt text", run_options(tmp_path))

    assert await runner.poll_run(run_ref) == "waiting_for_permission"
    assert await runner.poll_run(run_ref) == "waiting_for_permission"
    events = await runner.fetch_events(run_ref)
    assert [event.event_type for event in events] == ["run_started", "run_waiting_for_permission"]


@pytest.mark.asyncio
async def test_fake_runner_running_polls_before_terminal_status(tmp_path: Path) -> None:
    runner = FakeRunner(
        scripts_by_identifier={"symphony-123": [FakeRunScript(outcome="success", running_polls=2)]}
    )
    run_ref = await runner.start_run(issue(), "prompt text", run_options(tmp_path))

    assert await runner.poll_run(run_ref) == "running"
    assert await runner.poll_run(run_ref) == "running"
    assert await runner.poll_run(run_ref) == "succeeded"


@pytest.mark.asyncio
async def test_fake_runner_uses_scripts_in_order(tmp_path: Path) -> None:
    runner = FakeRunner(
        scripts_by_identifier={
            "symphony-123": [
                FakeRunScript(outcome="failure"),
                FakeRunScript(outcome="success"),
            ]
        }
    )

    first = await runner.start_run(issue(), "prompt text", run_options(tmp_path))
    second = await runner.start_run(issue(), "prompt text", run_options(tmp_path))

    assert await runner.poll_run(first) == "failed"
    assert await runner.poll_run(second) == "succeeded"


@pytest.mark.asyncio
async def test_fake_runner_rejects_unknown_run_ref() -> None:
    runner = FakeRunner()
    unknown = RunRef(provider="fake", mode="fake", run_id="missing")

    with pytest.raises(FakeRunnerError, match="Unknown fake run"):
        await runner.poll_run(unknown)
