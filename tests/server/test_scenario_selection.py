"""Scenario selection: the CLI flag, the off-mock refusal, and the
device-page select (§4.2 selection; §4.1's composition step)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk_server.cli import _build_seam
from benchweave_sdk_server.scenarios import ScenarioSelection, scenario_session
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.web import build_app

DEV = "example_device"


def _policy() -> GuardPolicy:
    return GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )


def test_build_seam_composes_the_scenario_session(starter_project: Path) -> None:
    seam, selection = _build_seam(starter_project, scenario="stale")
    assert seam.transport_kind == "mock"
    assert selection is not None and selection.current == "stale"

    async def run() -> None:
        await seam.session.connect()
        envelope = await seam.session.execute("read", {"parameter": "voltage"})
        assert envelope["data"]["quality"] == "stale"
        await seam.session.close()

    asyncio.run(run())


def test_build_seam_without_a_scenario_is_the_vectors_mock(starter_project: Path) -> None:
    seam, selection = _build_seam(starter_project)
    assert seam.transport_kind == "mock"
    assert selection is None

    async def run() -> None:
        await seam.session.connect()
        envelope = await seam.session.execute("read", {"parameter": "voltage"})
        assert envelope["data"]["value"] == 3.3
        assert envelope["data"]["source"] == "device"
        await seam.session.close()

    asyncio.run(run())


def test_a_scenario_off_the_mock_transport_refuses(starter_project: Path, capsys) -> None:
    """Scenarios do not exist on real hardware — the banner rule's sibling."""
    with pytest.raises(SystemExit) as exc:
        _build_seam(starter_project, transport="serial", scenario="normal")
    assert exc.value.code == 2
    assert "standalone_scenario_mock_only:" in capsys.readouterr().err


def test_the_cli_scenario_flag_accepts_the_nine(starter_project: Path) -> None:
    from click.testing import CliRunner

    from benchweave_sdk_server.cli import cli

    result = CliRunner().invoke(
        cli, ["serve", str(starter_project), "--scenario", "nope", "--no-open"]
    )
    assert result.exit_code == 2
    assert "Invalid value" in result.output


# --- the device-page select ----------------------------------------------------


def _scenario_client(plugin, selection: ScenarioSelection, policy: GuardPolicy):
    seam = _seam_over(plugin, selection)
    app = build_app(seam, policy=policy, scenario=selection)
    return TestClient(app, base_url="http://127.0.0.1:8477")


def _seam_over(plugin, selection: ScenarioSelection):
    from benchweave_sdk_server.seam import StandaloneSeam

    return StandaloneSeam(scenario_session(plugin, selection), transport_kind="mock")


def test_the_device_page_offers_the_nine(plugin, policy) -> None:
    with _scenario_client(plugin, ScenarioSelection("normal"), policy) as client:
        body = client.get(f"/devices/{DEV}").text
        for title in ("Normal", "Loading", "Stale", "Protective trip", "Request rejected"):
            assert title in body
        assert 'name="scenario"' in body


def test_the_plain_mock_serves_no_select(client) -> None:
    """The select is a scenario-mode surface; the vectors mock has nothing
    to switch (scenario switching is NOT a catalogue op — D-B1)."""
    body = client.get(f"/devices/{DEV}").text
    assert 'name="scenario"' not in body


def test_switching_serves_the_new_scenario_on_reconnect(plugin, policy) -> None:
    selection = ScenarioSelection("normal")
    with _scenario_client(plugin, selection, policy) as client:
        response = client.post(
            f"/devices/{DEV}/scenario",
            headers={"x-csrf-token": policy.csrf_token},
            data={"scenario": "critical"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert selection.current == "critical"
        # The switch mutates the NEXT connection's script: reconnect and
        # the critical quality serves through the pipeline.
        client.post(
            f"/devices/{DEV}/connect",
            headers={"x-csrf-token": policy.csrf_token},
            follow_redirects=False,
        )
        body = client.get(f"/devices/{DEV}/readings").text
        assert "critical" in body


def test_switching_to_an_unknown_id_renders_the_refusal(plugin, policy) -> None:
    selection = ScenarioSelection("normal")
    with _scenario_client(plugin, selection, policy) as client:
        response = client.post(
            f"/devices/{DEV}/scenario",
            headers={"x-csrf-token": policy.csrf_token},
            data={"scenario": "nope"},
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "standalone_scenario_unknown" in response.text
        assert selection.current == "normal"


def test_the_select_requires_the_csrf_token(plugin, policy) -> None:
    selection = ScenarioSelection("normal")
    with _scenario_client(plugin, selection, policy) as client:
        response = client.post(
            f"/devices/{DEV}/scenario", data={"scenario": "stale"}, follow_redirects=False
        )
        assert response.status_code == 403
        assert selection.current == "normal"
