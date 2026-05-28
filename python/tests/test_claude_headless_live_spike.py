from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import pytest

from symphony.config import ClaudeHeadlessConfig, EnvironmentConfig
from symphony.models import Issue, RunRef, RunStatus
from symphony.runner.base import RunOptions
from symphony.runner.claude_headless import (
    HANDOFF_END,
    HANDOFF_START,
    ClaudeHeadlessRunner,
)

pytestmark = [pytest.mark.live, pytest.mark.spike]

_RUN_ENV = "SYMPHONY_RUN_CLAUDE_HEADLESS_SPIKE"


@pytest.mark.asyncio
async def test_real_claude_headless_structured_handoff_spike(tmp_path: Path) -> None:
    if os.environ.get(_RUN_ENV) != "1":
        pytest.skip(f"Set {_RUN_ENV}=1 to run the real claude -p headless spike")

    executable = shutil.which("claude")
    if executable is None:
        pytest.skip("claude executable is not available on PATH")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = ClaudeHeadlessRunner(
        ClaudeHeadlessConfig(
            executable=executable,
            args=["-p"],
            timeout_seconds=120,
            kill_grace_seconds=5,
        ),
        environment=EnvironmentConfig(
            allow=[
                "HOME",
                "PATH",
                "SHELL",
                "TERM",
                "USER",
                "LOGNAME",
                "TMPDIR",
                "ANTHROPIC_API_KEY",
            ]
        ),
        stdout_path_factory=lambda run_id: tmp_path / "log" / run_id / "stdout.log",
        stderr_path_factory=lambda run_id: tmp_path / "log" / run_id / "stderr.log",
    )

    run_ref = await runner.start_run(
        Issue(
            id="spike-claude-headless",
            identifier="SPIKE-CLAUDE-HEADLESS",
            title="Validate claude -p structured handoff",
            state="open",
        ),
        _prompt(),
        RunOptions(tracker_kind="memory", workspace_path=workspace),
    )

    status = await _poll_until_done(runner, run_ref)
    events = await runner.fetch_events(run_ref)

    assert status == "succeeded"
    assert events[-1].event_type == "run_succeeded"
    assert events[-1].metadata["completion_artifact_status"] == "valid"
    assert (tmp_path / "log" / run_ref.run_id / "stdout.log").exists()
    assert (tmp_path / "log" / run_ref.run_id / "stderr.log").exists()


@pytest.mark.asyncio
async def test_real_claude_headless_workspace_edit_spike(tmp_path: Path) -> None:
    if os.environ.get(_RUN_ENV) != "1":
        pytest.skip(f"Set {_RUN_ENV}=1 to run the real claude -p headless spike")

    executable = shutil.which("claude")
    if executable is None:
        pytest.skip("claude executable is not available on PATH")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "input.txt").write_text("symphony input\n", encoding="utf-8")
    runner = ClaudeHeadlessRunner(
        ClaudeHeadlessConfig(
            executable=executable,
            args=["-p", "--allowedTools", "Read,Write,Edit"],
            timeout_seconds=180,
            kill_grace_seconds=5,
        ),
        environment=EnvironmentConfig(
            allow=[
                "HOME",
                "PATH",
                "SHELL",
                "TERM",
                "USER",
                "LOGNAME",
                "TMPDIR",
                "ANTHROPIC_API_KEY",
            ]
        ),
        stdout_path_factory=lambda run_id: tmp_path / "log" / run_id / "stdout.log",
        stderr_path_factory=lambda run_id: tmp_path / "log" / run_id / "stderr.log",
    )

    run_ref = await runner.start_run(
        Issue(
            id="spike-claude-headless-workspace-edit",
            identifier="SPIKE-CLAUDE-HEADLESS-WORKSPACE-EDIT",
            title="Validate claude -p workspace file editing",
            state="open",
        ),
        _workspace_edit_prompt(),
        RunOptions(tracker_kind="memory", workspace_path=workspace),
    )

    status = await _poll_until_done(runner, run_ref)
    events = await runner.fetch_events(run_ref)

    assert status == "succeeded"
    assert events[-1].event_type == "run_succeeded"
    assert events[-1].metadata["completion_artifact_status"] == "valid"
    assert (workspace / "output.txt").read_text(encoding="utf-8") == "symphony output\n"
    assert (tmp_path / "log" / run_ref.run_id / "stdout.log").exists()
    assert (tmp_path / "log" / run_ref.run_id / "stderr.log").exists()


def _prompt() -> str:
    payload = (
        '{"status":"succeeded","summary":"headless spike handoff emitted",'
        '"artifacts":[],"validation":[],"errors":[]}'
    )
    return f"""You are validating a Symphony runner spike.

Do not inspect files, run commands, or use tools. Reply with exactly this machine-readable block:

{HANDOFF_START}
{payload}
{HANDOFF_END}
"""


def _workspace_edit_prompt() -> str:
    payload = (
        '{"status":"succeeded","summary":"workspace edit spike completed",'
        '"artifacts":["output.txt"],"validation":["output.txt exact content verified by test"],'
        '"errors":[]}'
    )
    return f"""You are validating a Symphony runner spike inside a disposable workspace.

Work only in the current working directory.

Tasks:
1. Read `input.txt`.
2. Create `output.txt` with exactly this content, including the trailing newline:
   symphony output
3. Reply with exactly this machine-readable block after creating the file:

{HANDOFF_START}
{payload}
{HANDOFF_END}
"""


async def _poll_until_done(runner: ClaudeHeadlessRunner, run_ref: RunRef) -> RunStatus:
    for _ in range(1500):
        status = await runner.poll_run(run_ref)
        if status != "running":
            return status
        await asyncio.sleep(0.1)
    raise AssertionError("real claude headless spike did not finish")
