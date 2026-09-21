"""Author-facing SDK checks; the SDK must not import the gateway."""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

import pytest

from benchweave_sdk import conformance, packaging, scaffold, testing, validation

# Main-side this is the pinned packages/sdk submodule tree; here it is this
# checkout's own src tree, which is what an editable install resolves to.
SDK = Path(__file__).resolve().parents[1] / "src"


def test_resolves_from_the_pinned_submodule_tree() -> None:
    """The SDK under test must be this checkout's tree (#53, as migrated).

    An environment can carry another benchweave_sdk install whose path
    entries point somewhere else; without this assertion a path-order
    change silently tests that (possibly stale) tree instead of the commit
    under test. Main-side the same guard pins the packages/sdk submodule.
    """
    module = importlib.import_module("benchweave_sdk")
    source = module.__file__
    assert source is not None, "benchweave_sdk resolved without a source file"
    resolved = Path(source).resolve()
    assert resolved.is_relative_to(SDK), (
        f"benchweave_sdk resolved from {resolved}, not the pinned submodule tree "
        f"{SDK}; an editable install or standalone checkout is shadowing it"
    )


def test_context_preserves_dispatch_and_cancellation() -> None:
    context = testing.MockContext("op-1", deadline_monotonic=1.0)
    assert not context.dispatched
    asyncio.run(context.mark_dispatch_started())
    context.cancel()
    assert context.dispatched and context.is_cancelled()


def test_transport_rejects_cancelled_or_expired_without_consuming_vector() -> None:
    host = testing.MockHost([({"kind": "stream_send", "data": b"x"}, {})])
    expired = testing.MockContext("op", deadline_monotonic=0.0)
    with pytest.raises(TimeoutError):
        asyncio.run(host.transfer({"kind": "stream_send", "data": b"x"}, expired))
    assert host.transfers == [] and host.pending == 1
    cancelled = testing.MockContext("op", deadline_monotonic=10.0)
    cancelled.cancel()
    with pytest.raises(TimeoutError):
        asyncio.run(host.transfer({"kind": "stream_send", "data": b"x"}, cancelled))
    assert host.transfers == [] and host.pending == 1


def test_transport_requires_dispatch_marker_and_exact_script() -> None:
    host = testing.MockHost([({"kind": "stream_send", "data": b"x"}, {})])
    context = testing.MockContext("op", deadline_monotonic=10.0)
    with pytest.raises(AssertionError, match="dispatch"):
        asyncio.run(host.transfer({"kind": "stream_send", "data": b"x"}, context))
    asyncio.run(context.mark_dispatch_started())
    assert asyncio.run(host.transfer({"kind": "stream_send", "data": b"x"}, context)) == {}
    host.assert_complete()
    with pytest.raises(AssertionError):
        asyncio.run(host.transfer({"kind": "stream_receive"}, context))


def test_offline_schema_and_correlation_validation() -> None:
    request: dict[str, object] = {"operation_id": "op-1", "verb": "identify", "arguments": {}}
    result: dict[str, object] = {
        "operation_id": "op-2",
        "verb": "identify",
        "status": "ok",
        "data": {
            "manufacturer": "Example",
            "model": "demo",
            "serial": None,
            "firmware": "1.0.0",
            "source": "device",
        },
    }
    validation.validate_request(request)
    with pytest.raises(ValueError, match="correlation"):
        validation.validate_result(result, request)
    result["operation_id"] = "op-1"
    validation.validate_result(result, request)
    request["unexpected"] = True
    with pytest.raises(ValueError):
        validation.validate_request(request)


def test_scaffold_builds_only_in_new_directory_and_has_tests(tmp_path: Path) -> None:
    target = tmp_path / "external"
    scaffold.create_project(target, "example_plugin")
    assert (target / "src/example_plugin/adapter.py").is_file()
    assert (target / "src/example_plugin/protocol.py").is_file()
    assert (target / "tests/test_plugin.py").is_file()
    with pytest.raises(FileExistsError):
        scaffold.create_project(target, "example_plugin")
    for name in ("../escape", "not-a-module", "class"):
        with pytest.raises(ValueError):
            scaffold.create_project(tmp_path / "bad", name)


def test_conformance_catches_wrong_identity_and_lifecycle_io(tmp_path: Path) -> None:
    from typing import Any

    class Broken:
        async def execute(self, *args: Any) -> dict[str, Any]:
            return {
                "operation_id": "wrong",
                "verb": "identify",
                "status": "ok",
                "data": {
                    "manufacturer": "X",
                    "model": "Y",
                    "serial": None,
                    "firmware": None,
                    "source": "device",
                },
            }

    with pytest.raises(ValueError, match="correlation"):
        asyncio.run(
            conformance.check_operation(
                Broken(),
                {"operation_id": "expected", "verb": "identify", "arguments": {}},
                testing.MockContext("expected", deadline_monotonic=1.0),
            )
        )
    scaffold.create_project(tmp_path / "sample", "sample_plugin")


@pytest.mark.parametrize("stage", ["open", "next_event", "close", "execute"])
def test_conformance_times_out_stalled_adapter(stage: str) -> None:
    from typing import Any

    descriptor = scaffold.descriptor_for("stall_plugin")

    class Stalled:
        async def open(self, *args: Any) -> None:
            if stage == "open":
                await asyncio.Event().wait()

        async def next_event(self, *args: Any) -> None:
            if stage == "next_event":
                await asyncio.Event().wait()

        async def close(self, *args: Any) -> None:
            if stage == "close":
                await asyncio.Event().wait()

        async def execute(self, *args: Any) -> None:
            await asyncio.Event().wait()

    async def run() -> None:
        with pytest.raises(TimeoutError):
            if stage == "execute":
                await conformance.check_operation(
                    Stalled(),
                    {"operation_id": "stalled", "verb": "identify", "arguments": {}},
                    testing.MockContext("stalled", deadline_monotonic=1.0),
                    timeout=0.01,
                )
            else:
                await conformance.check_lifecycle(Stalled, descriptor, timeout=0.01)

    asyncio.run(run())


def test_manifest_inventory_rejects_tamper_and_escape(tmp_path: Path) -> None:
    (tmp_path / "plugin.py").write_bytes(b"pass\n")
    inventory = packaging.inventory(tmp_path)
    packaging.verify_inventory(tmp_path, inventory)
    (tmp_path / "plugin.py").write_bytes(b"evil\n")
    with pytest.raises(ValueError, match="hash|size"):
        packaging.verify_inventory(tmp_path, inventory)
    with pytest.raises(ValueError, match="path"):
        packaging.verify_inventory(
            tmp_path, [{"path": "../escape", "bytes": 0, "sha256": "0" * 64}]
        )


def test_generated_adapter_maps_host_resource_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scaffold.create_project(tmp_path / "plugin", "resource_failure_plugin")
    monkeypatch.syspath_prepend(str(tmp_path / "plugin/src"))
    adapter = importlib.import_module("resource_failure_plugin.adapter")
    protocol = importlib.import_module("resource_failure_plugin.protocol")

    async def run() -> None:
        host = testing.MockHost([(protocol.transaction("read"), RuntimeError("host resource"))])
        plugin = adapter.create_plugin()
        context = testing.MockContext("op", deadline_monotonic=1.0)
        await plugin.open({}, host, context)
        request = {"operation_id": "op", "verb": "read", "arguments": {"parameter": "voltage"}}
        result = await plugin.execute(request, context)
        validation.validate_result(result, request)
        assert result["status"] == "unknown"
        assert result["error"]["code"] == "INTERNAL_ERROR"
        host.assert_complete()
        await plugin.close(context)

    try:
        asyncio.run(run())
    finally:
        for name in tuple(sys.modules):
            if name == "resource_failure_plugin" or name.startswith("resource_failure_plugin."):
                del sys.modules[name]


def test_missing_schema_resource_fails_offline() -> None:
    from referencing.exceptions import NoSuchResource

    registry = validation._registry()
    with pytest.raises(NoSuchResource):
        registry.get_or_retrieve("https://example.invalid/not-in-the-sdk.json")


def test_finite_clock_and_descriptor_rejections() -> None:
    host = testing.MockHost([])
    for delta in (-1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            host.advance(delta)
    with pytest.raises(ValueError):
        validation.validate_descriptor({"otdp_version": "0.1.0"})
