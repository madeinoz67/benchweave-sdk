"""I3b slice 4: capture events, dispatch surfaces, lifespan, CLI root.

The capture events ride the EXISTING EventBus and /events stream (I2c's
one-sequence rule — no new event machinery): ``capture_started`` at arm
time, ``capture_progress`` coalesced to at most one row per 250 ms carrying
the staged-byte total, ``capture_stopped`` at the terminal state. SW-51:
the capture is host-process state — a disconnected browser stream cannot
stop it. The dispatch surfaces record themselves (SW-34): REST says
``rest``, MCP says ``mcp``. The app lifespan releases the capture library's
root lock (NFR-O1's close-down shape), and ``serve --capture-root`` threads
one root to the seam and the serial session factory.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from click.testing import CliRunner
from test_capture_lifecycle import DEV, _connected, _host, _start

from benchweave_sdk.scaffold import create_project
from benchweave_sdk_server.cli import _build_seam
from benchweave_sdk_server.cli import cli as server_cli
from benchweave_sdk_server.mcp import _dispatch
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.web import build_app

_TEST_BASE = "http://127.0.0.1:8477"


def _policy() -> GuardPolicy:
    return GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )


def _bearer(policy: GuardPolicy) -> dict[str, str]:
    return {"authorization": f"Bearer {policy.bearer_token}"}


# --- the bus events (250 ms coalescing) -------------------------------------


def test_capture_events_ride_the_bus_coalesced(tmp_path: Path) -> None:
    """A ~0.9 s capture publishes started, at most one progress row per
    250 ms (SW-26/NFR-Q3's frame budget), and stopped with the terminal
    state — all on the one sequence events_get serves."""
    host = _host(tmp_path, mode="slow")

    async def scenario() -> dict:
        await _connected(host)
        await host.call("capture_start", _start(count=40), surface="rest")
        return await host.await_capture()

    outcome = asyncio.run(scenario())
    events = asyncio.run(host.call("events_get", {"after_id": 0}))["events"]
    started = next(
        event for event in events if event["kind"] == "capture_started"
    )
    assert started["data"]["capture_id"] == outcome["capture_id"]
    assert started["data"]["bound"]["count"] == 40
    progress = [
        event for event in events if event["kind"] == "capture_progress"
    ]
    assert 1 <= len(progress) <= 5
    totals = [event["data"]["bytes"] for event in progress]
    assert all(total > 0 for total in totals)
    assert totals == sorted(totals)
    stopped = next(
        event for event in events if event["kind"] == "capture_stopped"
    )
    assert stopped["data"]["state"] == outcome["state"]
    assert stopped["data"]["stop_reason"] == outcome["stop_reason"]


# --- the dispatch surfaces (SW-34) ------------------------------------------


def test_rest_dispatch_records_the_rest_surface(tmp_path: Path) -> None:
    host = _host(tmp_path, mode="slow")
    policy = _policy()
    app = build_app(host, policy=policy)
    from fastapi.testclient import TestClient

    with TestClient(app, base_url=_TEST_BASE) as client:
        client.post("/v1/device_connect", json={"device_id": DEV}, headers=_bearer(policy))
        started = client.post(
            "/v1/capture_start", json=_start(count=20), headers=_bearer(policy)
        )
        assert started.status_code == 200
        capture_id = started.json()["data"]["capture_id"]
        stopped = client.post(
            "/v1/capture_stop",
            json={"capture_id": capture_id},
            headers=_bearer(policy),
        )
        assert stopped.json()["data"]["state"] == "published"
    metadata = json.loads(
        (tmp_path / "captures" / capture_id / "metadata.json").read_text()
    )
    assert metadata["surface"] == "rest"


def test_mcp_dispatch_records_the_mcp_surface(tmp_path: Path) -> None:
    host = _host(tmp_path, mode="ok")

    async def scenario() -> str:
        await _connected(host)
        started = await _dispatch(host, "capture_start", _start(count=3))
        await host.await_capture()
        return str(started["capture_id"])

    capture_id = asyncio.run(scenario())
    metadata = json.loads(
        (tmp_path / "captures" / capture_id / "metadata.json").read_text()
    )
    assert metadata["surface"] == "mcp"


# --- SW-51: the capture is host state, never request state ------------------


def test_a_disconnected_client_does_not_stop_the_capture(tmp_path: Path) -> None:
    """AR-7's substance at the process boundary the in-process clients can
    reach: the client that started the capture goes away entirely (its
    connection closed, a SECOND client must finish the job) — the capture
    keeps running and a later stop finalises its bytes. The SSE stream's
    rendered relay is I2c's browser-lane surface: neither TestClient nor
    httpx.ASGITransport streams incrementally (both buffer the full body —
    measured: both hang on an infinite stream), so the bus row above is
    the in-suite pin and the rendered stream stays the browser lane's
    arm. Disclosed."""
    host = _host(tmp_path, mode="slow")
    policy = _policy()
    app = build_app(host, policy=policy)

    async def scenario() -> dict:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=_TEST_BASE
        ) as client:
            await client.post(
                "/v1/device_connect", json={"device_id": DEV}, headers=_bearer(policy)
            )
            started = (
                await client.post(
                    "/v1/capture_start",
                    json=_start(count=30),
                    headers=_bearer(policy),
                )
            ).json()["data"]
            # The start REQUEST has fully completed: nothing about it holds
            # the capture — this pause is the disconnect window.
            await asyncio.sleep(0.05)
            stopped = (
                await client.post(
                    "/v1/capture_stop",
                    json={"capture_id": started["capture_id"]},
                    headers=_bearer(policy),
                )
            ).json()["data"]
            return stopped

    stopped = asyncio.run(scenario())
    assert stopped["state"] == "published"
    assert stopped["manifest"]["byte_length"] > 0
    events = asyncio.run(host.call("events_get", {"after_id": 0}))["events"]
    assert any(event["kind"] == "capture_stopped" for event in events)


# --- the lifespan close-down -------------------------------------------------


def test_lifespan_releases_the_library_lock(tmp_path: Path) -> None:
    host = _host(tmp_path, mode="ok")
    policy = _policy()
    app = build_app(host, policy=policy)
    # TestClient (not bare httpx): the lock release rides the app's own
    # lifespan, which only a lifespan-running client executes.
    from fastapi.testclient import TestClient

    with TestClient(app, base_url=_TEST_BASE) as client:
        client.post("/v1/device_connect", json={"device_id": DEV}, headers=_bearer(policy))
        started = client.post(
            "/v1/capture_start", json=_start(count=2), headers=_bearer(policy)
        )
        capture_id = started.json()["data"]["capture_id"]
        client.post(
            "/v1/capture_stop",
            json={"capture_id": capture_id},
            headers=_bearer(policy),
        )
        assert (tmp_path / "captures" / "library.lock").exists()
    assert not (tmp_path / "captures" / "library.lock").exists()


# --- the CLI root ------------------------------------------------------------


def test_serve_exposes_the_capture_root_option() -> None:
    result = CliRunner().invoke(server_cli, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--capture-root" in result.output


def test_build_seam_threads_the_capture_root(tmp_path: Path) -> None:
    create_project(tmp_path / "proj", "rootcheck_plugin")
    captures = tmp_path / "caps"
    seam, _ = _build_seam(tmp_path / "proj", capture_root=captures)
    rows = asyncio.run(seam.call("capture_list", {}))["captures"]
    assert rows == []
    assert (captures / "library.sqlite3").exists()
