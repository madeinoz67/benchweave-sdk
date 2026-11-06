"""Deterministic file inventory and plugin-package discovery helpers; no
publication or dependency installation."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any


def _package_dir(project: Path, *, refusal: str) -> Path:
    """The single package directory under ``<project>/src`` — derive-ui's own
    discovery, minted as a helper when regen-fixtures became its second user
    (issue #463 row 8) and shared with the classref gate since the wheel
    install made the pick load-bearing. A real wheel install (``uv pip
    install --target``) leaves the package tree beside its
    ``<name>-<version>.dist-info`` metadata directory, so those, ``.egg-info``
    and ``__pycache__`` are never the package, and the candidates are read in
    sorted order — the pick must not depend on the filesystem's ``iterdir``
    order. The refusal prefix is the CALLER's (STD-4: each command refuses in
    its own voice). The ``is_dir`` guard covers the missing-src/ half of the
    input space too: ``iterdir`` on an absent directory is a raw errno, and
    the named refusal is the better message."""
    src = project / "src"
    package_dir = (
        next(
            (
                path
                for path in sorted(src.iterdir())
                if path.is_dir()
                and path.name != "__pycache__"
                and not path.name.endswith((".dist-info", ".egg-info"))
            ),
            None,
        )
        if src.is_dir()
        else None
    )
    if package_dir is None:
        raise ValueError(f"{refusal}: no package under {project / 'src'}")
    return package_dir


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
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Expected a real bundle directory")
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
    # A hash-free walk detects unlisted files: every listed file was already
    # read and digested above, and re-running inventory() here used to read
    # and hash the entire bundle a second time for no additional assurance.
    present = set()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlink inventory path")
        if path.is_file():
            present.add(path.relative_to(root).as_posix())
    if seen != present:
        raise ValueError("Unlisted inventory path")
