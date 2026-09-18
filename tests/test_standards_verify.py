"""Verification paths for the vendored standards state, checkout and installed."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from benchweave_sdk import standards_sync
from benchweave_sdk.standards_sync import (
    _verify_state,
    _verify_tree,
    verify_installed,
)

REPO = Path(__file__).resolve().parents[1]


def test_repo_state_verifies() -> None:
    _verify_state(REPO / "standards-lock.json", REPO / "src/benchweave_sdk/standards")


def test_corrupted_tree_is_refused(tmp_path: Path) -> None:
    lock_path = tmp_path / "standards-lock.json"
    tree = tmp_path / "standards"
    shutil.copy(REPO / "standards-lock.json", lock_path)
    shutil.copytree(
        REPO / "src/benchweave_sdk/standards",
        tree,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    lock = json.loads(lock_path.read_bytes())
    victim = tree / lock["standards"][0]["files"][0]["path"]
    victim.write_bytes(victim.read_bytes() + b"\n# drift")
    with pytest.raises(ValueError, match="hash_mismatch"):
        _verify_state(lock_path, tree)


def test_empty_lock_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not_synced"):
        _verify_tree(tmp_path, {})


def test_verify_installed_reports_missing_packaged_lock() -> None:
    # In an editable checkout the package directory carries no packaged lock
    # (the lock lives at the repository root and is force-included only into
    # wheels), so the installed-mode verifier must fail with the clear error
    # rather than pretending to verify.
    if (REPO / "src/benchweave_sdk" / "standards-lock.json").is_file():
        pytest.skip("packaged lock present; installed layout")
    with pytest.raises(ValueError, match="lock_missing"):
        verify_installed()


def test_checkout_root_detection() -> None:
    from benchweave_sdk.cli import _sdk_checkout_root

    assert _sdk_checkout_root() == REPO


def test_verify_installed_passes_on_an_installed_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mirror an installed wheel: the packaged lock sits INSIDE the package,
    # beside the vendored standards tree. This is the success path the
    # publish smoke also proves against the real wheel.
    package = tmp_path / "benchweave_sdk"
    package.mkdir()
    shutil.copy(REPO / "standards-lock.json", package / "standards-lock.json")
    shutil.copytree(
        REPO / "src/benchweave_sdk/standards",
        package / "standards",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    monkeypatch.setattr(standards_sync, "files", lambda _name: package)
    verify_installed()
