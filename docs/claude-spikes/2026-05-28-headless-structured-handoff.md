# Spike: Headless structured handoff

- Date: 2026-05-28
- Environment: macOS local development machine, Python 3.14.5, Claude Code 2.1.153,
  `claude -p` invoked through the Python `ClaudeHeadlessRunner`
- Setup:
  - Branch: `python-headless-spike-test`
  - Command:
    ```bash
    cd python
    SYMPHONY_RUN_CLAUDE_HEADLESS_SPIKE=1 uv run pytest \
      tests/test_claude_headless_live_spike.py \
      -m "live and spike"
    ```
  - Initial sandboxed run failed before pytest because `uv` could not access
    `/Users/brian/.cache/uv`; reran with approved filesystem access.
- Result: supported
- Evidence:
  - Test result: `1 passed in 8.98s`
  - Run ID: `claude-7211927f876143b290df85da5decdff4`
  - Stdout log:
    `/private/var/folders/dp/6vxh0d4132z9l6__l92mmy6r0000gn/T/pytest-of-brian/pytest-17/test_real_claude_headless_stru0/log/claude-7211927f876143b290df85da5decdff4/stdout.log`
  - Stderr log:
    `/private/var/folders/dp/6vxh0d4132z9l6__l92mmy6r0000gn/T/pytest-of-brian/pytest-17/test_real_claude_headless_stru0/log/claude-7211927f876143b290df85da5decdff4/stderr.log`
  - Stdout contained a valid `SYMPHONY_HANDOFF_START` / `SYMPHONY_HANDOFF_END` block with
    `{"status":"succeeded","summary":"headless spike handoff emitted","artifacts":[],"validation":[],"errors":[]}`.
  - Stderr was empty.
- Failure modes:
  - The command needs access to the user's `uv` cache and local Claude credentials.
  - The current spike only validates a simple no-tool prompt and structured completion parsing.
- Required fallback:
  - Keep the spike gated behind `SYMPHONY_RUN_CLAUDE_HEADLESS_SPIKE=1`.
  - Treat missing `claude`, missing credentials, timeout, nonzero exit, or missing structured
    handoff as unsupported for that environment.
- Implementation notes:
  - The existing headless runner can execute `claude -p`, capture stdout/stderr logs, and parse a
    structured handoff artifact for a successful run.
  - This does not validate billing, rate limits, permissions, subagent behavior, or nontrivial tool
    use. Those remain separate spikes.
