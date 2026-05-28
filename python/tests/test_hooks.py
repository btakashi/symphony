from pathlib import Path

import pytest

from symphony.hooks import HookError, run_workspace_hook


@pytest.mark.asyncio
async def test_run_workspace_hook_runs_from_workspace(tmp_path: Path) -> None:
    await run_workspace_hook("printf 'ok' > hook-output.txt", workspace_path=tmp_path)

    assert (tmp_path / "hook-output.txt").read_text(encoding="utf-8") == "ok"


@pytest.mark.asyncio
async def test_run_workspace_hook_raises_on_failure(tmp_path: Path) -> None:
    with pytest.raises(HookError, match="nope"):
        await run_workspace_hook("printf 'nope' >&2; exit 7", workspace_path=tmp_path)
