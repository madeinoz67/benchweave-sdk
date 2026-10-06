"""The presentation render (I2a §3.1–3.2): the manifest is the page set.

The host renders the ALREADY-VALIDATED presentation model — pages at
``/pages/{id}``, reading tiles through the package's own
``render_reading`` partial, severity composed through the baseline-pinned
quality map, staleness computed from the descriptor's own window — and it
invents no second projection of the manifest.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk.fixtures import generate_baselines
from benchweave_sdk_server import catalogue
from benchweave_sdk_server.presentation import (
    QUALITY_SEVERITY,
    SUPPORTED_FEATURES,
    SUPPORTED_PANELS,
    compose_severity,
    reading_tile_html,
)
from benchweave_sdk_server.scenarios import SCENARIOS
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.session import PluginSession, mock_exchanges
from benchweave_sdk_server.transport import LoopingMockHost
from benchweave_sdk_server.web import build_app

DEV = "example_device"
NO_GATEWAY = "NO GATEWAY · LOCAL PRESENTATION ONLY"


def _policy() -> GuardPolicy:
    return GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )


def _client(seam: StandaloneSeam) -> tuple[TestClient, GuardPolicy]:
    """The app AND its policy: REST mutations carry the launch bearer
    (NFR-S3), so tests need the token the app was built with."""
    policy = _policy()
    app = build_app(seam, policy=policy)
    return TestClient(app, base_url="http://127.0.0.1:8477"), policy


@pytest.fixture()
def connected(plugin) -> Iterator[tuple[TestClient, GuardPolicy]]:
    seam = StandaloneSeam(
        PluginSession(plugin, lambda: LoopingMockHost(mock_exchanges(plugin))),
        transport_kind="mock",
    )
    client, policy = _client(seam)
    with client:
        token = _csrf_via_page(client)
        client.post(f"/devices/{DEV}/connect", headers={"x-csrf-token": token})
        yield client, policy


def _csrf_via_page(client: TestClient) -> str:
    """The page-delivered CSRF token (rendered into every page, NFR-S3)."""
    body = client.get(f"/devices/{DEV}").text
    marker = 'hx-headers=\'{"X-CSRF-Token": "'
    return body.split(marker, 1)[1].split('"', 1)[0]


# --- the host's declared feature/panel sets (SW-41) ---------------------------


def test_the_host_declares_its_supported_features_and_panels() -> None:
    """Data, not inference: the feature set names what this host renders
    and the panel set is empty (no class/custom panel ships)."""
    assert SUPPORTED_FEATURES, "the host must declare the features it renders"
    assert frozenset() == SUPPORTED_PANELS


def test_a_required_feature_the_host_lacks_refuses_the_load(
    starter_project: Path, tmp_path: Path
) -> None:
    """SW-41's refusing arm, end to end: a manifest whose
    required_ui_features names an id outside the host's set fails
    validation at load — before any port binds (SW-05)."""
    from benchweave_sdk_server.session import PluginLoadError, load_plugin_project

    project = _scaffold_with_manifest_extension(
        tmp_path / "feature-gap", required_ui_features=["hologram-view/1.0.0"]
    )
    with pytest.raises(PluginLoadError, match="standalone_plugin_invalid"):
        load_plugin_project(project)


# --- the quality→severity map is pinned to the SDK's own baselines ------------


def test_the_quality_severity_map_is_pinned_to_the_baseline_rows(starter_project) -> None:
    """The two tables cannot drift silently: for every baseline scenario,
    the severity the host composes from the LIVE pipeline's state equals
    ``generate_baselines``' own ``expected_severity`` row (the SDK's
    baseline model is the authority — the parity oracle's unit arm)."""
    from benchweave_sdk_server.presentation import load_host_presentation

    plugin = _load(starter_project)
    presentation = load_host_presentation(plugin)
    manifest = presentation.manifest
    catalogue_document = presentation.binding_catalogue
    rows = {
        row.id: row.expected_severity
        for row in generate_baselines(catalogue_document, manifest)
    }
    live_qualities = {"disconnected": None, "request-rejected": None}
    for scenario in SCENARIOS:
        if scenario.id in live_qualities:
            continue
        severity = QUALITY_SEVERITY[scenario.quality]
        assert severity == rows[scenario.id], scenario.id
    # The refusal classes compose through their own contributions.
    assert compose_severity(["critical"]) == rows["disconnected"]
    assert compose_severity(["warning"]) == rows["request-rejected"]


def test_the_map_is_closed_over_the_live_quality_vocabulary() -> None:
    """Every quality string the nine scenarios serve is a key, and an
    unknown quality string renders neutral severity with the string
    verbatim in the quality slot (ST-3's two-channels rule)."""
    for scenario in SCENARIOS:
        if scenario.quality:
            assert scenario.quality in QUALITY_SEVERITY, scenario.id
    assert "device-good" not in QUALITY_SEVERITY
    html, severity = reading_tile_html(
        read={"value": 1.0, "unit": "V", "quality": "device-good", "age_ms": 10},
        parameter={},
        label="supply",
    )
    assert severity == "neutral"
    assert "device-good" in html


# --- the mode banner: one §D.1 component, wordings import-compared ------------


def test_the_mode_banner_replaces_both_i1_banners(connected) -> None:
    """One contract component (SW-27/SW-32/#309-B's rule): mock pages carry
    the simulated entry plus the three standalone truths; the I1 hand
    banner and the second banner element are gone."""
    client, _ = connected
    body = client.get("/").text
    assert "data-bw-mode-banner" in body
    assert NO_GATEWAY in body
    assert "SIMULATED PRESENTATION DATA" in body
    assert "STANDALONE — no gateway" not in body
    assert "SIMULATED — mock transport" not in body
    assert "banner-simulated" not in body


def test_the_simulated_entry_follows_the_transport_kind(plugin) -> None:
    seam = StandaloneSeam(
        PluginSession(plugin, lambda: LoopingMockHost(mock_exchanges(plugin))),
        transport_kind="recording",
    )
    client, _ = _client(seam)
    with client:
        body = client.get("/").text
        assert NO_GATEWAY in body
        assert "SIMULATED PRESENTATION DATA" not in body


def test_the_banner_wordings_come_from_the_package_fixture() -> None:
    """Import-compared, not copied: every host banner wording is the
    package's own §D.1 mode-row wording for the same key."""
    from benchweave_ui_html.fixtures import MODES

    from benchweave_sdk_server.presentation import mode_banner_entries

    for simulated in (True, False):
        entries = mode_banner_entries(simulated=simulated).modes
        wordings = {entry.key: entry.wording for entry in entries}
        package = {entry.key: entry.wording for entry in MODES}
        for key, wording in wordings.items():
            assert wording == package[key], key
        assert ("simulated" in wordings) == simulated
        for standalone in ("no-gateway", "no-lease", "no-policy"):
            assert standalone in wordings


# --- the pages ----------------------------------------------------------------


def test_the_readings_page_renders_tiles_through_the_package_partial(
    connected,
) -> None:
    """Component parity's unit arm: the page contains the EXACT
    ``render_reading`` output built from the live read — a hand-rolled
    tile cannot pass an exact-substring containment."""
    from benchweave_ui_html.data import ReadingData
    from benchweave_ui_html.partials import render_reading

    client, policy = connected
    read = client.post(
        "/v1/parameter_read",
        json={"device_id": DEV, "parameter": "voltage"},
        headers={"authorization": f"Bearer {policy.bearer_token}"},
    )
    assert read.status_code == 200
    expected = render_reading(
        ReadingData(
            label="voltage",
            severity="neutral",
            value="3.3",
            unit="V",
            quality="valid",
            freshness="0 ms",
            stale_verdict="fresh",
        )
    )
    page = client.get("/pages/readings")
    assert page.status_code == 200
    assert expected in page.text


def test_the_page_carries_its_composed_severity(connected) -> None:
    client, _ = connected
    body = client.get("/pages/readings").text
    assert 'data-bw-page-severity="neutral"' in body


def test_the_index_links_the_manifest_pages(connected) -> None:
    client, _ = connected
    body = client.get("/").text
    assert 'href="/pages/readings"' in body


def test_an_unknown_page_is_404(connected) -> None:
    client, _ = connected
    assert client.get("/pages/no-such-page").status_code == 404


def test_a_panel_page_the_host_lacks_renders_the_refusal(
    starter_project: Path, tmp_path: Path
) -> None:
    """SW-41: an optional panel the host does not carry renders the
    panel_unavailable refusal on its page and lands in host_info."""
    project = _scaffold_with_manifest_extension(
        tmp_path / "panel-page",
        extra_pages=[
            {
                "id": "vendor-view",
                "title": "Vendor view",
                "kind": "custom_panel",
                "panel_id": "vendor-panel/1.0.0",
                "bindings": [],
                "required": False,
            }
        ],
    )
    from benchweave_sdk_server.cli import _build_seam

    seam, _ = _build_seam(project)
    client, _policy_unused = _client(seam)
    with client:
        page = client.get("/pages/vendor-view")
        assert page.status_code == 200
        assert "panel_unavailable" in page.text
        assert "vendor-panel/1.0.0" in page.text
        # Fold 4: the honesty channel states the TRUE state - a panel page
        # renders its refusal and nothing below (the host skips binding
        # gathering for panel pages), so the notice must not claim bindings
        # render below.
        assert "render below" not in page.text
        assert "no bindings" in page.text
        info = client.post(
            "/v1/host_info", json={}, headers={"authorization": "Bearer x"}
        )
        # The bearer guard refuses REST mutations without the launch token
        # — read the presentation block through a second seam-level check.
        assert info.status_code == 403

        async def host_info() -> dict:

            return await seam.call("host_info", {})

        import asyncio

        presentation = asyncio.run(host_info())["presentation"]
        assert presentation["unavailable_pages"] == ["vendor-view"]
        assert sorted(presentation["features"]) == sorted(SUPPORTED_FEATURES)
        assert presentation["panels"] == []


def test_host_info_names_the_presentation_block(client: TestClient, policy) -> None:
    info = client.post(
        "/v1/host_info", json={}, headers={"authorization": f"Bearer {policy.bearer_token}"}
    ).json()["data"]
    assert set(info["presentation"]) == {"features", "panels", "unavailable_pages"}
    # The MCP-visible result schema carries the same block (CON-3).
    schema = catalogue.spec("host_info").result_schema
    assert schema is not None and "presentation" in schema["properties"]


def test_host_info_validates_over_mcp_structured_output(starter_project) -> None:
    """The schema pin extends with the block (CON-3): fastmcp validates the
    structured output against the catalogue's result schema — a mismatch
    between the seam's output and the pinned schema refuses here."""
    import asyncio

    from fastmcp import Client

    from benchweave_sdk_server.mcp import build_mcp
    from benchweave_sdk_server.session import load_plugin_project

    plugin = load_plugin_project(starter_project)
    seam = StandaloneSeam(
        PluginSession(plugin, lambda: LoopingMockHost(mock_exchanges(plugin))),
        transport_kind="mock",
    )

    async def run() -> None:
        async with Client(build_mcp(seam)) as client:
            result = await client.call_tool("bws_v1_host_info", {})
        data = result.structured_content or {}
        assert set(data["presentation"]) == {"features", "panels", "unavailable_pages"}
        # The link block (issue #407) is additive and null on the mock —
        # the structured output validates against the same schema only
        # because the block is declared there.
        assert data["link"] is None

    asyncio.run(run())


def test_globals_css_serves_the_installed_package_bytes(client: TestClient) -> None:
    from benchweave_ui_html.assets import ASSETS_DIR

    served = client.get("/assets/globals.css")
    assert served.status_code == 200
    assert served.content == (ASSETS_DIR / "globals.css").read_bytes()


# --- helpers ------------------------------------------------------------------


def _load(project: Path):
    from benchweave_sdk_server.session import load_plugin_project

    return load_plugin_project(project)


def _scaffold_with_manifest_extension(
    destination: Path,
    *,
    extra_pages: list[dict] | None = None,
    required_ui_features: list[str] | None = None,
) -> Path:
    """A scaffolded ``--with-ui`` project whose manifest carries the extra
    pages (digests recomputed — the envelope pins the manifest bytes)."""
    import hashlib

    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    create_project(destination, "example_plugin")
    create_ui_resources(destination, "example_plugin")
    package = destination / "src" / "example_plugin"
    manifest_path = package / "ui" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if extra_pages:
        manifest["pages"].extend(extra_pages)
    if required_ui_features:
        manifest["required_ui_features"] = required_ui_features
    raw = (json.dumps(manifest, indent=2) + "\n").encode()
    manifest_path.write_bytes(raw)
    envelope_path = package / "presentation.json"
    envelope = json.loads(envelope_path.read_text())
    envelope["manifest"]["sha256"] = hashlib.sha256(raw).hexdigest()
    envelope_path.write_text(json.dumps(envelope, indent=2) + "\n")
    return destination


def test_the_descriptor_window_drives_the_staleness_verdict(
    starter_project: Path, tmp_path: Path
) -> None:
    """ST-2's boundary, live: equality renders fresh, +1 renders stale with
    the marker; a descriptor with no declared window renders NO verdict
    (ST-3) — the honest negatives."""
    import shutil

    bounded = tmp_path / "bounded"
    shutil.copytree(starter_project, bounded)
    _edit_read_policy(bounded, max_age_ms=500)
    plugin = replace(_load(bounded), adapter_factory=None)
    plugin = _with_controlled_age_adapter(plugin, age_ms=500)
    seam = StandaloneSeam(
        PluginSession(plugin, lambda: _scripted(plugin)),
        transport_kind="mock",
    )
    client, _unused = _client(seam)
    with client:
        client.post(f"/devices/{DEV}/connect", headers={"x-csrf-token": _csrf_via_page(client)})
        body = client.get("/pages/readings").text
        assert "bw-reading__value" in body, "the tile must render (fresh arm)"
        assert "bw-reading--stale" not in body
        assert 'data-bw-stale="true"' not in body

    stale_plugin = _with_controlled_age_adapter(_load(bounded), age_ms=501)
    seam = StandaloneSeam(
        PluginSession(stale_plugin, lambda: _scripted(stale_plugin)),
        transport_kind="mock",
    )
    client, _unused = _client(seam)
    with client:
        client.post(f"/devices/{DEV}/connect", headers={"x-csrf-token": _csrf_via_page(client)})
        body = client.get("/pages/readings").text
        assert "bw-reading__value" in body, "the tile must render before staleness means anything"
        assert "bw-reading--stale" in body
        assert 'data-bw-stale="true"' in body
        assert "stale-marker" in body

    # ST-3's honest negative is UNIT-pinned: a validated descriptor cannot
    # omit read_policy on a readable parameter (validate_descriptor requires
    # it), so "no declared window" never reaches the HTTP surface through
    # the validated load path — the no-verdict branch is the tile builder's
    # defensive arm, pinned here at the mechanism it actually guards.
    tile, _severity = reading_tile_html(
        {"value": 3.3, "unit": "V", "quality": "valid", "age_ms": 999},
        {"name": "voltage", "unit": "V"},
        label="voltage",
    )
    assert "bw-reading__value" in tile
    assert "bw-reading--stale" not in tile
    assert 'data-bw-stale="true"' not in tile


def _edit_read_policy(project: Path, *, max_age_ms: int) -> None:
    descriptor_path = project / "src" / "example_plugin" / "descriptor.json"
    document = json.loads(descriptor_path.read_text())
    document["parameters"][0]["read_policy"] = {
        "max_age_ms": max_age_ms,
        "destructive": False,
    }
    _rewrite_descriptor_and_repin(project, document)


def _rewrite_descriptor_and_repin(project: Path, document: dict) -> None:
    """Rewrite the descriptor and re-pin its digest in every presentation
    document (the envelope, manifest and catalogue all carry it)."""
    import hashlib

    package = project / "src" / "example_plugin"
    raw = (json.dumps(document, indent=2) + "\n").encode()
    (package / "descriptor.json").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    manifest_path = package / "ui" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["descriptor_sha256"] = digest
    manifest_raw = (json.dumps(manifest, indent=2) + "\n").encode()
    manifest_path.write_bytes(manifest_raw)
    envelope_path = package / "presentation.json"
    envelope = json.loads(envelope_path.read_text())
    envelope["descriptor_sha256"] = digest
    envelope["manifest"]["sha256"] = hashlib.sha256(manifest_raw).hexdigest()
    envelope_path.write_text(json.dumps(envelope, indent=2) + "\n")
    catalogue_path = package / "binding-catalogue.json"
    catalogue_document = json.loads(catalogue_path.read_text())
    catalogue_document["descriptor_sha256"] = digest
    catalogue_path.write_text(json.dumps(catalogue_document, indent=2) + "\n")


def _with_controlled_age_adapter(plugin, *, age_ms: int):
    """A scripted adapter serving a controlled ``age_ms`` (test-only)."""
    from benchweave_sdk_server.session import LoadedPlugin

    class ControlledAgeAdapter:
        def __init__(self) -> None:
            self.services = None
            self.closed = False

        async def open(self, descriptor, services, context) -> None:
            self.services = services

        async def execute(self, request, context):
            verb = request.get("verb")
            operation_id = request.get("operation_id")
            await context.mark_dispatch_started()
            if verb == "identify":
                await self.services.transfer(
                    {
                        "kind": "stream_exchange",
                        "data": b"ID?\n",
                        "max_bytes": 128,
                        "termination": "lf",
                        "exact_bytes": None,
                    },
                    context,
                )
                return {
                    "operation_id": operation_id,
                    "verb": verb,
                    "status": "ok",
                    "data": {
                        "manufacturer": "SDK Example",
                        "model": "demo",
                        "serial": DEV,
                        "firmware": "1.0.0",
                        "source": "controlled",
                    },
                }
            response = await self.services.transfer(
                {
                    "kind": "stream_exchange",
                    "data": b"V?\n",
                    "max_bytes": 128,
                    "termination": "lf",
                    "exact_bytes": None,
                },
                context,
            )
            value = float(response["data"][:-1])
            return {
                "operation_id": operation_id,
                "verb": verb,
                "status": "ok",
                "data": {
                    "parameter": "voltage",
                    "value": value,
                    "unit": "V",
                    "observed_at": self.services.utc_now(),
                    "age_ms": age_ms,
                    "quality": "valid",
                    "source": "controlled",
                },
            }

        async def next_event(self, subscription_id, context):
            return None

        async def close(self, context) -> None:
            if self.closed:
                return
            self.closed = True
            if self.services is not None:
                await self.services.close_transport(context)

    return LoadedPlugin(
        project_root=plugin.project_root,
        package=plugin.package,
        descriptor=plugin.descriptor,
        descriptor_sha256=plugin.descriptor_sha256,
        plugin_version=plugin.plugin_version,
        adapter_factory=ControlledAgeAdapter,
        has_presentation=plugin.has_presentation,
        load_diagnostic=None,
    )


def _scripted(plugin):
    from benchweave_sdk_server.session import mock_exchanges

    return LoopingMockHost(mock_exchanges(plugin))
