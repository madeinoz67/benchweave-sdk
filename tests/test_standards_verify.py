"""Verification paths for the vendored standards state, checkout and installed."""

from __future__ import annotations

import hashlib
import json
import shutil
import tomllib
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


# --- plugin-ui-class-reference 0.1.0 train sync (gateway issue #463, L2) ----
# The train arms pin the lock's train state so the sync commit cannot land
# without it: the new family row active+stable with digest-verified vendored
# bytes, the pure-addition posture (no prior row removed, no marker flip),
# the dependency_policy mirror carrying the seventh id, and the MINOR bump
# the carried-set motion requires. They derive everything from the committed
# tree — no gateway checkout needed — so they run in CI against the merge
# result alone.
#
# The #458 train's arms (otdp 0.2.3 / registry 0.1.3, the retained-flip and
# .bin arms) are retired here — per-train arms, replaced each train; the
# states they pinned are superseded by this train's lock.


def _train_lock() -> dict[str, object]:
    return json.loads((REPO / "standards-lock.json").read_bytes())


def _train_row(
    lock: dict[str, object], identifier: str, version: str
) -> dict[str, object] | None:
    standards = lock.get("standards")
    if not isinstance(standards, list):
        return None
    return next(
        (
            row
            for row in standards
            if isinstance(row, dict)
            and row.get("id") == identifier
            and row.get("version") == version
        ),
        None,
    )


def _train_vendored_digests(row: dict[str, object]) -> None:
    files = row.get("files")
    assert isinstance(files, list) and files, "the row lists no files"
    for file_row in files:
        assert isinstance(file_row, dict)
        rel = str(file_row.get("path", ""))
        path = REPO / "src/benchweave_sdk/standards" / rel
        assert path.is_file(), f"vendored file missing: {rel}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == file_row.get("sha256"), (
            f"digest mismatch: {rel}"
        )


def test_train_sync_lock_carries_classref_0_1_0_active() -> None:
    """The 0.1.0 row is active+stable; every file row matches the vendored
    bytes byte-for-byte."""
    row = _train_row(_train_lock(), "plugin-ui-class-reference", "0.1.0")
    assert row is not None, (
        "plugin-ui-class-reference@0.1.0 missing from standards-lock.json"
    )
    assert row.get("active") is True
    assert row.get("status") == "stable"
    _train_vendored_digests(row)


def test_train_sync_family_is_a_pure_addition() -> None:
    """Pure ADD: no prior row removed, no marker flipped. The six prior
    active rows stay active+stable and the eight retained rows survive
    (copy-never-move holds trivially — the family is the train's only
    carried-set motion)."""
    lock = _train_lock()
    standards = lock.get("standards")
    assert isinstance(standards, list)
    assert len(standards) == 15, f"expected 15 rows, found {len(standards)}"
    prior_actives = {
        "otdp": "0.2.3",
        "registry": "0.1.3",
        "execution": "0.2.0",
        "interface": "0.1.0",
        "plugin-ui": "0.3.1",
        "plugin-ui-preview": "0.2.0",
    }
    for identifier, version in prior_actives.items():
        row = _train_row(lock, identifier, version)
        assert row is not None, f"{identifier}@{version} dropped from the lock"
        assert row.get("active") is True, f"{identifier}@{version} lost its active marker"
        assert row.get("status") == "stable"
    retained = [row for row in standards if row.get("active") is False]
    assert len(retained) == 8, (
        f"expected 8 retained rows (the pre-train posture), found {len(retained)}"
    )


def test_train_sync_policy_mirror_carries_the_family() -> None:
    """The dependency_policy mirror (carried verbatim from the gateway
    manifest at sync time) declares the seventh id."""
    policy = _train_lock().get("dependency_policy")
    assert isinstance(policy, dict)
    declared = policy.get("standards")
    assert isinstance(declared, dict)
    assert sorted(declared) == [
        "execution",
        "interface",
        "otdp",
        "plugin-ui",
        "plugin-ui-class-reference",
        "plugin-ui-preview",
        "registry",
    ]


def test_train_sync_carries_the_sdk_0_13_0_bump() -> None:
    """A carried-set change is version motion: the bump-class gate refuses
    an EQUAL-version sync carrying it, so the sync rides a MINOR and the
    lock anchor moves with pyproject."""
    lock = _train_lock()
    compat = lock.get("compatibility")
    assert isinstance(compat, dict)
    assert compat.get("sdk") == "0.13.0", (
        f"lock anchor at {compat.get('sdk')}, expected 0.13.0"
    )
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == "0.13.0"
