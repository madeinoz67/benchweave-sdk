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
    transport, free port, the supervision family under a scratch root.
    The spawn's cwd is a scratch dir too — a host's default capture
    root resolves under its cwd, and the repo checkout is not a bench."""
    root = tmp_path_factory.mktemp("family")
    run_cwd = root / "cwd"
    run_cwd.mkdir()
    bindings = root / "device-bindings.json"
    port = _free_port()
    started = subprocess.run(
        [
            sys.executable, "-m", "benchweave_sdk_server.cli", "start",
            str(starter_project), "--bindings", str(bindings),
            "--host", "127.0.0.1", "--port", str(port),
        ],
        cwd=str(run_cwd), capture_output=True, text=True, timeout=120,
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


# --- the CLI-level arms (SH1-SH9): the reshaped `mcp` command -----------------


def _raw_stdio_exchange(
    args: list[str],
    *,
    project: Path,
    env_extra: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> dict[str, object]:
    """One raw stdio exchange against a real shim subprocess: initialize
    → initialized → tools/list → stdin EOF. Captures EVERY output byte
    (SH3's subject) plus the parsed initialize result and tool names."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    proc = subprocess.Popen(
        [sys.executable, "-m", "benchweave_sdk_server.cli", "mcp", str(project), *args],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=str(cwd or REPO), env=env,
    )
    assert proc.stdin is not None and proc.stdout is not None
    initialize = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "shim-arm", "version": "0"},
        },
    }
    proc.stdin.write(json.dumps(initialize) + "\n")
    proc.stdin.write(json.dumps(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}
    ) + "\n")
    proc.stdin.write(json.dumps(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    ) + "\n")
    proc.stdin.close()
    stdout, stderr = proc.communicate(timeout=60)
    init_result: dict[str, object] = {}
    tools: list[str] = []
    for line in stdout.splitlines():
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if message.get("id") == 1 and "result" in message:
            init_result = dict(message["result"])
        if message.get("id") == 2 and "result" in message:
            tools = [
                str(tool.get("name"))
                for tool in message["result"].get("tools", [])
            ]
    return {
        "init": init_result,
        "tools": tools,
        "stdout": stdout,
        "stderr": stderr,
        "returncode": proc.returncode,
    }


def _stdio_client(
    args: list[str],
    *,
    project: Path,
    env_extra: dict[str, str] | None = None,
    cwd: Path | None = None,
    stderr_log: Path | None = None,
) -> object:
    """A context-manager shim client over a REAL stdio subprocess. The
    subprocess's stderr is captured to ``stderr_log`` (StdioTransport's
    log_file — the SH4/SH7/SH8 disclosure lines land there)."""
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return Client(StdioTransport(
        sys.executable,
        ["-m", "benchweave_sdk_server.cli", "mcp", str(project), *args],
        env=env, cwd=str(cwd or REPO), keep_alive=False,
        log_file=stderr_log,
    ))


#: The synthetic binary fixture (tests/fixtures/binary_frames_plugin): a
#: WRITABLE scripted parameter (sample_avg, rw) and a scripted capture
#: exchange, so the parity arms can walk a real device conversation. The
#: mock host's script is LINEAR and demand-ordered (the bytestream
#: doctrine), so each arm that consumes the device script starts its OWN
#: host — the module host stays for the arms that never speak to the
#: device (tools/list, instructions, refusals).
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "binary_frames_plugin"
DEV = {"device_id": "frames_dev"}

#: The capture burst's shape (the fixture's scripted exchange): 128
#: float64 samples = the 1024-byte burst, the bytestream suite's own args.
CAPTURE_ARGS = {
    "format": "waveform_f64le",
    "count": 128,
    "sample_interval_s": 0.001,
    "unit": "V",
}


@pytest.fixture()
def scripted_host(tmp_path: Path):
    """A fresh started host per arm (the linear script is consumed
    in-memory per process): mock transport over the binary fixture. The
    spawn's cwd is a scratch dir — a host's default capture root
    resolves under its cwd, and the repo checkout is not a bench."""
    run_cwd = tmp_path / "cwd"
    run_cwd.mkdir()
    bindings = tmp_path / "device-bindings.json"
    port = _free_port()
    started = subprocess.run(
        [
            sys.executable, "-m", "benchweave_sdk_server.cli", "start",
            str(FIXTURE), "--bindings", str(bindings),
            "--host", "127.0.0.1", "--port", str(port),
        ],
        cwd=str(run_cwd), capture_output=True, text=True, timeout=120,
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


class TestShimSubprocessArms:
    """SH1-SH9: real shim subprocesses over the module-scoped host and
    staged families."""

    @POSIX_HOST
    def test_sh1_agent_to_host_to_browser(
        self, scripted_host: HostHandle, tmp_path: Path,
    ) -> None:
        """One session, agent→host→browser: the agent's stage/apply and
        capture round-trip land on the HOST's session (the script walks
        in the fixture's demand order); the browser's data path (REST)
        serves the SAME session (the connect the agent made persists —
        a fallback fork would refuse not_connected); the capture's own
        metadata carries surface "mcp" — the host recorded the MCP
        surface for the shim-forwarded work. SH2's clauses ride this
        arm's run."""
        capture_dir = tmp_path / "shim-captures"  # SH2's shim-only root
        before = scripted_host.tokens_file.read_bytes()
        journal = lifecycle.journal_path(scripted_host.bindings)
        rows_before = (
            len(journal.read_text().splitlines()) if journal.exists() else 0
        )

        async def run() -> dict[str, object]:
            async with _stdio_client(
                ["--bindings", str(scripted_host.bindings)],
                project=FIXTURE,
                env_extra={"BENCHWEAVE_CAPTURE_DIR": str(capture_dir)},
            ) as client:
                await client.call_tool("bws_v1_device_connect", DEV)
                await client.call_tool("bws_v1_parameter_read", {**DEV, "parameter": "sample_avg"})
                await client.call_tool("bws_v1_parameter_stage", {
                    **DEV, "parameter": "sample_avg", "value": 3.0,
                })
                applied = (await client.call_tool(
                    "bws_v1_parameter_apply", DEV,
                )).structured_content
                capture = (await client.call_tool(
                    "bws_v1_capture_start", {**DEV, **CAPTURE_ARGS},
                )).structured_content
                capture_id = str(capture.get("capture_id"))
                # A count-bound capture completes on the burst itself;
                # the stop tolerates the already-completed shape.
                await client.call_tool(
                    "bws_v1_capture_stop", {"capture_id": capture_id},
                    raise_on_error=False,
                )
                listed = (await client.call_tool(
                    "bws_v1_capture_list", {},
                )).structured_content
                events = (await client.call_tool(
                    "bws_v1_events_get", {"after_id": 0},
                )).structured_content
            # The burst drains on the host: poll the list through the
            # shim until the capture publishes (bounded retries).
            for _ in range(10):
                rows = listed.get("captures", [])
                if rows and rows[-1].get("state") == "published":
                    break
                await asyncio.sleep(0.2)
                async with _stdio_client(
                    ["--bindings", str(scripted_host.bindings)],
                    project=FIXTURE,
                ) as client:
                    listed = (await client.call_tool(
                        "bws_v1_capture_list", {},
                    )).structured_content
            return {
                "applied": applied,
                "capture": capture,
                "listed": listed,
                "events": events,
            }
            return {
                "applied": applied,
                "capture": capture,
                "listed": listed,
                "events": events,
            }

        outcome = asyncio.run(run())
        after = scripted_host.tokens_file.read_bytes()
        # The agent's apply landed on the host's device conversation.
        applied = outcome["applied"]
        assert applied is not None and applied.get("applied", [{}])[0].get("value") == 3.0
        # The browser's data path serves the SAME session: the connect
        # the agent made persists (a fallback fork would refuse
        # not_connected); the scripted poll answers its own row.
        with httpx.Client(
            base_url=scripted_host.url, timeout=5.0,
            headers={"Authorization": f"Bearer {scripted_host.bearer}"},
        ) as rest:
            response = rest.post(
                "/v1/parameter_read",
                json={"device_id": "frames_dev", "parameter": "sample_avg"},
            )
            assert response.status_code == 200, response.text
        # The surface witness: the host's capture metadata records the
        # MCP surface for the shim-forwarded capture (the event payload
        # carries no surface field — this is the surface-bearing
        # mechanism the record's parity claim rides).
        listed = outcome["listed"]
        rows = listed.get("captures", [])
        assert rows and rows[-1].get("surface") == "mcp", listed
        # The event pair exists (kinds; event data carries no surface).
        events = outcome["events"]
        kinds = [row.get("kind") for row in events.get("events", [])]
        assert "parameter_stage" in kinds
        assert "parameter_apply" in kinds
        # SH2's first three clauses ride this arm's run.
        record = json.loads(lifecycle.pid_path(scripted_host.bindings).read_text())
        assert record["pid"] == scripted_host.pid
        assert before == after, "the tokens file moved under the shim"
        rows_after = (
            len(journal.read_text().splitlines()) if journal.exists() else 0
        )
        assert rows_after == rows_before, "the shim journaled"

    @POSIX_HOST
    def test_sh1b_browser_to_host_to_agent(
        self, scripted_host: HostHandle,
    ) -> None:
        """The reverse direction: the browser's write (REST connect,
        read, stage, apply — the demand order) lands on the host's
        session; the agent's read THROUGH THE SHIM then serves the SAME
        session (the REST connect persists — a fork would refuse)."""
        with httpx.Client(
            base_url=scripted_host.url, timeout=5.0,
            headers={"Authorization": f"Bearer {scripted_host.bearer}"},
        ) as rest:
            for operation, arguments in (
                ("device_connect", DEV),
                ("parameter_read", {**DEV, "parameter": "sample_avg"}),
                ("parameter_stage", {**DEV, "parameter": "sample_avg", "value": 3.0}),
                ("parameter_apply", DEV),
                ("capture_start", {**DEV, **CAPTURE_ARGS}),
            ):
                response = rest.post(f"/v1/{operation}", json=arguments)
                assert response.status_code == 200, response.text
            assert response.json()["data"]["state"] == "capturing"
            # The capture row is consumed; the poll row is next for the
            # shim's read. The capture publishes on its own.
            for _ in range(10):
                listing = rest.post("/v1/capture_list", json={})
                assert listing.status_code == 200, listing.text
                rows = listing.json()["data"]["captures"]
                if rows and rows[-1].get("state") == "published":
                    break
                time.sleep(0.2)

        async def run() -> object:
            async with _stdio_client(
                ["--bindings", str(scripted_host.bindings)],
                project=FIXTURE,
            ) as client:
                return (await client.call_tool(
                    "bws_v1_parameter_read",
                    {**DEV, "parameter": "sample_avg"},
                )).structured_content

        read = asyncio.run(run())
        assert read is not None and read.get("value") == 2.5  # the poll row

    @POSIX_HOST
    def test_sh2_no_second_writer(
        self, scripted_host: HostHandle, tmp_path: Path,
    ) -> None:
        """After a shim session: pidfile names the HOST pid; tokens
        byte-identical; no journal row; the shim-only capture dir is
        still ABSENT — the shim wrote nothing anywhere. The shim speaks
        host_info only (no device conversation; the script is not
        consumed)."""
        capture_dir = tmp_path / "shim-capture-probe"
        before = scripted_host.tokens_file.read_bytes()
        async def run() -> None:
            async with _stdio_client(
                ["--bindings", str(scripted_host.bindings)],
                project=FIXTURE,
                env_extra={"BENCHWEAVE_CAPTURE_DIR": str(capture_dir)},
            ) as client:
                await client.call_tool("bws_v1_host_info", {})
        asyncio.run(run())
        record = json.loads(lifecycle.pid_path(scripted_host.bindings).read_text())
        assert record["pid"] == scripted_host.pid
        assert scripted_host.tokens_file.read_bytes() == before
        journal = lifecycle.journal_path(scripted_host.bindings)
        for row in (journal.read_text().splitlines() if journal.exists() else []):
            payload = json.loads(row)
            assert "shim" not in str(payload.get("event", "")).lower()
        assert not capture_dir.exists(), "the shim created its capture dir"

    @POSIX_HOST
    def test_sh3_token_hygiene_kill_on_sight(
        self, started_host: HostHandle, starter_project: Path,
    ) -> None:
        """SH3: zero occurrences of the bearer value or the literal
        'Bearer ' in the shim subprocess's FULL stdout+stderr."""
        exchange = _raw_stdio_exchange(
            ["--bindings", str(started_host.bindings)],
            project=starter_project,
        )
        assert exchange["returncode"] == 0, exchange["stderr"]
        everything = str(exchange["stdout"]) + str(exchange["stderr"])
        assert started_host.bearer not in everything
        assert "Bearer " not in everything

    def test_sh4_fallback_engages(
        self, tmp_path: Path,
    ) -> None:
        """Empty family → the shim serves the in-process fallback:
        stderr carries the fallback line naming verdict absent; the
        instructions carry the in-process marker; a stage/apply succeeds
        on the local mock; host_info answers mode standalone."""
        scratch = tmp_path / "empty-family"
        scratch.mkdir()
        stderr_path = scratch / "shim-stderr.log"

        async def run() -> dict[str, object]:
            async with _stdio_client(
                [], project=FIXTURE, cwd=scratch,
                stderr_log=stderr_path,
            ) as client:
                host_info = (await client.call_tool(
                    "bws_v1_host_info", {})).structured_content
                await client.call_tool("bws_v1_device_connect", DEV)
                await client.call_tool("bws_v1_parameter_read", {**DEV, "parameter": "sample_avg"})
                stage = await client.call_tool("bws_v1_parameter_stage", {
                    **DEV, "parameter": "sample_avg", "value": 3.0,
                }, raise_on_error=False)
                apply_result = await client.call_tool(
                    "bws_v1_parameter_apply", DEV,
                    raise_on_error=False,
                )
            return {
                "host_info": host_info,
                "stage": stage,
                "apply": apply_result,
            }

        outcome = asyncio.run(run())
        assert outcome["host_info"] is not None
        assert outcome["host_info"].get("mode") == "standalone"
        assert not getattr(outcome["stage"], "is_error", True), (
            "the fallback's local mock must serve the stage"
        )
        assert not getattr(outcome["apply"], "is_error", True), (
            "the fallback's local mock must serve the apply"
        )
        text = stderr_path.read_text()
        assert "no running host beside" in text
        assert "verdict: absent" in text
        assert "in-process fallback" in text

    @POSIX_HOST
    def test_sh5_fork_guard_refuses_cli_level(
        self, starter_project: Path, tmp_path: Path,
    ) -> None:
        """A live foreign pid in the capture root's library.lock refuses
        the fallback, typed, naming the pid; no server is served."""
        from benchweave_sdk_server.shim import CAPTURE_ROOT_HELD_PREFIX

        family = tmp_path / "family"
        family.mkdir()
        capture = tmp_path / "held-root"
        capture.mkdir()
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL,
        )
        try:
            (capture / "library.lock").write_text(
                json.dumps({"pid": child.pid}), encoding="utf-8"
            )
            exchange = _raw_stdio_exchange(
                ["--bindings", str(family / "device-bindings.json")],
                project=starter_project,
                env_extra={"BENCHWEAVE_CAPTURE_DIR": str(capture)},
            )
            assert exchange["returncode"] != 0
            assert CAPTURE_ROOT_HELD_PREFIX in str(exchange["stderr"])
            assert str(child.pid) in str(exchange["stderr"])
            assert exchange["tools"] == []
        finally:
            child.terminate()
            child.wait(timeout=10)

    @POSIX_HOST
    @requires_posix_file_perms
    def test_sh6_ours_but_unproxyable_refuses(
        self, started_host: HostHandle, starter_project: Path,
    ) -> None:
        """chmod 000 on the tokens file: refusal typed, naming the
        stop/start action — and NOT a fallback (the live host keeps
        serving; a follow-up REST read succeeds)."""
        from benchweave_sdk_server.shim import HOST_UNPROXYABLE_PREFIX

        lifecycle.tokens_path(started_host.bindings).chmod(0o000)
        try:
            exchange = _raw_stdio_exchange(
                ["--bindings", str(started_host.bindings)],
                project=starter_project,
            )
            assert exchange["returncode"] != 0
            combined = str(exchange["stderr"]) + str(exchange["stdout"])
            assert HOST_UNPROXYABLE_PREFIX in combined
            assert "stop" in combined and "start" in combined
        finally:
            lifecycle.tokens_path(started_host.bindings).chmod(0o600)
        # The live host never stopped serving.
        with httpx.Client(
            base_url=started_host.url, timeout=5.0,
            headers={"Authorization": f"Bearer {started_host.bearer}"},
        ) as rest:
            response = rest.post("/v1/host_info", json={})
            assert response.status_code == 200, response.text

    @POSIX_HOST
    def test_sh7_stale_family_falls_back_with_disclosure(
        self, starter_project: Path, tmp_path: Path,
    ) -> None:
        """(a) a dead-pid pidfile and (b) a dead pidfile whose tokens
        name a different dead pid — both fall back WITH the disclosure
        naming the verdict; neither proxies. The live-pidfile token
        mismatch is SH6's refusal class (pinned in TestDiscover).
        Interpretation note: the §6 SH7 row's "(b) falls back" is
        coherent only under a DEAD pidfile — a LIVE pidfile with a
        tokens mismatch is the record's own KILL shape (fallback beside
        verdict-ours), so (b) is armed as its stale-family variant."""
        # (a) dead pidfile, no tokens.
        family_a = tmp_path / "stale-a"
        family_a.mkdir()
        bindings_a = family_a / "device-bindings.json"
        _stage_ours_pidfile(bindings_a, _dead_child())
        stderr_a = family_a / "stderr.log"
        async def run_a() -> object:
            async with _stdio_client(
                ["--bindings", str(bindings_a)],
                project=starter_project, cwd=family_a,
                stderr_log=stderr_a,
            ) as client:
                return (await client.call_tool(
                    "bws_v1_host_info", {})).structured_content
        assert asyncio.run(run_a()) is not None  # a server WAS served
        text_a = stderr_a.read_text()
        assert "verdict: dead" in text_a
        assert "in-process fallback" in text_a

        # (b) dead pidfile + tokens naming a different dead pid.
        family_b = tmp_path / "stale-b"
        family_b.mkdir()
        bindings_b = family_b / "device-bindings.json"
        dead_one = _dead_child()
        dead_two = _dead_child()
        _stage_ours_pidfile(bindings_b, dead_one)
        _stage_tokens(bindings_b, pid=dead_two)
        stderr_b = family_b / "stderr.log"
        async def run_b() -> object:
            async with _stdio_client(
                ["--bindings", str(bindings_b)],
                project=starter_project, cwd=family_b,
                stderr_log=stderr_b,
            ) as client:
                return (await client.call_tool(
                    "bws_v1_host_info", {})).structured_content
        assert asyncio.run(run_b()) is not None
        text_b = stderr_b.read_text()
        assert "verdict: dead" in text_b

    @POSIX_HOST
    def test_sh8_authoring_degrade(
        self, started_host: HostHandle, starter_project: Path,
    ) -> None:
        """Host started WITHOUT authoring (start has no such flag —
        every started host is a non-authoring host): the shim with
        --authoring serves anyway, the tool list has no authoring
        tools, and stderr carries the mismatch disclosure."""
        stderr_path = started_host.bindings.parent / "sh8-stderr.log"
        async def run() -> list[str]:
            async with _stdio_client(
                ["--bindings", str(started_host.bindings), "--authoring"],
                project=starter_project,
                stderr_log=stderr_path,
            ) as client:
                tools = await client.list_tools()
            return [str(tool.name) for tool in tools]

        names = asyncio.run(run())
        assert "plugin_new" not in names
        text = stderr_path.read_text()
        assert "does not serve authoring tools" in text

    @POSIX_HOST
    def test_sh9_proxy_mode_instructions_name_the_host(
        self, started_host: HostHandle, starter_project: Path,
    ) -> None:
        """SH9 proxy half: the real shim subprocess's initialize result
        carries instructions naming the host URL and pid, and never the
        fallback marker."""
        from benchweave_sdk_server.shim import FALLBACK_MARKER

        exchange = _raw_stdio_exchange(
            ["--bindings", str(started_host.bindings)],
            project=starter_project,
        )
        assert exchange["returncode"] == 0, exchange["stderr"]
        init = exchange["init"]
        instructions = str(init.get("instructions", ""))
        assert started_host.url in instructions
        assert str(started_host.pid) in instructions
        assert "share one host" in instructions
        assert FALLBACK_MARKER not in instructions


# --- SH9's fallback half (in-process, the test_mcp.py pattern) ----------------


class TestSH9Fallback:
    @POSIX_HOST
    def test_fallback_instructions_carry_the_marker(self, starter_project: Path) -> None:
        from benchweave_sdk_server.cli import _build_seam
        from benchweave_sdk_server.mcp import registered_tool_names
        from benchweave_sdk_server.shim import (
            FALLBACK_MARKER,
            PROXY_MARKER_TEMPLATE,
            build_fallback_server,
        )

        seam, _ = _build_seam(starter_project)
        server = build_fallback_server(seam, authoring=True)
        assert FALLBACK_MARKER in server.instructions
        assert "{url}" not in server.instructions
        assert PROXY_MARKER_TEMPLATE.split("{url}")[0] not in server.instructions
        # The full tool set rides the fallback construction (AM1's shape).
        assert "bws_v1_host_info" in set(registered_tool_names(server))
        assert "plugin_new" in set(registered_tool_names(server))
        asyncio.run(seam.settle_capture_for_shutdown())
        seam.close()
