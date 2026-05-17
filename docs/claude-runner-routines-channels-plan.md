# Claude Code Runner Plan: Routines, Channels, and Headless

## Summary

Add Claude Code support behind a transport-neutral runner interface so Symphony can use Claude Routines, Claude Channels, or `claude -p` headless mode per workflow. Keep tracker polling, issue normalization, concurrency, retries, and reconciliation independent from the Claude transport.

Default strategy:

- Use Claude Routines as the preferred subscription-billed cloud automation path after validation.
- Use Claude Channels as the local interactive-session fallback when routines cannot access required repo, tracker, or environment resources.
- Support `claude -p` / headless mode as an explicit opt-in batch runner for environments where API-style billing, non-interactive execution, and subprocess lifecycle management are acceptable.
- Do not make `claude -p` the default Claude path because it is expected to use Agent SDK/API-style billing credits rather than normal interactive subscription usage.

## Risk-Reduction Spike First

Before implementation, run validation spikes and record results in repo docs.

- Routine billing: trigger a routine and confirm usage appears under Claude subscription usage, not API/Agent SDK billing; verify whether API-triggered runs count against daily routine caps.
- Routine API: create an API-triggered routine, send a sample issue payload, capture returned `claude_code_session_id`, URL, error cases, and rate/cap behavior.
- Routine subagents: add a repo-visible test subagent, invoke it from a routine prompt using `@agent-name`, and confirm it runs with usable status/transcript visibility.
- Routine completion: prove Symphony can detect completion from a deterministic artifact, such as tracker comment, PR URL, branch, state transition, or machine-readable summary.
- Channels transport: prove Symphony can send issue work into a running Claude Code session through a channel MCP server and receive replies.
- Channels subagent telemetry: prove `SubagentStart`, `SubagentStop`, tool hooks, and OpenTelemetry can be correlated with `issue_id`, `session_id`, `agent_id`, and workspace.
- Headless billing: run `claude -p` with a sample task and confirm billing/usage attribution, rate limits, and whether usage is subscription, API, or Agent SDK credit based.
- Headless execution contract: prove Symphony can launch `claude -p` in a workspace, pass the issue prompt over stdin or argv, capture stdout/stderr, enforce timeout/cancel behavior, and detect a structured final handoff block.
- Headless subagents/permissions: prove whether `claude -p` can invoke repo-visible subagents and how permission/tool-denial prompts surface in non-interactive mode.
- Tracker writeback: validate at least one tracker write path for Jira, ClickUp, GitHub Issues, and Dolt mode selected below.

Do not build the full runner until these are verified or explicitly marked as unsupported with fallback behavior.

Suggested spike order:

1. Prove Routine API dispatch and completion detection with a disposable routine and test repo.
2. Prove Routine billing/cap behavior from both UI-triggered and API-triggered runs.
3. Prove Routine subagent behavior and transcript/status visibility.
4. Prove Channel message delivery into one local Claude Code session and reply delivery back to Symphony.
5. Prove Channel hook/OpenTelemetry correlation for main-agent and subagent events.
6. Prove `claude -p` billing, subprocess lifecycle, completion parsing, permissions, and subagent behavior.
7. Prove tracker writeback paths for every non-Linear tracker before enabling those adapters in production workflows.

Spike result format:

```markdown
## Spike: <name>

- Date:
- Environment:
- Setup:
- Result: supported | unsupported | inconclusive
- Evidence:
- Failure modes:
- Required fallback:
- Implementation notes:
```

## Core Architecture

Introduce a provider-neutral execution boundary:

```elixir
start_run(issue, prompt, opts) -> {:ok, run_ref} | {:error, reason}
poll_run(run_ref) -> {:ok, status} | {:error, reason}
cancel_run(run_ref) -> :ok | {:error, reason}
fetch_events(run_ref) -> {:ok, [event]} | {:error, reason}
```

Normalized run statuses:

- `queued`
- `starting`
- `running`
- `waiting_for_permission`
- `succeeded`
- `failed`
- `cancelled`
- `unknown`

Normalized run event fields:

- `provider`
- `mode`
- `tracker_kind`
- `issue_id`
- `issue_identifier`
- `run_id`
- `session_id`
- `agent_id`
- `workspace_path`
- `event_type`
- `message`
- `metadata`
- `timestamp`

Config shape:

```yaml
agent:
  provider: claude
  mode: routine # routine | channel | headless

claude:
  routine:
    id: "routine_..."
    trigger: api
    completion_artifact: tracker_comment
  channel:
    session_strategy: per_issue
    channel_server: symphony-channel
    require_hooks: true
    require_otel: true
  headless:
    executable: claude
    args: ["-p"]
    prompt_transport: stdin
    completion_artifact: structured_handoff
    timeout_seconds: 7200
```

Keep Codex support behind the same runner boundary where practical, rather than continuing to hard-wire `AgentRunner` to `Codex.AppServer`.

## Phased Implementation

### Phase 0: Spike Documentation

- Add a `docs/claude-spikes/` folder for validation notes.
- Capture each risk-reduction spike using the template above.
- Mark unsupported features explicitly, including the fallback behavior Symphony will use.
- Do not add new workflow config that operators can enable until the corresponding spike is documented.

### Phase 1: Runner Boundary

- Introduce a runner behavior/protocol around `start_run`, `poll_run`, `cancel_run`, and `fetch_events`.
- Adapt the current Codex app-server execution path to that boundary first.
- Keep orchestrator state transitions unchanged except where they need normalized runner statuses.
- Add fake runner implementations for deterministic orchestrator tests.

Exit criteria:

- Existing Codex behavior still passes current tests.
- Orchestrator tests can dispatch through a fake runner without referencing Codex-specific structs.
- Status/log output still includes current Codex token and session metadata where available.

### Phase 2: Tracker Boundary

- Make tracker adapter operations explicit and normalize all tracker payloads into the existing issue model.
- Keep Linear as the first adapter under the new boundary.
- Add GitHub Issues next because credentials and issue semantics are easiest to validate locally.
- Add Jira, ClickUp, and Dolt only after writeback behavior is validated.

Exit criteria:

- Linear behavior is unchanged.
- Tracker adapter tests cover candidate fetch, state reconciliation, terminal cleanup, and optional writeback.
- Workflow validation rejects unsupported tracker kinds before dispatch.

### Phase 3: Claude Routine Runner

- Implement Routine runner behind the provider-neutral runner behavior.
- Store routine ID, returned session ID, trigger response metadata, and completion artifact state.
- Treat provider status as operational telemetry, not task success.
- Reconcile task completion only through configured artifacts.

Exit criteria:

- Routine dispatch is gated by documented spike evidence and env/config validation.
- Failure modes for missing routine ID, cap exceeded, unavailable routine, and missing artifact are tested.
- Operators can see routine/session identifiers and the latest completion-artifact status.

### Phase 4: Claude Channel Runner

- Implement Channel runner after local channel transport is proven.
- Launch or attach to one Claude Code session per issue workspace.
- Route progress, permission, cancellation, completion, hook, and telemetry messages through a persisted channel event log.
- Fail startup when required hooks or OpenTelemetry are unavailable and config requires them.

Exit criteria:

- A local Channel run can complete the same fake issue contract as the Routine runner.
- Subagent and tool events are correlated with issue/run/session IDs.
- Channel disconnects, busy-session backpressure, and missing final replies are covered by tests.

### Phase 5: Claude Headless Runner

- Implement a `claude -p` runner behind the provider-neutral runner behavior.
- Launch one subprocess per active issue workspace.
- Pass the same normalized issue context and workflow prompt used by Routine and Channel runners.
- Capture stdout, stderr, exit status, process ID, start/stop timestamps, and the parsed final handoff block.
- Enforce configured timeout, cancellation, and workspace path safety.
- Treat process exit code as infrastructure status and require a configured completion artifact for task success.

Exit criteria:

- Headless dispatch is gated by documented spike evidence and env/config validation.
- Timeout, cancellation, nonzero exit, malformed final handoff, missing executable, and permission-denial behavior are tested.
- Operators can see process ID, latest output summary, exit status, and completion-artifact status.

### Phase 6: Operational Hardening

- Add operator-facing status for provider, mode, tracker kind, run IDs, session IDs, completion artifacts, and subagent activity.
- Add recovery tests for process restart, stale active runs, abandoned workspaces, and tracker state changes during active Claude runs.
- Add documentation for supported provider/tracker combinations and their known limitations.

## Claude Routine Mode

Routine mode is the preferred Claude path if validation passes.

Implementation behavior:

- Symphony polls tracker issues as it does today.
- For each eligible issue, Symphony builds a prompt containing normalized issue context, workflow prompt, expected handoff artifact, and subagent instructions.
- Symphony triggers the configured routine via API and stores the returned routine/session identifiers in run metadata.
- Symphony treats routine infrastructure status as insufficient for task success.
- Completion is determined by a configured artifact: tracker comment, issue state, PR URL, branch, or structured summary.
- Cancellation is best-effort unless the routine API exposes reliable cancellation.

Prompt requirements:

- Include exact issue ID and identifier.
- Include tracker URL and desired final artifact.
- If subagents are validated, explicitly instruct Claude to use configured subagents such as implementer then QA reviewer.
- Require a final machine-readable handoff block for Symphony reconciliation.

Fallbacks:

- If routine subagents fail, run implementation and QA in the main routine prompt.
- If routine tracker connectors fail, Symphony passes issue context in the API payload and performs tracker polling/writeback locally where supported.
- If routine caps block execution, leave issue unclaimed or mark run as backoff according to existing orchestrator retry policy.

## Claude Channel Mode

Channel mode is the local interactive fallback.

Implementation behavior:

- Use one Claude Code interactive session per active issue/workspace.
- Launch or attach to Claude Code with `--channels` and the Symphony channel MCP server.
- Symphony sends a channel event containing issue context, workflow prompt, run ID, and expected reply protocol.
- Claude replies through the channel `reply` tool with progress and completion messages.
- Completion requires either a final reply following the Symphony protocol, a `Stop` hook event, or a verified tracker/PR artifact.
- Permission prompts are relayed through the channel permission mechanism where available.

Channel server responsibilities:

- Authenticate local Symphony requests.
- Accept `start_issue`, `cancel_issue`, and `status` messages from Symphony.
- Emit Claude channel notifications.
- Expose a `reply` tool for Claude.
- Persist event logs enough for crash recovery.
- Include issue/run IDs in every message.

Telemetry requirements:

- Enable Claude Code hooks for `Stop`, `SubagentStart`, `SubagentStop`, `PreToolUse`, `PostToolUse`, and tool failures.
- Enable OpenTelemetry when available.
- Correlate events by `issue_id`, `run_id`, `session_id`, `agent_id`, and workspace path.
- Surface subagent activity in Symphony status output.
- Treat missing required telemetry as a startup validation failure when `claude.channel.require_hooks` or `require_otel` is true.

Limitations:

- Do not multiplex multiple tracker issues through one Claude session.
- Do not rely on Channels as a direct subagent API; subagent use is prompt-driven through the main Claude session.
- Treat queued channel events while Claude is busy as normal backpressure.

## Claude Headless Mode

Headless mode uses `claude -p` as an opt-in non-interactive subprocess runner.

Use cases:

- CI-like batch execution where API-style billing and non-interactive behavior are acceptable.
- Environments where Routines are unavailable and Channels are too operationally heavy.
- Validation or migration paths that need the simplest Claude subprocess integration first.

Implementation behavior:

- Symphony polls tracker issues as it does today.
- For each eligible issue, Symphony creates or reuses the issue workspace and launches `claude -p` from that workspace.
- Symphony passes a full prompt containing normalized issue context, workflow prompt, expected handoff artifact, and permission constraints.
- Prompt delivery defaults to stdin to avoid shell quoting limits and leaking issue text through process args.
- Symphony captures stdout/stderr incrementally, summarizes recent output for status, and stores full logs according to the existing logging policy.
- Completion requires a configured artifact, such as structured handoff block, tracker comment, PR URL, branch, or issue state transition.
- Cancellation terminates the subprocess best-effort and records the signal/exit status.

Prompt requirements:

- Include exact issue ID and identifier.
- Include tracker URL and desired final artifact.
- Require a final machine-readable handoff block when `completion_artifact=structured_handoff`.
- If subagents are validated, explicitly instruct Claude to use configured subagents; otherwise keep implementation and QA in the main prompt.
- State that the run is non-interactive and must fail with a clear final error if permissions or missing credentials block progress.

Headless metadata:

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

Fallbacks:

- If `claude -p` cannot use subagents, run implementation and QA in the main prompt.
- If permission prompts cannot be satisfied non-interactively, fail fast and retry only after operator configuration changes.
- If stdout parsing is unreliable, require an external completion artifact such as tracker comment or PR URL.

Limitations:

- Do not treat exit code `0` alone as task success.
- Do not pass secrets or full issue payloads through argv.
- Do not use headless mode as a subscription-billing workaround unless billing validation proves it is acceptable.
- Expect less interactive telemetry than Channels unless hooks/OpenTelemetry are validated for headless runs.

## Tracker Options

Add tracker adapters behind the existing tracker boundary. All trackers must normalize into the same issue model used by the runner.

Supported `tracker.kind` values:

- `jira`
- `clickup`
- `github_issues`
- `dolt`
- existing `linear`
- existing `memory`

Shared adapter operations:

- `fetch_candidate_issues()`
- `fetch_issues_by_states(state_names)`
- `fetch_issue_states_by_ids(issue_ids)`
- optional `create_comment(issue_id, body)`
- optional `update_issue_state(issue_id, state_name)`

Tracker config should include only tracker-specific credentials and filters; it must not know whether Claude runs via routines, channels, or headless subprocesses.

Dolt default assumption:

- Treat Dolt as a SQL-backed issue database with configured table/query mappings.
- If this assumption is wrong, replace with a `dolt.mode` option later: `sql`, `local_cli`, or `dolthub_api`.

## Public Config Changes

Extend workflow front matter:

```yaml
tracker:
  kind: github_issues
  api_key: $GITHUB_TOKEN
  owner: your-org
  repo: your-repo
  active_states: ["Todo", "In Progress"]
  terminal_states: ["Done", "Closed"]

agent:
  provider: claude
  mode: routine
  max_concurrent_agents: 5
  max_turns: 1

claude:
  routine:
    id: $CLAUDE_ROUTINE_ID
    completion_artifact: tracker_comment
    subagents:
      - implementer
      - qa-reviewer
  headless:
    executable: claude
    args: ["-p"]
    prompt_transport: stdin
    completion_artifact: structured_handoff
    timeout_seconds: 7200
```

Validation rules:

- `agent.provider=claude` requires `agent.mode`.
- `agent.mode=routine` requires `claude.routine.id`.
- `agent.mode=channel` requires channel server config and local Claude Code capability checks.
- `agent.mode=headless` requires `claude.headless.executable`, `claude.headless.args`, and timeout/cancellation settings.
- Tracker credentials are resolved from tracker-specific canonical env vars.
- Unsupported tracker/agent modes fail before dispatch.

## Testing Plan

Add focused tests before broad integration tests.

- Config parsing and validation for `agent.provider`, `agent.mode`, `claude.routine`, `claude.channel`, `claude.headless`, and new tracker kinds.
- Runner contract tests using fake routine, fake channel, and fake headless implementations.
- Orchestrator tests proving runner mode does not affect dispatch, retry, reconciliation, and cleanup semantics.
- Tracker adapter normalization tests for Jira, ClickUp, GitHub Issues, and Dolt.
- Routine spike tests against a disposable routine and test repo, gated by env vars.
- Channel spike tests against a local Claude Code session, gated by env vars.
- Headless spike tests against `claude -p`, gated by env vars.
- Telemetry tests proving subagent/tool/hook events attach to the correct run.
- Failure tests for missing credentials, cap exceeded, routine unavailable, channel disconnected, headless executable missing, headless timeout, subagent unavailable, and missing completion artifact.

Acceptance criteria:

- Symphony can dispatch the same normalized issue through `claude.routine`, `claude.channel`, or `claude.headless`.
- Tracker adapters are interchangeable with no runner changes.
- Routine mode has verified billing/cap/subagent behavior documented.
- Channel mode has verified reply, completion, hook, and telemetry behavior documented.
- Headless mode has verified billing, completion parsing, cancellation, timeout, permissions, and subagent behavior documented.
- Symphony never treats provider status, session status, or process exit status alone as task success.
- Operator status shows enough telemetry to understand what Claude and subagents are doing.

## Assumptions

- Routines use subscription usage and are the preferred official automation path if validation confirms expected billing and caps.
- Routines can run subagents because they are Claude Code sessions, but this must be validated before relying on it.
- Channels are suitable for local interactive fallback but are not equivalent to Codex app-server.
- One Claude session per active issue is the safe concurrency model for Channels.
- `claude -p` may be useful as a simple subprocess runner, but its billing, non-interactive permission behavior, and subagent support must be validated before enabling it by default.
- Dolt will initially be treated as a SQL-backed tracker unless a different Dolt integration mode is explicitly chosen.
