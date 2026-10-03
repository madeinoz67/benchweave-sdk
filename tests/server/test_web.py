"""The web surface: banner, readings, polling loop, assets, REST envelopes."""

from __future__ import annotations

import re

from benchweave_sdk_server.web import BANNER, build_app

DEV = "example_device"
SCRIPT_TAG = re.compile(r"<script\b([^>]*)>")


def _connect(client, policy) -> None:
    response = client.post(
        f"/devices/{DEV}/connect",
        headers={"x-csrf-token": policy.csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_home_carries_the_banner_and_plugin_identity(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    # The literal, not the constant: SW-27 pins these exact words on every
    # page, distinct from the preview server's SIMULATED PRESENTATION DATA.
    assert "STANDALONE — no gateway" in body
    assert BANNER == "STANDALONE — no gateway"
    assert "example_plugin" in body
    assert f"/devices/{DEV}" in body


def test_home_banner_names_the_absent_guarantees(client) -> None:
    body = client.get("/").text
    for guarantee in ("leases", "policy", "approvals", "procedures", "runs"):
        assert guarantee in body


def test_device_page_shows_the_reading_after_connect(client, policy) -> None:
    _connect(client, policy)
    body = client.get(f"/devices/{DEV}").text
    assert "voltage" in body
    assert "3.3" in body
    assert "V" in body


def test_ten_polls_all_serve_the_reading(client, policy) -> None:
    _connect(client, policy)
    for _ in range(10):
        response = client.get(f"/devices/{DEV}/readings")
        assert response.status_code == 200
        assert "3.3" in response.text


def test_exhausted_transport_shows_the_refused_state(plugin, policy) -> None:
    """The D(i) page arm: cycles=1, the second poll renders the refusal."""
    import asyncio

    from benchweave_sdk_server.seam import StandaloneSeam
    from benchweave_sdk_server.session import PluginSession, mock_exchanges
    from benchweave_sdk_server.transport import LoopingMockHost

    host = LoopingMockHost(mock_exchanges(plugin), cycles=1)
    seam = StandaloneSeam(PluginSession(plugin, lambda: host), transport_kind="mock")
    app = build_app(seam, policy=policy)
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://127.0.0.1:8477") as client:
        asyncio.run(seam.call("device_connect", {"device_id": DEV}))
        first = client.get(f"/devices/{DEV}/readings")
        assert "3.3" in first.text
        second = client.get(f"/devices/{DEV}/readings")
        assert "Readings refused" in second.text
        assert "unavailable" in second.text


def test_no_script_without_src_anywhere(client, policy) -> None:
    """CSP shape (R2): every template and rendered page, no inline script."""
    from pathlib import Path

    _connect(client, policy)
    pages = ["/", f"/devices/{DEV}", f"/devices/{DEV}/readings"]
    for page in pages:
        for attributes in SCRIPT_TAG.findall(client.get(page).text):
            assert "src=" in attributes, (page, attributes)
    templates = Path(__file__).resolve().parents[2] / "src" / "benchweave_sdk_server" / "templates"
    for template in templates.glob("*.html"):
        for attributes in SCRIPT_TAG.findall(template.read_text()):
            assert "src=" in attributes, (template.name, attributes)


def test_htmx_config_meta_disallows_eval(client) -> None:
    head = client.get("/").text
    assert 'name="htmx-config"' in head
    assert "allowEval" in head


def test_assets_serve_with_their_media_types(client) -> None:
    css = client.get("/assets/tokens.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    js = client.get("/assets/htmx.min.js")
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]


def test_asset_traversal_is_refused(client) -> None:
    for path in (
        "/assets/..%2Finventory.json",
        "/assets/%2e%2e/inventory.json",
    ):
        response = client.get(path)
        assert response.status_code in (404, 400), path


def test_unknown_device_page_is_404(client) -> None:
    assert client.get("/devices/nope").status_code == 404


def test_rest_envelopes_carry_correlation_ids(client, policy) -> None:
    headers = {"authorization": f"Bearer {policy.bearer_token}"}
    ok = client.post("/v1/host_info", headers=headers, json={})
    assert ok.status_code == 200
    body = ok.json()
    assert body["correlation_id"]
    assert body["data"]["mode"] == "standalone"


def test_rest_deferred_operation_refuses(client, policy) -> None:
    headers = {"authorization": f"Bearer {policy.bearer_token}"}
    response = client.post("/v1/capture_start", headers=headers, json={})
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "unavailable"
    assert body["error"]["details"]["reason"] == "increment_deferral"
    assert body["correlation_id"]


def test_rest_argument_validation_is_400(client, policy) -> None:
    headers = {"authorization": f"Bearer {policy.bearer_token}"}
    response = client.post("/v1/device_get", headers=headers, json={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_rest_unknown_operation_is_not_routed(client, policy) -> None:
    headers = {"authorization": f"Bearer {policy.bearer_token}"}
    response = client.post("/v1/lease_create", headers=headers, json={})
    assert response.status_code == 404


def test_mcp_mount_initializes(client, policy) -> None:
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "t", "version": "0"}}},
        headers={
            "authorization": f"Bearer {policy.bearer_token}",
            "accept": "application/json, text/event-stream",
            "origin": "http://127.0.0.1:8477",
        },
    )
    assert response.status_code == 200


def test_failed_connect_renders_a_refusal_state(plugin, policy) -> None:
    """M1 RED arm (UI): a refused connect must RENDER the refusal — the
    operator never gets the silent 'Connect the device...' prompt instead."""

    from fastapi.testclient import TestClient

    from benchweave_sdk_server.seam import StandaloneSeam
    from benchweave_sdk_server.session import PluginSession, mock_exchanges
    from benchweave_sdk_server.transport import LoopingMockHost

    script = mock_exchanges(plugin)
    # Script the establishment itself to fail: the connect-time identify
    # loses the transport, so device_connect refuses not_ready.
    script[0] = (script[0][0], ConnectionError("scripted loss at establish"))
    host = LoopingMockHost(script)
    seam = StandaloneSeam(PluginSession(plugin, lambda: host), transport_kind="mock")
    app = build_app(seam, policy=policy)
    with TestClient(app, base_url="http://127.0.0.1:8477") as client:
        response = client.post(
            f"/devices/{DEV}/connect",
            headers={"x-csrf-token": policy.csrf_token},
            follow_redirects=True,
        )
        body = response.text
        assert "Connect refused" in body
        assert "not_ready" in body
