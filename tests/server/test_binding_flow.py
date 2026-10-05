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


_MATCHING = b"SDK Example,demo,SIM001,1.0.0\n"
_A = "/dev/match-a"
_B = "/dev/match-b"
_MOVED_B = "/dev/moved-b"


def _binding_app(
    tmp_path: Path,
    *,
    serials: tuple[str | None, str | None] = ("SER-A", "SER-B"),
) -> dict[str, Any]:
    """A serial seam over a binding-backed endpoint (two matching boards).

    The candidates list is mutable: a test re-enumerates by editing it (the
    enumerate closure reads it live), modelling unplug/replug.
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
    session = serial_plugin_session(plugin, endpoint, open_port=open_port)
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
