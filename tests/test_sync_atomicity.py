"""Interrupted syncs never destroy the vendored tree; verification stays exact."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchweave_sdk import standards_sync
from benchweave_sdk.packaging import inventory, verify_inventory
from benchweave_sdk.standards_sync import SyncReport, sync

REPO = Path(__file__).resolve().parents[1]


def _export(tmp_path: Path) -> Path:
    """Rebuild a corpus-shaped bundle from this repository's lock and vendored tree.

    A synthetic subset of a real export and circular by construction; see
    ``test_standards_sync._export`` for what it does and does not reproduce.
    """
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


def _files(tree: Path) -> list[str]:
    return sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*") if p.is_file())


def _assert_no_sync_debris(sdk: Path) -> None:
    """Nothing an interrupted sync could leave behind may sit where packaging looks.

    The wheel packages ``src/benchweave_sdk`` wholesale, the sdist includes
    ``src``, and every verification lane walks only ``standards/`` — so the
    package directory must hold exactly its committed entries, and the
    staging root must be gone.
    """
    package = sdk / "src/benchweave_sdk"
    assert sorted(p.name for p in package.iterdir()) == ["__init__.py", "standards"]
    assert not (sdk / standards_sync.STAGING_DIR).exists()


def test_staging_lives_outside_the_packaged_tree(tmp_path: Path) -> None:
    """Structural pin: a crash cannot ship debris because staging is never under src/."""
    for path in standards_sync._staging_paths(tmp_path):
        assert path.is_relative_to(tmp_path)
        assert not path.is_relative_to(tmp_path / "src")


def test_interrupted_rewrite_preserves_the_existing_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fault fires inside the staged write loop, so this test enters ``_write_vendored``.

    Classification reads and digests every bundle file before the writer
    runs, so a fault counted on bundle reads never reached it. Counting
    writes into either the staging area or the tree itself instead means the
    old rmtree-then-write order fails this test: its tenth write lands in a
    tree it has already destroyed.
    """
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    tree = sdk / "src/benchweave_sdk/standards"
    before = _files(tree)
    staging, _retired = standards_sync._staging_paths(sdk)

    original = Path.write_bytes
    staged = {"count": 0}

    def failing_write(self: Path, data: bytes) -> int:
        if self.is_relative_to(staging) or self.is_relative_to(tree):
            staged["count"] += 1
            if staged["count"] >= 10:
                raise OSError("disk full")
        return original(self, data)

    monkeypatch.setattr(Path, "write_bytes", failing_write)
    with pytest.raises(OSError, match="disk full"):
        sync(bundle, sdk)
    monkeypatch.undo()

    assert staged["count"] == 10, "the fault must fire on the tenth write of the new tree"
    assert _files(tree) == before, "an interrupted sync must leave the old tree untouched"
    _assert_no_sync_debris(sdk)
    # And the committed state still verifies: lock and tree agree.
    sync(None, sdk, check_only=True)


def test_failed_swap_restores_the_previous_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    tree = sdk / "src/benchweave_sdk/standards"
    before = _files(tree)
    staging, retired = standards_sync._staging_paths(sdk)

    original_rename = Path.rename

    def failing_rename(self: Path, target: object) -> Path:
        if self == staging:
            # Exactly the staging->tree swap, after the old tree moved aside.
            assert retired.is_dir() and not tree.exists()
            raise OSError("swap interrupted")
        return original_rename(self, target)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "rename", failing_rename)
    with pytest.raises(OSError, match="swap interrupted"):
        sync(bundle, sdk)
    monkeypatch.undo()

    assert _files(tree) == before, "a failed swap must restore the previous tree"
    _assert_no_sync_debris(sdk)
    sync(None, sdk, check_only=True)


def test_orphaned_staging_never_reaches_a_check_lane_and_is_swept(tmp_path: Path) -> None:
    """Debris from a crash lives outside the tree and the package; the next sync sweeps it."""
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    for debris in standards_sync._staging_paths(sdk):
        (debris / "otdp").mkdir(parents=True)
        (debris / "otdp" / "partial.json").write_bytes(b"{")
    assert sync(None, sdk, check_only=True) == SyncReport((), (), (), ())
    package = sdk / "src/benchweave_sdk"
    assert sorted(p.name for p in package.iterdir()) == ["__init__.py", "standards"]
    sync(bundle, sdk)
    _assert_no_sync_debris(sdk)


def _park_the_tree(sdk: Path) -> Path:
    """The state a sync leaves when it dies between the swap's two renames."""
    tree = sdk / "src/benchweave_sdk/standards"
    _staging, retired = standards_sync._staging_paths(sdk)
    retired.parent.mkdir(parents=True)
    tree.rename(retired)
    return tree


def test_a_parked_tree_is_put_back_before_a_recovery_sync_can_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The parked tree is the only copy; a recovery sync that fails must not cost it."""
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    before = _files(sdk / "src/benchweave_sdk/standards")
    tree = _park_the_tree(sdk)
    with pytest.raises(ValueError, match="^hash_mismatch: .* missing from the vendored tree"):
        sync(None, sdk, check_only=True)

    staging, _retired = standards_sync._staging_paths(sdk)
    original = Path.write_bytes

    def failing_write(self: Path, data: bytes) -> int:
        if self.is_relative_to(staging):
            raise OSError("disk full")
        return original(self, data)

    monkeypatch.setattr(Path, "write_bytes", failing_write)
    with pytest.raises(OSError, match="disk full"):
        sync(bundle, sdk)
    monkeypatch.undo()

    assert _files(tree) == before, "the last good tree must survive a failed recovery sync"
    _assert_no_sync_debris(sdk)
    sync(None, sdk, check_only=True)


def test_a_recovery_sync_completes_from_the_parked_state(tmp_path: Path) -> None:
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    before = _files(sdk / "src/benchweave_sdk/standards")
    tree = _park_the_tree(sdk)
    assert sync(bundle, sdk) == SyncReport((), (), (), ())
    assert _files(tree) == before
    _assert_no_sync_debris(sdk)
    sync(None, sdk, check_only=True)


def test_single_pass_hashing_still_refuses_an_undeclared_content_change(tmp_path: Path) -> None:
    """One read-and-digest pass feeds classification and the integrity check alike.

    A byte change the manifest does not declare is classified first, so the
    refusal is ``standards_version_required``, exactly as before the pass
    was shared.
    """
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, _export(tmp_path / "clean"))
    victim = next((bundle / "files").rglob("*.json"))
    victim.write_bytes(victim.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="^standards_version_required: "):
        sync(bundle, sdk)


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


@pytest.mark.parametrize("kind", ["dangling", "directory"])
def test_verify_inventory_refuses_symlinks_met_during_the_walk(tmp_path: Path, kind: str) -> None:
    """The hash-free walk keeps inventory()'s symlink refusal, not only its real-root one.

    Neither kind counts as a file, so without the in-walk refusal both pass
    silently as if the bundle held nothing but its listed files.
    """
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "a.json").write_bytes(b"{}")
    listed = inventory(root)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    target = elsewhere if kind == "directory" else tmp_path / "absent.json"
    try:
        (root / "link").symlink_to(target, target_is_directory=kind == "directory")
    except OSError:
        pytest.skip("symlinks unavailable (privilege or filesystem)")
    with pytest.raises(ValueError, match="^Symlink inventory path$"):
        verify_inventory(root, listed)
