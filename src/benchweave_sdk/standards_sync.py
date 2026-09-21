"""Import a benchweave standards bundle into the SDK's own vendored tree.

The lock file is the record of what was vendored. ``--check`` recomputes the
vendored tree against that record and refuses silent drift; a bundle whose
content changed without a standards version increment is refused outright.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import time
import tomllib
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

LOCK_NAME = "standards-lock.json"
VENDORED = "src/benchweave_sdk/standards"
STAMP_NAME = "_GENERATED.txt"
STAMP_LINE = "{path} — Generated from {identifier}@{version} — do not edit"
STAGING_DIR = ".standards-sync"
# The 8.3 short name of _GENERATED.txt. A row spelled with the alias can
# resolve to the stamp at lookup when the stamp was created first (a
# hand-crafted tree); this writer's row-before-stamp order avoids that —
# refused regardless as defense-in-depth.
_STAMP_SHORT_NAME = re.compile(r"(?i)_gener~[0-9]+\.txt")


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
    # One pass reads every bundle file once and keeps its bytes: the digests
    # serve classification and the integrity check, and an import writes those
    # same bytes out. Before this, a standard whose version and bytes were
    # unchanged was hashed twice (once in each of those two places) and an
    # import read every file again to write it. Added and version-incremented
    # standards were already hashed only once, so a first sync saves the
    # second read, not a hash.
    payloads = {
        standard["id"]: _bundle_payloads(bundle, standard) for standard in document["standards"]
    }
    recomputed = {
        identifier: {path: hashlib.sha256(raw).hexdigest() for path, raw in files.items()}
        for identifier, files in payloads.items()
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
        with _sync_mutex(sdk_root):
            _write_vendored(sdk_root, document, payloads, recomputed)
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
        standards = document.get("standards")
        if not isinstance(standards, list) or not standards:
            # No row ever reaches a guard here, and the writer would exchange
            # the whole vendored tree for an empty one — a state every
            # verification lane refuses only after the destruction.
            raise ValueError(
                "bundle_manifest_invalid: the standards list is missing or empty"
            )
        seen_ids: set[str] = set()
        for standard in standards:
            identifier = standard["id"]
            _ = standard["version"], standard["status"]
            if (problem := _identifier_problem(identifier)) is not None:
                # The per-standard stamp is written at <tree>/<id>/, and a
                # standard with no files never reaches _guard_path.
                raise ValueError(f"bundle_manifest_invalid: standard id {identifier!r} {problem}")
            if unicodedata.normalize("NFC", identifier).casefold() in seen_ids:
                # Every later stage keys per-standard state by id (last
                # wins); a duplicate would otherwise surface as a bare
                # KeyError from the integrity check instead of a refusal.
                # Compared case-folded and NFC-normalized: OTDP and otdp are
                # one directory on Windows and macOS, and so are the NFC and
                # NFD spellings of the same name.
                raise ValueError(f"bundle_manifest_invalid: duplicate standard id {identifier!r}")
            seen_ids.add(unicodedata.normalize("NFC", identifier).casefold())
            seen_paths: set[str] = set()
            for file in standard["files"]:
                _guard_path(identifier, file["path"])
                if not _is_digest(file["sha256"]):
                    raise ValueError(
                        f"bundle_manifest_invalid: sha256 for {file['path']} is not "
                        "64 lowercase hex characters"
                    )
                if file["path"].casefold() in seen_paths:
                    raise ValueError(
                        f"bundle_manifest_invalid: duplicate file path {file['path']!r} "
                        f"in {identifier!r}"
                    )
                seen_paths.add(file["path"].casefold())
    except json.JSONDecodeError as exc:
        raise ValueError(f"bundle_manifest_invalid: {exc}") from exc
    except (KeyError, TypeError) as exc:
        raise ValueError(f"bundle_manifest_invalid: {exc}") from exc
    return document


_DIGEST = re.compile(r"[0-9a-f]{64}")


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


# Names Windows resolves to a device whatever directory they appear in, with or
# without an extension (NUL, con.txt, COM1.json); the superscript digit forms
# (com¹, lpt²) and the console API names (conin$, conout$) resolve as devices
# too. COM0 is not a device — the class is COM1–COM9 and LPT1–LPT9, plus the
# superscript forms of 1–3.
_WINDOWS_DEVICE = re.compile(
    r"(?i)(con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³]|conin\$|conout\$)(\..*)?"
)
# Characters a Windows filesystem cannot write in a name at all; the row and
# id rules are judged as strings so the sync refuses them on every platform
# rather than failing mid-write only where they are unwritable.
_WINDOWS_UNWRITABLE = re.compile(r"[<>:\"|?*\x00-\x1f]")


def _segment_problem(segment: str) -> str | None:
    """Why one path segment would not name what it says on some filesystem, or None."""
    if not segment or segment in (".", ".."):
        return "has an empty or dot segment"
    if segment != segment.rstrip(". "):
        # Windows strips trailing dots and spaces, so the name aliases another.
        return "has a segment ending in a dot or a space"
    if _WINDOWS_DEVICE.fullmatch(segment):
        return "names a Windows device"
    if _WINDOWS_UNWRITABLE.search(segment):
        return "has a character a Windows filesystem cannot write"
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
    if len(segments) == 2 and (
        segments[1].casefold() == STAMP_NAME.casefold()
        or _STAMP_SHORT_NAME.fullmatch(segments[1])
    ):
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


def _bundle_payloads(bundle: Path, standard: dict[str, Any]) -> dict[str, bytes]:
    """One standard's bundle bytes, read once; digests and the written tree both come from these.

    The corpus is a few dozen small documents, so holding it for the length
    of a sync costs nothing worth a second pass over the disk.
    """
    return {file["path"]: _bundle_file(bundle, file["path"]) for file in standard["files"]}


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


def _staging_paths(sdk_root: Path) -> tuple[Path, Path]:
    """Where an in-flight sync stages the new tree and parks the old one.

    Both live under ``<sdk_root>/.standards-sync/`` — outside ``src`` — so a
    tree orphaned by a crash mid-sync cannot ship: the wheel packages
    ``src/benchweave_sdk`` and the sdist's include list is explicit, and
    neither names this directory. It sits inside the checkout, hence on the
    vendored tree's own filesystem, which is what keeps the swap's renames
    atomic.
    """
    root = sdk_root / STAGING_DIR
    return root / "new", root / "old"


def _clear_staging(staging: Path, retired: Path) -> None:
    """Sweep what an earlier sync left behind, or say exactly what is in the way.

    Nothing has been touched when this runs, so a leftover that cannot be
    removed (a file an antivirus scan holds open, a read-only entry, a plain
    file sitting where the staging directory goes) is a refusal that names
    the path, not a raw OSError, and the vendored tree is still intact.
    """
    root = staging.parent
    if (root.exists() or root.is_symlink()) and (root.is_symlink() or not root.is_dir()):
        raise ValueError(
            f"sync_staging_blocked: {root} is not a directory; remove it and run the sync again"
        )
    for leftover in (staging, retired):
        if leftover.is_symlink() or leftover.is_file():
            leftover.unlink(missing_ok=True)
        elif leftover.exists():
            shutil.rmtree(leftover, ignore_errors=True)
        if leftover.exists() or leftover.is_symlink():
            raise ValueError(
                f"sync_staging_blocked: {leftover} could not be removed; "
                "delete it and run the sync again"
            )


@contextlib.contextmanager
def _sync_mutex(sdk_root: Path) -> Iterator[None]:
    """One sync at a time per checkout: the swap's guarantees are single-flight.

    A plain ``O_CREAT | O_EXCL`` lock file beside the staging directories,
    carrying the owner's pid. A concurrent sync refuses here — before the
    recovery, the sweep, or any staging — naming the live pid, so the advice
    can never be to delete another running sync's staging. A lock whose owner
    is gone (a crashed sync) is reclaimed; the residual is pid reuse: a new
    process holding a dead sync's pid makes the lock look live, and the
    refusal names the lock path for an operator to remove.
    """
    lock_path = sdk_root / STAGING_DIR / "lock"
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        # Something other than a directory sits where the staging root goes;
        # the sweep below would refuse it, but the lock comes first.
        raise ValueError(
            f"sync_staging_blocked: {lock_path.parent} is not a directory; "
            "remove it and run the sync again"
        ) from None
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        alive = False
        pid: int | None = None
        try:
            holder = lock_path.read_text(encoding="utf-8").split()
            pid = int(holder[0])
            try:
                os.kill(pid, 0)
            except PermissionError:
                alive = True  # exists but is not ours to signal
            except OSError:
                alive = False  # the owner is gone
            else:
                alive = True
        except (OSError, ValueError, IndexError):
            # An empty or unreadable lock is crash debris between create and write.
            pid = None
        if alive:
            raise ValueError(
                f"sync_staging_blocked: another sync (pid {pid}) is running in "
                f"{sdk_root}; let it finish and run the sync again"
            ) from None
        lock_path.unlink(missing_ok=True)
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise ValueError(
                f"sync_staging_blocked: {lock_path} is held by another sync; "
                "let it finish and run the sync again"
            ) from None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()} {int(time.time())}\n")
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)
        # Leave no staging root behind on a clean exit; if a parked tree or
        # debris survives (a failed sync), the occupied directory stays.
        with contextlib.suppress(OSError):
            lock_path.parent.rmdir()


def _write_vendored(
    sdk_root: Path,
    document: dict[str, Any],
    payloads: dict[str, dict[str, bytes]],
    recomputed: dict[str, dict[str, str]],
) -> None:
    """Rewrite the vendored tree and lock; vendored bytes match the bundle exactly.

    The new tree is staged outside the package (``_staging_paths``) and
    swapped in at the end, so an interrupted sync can never leave a
    half-empty vendored tree behind (the old ``rmtree``-then-write order
    destroyed the tree first) and never leaves staging debris where
    packaging could pick it up. A crash between the swap's two renames
    leaves the old tree parked and the vendored path absent, which
    ``--check`` reports as missing files; the next sync puts the parked tree
    back before it stages anything, so a second failure cannot cost the last
    good copy, and only then sweeps the leftovers (``_clear_staging``). Once
    the swap has happened, failing to delete the parked old tree must not stop
    the lock being written, so that deletion is best-effort and the next sync
    sweeps what is left.

    The lock is written only after the swap and records the digests
    recomputed from the bundle's bytes, never the manifest's claims (STD-2).
    A failure between swap and lock is ``--check`` drift whenever the bundle's
    bytes moved. When only a version or a status moved, the bytes still match
    the old lock, so the committed-state check and the build hook stay green
    while the stamps run ahead of the lock; a bundle-mode ``--check`` sees it,
    and the next sync rewrites both.
    """
    tree = sdk_root / VENDORED
    staging, retired = _staging_paths(sdk_root)
    if retired.exists() and not tree.exists():
        # A sync that died between the swap's two renames left the last good
        # tree parked and the vendored path absent. It is the only copy, and
        # the staging below can still fail, so it goes back first.
        retired.rename(tree)
    _clear_staging(staging, retired)
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
            digests = recomputed[standard["id"]]
            stamps: list[str] = []
            rows: list[dict[str, str]] = []
            for file in standard["files"]:
                raw = payloads[standard["id"]][file["path"]]
                target = staging / file["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                stamps.append(
                    STAMP_LINE.format(
                        path=file["path"], identifier=standard["id"], version=standard["version"]
                    )
                )
                rows.append({"path": file["path"], "sha256": digests[file["path"]]})
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
            tree.rename(retired)
            try:
                staging.rename(tree)
            except BaseException:
                # The old tree was already moved aside; put it back so a
                # failed swap leaves the previous state in place, not a
                # missing vendored tree.
                retired.rename(tree)
                raise
            # The swap is done. A parked tree that will not delete (a read-only
            # file, a handle an indexer holds) must not stop the lock below
            # being written; the next sync sweeps it.
            shutil.rmtree(retired, ignore_errors=True)
        else:
            tree.parent.mkdir(parents=True, exist_ok=True)
            staging.rename(tree)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        # Empty after a completed swap or a cleaned-up failure; a parked tree
        # from a crash between the two renames keeps it, deliberately.
        with contextlib.suppress(OSError):
            staging.parent.rmdir()
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
