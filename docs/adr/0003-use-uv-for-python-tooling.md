# 0003. Use uv for Python Tooling

## Status

Accepted

## Context and Problem Statement

The Python implementation needs a repeatable way to manage the Python version, virtual environment,
dependencies, lockfile, and tool execution. The project does not need a second runtime manager for
the Python-only implementation.

## Decision Drivers

- Keep setup simple for Python contributors.
- Use one tool for Python version pinning, dependency resolution, virtualenv management, and command
  execution.
- Keep formatting, linting, type checking, and tests runnable through a consistent command prefix.
- Avoid introducing `mise` only for Python when `uv` can manage the needed Python workflow.
- Prefer standard Python project metadata and tool configuration in `pyproject.toml`.
- Keep development commands simple and discoverable.

## Considered Options

- `uv` only.
- `mise` plus `uv`.
- Poetry.
- Standard `venv` and `pip`.

## Decision Outcome

Use `uv` only for the Python implementation.

`uv` owns:

- `.python-version`
- virtual environment management
- dependency resolution
- `uv.lock`
- command execution through `uv run`

Python tool configuration should live in `pyproject.toml` whenever the tool supports it.
Use Poe the Poet for simple pyproject-defined development tasks such as `check`, `lint`,
`typecheck`, and `test`.

## Consequences

- Contributors should use `uv run` for project commands.
- Contributors should use `uv run poe <task>` for common development tasks.
- The Python project should not add `mise.toml`, Poetry files, or separate Python tool runners unless
  a later ADR supersedes this decision.
- Separate config files should be avoided when equivalent `pyproject.toml` configuration is
  supported.
- Custom Python helper code should stay minimal; prefer pyproject tasks for simple command aliases.
- Existing Elixir `mise` configuration remains unchanged and separate.

## Links

- https://docs.astral.sh/uv/
