# Symphony

This repository is developing a Python implementation of Symphony while keeping the existing Elixir
reference implementation intact.

## Current Focus

- Build the Python implementation under `python/`.
- Use Beads (`bd`) as the local tracker backend.
- Use Claude headless mode (`claude -p`) as the first real runner after fake-runner coverage.
- Keep implementation aligned with [`SPEC.md`](SPEC.md), [`WORKFLOW.md`](WORKFLOW.md), and the plans
  in [`docs/`](docs/).

## Tooling

- Use `uv` for Python version pinning, dependency management, lockfile, virtualenv, and command
  execution.
- Use Python 3.14.
- Use Ruff for formatting and linting.
- Use basedpyright for type checking.
- Use pytest for unit, integration, live, and spike tests. The default Poe `test` task includes
  coverage reporting.
- Use Beads locally through the `bd` CLI.
- Prefer putting Python tool configuration in `pyproject.toml` whenever the tool supports it. Avoid
  separate config files unless the tool cannot be configured cleanly from `pyproject.toml`.
- Keep implementation as simple as possible. Minimize new custom code and third-party libraries;
  add dependencies only when they remove enough complexity to justify themselves.
- Run routine Python development tasks through Poe from `python/pyproject.toml`:
  - `cd python && uv sync`
  - `cd python && uv run poe check`
  - `cd python && uv run poe format-check`
  - `cd python && uv run poe lint`
  - `cd python && uv run poe typecheck`
  - `cd python && uv run poe test`
  - `cd python && uv run poe clean`
- Prefer narrow command approvals. Good whitelist prefixes for this repo include:
  - `uv run poe`
  - `uv run ruff`
  - `uv run basedpyright`
  - `uv run pytest`
  - `bd`
  Avoid broad approvals such as `uv run` or `rm`.

## Documentation Lookup

When incorporating, choosing, or configuring software dependencies or tools, check the latest
official documentation first. Prefer primary sources such as project docs, release pages, and
official repositories.

Use the `chub` CLI and the Context Hub / get-api-docs skill when available to retrieve current API
documentation. Fall back to direct official documentation lookup when Context Hub is unavailable or
does not cover the software.

## Architecture Decisions

Record meaningful architectural decisions as MADR files under [`docs/adr/`](docs/adr/). Keep ADRs
short, concrete, and current while the plan is still draft.

## Safety

- Do not run agent subprocesses outside the configured issue workspace.
- Default Claude headless runs to an explicit environment allowlist.
- Do not pass secrets through argv.
- Do not treat a successful process exit as task success without the configured completion artifact.
