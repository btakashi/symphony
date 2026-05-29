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
uv run symphony run-once --workflow ../WORKFLOW.md
uv run symphony status
uv run symphony status --json
```

`symphony run-once` loads `WORKFLOW.md`, checks the local Beads CLI, claims the first ready issue,
creates or reuses its workspace, runs `hooks.after_create` for new workspaces, and dispatches the
issue through the configured `claude.headless` runner. Fresh run-once workspaces are created as git
worktrees so the dispatched agent retains local Beads access from inside the workspace.

`symphony status` reads `log/status.json` when the daemon has written a current snapshot. If that
file is missing, it falls back to `.symphony/runs/*.json` so recent run attempts remain inspectable
after a process exit or restart.

## Trackers

The default local workflow uses Beads:

```yaml
tracker:
  kind: beads
  command: bd
```

GitHub Issues can be selected with the local `gh` CLI:

```yaml
tracker:
  kind: github
  command: gh
  repository: owner/repo
  in_progress_label: symphony:in-progress
```

`tracker.kind=github` requires `gh auth status` to pass before dispatch. Symphony claims issues by
adding `in_progress_label`, filters that label out of future candidates, comments when requested,
and closes issues after succeeded runs.

## Smoke Tests

- 2026-05-28: Confirmed the Python Symphony PoC can dispatch Claude Code through Beads worktrees
  and inspect completed runs.
- 2026-05-28: Confirmed the PoC can publish a completed Claude Code worktree as a draft PR.
- 2026-05-29: Confirmed the GitHub Issues tracker (`tracker.kind=github`) live smoke ran through
  Claude Code.
