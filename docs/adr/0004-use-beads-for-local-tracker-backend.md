# 0004. Use Beads for Local Tracker Backend

## Status

Accepted

## Context and Problem Statement

The Python Symphony implementation needs a local tracker backend before depending on hosted systems
such as Linear, GitHub Issues, Jira, or ClickUp. A hand-rolled filesystem tracker would require
Symphony to design issue formats, dependencies, claiming, state transitions, and ready-queue logic.

Beads (`bd`) is a local-first issue tracker designed for AI coding workflows. It supports JSON CLI
output, dependency-aware ready queues, issue claiming, comments/notes, and local embedded storage.
Beads uses Dolt internally, but DoltHub is not required.

## Decision Drivers

- Keep the bootstrap tracker local.
- Avoid designing a custom issue-file format and dependency graph.
- Use a tracker designed for AI-agent workflows.
- Use programmatic JSON CLI output for a simple first adapter.
- Avoid hosted DoltHub or other remote tracker dependencies.
- Preserve the same normalized `Issue` model used by future tracker adapters.

## Considered Options

- Hand-rolled filesystem tracker.
- Memory-only tracker.
- GitHub Issues.
- Linear.
- Beads.

## Decision Outcome

Use Beads as the first local tracker backend.

The initial Python adapter should shell out to the `bd` CLI and request JSON output. Treat Beads as
an external CLI dependency first, not as a Python library.

Initial command mapping:

```text
fetch_candidate_issues       -> bd ready --json
fetch_issue_states_by_ids    -> bd show <id> --json
create_comment               -> bd comment <id> <body> --json
update_issue_state/claim     -> bd update <id> --claim --json or bd close <id> --json
```

Use Beads embedded mode by default. Server mode can be added later if Symphony needs multiple
concurrent writers.

## Consequences

- The Python implementation can bootstrap against a real local tracker without hosted services.
- Beads must be installed for local tracker runs.
- Tests should still use a memory/fake tracker for deterministic unit coverage.
- The Beads adapter must handle CLI errors, missing `bd`, malformed JSON, and unsupported Beads
  versions explicitly.
- If Beads semantics do not match Symphony's needs, a future ADR can add a filesystem tracker or
  another local backend.

## Links

- https://github.com/gastownhall/beads
- https://gastownhall.github.io/beads/
- [`../python-claude-symphony-plan.md`](../python-claude-symphony-plan.md)
