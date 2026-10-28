import asyncio
import base64
import json
from importlib.resources import files
from pathlib import Path
import pytest
from benchweave_sdk.validation import validate_descriptor, verify_provider_pin
from benchweave_sdk_server.ftdi import ScriptedFtdiDriver, ftdi_plugin_session
from benchweave_sdk_server.session import load_plugin_project
from example_plugin.adapter import create_plugin
from example_plugin import protocol as proto


def _script():
    """The bring-up conversation as a double script (the #564 row shape),
    spelled from this package's own protocol builders. The recorded-evidence
    story is the replay journal a bench session records with --record; this
    script is a rehearsal smoke, not evidence (it claims nothing)."""
    return [
        {"name": "reset", "transaction": proto.reset_device(), "response": {}},
        {"name": "purge", "transaction": proto.purge_rx(), "response": {}},
        {"name": "latency", "transaction": proto.set_latency(), "response": {}},
        {"name": "baud", "transaction": proto.set_baud(), "response": {}},
        {"name": "bitmode", "transaction": proto.set_bitmode(), "response": {}},
        {"name": "pins-idle", "transaction": proto.read_pins(),
         "response": {"data": base64.b64encode(bytes([proto.PINS_IDLE])).decode()}},
        {"name": "bitstream", "transaction": proto.stream_send(proto.BITSTREAM_CHUNK),
         "response": {}},
        {"name": "pins-done", "transaction": proto.read_pins(),
         "response": {"data": base64.b64encode(bytes([proto.DONE_BYTE])).decode()}},
        {"name": "status", "transaction": proto.status_exchange(),
         "response": {"data": proto.STATUS_REPLY.hex()}},
    ]


def test_descriptor_pin_and_contract():
    descriptor = json.loads(files("example_plugin").joinpath("descriptor.json").read_text())
    validate_descriptor(descriptor)
    pinned = verify_provider_pin(
        descriptor, Path(str(files("example_plugin").joinpath("descriptor.json")))
    )
    assert pinned is not None
    assert pinned["feature_id"].startswith("otdp.transport.ftdi-control/")


def test_bring_up_rehearses_on_the_shipped_double(tmp_path):
    async def run():
        project = Path(__file__).resolve().parents[1]
        plugin = load_plugin_project(project)
        driver = ScriptedFtdiDriver(_script())
        session = ftdi_plugin_session(
            plugin, "ftdi://::0x0403:0x6001/1", driver_factory=lambda url: driver,
            capture_root=tmp_path / "caps",
        )
        await session.connect()
        read = await session.execute("read", {"parameter": "line_status"})
        assert read["status"] == "ok"
        assert read["data"]["value"] == 0x5A
        await session.close()
    asyncio.run(run())


def test_no_transmit_before_dispatch(tmp_path):
    async def run():
        project = Path(__file__).resolve().parents[1]
        plugin = load_plugin_project(project)
        driver = ScriptedFtdiDriver(_script())
        session = ftdi_plugin_session(
            plugin, "ftdi://::0x0403:0x6001/1", driver_factory=lambda url: driver,
            capture_root=tmp_path / "caps",
        )
        await session.connect()
        calls_before = list(driver.calls)
        handle = create_plugin()
        from benchweave_sdk.testing import MockContext
        context = MockContext("op", deadline_monotonic=1.0)
        await handle.open({}, type("Dead", (), {
            "monotonic": lambda self: 0.0,
            "transfer": lambda self, t, c: (_ for _ in ()).throw(AssertionError("transmitted")),
            "close_transport": lambda self, c: None,
        })(), context)
        request = {"operation_id": "op", "verb": "read",
                   "arguments": {"parameter": "line_status"}}
        context.cancel()
        result = await handle.execute(request, context)
        assert result["status"] == "error"
        assert result["error"]["dispatch_state"] == "not_dispatched"
        assert driver.calls == calls_before
        await session.close()
    asyncio.run(run())


def test_uncertain_response_after_dispatch(tmp_path):
    async def run():
        project = Path(__file__).resolve().parents[1]
        plugin = load_plugin_project(project)
        rows = _script()
        rows[-1]["response"] = {"data": "c200"}  # a partial reply: the exchange times out
        driver = ScriptedFtdiDriver(rows)
        session = ftdi_plugin_session(
            plugin, "ftdi://::0x0403:0x6001/1", driver_factory=lambda url: driver,
            capture_root=tmp_path / "caps",
        )
        await session.connect()
        read = await session.execute("read", {"parameter": "line_status"})
        assert read["status"] == "unknown"
        assert read["error"]["dispatch_state"] == "unknown"
        await session.close()
    asyncio.run(run())


def test_wire_counter_refuses_a_gap():
    """The wire helpers (issue #566): one counter sequences reads and
    writes; a gap is a refusal naming the expected and observed counter
    and the exchange index."""
    from example_plugin.wire import (
        CommandCounter, CounterGapError, EVIDENCE_COMMAND_COUNTER_GAP)
    tracker = CommandCounter(modulus=256)
    recorded = []

    async def record(entry):
        recorded.append(entry)

    async def run():
        await tracker.advance(0x10)
        await tracker.advance(0x11)

    asyncio.run(run())

    async def gap():
        await tracker.advance(0x14, record=record)

    with pytest.raises(CounterGapError,
                       match=r"exchange 2.*expected 0x12.*observed 0x14"):
        asyncio.run(gap())
    assert recorded[0]["kind"] is EVIDENCE_COMMAND_COUNTER_GAP
