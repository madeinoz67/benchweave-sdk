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
