# 0005. Start with Claude Headless Runner

## Status

Proposed

## Context and Problem Statement

The Claude runner plan includes Routines, Channels, and `claude -p` headless mode. Routines and
Channels need validation spikes before full implementation. Headless mode is the simplest transport
for proving the Python runner boundary because it can be modeled as subprocess orchestration.

## Decision Drivers

- Validate the provider-neutral runner boundary early.
- Avoid waiting on Routine API and Channel transport details.
- Exercise workspace isolation, prompt building, logging, cancellation, timeout, and completion
  artifact parsing with a concrete runner.
- Keep the first implementation small enough to test locally.

## Considered Options

- Start with Claude Routines.
- Start with Claude Channels.
- Start with `claude -p` headless mode.
- Start with only a fake runner.

## Decision Outcome

Start with the fake runner and `claude -p` headless runner.

Headless success requires a configured completion artifact. Process exit code alone is not task
success.

## Consequences

- Billing, permission, and subagent behavior for `claude -p` still need validation before production
  use.
- Routine and Channel modes can be added later behind the same runner interface.
- The first real runner implementation can be tested primarily with local subprocess fixtures.

## Links

- [`../claude-runner-routines-channels-plan.md`](../claude-runner-routines-channels-plan.md)
- [`../python-claude-symphony-plan.md`](../python-claude-symphony-plan.md)
