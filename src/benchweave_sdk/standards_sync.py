"""Import a benchweave standards bundle into the SDK's own vendored tree.

The lock file is the record of what was vendored. ``--check`` recomputes the
vendored tree against that record and refuses silent drift; a bundle whose
content changed without a standards version increment is refused outright.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
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


def sync(bundle: Path | None, sdk_root: Path, *, check_only: bool = False) -> SyncReport:
    """Import ``bundle`` into ``sdk_root``'s vendored tree, or verify it.

    Classification hashes the bundle's files as they exist on disk, so a
    content change the manifest does not declare is still caught: unchanged
    version plus changed bytes raises ``standards_version_required``.

    With ``bundle=None`` and ``check_only``, verify the committed state alone
    — lock against vendored tree against stamps — with no main-project export.
    Importing without a bundle is refused.
    """
    if bundle is None:
        if not check_only:
            raise ValueError(
                "bundle_required: importing needs a bundle; only --check runs without one"
            )
        _verify_self_consistency(sdk_root)
        return SyncReport((), (), (), ())
    document = _load_bundle(bundle)
    lock = _read_lock(sdk_root)
    previous = {row["id"]: row for row in lock.get("standards", [])}
    # One read-and-digest pass over the bundle serves both the drift
    # classification and the manifest integrity check below; the files were
    # previously read and hashed twice.
    recomputed = {
        standard["id"]: _bundle_hashes(bundle, standard) for standard in document["standards"]
    }
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
        elif recomputed[identifier] != _lock_hashes(prior):
            raise ValueError(
                f"standards_version_required: {identifier} content changed without a "
                "standards version increment"
            )
        elif prior.get("status") != "deprecated" and standard["status"] == "deprecated":
            # Status-only transition: same version and bytes, new deprecation.
            deprecated.append(identifier)
    removed = sorted(previous)
    _verify_bundle_integrity(document, recomputed)
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
        if not isinstance(document, dict):
            raise ValueError("bundle_manifest_invalid: the manifest is not a JSON object")
        if document.get("bundle_version") != 1:
            raise ValueError("bundle_version_unsupported")
        for standard in document["standards"]:
            identifier = standard["id"]
            _ = standard["version"], standard["status"]
            if (problem := _identifier_problem(identifier)) is not None:
                # The per-standard stamp is written at <tree>/<id>/, and a
                # standard with no files never reaches _guard_path.
                raise ValueError(f"bundle_manifest_invalid: standard id {identifier!r} {problem}")
            for file in standard["files"]:
                _guard_path(identifier, file["path"])
                if not _is_digest(file["sha256"]):
                    raise ValueError(
                        f"bundle_manifest_invalid: sha256 for {file['path']} is not "
                        "64 lowercase hex characters"
                    )
    except json.JSONDecodeError as exc:
        raise ValueError(f"bundle_manifest_invalid: {exc}") from exc
    except (KeyError, TypeError) as exc:
        raise ValueError(f"bundle_manifest_invalid: {exc}") from exc
    return document


_DIGEST = re.compile(r"[0-9a-f]{64}")


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


# Names Windows resolves to a device whatever directory they appear in, with or
# without an extension (NUL, con.txt, COM1.json).
_WINDOWS_DEVICE = re.compile(r"(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?")


def _segment_problem(segment: str) -> str | None:
    """Why one path segment would not name what it says on some filesystem, or None."""
    if not segment or segment in (".", ".."):
        return "has an empty or dot segment"
    if segment != segment.rstrip(". "):
        # Windows strips trailing dots and spaces, so the name aliases another.
        return "has a segment ending in a dot or a space"
    if _WINDOWS_DEVICE.fullmatch(segment):
        return "names a Windows device"
    return None


def _identifier_problem(identifier: object) -> str | None:
    """Why a standard id cannot name a directory directly under the tree, or None."""
    if not isinstance(identifier, str) or not identifier:
        return "is not a non-empty string"
    if any(char in identifier for char in "/\\:"):
        return "is not a single path segment"
    return _segment_problem(identifier)


def _path_problem(identifier: object, path: object) -> str | None:
    """Why a ``<id>/...`` row cannot be joined onto a tree, or None.

    Judged as a string, never as a path, so the rule means the same thing on
    every platform: a backslash or a drive colon is an ordinary character to
    ``PurePosixPath`` but a separator to the ``Path`` that does the write on
    Windows, and a dot or empty segment is a traversal or an alias to some
    filesystem. hatch_build.py carries the same rule inline (STD-3).
    """
    if not isinstance(path, str):
        return "is not a string"
    segments = path.split("/")
    if len(segments) < 2:
        return "has no file component"
    if "\\" in path or ":" in path:
        return "contains a backslash or a drive separator"
    for segment in segments:
        if (problem := _segment_problem(segment)) is not None:
            return problem
    if segments[0] != identifier:
        return "is not under its standard's directory"
    if len(segments) == 2 and segments[1].casefold() == STAMP_NAME.casefold():
        return "claims the stamp path the writer reserves"
    return None


def _guard_path(identifier: str, path: str) -> None:
    """Bundle paths are ``<id>/``-prefixed and must stay inside the tree.

    This is the write boundary for a bundle: nothing is hashed or written
    for a row it refuses.
    """
    if _path_problem(identifier, path) is not None:
        raise ValueError(f"bundle_path_invalid: {path}")


def _read_lock(sdk_root: Path) -> dict[str, Any]:
    return _read_lock_file(sdk_root / LOCK_NAME)


def _read_lock_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        lock: dict[str, Any] = json.loads(path.read_bytes())
        if not isinstance(lock, dict):
            raise TypeError("the lock is not a JSON object")
        _ = lock["lock_version"]
        # Every reader below indexes these fields; checking the shape once
        # here keeps a malformed row a lock_invalid refusal in every lane,
        # rather than a bare KeyError from whichever lane meets it first.
        for standard in lock["standards"]:
            _ = standard["id"], standard["version"]
            for file in standard["files"]:
                _ = file["path"], file["sha256"]
    except json.JSONDecodeError as exc:
        raise ValueError(f"lock_invalid: {exc}") from exc
    except (KeyError, TypeError) as exc:
        raise ValueError(f"lock_invalid: {exc}") from exc
    if lock.get("lock_version") != 1:
        raise ValueError("lock_version_unsupported")
    return lock


def _bundle_hashes(bundle: Path, standard: dict[str, Any]) -> dict[str, str]:
    """Hashes recomputed from the bundle's files, not its manifest claims."""
    hashes: dict[str, str] = {}
    for file in standard["files"]:
        raw = _bundle_file(bundle, file["path"])
        hashes[file["path"]] = hashlib.sha256(raw).hexdigest()
    return hashes


def _bundle_file(bundle: Path, path: str) -> bytes:
    """Bundle payload bytes; a listed-but-absent file is a vocabulary error."""
    source = bundle / "files" / path
    if not source.is_file():
        raise ValueError(f"bundle_file_missing: {path}")
    return source.read_bytes()


def _lock_hashes(prior: dict[str, Any]) -> dict[str, str]:
    return {file["path"]: file["sha256"] for file in prior["files"]}


def _verify_bundle_integrity(
    document: dict[str, Any], recomputed: dict[str, dict[str, str]]
) -> None:
    """The manifest must describe the bytes actually present in the bundle.

    sha256 is the anchor: the lock records no sizes, only digests.
    ``recomputed`` carries the digests already computed from the bundle's
    files, so the bundle is read exactly once per sync.
    """
    for standard in document["standards"]:
        actual = recomputed[standard["id"]]
        for file in standard["files"]:
            if actual[file["path"]] != file["sha256"]:
                raise ValueError(f"hash_mismatch: {file['path']}")


def _collect_stamps(tree: Path, standards: list[dict[str, Any]]) -> set[str]:
    """Verify every standard's stamp is present; return their paths.

    Shared by every verification lane (#9): a missing stamp is drift in
    bundle-mode --check, the no-bundle lane, and the hatch build hook
    alike — it would ride into wheels unnoticed.
    """
    stamps: set[str] = set()
    for standard in standards:
        stamp = f"{standard['id']}/{STAMP_NAME}"
        if not (tree / stamp).is_file():
            raise ValueError(f"stamp_missing: {stamp}")
        stamps.add(stamp)
    return stamps


def _sweep_vendored_tree(tree: Path, recorded: set[str], stamps: set[str]) -> None:
    """The one extras sweep (#9): every file in the vendored tree must be
    lock-recorded, a per-standard stamp, or transient __pycache__ —
    presentation.py imports the vendored plugin-ui contracts module, so
    its bytecode cache appears beside the source; it is gitignored and
    never packaged. Anything else is drift: it would ship in a wheel
    built outside the gated paths."""
    present: set[str] = set()
    for entry in tree.rglob("*"):
        relative = entry.relative_to(tree)
        if entry.is_symlink() or entry.is_junction():
            # rglob does not descend a linked directory, so whatever sits
            # behind it would be invisible here while packaging follows the
            # link and ships it. Nothing in a vendored tree is a link.
            raise ValueError(f"unexpected_vendored_file: {relative.as_posix()} is a link")
        if entry.is_file() and "__pycache__" not in relative.parts:
            present.add(relative.as_posix())
    for path in sorted(present - recorded - stamps):
        raise ValueError(f"unexpected_vendored_file: {path}")


def _verify_vendored_tree(sdk_root: Path, lock: dict[str, Any]) -> None:
    """Recompute the vendored tree against the lock; refuse any drift.

    #9: this lane now verifies what the no-bundle lane verifies — per-file
    digests over lock-recorded paths, stamp presence per standard, and the
    extras sweep over the whole tree. A stray file or a missing stamp is
    drift here too, not only in the bundle-free lane.
    """
    _verify_tree(sdk_root / VENDORED, lock)


def _verify_tree(tree: Path, lock: dict[str, Any]) -> None:
    recorded: dict[str, str] = {}
    try:
        for standard in lock.get("standards", []):
            identifier = standard["id"]
            if (problem := _identifier_problem(identifier)) is not None:
                raise ValueError(f"lock_invalid: standard id {identifier!r} {problem}")
            for file in standard["files"]:
                # A lock row is joined onto the tree and hashed; an unguarded
                # row would make --check vouch for bytes outside it. The
                # build hook refuses the same rows (STD-3).
                if (problem := _path_problem(identifier, file["path"])) is not None:
                    raise ValueError(f"lock_invalid: path {file['path']!r} {problem}")
                recorded[file["path"]] = file["sha256"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"lock_invalid: {exc}") from exc
    if not recorded:
        raise ValueError("not_synced: no standards in the lock; run sync-standards first")
    for path, digest in sorted(recorded.items()):
        target = tree / path
        if not target.is_file():
            raise ValueError(f"hash_mismatch: {path} missing from the vendored tree")
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError(f"hash_mismatch: {path}")
    stamps = _collect_stamps(tree, lock.get("standards", []))
    _sweep_vendored_tree(tree, set(recorded), stamps)


def _verify_self_consistency(sdk_root: Path) -> None:
    """Verify the committed state alone: lock ↔ vendored tree ↔ stamps.

    The bundle-free ``--check`` lane proves the SDK repository is internally
    consistent with no main-project export. Beyond the per-file digests, an
    unrecorded file in the tree or a missing stamp is drift too: either would
    ride into wheels unnoticed.
    """
    _verify_state(sdk_root / LOCK_NAME, sdk_root / VENDORED)


def verify_installed() -> None:
    """Verify an installed SDK's vendored tree against its packaged lock.

    Installed distributions carry the lock inside the package (wheels since
    the lock was force-included), so ``sync-standards --check`` can prove
    integrity without a repository checkout — including the stamp and
    extras checks the repository lanes run. Importing a bundle still needs
    the checkout: it rewrites the source tree.
    """
    package = Path(str(files("benchweave_sdk")))
    lock_path = package / LOCK_NAME
    if not lock_path.is_file():
        raise ValueError(
            "lock_missing: this installed SDK does not package its standards lock; "
            "reinstall a newer benchweave-sdk or run --check from a repository checkout"
        )
    _verify_state(lock_path, package / "standards")


def _verify_state(lock_path: Path, tree: Path) -> None:
    lock = _read_lock_file(lock_path)
    _verify_tree(tree, lock)


def _write_vendored(bundle: Path, sdk_root: Path, document: dict[str, Any]) -> None:
    """Rewrite the vendored tree and lock; vendored bytes match the bundle exactly.

    The new tree is staged beside the old one and swapped in at the end, so
    an interrupted sync can never leave a half-empty vendored tree behind
    (the old ``rmtree``-then-write order destroyed the tree first). The lock
    is written only after the swap: a failure between the two surfaces as
    loud ``--check`` drift, never as a silently torn state.
    """
    tree = sdk_root / VENDORED
    staging = tree.with_name(tree.name + ".new")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    lock: dict[str, Any] = {
        "lock_version": 1,
        "standards": [],
        "compatibility": {
            "main_project": ">=0.1.0",
            "sdk": _sdk_version(sdk_root),
            "notes": None,
        },
    }
    try:
        for standard in document["standards"]:
            stamps: list[str] = []
            rows: list[dict[str, str]] = []
            for file in standard["files"]:
                raw = _bundle_file(bundle, file["path"])
                target = staging / file["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                stamps.append(
                    STAMP_LINE.format(
                        path=file["path"], identifier=standard["id"], version=standard["version"]
                    )
                )
                rows.append({"path": file["path"], "sha256": file["sha256"]})
            stamp_file = staging / standard["id"] / STAMP_NAME
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
        if tree.exists():
            retired = tree.with_name(tree.name + ".old")
            if retired.exists():
                shutil.rmtree(retired)
            tree.rename(retired)
            try:
                staging.rename(tree)
            except BaseException:
                # The old tree was already moved aside; put it back so a
                # failed swap leaves the previous state in place, not a
                # missing vendored tree.
                retired.rename(tree)
                raise
            shutil.rmtree(retired)
        else:
            staging.rename(tree)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
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
