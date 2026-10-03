"""The slice-B acceptance suite: the nine baseline states through the
REAL surface, both arms (the HTML readings partial AND REST), with the
script-removal RED control (design §7, gate B-S)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk_server.cli import _build_seam
from benchweave_sdk_server.scenarios import ScenarioAdapter, ScenarioSelection, scenario_exchanges
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.session import PluginSession
from benchweave_sdk_server.transport import LoopingMockHost
from benchweave_sdk_server.web import build_app

DEV = "example_device"

#: Each scenario's expected observation, asserted identically over both
#: arms: the quality string, whether the HTML shows a value, and the
#: refusal class (None = the read serves).
EXPECTED = {
    "normal": {"quality": "valid", "value": "0.0", "refusal": None},
    "loading": {"quality": "loading", "value": "", "refusal": None},
    "stale": {"quality": "stale", "value": "0.0", "refusal": None},
    "disconnected": {"quality": None, "value": None, "refusal": "connect_not_ready"},
    "warning": {"quality": "warning", "value": "0.0", "refusal": None},
    "critical": {"quality": "critical", "value": "0.0", "refusal": None},
    "trip": {"quality": "trip", "value": "0.0", "refusal": None},
    "recovery": {"quality": "recovering", "value": "0.0", "refusal": None},
    "request-rejected": {"quality": None, "value": None, "refusal": "device_rejected"},
}


def _policy() -> GuardPolicy:
    return GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )


def _scenario_client(starter_project: Path, scenario_id: str, policy: GuardPolicy):
    seam, _ = _build_seam(starter_project, scenario=scenario_id)
    app = build_app(seam, policy=policy)
    return TestClient(app, base_url="http://127.0.0.1:8477")


def _read_rest(client: TestClient, policy: GuardPolicy):
    return client.post(
        "/v1/parameter_read",
        json={"device_id": DEV, "parameter": "voltage"},
        headers={"authorization": f"Bearer {policy.bearer_token}"},
    )


@pytest.mark.parametrize("scenario_id", list(EXPECTED))
def test_the_nine_through_the_real_surface_both_arms(
    starter_project: Path, scenario_id: str
) -> None:
    """Gate B-S: freshly scaffolded --with-ui project, --scenario <id>,
    connect, then the same observation over the HTML partial and REST."""
    policy = _policy()
    expected = EXPECTED[scenario_id]
    with _scenario_client(starter_project, scenario_id, policy) as client:
        connect = client.post(
            f"/devices/{DEV}/connect",
            headers={"x-csrf-token": policy.csrf_token},
            follow_redirects=False,
        )
        if expected["refusal"] == "connect_not_ready":
            # Through the pipeline, disconnected IS a refused connection:
            # REST answers not_ready and the page renders the refused state.
            rest_connect = client.post(
                "/v1/device_connect",
                json={"device_id": DEV},
                headers={"authorization": f"Bearer {policy.bearer_token}"},
            )
            assert rest_connect.status_code == 409
            assert rest_connect.json()["error"]["code"] == "not_ready"
            html = client.post(
                f"/devices/{DEV}/connect",
                headers={"x-csrf-token": policy.csrf_token},
                follow_redirects=True,
            ).text
            assert "Connect refused" in html
            assert "not_ready" in html
            assert connect.status_code == 200  # the rendered refusal
            return

        assert connect.status_code == 303

        # HTML arm: the readings partial.
        html = client.get(f"/devices/{DEV}/readings").text
        # REST arm: the same read over JSON.
        rest = _read_rest(client, policy)

        if expected["refusal"] == "device_rejected":
            assert rest.status_code == 409
            body = rest.json()
            assert body["error"]["code"] == "conflict"
            assert body["error"]["details"]["adapter"]["code"] == "DEVICE_REJECTED"
            assert body["error"]["details"]["adapter"]["dispatch_state"] == "dispatched"
            assert "Readings refused" in html
            assert "DEVICE_REJECTED" in html
            return

        # The no-laundering pin: both arms serve the SAME value and quality.
        assert rest.status_code == 200
        data = rest.json()["data"]
        assert data["quality"] == expected["quality"]
        if expected["value"]:
            assert str(data["value"]) == expected["value"]
            assert expected["value"] in html
        else:
            assert data["value"] is None
        assert expected["quality"] in html


def test_b_s_red_control_deleted_script_rows_surface_honest_refusals(
    starter_project: Path,
) -> None:
    """Gate B-S's RED control: delete the scenario's read rows and the
    reads surface unavailable/not_ready honestly — the states come from
    the transport, never template constants."""
    from benchweave_sdk_server.session import load_plugin_project

    plugin = load_plugin_project(starter_project)
    script = scenario_exchanges(plugin, "normal")
    severed = [script[0]]  # establishment only
    selection = ScenarioSelection("normal")
    seam = StandaloneSeam(
        PluginSession(
            replace(plugin, adapter_factory=ScenarioAdapter),
            lambda: LoopingMockHost(severed),
        ),
        transport_kind="mock",
    )
    policy = _policy()
    with TestClient(build_app(seam, policy=policy), base_url="http://127.0.0.1:8477") as client:
        client.post(
            f"/devices/{DEV}/connect",
            headers={"x-csrf-token": policy.csrf_token},
            follow_redirects=False,
        )
        rest = _read_rest(client, policy)
        assert rest.status_code == 503
        assert rest.json()["error"]["code"] == "unavailable"
        html = client.get(f"/devices/{DEV}/readings").text
        assert "Readings refused" in html
        assert "unavailable" in html
        assert selection.current == "normal"
