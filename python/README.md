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

## Pre-Commit Hooks

Install the repository hook from this directory:

```bash
uv run pre-commit install -c ../.pre-commit-config.yaml
```

Run the hook suite manually:

```bash
uv run pre-commit run --config ../.pre-commit-config.yaml --all-files
```

Clean generated caches:

```bash
uv run poe clean
```

## Branch And PR Workflow

Use stacked PRs for dependent Python Symphony changes. See
[`docs/stacked-pr-workflow.md`](../docs/stacked-pr-workflow.md) for Graphite CLI usage, plain
Git/GitHub fallback commands, branch target conventions, and fork behavior.

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
uv run symphony status
uv run symphony status --json
```

`symphony status` reads `log/status.json` when the daemon has written a current snapshot. If that
file is missing, it falls back to `.symphony/runs/*.json` so recent run attempts remain inspectable
after a process exit or restart.
