"""The CLI's serial device wiring (issue #389): ``_build_seam`` is the only
place ``--device`` can reach the seam, and before this fix it never did —
the no-re-probe clause (the I3 record §3.3: a candidate equal to the
connected session's port is served from the session's established identity
without re-probing) held only in tests that constructed the seam by hand.
Every arm here goes THROUGH the factory, so the wiring cannot regress the
way it once shipped: the serial seam must carry the device path, a scan
through it must serve the connected port from session identity without
re-opening it, and the mock and scenario branches must stay free of serial
wiring (transport selection stays the factory's whole expression).
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk_server.cli import _build_seam
from benchweave_sdk_server.serial import SerialPortHooks


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


class Candidate:
    """A list_ports-shaped candidate: with no USB identity hint declared,
    the device name is the only field discovery reads."""

    def __init__(self, device: str) -> None:
        self.device = device


_MATCHING = b"SDK Example,demo,SIM001,1.0.0\n"
_CONNECTED = "/dev/match-a"
_OTHER = "/dev/match-b"


def _wired_seam(starter_project: Path) -> tuple[Any, list[str]]:
    """A serial seam built THROUGH the CLI factory over injected ports.

    The session's opener and the discovery hooks share one ``opened`` log —
    the production shape, where both axes would open the same physical
    device. The hooks axis is this double's own injection (``_build_seam``
    owns the DEVICE wiring, not enumeration); the device path under test
    rides the factory alone, never the test's hand.
    """
    ports = {
        _CONNECTED: LoopbackPort(replies={b"ID?\n": _MATCHING}),
        _OTHER: LoopbackPort(replies={b"ID?\n": _MATCHING}),
    }
    opened: list[str] = []

    def open_port(device: str, settings: dict[str, Any]) -> LoopbackPort:
        opened.append(device)
        return ports[device]

    seam, selection = _build_seam(
        starter_project,
        transport="serial",
        device=_CONNECTED,
        open_port=open_port,
    )
    assert selection is None
    seam._serial_ports = SerialPortHooks(
        enumerate_ports=lambda: [Candidate(_CONNECTED), Candidate(_OTHER)],
        open_port=open_port,
    )
    return seam, opened


def test_the_cli_serial_seam_carries_the_device_path(starter_project: Path) -> None:
    """The wiring itself (issue #385's resolver form): ``serve --transport
    serial --device PATH`` hands the seam the SAME endpoint object the
    session factory consults — resolve it and you get the path, or the
    scan's connected short-circuit never fires in production (issue #389:
    pre-fix the seam carried no path at all; only hand-built test seams
    ever set it)."""
    seam, _ = _wired_seam(starter_project)
    assert seam._serial_endpoint is not None
    assert seam._serial_endpoint() == _CONNECTED
    assert seam._serial_endpoint.last_resolution is None, (
        "nothing has connected; the resolution is unset, not fabricated"
    )


def test_a_scan_through_the_cli_seam_never_reopens_the_connected_port(
    starter_project: Path,
) -> None:
    """The production effect, end to end through the factory: after the
    session connects (the port's FIRST open), a scan serves the connected
    port from the session's established identity — the port is never
    opened a second time, and the other candidate still probes. Pre-fix
    the scan re-opened the live port and raced the session for its bytes
    (the Windows failure: the second open fails and the connected device
    vanishes from the scan)."""
    seam, opened = _wired_seam(starter_project)

    async def scenario() -> dict[str, Any]:
        await seam.session.connect()
        assert seam.session.connected
        assert seam.session.identity is not None, "connect establishes identity"
        try:
            return await seam.call("device_discover")
        finally:
            await seam.session.close()

    result = asyncio.run(scenario())
    assert opened == [_CONNECTED, _OTHER], (
        "the connected port is opened exactly once (the session's own "
        "connect); the scan serves it from session identity and probes "
        "only the other candidate"
    )
    devices = result["devices"]
    assert [row["id"] for row in devices] == ["example_device", "example_device"]
    assert all(row["manufacturer"] == "SDK Example" for row in devices), (
        "the served row carries the session's identity, not a re-probe's"
    )


def test_the_mock_and_scenario_branches_carry_no_serial_wiring(
    starter_project: Path,
) -> None:
    """The fix touches one branch: the plain mock and the scenario seam
    both stay mock-kind with no device path — transport selection stays
    the factory's whole expression."""
    plain, plain_selection = _build_seam(starter_project)
    assert plain.transport_kind == "mock"
    assert plain_selection is None
    assert plain._serial_endpoint is None
    scenario_seam, selection = _build_seam(starter_project, scenario="stale")
    assert scenario_seam.transport_kind == "mock"
    assert selection is not None and selection.current == "stale"
    assert scenario_seam._serial_endpoint is None


def test_serial_without_a_device_refuses(starter_project: Path, capsys) -> None:
    """The serial branch's own guard, previously pinned nowhere: no
    ``--device`` (absent or empty) refuses with the prefixed message."""
    with pytest.raises(SystemExit) as exc:
        _build_seam(starter_project, transport="serial")
    assert exc.value.code == 2
    assert "standalone_transport_serial_device_required:" in capsys.readouterr().err


def test_a_device_on_the_mock_transport_refuses(starter_project: Path, capsys) -> None:
    """The sibling guard, previously pinned nowhere: ``--device`` applies
    only to ``--transport serial``."""
    with pytest.raises(SystemExit) as exc:
        _build_seam(starter_project, device="/dev/nowhere")
    assert exc.value.code == 2
    assert "standalone_transport_device_serial_only:" in capsys.readouterr().err
