"""The scaffolder either completes a project or leaves nothing behind."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchweave_sdk.scaffold import create_project


def test_create_project_completes(tmp_path: Path) -> None:
    destination = tmp_path / "demo"
    create_project(destination, "demo_plugin")
    assert (destination / "pyproject.toml").is_file()
    assert (destination / "src/demo_plugin/descriptor.json").is_file()
    assert not destination.with_name("demo.partial").exists()


def test_create_project_refuses_existing_destination(tmp_path: Path) -> None:
    destination = tmp_path / "demo"
    destination.mkdir()
    with pytest.raises(FileExistsError):
        create_project(destination, "demo_plugin")


def test_create_project_refuses_dangling_symlink_destination(tmp_path: Path) -> None:
    # exists() is False for a dangling symlink, but the name is taken and the
    # final rename would fail mid-flight; refuse it up front, as documented.
    destination = tmp_path / "demo"
    try:
        destination.symlink_to(tmp_path / "nowhere")
    except OSError:
        pytest.skip("symlinks unavailable (privilege or filesystem)")
    # The full prefix, not "already exists": on Windows the rename this guard
    # pre-empts fails with WinError 183, whose text also says "already exists".
    with pytest.raises(FileExistsError, match="^Destination already exists: "):
        create_project(destination, "demo_plugin")
    assert destination.is_symlink(), "the link itself must be left alone"


def test_create_project_refuses_an_existing_staging_path_and_leaves_it_alone(
    tmp_path: Path,
) -> None:
    """A leftover ``.partial`` sibling is not ours to delete: it may be the user's own directory."""
    destination = tmp_path / "demo"
    staging = tmp_path / "demo.partial"
    staging.mkdir()
    (staging / "notes.txt").write_text("the user's own file", encoding="utf-8")
    with pytest.raises(FileExistsError, match="^Staging path already exists: "):
        create_project(destination, "demo_plugin")
    assert (staging / "notes.txt").read_text(encoding="utf-8") == "the user's own file"
    assert not destination.exists()


def test_interrupted_generation_leaves_no_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "demo"
    original = Path.write_text
    calls = {"count": 0}

    def failing(self: Path, *args: object, **kwargs: object) -> int:
        calls["count"] += 1
        if calls["count"] >= 3:
            raise OSError("disk full")
        return original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_text", failing)
    with pytest.raises(OSError, match="disk full"):
        create_project(destination, "demo_plugin")
    assert not destination.exists()
    assert not destination.with_name("demo.partial").exists()


def test_reserved_package_name_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_project(tmp_path / "x", "benchweave_sdk")
