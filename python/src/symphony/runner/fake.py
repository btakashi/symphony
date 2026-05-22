"""Deterministic fake runner for tests and local orchestration."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import Field

from symphony.models import Issue, RunEvent, RunRef, RunStatus, SymphonyModel
from symphony.runner.base import RunOptions

FakeOutcome = Literal["success", "failure", "waiting"]


class FakeRunnerError(RuntimeError):
    """Raised when the fake runner is used with an unknown run."""


class FakeRunScript(SymphonyModel):
    """Scripted fake-runner behavior for one run."""

    outcome: FakeOutcome = "success"
    running_polls: int = Field(default=0, ge=0)
    message: str | None = None


class _FakeRunState(SymphonyModel):
    run_ref: RunRef
    issue: Issue
    prompt: str
    opts: RunOptions
    script: FakeRunScript
    polls: int = 0
    status: RunStatus = "queued"
    events: tuple[RunEvent, ...] = ()


class FakeRunner:
    """Runner implementation with deterministic in-memory state."""

    provider = "fake"
    mode = "fake"

    def __init__(
        self,
        *,
        scripts_by_identifier: dict[str, Iterable[FakeRunScript]] | None = None,
    ) -> None:
        self._scripts_by_identifier = {
            identifier: deque(scripts)
            for identifier, scripts in (scripts_by_identifier or {}).items()
        }
        self._runs: dict[str, _FakeRunState] = {}
        self.started_prompts: dict[str, str] = {}

    async def start_run(self, issue: Issue, prompt: str, opts: RunOptions) -> RunRef:
        run_ref = RunRef(provider=self.provider, mode=self.mode, run_id=f"fake-{uuid4().hex}")
        script = self._next_script(issue.identifier)
        started_event = _event(
            run_ref=run_ref,
            issue=issue,
            opts=opts,
            event_type="run_started",
            message=f"Fake runner started {issue.identifier}",
            metadata={"attempt": opts.attempt, "outcome": script.outcome},
        )
        state = _FakeRunState(
            run_ref=run_ref,
            issue=issue,
            prompt=prompt,
            opts=opts,
            script=script,
            status="running",
            events=(started_event,),
        )
        self._runs[run_ref.run_id] = state
        self.started_prompts[run_ref.run_id] = prompt
        return run_ref

    async def poll_run(self, run_ref: RunRef) -> RunStatus:
        state = self._state_for(run_ref)
        if state.status in {"succeeded", "failed", "cancelled", "waiting_for_permission"}:
            return state.status

        polls = state.polls + 1
        if polls <= state.script.running_polls:
            self._runs[run_ref.run_id] = state.model_copy(
                update={"polls": polls, "status": "running"}
            )
            return "running"

        status = _terminal_status(state.script.outcome)
        event_type = f"run_{status}"
        message = state.script.message or f"Fake runner {status} {state.issue.identifier}"
        events = (
            *state.events,
            _event(
                run_ref=run_ref,
                issue=state.issue,
                opts=state.opts,
                event_type=event_type,
                message=message,
                metadata={"polls": polls},
            ),
        )
        self._runs[run_ref.run_id] = state.model_copy(
            update={"polls": polls, "status": status, "events": events}
        )
        return status

    async def cancel_run(self, run_ref: RunRef) -> None:
        state = self._state_for(run_ref)
        if state.status in {"succeeded", "failed", "cancelled"}:
            return

        events = (
            *state.events,
            _event(
                run_ref=run_ref,
                issue=state.issue,
                opts=state.opts,
                event_type="run_cancelled",
                message=f"Fake runner cancelled {state.issue.identifier}",
            ),
        )
        self._runs[run_ref.run_id] = state.model_copy(
            update={"status": "cancelled", "events": events}
        )

    async def fetch_events(self, run_ref: RunRef) -> list[RunEvent]:
        return list(self._state_for(run_ref).events)

    def _next_script(self, identifier: str) -> FakeRunScript:
        scripts = self._scripts_by_identifier.get(identifier)
        if scripts is None or not scripts:
            return FakeRunScript()
        return scripts.popleft()

    def _state_for(self, run_ref: RunRef) -> _FakeRunState:
        state = self._runs.get(run_ref.run_id)
        if state is None:
            raise FakeRunnerError(f"Unknown fake run: {run_ref.run_id}")
        return state


def _terminal_status(outcome: FakeOutcome) -> RunStatus:
    match outcome:
        case "success":
            return "succeeded"
        case "failure":
            return "failed"
        case "waiting":
            return "waiting_for_permission"


def _event(
    *,
    run_ref: RunRef,
    issue: Issue,
    opts: RunOptions,
    event_type: str,
    message: str,
    metadata: dict[str, object] | None = None,
) -> RunEvent:
    return RunEvent(
        provider=run_ref.provider,
        mode=run_ref.mode,
        tracker_kind=opts.tracker_kind,
        issue_id=issue.id,
        issue_identifier=issue.identifier,
        run_id=run_ref.run_id,
        workspace_path=opts.workspace_path,
        event_type=event_type,
        message=message,
        metadata=dict(metadata or {}),
        timestamp=datetime.now(UTC),
    )
