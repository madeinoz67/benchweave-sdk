import asyncio
import json
from importlib.resources import files
from pathlib import Path
import pytest
from benchweave_sdk.testing import MockContext, MockHost
from benchweave_sdk.validation import validate_descriptor, validate_result
from example_plugin.adapter import create_plugin
from example_plugin.protocol import transaction


def test_identify_and_read():
    async def run():
        descriptor = json.loads(files("example_plugin").joinpath("descriptor.json").read_text())
        validate_descriptor(descriptor)
        host = MockHost([(transaction("identify"), {"data": b"SDK Example,demo,SIM001,1.0.0\n"}),
                         (transaction("read"), {"data": b"3.3\n"})])
        plugin = create_plugin()
        context = MockContext("op-1", deadline_monotonic=1.0)
        await plugin.open(descriptor, host, context)
        for verb, args in (("identify", {}), ("read", {"parameter": "voltage"})):
            request = {"operation_id": "op-1", "verb": verb, "arguments": args}
            result = await plugin.execute(request, context)
            validate_result(result, request)
            assert result["status"] == "ok"
        host.assert_complete()
        await plugin.close(context)
        await plugin.close(context)
    asyncio.run(run())


def test_quiet_lifecycle():
    from benchweave_sdk.conformance import check_lifecycle
    descriptor = json.loads(files("example_plugin").joinpath("descriptor.json").read_text())
    asyncio.run(check_lifecycle(create_plugin, descriptor))


def test_no_transmit_before_dispatch():
    async def run():
        for reason in ("cancelled", "expired", "bad_arguments", "wrong_context"):
            host = MockHost([])
            plugin = create_plugin()
            context = MockContext("op", deadline_monotonic=1.0)
            await plugin.open({}, host, context)
            request = {"operation_id": "op", "verb": "read",
                       "arguments": {"parameter": "voltage"}}
            if reason == "cancelled":
                context.cancel()
            elif reason == "expired":
                host.advance(1.0)
            elif reason == "bad_arguments":
                request["arguments"]["parameter"] = "unknown"
            else:
                context.operation_id = "other"
            result = await plugin.execute(request, context)
            validate_result(result, request)
            assert result["status"] == "error"
            assert result["error"]["dispatch_state"] == "not_dispatched"
            assert not context.dispatched and not host.transfers
            await plugin.close(MockContext("cleanup", deadline_monotonic=2.0))
    asyncio.run(run())


def test_uncertain_response_after_dispatch():
    async def run():
        responses = ({"data": b"nan\n"}, {"data": b"3.3"}, {"data": b"\xff\n"},
                     ConnectionError("lost"), TimeoutError("expired"), RuntimeError("host"))
        for response in responses:
            host = MockHost([(transaction("read"), response)])
            plugin = create_plugin()
            context = MockContext("op", deadline_monotonic=1.0)
            await plugin.open({}, host, context)
            request = {"operation_id": "op", "verb": "read",
                       "arguments": {"parameter": "voltage"}}
            result = await plugin.execute(request, context)
            validate_result(result, request)
            assert result["status"] == "unknown"
            assert result["error"]["dispatch_state"] == "unknown"
            assert context.dispatched
            host.assert_complete()
            await plugin.close(context)
    asyncio.run(run())


def test_wire_counter_refuses_a_gap():
    """The wire helpers (issue #566): one counter sequences reads and
    writes; a gap is a refusal naming the expected and observed counter
    and the exchange index. The evidence kind comes from the module's
    closed set — a misspelled constant fails at import, never as a wrong
    string at runtime."""
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


def test_wire_paced_poll_waits_the_declared_interval():
    """A declared poll interval every retry honours first; the pacer owns
    the wait, so a loop cannot skip the pace (issue #566)."""
    from example_plugin.wire import paced_poll
    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    async def read():
        return None  # never ready inside the attempt budget

    async def run():
        await paced_poll(2, 0.05, read=read, ready=lambda outcome: bool(outcome),
                         monotonic=lambda: 0.0, deadline=1.0, sleep=sleep)

    with pytest.raises(TimeoutError):
        asyncio.run(run())
    assert waits == [0.05]


def test_wire_completion_signal_pins_success():
    """An operation whose hardware completion signal is not asserted never
    reports ok (issue #566)."""
    from example_plugin.wire import CompletionUnassertedError, require_completion
    require_completion(True, signal="demo done pin")
    with pytest.raises(CompletionUnassertedError, match="demo done pin"):
        require_completion(False, signal="demo done pin")


def test_vectors_evidence_claims_carry_recorded_bytes():
    """The anti-circularity invariant for this plugin's own vectors: a
    vectors.json that claims hardware evidence must carry at least one
    hand-recorded exchange. The scaffold ships synthetic evidence, which
    claims nothing (issue #566)."""
    from benchweave_sdk.vectors import validate_vectors_evidence
    document = json.loads(files("example_plugin").joinpath("vectors.json").read_text())
    validate_vectors_evidence(document, source=Path("vectors.json"))
