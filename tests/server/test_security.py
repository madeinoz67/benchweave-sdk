"""The guard set: every refusal green in the full app, every attack passing
in the minus-one app (gate D — each guard proven to be the mechanism)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from benchweave_sdk_server import security
from benchweave_sdk_server.security import GuardPolicy
from benchweave_sdk_server.web import build_app

DEV = "example_device"
EVIL_HOST = {"host": "evil.example:8477"}
MCP_HEADERS = {
    "authorization": "Bearer not-the-token",
    "content-type": "application/json",
    "accept": "application/json, text/event-stream",
}


def _app(seam, policy: GuardPolicy) -> FastAPI:
    return build_app(seam, policy=policy)


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, base_url="http://127.0.0.1:8477")


def minus(seam, policy: GuardPolicy, flag: str):
    """A context-managed client over the app with exactly one guard off —
    the minus-one construction that proves each guard is the mechanism."""
    from contextlib import contextmanager

    @contextmanager
    def _entered():
        with _client(_app(seam, policy.minus(flag))) as entered:
            yield entered

    return _entered()


# --- trusted-Host (NFR-S2) -------------------------------------------------


def test_evil_host_refused_on_all_three_surfaces(client) -> None:
    mcp_init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    checks = (
        lambda: client.get("/", headers=EVIL_HOST),
        lambda: client.post("/v1/host_info", headers=EVIL_HOST, json={}),
        lambda: client.post("/mcp", headers={**MCP_HEADERS, **EVIL_HOST}, json=mcp_init),
    )
    for call in checks:
        response = call()
        assert response.status_code == 403, response.status_code
        assert response.json()["error"] == "standalone_invalid_host"


def test_minus_trusted_host_lets_the_rebinding_through(seam, policy) -> None:
    with minus(seam, policy, "enable_trusted_host") as client:
        response = client.get("/", headers=EVIL_HOST)
    assert response.status_code == 200


def test_wrong_port_is_untrusted(client) -> None:
    response = client.get("/", headers={"host": "127.0.0.1:9999"})
    assert response.status_code == 403


def test_localhost_names_the_loopback_listener(client) -> None:
    response = client.get("/", headers={"host": "localhost:8477"})
    assert response.status_code == 200


# --- CSRF (NFR-S3) ----------------------------------------------------------


def test_csrf_less_connect_post_refused(client, policy) -> None:
    response = client.post(f"/devices/{DEV}/connect", data={})
    assert response.status_code == 403
    assert response.json()["error"] == "standalone_csrf_required"


def test_connect_with_token_redirects(client, policy) -> None:
    response = client.post(
        f"/devices/{DEV}/connect",
        headers={"x-csrf-token": policy.csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_minus_csrf_lets_the_post_through(seam, policy) -> None:
    with minus(seam, policy, "enable_csrf") as client:
        response = client.post(f"/devices/{DEV}/connect", data={}, follow_redirects=False)
    assert response.status_code == 303


# --- REST bearer (NFR-S3) ---------------------------------------------------


def test_bearer_less_rest_mutation_refused(client) -> None:
    response = client.post("/v1/device_connect", json={"device_id": DEV})
    assert response.status_code == 403
    assert response.json()["error"] == "standalone_bearer_required"


def test_bearer_rest_mutation_accepted(client, policy) -> None:
    response = client.post(
        "/v1/device_connect",
        json={"device_id": DEV},
        headers={"authorization": f"Bearer {policy.bearer_token}"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["connected"] is True


def test_minus_bearer_lets_the_mutation_through(seam, policy) -> None:
    with minus(seam, policy, "enable_bearer") as client:
        response = client.post("/v1/device_connect", json={"device_id": DEV})
    assert response.status_code == 200


# --- MCP over HTTP (NFR-S4) -------------------------------------------------


def _mcp_post(client: TestClient, *, origin: str | None, token: str | None):
    headers = {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
    }
    if origin is not None:
        headers["origin"] = origin
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18",
                         "capabilities": {},
                         "clientInfo": {"name": "test", "version": "0"}}},
        headers=headers,
    )


def test_mcp_disallowed_origin_refused(client, policy) -> None:
    response = _mcp_post(client, origin="http://evil.example", token=policy.bearer_token)
    assert response.status_code == 403
    assert response.json()["error"] == "standalone_origin_not_allowed"


def test_mcp_missing_token_refused(client) -> None:
    response = _mcp_post(client, origin="http://127.0.0.1:8477", token=None)
    assert response.status_code == 403
    assert response.json()["error"] == "standalone_mcp_token_required"


def test_mcp_loopback_origin_with_token_passes_the_guard(client, policy) -> None:
    response = _mcp_post(client, origin="http://127.0.0.1:8477", token=policy.bearer_token)
    assert response.status_code != 403


def test_minus_mcp_guard_lets_the_attack_through(seam, policy) -> None:
    with minus(seam, policy, "enable_mcp_guard") as client:
        response = _mcp_post(client, origin="http://evil.example", token=None)
    assert response.status_code != 403


# --- body cap (NFR-S6) ------------------------------------------------------


def test_oversized_body_is_refused_payload_too_large(client, policy) -> None:
    payload = {"device_id": "x" * (security.MAX_REQUEST_BYTES + 1)}
    response = client.post(
        "/v1/device_discover",
        json=payload,
        headers={"authorization": f"Bearer {policy.bearer_token}"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_minus_body_cap_lets_the_body_through(seam, policy) -> None:
    with minus(seam, policy, "enable_body_cap") as client:
        payload = {"device_id": "x" * (security.MAX_REQUEST_BYTES + 1)}
        response = client.post(
            "/v1/device_discover",
            json=payload,
            headers={"authorization": f"Bearer {policy.bearer_token}"},
        )
    assert response.status_code != 413


# --- CSP / no CORS (NFR-S5) --------------------------------------------------


def test_html_carries_strict_csp_without_inline(client) -> None:
    response = client.get("/")
    csp = response.headers.get("content-security-policy", "")
    assert "script-src 'self'" in csp
    assert "unsafe-inline" not in csp
    assert csp.startswith("default-src 'none'")


def test_no_cors_headers_anywhere(client, policy) -> None:
    ok = client.get("/")
    assert "access-control-allow-origin" not in ok.headers
    posted = client.post(
        "/v1/host_info",
        json={},
        headers={"authorization": f"Bearer {policy.bearer_token}"},
    )
    assert "access-control-allow-origin" not in posted.headers
    asset = client.get("/assets/tokens.css")
    assert "access-control-allow-origin" not in asset.headers
    assert "access-control-allow-methods" not in asset.headers


def test_minus_csp_serves_without_the_header(seam, policy) -> None:
    with minus(seam, policy, "enable_csp") as client:
        head = client.get("/").headers
    assert "content-security-policy" not in head


# --- listener rules (NFR-S1): owned by the guard module since #308 ----------


def test_listener_rules_live_in_the_guard_module() -> None:
    """``validate_listener`` and ``MAX_REQUEST_BYTES`` are OWNED here, moved
    verbatim from the dying ``benchweave_sdk.preview_server`` at 0.7.0: the
    refusals keep their ``preview_`` prefixes (recorded lineage), and the
    three rules are pinned at the new home — loopback binds freely, wildcard
    never binds, non-loopback binds only with acknowledgement."""
    from benchweave_sdk_server.security import MAX_REQUEST_BYTES, validate_listener

    assert MAX_REQUEST_BYTES == 64 * 1024
    with pytest.raises(ValueError, match="preview_invalid_listener"):
        validate_listener("not-an-address", False)
    with pytest.raises(ValueError, match="preview_unsafe_listener"):
        validate_listener("0.0.0.0", False)
    with pytest.raises(ValueError, match="preview_network_acknowledgement_required"):
        validate_listener("192.168.1.5", False)
    # Loopback binds without acknowledgement; acknowledgement lifts the
    # non-loopback refusal (the serve CLI arms pin the same rules end to end).
    validate_listener("127.0.0.1", False)
    validate_listener("192.168.1.5", True)


# --- the CLI never omits a guard ---------------------------------------------


def test_complete_policy_arms_every_guard(policy: GuardPolicy) -> None:
    for flag in (
        "enable_trusted_host", "enable_csrf", "enable_bearer",
        "enable_mcp_guard", "enable_body_cap", "enable_csp",
    ):
        assert getattr(policy, flag) is True


def test_complete_policy_installs_six_middlewares(app: FastAPI) -> None:
    classes = {entry.cls.__name__ for entry in app.user_middleware}
    for name in (
        "TrustedHostGuard", "CsrfGuard", "BearerGuard", "McpGuard",
        "BodyCapGuard", "SecurityHeadersGuard",
    ):
        assert name in classes
