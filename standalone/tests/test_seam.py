"""The seam's refusal model and its adapter-envelope honesty (SW-10..13)."""

from __future__ import annotations

import pytest

from benchweave_standalone.errors import SeamError
from benchweave_standalone.seam import StandaloneSeam, sdk_version
from benchweave_standalone.session import PluginSession
from benchweave_standalone.transport import LoopingMockHost

DEV = {"device_id": "example_device"}

_IDENTIFY = (
    {
        "kind": "stream_exchange", "data": b"ID?\n", "max_bytes": 128,
        "termination": "lf", "exact_bytes": None,
    },
    {"data": b"SDK Example,demo,SIM001,1.0.0\n"},
)
_READ_TX = {
    "kind": "stream_exchange", "data": b"V?\n", "max_bytes": 128,
    "termination": "lf", "exact_bytes": None,
}


def call(seam: StandaloneSeam, operation: str, arguments: dict | None = None) -> dict:
    import asyncio

    return asyncio.run(seam.call(operation, arguments or {}))


def test_host_info_discloses_the_standalone_truth(seam) -> None:
    info = call(seam, "host_info")
    assert info["mode"] == "standalone"
    assert info["absent_guarantees"] == [
        "leases", "policy", "approvals", "procedures", "runs",
    ]
    assert info["served_operations"] == [
        "host_info", "device_discover", "device_connect", "device_disconnect",
        "device_get", "parameter_read",
    ]
    assert "capture_start" in info["deferred_operations"]
    assert info["plugin"]["package"] == "example_plugin"
    assert len(info["plugin"]["descriptor_sha256"]) == 64
    assert info["transport"] == "mock"
    assert info["sdk_version"] == sdk_version()
    assert info["sdk_version"]  # derived, never a literal


def test_discover_reports_exactly_one_device(seam) -> None:
    devices = call(seam, "device_discover")["devices"]
    assert len(devices) == 1
    assert devices[0]["manufacturer"] == "SDK Example"
    assert devices[0]["model"] == "demo"
    assert devices[0]["id"] == "example_device"


def test_unknown_operation_is_invalid_request(seam) -> None:
    with pytest.raises(SeamError) as caught:
        call(seam, "lease_create", {})
    assert caught.value.code == "invalid_request"
    assert caught.value.correlation_id


def test_deferred_operations_refuse_with_the_deferral_reason(seam) -> None:
    for name in ("parameter_stage", "capture_start", "events_get", "preset_apply"):
        with pytest.raises(SeamError) as caught:
            call(seam, name, {})
        assert caught.value.code == "unavailable"
        assert caught.value.details["reason"] == "increment_deferral"
        assert caught.value.correlation_id


def test_argument_validation_reports_findings(seam) -> None:
    with pytest.raises(SeamError) as caught:
        call(seam, "parameter_read", {"device_id": "example_device"})
    assert caught.value.code == "invalid_request"
    assert caught.value.details["findings"]


def test_unknown_device_is_not_found(seam) -> None:
    with pytest.raises(SeamError) as caught:
        call(seam, "device_get", {"device_id": "nope"})
    assert caught.value.code == "not_found"


def test_unknown_parameter_is_not_found(seam) -> None:
    call(seam, "device_connect", DEV)
    with pytest.raises(SeamError) as caught:
        call(seam, "parameter_read", {**DEV, "parameter": "current"})
    assert caught.value.code == "not_found"


def test_device_operations_require_connection(seam) -> None:
    with pytest.raises(SeamError) as caught:
        call(seam, "device_get", DEV)
    assert caught.value.code == "not_ready"
    with pytest.raises(SeamError) as caught:
        call(seam, "parameter_read", {**DEV, "parameter": "voltage"})
    assert caught.value.code == "not_ready"


def test_the_full_happy_path(seam) -> None:
    assert call(seam, "device_connect", DEV) == {
        "device_id": "example_device", "connected": True,
    }
    identity = call(seam, "device_get", DEV)
    assert identity["manufacturer"] == "SDK Example"
    assert identity["model"] == "demo"
    assert identity["serial"] == "SIM001"
    reading = call(seam, "parameter_read", {**DEV, "parameter": "voltage"})
    assert reading["value"] == 3.3
    assert reading["unit"] == "V"
    assert reading["quality"] == "valid"
    assert call(seam, "device_disconnect", DEV)["connected"] is False
    assert call(seam, "device_disconnect", DEV)["connected"] is False  # idempotent


def test_double_connect_is_a_conflict(seam) -> None:
    call(seam, "device_connect", DEV)
    with pytest.raises(SeamError) as caught:
        call(seam, "device_connect", DEV)
    assert caught.value.code == "conflict"


def test_twenty_sequential_reads(seam) -> None:
    call(seam, "device_connect", DEV)
    call(seam, "device_get", DEV)
    for _ in range(20):
        reading = call(seam, "parameter_read", {**DEV, "parameter": "voltage"})
        assert reading["value"] == 3.3


def test_exhausted_transport_fails_honestly_with_correlation(plugin) -> None:
    """The D(i) RED control at the seam: cycles=1, second read refused."""
    host = LoopingMockHost([_IDENTIFY, (_READ_TX, {"data": b"3.3\n"})], cycles=1)
    seam = StandaloneSeam(PluginSession(plugin, lambda: host), transport_kind="mock")
    call(seam, "device_connect", DEV)
    first = call(seam, "parameter_read", {**DEV, "parameter": "voltage"})
    assert first["value"] == 3.3
    with pytest.raises(SeamError) as caught:
        call(seam, "parameter_read", {**DEV, "parameter": "voltage"})
    assert caught.value.code == "unavailable"
    assert caught.value.correlation_id


def test_adapter_protocol_error_preserves_the_envelope(plugin) -> None:
    """A malformed device response stays distinct end to end (SW-12)."""
    host = LoopingMockHost(
        [
            _IDENTIFY,
            (_READ_TX, {"data": b"nan\n"}),
        ],
    )
    seam = StandaloneSeam(PluginSession(plugin, lambda: host), transport_kind="mock")
    call(seam, "device_connect", DEV)
    with pytest.raises(SeamError) as caught:
        call(seam, "parameter_read", {**DEV, "parameter": "voltage"})
    assert caught.value.code == "unavailable"
    adapter = caught.value.details["adapter"]
    assert adapter["code"] == "PROTOCOL_ERROR"
    assert adapter["dispatch_state"] == "unknown"


def test_adapter_timeout_maps_to_not_ready(plugin) -> None:
    host = LoopingMockHost(
        [
            _IDENTIFY,
            (_READ_TX, TimeoutError("scripted expiry")),
        ],
    )
    seam = StandaloneSeam(PluginSession(plugin, lambda: host), transport_kind="mock")
    call(seam, "device_connect", DEV)
    with pytest.raises(SeamError) as caught:
        call(seam, "parameter_read", {**DEV, "parameter": "voltage"})
    assert caught.value.code == "not_ready"
    assert caught.value.details["adapter"]["code"] == "TIMEOUT"


def test_adapter_transport_loss_maps_to_not_ready(plugin) -> None:
    """NFR-O2: transport loss is a not_ready on device operations."""
    host = LoopingMockHost(
        [
            _IDENTIFY,
            (_READ_TX, ConnectionError("scripted loss")),
        ],
    )
    seam = StandaloneSeam(PluginSession(plugin, lambda: host), transport_kind="mock")
    call(seam, "device_connect", DEV)
    with pytest.raises(SeamError) as caught:
        call(seam, "parameter_read", {**DEV, "parameter": "voltage"})
    assert caught.value.code == "not_ready"
    assert caught.value.details["adapter"]["code"] == "TRANSPORT_ERROR"


def test_reconnect_after_disconnect_lives(plugin) -> None:
    """M1 RED arm: a disconnect must not kill the session for the process
    lifetime — reconnect re-establishes and reads keep working."""
    from benchweave_standalone.session import mock_exchanges

    script = mock_exchanges(plugin)
    # The production shape: the factory mints a fresh scripted transport
    # per connection (LoopingMockHost deep-copies the script, so the list
    # is safely shared across connections).
    seam = StandaloneSeam(
        PluginSession(plugin, lambda: LoopingMockHost(script)), transport_kind="mock"
    )
    assert call(seam, "device_connect", DEV)["connected"] is True
    assert call(seam, "parameter_read", {**DEV, "parameter": "voltage"})["value"] == 3.3
    assert call(seam, "device_disconnect", DEV)["connected"] is False
    assert call(seam, "device_connect", DEV)["connected"] is True
    assert call(seam, "parameter_read", {**DEV, "parameter": "voltage"})["value"] == 3.3
    assert call(seam, "parameter_read", {**DEV, "parameter": "voltage"})["value"] == 3.3
