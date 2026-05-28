"""Workspace hook execution."""

from __future__ import annotations

import asyncio
from pathlib import Path


class HookError(RuntimeError):
    """Raised when a workspace hook fails."""


async def run_workspace_hook(script: str, *, workspace_path: Path) -> None:
    """Run a workflow-owned shell hook from an issue workspace."""

    process = await asyncio.create_subprocess_shell(
        script,
        cwd=workspace_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await process.communicate()
    if process.returncode != 0:
        stdout = stdout_bytes.decode(errors="replace").strip()
        stderr = stderr_bytes.decode(errors="replace").strip()
        message = stderr or stdout or f"hook exited with status {process.returncode}"
        raise HookError(message)
