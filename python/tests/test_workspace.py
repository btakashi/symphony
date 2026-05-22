from pathlib import Path

import pytest

from symphony.config import WorkspaceConfig
from symphony.models import Workspace
from symphony.workspace import (
    WorkspaceError,
    WorkspaceManager,
    ensure_path_under_root,
    sanitize_workspace_key,
)


def test_sanitize_workspace_key_replaces_unsafe_characters() -> None:
    assert sanitize_workspace_key(" TEAM-123 / fix: bug ") == "TEAM-123___fix__bug"


@pytest.mark.parametrize("identifier", ["", "   ", ".", ".."])
def test_sanitize_workspace_key_rejects_empty_and_reserved_values(identifier: str) -> None:
    with pytest.raises(WorkspaceError):
        sanitize_workspace_key(identifier)


def test_create_for_issue_creates_workspace_under_root(tmp_path: Path) -> None:
    manager = WorkspaceManager(WorkspaceConfig(root=tmp_path))

    workspace = manager.create_for_issue("TEAM-123 / fix: bug")

    assert workspace == Workspace(
        path=tmp_path / "TEAM-123___fix__bug",
        workspace_key="TEAM-123___fix__bug",
        created_now=True,
    )
    assert workspace.path.is_dir()


def test_create_for_issue_reuses_existing_workspace(tmp_path: Path) -> None:
    manager = WorkspaceManager(WorkspaceConfig(root=tmp_path))

    first = manager.create_for_issue("TEAM-123")
    second = manager.create_for_issue("TEAM-123")

    assert first.created_now is True
    assert second == Workspace(
        path=tmp_path / "TEAM-123", workspace_key="TEAM-123", created_now=False
    )


def test_create_for_issue_rejects_existing_non_directory(tmp_path: Path) -> None:
    manager = WorkspaceManager(WorkspaceConfig(root=tmp_path))
    (tmp_path / "TEAM-123").write_text("not a directory", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="not a directory"):
        manager.create_for_issue("TEAM-123")


@pytest.mark.parametrize("workspace_key", ["../escape", "/tmp/escape", "nested/key", r"nested\key"])
def test_path_for_key_rejects_escape_attempts(tmp_path: Path, workspace_key: str) -> None:
    manager = WorkspaceManager(WorkspaceConfig(root=tmp_path))

    with pytest.raises(WorkspaceError):
        manager.path_for_key(workspace_key)


def test_ensure_path_under_root_rejects_resolved_escape(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError, match="escapes configured root"):
        ensure_path_under_root(tmp_path, tmp_path / ".." / "escape")


def test_validate_cwd_accepts_exact_workspace_path(tmp_path: Path) -> None:
    manager = WorkspaceManager(WorkspaceConfig(root=tmp_path))
    workspace = manager.create_for_issue("TEAM-123")

    manager.validate_cwd(tmp_path / "." / "TEAM-123", workspace)


def test_validate_cwd_rejects_other_in_root_path(tmp_path: Path) -> None:
    manager = WorkspaceManager(WorkspaceConfig(root=tmp_path))
    workspace = manager.create_for_issue("TEAM-123")
    other = manager.create_for_issue("TEAM-456")

    with pytest.raises(WorkspaceError, match="does not match"):
        manager.validate_cwd(other.path, workspace)
