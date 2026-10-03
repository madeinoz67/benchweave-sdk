"""The packaging hook refuses a build without the copier template root.

``hatch_build.py`` imports hatchling's BuildHookInterface, which exists only
in build environments (a build-time dependency, deliberately absent from the
dev venv). The interface is a bare base class, so a minimal stand-in lets the
scaffold-template presence check run under unit test; the real hook executes
in every ``uv build`` lane (ci.yml's wheel smoke installs the wheel and runs
``new --with-ui`` from it, publish.yml at release).
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_build_hook(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    stubs: dict[str, types.ModuleType] = {}

    def module(name: str) -> types.ModuleType:
        if name not in stubs:
            stubs[name] = types.ModuleType(name)
        return stubs[name]

    module("hatchling")
    module("hatchling.builders")
    module("hatchling.builders.hooks")
    module("hatchling.builders.hooks.plugin")
    interface = module("hatchling.builders.hooks.plugin.interface")

    class BuildHookInterface:  # the real one is an attribute-free base class
        pass

    interface.BuildHookInterface = BuildHookInterface
    for name, mod in stubs.items():
        monkeypatch.setitem(sys.modules, name, mod)
    spec = importlib.util.spec_from_file_location("hatch_build_under_test", ROOT / "hatch_build.py")
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_build_refuses_without_the_template_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = _load_build_hook(monkeypatch)
    with pytest.raises(RuntimeError, match=r"^Scaffold template member missing: copier.yml"):
        hook._validate_scaffold_template(tmp_path)


def test_build_requires_the_answers_template_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No .copier-answers.yml.jinja means no provenance is ever written (spike-proven)."""
    hook = _load_build_hook(monkeypatch)
    (tmp_path / "copier.yml").write_text("_subdirectory: template\n", encoding="utf-8")
    with pytest.raises(
        RuntimeError, match=r"^Scaffold template member missing: template/\.copier-answers"
    ):
        hook._validate_scaffold_template(tmp_path)


def test_build_accepts_the_repository_template_root(monkeypatch: pytest.MonkeyPatch) -> None:
    hook = _load_build_hook(monkeypatch)
    hook._validate_scaffold_template(ROOT)
