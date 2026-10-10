"""Issue #440 — the stdio MCP shim: the design record's §6 arm bank.

Arms SH0-SH9 (+ AM1/AM2 in test_cli.py), the four RED controls
(discovery bypass / authorization unwired / fork guard removed / marker
unwired), one module-scoped started host. Typed outcomes per §6; counts
read from junitxml attributes, never a filtered summary line.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from benchweave_sdk_server import library

REPO = Path(__file__).resolve().parents[2]


# --- library.read_lock (the fork guard's reader) -----------------------------


class TestReadLock:
    """``library.read_lock``: parse + probe, never a steal (the design's
    fork-guard reader). Conservative rule inherited from the lock writer:
    an unprovable lock is treated as live."""

    def test_live_pid_is_live(self, tmp_path: Path) -> None:
        lock = tmp_path / "library.lock"
        lock.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
        read = library.read_lock(tmp_path)
        assert read is not None
        assert read.pid == os.getpid()
        assert read.live is True

    def test_provably_dead_pid_is_not_live(self, tmp_path: Path) -> None:
        dead = subprocess.Popen(
            [sys.executable, "-c", "pass"], stdout=subprocess.DEVNULL
        )
        dead.wait(timeout=10)
        lock = tmp_path / "library.lock"
        lock.write_text(json.dumps({"pid": dead.pid}), encoding="utf-8")
        read = library.read_lock(tmp_path)
        assert read is not None
        assert read.pid == dead.pid
        assert read.live is False

    def test_absent_lock_is_none(self, tmp_path: Path) -> None:
        assert library.read_lock(tmp_path) is None

    def test_unparseable_lock_is_live_conservative(self, tmp_path: Path) -> None:
        lock = tmp_path / "library.lock"
        lock.write_text("not json at all", encoding="utf-8")
        read = library.read_lock(tmp_path)
        assert read is not None
        assert read.pid is None
        assert read.live is True

    def test_non_integer_pid_is_live_conservative(self, tmp_path: Path) -> None:
        lock = tmp_path / "library.lock"
        lock.write_text(json.dumps({"pid": "12x"}), encoding="utf-8")
        read = library.read_lock(tmp_path)
        assert read is not None
        assert read.pid is None
        assert read.live is True
