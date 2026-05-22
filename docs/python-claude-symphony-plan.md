# Python Symphony Plan: Claude Runners

## Purpose

Build a Python implementation of Symphony for teams where Python is the supported service language.
This plan builds on:

- [`../SPEC.md`](../SPEC.md), the language-agnostic Symphony service specification.
- [`claude-runner-routines-channels-plan.md`](claude-runner-routines-channels-plan.md), the Claude
  runner plan for Routines, Channels, and `claude -p` headless mode.

The Python implementation should preserve the orchestration contract from the original plan:
tracker polling, normalized issues, per-issue workspaces, bounded concurrency, retries,
reconciliation, runner cancellation, and completion artifacts must remain independent from the
selected Claude transport.

## Porting Strategy

Use the Elixir implementation as a behavioral reference, not as a structural template. Python should
lean on a small `asyncio` service core, typed configuration models, explicit runner/tracker
interfaces, and subprocess/API clients that are easy to test with fakes.

Use Python 3.14 and `uv` as the Python project manager. Do not introduce `mise`, Poetry, or a
separate Python tool runner unless a later ADR supersedes this decision. `uv` should own the Python
version pin, virtual environment, dependency resolution, lockfile, and command execution.

Use Ruff for formatting and linting, basedpyright for type checking, and pytest for tests. Run all
Python tools through `uv run`. Prefer putting Python tool configuration in `pyproject.toml` whenever
the tool supports it.

Recommended default order:

1. Build the Python core around `claude.headless` / `claude -p` first because it validates the
   runner boundary with the simplest transport.
2. Add tracker adapters after the runner contract is stable.
3. Add Claude Routines after the Routine API, billing, caps, completion, and subagent spikes are
   documented.
4. Add Claude Channels after local channel transport and telemetry correlation are documented.

Do not implement a full production runner before the validation spikes in the Claude runner plan
are complete or explicitly marked unsupported with fallback behavior.

## Proposed Package Layout

```text
python/
  pyproject.toml
  uv.lock
  .python-version
  README.md
  src/
    symphony/
      __init__.py
      cli.py
      config.py
      events.py
      log_events.py
      orchestrator.py
      prompt.py
      status.py
      workflow.py
      workspace.py
      tracker/
        __init__.py
        base.py
        memory.py
        beads.py
        linear.py
        github_issues.py
        jira.py
        clickup.py
        dolt.py
      runner/
        __init__.py
        base.py
        fake.py
        claude_headless.py
        claude_routine.py
        claude_channel.py
  tests/
    unit/
    integration/
    spikes/
```

Start with `memory` tracker and `fake` runner tests so the orchestrator can be tested without
network access, credentials, Claude, or a real issue tracker. Use Beads as the first real local
tracker backend.

## Core Interfaces

### Runner

Model the original runner boundary as an async protocol:

```python
class Runner(Protocol):
    async def start_run(self, issue: Issue, prompt: str, opts: RunOptions) -> RunRef: ...
    async def poll_run(self, run_ref: RunRef) -> RunStatus: ...
    async def cancel_run(self, run_ref: RunRef) -> None: ...
    async def fetch_events(self, run_ref: RunRef) -> list[RunEvent]: ...
```

Normalized statuses:

- `queued`
- `starting`
- `running`
- `waiting_for_permission`
- `succeeded`
- `failed`
- `cancelled`
- `unknown`

Run success must require the configured completion artifact. A green provider status, session state,
subprocess exit code, or HTTP response is infrastructure status only.

### Tracker

Model trackers as async adapters:

```python
class Tracker(Protocol):
    async def fetch_candidate_issues(self) -> list[Issue]: ...
    async def fetch_issues_by_states(self, state_names: list[str]) -> list[Issue]: ...
    async def fetch_issue_states_by_ids(self, issue_ids: list[str]) -> dict[str, str]: ...
    async def create_comment(self, issue_id: str, body: str) -> None: ...
    async def update_issue_state(self, issue_id: str, state_name: str) -> None: ...
```

Comment and state update can be optional capabilities. The orchestrator should check adapter
capabilities before using writeback.

### Beads Tracker

Use Beads (`bd`) as the bootstrap local tracker backend.

Beads runs locally in embedded mode by default, with no DoltHub remote required. The first adapter
should shell out to the `bd` CLI and use JSON output rather than depending on Beads internals.

Initial command mapping:

```text
fetch_candidate_issues()      -> bd ready --json
fetch_issue_states_by_ids()   -> bd show <id> --json
create_comment(issue, body)   -> bd comment <id> <body> --json
claim issue                   -> bd update <id> --claim --json
close issue                   -> bd close <id> --json
```

The adapter must validate that `bd` is installed, parse JSON defensively, and normalize Beads issues
into the same `Issue` model used by hosted trackers.

For local solo development, initialize Beads with:

```bash
bd init --quiet --stealth --skip-agents --skip-hooks --non-interactive
```

Rationale:

- `--stealth` keeps Beads local to the repository and avoids normal repo tracking setup.
- `--skip-agents` prevents Beads from creating or modifying agent instruction files.
- `--skip-hooks` prevents Beads from installing git hooks.
- `--non-interactive` makes setup repeatable for scripts and tests.

Use `bd bootstrap --yes` for recovery or fresh clones once Beads state conventions are established.

### Domain Models

Use Pydantic v2 models for config and external data boundaries:

- `Issue`
- `BlockerRef`
- `WorkflowDefinition`
- `ServiceConfig`
- `Workspace`
- `RunAttempt`
- `RunRef`
- `RunEvent`
- `RetryEntry`
- `StatusSnapshot`

Use dataclasses only for small internal ephemeral structs when Pydantic validation is unnecessary.

## Configuration

Keep the same workflow front matter contract from the Claude runner plan:

```yaml
tracker:
  kind: beads
  command: bd
  active_states: ["open", "in_progress"]
  terminal_states: ["closed"]

agent:
  provider: claude
  mode: headless # routine | channel | headless
  max_concurrent_agents: 2
  max_turns: 1

claude:
  headless:
    executable: claude
    args: ["-p"]
    prompt_transport: stdin
    completion_artifact: structured_handoff
    timeout_seconds: 7200
    kill_grace_seconds: 10

environment:
  inherit: false
  allow:
    - HOME
    - PATH
    - SHELL
    - TERM
    - USER
    - LOGNAME
    - TMPDIR
    - ANTHROPIC_API_KEY
    - GITHUB_TOKEN
  deny: []
```

Python-specific validation rules:

- Resolve `$ENV_VAR` references once at config load time.
- Reject unsupported `tracker.kind`, `agent.provider`, and `agent.mode` before dispatch.
- Reject relative workspace roots after normalization.
- Reject workspaces that resolve outside the configured workspace root.
- Require `claude.headless.executable`, `claude.headless.args`, and timeout settings for
  `agent.mode=headless`.
- Require Routine and Channel settings only when those modes are selected.
- Default headless subprocesses to an explicit environment allowlist instead of inheriting the full
  parent environment.

## Claude Headless First Milestone

Implement `runner/claude_headless.py` first.

Behavior:

- Launch one `asyncio.create_subprocess_exec` subprocess per active issue workspace.
- Run with `cwd` set to the issue workspace.
- Pass prompt content over stdin by default.
- Capture stdout and stderr incrementally.
- Write full stdout/stderr logs to run-specific log files.
- Maintain recent output summaries for status.
- Enforce timeout with cancellation.
- On cancellation, terminate the subprocess first, then kill after a grace period.
- Parse the configured completion artifact from output or verify an external artifact.
- Return failure if the process exits without the required artifact.

Headless run metadata:

- `provider`
- `mode`
- `run_id`
- `process_id`
- `workspace_path`
- `started_at`
- `ended_at`
- `exit_status`
- `signal`
- `stdout_log_path`
- `stderr_log_path`
- `last_output_summary`
- `completion_artifact_status`

Structured handoff block:

```text
SYMPHONY_HANDOFF_START
{"status":"succeeded","summary":"...","artifacts":[],"validation":[],"errors":[]}
SYMPHONY_HANDOFF_END
```

The content between delimiters must be JSON. Invalid JSON, missing delimiters, or an unsupported
`status` value makes the run fail even if the subprocess exits successfully.

## Orchestrator Design

Use `asyncio` tasks and explicit state rather than threads.

Responsibilities:

- Poll tracker on a fixed interval.
- Normalize and sort candidate issues.
- Respect `max_concurrent_agents`.
- Avoid dispatching blocked issues.
- Create/reuse safe workspaces.
- Build prompt from issue context and workflow prompt body.
- Start runner attempts.
- Poll active runs and fetch events.
- Cancel active runs when tracker state becomes ineligible.
- Retry transient failures with exponential backoff.
- Clean terminal-state workspaces according to config.
- Emit structured status snapshots and logs.

Keep scheduler coordination in memory for the first version, but write a durable run ledger for every
started run so process crashes and partial runs are inspectable.

Runtime state paths:

```text
python/.symphony/runs/<run_id>.json
python/log/events.jsonl
python/log/status.json
python/log/runs/<run_id>/stdout.log
python/log/runs/<run_id>/stderr.log
```

Beads remains the source of truth for issue state. The run ledger is Symphony's process-level record
of attempts, subprocess metadata, completion artifacts, and log paths.

## Logging And Status

Start with JSON logs and a CLI status command. A web dashboard can come later.

Every log/event should include:

- `provider`
- `mode`
- `tracker_kind`
- `issue_id`
- `issue_identifier`
- `run_id`
- `session_id` when available
- `agent_id` when available
- `workspace_path`
- `event_type`
- `message`
- `metadata`
- `timestamp`

For headless mode, include process metadata and log file paths. For Routine and Channel modes, use
the event fields from the Claude runner plan.

The status CLI should read `python/log/status.json` first and fall back to run ledger files when the
daemon is not running.

## Architecture Decision Records

Record architectural decisions in MADR format under `docs/adr/`.

Initial ADRs:

- `0001-record-architecture-decisions.md`
- `0002-use-python-for-symphony-implementation.md`
- `0003-use-uv-for-python-tooling.md`
- `0004-use-beads-for-local-tracker-backend.md`
- `0005-start-with-claude-headless-runner.md`
- `0006-use-basedpyright-for-type-checking.md`
- `0007-use-pydantic-v2-for-config-and-boundary-models.md`
- `0008-use-environment-allowlist-for-headless-runs.md`

Minimum MADR sections:

- `# <number>. <title>`
- `## Status`
- `## Context and Problem Statement`
- `## Decision Drivers`
- `## Considered Options`
- `## Decision Outcome`
- `## Consequences`
- `## Links`

Keep ADRs short and concrete. Update them by adding superseding ADRs rather than rewriting history,
unless correcting typos or clarifying wording before a decision is adopted.

## Testing Plan

Unit tests:

- Workflow front matter parsing.
- Config defaults, environment resolution, and validation failures.
- Workspace path safety and sanitization.
- Prompt rendering.
- Handoff block parsing.
- Tracker normalization.
- Beads CLI command mapping, JSON parsing, and missing-command errors.
- Runner protocol behavior using fake runners.

Orchestrator tests:

- Dispatch respects active states and concurrency.
- Retry backoff schedules failures without duplicate dispatch.
- Reconciliation cancels ineligible active issues.
- Terminal-state cleanup is invoked.
- Runner mode does not alter orchestration semantics.

Headless tests:

- Subprocess success with valid handoff.
- Exit code `0` without handoff is failure.
- Nonzero exit with logs is failure.
- Timeout terminates the subprocess.
- Cancellation terminates the subprocess.
- Stdout/stderr logs are captured.
- Workspace cwd is enforced.

Integration/spike tests:

- Real `claude -p` smoke test, gated by env vars.
- Routine API smoke test, gated by env vars.
- Channel local-session smoke test, gated by env vars.
- Tracker writeback tests, gated by tracker credentials.

Pytest markers:

```toml
[tool.pytest.ini_options]
markers = [
  "unit: fast deterministic tests with no external services",
  "integration: local integration tests that may use subprocesses or temporary Beads databases",
  "live: tests that call external services or real Claude",
  "spike: exploratory validation tests that are not part of the default gate",
]
```

Default test command:

```bash
uv run pytest -m "not integration and not live and not spike"
```

## Phased Implementation

### Phase 0: Repository Setup

- Add `python/` project with `pyproject.toml`, `uv.lock`, `.python-version`, formatter, linter,
  type checker, and test runner.
- Add a Python README with local setup and development commands.
- Add CI or local make targets if this repo expects them.
- Add initial MADR records for Python, `uv`, basedpyright, Beads tracker bootstrap, and
  headless-first runner implementation.

Exit criteria:

- `uv run pytest` runs.
- `uv run ruff format --check .`, `uv run ruff check .`, and `uv run basedpyright` run.
- Pytest markers for `unit`, `integration`, `live`, and `spike` are configured.
- Unit test, integration test, and live/spike test commands are documented.

### Phase 1: Config, Workflow, And Models

- Implement `workflow.py`, `config.py`, and core domain models.
- Parse `WORKFLOW.md` front matter and prompt body.
- Validate the Claude config shape from the original plan.
- Implement Pydantic v2 models for config and external data boundaries.

Exit criteria:

- Config tests cover valid headless, routine, and channel examples.
- Invalid tracker/agent modes fail before dispatch.
- Environment allowlist behavior is covered by tests.

### Phase 2: Workspace And Prompt Builder

- Implement workspace key sanitization and path safety.
- Implement prompt rendering from normalized issue context plus workflow prompt.
- Add the structured handoff requirement to headless prompts.

Exit criteria:

- Workspaces cannot escape configured root.
- Prompt snapshots are stable enough for review.

### Phase 3: Runner Boundary And Headless Runner

- Implement `runner/base.py`, `runner/fake.py`, and `runner/claude_headless.py`.
- Capture output logs and parse structured handoff blocks.
- Implement timeout and cancellation behavior.

Exit criteria:

- Fake runner contract tests pass.
- Headless subprocess tests pass without requiring Claude.
- Real `claude -p` spike remains gated by env vars.

### Phase 4: Tracker Boundary

- Implement `tracker/base.py`, `tracker/memory.py`, and `tracker/beads.py`.
- Use `memory` for deterministic tests and Beads for the first real local tracker.
- Add hosted tracker adapters later, preferably GitHub Issues or Linear first.
- Keep Jira, ClickUp, and direct Dolt integrations behind documented spike results.

Exit criteria:

- Memory tracker drives deterministic orchestrator tests.
- Beads adapter can fetch, claim, comment on, close, and normalize local candidate issues.

### Phase 5: Orchestrator

- Implement the polling loop, concurrency, retries, reconciliation, cancellation, cleanup, and
  status snapshots.
- Use fake runner and memory tracker for deterministic tests.

Exit criteria:

- The daemon can process one memory issue end to end through the fake runner.
- The daemon can process one Beads issue through `claude.headless` when local Beads and Claude are
  available.

### Phase 6: Routine And Channel Runners

- Implement Routine and Channel runners only after their validation spikes are documented.
- Reuse the same runner protocol and completion artifact rules.

Exit criteria:

- The same normalized issue can run through headless, routine, or channel mode without tracker or
  orchestrator changes.

### Phase 7: Operational Hardening

- Add restart recovery behavior.
- Add richer status output.
- Add provider/tracker compatibility docs.
- Add packaging and deployment guidance for the company environment.

Exit criteria:

- Operators can understand active runs, failed runs, retry state, workspaces, and artifacts from
  logs/status alone.

## Open Decisions

- First hosted tracker after Beads: GitHub Issues, Linear, or the company-default tracker.
- Whether the Python implementation lives beside `elixir/` in this repo or starts as a separate
  repository after the plan is approved.

## Acceptance Criteria

- The Python implementation conforms to the language-agnostic Symphony spec where applicable.
- The Claude runner behavior matches the original Claude runner plan.
- The orchestrator does not know which Claude mode is selected beyond normalized runner status and
  events.
- `claude.headless` can process a normalized issue end to end with a required completion artifact.
- Routine and Channel modes can be added without rewriting tracker, workspace, prompt, retry, or
  reconciliation logic.
- The implementation is understandable and maintainable for Python-first teams.
