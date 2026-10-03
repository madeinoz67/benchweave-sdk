"""The device-rejection refusal path: SW-12 distinctness end to end
(the request-rejected scenario's live-pipeline surface, §4.2)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from benchweave_sdk_server.cli import _build_seam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.web import build_app

DEV = "example_device"


def _client(starter_project, policy: GuardPolicy) -> TestClient:
    seam, _ = _build_seam(starter_project, scenario="request-rejected")
    return TestClient(
        build_app(seam, policy=policy), base_url="http://127.0.0.1:8477"
    )


def _policy() -> GuardPolicy:
    return GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )


def _connect(client: TestClient, policy: GuardPolicy) -> None:
    response = client.post(
        f"/devices/{DEV}/connect",
        headers={"x-csrf-token": policy.csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_rest_refusal_carries_the_device_rejection_verbatim(starter_project) -> None:
    """The device said no: the interface code is conflict (a state-based
    refusal), and the adapter's own envelope — code DEVICE_REJECTED,
    dispatch_state dispatched — rides the details verbatim (SW-12)."""
    policy = _policy()
    with _client(starter_project, policy) as client:
        _connect(client, policy)
        response = client.post(
            "/v1/parameter_read",
            json={"device_id": DEV, "parameter": "voltage"},
            headers={"authorization": f"Bearer {policy.bearer_token}"},
        )
        assert response.status_code == 409
        body = response.json()
        assert body["error"]["code"] == "conflict"
        adapter = body["error"]["details"]["adapter"]
        assert adapter["code"] == "DEVICE_REJECTED"
        assert adapter["dispatch_state"] == "dispatched"


def test_the_html_refused_state_shows_the_adapter_code(starter_project) -> None:
    """The readings refused notice renders the device's own code — the
    author sees WHICH refusal, not just that one happened."""
    policy = _policy()
    with _client(starter_project, policy) as client:
        _connect(client, policy)
        body = client.get(f"/devices/{DEV}/readings").text
        assert "Readings refused" in body
        assert "DEVICE_REJECTED" in body
        assert "dispatched" in body


def test_a_transmission_refusal_stays_not_ready(starter_project) -> None:
    """Distinctness pin: a transport-loss refusal (the disconnected
    scenario's establishment) answers not_ready — it is NOT the device
    saying no."""
    policy = _policy()
    seam, _ = _build_seam(starter_project, scenario="disconnected")
    with TestClient(
        build_app(seam, policy=policy), base_url="http://127.0.0.1:8477"
    ) as client:
        response = client.post(
            "/v1/device_connect",
            json={"device_id": DEV},
            headers={"authorization": f"Bearer {policy.bearer_token}"},
        )
        assert response.status_code == 409
        body = response.json()
        assert body["error"]["code"] == "not_ready"
        assert "DEVICE_REJECTED" not in str(body)
