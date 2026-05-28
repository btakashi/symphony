# Spike: Headless workspace edit

- Date: 2026-05-28
- Environment: macOS local development machine, Python 3.14.5, Claude Code 2.1.153,
  `claude -p` invoked through the Python `ClaudeHeadlessRunner`
- Setup:
  - Branch: `python-headless-spike-evidence`
  - The test created a disposable workspace containing `input.txt`.
  - Claude was launched with `--allowedTools Read,Write,Edit`.
  - Command:
    ```bash
    cd python
    SYMPHONY_RUN_CLAUDE_HEADLESS_SPIKE=1 uv run pytest \
      tests/test_claude_headless_live_spike.py::test_real_claude_headless_workspace_edit_spike \
      -m "live and spike"
    ```
- Result: supported
- Evidence:
  - Test result: `1 passed in 16.04s`
  - Run ID: `claude-775fe8f135c0497cb3424f85ae4e3b21`
  - Workspace:
    `/private/var/folders/dp/6vxh0d4132z9l6__l92mmy6r0000gn/T/pytest-of-brian/pytest-21/test_real_claude_headless_work0/workspace`
  - Stdout log:
    `/private/var/folders/dp/6vxh0d4132z9l6__l92mmy6r0000gn/T/pytest-of-brian/pytest-21/test_real_claude_headless_work0/log/claude-775fe8f135c0497cb3424f85ae4e3b21/stdout.log`
  - Stderr log:
    `/private/var/folders/dp/6vxh0d4132z9l6__l92mmy6r0000gn/T/pytest-of-brian/pytest-21/test_real_claude_headless_work0/log/claude-775fe8f135c0497cb3424f85ae4e3b21/stderr.log`
  - Claude created `output.txt` with exact content `symphony output\n`.
  - Stdout contained a valid `SYMPHONY_HANDOFF_START` / `SYMPHONY_HANDOFF_END` block with
    status `succeeded`, artifact `output.txt`, and validation
    `output.txt exact content verified by test`.
  - Stderr was empty.
- Failure modes:
  - The command needs access to the user's `uv` cache and local Claude credentials.
  - Workspace edits require explicit tool allowance in non-interactive mode.
  - The current spike validates simple file creation only, not git operations, package installs,
    test execution, tracker writeback, or multi-step project work.
- Required fallback:
  - Keep workspace-edit spikes gated behind `SYMPHONY_RUN_CLAUDE_HEADLESS_SPIKE=1`.
  - Use a disposable workspace for live file-edit validation.
  - Treat missing tool permission, timeout, nonzero exit, missing output file, or missing structured
    handoff as unsupported for that environment.
- Implementation notes:
  - Local Claude Code subscription auth is sufficient for `claude -p` workspace file edits in this
    environment.
  - The current runner can launch Claude in a specific workspace, pass a prompt through stdin,
    capture logs, parse the structured handoff, and observe filesystem side effects.
  - This supports a near-term Symphony path using Beads plus local `claude -p` before implementing
    Routine, Channel, GitHub Issues, or Jira adapters.
