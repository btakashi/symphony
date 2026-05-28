"""Core domain models used by Symphony orchestration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SymphonyModel(BaseModel):
    """Base model with strict boundaries for external data."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class BlockerRef(SymphonyModel):
    id: str | None = None
    identifier: str | None = None
    state: str | None = None


class Issue(SymphonyModel):
    id: str
    identifier: str
    title: str
    description: str | None = None
    priority: int | None = None
    state: str
    branch_name: str | None = None
    url: str | None = None
    labels: tuple[str, ...] = ()
    blocked_by: tuple[BlockerRef, ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorkflowDefinition(SymphonyModel):
    config: dict[str, Any]
    prompt_template: str


RunStatus = Literal[
    "queued",
    "starting",
    "running",
    "waiting_for_permission",
    "succeeded",
    "failed",
    "cancelled",
    "unknown",
]


class Workspace(SymphonyModel):
    path: Path
    workspace_key: str
    created_now: bool = False


class RunRef(SymphonyModel):
    provider: str
    mode: str
    run_id: str


class RunAttempt(SymphonyModel):
    issue_id: str
    issue_identifier: str
    attempt: int | None = None
    workspace_path: Path
    started_at: datetime
    status: RunStatus
    error: str | None = None


class RunMetadata(SymphonyModel):
    provider: str
    mode: str
    tracker_kind: str
    issue_id: str
    issue_identifier: str
    run_id: str
    attempt: int | None = None
    workspace_path: Path
    status: RunStatus
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunEvent(SymphonyModel):
    provider: str
    mode: str
    tracker_kind: str
    issue_id: str
    issue_identifier: str
    run_id: str
    session_id: str | None = None
    agent_id: str | None = None
    workspace_path: Path
    event_type: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class RetryEntry(SymphonyModel):
    issue_id: str
    identifier: str
    attempt: int = Field(ge=1)
    due_at_ms: int = Field(ge=0)
    error: str | None = None


class StatusSnapshot(SymphonyModel):
    generated_at: datetime
    active_runs: tuple[RunAttempt, ...] = ()
    retry_queue: tuple[RetryEntry, ...] = ()
