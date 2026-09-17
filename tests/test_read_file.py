"""Regression tests for the bounded, symlink-refusing file reader."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from benchweave_sdk.presentation import read_file


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
    with pytest.raises((ValueError, OSError)):
        read_file(tmp_path)


def test_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        read_file(tmp_path / "absent.json")


def test_rejects_symlinked_final_component(tmp_path: Path) -> None:
    target = tmp_path / "real.json"
    target.write_bytes(b"{}")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable (privilege or filesystem)")
    with pytest.raises((ValueError, OSError)):
        read_file(link)


def test_rejects_symlinked_directory_component(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    target = real_dir / "document.json"
    target.write_bytes(b"{}")
    link_dir = tmp_path / "alias"
    try:
        link_dir.symlink_to(real_dir, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable (privilege or filesystem)")
    with pytest.raises((ValueError, OSError)):
        read_file(link_dir / "document.json")


def test_exact_limit_is_accepted(tmp_path: Path) -> None:
    target = tmp_path / "exact.bin"
    payload = os.urandom(32)
    target.write_bytes(payload)
    assert read_file(target, limit=32) == payload
