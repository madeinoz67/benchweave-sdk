"""The nine baseline scenarios: definitions as data, scripts derived from
the descriptor, and the states served through the live pipeline (§4.2)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from benchweave_sdk.fixtures import BASELINE_IDS
from benchweave_sdk_server.scenarios import (
    SCENARIOS,
    ScenarioSelection,
    scenario_exchanges,
    scenario_session,
)
from benchweave_sdk_server.session import PluginLoadError
from benchweave_sdk_server.transport import LoopingMockHost


def _load(project: Path):
    from benchweave_sdk_server.session import load_plugin_project

    return load_plugin_project(project)


# --- the definitions ship as data -------------------------------------------


def test_the_nine_ids_are_the_baseline_set() -> None:
    assert tuple(row.id for row in SCENARIOS) == (
        "normal",
        "loading",
        "stale",
        "disconnected",
        "warning",
        "critical",
        "trip",
        "recovery",
        "request-rejected",
    )
    assert {row.id for row in SCENARIOS} == set(BASELINE_IDS)


def test_titles_come_from_the_baseline_rows() -> None:
    titles = {row.id: row.title for row in SCENARIOS}
    assert titles["normal"] == "Normal"
    assert titles["loading"] == "Loading"
    assert titles["trip"] == "Protective trip"
    assert titles["request-rejected"] == "Request rejected"


def test_unknown_scenario_refuses_with_a_prefix(plugin) -> None:
    with pytest.raises(PluginLoadError, match="standalone_scenario_unknown:"):
        scenario_exchanges(plugin, "nope")


# --- the scripts derive from the descriptor's own declarations --------------


def test_normal_script_is_establishment_then_one_read_per_parameter(plugin) -> None:
    script = scenario_exchanges(plugin, "normal")
    assert script[0][0]["data"] == b"ID?\n"
    assert script[0][1]["data"] == b"SDK Example,demo,example_device,1.0.0\n"
    assert script[1][0]["data"] == b"R:voltage\n"
    # The starter's voltage declares no range: the type-canonical float.
    assert script[1][1]["data"] == b"0.0,valid\n"


def test_the_quality_column_rides_the_script_bytes(plugin) -> None:
    for scenario_id, line in (
        ("normal", b"0.0,valid\n"),
        ("loading", b",loading\n"),
        ("stale", b"0.0,stale\n"),
        ("warning", b"0.0,warning\n"),
        ("critical", b"0.0,critical\n"),
        ("trip", b"0.0,trip\n"),
        ("recovery", b"0.0,recovering\n"),
    ):
        script = scenario_exchanges(plugin, scenario_id)
        assert script[1][1]["data"] == line, scenario_id


def test_disconnected_refuses_the_establishment(plugin) -> None:
    script = scenario_exchanges(plugin, "disconnected")
    assert len(script) == 1
    request, response = script[0]
    assert request["data"] == b"ID?\n"
    assert isinstance(response, ConnectionError)


def test_request_rejected_scripts_a_device_refusal_frame(plugin) -> None:
    script = scenario_exchanges(plugin, "request-rejected")
    assert script[1][0]["data"] == b"R:voltage\n"
    assert script[1][1]["data"] == b"!rejected\n"


def _range_plugin(parameter_type: str, extra: dict, tmp_path: Path):
    """A plain scaffold (no presentation envelope pinning the descriptor
    bytes) whose first parameter carries a declared range."""
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "ranged"
    create_project(project, "example_plugin")
    descriptor_path = project / "src" / "example_plugin" / "descriptor.json"
    document = json.loads(descriptor_path.read_text())
    parameter = document["parameters"][0]
    parameter["type"] = parameter_type
    parameter.update(extra)
    descriptor_path.write_text(json.dumps(document))
    return _load(project)


def test_a_declared_range_supplies_the_midpoint(tmp_path: Path) -> None:
    plugin = _range_plugin("float", {"range": [0.0, 5.0]}, tmp_path)
    script = scenario_exchanges(plugin, "normal")
    assert script[1][1]["data"] == b"2.5,valid\n"


def test_an_int_range_midpoint_stays_an_int(tmp_path: Path) -> None:
    plugin = _range_plugin("int", {"range": [0, 5]}, tmp_path)
    script = scenario_exchanges(plugin, "normal")
    assert script[1][1]["data"] == b"2,valid\n"


# --- the states serve through the live pipeline ------------------------------




@pytest.mark.parametrize(
    ("scenario_id", "quality"),
    [
        ("normal", "valid"),
        ("stale", "stale"),
        ("warning", "warning"),
        ("critical", "critical"),
        ("trip", "trip"),
        ("recovery", "recovering"),
    ],
)
def test_value_states_serve_the_scripted_quality(plugin, scenario_id, quality) -> None:
    session = scenario_session(plugin, ScenarioSelection(scenario_id))

    async def run() -> None:
        await session.connect()
        envelope = await session.execute("read", {"parameter": "voltage"})
        assert envelope["status"] == "ok"
        assert envelope["data"]["quality"] == quality
        assert envelope["data"]["value"] == 0.0
        assert envelope["data"]["source"] == "scenario"
        await session.close()

    asyncio.run(run())


def test_loading_serves_an_absent_value(plugin) -> None:
    session = scenario_session(plugin, ScenarioSelection("loading"))

    async def run() -> None:
        await session.connect()
        envelope = await session.execute("read", {"parameter": "voltage"})
        assert envelope["status"] == "ok"
        assert envelope["data"]["value"] is None
        assert envelope["data"]["quality"] == "loading"
        await session.close()

    asyncio.run(run())


def test_disconnected_fails_the_connect(plugin) -> None:
    session = scenario_session(plugin, ScenarioSelection("disconnected"))

    async def run() -> None:
        with pytest.raises(RuntimeError, match="standalone_connect_failed"):
            await session.connect()
        assert not session.connected
        await session.close()

    asyncio.run(run())


def test_request_rejected_yields_a_dispatched_device_rejection(plugin) -> None:
    session = scenario_session(plugin, ScenarioSelection("request-rejected"))

    async def run() -> None:
        await session.connect()
        envelope = await session.execute("read", {"parameter": "voltage"})
        assert envelope["status"] == "error"
        assert envelope["error"]["code"] == "DEVICE_REJECTED"
        assert envelope["error"]["dispatch_state"] == "dispatched"
        await session.close()

    asyncio.run(run())


def test_identity_comes_from_the_descriptor(plugin) -> None:
    session = scenario_session(plugin, ScenarioSelection("normal"))

    async def run() -> None:
        await session.connect()
        assert session.identity == {
            "manufacturer": "SDK Example",
            "model": "demo",
            "serial": "example_device",
            "firmware": "1.0.0",
            "source": "scenario",
        }
        await session.close()

    asyncio.run(run())


def test_removing_the_script_rows_surfaces_an_honest_refusal(plugin) -> None:
    """The B-S RED control (unit arm): the states ride the transport script,
    never a template constant — delete the read rows and the read refuses
    (the recycled establishment cannot answer a read)."""
    from dataclasses import replace

    from benchweave_sdk.testing import ConformanceError
    from benchweave_sdk_server.scenarios import ScenarioAdapter
    from benchweave_sdk_server.session import PluginSession

    script = scenario_exchanges(plugin, "normal")
    severed = [script[0]]  # establishment only: the read rows are gone
    session = PluginSession(
        replace(plugin, adapter_factory=ScenarioAdapter),
        lambda: LoopingMockHost(severed),
    )

    async def run() -> None:
        await session.connect()
        with pytest.raises(ConformanceError):
            await session.execute("read", {"parameter": "voltage"})
        await session.close()

    asyncio.run(run())


# --- the selection holder ----------------------------------------------------


def test_selection_validates_ids() -> None:
    selection = ScenarioSelection("normal")
    assert selection.current == "normal"
    selection.select("stale")
    assert selection.current == "stale"
    with pytest.raises(ValueError, match="standalone_scenario_unknown:"):
        selection.select("nope")
