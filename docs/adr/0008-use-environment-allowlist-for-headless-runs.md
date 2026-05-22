# 0008. Use Environment Allowlist for Headless Runs

## Status

Accepted

## Context and Problem Statement

Headless Claude runs execute subprocesses in issue workspaces. Inheriting the full parent
environment could expose unrelated credentials or host-specific state to the agent process. The
implementation needs an explicit default posture for environment propagation.

## Decision Drivers

- Reduce accidental secret exposure.
- Make headless runs reproducible.
- Keep required credentials explicit in workflow config.
- Preserve enough environment for normal CLI execution.

## Considered Options

- Inherit the full parent environment.
- Use an explicit allowlist.
- Use an explicit denylist.
- Start with an empty environment.

## Decision Outcome

Use an explicit environment allowlist for headless subprocesses by default.

The default allowlist may include basic shell/runtime variables and explicitly required credentials,
such as `ANTHROPIC_API_KEY` and `GITHUB_TOKEN`, when configured for the workflow.

## Consequences

- Workflows must declare credentials and environment variables they need.
- Some tools may fail until their required environment variables are added to the allowlist.
- The default is safer than broad inheritance but still practical for local development.
- Future work may add secret redaction in logs and per-run environment audit output.

## Links

- [`../python-claude-symphony-plan.md`](../python-claude-symphony-plan.md)
