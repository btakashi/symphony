from pathlib import Path

import pytest

from symphony.config import (
    ConfigError,
    MissingEnvironmentVariable,
    load_config,
    resolve_env_tokens,
)
from symphony.workflow import WorkflowError, load_service_config, parse_workflow_text

VALID_WORKFLOW = """---
tracker:
  kind: beads
  command: bd
workspace:
  root: ~/code/symphony-workspaces
agent:
  provider: claude
  mode: headless
claude:
  headless:
    executable: claude
    args:
      - -p
environment:
  inherit: false
---

Do the work.
"""


def test_parse_workflow_text_splits_front_matter_and_prompt() -> None:
    workflow = parse_workflow_text(VALID_WORKFLOW)

    assert workflow.config["tracker"] == {"kind": "beads", "command": "bd"}
    assert workflow.prompt_template == "Do the work."


def test_parse_workflow_text_rejects_missing_front_matter() -> None:
    with pytest.raises(WorkflowError, match="must start"):
        parse_workflow_text("Do the work.")


def test_load_config_validates_headless_config() -> None:
    workflow = parse_workflow_text(VALID_WORKFLOW)

    config = load_config(workflow.config)

    assert config.tracker.kind == "beads"
    assert config.agent.mode == "headless"
    assert config.claude.headless is not None
    assert config.claude.headless.args == ["-p"]
    assert config.environment.inherit is False


def test_load_config_accepts_github_tracker_with_repository() -> None:
    config = load_config(
        {
            "tracker": {
                "kind": "github",
                "command": "gh",
                "repository": "owner/repo",
            },
            "workspace": {"root": "/tmp/symphony-workspaces"},
            "agent": {"provider": "claude", "mode": "headless"},
            "claude": {"headless": {"executable": "claude"}},
        }
    )

    assert config.tracker.kind == "github"
    assert config.tracker.repository == "owner/repo"
    assert config.tracker.in_progress_label == "symphony:in-progress"


def test_load_config_requires_github_repository() -> None:
    raw_config = {
        "tracker": {"kind": "github"},
        "workspace": {"root": "/tmp/symphony-workspaces"},
        "agent": {"provider": "claude", "mode": "headless"},
        "claude": {"headless": {"executable": "claude"}},
    }

    with pytest.raises(ConfigError, match=r"tracker\.repository"):
        load_config(raw_config)


def test_load_config_accepts_jira_tracker() -> None:
    config = load_config(
        {
            "tracker": {
                "kind": "jira",
                "url": "https://example.atlassian.net",
                "project": "SYMP",
                "username": "person@example.com",
                "api_token": "$JIRA_API_TOKEN",
                "jql": 'project = "SYMP" AND statusCategory != Done',
            },
            "workspace": {"root": "/tmp/symphony-workspaces"},
            "agent": {"provider": "claude", "mode": "headless"},
            "claude": {"headless": {"executable": "claude"}},
        },
        environ={"JIRA_API_TOKEN": "token"},
    )

    assert config.tracker.kind == "jira"
    assert config.tracker.url == "https://example.atlassian.net"
    assert config.tracker.project == "SYMP"
    assert config.tracker.username == "person@example.com"
    assert config.tracker.api_token == "token"


def test_load_config_requires_jira_auth_fields() -> None:
    raw_config = {
        "tracker": {"kind": "jira", "url": "https://example.atlassian.net"},
        "workspace": {"root": "/tmp/symphony-workspaces"},
        "agent": {"provider": "claude", "mode": "headless"},
        "claude": {"headless": {"executable": "claude"}},
    }

    with pytest.raises(ConfigError, match=r"tracker\.project"):
        load_config(raw_config)


def test_load_config_requires_selected_mode_config() -> None:
    raw_config = {
        "tracker": {"kind": "beads"},
        "workspace": {"root": "/tmp/symphony-workspaces"},
        "agent": {"provider": "claude", "mode": "routine"},
        "claude": {"headless": {"executable": "claude"}},
    }

    with pytest.raises(ConfigError, match=r"agent\.mode=routine"):
        load_config(raw_config)


def test_resolve_env_tokens_replaces_exact_tokens() -> None:
    value = {
        "api_key": "$TOKEN",
        "literal": "prefix-$TOKEN",
        "nested": ["${TOKEN}"],
    }

    resolved = resolve_env_tokens(value, {"TOKEN": "secret"})

    assert resolved == {
        "api_key": "secret",
        "literal": "prefix-$TOKEN",
        "nested": ["secret"],
    }


def test_resolve_env_tokens_rejects_missing_env() -> None:
    with pytest.raises(MissingEnvironmentVariable, match="TOKEN"):
        resolve_env_tokens("$TOKEN", {})


def test_workspace_root_must_be_absolute_after_expansion() -> None:
    raw_config = {
        "tracker": {"kind": "beads"},
        "workspace": {"root": "relative/path"},
        "agent": {"provider": "claude", "mode": "headless"},
        "claude": {"headless": {"executable": "claude"}},
    }

    with pytest.raises(ConfigError, match=r"workspace\.root"):
        load_config(raw_config)


def test_root_workflow_config_is_valid() -> None:
    root_workflow = Path(__file__).parents[2] / "WORKFLOW.md"

    config = load_service_config(root_workflow)

    assert config.tracker.kind == "beads"
    assert config.agent.provider == "claude"
    assert config.agent.mode == "headless"
    assert config.claude.headless is not None
