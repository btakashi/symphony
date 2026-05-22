from pathlib import Path

from symphony.clean import clean, clean_paths


def test_clean_paths_are_inside_project_root(tmp_path: Path) -> None:
    paths = clean_paths()

    assert paths
    assert all(path.resolve().is_relative_to(Path.cwd().resolve()) for path in paths)


def test_clean_rejects_unrecognized_project_root(tmp_path: Path) -> None:
    try:
        clean(tmp_path)
    except RuntimeError as exc:
        assert "unrecognized project root" in str(exc)
    else:
        raise AssertionError("clean should reject arbitrary roots")


def test_clean_removes_known_cache_paths() -> None:
    project_root = Path.cwd()
    cache_dir = project_root / ".pytest_cache"
    cache_dir.mkdir(exist_ok=True)
    pycache_dir = project_root / "src" / "symphony" / "__pycache__"
    pycache_dir.mkdir(parents=True, exist_ok=True)

    clean()

    assert not cache_dir.exists()
    assert not pycache_dir.exists()
