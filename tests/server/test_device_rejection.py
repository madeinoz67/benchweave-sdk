"""The device-rejection refusal path: SW-12 distinctness end to end
(the request-rejected scenario's live-pipeline surface, §4.2)."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from benchweave_sdk_server.cli import _build_seam
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.session import (
    PluginSession,
    load_plugin_project,
    mock_plugin_session,
)
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
    """The refused row renders the device's own code — the author sees
    WHICH refusal, not just that one happened. Issue #571: a per-parameter
    refusal renders a row, not the page-level notice."""
    policy = _policy()
    with _client(starter_project, policy) as client:
        _connect(client, policy)
        body = client.get(f"/devices/{DEV}/readings").text
        assert "Readings refused" not in body
        assert "refused" in body
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


# --- issue #571: per-parameter isolation on the readings page ----------------


class _PerParameterAdapter:
    """Answers identify and each parameter read independently: ``b``'s read
    is refused by the device, ``a`` and ``c`` answer standard receipts."""

    def __init__(self) -> None:
        self.services: Any = None

    async def open(self, descriptor: Any, services: Any, context: Any) -> None:
        self.services = services

    async def execute(self, request: dict[str, Any], context: Any) -> dict[str, Any]:
        await context.mark_dispatch_started()
        if request.get("verb") == "identify":
            return {
                "status": "ok",
                "data": {"manufacturer": "SDK Example", "model": "demo"},
            }
        name = request["arguments"]["parameter"]
        if name == "b":
            return {
                "status": "error",
                "error": {
                    "code": "DEVICE_REJECTED",
                    "message": "device refused this read in its current state",
                    "dispatch_state": "dispatched",
                },
            }
        return {"status": "ok", "data": _receipt(name)}

    async def next_event(self, subscription_id: Any, context: Any) -> None:
        return None

    async def close(self, context: Any) -> None:
        self.services = None


def _receipt(name: str) -> dict[str, Any]:
    return {
        "parameter": name,
        "value": {"a": 1.5, "c": 3.5}[name],
        "unit": "V",
        "observed_at": "2026-11-07T00:00:00Z",
        "age_ms": 0,
        "quality": "valid",
        "source": "device",
    }


def _refusing_project(starter_project: Path, tmp_path: Path) -> Path:
    """A presentation-free project declaring three readable parameters
    (``a`` ro, ``b`` rw, ``c`` ro) — the issue #571 fixture (design §6)."""
    plain = tmp_path / "isolation"
    shutil.copytree(starter_project, plain)
    package = plain / "src" / "example_plugin"
    for name in ("presentation.json", "binding-catalogue.json"):
        (package / name).unlink()
    shutil.rmtree(package / "ui")
    descriptor_path = package / "descriptor.json"
    descriptor = json.loads(descriptor_path.read_text())
    descriptor["parameters"] = [
        {
            "name": name,
            "description": f"Synthetic {name}",
            "type": "float",
            "access": access,
            "semantic": "setpoint" if access == "rw" else "measurement",
            "unit": "V",
            **({"range": [0.0, 5.0], "hazard_class": "unknown"} if access == "rw" else {}),
            "binding": {"kind": "adapter", "key": name},
            "read_policy": {"max_age_ms": 0, "destructive": False},
            **(
                {
                    "write_policy": {
                        "effect": "setting",
                        "completion": "readback",
                        "retry": "never",
                        "verification_parameter": name,
                        "settling_timeout_ms": 100,
                    }
                }
                if access == "rw"
                else {}
            ),
        }
        for name, access in (("a", "ro"), ("b", "rw"), ("c", "ro"))
    ]
    descriptor_path.write_text(json.dumps(descriptor))
    return plain


def _isolation_client(project: Path, policy: GuardPolicy) -> TestClient:
    plugin = replace(load_plugin_project(project), adapter_factory=_PerParameterAdapter)
    seam = StandaloneSeam(mock_plugin_session(plugin), transport_kind="mock")
    return TestClient(build_app(seam, policy=policy), base_url="http://127.0.0.1:8477")


def _rows_by_name(html: str) -> dict[str, str]:
    """The readings table's data rows, keyed by the row-header name."""
    if "<tbody>" not in html:
        return {}
    body = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    rows: dict[str, str] = {}
    for row in body.split("<tr>")[1:]:
        name = row.split('scope="row">', 1)[1].split("</th>", 1)[0]
        rows[name] = row
    return rows


def test_a_refused_parameter_does_not_blank_the_other_rows(
    starter_project: Path, tmp_path: Path
) -> None:
    """Issue #571 A1: three declared readable parameters, the device refuses
    exactly one — three rows render, two with their values, one marked
    refused. Denominator: 3 declared readable parameters."""
    policy = _policy()
    with _isolation_client(
        _refusing_project(starter_project, tmp_path), policy
    ) as client:
        _connect(client, policy)
        html = client.get(f"/devices/{DEV}/readings").text

    rows = _rows_by_name(html)
    assert len(rows) == 3, html
    assert "1.5" in rows["a"]
    assert "3.5" in rows["c"]
    assert "refused" in rows["b"]
    assert "conflict" in rows["b"]
    assert "DEVICE_REJECTED" in rows["b"]
    assert "dispatched" in rows["b"]
    assert "Readings refused" not in html


def test_the_device_page_and_the_polled_partial_agree(
    starter_project: Path, tmp_path: Path
) -> None:
    """Issue #571 A3: the inline device-page copy and the polled partial come
    from the same gather, so both isolate the same row."""
    policy = _policy()
    with _isolation_client(
        _refusing_project(starter_project, tmp_path), policy
    ) as client:
        _connect(client, policy)
        device = _rows_by_name(client.get(f"/devices/{DEV}").text)
        partial = _rows_by_name(client.get(f"/devices/{DEV}/readings").text)

    assert set(device) == set(partial) == {"a", "b", "c"}
    for surface in (device, partial):
        assert "refused" in surface["b"]
        assert "refused" not in surface["a"]
        assert "1.5" in surface["a"]
        assert "3.5" in surface["c"]


def test_a_degraded_load_still_refuses_the_whole_page(tmp_path: Path) -> None:
    """Issue #571 A2(b): a session-level refusal (not_ready from a degraded
    load) stays page-level — the notice, never per-row marks."""
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "degraded"
    create_project(project, "example_plugin")
    descriptor_path = project / "src" / "example_plugin" / "descriptor.json"
    descriptor = json.loads(descriptor_path.read_text())
    descriptor["integration"]["adapter"]["entry_point"] = (
        "example_plugin.absent:create_plugin"
    )
    descriptor_path.write_text(json.dumps(descriptor))

    plugin = load_plugin_project(project)
    seam = StandaloneSeam(
        PluginSession(plugin, lambda: None),  # type: ignore[arg-type]
        transport_kind="mock",
    )
    policy = _policy()
    with TestClient(
        build_app(seam, policy=policy), base_url="http://127.0.0.1:8477"
    ) as client:
        html = client.get(f"/devices/{DEV}/readings").text

    assert "Readings refused" in html
    assert "not_ready" in html
    assert "<table" not in html
