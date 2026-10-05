"""The seam event bus (I2c §4.2): monotonic gap-free ids, ``events_get``
over every surface, and the SSE stream that carries the same order."""

from __future__ import annotations

import asyncio
import contextlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest  # noqa: F401 - fixture availability

from benchweave_sdk_server.events import EventBus

DEV = {"device_id": "example_device"}


# --- the bus itself -----------------------------------------------------------


def test_bus_ids_are_monotonic_and_gap_free() -> None:
    bus = EventBus()
    ids = [bus.publish("device_connect", {"device_id": "d"}) for _ in range(5)]
    assert ids == [1, 2, 3, 4, 5]
    assert bus.last_id() == 5


def test_bus_survives_interleaved_emissions_without_gaps() -> None:
    """The monotonicity arm: concurrent publishers must produce exactly
    1..N with no duplicate and no missing id (STO-2's in-process echo)."""
    bus = EventBus()
    total = 200
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(bus.publish, "parameter_stage", {"parameter": f"p{i}"})
            for i in range(total)
        ]
        published = [future.result() for future in futures]
    assert sorted(published) == list(range(1, total + 1))
    assert bus.last_id() == total
    rows = bus.after(0)
    assert [row["id"] for row in rows] == list(range(1, total + 1))


def test_bus_after_returns_only_rows_beyond_the_cursor() -> None:
    bus = EventBus()
    for index in range(4):
        bus.publish("device_connect", {"n": index})
    assert [row["id"] for row in bus.after(0)] == [1, 2, 3, 4]
    assert [row["id"] for row in bus.after(2)] == [3, 4]
    assert bus.after(4) == []
    assert bus.after(99) == []


# --- the seam publishes state changes -----------------------------------------


def _events(seam, after_id: int = 0) -> list[dict]:
    return asyncio.run(
        seam.call("events_get", {"after_id": after_id})
    )["events"]


def test_state_changes_publish_and_reads_do_not(seam) -> None:
    asyncio.run(seam.call("device_connect", DEV))
    asyncio.run(seam.call("parameter_read", {**DEV, "parameter": "voltage"}))
    kinds = [row["kind"] for row in _events(seam)]
    assert "device_connect" in kinds
    assert "parameter_read" not in kinds


def test_disconnect_publishes(seam) -> None:
    asyncio.run(seam.call("device_connect", DEV))
    asyncio.run(seam.call("device_disconnect", DEV))
    kinds = [row["kind"] for row in _events(seam)]
    assert kinds[-1] == "device_disconnect"


def test_refusals_publish_the_refused_class(seam) -> None:
    """A refused operation is a state-change class of its own: the refusal
    rides the bus with the operation name and the interface code."""
    from benchweave_sdk_server.errors import SeamError

    with pytest.raises(SeamError):
        asyncio.run(seam.call("parameter_read", {**DEV, "parameter": "voltage"}))
    refused = [row for row in _events(seam) if row["kind"] == "refused"]
    assert refused, "the refusal class must ride the bus"
    assert refused[-1]["data"]["operation"] == "parameter_read"
    assert refused[-1]["data"]["code"] == "not_ready"


def test_every_refusal_family_publishes_the_refused_class(seam) -> None:
    """FOLD-E: the refused class covers every refusal family a seam exit
    can take — the unknown operation, the handler's own typed refusal
    (unavailable), the argument-validation refusal, and the adapter-mapped
    refusal. Watching pages must see every refusal, not only the ones
    that happen to raise inside a handler. (The pre-I3b fourth family,
    declared-but-deferred, is VACANT since the I3b flip — nothing defers;
    it returns the moment a row defers again, and its proof shape is the
    same seam-exit row pinned here.)"""
    from benchweave_sdk_server.errors import SeamError

    # Unknown operation (refused BEFORE any handler exists).
    with pytest.raises(SeamError):
        asyncio.run(seam.call("lease_create", {}))
    # Handler refusal: capture_start over the mock transport's services
    # is unavailable naming the gap (the I3b lifecycle's own arm).
    with pytest.raises(SeamError):
        asyncio.run(
            seam.call(
                "device_connect", {"device_id": seam.session.device_id}
            )
        )
        asyncio.run(
            seam.call(
                "capture_start",
                {
                    "device_id": seam.session.device_id,
                    "format": "waveform_f64le",
                    "count": 4,
                    "sample_interval_s": 0.001,
                    "unit": "V",
                },
            )
        )
    # Argument validation (the schema gate, before the handler).
    with pytest.raises(SeamError):
        asyncio.run(seam.call("events_get", {}))
    refused = [row["data"] for row in _events(seam) if row["kind"] == "refused"]
    operations = {row["operation"] for row in refused}
    assert {"lease_create", "capture_start", "events_get"} <= operations
    codes = {row["operation"]: row["code"] for row in refused}
    assert codes["lease_create"] == "invalid_request"
    assert codes["capture_start"] == "unavailable"
    assert codes["events_get"] == "invalid_request"


def test_reload_refusals_publish_the_refused_class(tmp_path) -> None:
    """FOLD-E: the reload family raises SeamError OUTSIDE seam.call — its
    refusals publish 'refused' themselves, or watching pages never see
    Q11's own conflict."""
    import shutil as _shutil
    from pathlib import Path

    from benchweave_sdk_server.errors import SeamError
    from benchweave_sdk_server.seam import StandaloneSeam
    from benchweave_sdk_server.session import load_plugin_project, mock_plugin_session

    project = tmp_path / "setpoint"
    _shutil.copytree(
        Path(__file__).resolve().parent.parent / "fixtures" / "setpoint_plugin",
        project,
    )
    plugin = load_plugin_project(project)
    seam = StandaloneSeam(mock_plugin_session(plugin), transport_kind="mock")
    asyncio.run(
        seam.call(
            "parameter_stage",
            {"device_id": "setpoint_dev", "parameter": "current_limit", "value": 1.0},
        )
    )
    with pytest.raises(SeamError):
        asyncio.run(seam.reload_plugin(source="test"))
    with pytest.raises(SeamError):
        asyncio.run(seam.confirm_reload(source="test"))
    refused = [
        row["data"]
        for row in asyncio.run(seam.call("events_get", {"after_id": 0}))["events"]
        if row["kind"] == "refused"
    ]
    reload_refusals = [row for row in refused if "reload" in row["operation"]]
    assert len(reload_refusals) == 2, refused
    assert all(row["code"] != "" for row in reload_refusals)


def test_events_get_reports_last_id_and_honours_the_cursor(seam) -> None:
    asyncio.run(seam.call("device_connect", DEV))
    first = asyncio.run(seam.call("events_get", {"after_id": 0}))
    assert first["last_id"] >= 1
    tail = asyncio.run(seam.call("events_get", {"after_id": first["last_id"]}))
    assert tail["events"] == []


# --- REST and MCP see the same order ------------------------------------------


def test_events_get_over_rest(client, policy) -> None:
    response = client.post(
        "/v1/events_get",
        headers={"authorization": f"Bearer {policy.bearer_token}"},
        json={"after_id": 0},
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["data"]["last_id"], int)
    assert "events" in body["data"]


def test_events_get_over_mcp(seam) -> None:
    from fastmcp import Client

    from benchweave_sdk_server.mcp import build_mcp

    mcp = build_mcp(seam)

    async def run() -> dict:
        async with Client(mcp) as client:
            await client.call_tool("bws_v1_device_connect", DEV)
            result = await client.call_tool(
                "bws_v1_events_get", {"after_id": 0}, raise_on_error=False
            )
            return result.structured_content or {}

    data = asyncio.run(run())
    kinds = [row["kind"] for row in data["events"]]
    assert "device_connect" in kinds


def test_rest_and_mcp_see_one_order(seam, policy) -> None:
    """The PRD §6 diagram's rule: the browser, REST watchers and MCP read
    ONE sequence — the ids they observe agree."""
    from fastapi.testclient import TestClient

    from benchweave_sdk_server.mcp import build_mcp
    from benchweave_sdk_server.web import build_app

    asyncio.run(seam.call("device_connect", DEV))
    app = build_app(seam, policy=policy)
    mcp = build_mcp(seam)

    async def over_mcp() -> dict:
        from fastmcp import Client

        async with Client(mcp) as client:
            result = await client.call_tool(
                "bws_v1_events_get", {"after_id": 0}, raise_on_error=False
            )
            return result.structured_content or {}

    with TestClient(app, base_url="http://127.0.0.1:8477") as rest:
        over_rest = rest.post(
            "/v1/events_get",
            headers={"authorization": f"Bearer {policy.bearer_token}"},
            json={"after_id": 0},
        ).json()
    data_mcp = asyncio.run(over_mcp())
    assert [row["id"] for row in over_rest["data"]["events"]] == [
        row["id"] for row in data_mcp["events"]
    ]
    assert [row["kind"] for row in over_rest["data"]["events"]] == [
        row["kind"] for row in data_mcp["events"]
    ]


# --- the SSE endpoint ----------------------------------------------------------


async def _drain_sse(app, path: str, enough: str) -> tuple[str, list[str]]:
    """Collect the SSE stream's first bytes by driving the ASGI app
    directly — httpx's ASGITransport buffers the whole body, so an
    infinite stream can never drain through it. This arm speaks ASGI
    itself: the full middleware stack runs, ``http.response.start`` and
    each ``http.response.body`` chunk are captured as the app produces
    them, the collection stops once ``enough`` text has arrived (or the
    ``asyncio.timeout`` backstop fails loudly), and the app task is then
    cancelled — which is exactly how a disconnect ends the stream in
    production (the server cancels the response task)."""

    body: list[str] = []
    status_holder: list[int] = []
    ctype_holder: list[str] = []

    async def receive() -> dict:
        # No client message ever arrives: a GET has no body, and the
        # disconnect is expressed by the task cancellation below.
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.start":
            status_holder.append(int(message["status"]))
            headers = {
                bytes(key).decode().lower(): bytes(value).decode()
                for key, value in message.get("headers", [])
            }
            ctype_holder.append(headers.get("content-type", ""))
        elif message["type"] == "http.response.body":
            body.append(bytes(message.get("body", b"")).decode())

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path.split("?")[0],
        "raw_path": path.encode(),
        "query_string": path.partition("?")[2].encode(),
        "root_path": "",
        "headers": [(b"host", b"127.0.0.1:8477")],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8477),
    }

    task = asyncio.create_task(app(scope, receive, send))
    try:
        async with asyncio.timeout(10.0):
            while not status_holder or enough not in "".join(body):
                await asyncio.sleep(0.02)
    finally:
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
    text = "".join(body)
    return ctype_holder[0] if ctype_holder else "", text.splitlines()


def test_sse_streams_the_backlog_in_order(app, seam) -> None:
    asyncio.run(seam.call("device_connect", DEV))
    content_type, lines = asyncio.run(
        _drain_sse(app, "/events", 'data: {"id":')
    )
    assert content_type.startswith("text/event-stream")
    text = "\n".join(lines)
    assert "event: device_connect" in text
    # Every data frame is a JSON object carrying the bus's own fields.
    frames = [
        line.removeprefix("data: ")
        for line in lines
        if line.startswith("data: ")
    ]
    assert frames
    first = json.loads(frames[0])
    assert set(first) == {"id", "kind", "data"}


def test_sse_honours_the_cursor(app, seam) -> None:
    asyncio.run(seam.call("device_connect", DEV))
    last = seam.events.last_id()
    asyncio.run(seam.call("device_disconnect", DEV))
    _, lines = asyncio.run(
        _drain_sse(app, f"/events?after_id={last}", 'data: {"id":')
    )
    # The connect event is at or behind the cursor: the stream carries the
    # disconnect only, and any data frame must be strictly newer than the
    # cursor — a pre-cursor replay fails.
    text = "\n".join(lines)
    assert "event: device_disconnect" in text
    assert "event: device_connect" not in text
    for line in lines:
        if line.startswith("data: "):
            payload = json.loads(line.removeprefix("data: "))
            assert payload["id"] > last
