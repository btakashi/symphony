---
tracker:
  kind: beads
  command: bd
  active_states:
    - open
    - in_progress
  terminal_states:
    - closed
polling:
  interval_ms: 5000
workspace:
  root: ~/code/symphony-python-workspaces
hooks:
  after_create: |
    workspace="$PWD"
    parent="$(dirname "$workspace")"
    name="$(basename "$workspace")"
    cd "$parent"
    rmdir "$workspace"
    cd /Users/brian/Code/symphony
    bd worktree create "$workspace" --branch "symphony-workspace-$name"
    cd "$workspace/python" && uv sync
agent:
  provider: claude
  mode: headless
  max_concurrent_agents: 1
  max_turns: 1
claude:
  headless:
    executable: claude
    args:
      - -p
      - --allowedTools
      - Read,Write,Edit,Bash
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
---

You are working on a Beads issue for the Python Symphony implementation.

Issue context:
ID: {{ issue.identifier }}
Title: {{ issue.title }}
Current status: {{ issue.state }}
Labels: {{ issue.labels }}
URL: {{ issue.url }}

Description:
{% if issue.description %}
{{ issue.description }}
{% else %}
No description provided.
{% endif %}

Instructions:

1. Work only in the provided repository workspace.
2. Treat the issue context above as authoritative; Symphony has already read and claimed the Beads
   issue before dispatch.
3. Keep implementation focused on the issue scope.
4. Run the relevant validation before handoff.
5. Record discovered follow-up work as new Beads issues when the workspace has Beads access; if
   Beads is unavailable, include the follow-up in the structured handoff errors or artifacts.
6. Do not close or transition the issue yourself; Symphony performs tracker writeback from the
   structured handoff.
7. Do not treat a successful process exit as task success without a structured handoff block.

Quality gates:

- Full local gate: `cd python && uv run poe check`
- Format check: `cd python && uv run poe format-check`
- Lint: `cd python && uv run poe lint`
- Type check: `cd python && uv run poe typecheck`
- Unit tests: `cd python && uv run poe test`

Final response must include this exact machine-readable block:

SYMPHONY_HANDOFF_START
{"status":"succeeded","summary":"<short summary>","artifacts":[],"validation":[],"errors":[]}
SYMPHONY_HANDOFF_END
