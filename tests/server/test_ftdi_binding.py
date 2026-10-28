"""Row a (issue #568, the owner expansion): the ftdi transport's endpoint
lifecycle — discovery, the operator pick, and the persisted binding — the
serial lane's shape one transport over, on the SAME BindingStore and
endpoint model. The design record's "no binding store, no discovery"
posture is superseded by the owner ruling of 2026-10-28; the record says
so.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk_server.binding import BindingStore, resolve_endpoint
from benchweave_sdk_server.cli import _build_seam
from benchweave_sdk_server.errors import SeamError
from benchweave_sdk_server.ftdi import (
    FtdiDeviceHooks,
    FtdiEndpoint,
    ScriptedFtdiDriver,
    discover_ftdi_devices,
)
from benchweave_sdk_server.session import load_plugin_project

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "ftdi_control_plugin"
_URL = "ftdi://::0x0403:0x6001/1"
_URL_OTHER = "ftdi://::0x0403:0x6001/2"


def _hooks(open_log: list[str] | None = None) -> FtdiDeviceHooks:
    """The injected hooks: enumerate two URLs; open returns a scripted
    double over the fixture's bring-up (identify confirms), recording the
    opens."""

    def open_url(url: str) -> ScriptedFtdiDriver:
        if open_log is not None:
            open_log.append(url)
        rows = json.loads(
            (FIXTURE_ROOT / "src" / "ftdi_control_demo" / "vectors.json").read_text()
        )["exchanges"][:8]
        return ScriptedFtdiDriver(rows)

    return FtdiDeviceHooks(
        enumerate_urls=lambda: [_URL, _URL_OTHER], open_url=open_url
    )


def _ftdi_binding_row(url: str) -> dict[str, Any]:
    return {
        "connection_key": "ftdi_demo",
        "plugin_package": "ftdi_control_demo",
        "transport": "ftdi",
        "endpoint_kind": "ftdi_url",
        "usb_serial": None,
        "vid": None,
        "pid": None,
        "port_path": None,
        "ftdi_url": url,
        "identity": {
            "manufacturer": "OTDP Reference",
            "model": "ftdi-control-demo",
            "firmware": None,
        },
        "bound_at": "2026-10-28T00:00:00Z",
        "bound_via": "test",
    }


# --------------------------------------------------------------------------
# The binding model
# --------------------------------------------------------------------------


def test_an_ftdi_url_row_round_trips_and_resolves() -> None:
    """The closed row shape admits ftdi_url rows (the URL is the endpoint
    identity; every other endpoint field null) and resolution serves the
    stored URL while a fresh enumeration lists it."""
    row = _ftdi_binding_row(_URL)
    assert resolve_endpoint(row, lambda: [], enumerate_urls=lambda: [_URL]) == _URL


def test_a_stale_ftdi_url_row_refuses() -> None:
    """The URL absent from a fresh enumeration is staleness — the
    port_path posture one transport over; never a guess."""
    row = _ftdi_binding_row(_URL)
    with pytest.raises(Exception, match="stale"):
        resolve_endpoint(row, lambda: [], enumerate_urls=lambda: [_URL_OTHER])


def test_a_foreign_url_row_refuses_the_schema(tmp_path: Path) -> None:
    """The URL pattern is the pyftdi selector spelling — a non-URL string
    refuses the document at load."""
    row = _ftdi_binding_row("not-a-url")
    store = BindingStore.open(tmp_path / "device-bindings.json")
    with pytest.raises(ValueError, match="standalone_binding_schema"):
        store.bind(row)


# --------------------------------------------------------------------------
# The endpoint and discovery
# --------------------------------------------------------------------------


def test_the_endpoint_resolves_at_connect_time_and_records() -> None:
    """FtdiEndpoint is late-bound (a rebind redirects the next connection)
    and records the last resolution — the seam's connected short-circuit
    reads that fact."""
    calls: list[str] = []

    def source() -> str:
        calls.append("resolved")
        return _URL

    endpoint = FtdiEndpoint(source)
    assert endpoint() == _URL
    assert len(calls) == 1
    # last_resolution is set by the session factory after a successful
    # open (pinned end to end by the stored-binding arm below).
    assert endpoint.last_resolution is None


def test_discovery_confirms_by_identify_over_the_double() -> None:
    """discover_ftdi_devices enumerates the hooks' URLs, confirms each by
    its identify answer (manufacturer and model against the descriptor),
    and returns one row shape across transports (the URL rides the
    port_path slot — the endpoint string slot)."""
    plugin = load_plugin_project(FIXTURE_ROOT)
    devices = asyncio.run(discover_ftdi_devices(plugin, hooks=_hooks()))
    assert [row["port_path"] for row in devices] == [_URL, _URL_OTHER]
    assert all(row["manufacturer"] == "OTDP Reference" for row in devices)


def test_discovery_serves_the_connected_url_from_identity() -> None:
    """The connected short-circuit: the session's URL is served from its
    established identity without re-probing (NFR-O3's sibling)."""
    plugin = load_plugin_project(FIXTURE_ROOT)
    devices = asyncio.run(
        discover_ftdi_devices(
            plugin,
            hooks=_hooks(),
            connected_url=_URL,
            connected_identity={
                "manufacturer": "OTDP Reference",
                "model": "ftdi-control-demo",
            },
        )
    )
    assert [row["port_path"] for row in devices] == [_URL, _URL_OTHER]


# --------------------------------------------------------------------------
# The serve lifecycle through the CLI factory
# --------------------------------------------------------------------------


def test_serve_without_device_starts_binding_pending(
    tmp_path: Path, monkeypatch
) -> None:
    """F-385-2's shape on ftdi: no --device serves BINDING-PENDING; the
    connect refuses not_ready with reason binding_absent so the UI can
    render the pick."""
    monkeypatch.setenv(
        "BENCHWEAVE_STANDALONE_BINDINGS", str(tmp_path / "device-bindings.json")
    )
    seam, _ = _build_seam(FIXTURE_ROOT, transport="ftdi")
    assert seam.transport_kind == "ftdi"
    assert seam.binding_row is None

    async def scenario() -> None:
        with pytest.raises(SeamError) as caught:
            await seam.call("device_connect", {"device_id": "ftdi_demo"})
        assert caught.value.code == "not_ready"
        assert caught.value.details["reason"] == "binding_absent"

    asyncio.run(scenario())


def test_a_stored_binding_connects_without_the_device_flag(
    tmp_path: Path, monkeypatch
) -> None:
    """The whole point of the store: a binding written by a previous run
    makes a fresh serve — no --device — connect straight to the bound
    URL, and the endpoint records its last resolution."""
    store_path = tmp_path / "device-bindings.json"
    store = BindingStore.open(store_path)
    store.bind(_ftdi_binding_row(_URL))
    monkeypatch.setenv("BENCHWEAVE_STANDALONE_BINDINGS", str(store_path))
    all_rows = json.loads(
        (FIXTURE_ROOT / "src" / "ftdi_control_demo" / "vectors.json").read_text()
    )["exchanges"]
    opened: list[str] = []

    def open_url(url: str) -> ScriptedFtdiDriver:
        opened.append(url)
        return ScriptedFtdiDriver(all_rows)

    hooks = FtdiDeviceHooks(
        enumerate_urls=lambda: [_URL], open_url=open_url
    )
    seam, _ = _build_seam(FIXTURE_ROOT, transport="ftdi", driver_hooks=hooks)

    async def scenario() -> None:
        await seam.call("device_connect", {"device_id": "ftdi_demo"})
        read = await seam.call(
            "parameter_read",
            {"device_id": "ftdi_demo", "parameter": "line_status"},
        )
        assert read["value"] == 0x5A, read

    asyncio.run(scenario())
    assert opened == [_URL], "the stored binding resolved the connect"
    assert seam._ftdi_endpoint.last_resolution == _URL


def test_the_seam_scan_serves_the_ftdi_discovery(tmp_path: Path) -> None:
    """device_discover on the ftdi transport runs the confirm-by-identify
    scan (the ONLY transmissions are the identify exchanges) and caches
    the result — GET serves the cache, never a live scan."""
    from benchweave_sdk_server.ftdi import FtdiDeviceHooks, ScriptedFtdiDriver

    rows = json.loads(
        (FIXTURE_ROOT / "src" / "ftdi_control_demo" / "vectors.json").read_text()
    )["exchanges"][:8]
    seam, _ = _build_seam(
        FIXTURE_ROOT,
        transport="ftdi",
        driver_hooks=FtdiDeviceHooks(
            enumerate_urls=lambda: [_URL],
            open_url=lambda url: ScriptedFtdiDriver(rows),
        ),
    )
    result = asyncio.run(seam.call("device_discover"))
    devices = result["devices"]
    assert [row["port_path"] for row in devices] == [_URL]
    assert seam.discovery_cache is not None and len(seam.discovery_cache) == 1
