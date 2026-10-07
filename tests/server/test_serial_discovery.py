"""Serial discovery (SW-62) and the NFR-O3 GET/POST split (AR-4).

Loopback candidates only: enumeration and port opening are injected, the
two descriptor-matching candidates answer identify, one answers foreign,
one stays silent. ``device_discover`` returns exactly the two; the write
log shows only identify frames; GET / never transmits (the last-result
cache); scanning is an explicit POST.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
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


class CandidatePort:
    """A list_ports-shaped candidate: ``device`` plus USB identity.

    ``serial_number`` models ``ListPortInfo``'s own field (None when the
    device descriptor carries no iSerial — the CH343G-class open fact).
    """

    def __init__(
        self,
        device: str,
        vid: int | None = None,
        pid: int | None = None,
        serial_number: str | None = None,
    ) -> None:
        self.device = device
        self.vid = vid
        self.pid = pid
        self.serial_number = serial_number


_MATCHING = b"SDK Example,demo,SIM001,1.0.0\n"
_FOREIGN = b"Other Vendor,other,X999,9.9\n"


def _scan_fixture(tmp_path: Path) -> dict[str, Any]:
    """The AR-4 fixture: four candidates, two answering with the
    descriptor's identity, one foreign, one silent."""
    project = tmp_path / "proj"
    from benchweave_sdk.scaffold import create_project

    create_project(project, "example_plugin")
    descriptor_path = project / "src" / "example_plugin" / "descriptor.json"
    document = json.loads(descriptor_path.read_text())
    document["transport"]["settings"]["x-standalone-usb-vid"] = "1a86"
    descriptor_path.write_text(json.dumps(document))
    plugin = load_plugin_project(project)
    matching_a = LoopbackPort(replies={b"ID?\n": _MATCHING})
    matching_b = LoopbackPort(replies={b"ID?\n": _MATCHING})
    foreign = LoopbackPort(replies={b"ID?\n": _FOREIGN})
    silent = LoopbackPort()
    ports = {
        "/dev/match-a": matching_a,
        "/dev/match-b": matching_b,
        "/dev/foreign": foreign,
        "/dev/silent": silent,
    }
    candidates = [
        CandidatePort("/dev/match-a", vid=0x1A86, pid=0x7523, serial_number="SER-A"),
        CandidatePort("/dev/match-b", vid=0x1A86, pid=0x7523, serial_number="SER-B"),
        CandidatePort("/dev/foreign", vid=0x1A86, pid=0x0002),
        CandidatePort("/dev/silent", vid=0x1A86, pid=0x0003),
        CandidatePort("/dev/other-vendor", vid=0x10C4, pid=0xEA60),
    ]
    opened: list[str] = []

    def open_port(device: str, settings: dict[str, Any]) -> LoopbackPort:
        opened.append(device)
        return ports[device]

    def enumerate_ports() -> list[CandidatePort]:
        return list(candidates)

    from benchweave_sdk_server.serial import SerialPortHooks

    hooks = SerialPortHooks(enumerate_ports=enumerate_ports, open_port=open_port)
    return {
        "plugin": plugin,
        "ports": ports,
        "opened": opened,
        "hooks": hooks,
        "matching": [matching_a, matching_b],
    }


def test_ar4_discovery_returns_exactly_the_two_matching_candidates(tmp_path: Path) -> None:
    fx = _scan_fixture(tmp_path)
    from benchweave_sdk_server.serial import discover_serial_devices

    devices = asyncio.run(
        discover_serial_devices(fx["plugin"], hooks=fx["hooks"])
    )
    assert [row["id"] for row in devices] == ["example_device", "example_device"]
    assert all(row["transport"] == "serial" for row in devices)
    assert all(row["manufacturer"] == "SDK Example" for row in devices)
    # Only identify frames reached any port: one probe per opened candidate,
    # nothing else.
    all_written = [
        frame for port in fx["ports"].values() for frame in port.written
    ]
    assert all_written == [b"ID?\n", b"ID?\n", b"ID?\n", b"ID?\n"]
    assert fx["opened"] == ["/dev/match-a", "/dev/match-b", "/dev/foreign", "/dev/silent"], (
        "the wrong-VID candidate is hint-filtered and never opened"
    )


def test_rows_carry_the_endpoint_fields(tmp_path: Path) -> None:
    """Issue #385 §1.2: a discovery row names its PHYSICAL endpoint —
    ``port_path`` always, ``usb_serial`` when the candidate's descriptor
    carries an iSerial (None when it does not — an honest null, never a
    fabricated serial). Two identical boards were previously two
    indistinguishable rows the operator could not act on."""
    fx = _scan_fixture(tmp_path)
    from benchweave_sdk_server.serial import discover_serial_devices

    devices = asyncio.run(
        discover_serial_devices(fx["plugin"], hooks=fx["hooks"])
    )
    assert [row["port_path"] for row in devices] == ["/dev/match-a", "/dev/match-b"]
    assert [row["usb_serial"] for row in devices] == ["SER-A", "SER-B"]


def test_a_silent_or_foreign_port_is_omitted_not_reported(tmp_path: Path) -> None:
    fx = _scan_fixture(tmp_path)
    from benchweave_sdk_server.serial import discover_serial_devices

    devices = asyncio.run(discover_serial_devices(fx["plugin"], hooks=fx["hooks"]))
    assert len(devices) == 2, "an unconfirmed port is not a device"


def test_the_connected_sessions_port_is_served_without_reprobing(tmp_path: Path) -> None:
    fx = _scan_fixture(tmp_path)
    from benchweave_sdk_server.serial import discover_serial_devices

    identity = {
        "manufacturer": "SDK Example",
        "model": "demo",
        "serial": "SIM001",
        "firmware": "1.0.0",
        "source": "device",
    }
    devices = asyncio.run(
        discover_serial_devices(
            fx["plugin"],
            hooks=fx["hooks"],
            connected_device="/dev/match-a",
            connected_identity=identity,
        )
    )
    assert [row["id"] for row in devices].count("example_device") == 2
    assert fx["opened"].count("/dev/match-a") == 0, (
        "the connected port is never re-probed"
    )
    # §1.2: the connected row is served with the CONNECTED candidate's own
    # endpoint — the operator sees which physical row their session is on.
    assert devices[0]["port_path"] == "/dev/match-a"
    assert devices[0]["usb_serial"] == "SER-A"


def test_a_connected_era_row_with_a_mismatched_mint_serial_is_not_confirmed(
    tmp_path: Path,
) -> None:
    """Trust-2 (probe 3's class): the connected short-circuit row takes its
    serial from the LIVE enumeration — a re-occupied path (the connected
    unit left, a foreign unit took the path) would serve a chimera row (the
    session's established identity, the re-occupant's serial) that the
    bind-time serial-evidence check cannot catch, because both sides of ITS
    comparison read the foreign serial. The mint-time serial reconciles:
    known and mismatched, the row is skipped — the re-occupant is not a
    confirmed candidate."""
    fx = _scan_fixture(tmp_path)
    from benchweave_sdk_server.serial import SerialPortHooks, discover_serial_devices

    identity = {"manufacturer": "SDK Example", "model": "demo"}
    # The physical swap: the enumeration now carries a foreign serial at
    # the connected path.
    swapped = [CandidatePort("/dev/match-a", vid=0x1A86, pid=0x7523, serial_number="SER-X")]
    devices = asyncio.run(
        discover_serial_devices(
            fx["plugin"],
            hooks=SerialPortHooks(
                enumerate_ports=lambda: swapped, open_port=lambda d, s: fx["ports"][d]
            ),
            connected_device="/dev/match-a",
            connected_identity=identity,
            connected_serial="SER-A",
            connected_serial_known=True,
        )
    )
    assert devices == [], "the re-occupied path's row must not confirm"


def test_a_connected_era_row_reconciles_matching_and_null_mint_serials(
    tmp_path: Path,
) -> None:
    """The reconciliation's honest edges: a matching mint serial serves the
    row; a serial-less unit (mint None, live None) reconciles and serves;
    a mint-time None against a live serial is a MISMATCH (the occupant
    changed) and must not confirm."""
    fx = _scan_fixture(tmp_path)
    from benchweave_sdk_server.serial import SerialPortHooks, discover_serial_devices

    identity = {"manufacturer": "SDK Example", "model": "demo"}

    def _run(candidates: list[CandidatePort], minted: str | None) -> list[Any]:
        return asyncio.run(
            discover_serial_devices(
                fx["plugin"],
                hooks=SerialPortHooks(
                    enumerate_ports=lambda: list(candidates),
                    open_port=lambda d, s: fx["ports"][d],
                ),
                connected_device="/dev/match-a",
                connected_identity=identity,
                connected_serial=minted,
                connected_serial_known=True,
            )
        )

    same = [CandidatePort("/dev/match-a", vid=0x1A86, pid=0x7523, serial_number="SER-A")]
    assert [row["usb_serial"] for row in _run(same, "SER-A")] == ["SER-A"]
    serial_less = [CandidatePort("/dev/match-a", vid=0x1A86, pid=0x7523)]
    assert [row["usb_serial"] for row in _run(serial_less, None)] == [None]
    gained = [CandidatePort("/dev/match-a", vid=0x1A86, pid=0x7523, serial_number="NEW")]
    assert _run(gained, None) == [], "an occupant that GAINED a serial is a mismatch"


def test_an_unknown_mint_serial_serves_the_row_as_before(
    tmp_path: Path,
) -> None:
    """The pre-fold shape stays honest: an endpoint minted without an
    enumeration (direct test construction, the byte-compat form) has NO
    evidence — no reconciliation runs, the connected row serves exactly as
    the lineage shipped it."""
    fx = _scan_fixture(tmp_path)
    from benchweave_sdk_server.serial import SerialPortHooks, discover_serial_devices

    identity = {"manufacturer": "SDK Example", "model": "demo"}
    swapped = [CandidatePort("/dev/match-a", vid=0x1A86, pid=0x7523, serial_number="SER-X")]
    devices = asyncio.run(
        discover_serial_devices(
            fx["plugin"],
            hooks=SerialPortHooks(
                enumerate_ports=lambda: swapped, open_port=lambda d, s: fx["ports"][d]
            ),
            connected_device="/dev/match-a",
            connected_identity=identity,
        )
    )
    assert [row["usb_serial"] for row in devices] == ["SER-X"]


def test_a_candidate_without_a_usb_serial_serves_an_honest_null(tmp_path: Path) -> None:
    """A bridge whose device descriptor carries no iSerial (pyserial's
    ``serial_number`` is None) serves ``usb_serial: null`` — honest null,
    never a fabricated serial or an empty string."""
    project = tmp_path / "proj"
    from benchweave_sdk.scaffold import create_project
    from benchweave_sdk_server.serial import SerialPortHooks, discover_serial_devices

    create_project(project, "example_plugin")
    plugin = load_plugin_project(project)
    port = LoopbackPort(replies={b"ID?\n": _MATCHING})
    hooks = SerialPortHooks(
        enumerate_ports=lambda: [CandidatePort("/dev/no-serial", vid=0x1A86, pid=0x7523)],
        open_port=lambda device, settings: port,
    )
    devices = asyncio.run(discover_serial_devices(plugin, hooks=hooks))
    assert [row["usb_serial"] for row in devices] == [None]
    assert [row["port_path"] for row in devices] == ["/dev/no-serial"]


def test_the_mock_transports_row_is_an_honest_null_endpoint(seam) -> None:
    """The mock branch has no endpoint at all: its single row carries
    ``port_path``/``usb_serial`` null — the one row shape holds across
    transports (§1.2), and the nulls are honest, never a fake path."""
    devices = asyncio.run(seam.call("device_discover"))["devices"]
    # The row echoes the DESCRIPTOR's declared transport (the scaffold
    # declares serial) — the serving transport is host_info's business.
    assert devices == [
        {
            "id": "example_device",
            "manufacturer": "SDK Example",
            "model": "demo",
            "transport": "serial",
            "connection_key": "example_device",
            "port_path": None,
            "usb_serial": None,
        }
    ]


def _serial_app(tmp_path: Path) -> tuple[Any, ...]:
    """A serial-transport app over the AR-4 fixture (TestClient + policy)."""
    fx = _scan_fixture(tmp_path)
    from benchweave_sdk_server.serial import SerialEndpoint, serial_plugin_session
    from benchweave_sdk_server.web import build_app

    # The resolver form (issue #385): ONE endpoint object feeds both the
    # session factory and the seam — the connected short-circuit reads the
    # resolver's last_resolution, never a second source of truth.
    endpoint = SerialEndpoint("/dev/match-a")
    session = serial_plugin_session(fx["plugin"], endpoint)
    seam = StandaloneSeam(
        session,
        transport_kind="serial",
        serial_ports=fx["hooks"],
        serial_endpoint=endpoint,
    )
    policy = GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )
    app = build_app(seam, policy=policy)
    return app, policy, fx, seam


def _serial_app_with_hooks(tmp_path: Path, hooks: Any) -> tuple[Any, ...]:
    """A serial-transport app over the AR-4 fixture with EXPLICIT hooks
    (the fold's failure-injection seam)."""
    fx = _scan_fixture(tmp_path)
    from benchweave_sdk_server.serial import SerialEndpoint, serial_plugin_session
    from benchweave_sdk_server.web import build_app

    endpoint = SerialEndpoint("/dev/match-a")
    session = serial_plugin_session(fx["plugin"], endpoint)
    seam = StandaloneSeam(
        session,
        transport_kind="serial",
        serial_ports=hooks,
        serial_endpoint=endpoint,
    )
    policy = GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )
    app = build_app(seam, policy=policy)
    return app, policy, fx, seam


def test_a_failing_scan_renders_a_typed_refusal_not_a_500(tmp_path: Path) -> None:
    """FOLD-E: the serial scan's real failures (a missing pyserial, an
    enumerate error) raise RuntimeError/ValueError/OSError BEFORE any
    SeamError exists — the route caught SeamError only, so they escaped as
    raw 500s. A refused scan renders the typed scan-refused row and is
    never cached into the GET view."""
    from benchweave_sdk_server.serial import SerialPortHooks

    def _broken_enumerate() -> list[Any]:
        raise RuntimeError(
            "standalone_serial_pyserial_missing: install 'benchweave-sdk[server]' "
            "for serial transport support"
        )

    app, policy, fx, seam = _serial_app_with_hooks(
        tmp_path,
        SerialPortHooks(
            enumerate_ports=_broken_enumerate, open_port=lambda device, settings: None
        ),
    )
    with TestClient(
        app, base_url="http://127.0.0.1:8477", raise_server_exceptions=False
    ) as client:
        page = client.post("/discover", headers={"x-csrf-token": policy.csrf_token})
        assert page.status_code == 200, page.status_code
        assert "Scan refused" in page.text
        assert "standalone_serial_pyserial_missing" in page.text
        after = client.get("/")
        assert after.status_code == 200
        assert seam.discovery_cache is None, "the failure is not cached into the GET view"
        assert "example_device" not in after.text


def test_an_unparseable_usb_hint_refuses_loudly(tmp_path: Path) -> None:
    """FOLD-F: an unparseable declared vid/pid hint used to make every
    port mismatch silently (`_identity_int("zz") -> None`) — an empty
    discovery with zero diagnostics. The declaration is now a loud typed
    refusal naming the value: fail-closed as before, but VISIBLE."""
    project = tmp_path / "proj"
    from benchweave_sdk.scaffold import create_project
    from benchweave_sdk_server.serial import (
        SerialPortHooks,
        discover_serial_devices,
    )

    create_project(project, "example_plugin")
    descriptor_path = project / "src" / "example_plugin" / "descriptor.json"
    document = json.loads(descriptor_path.read_text())
    document["transport"]["settings"]["x-standalone-usb-vid"] = "zz"
    descriptor_path.write_text(json.dumps(document))
    plugin = load_plugin_project(project)
    hooks = SerialPortHooks(
        enumerate_ports=lambda: [], open_port=lambda device, settings: None
    )
    with pytest.raises(ValueError, match="zz"):
        asyncio.run(discover_serial_devices(plugin, hooks=hooks))


def test_ar4_get_root_never_transmits_and_the_scan_is_an_explicit_post(
    tmp_path: Path,
) -> None:
    app, policy, fx, seam = _serial_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8477") as client:
        before = [list(p.written) for p in fx["ports"].values()]
        page = client.get("/")
        assert page.status_code == 200
        after_get = [list(p.written) for p in fx["ports"].values()]
        assert after_get == before, "GET / transmitted nothing"
        assert "Scan for devices" in page.text
        scan = client.post(
            "/discover",
            headers={"x-csrf-token": policy.csrf_token},
            follow_redirects=False,
        )
        assert scan.status_code == 303
        after_scan = [list(p.written) for p in fx["ports"].values()]
        assert after_scan != before, "the explicit POST scanned"
        frames = [f for p in fx["ports"].values() for f in p.written]
        assert set(frames) == {b"ID?\n"}
        listed = client.get("/")
        assert listed.status_code == 200
        assert listed.text.count("example_device") >= 2, "the cache serves the scan"
        after_listed = [list(p.written) for p in fx["ports"].values()]
        assert after_listed == after_scan, "GET / after the scan still transmits nothing"
        assert seam.discovery_cache is not None and len(seam.discovery_cache) == 2


def test_usb_hint_filter_accepts_int_and_hex_string(tmp_path: Path) -> None:
    """The x- extension values: ints compare literally, strings parse as
    base-16 (USB ids are conventionally hex); a candidate lacking the id
    never matches."""
    from benchweave_sdk_server.serial import usb_identity_filter

    fx = _scan_fixture(tmp_path)
    assert usb_identity_filter(fx["plugin"]) == {"vid": "1a86", "pid": None}


def test_an_unmarked_adapter_is_omitted_with_a_diagnostic(
    tmp_path: Path, caplog: Any
) -> None:
    """Fold-refute 1: FOLD-D's marker enforcement made an adapter that
    transmits without the dispatch marker vanish from serial discovery
    — silently, through the confirm-by-identify swallow. The omission
    is correct (fail-closed, AR-4) but a developer's device disappearing
    with zero diagnostics is the silent-empty class FOLD-F fixed for
    hints: the omission now logs a warning naming the port and the
    conformance refusal."""
    import logging

    from benchweave_sdk.scaffold import create_project
    from benchweave_sdk_server.serial import SerialPortHooks, discover_serial_devices

    project = tmp_path / "proj"
    create_project(project, "example_plugin")
    descriptor_path = project / "src" / "example_plugin" / "descriptor.json"
    document = json.loads(descriptor_path.read_text())
    document["transport"]["settings"]["x-standalone-usb-vid"] = "1a86"
    descriptor_path.write_text(json.dumps(document))
    adapter_path = project / "src" / "example_plugin" / "adapter.py"
    text = adapter_path.read_text()
    assert "await context.mark_dispatch_started()" in text
    adapter_path.write_text(
        text.replace("            await context.mark_dispatch_started()\n", "")
    )
    plugin = load_plugin_project(project)

    port = LoopbackPort(replies={b"ID?\n": _MATCHING})
    opened: list[str] = []

    def open_port(device: str, settings: dict[str, Any]) -> Any:
        opened.append(device)
        return port

    hooks = SerialPortHooks(
        enumerate_ports=lambda: [CandidatePort("/dev/match-a", vid=0x1A86, pid=0x7523)],
        open_port=open_port,
    )
    with caplog.at_level(logging.WARNING, logger="benchweave_sdk_server.serial"):
        rows = asyncio.run(discover_serial_devices(plugin, hooks=hooks))
    assert rows == []  # omitted, as before — fail-closed
    assert any(
        "dispatch marker" in record.message
        and "/dev/match-a" in record.message
        for record in caplog.records
    ), [record.message for record in caplog.records]
