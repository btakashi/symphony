# 0006. Use basedpyright for Type Checking

## Status

Accepted

## Context and Problem Statement

The Python Symphony implementation needs a type checker that works well in a `uv`-only Python
toolchain, can be pinned as a project dependency, and is strict enough for a greenfield service.
The team considered Pyright because it aligns closely with VS Code/Pylance, but the official
Pyright distribution is Node/npm-based.

## Decision Drivers

- Keep the Python implementation's tooling installable and runnable through `uv`.
- Avoid adding Node/npm only for type checking.
- Prefer strict defaults for a new codebase.
- Preserve broad compatibility with Pyright-style typing behavior.
- Keep CI and local command execution simple.

## Considered Options

- Pyright.
- basedpyright.
- mypy.
- ty.
- Pyrefly.
- Zuban.

## Decision Outcome

Use basedpyright as the primary type checker.

Run it through `uv`:

```bash
uv add --dev basedpyright
uv run basedpyright
```

Configure it in `pyproject.toml` with strict checking for `src` and `tests`.

## Consequences

- The project can keep a Python-only `uv` toolchain.
- Type checking is expected to be stricter than default Pyright/Pylance behavior.
- VS Code/Pylance diagnostics may not match CI exactly.
- If IDE/CI mismatch becomes a material problem, a future ADR can supersede this decision and move
  to Pyright.

## Links

- https://docs.basedpyright.com/
- https://github.com/microsoft/pyright
- [`0003-use-uv-for-python-tooling.md`](0003-use-uv-for-python-tooling.md)
