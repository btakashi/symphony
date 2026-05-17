# Claude Spike Notes

Use this folder to record validation spikes before enabling Claude runner modes in Symphony.

Each spike should answer one operational question with enough evidence for an implementer to decide
whether to build, defer, or add fallback behavior.

## Template

```markdown
# Spike: <name>

- Date:
- Environment:
- Setup:
- Result: supported | unsupported | inconclusive
- Evidence:
- Failure modes:
- Required fallback:
- Implementation notes:
```

## Required Spikes

- Routine API dispatch and completion detection.
- Routine billing and cap behavior for UI-triggered and API-triggered runs.
- Routine subagent behavior and transcript/status visibility.
- Channel message delivery into one local Claude Code session and replies back to Symphony.
- Channel hook/OpenTelemetry correlation for main-agent and subagent events.
- Headless `claude -p` billing, usage attribution, and rate limits.
- Headless subprocess lifecycle, timeout, cancellation, and structured completion parsing.
- Headless permission and subagent behavior.
- Tracker writeback paths for Jira, ClickUp, GitHub Issues, and Dolt.
