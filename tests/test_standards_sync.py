"""SDK standards import verifies hashes, classifies changes and refuses drift."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.standards_sync import SyncReport, sync

REPO = Path(__file__).resolve().parents[1]


def _export(tmp_path: Path) -> Path:
    """Rebuild a corpus-shaped bundle from the SDK's committed lock and vendored tree.

    What this reproduces: the manifest rows the sync reads (``id``,
    ``version``, ``status`` and each file's ``path``/``sha256``) and the file
    bytes, which the lock pins to the vendored tree. What it does not: the
    gateway's ``export_bundle`` is not importable here, so the manifest is a
    synthetic subset of a real export (none of its provenance fields, such
    as ``exported_from``, ``released``, ``supersedes`` or ``size``), and the
    rebuild is circular by construction — a vendored tree that has drifted
    from the gateway's canonical corpus rebuilds into a bundle that agrees
    with itself. Corpus-to-vendored drift is the main repository's check
    (``make check-sdk-standards``); these tests pin the sync's own behaviour
    against a bundle, not the vendored tree's fidelity to the corpus.
    """
    lock = json.loads((REPO / "standards-lock.json").read_bytes())
    bundle = tmp_path / "bundle"
    standards: list[dict[str, Any]] = []
    for standard in lock["standards"]:
        rows: list[dict[str, str]] = []
        for file in standard["files"]:
            source = REPO / "src/benchweave_sdk/standards" / file["path"]
            target = bundle / "files" / file["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            rows.append({"path": file["path"], "sha256": file["sha256"]})
        standards.append(
            {
                "id": standard["id"],
                "version": standard["version"],
                "status": standard["status"],
                "files": rows,
            }
        )
    document = {"bundle_version": 1, "standards": standards}
    (bundle / "bundle-manifest.json").write_bytes(
        (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )
    return bundle


def _synced_sdk(tmp_path: Path, bundle: Path) -> Path:
    sdk = tmp_path / "sdk"
    (sdk / "src/benchweave_sdk").mkdir(parents=True)
    (sdk / "src/benchweave_sdk/__init__.py").write_text("")
    sync(bundle, sdk)
    return sdk


def test_first_sync_writes_lock_and_vendored_tree(tmp_path: Path) -> None:
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    lock = json.loads((sdk / "standards-lock.json").read_bytes())
    assert {s["id"] for s in lock["standards"]} == {
        "otdp", "registry", "execution", "interface", "plugin-ui", "plugin-ui-preview"
    }
    stamp = sdk / "src/benchweave_sdk/standards/otdp/_GENERATED.txt"
    first_line = stamp.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("otdp/")
    assert first_line.endswith("Generated from otdp@0.2.0 — do not edit")
    # Stamps live beside files that stay byte-identical to the bundle.
    document = json.loads((bundle / "bundle-manifest.json").read_bytes())
    entry = next(s["files"][0] for s in document["standards"] if s["id"] == "otdp")
    vendored = sdk / "src/benchweave_sdk/standards" / entry["path"]
    assert vendored.read_bytes() == (bundle / "files" / entry["path"]).read_bytes()


def test_check_mode_detects_tampered_file(tmp_path: Path) -> None:
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    victim = next((sdk / "src/benchweave_sdk/standards").rglob("*.json"))
    victim.write_text(victim.read_text() + " tampered")
    with pytest.raises(ValueError, match="hash_mismatch"):
        sync(bundle, sdk, check_only=True)


def test_unchanged_resync_is_noop_report(tmp_path: Path) -> None:
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    report = sync(bundle, sdk)
    assert report == SyncReport((), (), (), ())


def test_normative_change_without_version_bump_is_refused(tmp_path: Path) -> None:
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    document = json.loads((bundle / "bundle-manifest.json").read_bytes())
    target = next(s for s in document["standards"] if s["id"] == "otdp")
    asset = bundle / "files" / target["files"][0]["path"]
    asset.write_bytes(asset.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="standards_version_required"):
        sync(bundle, sdk)


def test_versioned_change_reports_changed(tmp_path: Path) -> None:
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    document = json.loads((bundle / "bundle-manifest.json").read_bytes())
    target = next(s for s in document["standards"] if s["id"] == "otdp")
    asset = bundle / "files" / target["files"][0]["path"]
    asset.write_bytes(asset.read_bytes() + b"\n")
    target["files"][0]["sha256"] = hashlib.sha256(asset.read_bytes()).hexdigest()
    target["version"] = "0.3.1"
    (bundle / "bundle-manifest.json").write_bytes(
        (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )
    report = sync(bundle, sdk)
    assert report.changed == ("otdp",)


def test_status_only_deprecation_is_reported(tmp_path: Path) -> None:
    """stable -> deprecated at the same version and hashes is reportable, not silent."""
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    document = json.loads((bundle / "bundle-manifest.json").read_bytes())
    target = next(s for s in document["standards"] if s["id"] == "otdp")
    target["status"] = "deprecated"
    (bundle / "bundle-manifest.json").write_bytes(
        (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )
    report = sync(bundle, sdk)
    assert report.deprecated == ("otdp",)
    assert report.changed == ()


def test_missing_bundle_file_is_vocabulary_prefixed(tmp_path: Path) -> None:
    """A manifest-listed file absent from files/ is a ValueError, not a bare OSError."""
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    victim = bundle / "files" / "registry/0.1.1/package-lock.schema.json"
    victim.unlink()
    with pytest.raises(ValueError, match="bundle_file_missing"):
        sync(bundle, sdk)


def test_corrupt_lock_is_vocabulary_prefixed(tmp_path: Path) -> None:
    """An unparsable lock is reported as lock_invalid, not a bare JSONDecodeError."""
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    (sdk / "standards-lock.json").write_text("{not json")
    with pytest.raises(ValueError, match="lock_invalid"):
        sync(bundle, sdk)


def test_check_command_exits_zero_on_clean_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import benchweave_sdk.standards_sync as standards_sync
    from benchweave_sdk import cli as sdk_cli

    monkeypatch.setattr(
        standards_sync, "sync", lambda *args, **kwargs: SyncReport((), (), (), ())
    )
    assert sdk_cli.main(["sync-standards", str(tmp_path), "--check"]) == 0


def test_check_command_exits_nonzero_on_nonempty_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import benchweave_sdk.standards_sync as standards_sync
    from benchweave_sdk import cli as sdk_cli

    monkeypatch.setattr(
        standards_sync,
        "sync",
        lambda *args, **kwargs: SyncReport(("otdp",), (), (), ()),
    )
    assert sdk_cli.main(["sync-standards", str(tmp_path), "--check"]) == 1


def test_check_command_exits_nonzero_on_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import benchweave_sdk.standards_sync as standards_sync
    from benchweave_sdk import cli as sdk_cli

    def _tampered(*args: object, **kwargs: object) -> SyncReport:
        raise ValueError("hash_mismatch: tampered")

    monkeypatch.setattr(standards_sync, "sync", _tampered)
    assert sdk_cli.main(["sync-standards", str(tmp_path), "--check"]) == 1


# --- --check with no bundle: the self-contained lane, no main-project export. ---


def test_self_check_clean_tree_verifies_without_bundle(tmp_path: Path) -> None:
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    assert sync(None, sdk, check_only=True) == SyncReport((), (), (), ())


def test_self_check_detects_tampered_file_without_bundle(tmp_path: Path) -> None:
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    victim = next((sdk / "src/benchweave_sdk/standards").rglob("*.json"))
    victim.write_text(victim.read_text() + " tampered")
    with pytest.raises(ValueError, match="hash_mismatch"):
        sync(None, sdk, check_only=True)


def test_self_check_detects_deleted_file_without_bundle(tmp_path: Path) -> None:
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    victim = next((sdk / "src/benchweave_sdk/standards").rglob("*.json"))
    victim.unlink()
    with pytest.raises(ValueError, match="hash_mismatch.*missing"):
        sync(None, sdk, check_only=True)


def test_self_check_detects_extra_file_without_bundle(tmp_path: Path) -> None:
    """A file in the tree the lock does not record would ride into wheels."""
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    stray = sdk / "src/benchweave_sdk/standards/otdp/EXTRA.txt"
    stray.write_text("not in the lock")
    with pytest.raises(ValueError, match="unexpected_vendored_file"):
        sync(None, sdk, check_only=True)


def test_self_check_detects_missing_stamp_without_bundle(tmp_path: Path) -> None:
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    (sdk / "src/benchweave_sdk/standards/otdp/_GENERATED.txt").unlink()
    with pytest.raises(ValueError, match="stamp_missing"):
        sync(None, sdk, check_only=True)


def test_no_bundle_without_check_flag_is_refused(tmp_path: Path) -> None:
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    with pytest.raises(ValueError, match="bundle_required"):
        sync(None, sdk)


def test_check_command_without_bundle_passes_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import benchweave_sdk.standards_sync as standards_sync
    from benchweave_sdk import cli as sdk_cli

    seen: dict[str, object] = {}

    def _capture(bundle: object, *, sdk_root: object, check_only: object) -> SyncReport:
        seen["bundle"] = bundle
        return SyncReport((), (), (), ())

    monkeypatch.setattr(standards_sync, "sync", _capture)
    assert sdk_cli.main(["sync-standards", "--check"]) == 0
    assert seen["bundle"] is None


def test_check_command_without_bundle_verifies_real_committed_tree() -> None:
    """End to end on the SDK checkout itself: the CLI's no-bundle lane is clean."""
    from benchweave_sdk import cli as sdk_cli

    assert sdk_cli.main(["sync-standards", "--check"]) == 0


# --- Guards a mutation run showed unpinned: deleting either kept the suite green. ---


def _manifest(bundle: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((bundle / "bundle-manifest.json").read_bytes())
    return document


def _rewrite_manifest(bundle: Path, document: dict[str, Any]) -> None:
    (bundle / "bundle-manifest.json").write_bytes(
        (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )


def _fresh_sdk(tmp_path: Path) -> Path:
    sdk = tmp_path / "sdk"
    (sdk / "src/benchweave_sdk").mkdir(parents=True)
    (sdk / "src/benchweave_sdk/__init__.py").write_text("")
    return sdk


def test_parent_traversal_in_a_manifest_row_is_refused_before_any_write(
    tmp_path: Path,
) -> None:
    """``_guard_path`` is the write boundary for untrusted bundles.

    A manifest row may only name ``<id>/...`` paths inside the vendored
    tree. Without the guard a ``..`` row is hashed, classified and written
    wherever it points; the payload is planted where the traversal resolves
    so that only the guard, not a missing-file error, can refuse the sync.
    """
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    payload = b"{}"
    (bundle / "escape.json").write_bytes(payload)  # bundle/files/otdp/../../escape.json
    document = _manifest(bundle)
    target = next(s for s in document["standards"] if s["id"] == "otdp")
    target["files"].append(
        {"path": "otdp/../../escape.json", "sha256": hashlib.sha256(payload).hexdigest()}
    )
    target["version"] = "0.3.1"  # classification accepts a bumped standard; only the guard is left
    _rewrite_manifest(bundle, document)
    with pytest.raises(ValueError, match="^bundle_path_invalid: "):
        sync(bundle, sdk)
    assert not list(sdk.rglob("escape.json")), "nothing may be written outside the vendored tree"
    sync(None, sdk, check_only=True)


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/otdp/absolute.json", id="absolute"),
        pytest.param("registry/0.1.0/foreign.json", id="foreign-standard-prefix"),
        pytest.param("otdp", id="no-file-component"),
        # A backslash is a character to PurePosixPath and a separator to the
        # Windows writer: refused everywhere, not only where it would escape.
        pytest.param(f"otdp/..{chr(92)}..{chr(92)}escape.json", id="backslash-traversal"),
        pytest.param("otdp/./alias.json", id="dot-segment"),
        pytest.param("otdp//alias.json", id="empty-segment"),
        pytest.param("otdp/C:escape.json", id="drive-separator"),
    ],
)
def test_manifest_row_shape_outside_the_standard_is_refused(tmp_path: Path, path: str) -> None:
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    document = _manifest(bundle)
    target = next(s for s in document["standards"] if s["id"] == "otdp")
    target["files"].append({"path": path, "sha256": "0" * 64})
    target["version"] = "0.3.1"
    _rewrite_manifest(bundle, document)
    with pytest.raises(ValueError, match="^bundle_path_invalid: "):
        sync(bundle, sdk)


def test_file_less_standard_cannot_put_its_stamp_outside_the_tree(tmp_path: Path) -> None:
    """The stamp is written at <tree>/<id>/ and a file-less standard never reaches _guard_path."""
    bundle = _export(tmp_path)
    sdk = _synced_sdk(tmp_path, bundle)
    document = _manifest(bundle)
    document["standards"].append(
        {"id": "../escaped", "version": "1.0.0", "status": "stable", "files": []}
    )
    _rewrite_manifest(bundle, document)
    with pytest.raises(ValueError, match="^bundle_manifest_invalid: standard id"):
        sync(bundle, sdk)
    inside = sdk / "src/benchweave_sdk/standards"
    stamps = [p for p in sdk.rglob("_GENERATED.txt") if not p.is_relative_to(inside)]
    assert stamps == [], "no stamp may be written outside the vendored tree"
    sync(None, sdk, check_only=True)


@pytest.mark.parametrize("first_sync", [True, False], ids=["first-sync", "version-bump"])
def test_manifest_digest_claims_are_recomputed_not_trusted(
    tmp_path: Path, first_sync: bool
) -> None:
    """STD-2: a manifest that vouches for itself is not a pin.

    A row whose ``sha256`` disagrees with the file bytes is refused exactly
    where classification would otherwise accept the standard — on a first
    sync (every standard is new) and on a version bump (content is expected
    to change) — and nothing is written.
    """
    bundle = _export(tmp_path)
    sdk = _fresh_sdk(tmp_path) if first_sync else _synced_sdk(tmp_path, bundle)
    document = _manifest(bundle)
    target = next(s for s in document["standards"] if s["id"] == "otdp")
    if not first_sync:
        target["version"] = "0.3.1"
    target["files"][0]["sha256"] = "0" * 64
    _rewrite_manifest(bundle, document)
    lock_before = None if first_sync else (sdk / "standards-lock.json").read_bytes()
    with pytest.raises(ValueError, match="^hash_mismatch: "):
        sync(bundle, sdk)
    if first_sync:
        assert not (sdk / "standards-lock.json").exists()
        assert not (sdk / "src/benchweave_sdk/standards").exists()
    else:
        assert (sdk / "standards-lock.json").read_bytes() == lock_before
        sync(None, sdk, check_only=True)
