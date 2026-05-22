# Symphony Python

Python implementation of Symphony.

## Setup

This project uses `uv` only for Python version pinning, dependency management, virtualenvs, and
command execution.

```bash
uv sync
```

## Quality Gates

Run the default local gate through Poe:

```bash
uv run poe check
```

The `test` task includes coverage reporting for the `symphony` package.

Individual gates are also available:

```bash
uv run poe format-check
uv run poe lint
uv run poe typecheck
uv run poe test
```

Clean generated caches:

```bash
uv run poe clean
```

## Optional Tests

Optional suites can be run through pytest directly:

```bash
uv run pytest -m integration
uv run pytest -m live
uv run pytest -m spike
```

## CLI

```bash
uv run symphony --help
```
