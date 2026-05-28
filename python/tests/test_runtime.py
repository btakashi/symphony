from pathlib import Path

import pytest

from symphony.runtime import SymphonyRuntimeError, find_workflow_path


def test_find_workflow_path_searches_upward(tmp_path: Path) -> None:
    workflow = tmp_path / "WORKFLOW.md"
    workflow.write_text("---\n---\n\nDo work.\n", encoding="utf-8")
    nested = tmp_path / "one" / "two"
    nested.mkdir(parents=True)

    assert find_workflow_path(nested) == workflow


def test_find_workflow_path_accepts_file_start_path(tmp_path: Path) -> None:
    workflow = tmp_path / "WORKFLOW.md"
    workflow.write_text("---\n---\n\nDo work.\n", encoding="utf-8")
    child = tmp_path / "child.txt"
    child.write_text("", encoding="utf-8")

    assert find_workflow_path(child) == workflow


def test_find_workflow_path_reports_missing_workflow(tmp_path: Path) -> None:
    with pytest.raises(SymphonyRuntimeError, match=r"Unable to find WORKFLOW\.md"):
        find_workflow_path(tmp_path)
