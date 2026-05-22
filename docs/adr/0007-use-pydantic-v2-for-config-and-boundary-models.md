# 0007. Use Pydantic v2 for Config and Boundary Models

## Status

Accepted

## Context and Problem Statement

The Python implementation needs reliable validation for workflow config, tracker payloads, runner
metadata, and handoff artifacts. These are external boundaries where clear errors matter more than
minimizing dependencies.

## Decision Drivers

- Validate `WORKFLOW.md` config before dispatch.
- Normalize Beads and future tracker payloads into a stable issue model.
- Provide clear error messages for invalid config and malformed runner artifacts.
- Keep internal orchestration code working with typed objects.

## Considered Options

- Pydantic v2 for config and boundary models.
- Dataclasses plus explicit validators.
- TypedDict plus ad hoc validation.

## Decision Outcome

Use Pydantic v2 for config and external data boundaries.

Dataclasses may still be used for small internal ephemeral structs when validation is unnecessary.

## Consequences

- The project takes a runtime dependency on Pydantic.
- Config and external payload parsing get stronger validation and better error reporting.
- Tests should cover validation failures as first-class behavior.

## Links

- https://docs.pydantic.dev/
- [`../python-claude-symphony-plan.md`](../python-claude-symphony-plan.md)
