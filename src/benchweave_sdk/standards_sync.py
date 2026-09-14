"""Import a benchweave standards bundle into the SDK's own vendored tree.

The lock file is the record of what was vendored. ``--check`` recomputes the
vendored tree against that record and refuses silent drift; a bundle whose
content changed without a standards version increment is refused outright.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

LOCK_NAME = "standards-lock.json"
VENDORED = "src/benchweave_sdk/standards"
STAMP_NAME = "_GENERATED.txt"
STAMP_LINE = "{path} — Generated from {identifier}@{version} — do not edit"


@dataclass(frozen=True)
class SyncReport:
    """Classified outcome of comparing a bundle against the locked state."""

    added: tuple[str, ...]
    changed: tuple[str, ...]
    deprecated: tuple[str, ...]
    removed: tuple[str, ...]


def sync(bundle: Path, sdk_root: Path, *, check_only: bool = False) -> SyncReport:
    """Import ``bundle`` into ``sdk_root``'s vendored tree, or verify it.

    Classification hashes the bundle's files as they exist on disk, so a
    content change the manifest does not declare is still caught: unchanged
    version plus changed bytes raises ``standards_version_required``.
    """
    document = _load_bundle(bundle)
    lock = _read_lock(sdk_root)
    previous = {row["id"]: row for row in lock.get("standards", [])}
    added: list[str] = []
    changed: list[str] = []
    deprecated: list[str] = []
    for standard in document["standards"]:
        identifier = standard["id"]
        prior = previous.pop(identifier, None)
        if prior is None:
            added.append(identifier)
        elif prior["version"] != standard["version"]:
            changed.append(identifier)
            if standard["status"] == "deprecated":
                deprecated.append(identifier)
        elif _bundle_hashes(bundle, standard) != _lock_hashes(prior):
            raise ValueError(
                f"standards_version_required: {identifier} content changed without a "
                "standards version increment"
            )
    removed = sorted(previous)
    _verify_bundle_integrity(bundle, document)
    if check_only:
        _verify_vendored_tree(sdk_root, lock)
    else:
        _write_vendored(bundle, sdk_root, document)
    return SyncReport(
        tuple(sorted(added)),
        tuple(sorted(changed)),
        tuple(sorted(deprecated)),
        tuple(removed),
    )


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _load_bundle(bundle: Path) -> dict[str, Any]:
    manifest = bundle / "bundle-manifest.json"
    if not manifest.is_file():
        raise ValueError(f"bundle_manifest_missing: {manifest}")
    try:
        document: dict[str, Any] = json.loads(manifest.read_bytes())
        if document.get("bundle_version") != 1:
            raise ValueError("bundle_version_unsupported")
        for standard in document["standards"]:
            _ = standard["id"], standard["version"], standard["status"]
            for file in standard["files"]:
                _guard_path(standard["id"], file["path"])
    except json.JSONDecodeError as exc:
        raise ValueError(f"bundle_manifest_invalid: {exc}") from exc
    except (KeyError, TypeError) as exc:
        raise ValueError(f"bundle_manifest_invalid: {exc}") from exc
    return document


def _guard_path(identifier: str, path: str) -> None:
    """Bundle paths are ``<id>/``-prefixed and must stay inside the tree."""
    pure = PurePosixPath(path)
    parts = pure.parts
    if len(parts) < 2 or pure.is_absolute() or ".." in parts or parts[0] != identifier:
        raise ValueError(f"bundle_path_invalid: {path}")


def _read_lock(sdk_root: Path) -> dict[str, Any]:
    path = sdk_root / LOCK_NAME
    if not path.is_file():
        return {}
    lock: dict[str, Any] = json.loads(path.read_bytes())
    if lock.get("lock_version") != 1:
        raise ValueError("lock_version_unsupported")
    return lock


def _bundle_hashes(bundle: Path, standard: dict[str, Any]) -> dict[str, str]:
    """Hashes recomputed from the bundle's files, not its manifest claims."""
    return {
        file["path"]: hashlib.sha256((bundle / "files" / file["path"]).read_bytes()).hexdigest()
        for file in standard["files"]
    }


def _lock_hashes(prior: dict[str, Any]) -> dict[str, str]:
    return {file["path"]: file["sha256"] for file in prior["files"]}


def _verify_bundle_integrity(bundle: Path, document: dict[str, Any]) -> None:
    """The manifest must describe the bytes actually present in the bundle.

    sha256 is the anchor: the lock records no sizes, only digests.
    """
    for standard in document["standards"]:
        for file in standard["files"]:
            raw = (bundle / "files" / file["path"]).read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest != file["sha256"]:
                raise ValueError(f"hash_mismatch: {file['path']}")


def _verify_vendored_tree(sdk_root: Path, lock: dict[str, Any]) -> None:
    """Recompute the vendored tree against the lock; refuse any drift."""
    recorded = {
        file["path"]: file["sha256"]
        for standard in lock.get("standards", [])
        for file in standard["files"]
    }
    if not recorded:
        raise ValueError("not_synced: no standards in the lock; run sync-standards first")
    tree = sdk_root / VENDORED
    for path, digest in sorted(recorded.items()):
        target = tree / path
        if not target.is_file():
            raise ValueError(f"hash_mismatch: {path} missing from the vendored tree")
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError(f"hash_mismatch: {path}")


def _write_vendored(bundle: Path, sdk_root: Path, document: dict[str, Any]) -> None:
    """Rewrite the vendored tree and lock; vendored bytes match the bundle exactly."""
    tree = sdk_root / VENDORED
    if tree.exists():
        shutil.rmtree(tree)
    tree.mkdir(parents=True)
    lock: dict[str, Any] = {
        "lock_version": 1,
        "standards": [],
        "compatibility": {
            "main_project": ">=0.1.0",
            "sdk": _sdk_version(sdk_root),
            "notes": None,
        },
    }
    for standard in document["standards"]:
        stamps: list[str] = []
        rows: list[dict[str, str]] = []
        for file in standard["files"]:
            raw = (bundle / "files" / file["path"]).read_bytes()
            target = tree / file["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            stamps.append(
                STAMP_LINE.format(
                    path=file["path"], identifier=standard["id"], version=standard["version"]
                )
            )
            rows.append({"path": file["path"], "sha256": file["sha256"]})
        stamp_file = tree / standard["id"] / STAMP_NAME
        stamp_file.parent.mkdir(parents=True, exist_ok=True)
        stamp_file.write_text("\n".join(stamps) + "\n", encoding="utf-8")
        lock["standards"].append(
            {
                "id": standard["id"],
                "version": standard["version"],
                "status": standard["status"],
                "files": rows,
            }
        )
    (sdk_root / LOCK_NAME).write_bytes(_canonical_json(lock))


def _sdk_version(sdk_root: Path) -> str:
    """The SDK's own version; generated roots without one report ``unknown``."""
    pyproject = sdk_root / "pyproject.toml"
    if not pyproject.is_file():
        return "unknown"
    try:
        with pyproject.open("rb") as handle:
            return str(tomllib.load(handle)["project"]["version"])
    except (tomllib.TOMLDecodeError, KeyError):
        return "unknown"
