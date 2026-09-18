"""Regression tests for the bounded, symlink-refusing file reader.

The public ``read_file`` dispatches per platform, so CI on one OS never
executes the other branch through it alone; the ``_read_file_no_dirfd``
tests below therefore call the Windows branch directly — it is plain
``lstat``/``open`` and runs everywhere.
"""

from __future__ import annotations

import errno
import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk import presentation
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


# --- POSIX branch: refusal by inspection; errno is only the backstop --------

_POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="POSIX dir_fd walk only")

_OpenLike = Callable[[str, int, int, int | None], int]


class _KernelLikeOS:
    """``os`` with one ``open`` behaviour swapped in; everything else passes through.

    Lets a test stand in for a kernel whose ``O_NOFOLLOW`` open reports a
    different errno than the one this CI runner has, without patching the
    real ``os`` module for the rest of the process.
    """

    def __init__(self, open_override: _OpenLike) -> None:
        self._open = open_override

    def __getattr__(self, name: str) -> Any:
        return getattr(os, name)

    def open(self, path: str, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        return self._open(path, flags, mode, dir_fd)


@_POSIX_ONLY
def test_posix_symlinked_directory_is_refused_by_inspection_not_errno(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Linux 6.x and Darwin report ENOTDIR, not ELOOP, for a symlink opened O_NOFOLLOW|O_DIRECTORY.

    The directory check runs before the symlink check on both, so an errno
    mapping keyed on ELOOP misclassified a symlinked directory as a
    "bounded regular file" — the wrong reason, and invisible to a suite
    that had only ever executed on Windows. The refusal therefore has to
    come from the per-component lstat, with the errno mapping only a
    backstop; this stand-in kernel makes the property explicit whatever
    kernel the runner has.
    """
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "document.json").write_bytes(b"{}")
    link_dir = tmp_path / "alias"
    _symlink_or_skip(link_dir, real_dir, directory=True)

    def notdir_open(path: str, flags: int, mode: int, dir_fd: int | None) -> int:
        if flags & os.O_NOFOLLOW and flags & os.O_DIRECTORY:
            details = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
            if stat.S_ISLNK(details.st_mode):
                raise OSError(errno.ENOTDIR, "Not a directory")
        return os.open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(presentation, "os", _KernelLikeOS(notdir_open))
    with pytest.raises(ValueError, match="symlinked components"):
        read_file(link_dir / "document.json")


@_POSIX_ONLY
@pytest.mark.parametrize(
    ("code", "message"),
    [
        pytest.param(errno.ELOOP, "symlinked components", id="ELOOP-linux-darwin"),
        pytest.param(errno.EMLINK, "symlinked components", id="EMLINK-freebsd"),
        pytest.param(errno.ENOTDIR, "bounded regular file", id="ENOTDIR"),
        pytest.param(errno.EISDIR, "bounded regular file", id="EISDIR"),
    ],
)
def test_posix_open_errno_backstop_maps_shape_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, message: str
) -> None:
    """A component swapped after its lstat still surfaces as the shape refusal, per kernel."""
    target = tmp_path / "document.json"
    target.write_bytes(b"{}")

    def failing_open(path: str, flags: int, mode: int, dir_fd: int | None) -> int:
        if flags & os.O_NOFOLLOW:
            raise OSError(code, os.strerror(code))
        return os.open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(presentation, "os", _KernelLikeOS(failing_open))
    with pytest.raises(ValueError, match=message):
        read_file(target)


@_POSIX_ONLY
def test_posix_environment_errors_keep_their_oserror_face(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "document.json"
    target.write_bytes(b"{}")

    def denied_open(path: str, flags: int, mode: int, dir_fd: int | None) -> int:
        if flags & os.O_NOFOLLOW:
            raise OSError(errno.EACCES, os.strerror(errno.EACCES))
        return os.open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(presentation, "os", _KernelLikeOS(denied_open))
    with pytest.raises(PermissionError):
        read_file(target)


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
