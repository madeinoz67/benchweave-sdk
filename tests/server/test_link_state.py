# author: Stephen Eaton
"""Link-state cells for the standalone host surfaces (issue #407).

The R8 family: ``host_info`` and ``device_get`` carry the live link block
(``baud``/``boot_baud``/``negotiable``) when the host serves serial, null
on every other transport, and the seam bus carries the ``link`` event
family -- every surface (REST, SSE, MCP) serves one bus by construction
(events.py), so no web.py/mcp.py work rides.

All cells assert observed state; no cell asserts a wall-clock difference.
The harness rides the CLI factory (``_build_seam``) with an injected
opener (the test_cli_serial_wiring shape) so the wiring itself is under
test.
"""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk_server.cli import _build_seam
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.serial import serial_plugin_session
from benchweave_sdk_server.session import (
    HostOperationContext,
    LoadedPlugin,
    load_plugin_project,
)

_BOOT_BAUD = 115200
_TARGET = 3_000_000


class _SerialPort:
    """The in-process pyserial-shaped double; one port per OPEN."""

    def __init__(self, replies: dict[bytes, bytes]) -> None:
        import threading

        self.replies = dict(replies)
        self.inbound = bytearray()
        self.written: list[bytes] = []
        self.reads = 0
        self.closes = 0
        self.settings: dict[str, Any] | None = None
        self._data = threading.Event()
        self._lock = threading.Lock()

    def write(self, data: bytes) -> int | None:
        self.written.append(bytes(data))
        reply = self.replies.get(bytes(data))
        if reply is not None:
            with self._lock:
                self.inbound += reply
            self._data.set()
        return len(data)

    def read(self, size: int = 1) -> bytes:

        self.reads += 1
        while not self.inbound:
            if not self._data.wait(0.05):
                return b""
            self._data.clear()
        with self._lock:
            out = bytes(self.inbound[:size])
            del self.inbound[:size]
        return out

    def close(self) -> None:
        self.closes += 1
        self._data.set()


class _Opener:
    """Serves fresh ports per open by device path; records every open."""

    def __init__(self) -> None:
        self.opens: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, device: str, settings: dict[str, Any]) -> _SerialPort:
        self.opens.append((device, dict(settings)))
        return _SerialPort(replies={b"ID?\n": b"SDK Example,demo,SIM001,1.0.0\n"})


_IDENTIFY_TIMEOUT = {b"ID?\n": b"SDK Example,demo,SIM001,1.0.0\n"}


def _patched_plugin(project: Path, declared_bauds: list[int]) -> LoadedPlugin:
    """The scaffolded plugin with ``x-negotiated-bauds`` declared under
    ``transport.settings`` (the schema-legal ``x-`` lane)."""
    plugin = load_plugin_project(project)
    descriptor = copy.deepcopy(plugin.descriptor)
    settings = descriptor.setdefault("transport", {}).setdefault("settings", {})
    settings["x-negotiated-bauds"] = declared_bauds
    return LoadedPlugin(
        project_root=plugin.project_root,
        package=plugin.package,
        descriptor=descriptor,
        descriptor_sha256=plugin.descriptor_sha256,
        plugin_version=plugin.plugin_version,
        adapter_factory=plugin.adapter_factory,
        has_presentation=plugin.has_presentation,
        load_diagnostic=plugin.load_diagnostic,
    )


def _serial_seam(
    project: Path, *, declared_bauds: list[int] | None = None
) -> tuple[StandaloneSeam, _Opener]:
    """A serial seam through ``serial_plugin_session`` (the factory wiring)
    with the injected opener; the declared-bauds arm patches the
    descriptor (the x- lane rides settings, not project files)."""
    opener = _Opener()
    if declared_bauds is None:
        loaded = load_plugin_project(project)
    else:
        loaded = _patched_plugin(project, declared_bauds)
    session = serial_plugin_session(loaded, "/dev/fake0", open_port=opener)
    seam = StandaloneSeam(session, transport_kind="serial")
    return seam, opener


async def _connect(seam: StandaloneSeam) -> None:
    await seam.session.connect()
    assert seam.session.connected


def test_l1_host_info_link_block_is_null_then_boot_then_switched(
    starter_project,
) -> None:
    """L1 (R8): ``host_info["link"]`` is null before a connection, names
    the boot state after connect, and reflects the switched state after a
    real ``reconfigure_link`` through the session's services."""
    seam, opener = _serial_seam(starter_project, declared_bauds=[_TARGET])

    async def scenario() -> dict[str, Any]:
        info_before = await seam.call("host_info")
        await _connect(seam)
        info_boot = await seam.call("host_info")
        context = HostOperationContext("cell-link-state", timeout_ms=5000)
        applied = await seam.session.services.reconfigure_link(
            {"baud": _TARGET}, context
        )
        assert applied["baud"] == _TARGET
        info_switched = await seam.call("host_info")
        return {"before": info_before, "boot": info_boot, "switched": info_switched}

    states = asyncio.run(scenario())
    assert states["before"]["link"] is None
    assert states["boot"]["link"] == {
        "baud": _BOOT_BAUD,
        "boot_baud": _BOOT_BAUD,
        "negotiable": True,
    }
    assert states["switched"]["link"] == {
        "baud": _TARGET,
        "boot_baud": _BOOT_BAUD,
        "negotiable": True,
    }
    assert len(opener.opens) == 2, "boot open + the one reopen"

def test_l2_device_get_overlays_the_link_block_additively(starter_project) -> None:
    """L2 (R8, F3): ``device_get`` serves the established identity plus the
    link block — additive: every identity key survives, the link block
    rides beside them."""
    seam, _opener = _serial_seam(starter_project, declared_bauds=[_TARGET])

    async def scenario() -> dict[str, Any]:
        await _connect(seam)
        return await seam.call(
            "device_get", {"device_id": seam.session.device_id}
        )

    result = asyncio.run(scenario())
    identity = dict(seam.session.identity or {})
    assert identity, "the connect established an identity"
    for key, value in identity.items():
        assert result.get(key) == value, f"identity key {key} survives the overlay"
    assert result["link"] == {
        "baud": _BOOT_BAUD,
        "boot_baud": _BOOT_BAUD,
        "negotiable": True,
    }


def test_l3_link_events_ride_the_seam_bus(starter_project) -> None:
    """L3 (R7/R8): the seam bus carries the ``link`` family — an applied
    switch publishes one row, a refused switch another — and no other
    family claims the kind."""
    seam, _opener = _serial_seam(starter_project, declared_bauds=[_TARGET])
    cursor_before = seam.events.last_id()

    async def scenario() -> None:
        await _connect(seam)
        context = HostOperationContext("cell-link-events", timeout_ms=5000)
        await seam.session.services.reconfigure_link({"baud": _TARGET}, context)
        with pytest.raises(ValueError, match="standalone_serial_baud_not_negotiable"):
            await seam.session.services.reconfigure_link({"baud": 9600}, context)

    asyncio.run(scenario())
    rows = seam.events.after(cursor_before)
    link_rows = [row for row in rows if row["kind"] == "link"]
    assert [row["data"]["event"] for row in link_rows] == [
        "reconfigured",
        "reconfigure_refused",
    ], "the bus carries the applied and refused rows in order"
    for row in link_rows:
        assert row["data"]["operation_id"] == "cell-link-events"
        assert row["data"]["from_baud"] in (_BOOT_BAUD, _TARGET)
    assert all(row["kind"] != "refused" for row in link_rows), (
        "a link refusal is not a seam-exit refusal; the families stay distinct"
    )


def test_l4_the_mock_transport_carries_link_null(starter_project) -> None:
    """L4 (R8): on the mock transport the link block is null on both
    surfaces — the capability is invisible where no link exists."""
    seam, _selection = _build_seam(starter_project, transport="mock")

    async def scenario() -> tuple[dict[str, Any], dict[str, Any]]:
        info = await seam.call("host_info")
        await seam.session.connect()
        device = await seam.call("device_get", {"device_id": seam.session.device_id})
        return info, device

    info, device = asyncio.run(scenario())
    assert info["link"] is None
    assert device["link"] is None
