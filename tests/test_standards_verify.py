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


# --- otdp 0.2.3 + registry 0.1.3 train sync (gateway train PR #458) ---------
# The train arms pin the lock's train state so the sync commit cannot land
# without it: new active rows with digest-verified vendored bytes, the
# superseded rows flipped to retained (copy-never-move), the disclosed .bin
# watch item resolved end-to-end, and the MINOR bump the carried-set motion
# requires. They derive everything from the committed tree — no gateway
# checkout needed — so they run in CI against the merge result alone.


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


def test_train_sync_lock_carries_otdp_0_2_3_active() -> None:
    """The 0.2.3 row is active+stable; every file row matches the vendored
    bytes byte-for-byte."""
    row = _train_row(_train_lock(), "otdp", "0.2.3")
    assert row is not None, "otdp@0.2.3 missing from standards-lock.json"
    assert row.get("active") is True
    assert row.get("status") == "stable"
    _train_vendored_digests(row)


def test_train_sync_lock_carries_registry_0_1_3_active() -> None:
    """The 0.1.3 row is active+stable; every file row matches the vendored
    bytes byte-for-byte."""
    row = _train_row(_train_lock(), "registry", "0.1.3")
    assert row is not None, "registry@0.1.3 missing from standards-lock.json"
    assert row.get("active") is True
    assert row.get("status") == "stable"
    _train_vendored_digests(row)


def test_train_sync_prior_active_rows_flip_to_retained() -> None:
    """Copy-never-move: the superseded 0.2.2/0.1.2 rows stay listed with
    their files intact and lose only the active marker."""
    lock = _train_lock()
    for identifier, prior in (("otdp", "0.2.2"), ("registry", "0.1.2")):
        row = _train_row(lock, identifier, prior)
        assert row is not None, f"{identifier}@{prior} dropped from the lock"
        assert row.get("active") is False
        assert row.get("status") == "retained"
        _train_vendored_digests(row)


def test_train_sync_reference_analyzer_image_bin_ships() -> None:
    """The disclosed watch item: reference-analyzer-config.json pins its bench
    image by sha256; a vendor walk that drops the .bin dangles that pin. The
    arm resolves config → file → digest end-to-end, then checks the lock row
    carries the same digest."""
    example_dir = REPO / "src/benchweave_sdk/standards/otdp/0.2.3/examples"
    assert example_dir.is_dir(), "otdp/0.2.3 absent from the vendored tree"
    config = json.loads((example_dir / "reference-analyzer-config.json").read_bytes())
    named = config["integration"]["adapter"]["configuration"]["files"]
    images = [entry for entry in named if entry.get("id") == "bench_image"]
    assert images, "the analyzer example no longer names a bench image"
    pinned = images[0]
    image = example_dir / str(pinned["path"])
    assert image.is_file(), f"the vendor walk dropped {pinned['path']}"
    assert hashlib.sha256(image.read_bytes()).hexdigest() == pinned["sha256"], (
        "the shipped .bin no longer matches the example's pinned digest"
    )
    row = _train_row(_train_lock(), "otdp", "0.2.3")
    assert row is not None
    files = row.get("files")
    assert isinstance(files, list)
    lock_rows = {
        str(entry.get("path")): entry.get("sha256")
        for entry in files
        if isinstance(entry, dict)
    }
    assert (
        lock_rows.get(f"otdp/0.2.3/examples/{pinned['path']}") == pinned["sha256"]
    ), "the .bin lacks a lock row carrying the pinned digest"


def test_train_sync_carries_the_sdk_0_12_0_bump() -> None:
    """Two carried-set motions in one arc is version motion: the bump-class
    gate refuses a PATCH carrying it (#145 lesson), so the sync rides a MINOR
    and the lock anchor moves with pyproject."""
    lock = _train_lock()
    compat = lock.get("compatibility")
    assert isinstance(compat, dict)
    assert compat.get("sdk") == "0.12.0", (
        f"lock anchor at {compat.get('sdk')}, expected 0.12.0"
    )
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == "0.12.0"
