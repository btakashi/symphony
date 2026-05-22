# 0002. Use Python for Symphony Implementation

## Status

Accepted

## Context and Problem Statement

The existing reference implementation is written in Elixir, but Python is a supported language in
the target company environment. The new implementation should be maintainable by Python-first teams
while preserving the language-agnostic Symphony contract.

## Decision Drivers

- Python is officially supported in the target environment.
- Python has strong libraries for subprocesses, HTTP APIs, YAML, CLIs, and tests.
- The initial Claude headless runner can be implemented quickly with Python's async subprocess APIs.
- The implementation should be accessible to contributors who do not know Elixir.

## Considered Options

- Continue with Elixir.
- Implement in Go.
- Implement in TypeScript.
- Implement in Python.

## Decision Outcome

Implement the new Symphony service in Python.

Use the Elixir implementation as a behavioral reference, not a structural template.

## Consequences

- The Python implementation needs careful design for long-running daemon behavior, cancellation, and
  concurrency.
- `asyncio` should be used consistently for polling, subprocess execution, and cancellation.
- The implementation can still conform to `SPEC.md` and the Claude runner plan.

## Links

- [`../python-claude-symphony-plan.md`](../python-claude-symphony-plan.md)
- [`../../SPEC.md`](../../SPEC.md)
