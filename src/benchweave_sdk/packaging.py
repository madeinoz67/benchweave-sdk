"""Deterministic file inventory helpers; no publication or dependency installation."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any


def _file(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or relative.is_absolute()
        or any(part in (".", "..") for part in name.split("/"))
        or any(not part for part in name.split("/"))
    ):
        raise ValueError("Unsafe inventory path")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink inventory path")
    if not current.is_file() or not current.resolve().is_relative_to(root.resolve()):
        raise ValueError("Inventory path is not a contained regular file")
    return current


def inventory(root: Path) -> list[dict[str, Any]]:
    """Inventory a prepared bundle. The caller assigns registry file roles."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Expected a real bundle directory")
    result = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlink inventory path")
        if path.is_file():
            name = path.relative_to(root).as_posix()
            raw = _file(root, name).read_bytes()
            result.append(
                {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            )
    return result


def verify_inventory(root: Path, expected: list[dict[str, Any]]) -> None:
    """Reject missing, duplicate, altered, escaped and unlisted bundle files."""
    seen = set()
    for entry in expected:
        name = entry["path"]
        if name in seen:
            raise ValueError("Duplicate inventory path")
        seen.add(name)
        raw = _file(root, name).read_bytes()
        if len(raw) != entry["bytes"]:
            raise ValueError(f"File size mismatch: {name}")
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError(f"File hash mismatch: {name}")
    if seen != {entry["path"] for entry in inventory(root)}:
        raise ValueError("Unlisted inventory path")
