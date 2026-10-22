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


# --- plugin-ui-class-reference 0.3.0 train sync (gateway issue #463) ----
# The train arms pin the lock's train state so the sync commit cannot land
# without it: the new family rows active+stable with digest-verified vendored
# bytes, the pure-addition posture (no prior row removed; the two superseded
# actives flip to retained, never deleted), the dependency_policy mirror
# carrying the seventh id, and the MINOR bump the carried-set motion
# requires. They derive everything from the committed tree — no gateway
# checkout needed — so they run in CI against the merge result alone.
#
# The #458 train's arms (otdp 0.2.3 / registry 0.1.3, the retained-flip and
# .bin arms) were retired at L2; the L5 arms (classref 0.2.0 active, the
# 17-row posture) are retired here — per-train arms, replaced each train;
# the states they pinned are superseded by this train's lock.


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


def test_train_sync_lock_carries_classref_0_3_0_active() -> None:
    """The 0.3.0 row is active+stable; every file row matches the vendored
    bytes byte-for-byte. The train keeps plugin-ui 0.4.0 active beside it —
    the family's cross-constraint window requires the 0.4.0 schemas."""
    row = _train_row(_train_lock(), "plugin-ui-class-reference", "0.3.0")
    assert row is not None, (
        "plugin-ui-class-reference@0.3.0 missing from standards-lock.json"
    )
    assert row.get("active") is True
    assert row.get("status") == "stable"
    _train_vendored_digests(row)
    ui_row = _train_row(_train_lock(), "plugin-ui", "0.4.0")
    assert ui_row is not None, "plugin-ui@0.4.0 missing from standards-lock.json"
    assert ui_row.get("active") is True
    assert ui_row.get("status") == "stable"
    _train_vendored_digests(ui_row)


def test_train_sync_family_is_a_pure_addition() -> None:
    """The train's row posture at the LOCK: the multi-serving classref
    family adds its 0.3.0 row (0.2.0 flips to retained, never deleted —
    0.1.0 stays retained beside it), and the single-serving plugin-ui
    family CONSUMES its predecessor row (0.3.1 leaves the lock; its
    digest-frozen bytes stay in the gateway corpus — the lock carries the
    served set, not the corpus archive). The six untouched actives stay
    active+stable; twelve retained rows survive. The #450 train added
    interface 0.1.1 as a second ACTIVE interface row (multi-serving
    beside 0.1.0) — 17 -> 18; #525's OTDP train adds the otdp 0.2.4 row
    beside the retained 0.2.3 — 18 -> 19."""
    lock = _train_lock()
    standards = lock.get("standards")
    assert isinstance(standards, list)
    assert len(standards) == 19, f"expected 19 rows, found {len(standards)}"
    prior_actives = {
        "otdp": "0.2.4",
        "registry": "0.1.3",
        "execution": "0.2.0",
        "interface": "0.1.1",
        "plugin-ui": "0.4.0",
        "plugin-ui-preview": "0.2.0",
    }
    for identifier, version in prior_actives.items():
        row = _train_row(lock, identifier, version)
        assert row is not None, f"{identifier}@{version} dropped from the lock"
        assert row.get("active") is True, f"{identifier}@{version} lost its active marker"
        assert row.get("status") == "stable"
    retained_row = _train_row(lock, "plugin-ui-class-reference", "0.1.0")
    assert retained_row is not None, "classref 0.1.0 dropped from the lock"
    assert retained_row.get("active") is False, (
        "classref 0.1.0 kept its active marker after the train"
    )
    assert retained_row.get("status") == "retained"
    # This train's own multi-serving flip: classref 0.2.0 goes retained
    # exactly the 0.1.0 way (one ACTIVE row per id; the prior version's
    # bytes stay carried, its marker does not).
    classref_prior = _train_row(lock, "plugin-ui-class-reference", "0.2.0")
    assert classref_prior is not None, "classref 0.2.0 dropped from the lock"
    assert classref_prior.get("active") is False, (
        "classref 0.2.0 kept its active marker beside 0.3.0"
    )
    assert classref_prior.get("status") == "retained"
    # The #450 train's own multi-serving flip: interface 0.1.0 goes
    # retained exactly the classref way (one ACTIVE row per id; the prior
    # version's bytes stay carried, its marker does not).
    interface_prior = _train_row(lock, "interface", "0.1.0")
    assert interface_prior is not None, "interface 0.1.0 dropped from the lock"
    assert interface_prior.get("active") is False, (
        "interface 0.1.0 kept its active marker beside 0.1.1"
    )
    assert interface_prior.get("status") == "retained"
    consumed = _train_row(lock, "plugin-ui", "0.3.1")
    assert consumed is None, (
        "plugin-ui 0.3.1 stayed in the lock — the single-serving family's "
        "active succession consumes its predecessor row (the corpus keeps "
        "the digest-frozen bytes, not this lock)"
    )
    retained = [row for row in standards if row.get("active") is False]
    assert len(retained) == 12, (
        f"expected 12 retained rows (the post-train posture), found {len(retained)}"
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


def test_train_sync_lock_anchor_moves_with_pyproject() -> None:
    """A carried-set change is version motion: the bump-class gate refuses
    an EQUAL-version sync carrying it, so the sync rides a MINOR and the
    lock anchor moves with pyproject."""
    lock = _train_lock()
    compat = lock.get("compatibility")
    assert isinstance(compat, dict)
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]
    assert compat.get("sdk") == version, (
        f"lock anchor at {compat.get('sdk')}, pyproject at {version}"
    )
