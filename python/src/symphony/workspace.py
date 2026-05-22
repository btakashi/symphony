"""Workspace path construction and lifecycle helpers."""

from __future__ import annotations

import re
from pathlib import Path

from symphony.config import WorkspaceConfig
from symphony.models import Workspace


class WorkspaceError(ValueError):
    """Raised when a workspace path cannot be created safely."""


_UNSAFE_WORKSPACE_KEY_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]")
_SAFE_WORKSPACE_KEY_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_RESERVED_WORKSPACE_KEYS = {".", ".."}


class WorkspaceManager:
    """Create and validate per-issue workspaces under a configured root."""

    def __init__(self, config: WorkspaceConfig) -> None:
        self.root = config.root.resolve(strict=False)

    def create_for_issue(self, issue_identifier: str) -> Workspace:
        """Create or reuse the workspace for an issue identifier."""

        workspace_key = sanitize_workspace_key(issue_identifier)
        workspace_path = self.path_for_key(workspace_key)
        created_now = not workspace_path.exists()

        if workspace_path.exists() and not workspace_path.is_dir():
            raise WorkspaceError(f"Workspace path exists and is not a directory: {workspace_path}")

        try:
            workspace_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkspaceError(f"Unable to create workspace: {workspace_path}") from exc

        return Workspace(path=workspace_path, workspace_key=workspace_key, created_now=created_now)

    def path_for_key(self, workspace_key: str) -> Path:
        """Return the absolute workspace path for an already-sanitized key."""

        validate_workspace_key(workspace_key)
        return ensure_path_under_root(self.root, self.root / workspace_key)

    def validate_cwd(self, cwd: Path, workspace: Workspace) -> None:
        """Validate that a subprocess cwd is exactly the issue workspace path."""

        resolved_cwd = ensure_path_under_root(self.root, cwd)
        if resolved_cwd != workspace.path.resolve(strict=False):
            raise WorkspaceError(f"Workspace cwd does not match issue workspace: {cwd}")


def sanitize_workspace_key(identifier: str) -> str:
    """Convert an issue identifier to a safe workspace directory name."""

    workspace_key = _UNSAFE_WORKSPACE_KEY_CHARS_RE.sub("_", identifier.strip())
    validate_workspace_key(workspace_key)
    return workspace_key


def validate_workspace_key(workspace_key: str) -> None:
    """Validate an already-sanitized workspace key."""

    if not workspace_key:
        raise WorkspaceError("Workspace key cannot be empty")
    if workspace_key in _RESERVED_WORKSPACE_KEYS:
        raise WorkspaceError(f"Workspace key cannot be reserved path segment: {workspace_key}")
    if Path(workspace_key).is_absolute():
        raise WorkspaceError(f"Workspace key cannot be an absolute path: {workspace_key}")
    if "/" in workspace_key or "\\" in workspace_key:
        raise WorkspaceError(f"Workspace key cannot contain path separators: {workspace_key}")
    if _SAFE_WORKSPACE_KEY_RE.fullmatch(workspace_key) is None:
        raise WorkspaceError(f"Workspace key contains unsafe characters: {workspace_key}")


def ensure_path_under_root(root: Path, path: Path) -> Path:
    """Resolve and assert that a path stays under the workspace root."""

    resolved_root = root.resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise WorkspaceError(f"Workspace path escapes configured root: {resolved_path}") from exc
    return resolved_path
