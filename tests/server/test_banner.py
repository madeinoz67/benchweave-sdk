"""The banner rule (§4.3): SIMULATED on mock only, STANDALONE on both."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.session import PluginSession, mock_exchanges
from benchweave_sdk_server.transport import LoopingMockHost
from benchweave_sdk_server.web import build_app

DEV = "example_device"
SIMULATED = "SIMULATED — mock transport"
STANDALONE = "STANDALONE — no gateway"

#: Pages are the shell-rendered surfaces (base.html). The readings partial
#: is an HTMX swap fragment served bare by design — it inherits the
#: enclosing page's banners, so banner assertions target the pages.
PAGES = ("/", f"/devices/{DEV}")


def _policy() -> GuardPolicy:
    return GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )


def _client(transport_kind: str, plugin) -> TestClient:
    seam = StandaloneSeam(
        PluginSession(plugin, lambda: LoopingMockHost(mock_exchanges(plugin))),
        transport_kind=transport_kind,
    )
    return TestClient(build_app(seam, policy=_policy()), base_url="http://127.0.0.1:8477")


def test_every_mock_page_carries_both_banners(plugin) -> None:
    with _client("mock", plugin) as client:
        for page in PAGES:
            body = client.get(page).text
            assert SIMULATED in body, page
            assert STANDALONE in body, page


def test_a_non_mock_transport_carries_no_simulated_banner(plugin) -> None:
    """The discrimination arm: over a transport kind that is not the mock,
    every page keeps the STANDALONE banner and asserts the simulated
    banner ABSENT (asserted absence, not mere silence). Real-hardware
    discrimination is exercised at I3; this pins the mechanism."""
    with _client("recording", plugin) as client:
        for page in PAGES:
            body = client.get(page).text
            assert STANDALONE in body, page
            assert SIMULATED not in body, page
            assert "banner-simulated" not in body, page


def test_scenario_mode_carries_the_simulated_banner(plugin) -> None:
    """Scenario mode implies mock (enforced), so scenario runs are
    banner-marked simulated — correct: they are simulated."""
    from benchweave_sdk_server.scenarios import ScenarioSelection, scenario_session

    seam = StandaloneSeam(
        scenario_session(plugin, ScenarioSelection("normal")), transport_kind="mock"
    )
    with TestClient(
        build_app(seam, policy=_policy()), base_url="http://127.0.0.1:8477"
    ) as client:
        body = client.get(f"/devices/{DEV}").text
        assert SIMULATED in body


def test_the_template_refuses_the_element_when_the_flag_is_false() -> None:
    """Template-level pin: base.html renders the simulated banner element
    iff the flag is true — the flag is a pure function of the transport
    kind, evaluated once per render from app.state.seam."""
    from pathlib import Path

    from jinja2 import Environment, FileSystemLoader, select_autoescape

    templates = Path(__file__).resolve().parents[2] / "src" / "benchweave_sdk_server" / "templates"
    env = Environment(
        loader=FileSystemLoader(templates), autoescape=select_autoescape(["html"])
    )
    base = env.get_template("base.html")

    def render(simulated: bool) -> str:
        return base.render(
            simulated=simulated,
            banner=STANDALONE,
            absent=["leases"],
            plugin={"package": "p", "plugin_version": "0", "descriptor_sha256": "0" * 12},
        )

    assert SIMULATED in render(True)
    assert SIMULATED not in render(False)
    assert STANDALONE in render(False)


@pytest.mark.parametrize("kind", ["mock", "recording"])
def test_the_flag_is_a_pure_function_of_the_transport_kind(plugin, kind) -> None:
    seam = StandaloneSeam(
        PluginSession(plugin, lambda: LoopingMockHost(mock_exchanges(plugin))),
        transport_kind=kind,
    )
    with TestClient(build_app(seam, policy=_policy()), base_url="http://127.0.0.1:8477") as client:
        body = client.get("/").text
        assert (SIMULATED in body) == (kind == "mock")
