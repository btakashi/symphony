"""WORKFLOW.md loading and front matter parsing."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import yaml

from symphony.config import ConfigError, ServiceConfig, load_config
from symphony.models import WorkflowDefinition


class WorkflowError(ValueError):
    """Raised when a workflow file is missing or malformed."""


def parse_workflow_text(text: str) -> WorkflowDefinition:
    """Parse YAML front matter and Markdown prompt body from workflow text."""

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise WorkflowError("WORKFLOW.md must start with YAML front matter delimiter '---'")

    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing_index is None:
        raise WorkflowError("WORKFLOW.md front matter is missing closing delimiter '---'")

    front_matter = "\n".join(lines[1:closing_index])
    prompt_template = "\n".join(lines[closing_index + 1 :]).strip()

    loaded: Any = yaml.safe_load(front_matter)
    if loaded is None:
        config: dict[str, Any] = {}
    elif isinstance(loaded, dict):
        config = _string_key_mapping(cast(dict[object, object], loaded))
    else:
        raise WorkflowError("WORKFLOW.md front matter must be a YAML mapping")

    return WorkflowDefinition(config=config, prompt_template=prompt_template)


def load_workflow(path: Path | str) -> WorkflowDefinition:
    """Load and parse a workflow file."""

    workflow_path = Path(path)
    try:
        return parse_workflow_text(workflow_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise WorkflowError(f"Unable to read workflow file {workflow_path}") from exc


def load_service_config(
    path: Path | str,
    environ: Mapping[str, str] | None = None,
) -> ServiceConfig:
    """Load a workflow file and validate its service config."""

    workflow = load_workflow(path)
    try:
        return load_config(workflow.config, environ)
    except ConfigError:
        raise


def _string_key_mapping(value: dict[object, object]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise WorkflowError("WORKFLOW.md front matter keys must be strings")
        result[key] = item
    return result
