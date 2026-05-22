from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from symphony.config import ClaudeHeadlessConfig, EnvironmentConfig
from symphony.models import Issue, RunRef
from symphony.runner.base import Runner, RunOptions
from symphony.runner.claude_headless import (
    HANDOFF_END,
    HANDOFF_START,
    ClaudeHeadlessRunner,
    ClaudeHeadlessRunnerError,
    parse_structured_handoff,
)


class FakeProcess:
    def __init__(
        self,
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
        delay: float = 0,
        ignore_terminate: bool = False,
    ) -> None:
        self.pid = 123
        self.returncode: int | None = None
        self._final_returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._delay = delay
        self._ignore_terminate = ignore_terminate
        self.input: bytes | None = None
        self.terminated = False
        self.killed = False

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        self.input = input
        await asyncio.sleep(self._delay)
        self.returncode = self._final_returncode
        return self._stdout.encode(), self._stderr.encode()

    def terminate(self) -> None:
        self.terminated = True
        if not self._ignore_terminate:
            self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        while self.returncode is None:
            await asyncio.sleep(0.001)
        return self.returncode


class FakeProcessFactory:
    def __init__(self, process: FakeProcess) -> None:
        self.process = process
        self.calls: list[tuple[list[str], Path, dict[str, str]]] = []

    async def __call__(
        self, command: Sequence[str], cwd: Path, env: Mapping[str, str]
    ) -> FakeProcess:
        self.calls.append((list(command), cwd, dict(env)))
        return self.process


def issue() -> Issue:
    return Issue(
        id="symphony-1",
        identifier="symphony-1",
        title="Implement headless runner",
        state="open",
    )


def opts(tmp_path: Path) -> RunOptions:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return RunOptions(tracker_kind="beads", workspace_path=workspace)


def config(**updates: object) -> ClaudeHeadlessConfig:
    return ClaudeHeadlessConfig.model_validate({"executable": "claude", "args": ["-p"], **updates})


def handoff(status: str = "succeeded", summary: str = "done") -> str:
    return f"""
agent output
{HANDOFF_START}
{{"status": "{status}", "summary": "{summary}", "artifacts": [], "validation": [], "errors": []}}
{HANDOFF_END}
"""


def runner(
    tmp_path: Path,
    *,
    process: FakeProcess,
    environment: EnvironmentConfig | None = None,
    environ: Mapping[str, str] | None = None,
    runner_config: ClaudeHeadlessConfig | None = None,
) -> tuple[ClaudeHeadlessRunner, FakeProcessFactory]:
    factory = FakeProcessFactory(process)
    return (
        ClaudeHeadlessRunner(
            runner_config or config(),
            environment=environment,
            environ=environ or {},
            process_factory=factory,
            stdout_path_factory=lambda run_id: tmp_path / "log" / run_id / "stdout.log",
            stderr_path_factory=lambda run_id: tmp_path / "log" / run_id / "stderr.log",
        ),
        factory,
    )


async def poll_until_done(subject: ClaudeHeadlessRunner, run_ref: RunRef) -> str:
    for _ in range(1500):
        status = await subject.poll_run(run_ref)
        if status != "running":
            return status
        await asyncio.sleep(0.001)
    raise AssertionError("run did not finish")


def accepts_runner(subject: Runner) -> Runner:
    return subject


def test_claude_headless_runner_satisfies_runner_protocol(tmp_path: Path) -> None:
    subject, _ = runner(tmp_path, process=FakeProcess(stdout=handoff()))

    assert accepts_runner(subject) is subject


@pytest.mark.asyncio
async def test_claude_headless_runner_success_flow(tmp_path: Path) -> None:
    process = FakeProcess(stdout=handoff(summary="implemented"))
    subject, factory = runner(
        tmp_path,
        process=process,
        environment=EnvironmentConfig(allow=["PATH", "ANTHROPIC_API_KEY"], deny=["PATH"]),
        environ={"PATH": "/bin", "ANTHROPIC_API_KEY": "token", "EXTRA": "ignored"},
    )

    run_ref = await subject.start_run(issue(), "prompt text", opts(tmp_path))
    status = await poll_until_done(subject, run_ref)
    events = await subject.fetch_events(run_ref)

    assert status == "succeeded"
    assert run_ref.provider == "claude"
    assert run_ref.mode == "headless"
    assert factory.calls == [
        (["claude", "-p"], tmp_path / "workspace", {"ANTHROPIC_API_KEY": "token"})
    ]
    assert process.input == b"prompt text"
    assert [event.event_type for event in events] == ["run_started", "run_succeeded"]
    assert events[-1].message == "implemented"
    assert (tmp_path / "log" / run_ref.run_id / "stdout.log").read_text(
        encoding="utf-8"
    ) == handoff(summary="implemented")


@pytest.mark.asyncio
async def test_claude_headless_runner_fails_without_handoff(tmp_path: Path) -> None:
    subject, _ = runner(tmp_path, process=FakeProcess(stdout="no artifact"))

    run_ref = await subject.start_run(issue(), "prompt text", opts(tmp_path))

    assert await poll_until_done(subject, run_ref) == "failed"
    events = await subject.fetch_events(run_ref)
    assert events[-1].event_type == "run_failed"
    assert events[-1].message == "Missing structured handoff artifact"


@pytest.mark.asyncio
async def test_claude_headless_runner_fails_on_nonzero_exit(tmp_path: Path) -> None:
    subject, _ = runner(tmp_path, process=FakeProcess(stdout=handoff(), returncode=2))

    run_ref = await subject.start_run(issue(), "prompt text", opts(tmp_path))

    assert await poll_until_done(subject, run_ref) == "failed"
    events = await subject.fetch_events(run_ref)
    assert events[-1].message == "Claude headless exited with status 2"


@pytest.mark.asyncio
async def test_claude_headless_runner_cancels_active_process(tmp_path: Path) -> None:
    process = FakeProcess(stdout=handoff(), delay=1)
    subject, _ = runner(tmp_path, process=process)
    run_ref = await subject.start_run(issue(), "prompt text", opts(tmp_path))

    await subject.cancel_run(run_ref)

    assert process.terminated is True
    assert await subject.poll_run(run_ref) == "cancelled"
    events = await subject.fetch_events(run_ref)
    assert events[-1].event_type == "run_cancelled"


@pytest.mark.asyncio
async def test_claude_headless_runner_kills_after_timeout(tmp_path: Path) -> None:
    process = FakeProcess(stdout=handoff(), delay=1, ignore_terminate=True)
    subject, _ = runner(
        tmp_path,
        process=process,
        runner_config=config(timeout_seconds=1, kill_grace_seconds=0),
    )

    run_ref = await subject.start_run(issue(), "prompt text", opts(tmp_path))
    status = await poll_until_done(subject, run_ref)

    assert status == "failed"
    assert process.terminated is True
    assert process.killed is True


def test_parse_structured_handoff_rejects_invalid_json() -> None:
    with pytest.raises(ClaudeHeadlessRunnerError, match="Invalid structured handoff"):
        parse_structured_handoff(f"{HANDOFF_START}\n{{\n{HANDOFF_END}")
