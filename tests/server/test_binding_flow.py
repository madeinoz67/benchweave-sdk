"""The binding flow through the seam (issue #385 §1.4/§1.5): the AR arms.

AR-A, AR-B, AR-C, AR-G, AR-H and the binding-backed re-scan arm of AR-I
live here, driven through :class:`StandaloneSeam` over injected loopback
doubles — no pyserial, invented names, deterministic (power analysis N/A:
every kill condition is behavioural and the design record §5 names each
arm's RED control). The route-bearing arms (AR-D/AR-E) live in the route
lane; this module pins the seam mechanism they call.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk_server.binding import BindingStore
from benchweave_sdk_server.errors import SeamError
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.session import load_plugin_project


class LoopbackPort:
    """The per-file pyserial-shaped double (the serial suite's own)."""

    def __init__(
        self,
        inbound: bytes = b"",
        replies: dict[bytes, bytes] | None = None,
        read_timeout: float = 0.05,
    ) -> None:
        self.inbound = bytearray(inbound)
        self.replies = dict(replies or {})
        self.written: list[bytes] = []
        self.reads = 0
        self.closes = 0
        self.read_timeout = read_timeout
        self._data = threading.Event()

    def write(self, data: bytes) -> int | None:
        self.written.append(bytes(data))
        reply = self.replies.get(bytes(data))
        if reply is not None:
            self.inbound += reply
            self._data.set()
        return len(data)

    def read(self, size: int = 1) -> bytes:
        self.reads += 1
        while not self.inbound:
            if not self._data.wait(self.read_timeout):
                return b""
            self._data.clear()
        out = bytes(self.inbound[:size])
        del self.inbound[:size]
        return out

    def close(self) -> None:
        self.closes += 1
        self._data.set()


class UsbCandidate:
    """A ``ListPortInfo``-shaped candidate (the resolver reads four fields)."""

    def __init__(
        self,
        device: str,
        vid: int | None = 0x1A86,
        pid: int | None = 0x7523,
        serial_number: str | None = None,
    ) -> None:
        self.device = device
        self.vid = vid
        self.pid = pid
        self.serial_number = serial_number


class _ParkingGate:
    """Arms-on-demand adapter-open parking (fold wave 2, lane A F2): the
    in-flight connect window. Discovery probes run BEFORE the arm pass
    straight through, so the scan that seeds the bind is unaffected; the
    armed window parks exactly the connect's ``open`` until released."""

    def __init__(self) -> None:
        self._armed = False
        self._release = asyncio.Event()

    def arm(self) -> None:
        self._armed = True

    def release(self) -> None:
        self._release.set()

    async def park_if_armed(self) -> None:
        if self._armed:
            await self._release.wait()


class _ParkingAdapter:
    """An adapter double whose ``open`` parks on the gate (nothing in the
    adapter contract forbids awaits in ``open``); everything else delegates
    to the scaffold adapter."""

    def __init__(self, inner: Any, gate: _ParkingGate) -> None:
        self._inner = inner
        self._gate = gate

    async def open(self, descriptor: Any, services: Any, context: Any) -> None:
        await self._gate.park_if_armed()
        return await self._inner.open(descriptor, services, context)

    async def execute(self, request: Any, context: Any) -> dict[str, Any]:
        return await self._inner.execute(request, context)

    async def close(self, context: Any) -> None:
        return await self._inner.close(context)


_MATCHING = b"SDK Example,demo,SIM001,1.0.0\n"
_A = "/dev/match-a"
_B = "/dev/match-b"
_MOVED_B = "/dev/moved-b"


def _binding_app(
    tmp_path: Path,
    *,
    serials: tuple[str | None, str | None] = ("SER-A", "SER-B"),
    open_gate: _ParkingGate | None = None,
) -> dict[str, Any]:
    """A serial seam over a binding-backed endpoint (two matching boards).

    The candidates list is mutable: a test re-enumerates by editing it (the
    enumerate closure reads it live), modelling unplug/replug.
    ``open_gate`` swaps the adapter factory for the parking double (the
    in-flight-connect window, fold wave 2 lane A F2).
    """
    from benchweave_sdk.scaffold import create_project
    from benchweave_sdk_server.binding import binding_endpoint
    from benchweave_sdk_server.serial import (
        SerialEndpoint,
        SerialPortHooks,
        serial_plugin_session,
    )

    project = tmp_path / "proj"
    create_project(project, "example_plugin")
    plugin = load_plugin_project(project)
    if open_gate is not None:
        factory = plugin.adapter_factory
        plugin = replace(
            plugin,
            adapter_factory=lambda: _ParkingAdapter(factory(), open_gate),
        )
    ports = {
        _A: LoopbackPort(replies={b"ID?\n": _MATCHING}),
        _B: LoopbackPort(replies={b"ID?\n": _MATCHING}),
    }
    candidates = [
        UsbCandidate(_A, serial_number=serials[0]),
        UsbCandidate(_B, serial_number=serials[1]),
    ]
    opened: list[str] = []

    def open_port(device: str, settings: dict[str, Any]) -> LoopbackPort:
        opened.append(device)
        return ports[device]

    hooks = SerialPortHooks(
        enumerate_ports=lambda: list(candidates), open_port=open_port
    )
    store = BindingStore.open(tmp_path / "device-bindings.json")
    endpoint = SerialEndpoint(
        binding_endpoint(store, plugin.package, plugin.device_id, hooks.enumerate_ports)
    )
    # The CLI's production shape (trust-2): the session factory mints with
    # the enumeration in hand, so each connect records the serial the
    # enumeration carried for the opened path — the evidence a connected-era
    # scan reconciles its short-circuit row against.
    session = serial_plugin_session(
        plugin, endpoint, open_port=open_port, enumerate_ports=hooks.enumerate_ports
    )
    seam = StandaloneSeam(
        session,
        transport_kind="serial",
        serial_ports=hooks,
        serial_endpoint=endpoint,
        bindings=store,
    )
    return {
        "seam": seam,
        "store": store,
        "ports": ports,
        "candidates": candidates,
        "opened": opened,
        "plugin": plugin,
        "endpoint": endpoint,
        "tmp_path": tmp_path,
    }


def _bind_b(fx: dict[str, Any]) -> None:
    asyncio.run(fx["seam"].call("device_discover"))
    asyncio.run(fx["seam"].bind_device(_B))


# --- the discriminator (§1.3) ------------------------------------------------


def test_distinct_serials_bind_usb_serial_keyed(tmp_path: Path) -> None:
    fx = _binding_app(tmp_path)
    _bind_b(fx)
    row = fx["store"].get(fx["plugin"].package, fx["plugin"].device_id)
    assert row is not None
    assert row["endpoint_kind"] == "usb_serial"
    assert row["usb_serial"] == "SER-B"
    assert row["port_path"] == _B
    assert row["vid"] == "1a86" and row["pid"] == "7523"
    assert row["identity"]["manufacturer"] == "SDK Example"
    assert row["identity"]["model"] == "demo"


def test_duplicate_serials_bind_port_path_keyed(tmp_path: Path) -> None:
    """Two bridges carrying the SAME serial (docks, some hubs): the
    discriminator falls to path keying on the bench's own evidence — the
    serial is not instance-stable here, and the store records that."""
    fx = _binding_app(tmp_path, serials=("X", "X"))
    _bind_b(fx)
    row = fx["store"].get(fx["plugin"].package, fx["plugin"].device_id)
    assert row is not None
    assert row["endpoint_kind"] == "port_path"
    assert row["usb_serial"] is None and row["vid"] is None and row["pid"] is None
    assert row["port_path"] == _B


def test_null_serials_bind_port_path_keyed(tmp_path: Path) -> None:
    """No iSerial on either board (the CH343G-class open fact): the honest
    floor is path keying — the discriminator is data, not guesswork."""
    fx = _binding_app(tmp_path, serials=(None, None))
    _bind_b(fx)
    row = fx["store"].get(fx["plugin"].package, fx["plugin"].device_id)
    assert row is not None
    assert row["endpoint_kind"] == "port_path"


def test_a_live_duplicate_serial_outside_the_cache_keys_on_the_path(
    tmp_path: Path,
) -> None:
    """Review fold M1: the discriminator's duplicate population is the LIVE
    enumeration the resolver will use, never only the confirmed cache — a
    twin that appeared after the scan (or was scan-invisible while busy)
    must not arm serial keying that resolve would immediately refuse as
    ambiguous: the busy-twin dead-end."""
    fx = _binding_app(tmp_path)
    asyncio.run(fx["seam"].call("device_discover"))
    fx["candidates"].append(UsbCandidate("/dev/late-twin", serial_number="SER-B"))
    asyncio.run(fx["seam"].bind_device(_B))
    row = fx["store"].get(fx["plugin"].package, fx["plugin"].device_id)
    assert row is not None
    assert row["endpoint_kind"] == "port_path", (
        "a serial the live enumeration carries twice keys on the path, "
        "even when the cache saw it once"
    )


def test_a_cache_duplicate_whose_live_twin_vanished_keys_on_serial(
    tmp_path: Path,
) -> None:
    """Fold wave 1, M1's refinement: the discriminator counts the LIVE
    enumeration — exactly the population resolve matches over. A scan-time
    duplicate whose port has since vanished no longer forces path keying:
    the live enumeration is the truth resolve will consult, and the pick
    keys on the serial."""
    fx = _binding_app(tmp_path, serials=("X", "X"))
    asyncio.run(fx["seam"].call("device_discover"))
    fx["candidates"].remove(fx["candidates"][0])  # the twin left after the scan
    asyncio.run(fx["seam"].bind_device(_B))
    row = fx["store"].get(fx["plugin"].package, fx["plugin"].device_id)
    assert row is not None
    assert row["endpoint_kind"] == "usb_serial"
    assert row["usb_serial"] == "X"


def test_a_vanished_pick_with_no_twin_refuses_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """Fold wave 2, lane A F1's milder face: the picked port unplugged
    between the scan and the click, nothing replaced it. The confirmed
    cache still carries the row, so the pick-unconfirmed check passes —
    the bind must cross-check the pick against the LIVE enumeration and
    refuse, never write a row for a dead path."""
    fx = _binding_app(tmp_path)
    asyncio.run(fx["seam"].call("device_discover"))
    fx["candidates"].remove(fx["candidates"][1])  # B left after the scan
    with pytest.raises(SeamError) as raised:
        asyncio.run(fx["seam"].bind_device(_B))
    assert raised.value.code == "invalid_request"
    assert "standalone_binding_pick_vanished:" in raised.value.message
    assert _B in raised.value.message
    assert fx["store"].get(fx["plugin"].package, fx["plugin"].device_id) is None
    assert not (fx["tmp_path"] / "device-bindings.json").exists(), (
        "a refused bind writes no document"
    )


def test_a_vanished_pick_with_a_serial_claiming_twin_opens_nothing(
    tmp_path: Path,
) -> None:
    """Fold wave 2, lane A F1's executed trigger: B unplugged after the
    scan and a foreign-class twin claiming SER-B appeared elsewhere. The
    cache cross-check passes and the live serial count is 1 (the twin), so
    the unfixed discriminator arms serial keying off the twin — the
    connect then opens a NEVER-CONFIRMED port. The bind must refuse on the
    picked path's live presence, and the twin must receive zero frames."""
    fx = _binding_app(tmp_path)
    asyncio.run(fx["seam"].call("device_discover"))
    fx["candidates"].remove(fx["candidates"][1])  # B left after the scan
    twin = "/dev/foreign-twin"
    twin_port = LoopbackPort(replies={b"ID?\n": _MATCHING})
    fx["ports"][twin] = twin_port
    fx["candidates"].append(
        UsbCandidate(twin, vid=0x0403, pid=0x6001, serial_number="SER-B")
    )
    with pytest.raises(SeamError) as raised:
        asyncio.run(fx["seam"].bind_device(_B))
    assert raised.value.code == "invalid_request"
    assert "standalone_binding_pick_vanished:" in raised.value.message
    # Nothing is bound, so the connect refuses binding_absent — the twin is
    # never opened and receives zero frames.
    with pytest.raises(SeamError) as connect_refusal:
        asyncio.run(fx["seam"].call("device_connect", {"device_id": "example_device"}))
    assert connect_refusal.value.details["reason"] == "binding_absent"
    assert twin not in fx["opened"], "the never-confirmed twin is never opened"
    assert twin_port.written == [], "the never-confirmed twin receives zero frames"


def test_a_reoccupied_path_with_a_different_serial_refuses_variant_a(
    tmp_path: Path,
) -> None:
    """Fold wave 3, delta F1 variant A: the scan confirmed SER-B at the
    picked path; B unplugged and a SER-X unit took the SAME path, with
    SER-B gone from the bus entirely. The path is live, so the
    vanished-pick check passes — the pick's SERIAL evidence must hold live
    too: the bind must refuse naming both serials, never write a
    path-keyed row on the old scan's identity and connect onto the SER-X
    unit."""
    fx = _binding_app(tmp_path)
    asyncio.run(fx["seam"].call("device_discover"))
    fx["candidates"][1] = UsbCandidate(_B, serial_number="SER-X")
    with pytest.raises(SeamError) as raised:
        asyncio.run(fx["seam"].bind_device(_B))
    assert raised.value.code == "invalid_request"
    assert "standalone_binding_pick_changed:" in raised.value.message
    assert "SER-B" in raised.value.message and "SER-X" in raised.value.message
    assert fx["store"].get(fx["plugin"].package, fx["plugin"].device_id) is None
    assert not (fx["tmp_path"] / "device-bindings.json").exists(), (
        "a refused bind writes no document"
    )
    with pytest.raises(SeamError) as connect_refusal:
        asyncio.run(fx["seam"].call("device_connect", {"device_id": "example_device"}))
    assert connect_refusal.value.details["reason"] == "binding_absent"
    assert fx["opened"] == [_A, _B], "only the seeding scan's probes ever opened a port"


def test_a_reoccupied_path_with_a_different_serial_refuses_variant_b(
    tmp_path: Path,
) -> None:
    """Fold wave 3, delta F1 variant B: the SER-X unit took the picked path
    AND a serial-claiming twin carries SER-B elsewhere — the case that
    mispredicted under the README's discriminator sentence. The bind must
    refuse on the serial-evidence check before any discriminator runs, and
    neither the re-occupied path nor the twin may open."""
    fx = _binding_app(tmp_path)
    asyncio.run(fx["seam"].call("device_discover"))
    fx["candidates"][1] = UsbCandidate(_B, serial_number="SER-X")
    elsewhere = "/dev/ser-b-elsewhere"
    fx["ports"][elsewhere] = LoopbackPort(replies={b"ID?\n": _MATCHING})
    fx["candidates"].append(UsbCandidate(elsewhere, serial_number="SER-B"))
    with pytest.raises(SeamError) as raised:
        asyncio.run(fx["seam"].bind_device(_B))
    assert raised.value.code == "invalid_request"
    assert "standalone_binding_pick_changed:" in raised.value.message
    assert "SER-B" in raised.value.message and "SER-X" in raised.value.message
    assert fx["store"].get(fx["plugin"].package, fx["plugin"].device_id) is None
    with pytest.raises(SeamError) as connect_refusal:
        asyncio.run(fx["seam"].call("device_connect", {"device_id": "example_device"}))
    assert connect_refusal.value.details["reason"] == "binding_absent"
    assert fx["opened"] == [_A, _B], "neither the re-occupied path nor the twin opened"


# --- AR-A: instance-keyed binding (THE core claim) ---------------------------


def test_ar_a_the_picked_instance_is_the_one_that_answers(tmp_path: Path) -> None:
    """Two identical boards, distinct serials: scan, bind B, connect. B's
    write log carries exactly the establishment exchange; A's is EMPTY; the
    store row's port_path is B. KILL: any frame on A, or a connect that
    opened A. RED control (design §5): neutralise the resolver to the
    constant-A form — the pre-slice behaviour — and the arm fails by
    catching frames on A."""
    fx = _binding_app(tmp_path)
    _bind_b(fx)
    port_a: LoopbackPort = fx["ports"][_A]
    port_b: LoopbackPort = fx["ports"][_B]
    # The scan's own identify probes are the confirmation mechanism, not
    # session traffic — snapshot AFTER them and assert the connect adds
    # nothing to the twin and exactly the establishment to B.
    a_before = list(port_a.written)
    b_before = list(port_b.written)
    result = asyncio.run(fx["seam"].call("device_connect", {"device_id": "example_device"}))
    assert result["connected"] is True
    assert port_a.written == a_before, "the unbound twin received zero new bytes"
    assert port_b.written == b_before + [b"ID?\n"], "B carries exactly the establishment"
    assert fx["store"].get(fx["plugin"].package, "example_device")["port_path"] == _B
    # The resolver's last_resolution is the path the live session opened.
    from benchweave_sdk_server.serial import SerialEndpoint

    endpoint = fx["seam"]._serial_endpoint
    assert isinstance(endpoint, SerialEndpoint)
    assert endpoint.last_resolution == _B


def test_ar_b_i_a_moved_board_resolves_by_serial(tmp_path: Path) -> None:
    """usb_serial keying is instance-stable across re-enumeration: replug B
    at a NEW path and the next connection resolves to the moved path."""
    fx = _binding_app(tmp_path)
    _bind_b(fx)
    a_before = list(fx["ports"][_A].written)
    fx["ports"][_MOVED_B] = LoopbackPort(replies={b"ID?\n": _MATCHING})
    fx["candidates"][1] = UsbCandidate(_MOVED_B, serial_number="SER-B")
    asyncio.run(fx["seam"].call("device_connect", {"device_id": "example_device"}))
    assert fx["opened"][-1] == _MOVED_B
    assert fx["ports"][_A].written == a_before, "the twin gains nothing"


def test_ar_b_ii_a_moved_path_keyed_board_refuses_without_fallback(
    tmp_path: Path,
) -> None:
    """Duplicate serials key on the path; move the board and the connect
    REFUSES stale naming the stale path — the surviving same-class twin
    receives zero writes. No silent fallback, ever."""
    fx = _binding_app(tmp_path, serials=("X", "X"))
    _bind_b(fx)
    a_before = list(fx["ports"][_A].written)
    fx["ports"][_MOVED_B] = LoopbackPort(replies={b"ID?\n": _MATCHING})
    fx["candidates"][1] = UsbCandidate(_MOVED_B, serial_number="X")
    with pytest.raises(SeamError) as raised:
        asyncio.run(fx["seam"].call("device_connect", {"device_id": "example_device"}))
    assert raised.value.code == "not_ready"
    assert raised.value.details["reason"] == "binding_stale"
    assert _B in raised.value.message
    assert fx["ports"][_A].written == a_before, "no fallback write to the twin"
    assert _MOVED_B not in fx["opened"], "the moved port is never opened"


def test_ar_c_a_stale_serial_refuses_before_any_open(tmp_path: Path) -> None:
    """The bound USB serial absent from a fresh enumeration: the connect
    refuses BEFORE any port open (the opened list gains nothing) with the
    serial named in the refusal."""
    fx = _binding_app(tmp_path)
    _bind_b(fx)
    opened_after_bind = list(fx["opened"])
    fx["candidates"].remove(fx["candidates"][1])
    with pytest.raises(SeamError) as raised:
        asyncio.run(fx["seam"].call("device_connect", {"device_id": "example_device"}))
    assert raised.value.code == "not_ready"
    assert raised.value.details["reason"] == "binding_stale"
    assert "SER-B" in raised.value.message
    assert fx["opened"] == opened_after_bind, "no port was opened on refusal"


# --- absent binding: serve starts, connect refuses ---------------------------


def test_no_binding_serves_pending_and_refuses_connect_named(
    tmp_path: Path,
) -> None:
    """§1.4 case 2: with no row, the SEAM CONSTRUCTS (the UI must render to
    let the operator pick) and ``device_connect`` refuses ``not_ready`` with
    reason ``binding_absent`` naming the connection key."""
    fx = _binding_app(tmp_path)
    with pytest.raises(SeamError) as raised:
        asyncio.run(fx["seam"].call("device_connect", {"device_id": "example_device"}))
    assert raised.value.code == "not_ready"
    assert raised.value.details["reason"] == "binding_absent"
    assert "example_device" in raised.value.message
    assert fx["opened"] == [], "no port was opened"


# --- AR-G: --device precedence -----------------------------------------------


def test_ar_g_the_device_flag_bypasses_and_never_touches_the_store(
    tmp_path: Path,
) -> None:
    """A stored binding to A plus the constant ``--device`` form: connect
    opens ONLY the named path and the store file's bytes are unchanged by
    the whole run. Precedence: the explicit flag over the stored row."""
    from benchweave_sdk.scaffold import create_project
    from benchweave_sdk_server.serial import (
        SerialEndpoint,
        SerialPortHooks,
        serial_plugin_session,
    )

    project = tmp_path / "proj"
    create_project(project, "example_plugin")
    plugin = load_plugin_project(project)
    named = "/dev/explicit"
    ports = {
        _A: LoopbackPort(replies={b"ID?\n": _MATCHING}),
        _B: LoopbackPort(replies={b"ID?\n": _MATCHING}),
        named: LoopbackPort(replies={b"ID?\n": _MATCHING}),
    }
    opened: list[str] = []

    def open_port(device: str, settings: dict[str, Any]) -> LoopbackPort:
        opened.append(device)
        return ports[device]

    hooks = SerialPortHooks(
        enumerate_ports=lambda: [
            UsbCandidate(_A, serial_number="SER-A"),
            UsbCandidate(_B, serial_number="SER-B"),
            UsbCandidate(named, serial_number="SER-X"),
        ],
        open_port=open_port,
    )
    store_path = tmp_path / "device-bindings.json"
    store = BindingStore.open(store_path)
    # A stored binding to A exists…
    _seed_binding(fx_store=store, hooks=hooks, project=project, pick=_A)
    before = store_path.read_bytes()
    # …but the constant endpoint (the --device form) wins. The seeding
    # scan's probes are not this run's traffic: snapshot after them.
    a_before = list(ports[_A].written)
    b_before = list(ports[_B].written)
    endpoint = SerialEndpoint(named)
    session = serial_plugin_session(plugin, endpoint, open_port=open_port)
    seam = StandaloneSeam(
        session,
        transport_kind="serial",
        serial_ports=hooks,
        serial_endpoint=endpoint,
        bindings=store,
    )
    asyncio.run(seam.call("device_connect", {"device_id": "example_device"}))
    assert opened[-1] == named, "only the explicit path opens"
    assert ports[_A].written == a_before and ports[_B].written == b_before, (
        "neither bound twin gains a byte: the stored row is not consulted"
    )
    assert store_path.read_bytes() == before, "the store file is byte-unchanged"


def _seed_binding(
    *, fx_store: BindingStore, hooks: Any, project: Path, pick: str
) -> Any:
    """Scan through a transient binding-backed seam and bind ``pick``."""
    from benchweave_sdk_server.binding import binding_endpoint
    from benchweave_sdk_server.serial import SerialEndpoint, serial_plugin_session

    plugin = load_plugin_project(project)
    endpoint = SerialEndpoint(
        binding_endpoint(fx_store, plugin.package, plugin.device_id, hooks.enumerate_ports)
    )
    session = serial_plugin_session(plugin, endpoint, open_port=hooks.open_port)
    seam = StandaloneSeam(
        session,
        transport_kind="serial",
        serial_ports=hooks,
        serial_endpoint=endpoint,
        bindings=fx_store,
    )
    asyncio.run(seam.call("device_discover"))
    asyncio.run(seam.bind_device(pick))
    return seam


# --- AR-H: the binding survives a plugin reload ------------------------------


def test_ar_h_the_binding_survives_a_confirmed_reload(tmp_path: Path) -> None:
    """Bind, reload (files unchanged, so no Q11 pend), reconnect: the row
    survives, the reconnect resolves through it, and the reloaded plugin's
    establishment lands on the bound port — the late-bound factory proof."""
    fx = _binding_app(tmp_path)
    _bind_b(fx)
    asyncio.run(fx["seam"].call("device_connect", {"device_id": "example_device"}))
    # One scan probe of B (the confirmation) plus the connection's own open.
    assert fx["opened"].count(_B) == 2
    result = asyncio.run(fx["seam"].reload_plugin(source="test"))
    assert result["status"] == "reloaded"
    assert result["reconnected"] is True
    assert fx["store"].get(fx["plugin"].package, fx["plugin"].device_id) is not None
    assert fx["opened"].count(_B) == 3, "the reconnect resolved through the binding"
    assert fx["ports"][_B].written.count(b"ID?\n") == 3, (
        "scan probe and both establishments all ran on the bound port"
    )


# --- AR-I's binding-backed half: the re-scan never re-opens the live port ----


def test_a_rescan_while_connected_never_reopens_the_bound_port(
    tmp_path: Path,
) -> None:
    """The connected short-circuit now flows from the resolver's
    ``last_resolution`` (the CLI-built arm lives in the wiring lane); the
    binding-backed seam must behave identically: a scan while connected
    serves the connected row from session identity and opens nothing for
    it."""
    fx = _binding_app(tmp_path)
    _bind_b(fx)
    asyncio.run(fx["seam"].call("device_connect", {"device_id": "example_device"}))
    opened_at_connect = list(fx["opened"])
    establishment = list(fx["ports"][_B].written)
    rows = asyncio.run(fx["seam"].call("device_discover"))["devices"]
    assert fx["opened"].count(_B) == opened_at_connect.count(_B), (
        "the bound, connected port is never re-opened by a scan"
    )
    assert fx["ports"][_B].written == establishment, "no bytes on the live port"
    connected_row = next(row for row in rows if row["port_path"] == _B)
    assert connected_row["usb_serial"] == "SER-B"


# --- trust-2: the connected-era serial reconciliation -------------------------


def test_the_factory_records_the_mint_time_serial(tmp_path: Path) -> None:
    """The evidence itself: a connect through the CLI's production shape
    (factory minted with the enumeration) records the serial the
    enumeration carried for the path it opened — known, on the endpoint the
    discovery short-circuit already reads."""
    fx = _binding_app(tmp_path)
    _bind_b(fx)
    asyncio.run(fx["seam"].call("device_connect", {"device_id": "example_device"}))
    assert fx["endpoint"].last_resolution == _B
    assert fx["endpoint"].last_serial == "SER-B"
    assert fx["endpoint"].last_serial_known is True


def test_a_connected_era_scan_refuses_the_reoccupied_connected_path(
    tmp_path: Path,
) -> None:
    """Probe 3's attack, through the seam (the production wiring): bind A,
    connect, physically swap the occupant at A (its serial changes while
    the session stays connected), scan. The unfixed seam served a chimera
    row at A — the session's OLD identity with the re-occupant's NEW
    serial — which then confirmed a bind keyed on the foreign serial, and
    the connect after it established on the never-picked unit. With the
    mint-time reconciliation: the scan carries NO row at A, and the bind
    after the disconnect refuses unconfirmed — the re-occupant never
    enters the confirmed cache."""
    fx = _binding_app(tmp_path)
    seam = fx["seam"]
    asyncio.run(seam.call("device_discover"))
    asyncio.run(seam.bind_device(_A))
    asyncio.run(seam.call("device_connect", {"device_id": "example_device"}))
    assert seam.session.connected
    # The physical swap: A's occupant leaves; a foreign unit (same path,
    # different serial) arrives. The session stays 'connected' (host
    # state; nothing probed the dead link).
    written_before = list(fx["ports"][_A].written)
    fx["candidates"][:] = [
        UsbCandidate(_A, serial_number="SER-X"),
        UsbCandidate(_B, serial_number="SER-B"),
    ]
    scan = asyncio.run(seam.call("device_discover"))
    paths = [row["port_path"] for row in scan["devices"]]
    assert _A not in paths, (
        "the re-occupied connected path must not serve a confirmed row"
    )
    assert fx["ports"][_A].written == written_before, (
        "the scan transmitted nothing on the connected path either way"
    )
    # The re-pick path after the swap: disconnect, then the operator's
    # click on the vanished row refuses — A is no longer confirmed.
    asyncio.run(seam.call("device_disconnect", {"device_id": "example_device"}))
    with pytest.raises(SeamError) as raised:
        asyncio.run(seam.bind_device(_A))
    assert raised.value.code == "invalid_request"
    assert "standalone_binding_pick_unconfirmed" in raised.value.message


def test_a_connected_era_scan_serves_the_row_when_the_serial_holds(
    tmp_path: Path,
) -> None:
    """The reconciliation's negative control: an UNCHANGED enumeration
    serves the connected row exactly as before — the fix refuses only the
    mismatched occupant, never the honest connected view."""
    fx = _binding_app(tmp_path)
    _bind_b(fx)
    asyncio.run(fx["seam"].call("device_connect", {"device_id": "example_device"}))
    rows = asyncio.run(fx["seam"].call("device_discover"))["devices"]
    connected_row = next(row for row in rows if row["port_path"] == _B)
    assert connected_row["usb_serial"] == "SER-B"


# --- bind/unbind guards ------------------------------------------------------


def test_bind_while_connected_refuses_conflict_unchanged(tmp_path: Path) -> None:
    fx = _binding_app(tmp_path)
    _bind_b(fx)
    store_path = fx["tmp_path"] / "device-bindings.json"
    before = store_path.read_bytes()
    asyncio.run(fx["seam"].call("device_connect", {"device_id": "example_device"}))
    with pytest.raises(SeamError) as raised:
        asyncio.run(fx["seam"].bind_device(_A))
    assert raised.value.code == "conflict"
    assert store_path.read_bytes() == before, "a refused bind writes nothing"


def test_unbind_while_connected_refuses_conflict(tmp_path: Path) -> None:
    fx = _binding_app(tmp_path)
    _bind_b(fx)
    asyncio.run(fx["seam"].call("device_connect", {"device_id": "example_device"}))
    with pytest.raises(SeamError) as raised:
        asyncio.run(fx["seam"].unbind_device())
    assert raised.value.code == "conflict"


def test_an_unconfirmed_pick_refuses_unchanged(tmp_path: Path) -> None:
    """AR-D's seam half: a hand-crafted pick naming a path the confirmed
    cache never carried refuses ``invalid_request`` with the
    ``standalone_binding_pick_unconfirmed:`` prefix; the store bytes are
    unchanged."""
    fx = _binding_app(tmp_path)
    asyncio.run(fx["seam"].call("device_discover"))
    asyncio.run(fx["seam"].bind_device(_B))
    store_path = fx["tmp_path"] / "device-bindings.json"
    before = store_path.read_bytes()
    with pytest.raises(SeamError) as raised:
        asyncio.run(fx["seam"].bind_device("/dev/never-scanned"))
    assert raised.value.code == "invalid_request"
    assert "standalone_binding_pick_unconfirmed:" in raised.value.message
    assert store_path.read_bytes() == before


def test_a_bind_without_any_scan_refuses_unconfirmed(tmp_path: Path) -> None:
    fx = _binding_app(tmp_path)
    with pytest.raises(SeamError) as raised:
        asyncio.run(fx["seam"].bind_device(_B))
    assert raised.value.code == "invalid_request"
    assert "standalone_binding_pick_unconfirmed:" in raised.value.message


def test_unbind_removes_the_row_and_publishes(tmp_path: Path) -> None:
    fx = _binding_app(tmp_path)
    _bind_b(fx)
    last = fx["seam"].events.last_id()
    asyncio.run(fx["seam"].unbind_device())
    assert fx["store"].rows() == []
    document = json.loads((fx["tmp_path"] / "device-bindings.json").read_text())
    assert document["bindings"] == [], "unbind leaves a valid empty document"
    kinds = [row["kind"] for row in fx["seam"].events.after(last)]
    assert "device_unbound" in kinds


def test_bind_publishes_device_bound(tmp_path: Path) -> None:
    fx = _binding_app(tmp_path)
    asyncio.run(fx["seam"].call("device_discover"))
    last = fx["seam"].events.last_id()
    asyncio.run(fx["seam"].bind_device(_B))
    published = [row for row in fx["seam"].events.after(last) if row["kind"] == "device_bound"]
    assert published and published[0]["data"]["port_path"] == _B


# --- fold wave 2: the guards must see an in-flight connect ---------------------


async def _await_open_count(fx: dict[str, Any], path: str, count: int) -> None:
    """Rendezvous with the connect's factory open: once ``path`` was opened
    ``count`` times the connect sits inside the parked adapter ``open`` (the
    only await left before establish)."""
    deadline = time.monotonic() + 5.0
    while fx["opened"].count(path) < count:
        if time.monotonic() > deadline:
            raise AssertionError(f"{path} was not opened {count}x in time")
        await asyncio.sleep(0.01)


def test_a_bind_during_an_in_flight_connect_refuses_conflict(
    tmp_path: Path,
) -> None:
    """Fold wave 2, lane A F2: an adapter ``open`` that parks is the
    in-flight connect window — the port is open on the wire while
    ``connected`` is still False. The bind conflict guard must see the
    window: the unguarded seam reads connected=False and the bind LANDS,
    leaving the live session on a different endpoint than the store
    records."""
    gate = _ParkingGate()
    fx = _binding_app(tmp_path, open_gate=gate)
    _bind_b(fx)
    store_path = fx["tmp_path"] / "device-bindings.json"
    before = store_path.read_bytes()

    async def scenario() -> dict[str, Any]:
        baseline = fx["opened"].count(_B)
        gate.arm()
        connect_task = asyncio.create_task(
            fx["seam"].call("device_connect", {"device_id": "example_device"})
        )
        await _await_open_count(fx, _B, baseline + 1)
        bind_task = asyncio.create_task(fx["seam"].bind_device(_A))
        await asyncio.sleep(0.05)  # the bind has run, or is queued on the seam
        gate.release()
        connected = await connect_task
        with pytest.raises(SeamError) as raised:
            await bind_task
        assert raised.value.code == "conflict"
        return connected

    connected = asyncio.run(scenario())
    assert connected["connected"] is True
    assert store_path.read_bytes() == before, "the refused bind wrote nothing"
    row = fx["store"].get(fx["plugin"].package, fx["plugin"].device_id)
    assert row is not None and row["port_path"] == _B, "the live endpoint stands"


def test_a_discover_during_an_in_flight_connect_never_reopens_the_port(
    tmp_path: Path,
) -> None:
    """Fold wave 2, lane A F2's other face: the scan's confirm-by-identify
    OPENS candidate ports. During an in-flight connect the unguarded
    short-circuit reads connected=False and the scan re-opens the port the
    connecting session just opened — a double-open on the wire. The guarded
    scan waits for the connect, then serves the connected row from session
    identity."""
    gate = _ParkingGate()
    fx = _binding_app(tmp_path, open_gate=gate)
    _bind_b(fx)

    async def scenario() -> tuple[list[dict[str, Any]], int]:
        baseline = fx["opened"].count(_B)
        gate.arm()
        connect_task = asyncio.create_task(
            fx["seam"].call("device_connect", {"device_id": "example_device"})
        )
        await _await_open_count(fx, _B, baseline + 1)
        discover_task = asyncio.create_task(fx["seam"].call("device_discover"))
        await asyncio.sleep(0.05)  # the scan is in flight against the parked connect
        gate.release()
        connected = await connect_task
        devices = await discover_task
        assert connected["connected"] is True
        return devices["devices"], baseline

    rows, baseline = asyncio.run(scenario())
    # Exactly ONE open of the bound port beyond the seeding scan's probe:
    # the connect's own. The unguarded seam re-opened it for the scan's
    # identify probe while the connect was still in flight.
    assert fx["opened"].count(_B) == baseline + 1, (
        "the connecting port is never re-opened by a scan"
    )
    connected_row = next(row for row in rows if row["port_path"] == _B)
    assert connected_row["usb_serial"] == "SER-B"
