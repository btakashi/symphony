"""Workflow configuration models and validation."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class ConfigError(ValueError):
    """Raised when workflow config cannot be loaded safely."""


class MissingEnvironmentVariable(ConfigError):
    """Raised when config references an unset environment variable."""


_ENV_TOKEN_RE = re.compile(r"^\$(?P<brace>\{)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?(brace)\})$")


def resolve_env_tokens(value: Any, environ: Mapping[str, str] | None = None) -> Any:
    """Resolve exact ``$VAR`` and ``${VAR}`` string values recursively."""

    source = environ if environ is not None else os.environ

    if isinstance(value, str):
        match = _ENV_TOKEN_RE.match(value)
        if match is None:
            return value
        name = match.group("name")
        if name not in source:
            raise MissingEnvironmentVariable(f"Environment variable {name!r} is not set")
        return source[name]

    if isinstance(value, list):
        items = cast(list[Any], value)
        return [resolve_env_tokens(item, source) for item in items]

    if isinstance(value, dict):
        items = cast(dict[Any, Any], value)
        return {key: resolve_env_tokens(item, source) for key, item in items.items()}

    return value


class StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrackerConfig(StrictConfigModel):
    kind: Literal[
        "beads",
        "memory",
    ]
    command: str = "bd"
    working_directory: Path | None = None
    active_states: list[str] = Field(default_factory=list)
    terminal_states: list[str] = Field(default_factory=list)

    @field_validator("working_directory", mode="before")
    @classmethod
    def expand_working_directory(cls, value: object) -> object:
        if isinstance(value, str):
            return Path(value).expanduser()
        return value


class PollingConfig(StrictConfigModel):
    interval_ms: int = Field(default=5000, ge=100)


class WorkspaceConfig(StrictConfigModel):
    root: Path

    @field_validator("root", mode="before")
    @classmethod
    def expand_root(cls, value: object) -> object:
        if isinstance(value, str):
            return Path(value).expanduser()
        return value

    @field_validator("root")
    @classmethod
    def require_absolute_root(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("workspace.root must resolve to an absolute path")
        return value


class HooksConfig(StrictConfigModel):
    after_create: str | None = None
    before_remove: str | None = None


class AgentConfig(StrictConfigModel):
    provider: Literal["claude"]
    mode: Literal["routine", "channel", "headless"]
    max_concurrent_agents: int = Field(default=1, ge=1)
    max_turns: int = Field(default=1, ge=1)


class ClaudeHeadlessConfig(StrictConfigModel):
    executable: str = "claude"
    args: list[str] = Field(default_factory=lambda: ["-p"])
    prompt_transport: Literal["stdin"] = "stdin"
    completion_artifact: Literal["structured_handoff", "tracker_comment"] = "structured_handoff"
    timeout_seconds: int = Field(default=7200, ge=1)
    kill_grace_seconds: int = Field(default=10, ge=0)


class ClaudeRoutineConfig(StrictConfigModel):
    id: str
    trigger: str = "api"
    completion_artifact: str = "tracker_comment"
    subagents: list[str] = Field(default_factory=list)


class ClaudeChannelConfig(StrictConfigModel):
    session_strategy: Literal["per_issue"] = "per_issue"
    channel_server: str
    require_hooks: bool = True
    require_otel: bool = True


class ClaudeConfig(StrictConfigModel):
    headless: ClaudeHeadlessConfig | None = None
    routine: ClaudeRoutineConfig | None = None
    channel: ClaudeChannelConfig | None = None


class EnvironmentConfig(StrictConfigModel):
    inherit: bool = False
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class ServiceConfig(StrictConfigModel):
    tracker: TrackerConfig
    polling: PollingConfig = Field(default_factory=PollingConfig)
    workspace: WorkspaceConfig
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    agent: AgentConfig
    claude: ClaudeConfig
    environment: EnvironmentConfig = Field(default_factory=EnvironmentConfig)

    @model_validator(mode="after")
    def validate_agent_mode_config(self) -> ServiceConfig:
        if self.agent.mode == "headless" and self.claude.headless is None:
            raise ValueError("agent.mode=headless requires claude.headless config")
        if self.agent.mode == "routine" and self.claude.routine is None:
            raise ValueError("agent.mode=routine requires claude.routine config")
        if self.agent.mode == "channel" and self.claude.channel is None:
            raise ValueError("agent.mode=channel requires claude.channel config")
        return self


def load_config(
    raw_config: Mapping[str, Any], environ: Mapping[str, str] | None = None
) -> ServiceConfig:
    """Resolve environment tokens and validate workflow config."""

    resolved = resolve_env_tokens(dict(raw_config), environ)
    try:
        return ServiceConfig.model_validate(resolved)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc
