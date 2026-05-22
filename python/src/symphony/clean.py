"""Safe cleanup helper for generated Python caches."""

from __future__ import annotations

import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_MARKERS = ("pyproject.toml", "uv.lock")


def clean_paths(project_root: Path = PROJECT_ROOT) -> list[Path]:
    """Return generated cache paths that are safe to remove."""

    paths = [
        project_root / ".pytest_cache",
        project_root / ".ruff_cache",
        project_root / "htmlcov",
        project_root / ".coverage",
    ]
    for source_root in (project_root / "src", project_root / "tests"):
        if source_root.exists():
            paths.extend(source_root.rglob("__pycache__"))
    return paths


def clean(project_root: Path = PROJECT_ROOT) -> None:
    """Remove generated cache paths under the Python project root."""

    resolved_root = project_root.resolve()
    _validate_project_root(resolved_root)
    paths = clean_paths(project_root)
    paths.append(Path(__file__).parent / "__pycache__")

    for path in paths:
        resolved_path = path.resolve()
        if resolved_path != resolved_root and not resolved_path.is_relative_to(resolved_root):
            raise RuntimeError(f"Refusing to remove path outside project root: {path}")
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def _validate_project_root(project_root: Path) -> None:
    if project_root != PROJECT_ROOT.resolve():
        raise RuntimeError(f"Refusing to clean unrecognized project root: {project_root}")
    for marker in PROJECT_MARKERS:
        if not (project_root / marker).exists():
            raise RuntimeError(f"Refusing to clean project root without {marker}: {project_root}")


def main() -> None:
    """Run the cleanup helper."""

    clean()
