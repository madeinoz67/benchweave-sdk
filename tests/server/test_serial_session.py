"""serial_plugin_session and the serial CLI surface (issue #285 I3a).

A serial session mints a FRESH link+services per connection (the M1 fold's
per-connection precedent); the port opener is injectable so tests never
touch pyserial. The CLI's ``serve --transport serial --device <path>`` is
validated at the argument level here; the connected flow runs through
`_build_seam` directly.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from benchweave_sdk_server.cli import cli
from benchweave_sdk_server.serial import (
    SerialCaptureServices,
    SerialLink,
    serial_plugin_session,
)
from benchweave_sdk_server.session import PluginSession, load_plugin_project


class LoopbackPort:
    """The in-process pyserial-shaped double (per-file test double, as the
    rest of the serial suite carries its own)."""

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
        self.settings: tuple[str, dict[str, Any]] | None = None
        self.read_timeout = read_timeout
        self._data = threading.Event()
        self._fail_read: Exception | None = None

    def write(self, data: bytes) -> int | None:
        self.written.append(bytes(data))
        reply = self.replies.get(bytes(data))
        if reply is not None:
            self.inbound += reply
            self._data.set()
        return len(data)

    def read(self, size: int = 1) -> bytes:
        self.reads += 1
        if self._fail_read is not None:
            error, self._fail_read = self._fail_read, None
            raise error
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


def _open_port_recorder(ports: dict[str, LoopbackPort]):
    """An injected opener: serves loopbacks by device path, recording the
    settings each open received."""

    def _open(device: str, settings: dict[str, Any]) -> LoopbackPort:
        port = LoopbackPort(replies={
            b"ID?\n": b"SDK Example,demo,SIM001,1.0.0\n",
            b"V?\n": b"3.3\n",
        })
        port.settings = (device, settings)
        ports[device] = port
        return port

    return _open


def test_the_serial_factory_mints_a_fresh_services_per_connection(
    starter_project,  # noqa: ARG001 - ensures the scaffolded plugin exists
) -> None:
    plugin = load_plugin_project(starter_project)
    ports: dict[str, LoopbackPort] = {}
    session = serial_plugin_session(plugin, "/dev/fake0", open_port=_open_port_recorder(ports))
    assert isinstance(session, PluginSession)
    first = session._services_factory()
    second = session._services_factory()
    assert first is not second
    assert isinstance(first, SerialCaptureServices)
    assert isinstance(first.link, SerialLink)
    assert first.link is not second.link
    device, settings = ports["/dev/fake0"].settings
    assert device == "/dev/fake0"
    assert settings["baud"] == 115200 and settings["max_frame_bytes"] == 128


def test_connect_establishes_identity_over_the_loopback(starter_project) -> None:
    plugin = load_plugin_project(starter_project)
    ports: dict[str, LoopbackPort] = {}
    session = serial_plugin_session(plugin, "/dev/fake0", open_port=_open_port_recorder(ports))
    asyncio.run(session.connect())
    try:
        assert session.connected and session.identity is not None
        assert session.identity["serial"] == "SIM001"
        envelope = asyncio.run(session.execute("read", {"parameter": "voltage"}))
        assert envelope["status"] == "ok" and envelope["data"]["value"] == pytest.approx(3.3)
    finally:
        asyncio.run(session.close())
    assert ports["/dev/fake0"].closes == 1


def test_cli_transport_serial_requires_device(starter_project: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["serve", str(starter_project), "--transport", "serial", "--no-open"]
    )
    assert result.exit_code == 2
    assert "--device" in result.output


def test_cli_transport_serial_refuses_an_empty_device(
    starter_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fold-refute 2: ``--device ""`` is a missing device, not a path —
    the guard must refuse it at boot, not pass it to pyserial at
    connect (the ``is None`` check let the empty string through)."""
    import benchweave_sdk_server.serial as serial_module

    def _no_session(*args: object, **kwargs: object) -> None:
        raise AssertionError("the guard must fire before the session builds")

    monkeypatch.setattr(serial_module, "serial_plugin_session", _no_session)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["serve", str(starter_project), "--transport", "serial", "--device", "", "--no-open"],
    )
    assert result.exit_code == 2
    assert "--device" in result.output


def test_cli_device_with_mock_is_refused(starter_project: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["serve", str(starter_project), "--device", "/dev/fake0", "--no-open"]
    )
    assert result.exit_code == 2
    assert "--transport serial" in result.output


def test_cli_serial_choice_is_served(starter_project: Path) -> None:
    """The choice widened from ["mock"]; an unknown transport still refuses."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["serve", str(starter_project), "--transport", "canbus", "--no-open"]
    )
    assert result.exit_code == 2
    assert "mock" in result.output and "serial" in result.output


def test_build_seam_serial_constructs_the_real_serial_host(starter_project) -> None:
    """The wiring test must DISCRIMINATE the real host from the mock: a
    ``transport_kind`` assertion alone passes against a seam that serves
    the MOCK over a "serial" label (the fold's finding). The injected
    opener must be the seam's transport source (the factory builds through
    it), the factory's product must be the serial services, and the mode
    banner must follow the transport kind (simulated iff mock)."""
    from benchweave_sdk_server.cli import _build_seam
    from benchweave_sdk_server.presentation import mode_banner_html

    ports: dict[str, LoopbackPort] = {}
    seam, selection = _build_seam(
        starter_project,
        transport="serial",
        device="/dev/fake0",
        open_port=_open_port_recorder(ports),
    )
    assert seam.transport_kind == "serial"
    assert selection is None
    services = seam.session._services_factory()
    assert isinstance(services, SerialCaptureServices), (
        "the serial transport must serve the real serial host, never the mock"
    )
    assert "/dev/fake0" in ports, "the injected opener built the transport"
    serial_banner = mode_banner_html(simulated=seam.transport_kind == "mock")
    assert "SIMULATED PRESENTATION DATA" not in serial_banner
    mock_seam, _ = _build_seam(starter_project, transport="mock")
    mock_banner = mode_banner_html(simulated=mock_seam.transport_kind == "mock")
    assert "SIMULATED PRESENTATION DATA" in mock_banner
