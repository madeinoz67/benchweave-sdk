"""Verify the vendored standards tree against its lock before packaging."""

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

LOCK_NAME = "standards-lock.json"
VENDORED = "src/benchweave_sdk/standards"
STAMP_NAME = "_GENERATED.txt"


def _validate_preview_assets(package: Path) -> None:
    root = package / "preview_assets"
    inventory_path = root / "inventory.json"
    if not inventory_path.is_file():
        raise RuntimeError("Bundled preview inventory missing; run npm run build:preview from ui/")
    try:
        inventory = json.loads(inventory_path.read_bytes())
        assets = inventory["assets"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("Bundled preview inventory is invalid") from exc
    if inventory.get("api_version") != 1 or not isinstance(assets, list) or not assets:
        raise RuntimeError("Bundled preview inventory is incompatible or empty")
    for asset in assets:
        relative = Path(asset["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Unsafe preview asset path: {relative}")
        content = (root / relative).read_bytes()
        if len(content) != asset["size"] or hashlib.sha256(content).hexdigest() != asset["sha256"]:
            raise RuntimeError(f"Bundled preview asset is stale or corrupt: {relative}")


def _unsafe_row(identifier: object, relative: object) -> bool:
    """The sync lanes' string rule for ids and ``<id>/...`` rows, inline.

    Inlined because the build hook must stay importable without the package
    installed; standards_sync._identifier_problem/_path_problem are the
    reference (STD-3: every lane refuses the same rows).
    """
    if _unsafe_identifier(identifier) or not isinstance(relative, str):
        return True
    segments = relative.split("/")
    return (
        len(segments) < 2
        or "\\" in relative
        or ":" in relative
        or any(_unsafe_segment(segment) for segment in segments)
        or segments[0] != identifier
        or (len(segments) == 2 and segments[1].casefold() == STAMP_NAME.casefold())
    )


def _unsafe_identifier(identifier: object) -> bool:
    """A standard id names one directory directly under the tree, nothing else."""
    if not isinstance(identifier, str):
        return True
    return any(c in identifier for c in "/\\:") or _unsafe_segment(identifier)


# Names Windows resolves to a device whatever directory they appear in, with or
# without an extension (NUL, con.txt, COM1.json); the superscript digit forms
# (com¹, lpt²) and the console API names (conin$, conout$) resolve as devices
# too. Kept identical to standards_sync._WINDOWS_DEVICE (STD-3).
_WINDOWS_DEVICE = re.compile(
    r"(?i)(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³]|conin\$|conout\$)(\..*)?"
)


def _unsafe_segment(segment: str) -> bool:
    return (
        not segment
        or segment in (".", "..")
        or segment != segment.rstrip(". ")
        or _WINDOWS_DEVICE.fullmatch(segment) is not None
    )


def _verify_vendored_file(tree: Path, identifier: str, relative: str, digest: str) -> None:
    if _unsafe_row(identifier, relative):
        raise RuntimeError(f"Unsafe vendored standards path: {relative}")
    target = tree / relative
    if not target.is_file():
        raise RuntimeError(f"Vendored standards file missing: {relative}")
    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise RuntimeError(f"Vendored standards file is stale or corrupt: {relative}")


def _validate_vendored_standards(root: Path) -> None:
    tree = root / VENDORED
    lock_path = root / LOCK_NAME
    if not tree.is_dir() or not lock_path.is_file():
        raise RuntimeError(
            "Vendored standards tree or lock missing; "
            "run benchweave-sdk sync-standards <bundle> from packages/sdk"
        )
    try:
        lock = json.loads(lock_path.read_bytes())
        standards = lock["standards"]
        if lock.get("lock_version") != 1 or not isinstance(standards, list) or not standards:
            raise RuntimeError("Bundled standards lock is incompatible or empty")
        recorded: set[str] = set()
        stamps: set[str] = set()
        for standard in standards:
            identifier = standard["id"]
            if _unsafe_identifier(identifier):
                raise RuntimeError(f"Unsafe vendored standard id: {identifier!r}")
            if not (tree / identifier / STAMP_NAME).is_file():
                raise RuntimeError(f"Vendored standard stamp missing: {identifier}/{STAMP_NAME}")
            stamps.add(f"{identifier}/{STAMP_NAME}")
            for file in standard["files"]:
                _verify_vendored_file(tree, identifier, file["path"], file["sha256"])
                recorded.add(file["path"])
        # #9: the build-time extras sweep — same rule as every sync lane
        # (lock ∪ stamps ∪ __pycache__; inlined here because the build hook
        # must stay importable without the package installed). A stray file
        # must not ship in a wheel built outside the gated paths.
        present: set[str] = set()
        for entry in tree.rglob("*"):
            relative = entry.relative_to(tree)
            if entry.is_symlink() or entry.is_junction():
                # Same rule as the sync lanes: rglob does not descend a linked
                # directory, but the wheel builder follows it and ships it.
                raise RuntimeError(f"unexpected_vendored_file: {relative.as_posix()} is a link")
            if entry.is_file() and "__pycache__" not in relative.parts:
                present.add(relative.as_posix())
        for path in sorted(present - recorded - stamps):
            raise RuntimeError(f"unexpected_vendored_file: {path}")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("Bundled standards lock is invalid") from exc


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        package = root / "src/benchweave_sdk"
        _validate_preview_assets(package)
        _validate_vendored_standards(root)
        _drop_vcs_exclusion_force_include(build_data)


def _drop_vcs_exclusion_force_include(build_data: dict[str, Any]) -> None:
    """Stop the sdist builder vendoring VCS exclusion files past the list.

    hatchling's SdistBuilder force-includes VCS exclusion files via
    build_data (get_build_data: every .gitignore/.hgignore found at the
    project root is added with its basename as the target), and
    force-include bypasses include/exclude entirely — an explicit exclude
    provably cannot stop it, and ignore-vcs only gates the exclude side.
    The declared five-entry sdist include list is this project's packaging
    contract, and selection here is include-based, so the vendored ignore
    file carries no rebuild hygiene either: dropping it changes nothing but
    the leak. Wheels force-include nothing of the kind; the pop is a no-op
    for them. The repo is git-only today, so the .hgignore arm is
    behavior-neutral (verified: identical sdist listing before/after).
    """
    exclusion_names = {".gitignore", ".hgignore"}
    force_include = build_data.get("force_include") or {}
    for source in [
        key
        for key, target in force_include.items()
        if target in exclusion_names and os.path.basename(key) in exclusion_names
    ]:
        force_include.pop(source)
