"""Verify the vendored standards tree against its lock before packaging."""

import hashlib
import json
import os
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


def _verify_vendored_file(tree: Path, relative: str, digest: str) -> None:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"Unsafe vendored standards path: {relative}")
    target = tree / path
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
            if not (tree / identifier / STAMP_NAME).is_file():
                raise RuntimeError(f"Vendored standard stamp missing: {identifier}/{STAMP_NAME}")
            stamps.add(f"{identifier}/{STAMP_NAME}")
            for file in standard["files"]:
                _verify_vendored_file(tree, file["path"], file["sha256"])
                recorded.add(file["path"])
        # #9: the build-time extras sweep — same rule as every sync lane
        # (lock ∪ stamps ∪ __pycache__; inlined here because the build hook
        # must stay importable without the package installed). A stray file
        # must not ship in a wheel built outside the gated paths.
        present = {
            path.relative_to(tree).as_posix()
            for path in tree.rglob("*")
            if path.is_file() and "__pycache__" not in path.relative_to(tree).parts
        }
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
    """Stop the sdist builder vendoring .gitignore past the include list.

    Hatchling's SdistBuilder force-includes VCS exclusion files via
    build_data (get_build_data: every .gitignore found at the project root
    is added with its basename as the target), and force-include bypasses
    include/exclude entirely — an explicit exclude provably cannot stop it,
    and ignore-vcs only gates the exclude side. The declared five-entry
    sdist include list is this project's packaging contract, and selection
    here is include-based, so the vendored ignore file carries no rebuild
    hygiene either: dropping it changes nothing but the leak. Wheels force
    include nothing of the kind; the pop is a no-op for them.
    """
    force_include = build_data.get("force_include") or {}
    for source in [
        key
        for key, target in force_include.items()
        if target == ".gitignore" and os.path.basename(key) == ".gitignore"
    ]:
        force_include.pop(source)
