"""Regression tests for the bounded, symlink-refusing file reader.

The public ``read_file`` dispatches per platform, so CI on one OS never
executes the other branch through it alone; the ``_read_file_no_dirfd``
tests below therefore call the Windows branch directly — it is plain
``lstat``/``open`` and runs everywhere.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from benchweave_sdk.presentation import _read_file_no_dirfd, read_file

# A regular file blocking a directory position: POSIX reports ENOTDIR, which
# read_file maps to its domain refusal; Windows reports the whole path as
# not-found at lstat (winerror 3), a faithful environment error kept as-is.
_BLOCKED_COMPONENT_ERROR: tuple[type[Exception], ...] = (
    (FileNotFoundError,) if sys.platform == "win32" else (ValueError,)
)


def _symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError:
        pytest.skip("symlinks unavailable (privilege or filesystem)")


def test_reads_regular_file_within_limit(tmp_path: Path) -> None:
    target = tmp_path / "document.json"
    target.write_bytes(b"{}")
    assert read_file(target) == b"{}"


def test_rejects_file_over_limit(tmp_path: Path) -> None:
    target = tmp_path / "large.bin"
    target.write_bytes(b"x" * 64)
    with pytest.raises(ValueError, match="bounded regular file"):
        read_file(target, limit=63)


def test_rejects_negative_limit(tmp_path: Path) -> None:
    target = tmp_path / "document.json"
    target.write_bytes(b"{}")
    with pytest.raises(ValueError, match="byte limit"):
        read_file(target, limit=-1)


def test_rejects_directory(tmp_path: Path) -> None:
    # Refusal class is aligned across platforms: always ValueError.
    with pytest.raises(ValueError, match="bounded regular file"):
        read_file(tmp_path)


def test_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        read_file(tmp_path / "absent.json")


def test_rejects_symlinked_final_component(tmp_path: Path) -> None:
    target = tmp_path / "real.json"
    target.write_bytes(b"{}")
    link = tmp_path / "link.json"
    _symlink_or_skip(link, target)
    with pytest.raises(ValueError, match="symlinked components"):
        read_file(link)


def test_rejects_symlinked_directory_component(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    target = real_dir / "document.json"
    target.write_bytes(b"{}")
    link_dir = tmp_path / "alias"
    _symlink_or_skip(link_dir, real_dir, directory=True)
    with pytest.raises(ValueError, match="symlinked components"):
        read_file(link_dir / "document.json")


def test_rejects_file_as_directory_component(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_bytes(b"x")
    with pytest.raises(_BLOCKED_COMPONENT_ERROR):
        read_file(blocker / "document.json")


def test_exact_limit_is_accepted(tmp_path: Path) -> None:
    target = tmp_path / "exact.bin"
    payload = os.urandom(32)
    target.write_bytes(payload)
    assert read_file(target, limit=32) == payload


# --- direct coverage of the Windows branch (runs on every platform) --------


def test_no_dirfd_reads_within_limit(tmp_path: Path) -> None:
    target = tmp_path / "document.json"
    payload = os.urandom(48)
    target.write_bytes(payload)
    assert _read_file_no_dirfd(target, 48) == payload


def test_no_dirfd_rejects_file_over_limit(tmp_path: Path) -> None:
    target = tmp_path / "large.bin"
    target.write_bytes(b"x" * 64)
    with pytest.raises(ValueError, match="bounded regular file"):
        _read_file_no_dirfd(target, 63)


def test_no_dirfd_rejects_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="bounded regular file"):
        _read_file_no_dirfd(tmp_path, 64)


def test_no_dirfd_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        _read_file_no_dirfd(tmp_path / "absent.json", 64)


def test_no_dirfd_rejects_symlinked_final_component(tmp_path: Path) -> None:
    target = tmp_path / "real.json"
    target.write_bytes(b"{}")
    link = tmp_path / "link.json"
    _symlink_or_skip(link, target)
    with pytest.raises(ValueError, match="symlinked components"):
        _read_file_no_dirfd(link, 64)


def test_no_dirfd_rejects_symlinked_directory_component(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "document.json").write_bytes(b"{}")
    link_dir = tmp_path / "alias"
    _symlink_or_skip(link_dir, real_dir, directory=True)
    with pytest.raises(ValueError, match="symlinked components"):
        _read_file_no_dirfd(link_dir / "document.json", 64)


def test_no_dirfd_rejects_file_as_directory_component(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_bytes(b"x")
    with pytest.raises(_BLOCKED_COMPONENT_ERROR):
        _read_file_no_dirfd(blocker / "document.json", 64)
