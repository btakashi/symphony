"""Prompt rendering for workflow templates."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from symphony.models import Issue, WorkflowDefinition


class PromptError(ValueError):
    """Base class for prompt rendering failures."""


class PromptTemplateParseError(PromptError):
    """Raised when a workflow prompt template is malformed."""


class PromptTemplateRenderError(PromptError):
    """Raised when a workflow prompt template cannot be rendered."""


DEFAULT_PROMPT = "You are working on an issue from Linear."
_TOKEN_RE = re.compile(r"({{.*?}}|{%.*?%})", re.DOTALL)


@dataclass(frozen=True)
class _TextNode:
    value: str


@dataclass(frozen=True)
class _VariableNode:
    expression: str


@dataclass(frozen=True)
class _IfNode:
    condition: str
    true_branch: tuple[_Node, ...]
    false_branch: tuple[_Node, ...]


_Node = _TextNode | _VariableNode | _IfNode


def build_prompt(
    workflow: WorkflowDefinition,
    issue: Issue,
    *,
    attempt: int | None = None,
) -> str:
    """Render the workflow prompt template for an issue."""

    return render_prompt_template(workflow.prompt_template, issue=issue, attempt=attempt)


def render_prompt_template(template: str, *, issue: Issue, attempt: int | None = None) -> str:
    """Render a minimal strict workflow prompt template.

    Supported syntax is intentionally narrow: dotted variable interpolation and
    ``if``/``else``/``endif`` blocks. Unsupported tags, filters, and unknown
    variables fail loudly.
    """

    if not template.strip():
        return DEFAULT_PROMPT

    nodes = _parse_template(template)
    context: Mapping[str, object] = {
        "issue": issue.model_dump(mode="json"),
        "attempt": attempt,
    }
    return "".join(_render_node(node, context) for node in nodes)


def _parse_template(template: str) -> tuple[_Node, ...]:
    tokens = _tokenize(template)
    nodes, position, stop_tag = _parse_nodes(tokens, 0, ())
    if stop_tag is not None:
        raise PromptTemplateParseError(f"Unexpected template tag: {stop_tag}")
    if position != len(tokens):
        raise PromptTemplateParseError("Template parser stopped before consuming all tokens")
    return tuple(nodes)


def _tokenize(template: str) -> list[str]:
    parts = _TOKEN_RE.split(template)
    return [part for part in parts if part]


def _parse_nodes(
    tokens: Sequence[str], position: int, stop_tags: tuple[str, ...]
) -> tuple[list[_Node], int, str | None]:
    nodes: list[_Node] = []
    while position < len(tokens):
        token = tokens[position]
        if token.startswith("{{") and token.endswith("}}"):
            expression = _parse_expression(token[2:-2].strip())
            nodes.append(_VariableNode(expression))
            position += 1
        elif token.startswith("{%") and token.endswith("%}"):
            tag = token[2:-2].strip()
            if tag in stop_tags:
                return nodes, position + 1, tag
            if tag.startswith("if "):
                condition = _parse_expression(tag.removeprefix("if ").strip())
                true_branch, position, stop_tag = _parse_nodes(
                    tokens, position + 1, ("else", "endif")
                )
                false_branch: list[_Node] = []
                if stop_tag == "else":
                    false_branch, position, stop_tag = _parse_nodes(tokens, position, ("endif",))
                if stop_tag != "endif":
                    raise PromptTemplateParseError(f"Missing endif for condition: {condition}")
                nodes.append(_IfNode(condition, tuple(true_branch), tuple(false_branch)))
            else:
                raise PromptTemplateParseError(f"Unsupported template tag: {tag}")
        else:
            nodes.append(_TextNode(token))
            position += 1
    if stop_tags:
        return nodes, position, None
    return nodes, position, None


def _parse_expression(expression: str) -> str:
    if not expression:
        raise PromptTemplateParseError("Template expression cannot be empty")
    if "|" in expression:
        raise PromptTemplateParseError(f"Unsupported template filter in expression: {expression}")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", expression):
        raise PromptTemplateParseError(f"Unsupported template expression: {expression}")
    return expression


def _render_node(node: _Node, context: Mapping[str, object]) -> str:
    match node:
        case _TextNode(value=value):
            return value
        case _VariableNode(expression=expression):
            return _stringify(_resolve_expression(expression, context))
        case _IfNode(condition=condition, true_branch=true_branch, false_branch=false_branch):
            branch = (
                true_branch if _is_truthy(_resolve_expression(condition, context)) else false_branch
            )
            return "".join(_render_node(child, context) for child in branch)


def _resolve_expression(expression: str, context: Mapping[str, object]) -> object:
    current: object = context
    for part in expression.split("."):
        mapping = _string_mapping(current, expression)
        if part not in mapping:
            raise PromptTemplateRenderError(f"Unknown template variable: {expression}")
        current = mapping[part]
    return current


def _string_mapping(value: object, expression: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PromptTemplateRenderError(f"Unknown template variable: {expression}")
    return cast(Mapping[str, object], value)


def _is_truthy(value: object) -> bool:
    return bool(value)


def _stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list | tuple):
        return ", ".join(_stringify(item) for item in cast(Sequence[object], value))
    return str(value)
