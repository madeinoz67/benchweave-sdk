import asyncio
import json
from importlib.resources import files
from benchweave_sdk.testing import MockContext, MockHost
from benchweave_sdk.validation import validate_descriptor, validate_result
from example_plugin.adapter import create_plugin
from example_plugin.protocol import transaction, probe


def test_identify_and_read():
    async def run():
        descriptor = json.loads(files("example_plugin").joinpath("descriptor.json").read_text())
        validate_descriptor(descriptor)
        host = MockHost([(transaction("identify"), {"data": b"SDK Example,demo,SIM001,1.0.0\n"}),
                         (probe(), {"data": b"STATUS OK\n"}),
                         (probe(), {"data": b""}),
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
            host = MockHost([(probe(), {"data": b""}),
                            (transaction("read"), response)])
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
