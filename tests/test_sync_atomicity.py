"""Interrupted syncs never destroy the vendored tree; verification stays exact."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchweave_sdk import standards_sync
from benchweave_sdk.packaging import inventory, verify_inventory
from benchweave_sdk.standards_sync import sync

REPO = Path(__file__).resolve().parents[1]


def _export(tmp_path: Path) -> Path:
    """Reconstruct the corpus bundle from this repository's lock and tree."""
    lock = json.loads((REPO / "standards-lock.json").read_bytes())
    bundle = tmp_path / "bundle"
    (bundle / "files").mkdir(parents=True)
    manifest: dict[str, object] = {"bundle_version": 1, "standards": []}
    for standard in lock["standards"]:
        manifest["standards"].append(  # type: ignore[attr-defined]
            {
                "id": standard["id"],
                "version": standard["version"],
                "status": standard["status"],
                "files": standard["files"],
            }
        )
        for file in standard["files"]:
            source = REPO / "src/benchweave_sdk/standards" / file["path"]
            target = bundle / "files" / file["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    (bundle / "bundle-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return bundle


def _synced_sdk(tmp_path: Path, bundle: Path) -> Path:
    sdk = tmp_path / "sdk"
    (sdk / "src/benchweave_sdk").mkdir(parents=True)
    (sdk / "src/benchweave_sdk/__init__.py").write_text("")
    sync(bundle, sdk)
    return sdk


def test_interrupted_rewrite_preserves_the_existing_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    tree = sdk / "src/benchweave_sdk/standards"
    before = sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*") if p.is_file())

    original = standards_sync._bundle_file
    calls = {"count": 0}

    def failing(bundle_path: Path, path: str) -> bytes:
        calls["count"] += 1
        if calls["count"] >= 10:
            raise OSError("disk full")
        return original(bundle_path, path)

    monkeypatch.setattr(standards_sync, "_bundle_file", failing)
    with pytest.raises(OSError, match="disk full"):
        sync(bundle, sdk)
    monkeypatch.undo()

    after = sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*") if p.is_file())
    assert after == before, "an interrupted sync must leave the old tree untouched"
    assert not tree.with_name(tree.name + ".new").exists()
    # And the committed state still verifies: lock and tree agree.
    sync(None, sdk, check_only=True)


def test_single_read_sync_still_verifies_and_refuses_tampering(tmp_path: Path) -> None:
    bundle = _export(tmp_path)
    victim = next((bundle / "files").rglob("*.json"))
    victim.write_bytes(victim.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="hash_mismatch|standards_version_required"):
        sync(bundle, _synced_sdk(tmp_path, _export(tmp_path / "clean")))


def test_verify_inventory_detects_unlisted_files(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "a.json").write_bytes(b"{}")
    listed = inventory(root)
    verify_inventory(root, listed)
    (root / "b.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="Unlisted inventory path"):
        verify_inventory(root, listed)


def test_verify_inventory_refuses_symlinked_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "a.json").write_bytes(b"{}")
    listed = inventory(real)
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable (privilege or filesystem)")
    with pytest.raises(ValueError, match="real bundle directory"):
        verify_inventory(alias, listed)


def test_failed_swap_restores_the_previous_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    tree = sdk / "src/benchweave_sdk/standards"
    before = sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*") if p.is_file())

    original_rename = Path.rename

    def failing_rename(self: Path, target: object) -> Path:
        # Fail exactly the staging->tree swap, after the old tree moved aside.
        if self.name.endswith(".new"):
            raise OSError("swap interrupted")
        return original_rename(self, target)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "rename", failing_rename)
    with pytest.raises(OSError, match="swap interrupted"):
        sync(bundle, sdk)
    monkeypatch.undo()

    after = sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*") if p.is_file())
    assert after == before, "a failed swap must restore the previous tree"
    assert not tree.with_name(tree.name + ".old").exists()
    sync(None, sdk, check_only=True)
