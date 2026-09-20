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
from types import SimpleNamespace
from typing import Any

import pytest

from benchweave_sdk import presentation
from benchweave_sdk.presentation import _read_file_no_dirfd, read_file

# A regular file blocking a directory position is not a symlink refusal, so
# both walks leave the platform's own error alone: POSIX reports ENOTDIR,
# Windows reports the whole path as not-found at lstat (winerror 3).
_BLOCKED_COMPONENT_ERROR: type[OSError] = (
    FileNotFoundError if sys.platform == "win32" else NotADirectoryError
)

_SYMLINK_REFUSAL = "^path_symlink_component: "


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
    # Same class on every platform: the POSIX walk's own error, named on Windows.
    with pytest.raises(IsADirectoryError):
        read_file(tmp_path)


def test_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        read_file(tmp_path / "absent.json")


def test_rejects_symlinked_final_component(tmp_path: Path) -> None:
    target = tmp_path / "real.json"
    target.write_bytes(b"{}")
    link = tmp_path / "link.json"
    _symlink_or_skip(link, target)
    with pytest.raises(ValueError, match=_SYMLINK_REFUSAL):
        read_file(link)


def test_rejects_symlinked_directory_component(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    target = real_dir / "document.json"
    target.write_bytes(b"{}")
    link_dir = tmp_path / "alias"
    _symlink_or_skip(link_dir, real_dir, directory=True)
    with pytest.raises(ValueError, match=_SYMLINK_REFUSAL):
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


# --- POSIX walk: main's _open_no_follow decides; pinned against a stand-in kernel ---

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
@pytest.mark.parametrize(
    "code",
    [
        pytest.param(errno.ENOTDIR, id="ENOTDIR-linux6-darwin-with-O_DIRECTORY"),
        pytest.param(errno.ELOOP, id="ELOOP-plain-O_NOFOLLOW"),
    ],
)
def test_posix_symlinked_directory_is_named_whatever_errno_the_kernel_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    """Linux 6.x and Darwin report ENOTDIR, not ELOOP, for a symlinked directory component.

    The directory check runs before the symlink check on both (measured on
    Linux 6.6), so the refusal cannot be keyed on one errno. This stand-in
    kernel makes the property explicit whatever kernel the runner has: a
    symlinked directory component is ``path_symlink_component:`` under
    either errno.
    """
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "document.json").write_bytes(b"{}")
    link_dir = tmp_path / "alias"
    _symlink_or_skip(link_dir, real_dir, directory=True)

    def kernel_open(path: str, flags: int, mode: int, dir_fd: int | None) -> int:
        if flags & os.O_NOFOLLOW and flags & os.O_DIRECTORY:
            details = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
            if stat.S_ISLNK(details.st_mode):
                raise OSError(code, os.strerror(code))
        return os.open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(presentation, "os", _KernelLikeOS(kernel_open))
    with pytest.raises(ValueError, match=_SYMLINK_REFUSAL):
        read_file(link_dir / "document.json")


@_POSIX_ONLY
@pytest.mark.parametrize(
    "code",
    [
        pytest.param(errno.ENOTDIR, id="ENOTDIR"),
        pytest.param(errno.ELOOP, id="ELOOP"),
        pytest.param(errno.EACCES, id="EACCES"),
    ],
)
def test_posix_open_errors_on_a_real_component_keep_their_oserror_face(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    """Only a confirmed symlink becomes the typed refusal; anything else re-raises unchanged."""
    target = tmp_path / "document.json"
    target.write_bytes(b"{}")

    def failing_open(path: str, flags: int, mode: int, dir_fd: int | None) -> int:
        if flags & os.O_NOFOLLOW:
            raise OSError(code, os.strerror(code))
        return os.open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(presentation, "os", _KernelLikeOS(failing_open))
    with pytest.raises(OSError) as raised:
        read_file(target)
    assert raised.value.errno == code
    assert not isinstance(raised.value, ValueError)


# --- _redirects_name: which lstat results redirect the path ---------------------

_SYMLINK_TAG = 0xA000000C
_JUNCTION_TAG = 0xA0000003
_WSL_SYMLINK_TAG = 0xA000001D
_CLOUD_FILE_TAG = 0x9000001A
_APP_EXEC_LINK_TAG = 0x8000001B
_REPARSE_ATTRIBUTE = 0x400


def _lstat_like(mode: int, attributes: int = 0, tag: int = 0) -> Any:
    return SimpleNamespace(st_mode=mode, st_file_attributes=attributes, st_reparse_tag=tag)


@pytest.mark.parametrize(
    ("details", "redirects"),
    [
        pytest.param(_lstat_like(stat.S_IFREG), False, id="plain-file"),
        pytest.param(_lstat_like(stat.S_IFDIR), False, id="plain-directory"),
        pytest.param(_lstat_like(stat.S_IFLNK), True, id="posix-symlink"),
        pytest.param(
            _lstat_like(stat.S_IFLNK, _REPARSE_ATTRIBUTE, _SYMLINK_TAG), True, id="windows-symlink"
        ),
        pytest.param(
            _lstat_like(stat.S_IFDIR, _REPARSE_ATTRIBUTE, _JUNCTION_TAG), True, id="junction"
        ),
        pytest.param(
            _lstat_like(stat.S_IFREG, _REPARSE_ATTRIBUTE, _WSL_SYMLINK_TAG), True, id="wsl-symlink"
        ),
        pytest.param(
            _lstat_like(stat.S_IFREG, _REPARSE_ATTRIBUTE, _CLOUD_FILE_TAG),
            False,
            id="cloud-file-placeholder",
        ),
        pytest.param(
            _lstat_like(stat.S_IFREG, _REPARSE_ATTRIBUTE, _APP_EXEC_LINK_TAG),
            False,
            id="app-execution-alias",
        ),
        pytest.param(
            _lstat_like(stat.S_IFREG, 0, _JUNCTION_TAG), False, id="tag-without-attribute"
        ),
    ],
)
def test_only_name_surrogates_redirect_the_path(details: Any, redirects: bool) -> None:
    """A reparse point that is not a name surrogate is an ordinary file.

    Refusing every reparse point refused every document in a OneDrive-backed
    checkout; ``os.lstat`` itself reports those as regular files.
    """
    assert presentation._redirects_name(details) is redirects


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows reparse point")
def test_windows_junction_component_is_refused(tmp_path: Path) -> None:
    """A junction needs no privilege to create, so the Windows lane always executes this."""
    import _winapi

    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "document.json").write_bytes(b"{}")
    junction = tmp_path / "junction"
    _winapi.CreateJunction(str(real_dir), str(junction))
    with pytest.raises(ValueError, match=_SYMLINK_REFUSAL):
        read_file(junction / "document.json")
    with pytest.raises(ValueError, match=_SYMLINK_REFUSAL):
        _read_file_no_dirfd(junction / "document.json", 64)


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
    with pytest.raises(IsADirectoryError):
        _read_file_no_dirfd(tmp_path, 64)


def test_no_dirfd_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        _read_file_no_dirfd(tmp_path / "absent.json", 64)


def test_no_dirfd_rejects_symlinked_final_component(tmp_path: Path) -> None:
    target = tmp_path / "real.json"
    target.write_bytes(b"{}")
    link = tmp_path / "link.json"
    _symlink_or_skip(link, target)
    with pytest.raises(ValueError, match=_SYMLINK_REFUSAL):
        _read_file_no_dirfd(link, 64)


def test_no_dirfd_rejects_symlinked_directory_component(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "document.json").write_bytes(b"{}")
    link_dir = tmp_path / "alias"
    _symlink_or_skip(link_dir, real_dir, directory=True)
    with pytest.raises(ValueError, match=_SYMLINK_REFUSAL):
        _read_file_no_dirfd(link_dir / "document.json", 64)


def test_no_dirfd_rejects_file_as_directory_component(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_bytes(b"x")
    with pytest.raises(_BLOCKED_COMPONENT_ERROR):
        _read_file_no_dirfd(blocker / "document.json", 64)
