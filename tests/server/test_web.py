"""The web surface: banner, readings, polling loop, assets, REST envelopes."""

from __future__ import annotations

import re
from pathlib import Path

from benchweave_sdk_server.web import build_app

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
    # The §D.1 component's own literal (SW-27): the I1 hand banner is
    # retired; the standalone truths ride the contract mode banner.
    assert "data-bw-mode-banner" in body
    assert "NO GATEWAY · LOCAL PRESENTATION ONLY" in body
    assert "example_plugin" in body
    assert f"/devices/{DEV}" in body


def test_the_served_titles_name_the_server_host(app) -> None:
    """Issue #309 slice A, fold F1: the FastAPI title carries the ruling's
    name — the dead distribution's title string is gone from the app
    object. The base template's <title> DEFAULT is renamed the same way;
    the index/device pages override that block with mode words
    ("Standalone host", the banner's vocabulary — kept, like SW-27).
    """
    assert app.title == "BenchWeave SDK server"
    from pathlib import Path

    templates = Path(__file__).resolve().parents[2] / "src" / "benchweave_sdk_server" / "templates"
    base = (templates / "base.html").read_text(encoding="utf-8")
    assert "BenchWeave SDK server" in base
    for page in sorted(templates.glob("*.html")):
        assert "BenchWeave standalone" not in page.read_text(encoding="utf-8"), page.name


def test_home_banner_names_the_absent_guarantees(client) -> None:
    body = client.get("/").text
    for guarantee in ("leases", "policy", "approvals", "procedures", "runs"):
        assert guarantee in body


def test_device_page_shows_the_reading_after_connect(client, policy) -> None:
    """A presentation-bearing plugin: the reading renders on the manifest
    page (the device page links it — I2a's retirement of the I1 table)."""
    _connect(client, policy)
    body = client.get("/pages/readings").text
    assert "voltage" in body
    assert "3.3" in body
    assert "V" in body
    device = client.get(f"/devices/{DEV}").text
    assert 'href="/pages/readings"' in device


def test_a_plugin_without_presentation_keeps_the_i1_readings_table(
    starter_project, tmp_path, policy
) -> None:
    """The degraded path: no presentation documents, so the device page
    remains the readings surface (the honest fallback, never a blank)."""
    import shutil

    from fastapi.testclient import TestClient

    from benchweave_sdk_server.seam import StandaloneSeam
    from benchweave_sdk_server.session import PluginSession, load_plugin_project, mock_exchanges
    from benchweave_sdk_server.transport import LoopingMockHost

    plain = tmp_path / "no-ui"
    shutil.copytree(starter_project, plain)

    package = plain / "src" / "example_plugin"
    for name in ("presentation.json", "binding-catalogue.json"):
        (package / name).unlink()
    shutil.rmtree(package / "ui")
    plugin = load_plugin_project(plain)
    assert not plugin.has_presentation
    seam = StandaloneSeam(
        PluginSession(plugin, lambda: LoopingMockHost(mock_exchanges(plugin))),
        transport_kind="mock",
    )
    with TestClient(build_app(seam, policy=policy), base_url="http://127.0.0.1:8477") as client:
        _connect(client, policy)
        body = client.get(f"/devices/{DEV}").text
        assert "3.3" in body
        partial = client.get(f"/devices/{DEV}/readings")
        assert "3.3" in partial.text


def test_ten_polls_all_serve_the_reading(client, policy) -> None:
    _connect(client, policy)
    for _ in range(10):
        response = client.get("/pages/readings/readings")
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
        first = client.get("/pages/readings/readings")
        assert "3.3" in first.text
        second = client.get("/pages/readings/readings")
        assert "Readings refused" in second.text
        assert "unavailable" in second.text


def test_no_script_without_src_anywhere(client, policy) -> None:
    """CSP shape (R2): every template and rendered page, no inline script."""
    from pathlib import Path

    _connect(client, policy)
    pages = ["/", f"/devices/{DEV}", "/pages/readings", "/pages/readings/readings"]
    for page in pages:
        for attributes in SCRIPT_TAG.findall(client.get(page).text):
            # The plot columns ride in a non-executing application/json
            # data block (CSP-safe by construction — never script code).
            if 'type="application/json"' in attributes:
                continue
            assert "src=" in attributes, (page, attributes)
    templates = Path(__file__).resolve().parents[2] / "src" / "benchweave_sdk_server" / "templates"
    for template in templates.glob("*.html"):
        for attributes in SCRIPT_TAG.findall(template.read_text()):
            if 'type="application/json"' in attributes:
                continue
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


# --- the poll region carries the live state (fold R-a) -------------------------


def test_the_poll_partial_carries_the_severity_badge(client, policy) -> None:
    """A polling browser swaps ONLY the partial's region: the severity
    badge must live inside it or the badge freezes at the first render's
    state while the tiles move on."""
    _connect(client, policy)
    partial = client.get("/pages/readings/readings")
    assert partial.status_code == 200
    assert 'data-bw-page-severity="neutral"' in partial.text


def test_the_full_page_renders_the_plot_region_once(client, policy) -> None:
    """The plots render inside the poll region (so live pages redraw); the
    full page must not render them a second time outside it — a duplicate
    figure hydrates twice and doubles the payload."""
    _connect(client, policy)
    body = client.get("/pages/readings").text
    assert body.count("data-bw-plot-host") == 1, body.count("data-bw-plot-host")
    assert body.count('aria-label="Traces"') == 1


def test_a_scenario_switch_moves_the_badge_through_the_poll(
    starter_project, policy
) -> None:
    """End to end: healthy page, switch the scenario selection, reconnect
    (the switch arms the NEXT connection), poll — the badge the polling
    browser receives carries the new severity without a full GET."""
    from fastapi.testclient import TestClient

    from benchweave_sdk_server.cli import _build_seam

    seam, selection = _build_seam(starter_project, scenario="normal")
    app = build_app(seam, policy=policy, scenario=selection)
    with TestClient(app, base_url="http://127.0.0.1:8477") as poll_client:
        _connect(poll_client, policy)
        before = poll_client.get("/pages/readings/readings").text
        assert 'data-bw-page-severity="neutral"' in before
        switch = poll_client.post(
            f"/devices/{DEV}/scenario",
            data={"scenario": "critical"},
            headers={"x-csrf-token": policy.csrf_token},
            follow_redirects=False,
        )
        assert switch.status_code == 303, switch.status_code
        poll_client.post(
            f"/devices/{DEV}/disconnect",
            headers={"x-csrf-token": policy.csrf_token},
            follow_redirects=False,
        )
        _connect(poll_client, policy)
        after = poll_client.get("/pages/readings/readings").text
        assert 'data-bw-page-severity="critical"' in after


# --- the connect prompt and the no-data line (folds R-b/R-c) --------------------


def _empty_configuration_page(project: Path) -> Path:
    """A manifest page with NO bindings (the lane's empty-bindings shape):
    valid by the schema (``ids`` has no floor), and it declares nothing to
    read — so the connect prompt would be a falsehood on it."""
    import hashlib
    import json

    package = project / "src" / "example_plugin"
    manifest_path = package / "ui" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["pages"].append(
        {
            "id": "settings",
            "title": "Settings",
            "kind": "configuration",
            "bindings": [],
            "required": False,
        }
    )
    raw = (json.dumps(manifest, indent=2) + "\n").encode()
    manifest_path.write_bytes(raw)
    envelope_path = package / "presentation.json"
    envelope = json.loads(envelope_path.read_text())
    envelope["manifest"]["sha256"] = hashlib.sha256(raw).hexdigest()
    envelope_path.write_text(json.dumps(envelope, indent=2) + "\n")
    return project


def test_an_empty_page_never_shows_the_connect_prompt(starter_project, tmp_path, policy) -> None:
    """Row R-b: the connect prompt names observations to read — a page that
    DECLARES none (connected or not) must never show it."""
    import shutil

    from fastapi.testclient import TestClient

    from benchweave_sdk_server.cli import _build_seam

    project = tmp_path / "empty-page"
    shutil.copytree(starter_project, project)
    _empty_configuration_page(project)
    seam, _ = _build_seam(project)
    with TestClient(
        build_app(seam, policy=policy), base_url="http://127.0.0.1:8477"
    ) as page_client:
        _connect(page_client, policy)
        body = page_client.get("/pages/settings").text
        assert "Connect the device" not in body
        assert "panel_unavailable" not in body


def test_the_connect_prompt_names_the_page_it_serves(client, policy) -> None:
    """Row R-b: a readings page WITH observation bindings and no connection
    shows the prompt (the honest not-connected-yet state)."""
    body = client.get("/pages/readings").text
    assert "Connect the device" in body


def test_the_no_data_line_survives_the_poll_swap(monkeypatch, client, policy) -> None:
    """Row R-b (the laundered-poll repro): a page carrying a non-observation
    binding renders its no-data disclosure on the full page AND on the poll
    partial — the swap must never launder the disclosure away."""
    from benchweave_sdk_server.presentation import BindingRow, HostPresentation, PageView

    synthetic = PageView(
        id="mixed",
        title="Mixed",
        kind="readings",
        required=False,
        panel_id=None,
        bindings=(
            BindingRow(
                id="obs", kind="observation", target_id="voltage", parameter_id="voltage"
            ),
            BindingRow(id="bulk", kind="dataset", target_id="capture"),
        ),
    )
    original = HostPresentation.page

    def patched(self, page_id):
        return synthetic if page_id == "mixed" else original(self, page_id)

    monkeypatch.setattr(HostPresentation, "page", patched)
    _connect(client, policy)
    full = client.get("/pages/mixed").text
    assert 'data-bw-binding="bulk"' in full
    assert "No data — dataset binding" in full
    partial = client.get("/pages/mixed/readings").text
    assert 'data-bw-binding="bulk"' in partial, "the poll swap dropped the disclosure"
    assert "No data — dataset binding" in partial


def test_a_page_with_no_observations_renders_only_disclosures(monkeypatch, client) -> None:
    """Row R-c: the no-data coverage arm — a page whose every binding is
    non-observation renders one disclosure line per binding, no prompt, no
    tiles."""
    from benchweave_sdk_server.presentation import BindingRow, HostPresentation, PageView

    synthetic = PageView(
        id="bulk-only",
        title="Bulk only",
        kind="dataset",
        required=False,
        panel_id=None,
        bindings=(
            BindingRow(id="one", kind="dataset", target_id="capture"),
            BindingRow(id="two", kind="procedure", target_id="invoke"),
        ),
    )
    original = HostPresentation.page

    def patched(self, page_id):
        return synthetic if page_id == "bulk-only" else original(self, page_id)

    monkeypatch.setattr(HostPresentation, "page", patched)
    body = client.get("/pages/bulk-only").text
    assert "No data — dataset binding" in body
    assert "No data — procedure binding" in body
    assert "Connect the device" not in body
    assert "bw-reading" not in body
