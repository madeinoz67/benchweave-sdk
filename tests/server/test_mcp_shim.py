"""Issue #440 — the stdio MCP shim: the design record's §6 arm bank.

Arms SH0-SH9 (+ AM1/AM2 in test_cli.py), the four RED controls
(discovery bypass / authorization unwired / fork guard removed / marker
unwired), one module-scoped started host. Typed outcomes per §6; counts
read from junitxml attributes, never a filtered summary line.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from benchweave_sdk_server import library, lifecycle

REPO = Path(__file__).resolve().parents[2]

#: The real-subprocess started-host arms ride the POSIX lane: the windows
#: `start` path currently cannot reach readiness with an empty daemon log
#: (issue #432), and the S1 harness these arms reuse is POSIX-first for
#: the same reason. The Windows CI leg corroborates per the W1 doctrine.
POSIX_HOST = pytest.mark.skipif(
    sys.platform == "win32",
    reason="the started-host arms reuse the S1 subprocess harness (POSIX "
    "first; issue #432 tracks the windows start gap) — the Windows CI leg "
    "is the Windows evidence per the W1 doctrine",
)

requires_posix_file_perms = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Path.chmod cannot stage the permission provocation on Windows "
    "(mode bits do not reach the ACL); the refusal path itself is pinned "
    "by the payload-shape arms below",
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _dead_child() -> int:
    """A provably dead pid (an exited-later child), the arm-safe way."""
    child = subprocess.Popen([sys.executable, "-c", "pass"],
                             stdout=subprocess.DEVNULL)
    child.wait(timeout=10)
    return int(child.pid)


def _stage_ours_pidfile(bindings: Path, pid: int) -> None:
    """A pidfile whose recorded start ticks are the pid's REAL ones, so
    the twin lattice verifies ``ours`` while the process lives."""
    lifecycle.pid_path(bindings).write_text(
        json.dumps(
            {
                "pid": pid,
                "server": "benchweave-sdk-server",
                "bindings": str(bindings),
                "started_wall": "2026-10-10T00:00:00Z",
                "started_ticks": lifecycle.process_start_ticks(pid),
                "log_destination": "stderr",
                "schema": 1,
            }
        ),
        encoding="utf-8",
    )


def _stage_tokens(
    bindings: Path,
    *,
    bearer: str = "shim-arm-bearer-not-real",
    url: str = "http://127.0.0.1:59001",
    pid: int,
) -> str:
    path = lifecycle.tokens_path(bindings)
    path.write_text(
        json.dumps(
            {
                "pid": pid,
                "bearer_token": bearer,
                "url": url,
                "written_wall": "2026-10-10T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return bearer


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


# --- shim.discover: the family lattice (§2.2) --------------------------------


class TestDiscover:
    """The four-way lattice, every outcome typed. Unit-shaped: staged
    families, no host process needed except where a LIVE pid is the
    subject."""

    def test_ours_with_usable_tokens_proxies(self, tmp_path: Path) -> None:
        from benchweave_sdk_server.shim import ProxyTarget, discover

        bindings = tmp_path / "device-bindings.json"
        _stage_ours_pidfile(bindings, os.getpid())
        _stage_tokens(bindings, pid=os.getpid())
        verdict = discover(bindings)
        assert isinstance(verdict, ProxyTarget)
        assert verdict.pid == os.getpid()
        assert verdict.url == "http://127.0.0.1:59001"
        assert verdict.bearer  # the payload's credential rides the target

    def test_absent_family_falls_back(self, tmp_path: Path) -> None:
        from benchweave_sdk_server.shim import NoHost, discover

        verdict = discover(tmp_path / "device-bindings.json")
        assert verdict == NoHost(reason="absent")

    def test_dead_pid_falls_back_naming_the_reason(self, tmp_path: Path) -> None:
        from benchweave_sdk_server.shim import NoHost, discover

        bindings = tmp_path / "device-bindings.json"
        dead = _dead_child()
        _stage_ours_pidfile(bindings, dead)
        verdict = discover(bindings)
        assert verdict == NoHost(reason="dead")

    def test_not_ours_refuses_typed(self, tmp_path: Path) -> None:
        from benchweave_sdk_server.shim import Refuse, discover

        bindings = tmp_path / "device-bindings.json"
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 stdout=subprocess.DEVNULL)
        try:
            # A LIVE pid whose recorded start ticks are WRONG — the
            # recycled-pid shape, verdict not-ours.
            _stage_ours_pidfile(bindings, child.pid)
            record = json.loads(lifecycle.pid_path(bindings).read_text())
            record["started_ticks"] = int(record["started_ticks"] or 0) + 1
            lifecycle.pid_path(bindings).write_text(json.dumps(record))
            verdict = discover(bindings)
            assert isinstance(verdict, Refuse)
            assert verdict.prefix == "standalone_supervision_unknown:"
            assert "status" in verdict.action
        finally:
            child.terminate()
            child.wait(timeout=10)

    def test_unknown_identity_refuses_typed(self,
                                            tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
        from benchweave_sdk_server.shim import Refuse, discover

        bindings = tmp_path / "device-bindings.json"
        _stage_ours_pidfile(bindings, os.getpid())
        monkeypatch.setattr(lifecycle, "process_start_ticks", lambda pid: None)
        verdict = discover(bindings)
        assert isinstance(verdict, Refuse)
        assert verdict.prefix == "standalone_supervision_unknown:"

    @requires_posix_file_perms
    def test_unreadable_tokens_refuse_not_fallback(self, tmp_path: Path) -> None:
        """A live host IS the family's owner: unusable tokens are a typed
        refusal, never a beside-it fallback (the no-second-writer rule)."""
        from benchweave_sdk_server.shim import Refuse, discover

        bindings = tmp_path / "device-bindings.json"
        _stage_ours_pidfile(bindings, os.getpid())
        _stage_tokens(bindings, pid=os.getpid())
        lifecycle.tokens_path(bindings).chmod(0o000)
        verdict = discover(bindings)
        assert isinstance(verdict, Refuse)
        assert verdict.prefix == "standalone_host_unproxyable:"
        assert "stop" in verdict.action and "start" in verdict.action

    def test_tokens_pid_mismatch_refuses(self, tmp_path: Path) -> None:
        """Both sources must agree: tokens.pid ≠ pidfile.pid is the stale
        payload shape — refused, never proxied, never fallback."""
        from benchweave_sdk_server.shim import Refuse, discover

        bindings = tmp_path / "device-bindings.json"
        _stage_ours_pidfile(bindings, os.getpid())
        _stage_tokens(bindings, pid=os.getpid() + 1)
        verdict = discover(bindings)
        assert isinstance(verdict, Refuse)
        assert verdict.prefix == "standalone_host_unproxyable:"

    def test_tokens_absent_refuses(self, tmp_path: Path) -> None:
        """Ours-but-no-tokens is the S7 anomaly (readiness implies
        deliverability) — a refusal, not a race to retry."""
        from benchweave_sdk_server.shim import Refuse, discover

        bindings = tmp_path / "device-bindings.json"
        _stage_ours_pidfile(bindings, os.getpid())
        verdict = discover(bindings)
        assert isinstance(verdict, Refuse)
        assert verdict.prefix == "standalone_host_unproxyable:"


# --- shim.fork_guard: the capture-root read (§2.3) ----------------------------


class TestForkGuard:
    def test_live_holder_refuses_naming_the_pid(self, tmp_path: Path) -> None:
        from benchweave_sdk_server.shim import fork_guard

        (tmp_path / "library.lock").write_text(
            json.dumps({"pid": os.getpid()}), encoding="utf-8"
        )
        guard = fork_guard(root=tmp_path)
        assert guard is not None
        assert guard.prefix == "standalone_capture_root_held:"
        assert f"pid {os.getpid()}" in guard.detail
        assert "start" in guard.action

    def test_dead_holder_is_clean(self, tmp_path: Path) -> None:
        from benchweave_sdk_server.shim import fork_guard

        (tmp_path / "library.lock").write_text(
            json.dumps({"pid": _dead_child()}), encoding="utf-8"
        )
        assert fork_guard(root=tmp_path) is None

    def test_absent_lock_is_clean(self, tmp_path: Path) -> None:
        from benchweave_sdk_server.shim import fork_guard

        assert fork_guard(root=tmp_path) is None

    def test_unprovable_lock_refuses(self, tmp_path: Path) -> None:
        """The lock writer's conservative direction: an unparseable lock
        is treated as live — the shim refuses rather than fork beside it."""
        from benchweave_sdk_server.shim import fork_guard

        (tmp_path / "library.lock").write_text("garbage", encoding="utf-8")
        guard = fork_guard(root=tmp_path)
        assert guard is not None
        assert guard.prefix == "standalone_capture_root_held:"
        assert "unprovable" in guard.detail


# --- the mode markers (§2.5, SH9's literals) ----------------------------------


class TestMarkers:
    def test_fallback_marker_is_the_pinned_literal(self) -> None:
        from benchweave_sdk_server.shim import FALLBACK_MARKER

        assert FALLBACK_MARKER == (
            "in-process fallback host: no other surface can attach; no "
            "browser session shares this process."
        )

    def test_proxy_instructions_name_url_and_pid(self) -> None:
        from benchweave_sdk_server.shim import (
            FALLBACK_MARKER,
            ProxyTarget,
            proxy_instructions,
        )

        text = proxy_instructions(
            ProxyTarget(url="http://127.0.0.1:59001", bearer="x", pid=4242)
        )
        assert "http://127.0.0.1:59001" in text
        assert "4242" in text
        assert "share one host" in text
        assert FALLBACK_MARKER not in text


# --- the started-host arms -----------------------------------------------------


@dataclass
class HostHandle:
    bindings: Path
    port: int
    pid: int
    bearer: str
    url: str
    tokens_file: Path


@pytest.fixture(scope="module")
def started_host(starter_project: Path, tmp_path_factory: pytest.TempPathFactory):
    """One started host for the module (the S1 harness shape): mock
    transport, free port, the supervision family under a scratch root."""
    root = tmp_path_factory.mktemp("family")
    bindings = root / "device-bindings.json"
    port = _free_port()
    started = subprocess.run(
        [
            sys.executable, "-m", "benchweave_sdk_server.cli", "start",
            str(starter_project), "--bindings", str(bindings),
            "--host", "127.0.0.1", "--port", str(port),
        ],
        cwd=str(REPO), capture_output=True, text=True, timeout=120,
    )
    assert started.returncode == 0, started.stdout + started.stderr
    payload = json.loads(started.stdout)
    tokens_file = lifecycle.tokens_path(bindings)
    tokens = json.loads(tokens_file.read_text())
    handle = HostHandle(
        bindings=bindings,
        port=port,
        pid=int(payload["pid"]),
        bearer=str(tokens["bearer_token"]),
        url=str(tokens["url"]),
        tokens_file=tokens_file,
    )
    with httpx.Client(
        base_url=handle.url, timeout=5.0,
        headers={"Authorization": f"Bearer {handle.bearer}"},
    ) as client:
        deadline = time.monotonic() + 30.0
        while True:
            try:
                response = client.get("/")
                if response.status_code < 500:
                    break
            except httpx.HTTPError:
                pass
            assert time.monotonic() < deadline, "started host never served"
    yield handle
    subprocess.run(
        [sys.executable, "-m", "benchweave_sdk_server.cli", "stop",
         "--bindings", str(bindings)],
        cwd=str(REPO), capture_output=True, text=True, timeout=60,
    )


def _canon_tools(tools: object) -> str:
    """SH0's canonical form: the record's four fields, JSON-sorted. The
    wire Tool's v2 names (input_schema) — the deprecated aliases would
    warn into the output."""
    return json.dumps(
        sorted(
            json.dumps(
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.input_schema,
                    "outputSchema": t.output_schema,
                },
                sort_keys=True,
            )
            for t in tools
        ),
        sort_keys=True,
    )


class TestSH0:
    """SH0, in-process breadth (the test_mcp.py pattern): shim vs direct
    streamable-HTTP client, canonical equality."""

    @POSIX_HOST
    def test_sh0_proxy_tools_equal_direct_canonical(self, started_host: HostHandle) -> None:
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport

        from benchweave_sdk_server.shim import ProxyTarget, build_shim_proxy

        target = ProxyTarget(
            url=started_host.url, bearer=started_host.bearer,
            pid=started_host.pid,
        )
        shim = build_shim_proxy(target)

        async def run() -> tuple[str, str]:
            direct = Client(
                StreamableHttpTransport(
                    f"{started_host.url}/mcp",
                    headers={"Authorization": f"Bearer {started_host.bearer}"},
                )
            )
            async with direct as client:
                direct_tools = await client.list_tools()
            async with Client(shim) as client:
                shim_tools = await client.list_tools()
            return _canon_tools(direct_tools), _canon_tools(shim_tools)

        direct_json, shim_json = asyncio.run(run())
        assert shim_json == direct_json, (
            "the shim-forwarded tool bytes differ from the host's own "
            f"(canonical JSON):\nDIRECT {direct_json[:400]}\nSHIM {shim_json[:400]}"
        )
