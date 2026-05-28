"""Claude Code headless runner backed by ``claude -p`` subprocesses."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from symphony.config import ClaudeHeadlessConfig, EnvironmentConfig
from symphony.models import Issue, RunEvent, RunRef, RunStatus
from symphony.runner.base import RunOptions
from symphony.runtime_paths import stderr_log_path, stdout_log_path

HANDOFF_START = "SYMPHONY_HANDOFF_START"
HANDOFF_END = "SYMPHONY_HANDOFF_END"
LogPathFactory = Callable[[str], Path]


class ClaudeHeadlessRunnerError(RuntimeError):
    """Raised when the Claude headless runner cannot manage a run."""


class HeadlessProcess(Protocol):
    """Subset of ``asyncio.subprocess.Process`` used by the runner."""

    @property
    def pid(self) -> int | None:
        """Process ID when available."""
        ...

    @property
    def returncode(self) -> int | None:
        """Process return code when available."""
        ...

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        """Wait for process completion and return stdout/stderr."""
        ...

    def terminate(self) -> None:
        """Ask the process to exit."""
        ...

    def kill(self) -> None:
        """Forcefully stop the process."""
        ...

    async def wait(self) -> int:
        """Wait for process termination."""
        ...


ProcessFactory = Callable[
    [Sequence[str], Path, Mapping[str, str]],
    Awaitable[HeadlessProcess],
]


class StructuredHandoff(BaseModel):
    """Completion artifact emitted by headless runs."""

    model_config = ConfigDict(extra="allow", frozen=True)

    status: str
    summary: str | None = None
    artifacts: list[Any] = Field(default_factory=list)
    validation: list[Any] = Field(default_factory=list)
    errors: list[Any] = Field(default_factory=list)


@dataclass
class _HeadlessRunState:
    run_ref: RunRef
    issue: Issue
    opts: RunOptions
    process: HeadlessProcess
    stdout_path: Path
    stderr_path: Path
    task: asyncio.Task[None] | None = None
    status: RunStatus = "running"
    events: list[RunEvent] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    error: str | None = None


class ClaudeHeadlessRunner:
    """Run issues through Claude Code's non-interactive print mode."""

    provider = "claude"
    mode = "headless"

    def __init__(
        self,
        config: ClaudeHeadlessConfig,
        *,
        environment: EnvironmentConfig | None = None,
        environ: Mapping[str, str] | None = None,
        process_factory: ProcessFactory | None = None,
        stdout_path_factory: LogPathFactory = stdout_log_path,
        stderr_path_factory: LogPathFactory = stderr_log_path,
    ) -> None:
        self._config = config
        self._environment = environment or EnvironmentConfig()
        self._environ = environ if environ is not None else os.environ
        self._process_factory = process_factory or _start_process
        self._stdout_path_factory = stdout_path_factory
        self._stderr_path_factory = stderr_path_factory
        self._runs: dict[str, _HeadlessRunState] = {}

    async def start_run(self, issue: Issue, prompt: str, opts: RunOptions) -> RunRef:
        run_ref = RunRef(provider=self.provider, mode=self.mode, run_id=f"claude-{uuid4().hex}")
        stdout_path = self._stdout_path_factory(run_ref.run_id)
        stderr_path = self._stderr_path_factory(run_ref.run_id)
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)

        command = [self._config.executable, *self._config.args]
        process = await self._process_factory(command, opts.workspace_path, self._subprocess_env())
        state = _HeadlessRunState(
            run_ref=run_ref,
            issue=issue,
            opts=opts,
            process=process,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        state.events.append(
            self._event(
                state,
                "run_started",
                f"Claude headless runner started {issue.identifier}",
                {
                    "pid": process.pid,
                    "command": command,
                    "stdout_log_path": stdout_path.as_posix(),
                    "stderr_log_path": stderr_path.as_posix(),
                },
            )
        )
        state.task = asyncio.create_task(self._complete_run(state, prompt))
        self._runs[run_ref.run_id] = state
        return run_ref

    async def poll_run(self, run_ref: RunRef) -> RunStatus:
        state = self._state_for(run_ref)
        if state.status in {"succeeded", "failed", "cancelled"}:
            return state.status
        if state.task is None:
            return "running"
        if not state.task.done():
            return "running"
        await state.task
        return state.status

    async def cancel_run(self, run_ref: RunRef) -> None:
        state = self._state_for(run_ref)
        if state.status in {"succeeded", "failed", "cancelled"}:
            return
        await self._stop_process(state)
        if state.task is not None:
            state.task.cancel()
        state.status = "cancelled"
        state.events.append(
            self._event(
                state, "run_cancelled", f"Claude headless runner cancelled {state.issue.identifier}"
            )
        )

    async def fetch_events(self, run_ref: RunRef) -> list[RunEvent]:
        return list(self._state_for(run_ref).events)

    def _state_for(self, run_ref: RunRef) -> _HeadlessRunState:
        state = self._runs.get(run_ref.run_id)
        if state is None:
            raise ClaudeHeadlessRunnerError(f"Unknown Claude headless run: {run_ref.run_id}")
        return state

    async def _complete_run(self, state: _HeadlessRunState, prompt: str) -> None:
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                state.process.communicate(prompt.encode()),
                timeout=self._config.timeout_seconds,
            )
        except TimeoutError:
            await self._stop_process(state)
            state.status = "failed"
            state.error = "Claude headless run timed out"
            state.events.append(
                self._event(
                    state,
                    "run_failed",
                    state.error,
                    {"pid": state.process.pid, "completion_artifact_status": "not_checked"},
                )
            )
            return

        state.stdout = stdout_bytes.decode(errors="replace")
        state.stderr = stderr_bytes.decode(errors="replace")
        state.stdout_path.write_text(state.stdout, encoding="utf-8")
        state.stderr_path.write_text(state.stderr, encoding="utf-8")

        status, message, metadata = _status_from_output(state.process.returncode, state.stdout)
        state.status = status
        state.error = message if status == "failed" else None
        state.events.append(
            self._event(
                state,
                f"run_{status}",
                message,
                {
                    "exit_status": state.process.returncode,
                    "pid": state.process.pid,
                    "stdout_log_path": state.stdout_path.as_posix(),
                    "stderr_log_path": state.stderr_path.as_posix(),
                    "completion_artifact_status": metadata.get("completion_artifact_status"),
                    **metadata,
                },
            )
        )

    async def _stop_process(self, state: _HeadlessRunState) -> None:
        if state.process.returncode is not None:
            return
        state.process.terminate()
        try:
            await asyncio.wait_for(state.process.wait(), timeout=self._config.kill_grace_seconds)
        except TimeoutError:
            state.process.kill()
            await state.process.wait()

    def _subprocess_env(self) -> dict[str, str]:
        if self._environment.inherit:
            values = dict(self._environ)
        else:
            values = {
                key: self._environ[key] for key in self._environment.allow if key in self._environ
            }
        for key in self._environment.deny:
            values.pop(key, None)
        return values

    def _event(
        self,
        state: _HeadlessRunState,
        event_type: str,
        message: str,
        metadata: dict[str, object] | None = None,
    ) -> RunEvent:
        return RunEvent(
            provider=self.provider,
            mode=self.mode,
            tracker_kind=state.opts.tracker_kind,
            issue_id=state.issue.id,
            issue_identifier=state.issue.identifier,
            run_id=state.run_ref.run_id,
            workspace_path=state.opts.workspace_path,
            event_type=event_type,
            message=message,
            metadata=dict(metadata or {}),
            timestamp=datetime.now(UTC),
        )


async def _start_process(
    command: Sequence[str], cwd: Path, env: Mapping[str, str]
) -> HeadlessProcess:
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            env=dict(env),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return cast(HeadlessProcess, process)
    except FileNotFoundError as exc:
        raise ClaudeHeadlessRunnerError(f"Claude executable not found: {command[0]}") from exc


def _status_from_output(
    returncode: int | None, stdout: str
) -> tuple[RunStatus, str, dict[str, str]]:
    if returncode != 0:
        return (
            "failed",
            f"Claude headless exited with status {returncode}",
            {"completion_artifact_status": "not_checked"},
        )

    try:
        handoff = parse_structured_handoff(stdout)
    except ClaudeHeadlessRunnerError as exc:
        return "failed", str(exc), {"completion_artifact_status": "missing_or_invalid"}

    if handoff.status == "succeeded":
        return (
            "succeeded",
            handoff.summary or "Claude headless run succeeded",
            {"completion_artifact_status": "valid"},
        )
    if handoff.status == "failed":
        return (
            "failed",
            handoff.summary or "Claude headless run failed",
            {"completion_artifact_status": "valid"},
        )
    return (
        "failed",
        f"Unsupported handoff status: {handoff.status}",
        {"completion_artifact_status": "unsupported_status"},
    )


def parse_structured_handoff(output: str) -> StructuredHandoff:
    start = output.find(HANDOFF_START)
    end = output.find(HANDOFF_END, start + len(HANDOFF_START))
    if start == -1 or end == -1:
        raise ClaudeHeadlessRunnerError("Missing structured handoff artifact")

    raw_json = output[start + len(HANDOFF_START) : end].strip()
    try:
        data = cast(dict[str, Any], json.loads(raw_json))
        return StructuredHandoff.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ClaudeHeadlessRunnerError("Invalid structured handoff artifact") from exc
