"""The mode banner rule (§4.3 → §D.1, I2a): one contract component.

``render_mode_banner`` carries the entries: the three standalone truths
always (SW-27/SW-32), ``simulated`` iff the transport is the mock (#309-B's
rule). The I1 hand banner and its second banner element are retired; the
wordings are the package's own §D.1 literals, import-compared.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk_server.presentation import mode_banner_entries
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.session import PluginSession, mock_exchanges
from benchweave_sdk_server.transport import LoopingMockHost
from benchweave_sdk_server.web import build_app

DEV = "example_device"
SIMULATED_WORDING = "SIMULATED PRESENTATION DATA"
NO_GATEWAY = "NO GATEWAY · LOCAL PRESENTATION ONLY"
NO_LEASE = "NO CONTROLLER LEASE · ACTIONS CANNOT BE AUTHORISED"
NO_POLICY = "NO POLICY ENGINE · POLICY CHECKS UNAVAILABLE"

#: Pages are the shell-rendered surfaces (base.html). Partials are HTMX
#: swap fragments served bare by design — they inherit the enclosing page's
#: banner, so banner assertions target the pages.
PAGES = ("/", f"/devices/{DEV}", "/pages/readings")


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


def test_every_mock_page_carries_all_four_entries(plugin) -> None:
    with _client("mock", plugin) as client:
        for page in PAGES:
            body = client.get(page).text
            for wording in (SIMULATED_WORDING, NO_GATEWAY, NO_LEASE, NO_POLICY):
                assert wording in body, (page, wording)


def test_a_non_mock_transport_carries_no_simulated_entry(plugin) -> None:
    """The discrimination arm: over a transport kind that is not the mock,
    every page keeps the three standalone entries and asserts the
    simulated entry ABSENT (asserted absence, not mere silence).
    Real-hardware discrimination is exercised at I3; this pins the
    mechanism."""
    with _client("recording", plugin) as client:
        for page in PAGES:
            body = client.get(page).text
            for wording in (NO_GATEWAY, NO_LEASE, NO_POLICY):
                assert wording in body, (page, wording)
            assert SIMULATED_WORDING not in body, page
            assert 'data-bw-mode="simulated"' not in body, page


def test_scenario_mode_carries_the_simulated_entry(plugin) -> None:
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
        assert SIMULATED_WORDING in body


def test_the_entries_are_the_package_fixture_wordings() -> None:
    """Import-compared (no second copy of the literals): each entry's
    wording equals the package's own §D.1 mode-row wording for its key."""
    from benchweave_ui_html.fixtures import MODES

    package = {entry.key: entry.wording for entry in MODES}
    for simulated in (True, False):
        for entry in mode_banner_entries(simulated=simulated).modes:
            assert entry.wording == package[entry.key], entry.key


def test_the_base_template_renders_the_component_iff_the_flag_is_true() -> None:
    """Template-level pin: base.html renders the banner component markup
    through the pre-rendered §D.1 partial — the flag is a pure function of
    the transport kind, evaluated once per render."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from markupsafe import Markup

    from benchweave_sdk_server.presentation import mode_banner_html

    templates = Path(__file__).resolve().parents[2] / "src" / "benchweave_sdk_server" / "templates"
    env = Environment(
        loader=FileSystemLoader(templates), autoescape=select_autoescape(["html"])
    )
    base = env.get_template("base.html")

    def render(simulated: bool) -> str:
        return base.render(
            mode_banner=Markup(mode_banner_html(simulated=simulated)),
            absent=["leases"],
            plugin={"package": "p", "plugin_version": "0", "descriptor_sha256": "0" * 12},
        )

    assert "data-bw-mode-banner" in render(True)
    assert SIMULATED_WORDING in render(True)
    assert SIMULATED_WORDING not in render(False)
    assert NO_GATEWAY in render(False)


@pytest.mark.parametrize("kind", ["mock", "recording"])
def test_the_flag_is_a_pure_function_of_the_transport_kind(plugin, kind) -> None:
    with _client(kind, plugin) as client:
        body = client.get("/").text
        assert (SIMULATED_WORDING in body) == (kind == "mock")
