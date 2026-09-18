"""Repo-mode detection must bind to the src tree, not just a matching pyproject.

A --target or PYTHONPATH install that happens to live inside an SDK checkout
satisfies the pyproject test alone; sync-standards must still treat the
running package as installed, or --check verifies the wrong tree and bundle
mode is wrongly permitted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchweave_sdk import cli


def _make_checkout(root: Path) -> None:
    (root / "pyproject.toml").write_text('[project]\nname = "benchweave-sdk"\n', encoding="utf-8")


def _run_from(monkeypatch: pytest.MonkeyPatch, package_dir: Path) -> Path | None:
    package_dir.mkdir(parents=True)
    monkeypatch.setattr(cli, "__file__", str(package_dir / "cli.py"))
    return cli._sdk_checkout_root()


def test_src_tree_of_a_checkout_is_repo_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_checkout(tmp_path)
    assert _run_from(monkeypatch, tmp_path / "src" / "benchweave_sdk") == tmp_path


def test_target_install_inside_a_checkout_is_not_repo_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # uv pip install --target <checkout>/lib: pyproject matches, module
    # runs from lib/ — the checkout must not be detected as the running SDK.
    _make_checkout(tmp_path)
    assert _run_from(monkeypatch, tmp_path / "lib" / "benchweave_sdk") is None


def test_plain_installed_layout_is_not_repo_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_dir = tmp_path / "venv" / "lib" / "site-packages" / "benchweave_sdk"
    assert _run_from(monkeypatch, package_dir) is None


def test_foreign_project_src_tree_is_not_repo_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "some-other-project"\n', encoding="utf-8"
    )
    assert _run_from(monkeypatch, tmp_path / "src" / "benchweave_sdk") is None
