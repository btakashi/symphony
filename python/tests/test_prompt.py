from pathlib import Path

import pytest

from symphony.models import Issue
from symphony.prompt import (
    DEFAULT_PROMPT,
    PromptTemplateParseError,
    PromptTemplateRenderError,
    build_prompt,
    render_prompt_template,
)
from symphony.workflow import load_workflow


def test_build_prompt_renders_root_workflow_snapshot() -> None:
    workflow = load_workflow(Path(__file__).parents[2] / "WORKFLOW.md")
    issue = Issue(
        id="issue-internal-1",
        identifier="symphony-123",
        title="Implement the thing",
        description="Use the existing project style.",
        state="open",
        labels=("python", "backend"),
        url="https://example.test/symphony-123",
    )

    prompt = build_prompt(workflow, issue)

    assert (
        prompt
        == """You are working on a Beads issue for the Python Symphony implementation.

Issue context:
ID: symphony-123
Title: Implement the thing
Current status: open
Labels: python, backend
URL: https://example.test/symphony-123

Description:

Use the existing project style.


Instructions:

1. Work only in the provided repository workspace.
2. Use Beads as the source of truth for task state.
3. Start by reading the issue with `bd show symphony-123 --json`.
4. Claim the issue before implementation when supported by Beads.
5. Keep implementation focused on the issue scope.
6. Run the relevant validation before handoff.
7. Record discovered follow-up work as new Beads issues instead of expanding scope.
8. Do not treat a successful process exit as task success without a structured handoff block.

Quality gates:

- Full local gate: `cd python && uv run poe check`
- Format check: `cd python && uv run poe format-check`
- Lint: `cd python && uv run poe lint`
- Type check: `cd python && uv run poe typecheck`
- Unit tests: `cd python && uv run poe test`

Final response must include this exact machine-readable block:

SYMPHONY_HANDOFF_START
{"status":"succeeded","summary":"<short summary>","artifacts":[],"validation":[],"errors":[]}
SYMPHONY_HANDOFF_END"""
    )


def test_build_prompt_renders_missing_description_snapshot() -> None:
    template = """Issue: {{ issue.identifier }}
Description:
{% if issue.description %}
{{ issue.description }}
{% else %}
No description provided.
{% endif %}
Attempt: {{ attempt }}"""
    issue = Issue(
        id="issue-internal-1",
        identifier="symphony-123",
        title="Implement the thing",
        description=None,
        state="open",
    )

    prompt = render_prompt_template(template, issue=issue, attempt=None)

    assert (
        prompt
        == """Issue: symphony-123
Description:

No description provided.

Attempt: """
    )


def test_render_prompt_uses_default_for_empty_template() -> None:
    issue = Issue(id="issue-internal-1", identifier="symphony-123", title="Title", state="open")

    assert render_prompt_template("  \n", issue=issue) == DEFAULT_PROMPT


def test_render_prompt_rejects_unknown_variable() -> None:
    issue = Issue(id="issue-internal-1", identifier="symphony-123", title="Title", state="open")

    with pytest.raises(PromptTemplateRenderError, match=r"issue\.missing"):
        render_prompt_template("{{ issue.missing }}", issue=issue)


def test_render_prompt_rejects_unsupported_filters() -> None:
    issue = Issue(id="issue-internal-1", identifier="symphony-123", title="Title", state="open")

    with pytest.raises(PromptTemplateParseError, match="filter"):
        render_prompt_template("{{ issue.title | upcase }}", issue=issue)


def test_render_prompt_rejects_unsupported_tags() -> None:
    issue = Issue(id="issue-internal-1", identifier="symphony-123", title="Title", state="open")

    with pytest.raises(PromptTemplateParseError, match="Unsupported template tag"):
        render_prompt_template("{% for label in issue.labels %}{{ label }}{% endif %}", issue=issue)
