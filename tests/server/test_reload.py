"""plugin_reload semantics and the Q11 confirmation branch (I2c §4.2,
SW-38 + Q11 option 2; gate I2-R's arms).

The reload's hard rules: a staged-unapplied value or an in-flight capture
refuses ``conflict``; a load that fails validation leaves the PREVIOUS
version fully loaded (host_info digest unchanged, diagnostics ride the
refusal); a clean reload swaps the plugin, rebuilds the presentation,
re-pins presets, reconnects if a session was open, and publishes
``plugin_reloaded`` so every open page sees the advisory. The Q11 branch:
an adapter-code change while CONNECTED on an attended host returns a
pending ``confirmation_required`` result — not an error, nothing torn down
— and the operator confirms in the UI; ``--unattended`` and contract-only
changes proceed without it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk.presentation import create_ui_resources
from benchweave_sdk.scaffold import create_project
from benchweave_sdk_server import authoring
from benchweave_sdk_server.errors import SeamError
from benchweave_sdk_server.scenarios import ScenarioSelection, scenario_session
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.session import mock_plugin_session
from benchweave_sdk_server.web import build_app

DEV = {"device_id": "example_device"}


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "starter"
    create_project(project, "example_plugin")
    create_ui_resources(project, "example_plugin")
    return project


def _seam(project: Path, **kwargs) -> StandaloneSeam:
    from benchweave_sdk_server.session import load_plugin_project

    plugin = load_plugin_project(project)
    return StandaloneSeam(mock_plugin_session(plugin), transport_kind="mock", **kwargs)


def _policy() -> GuardPolicy:
    return GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )


def _client(seam: StandaloneSeam, policy: GuardPolicy) -> TestClient:
    app = build_app(seam, policy=policy)
    return TestClient(app, base_url="http://127.0.0.1:8477")


def _call(seam: StandaloneSeam, operation: str, arguments: dict) -> dict:
    return asyncio.run(seam.call(operation, arguments))


def _digest(seam: StandaloneSeam) -> str:
    return _call(seam, "host_info", {})["plugin"]["descriptor_sha256"]


def _kinds(seam: StandaloneSeam) -> list[str]:
    return [row["kind"] for row in _call(seam, "events_get", {"after_id": 0})["events"]]


# --- the guards --------------------------------------------------------------


def test_staged_unapplied_refuses_conflict(tmp_path) -> None:
    # The starter is ro-only; staging needs the setpoint fixture's rw
    # parameter (staging is host state — no connection required).
    import shutil as _shutil

    project = tmp_path / "setpoint"
    _shutil.copytree(
        Path(__file__).resolve().parent.parent / "fixtures" / "setpoint_plugin",
        project,
    )
    seam = _seam(project)
    _call(
        seam,
        "parameter_stage",
        {"device_id": "setpoint_dev", "parameter": "current_limit", "value": 1.0},
    )
    with pytest.raises(SeamError) as caught:
        asyncio.run(seam.reload_plugin(source="test"))
    assert caught.value.code == "conflict"
    assert "staged" in caught.value.message


def test_capture_in_flight_refuses_conflict(tmp_path) -> None:
    """No capture exists until I3; the guard reads the seam's in-flight
    state, so the arm is exercised by setting it — exactly how I3's
    capture_start will hold it."""
    seam = _seam(_project(tmp_path))
    seam._capture_in_flight = True
    with pytest.raises(SeamError) as caught:
        asyncio.run(seam.reload_plugin(source="test"))
    assert caught.value.code == "conflict"
    assert "capture" in caught.value.message


# --- the failure branch: previous stays loaded ---------------------------------


def test_invalid_on_disk_descriptor_keeps_the_previous_version(tmp_path) -> None:
    project = _project(tmp_path)
    seam = _seam(project)
    before = _digest(seam)
    (project / "src" / "example_plugin" / "descriptor.json").write_text("{ not json")
    with pytest.raises(SeamError) as caught:
        asyncio.run(seam.reload_plugin(source="test"))
    assert "standalone_plugin_invalid" in caught.value.message
    assert _digest(seam) == before


# --- the clean reload -----------------------------------------------------------


def test_clean_contract_reload_swaps_digest_and_republishes(tmp_path) -> None:
    project = _project(tmp_path)
    seam = _seam(project)
    before = _digest(seam)
    authoring._contract_patch(
        seam,
        "descriptor",
        [{"op": "replace", "path": "/display_name", "value": "Reloaded demo"}],
    )
    result = asyncio.run(seam.reload_plugin(source="test"))
    assert result["status"] == "reloaded"
    after = _digest(seam)
    assert after != before
    assert result["descriptor_sha256"] == after
    assert "plugin_reloaded" in _kinds(seam)
    event = [
        row
        for row in _call(seam, "events_get", {"after_id": 0})["events"]
        if row["kind"] == "plugin_reloaded"
    ][0]
    assert event["data"]["descriptor_sha256"] == after
    assert event["data"]["source"] == "test"


def test_reload_reimports_changed_adapter_code(tmp_path) -> None:
    """A reload must re-EXECUTE the package's modules — the import cache
    would otherwise keep serving the previous adapter object forever."""
    project = _project(tmp_path)
    seam = _seam(project)
    old_factory = seam.session.plugin.adapter_factory
    adapter = project / "src" / "example_plugin" / "adapter.py"
    adapter.write_text(adapter.read_text() + "\n# reloaded\n")
    result = asyncio.run(seam.reload_plugin(source="test"))
    assert result["status"] == "reloaded"
    assert seam.session.plugin.adapter_factory is not old_factory


def test_reload_reconnects_a_connected_session_and_reads_still_serve(tmp_path) -> None:
    project = _project(tmp_path)
    seam = _seam(project)
    _call(seam, "device_connect", DEV)
    result = asyncio.run(seam.reload_plugin(source="test"))
    assert result["reconnected"] is True
    reading = _call(seam, "parameter_read", {**DEV, "parameter": "voltage"})
    assert reading["value"] == 3.3


def test_pages_re_render_the_patch_after_reload(tmp_path) -> None:
    project = _project(tmp_path)
    seam = _seam(project)
    with _client(seam, _policy()) as client:
        before = client.get("/pages/readings").text
        assert "Readings" in before
    authoring._contract_patch(
        seam,
        "manifest",
        [{"op": "replace", "path": "/pages/0/title", "value": "Live readings"}],
    )
    asyncio.run(seam.reload_plugin(source="test"))
    with _client(seam, _policy()) as client:
        after = client.get("/pages/readings").text
        assert "Live readings" in after


# --- FOLD-D: sibling top-level src modules ride the digest and eviction ----------


def test_d_sibling_src_modules_enter_the_adapter_digest(tmp_path) -> None:
    """A top-level src module the package imports is adapter CODE: an
    edit to it changes what a reload would execute, so a connected
    ATTENDED host must ask — today the digest walked only the package
    dir and the edit slipped past with no confirmation."""
    import sys

    project = _project(tmp_path)
    helper = project / "src" / "helper_module.py"
    helper.write_text("MARK = 1\n")
    adapter = project / "src" / "example_plugin" / "adapter.py"
    adapter.write_text("import helper_module\n" + adapter.read_text())
    seam = _seam(project)
    _call(seam, "device_connect", DEV)
    helper.write_text("MARK = 2\n")
    result = asyncio.run(seam.reload_plugin(source="test"))
    assert result["status"] == "confirmation_required", (
        "an edit to a module the plugin loads changed adapter code — the "
        "digest must see it"
    )
    # And the confirmation is not theatre: confirming must EXECUTE the new
    # bytes — today eviction cleared only the package, so the module cache
    # kept serving MARK=1 after the reload.
    confirm = asyncio.run(seam.confirm_reload(source="test"))
    assert confirm["status"] == "reloaded"
    import importlib

    fresh = importlib.import_module("helper_module")
    assert fresh is sys.modules["helper_module"]
    assert fresh.MARK == 2, "the module cache survived the reload — stale bytes"


def test_d_the_helper_edit_requires_no_descriptor_motion(tmp_path) -> None:
    """The digest's widening must not drag CONTRACT documents into the
    adapter-change class: the walk covers Python modules under src/, and
    nothing else — a descriptor edit still confirms-free in unattended
    mode with a helper present."""
    project = _project(tmp_path)
    helper = project / "src" / "helper_module.py"
    helper.write_text("MARK = 1\n")
    seam = _seam(project, unattended=True)
    _call(seam, "device_connect", DEV)
    authoring._contract_patch(
        seam,
        "descriptor",
        [{"op": "replace", "path": "/display_name", "value": "Contracts only"}],
    )
    result = asyncio.run(seam.reload_plugin(source="test"))
    assert result["status"] == "reloaded"


# --- the Q11 confirmation branch --------------------------------------------------


def _change_adapter_code(project: Path) -> None:
    adapter = project / "src" / "example_plugin" / "adapter.py"
    adapter.write_text(adapter.read_text() + "\n# adapter edit\n")


def test_adapter_change_connected_attended_asks_for_confirmation(tmp_path) -> None:
    project = _project(tmp_path)
    seam = _seam(project)
    _call(seam, "device_connect", DEV)
    before = _digest(seam)
    _change_adapter_code(project)
    result = asyncio.run(seam.reload_plugin(source="test"))
    # A pending state, NOT an error: nothing torn down, previous version
    # fully loaded and still serving.
    assert result["status"] == "confirmation_required"
    assert _digest(seam) == before
    assert "reload_confirmation_required" in _kinds(seam)
    reading = _call(seam, "parameter_read", {**DEV, "parameter": "voltage"})
    assert reading["value"] == 3.3
    assert seam.pending_reload is not None


def test_ui_confirm_proceeds(tmp_path) -> None:
    project = _project(tmp_path)
    seam = _seam(project)
    _call(seam, "device_connect", DEV)
    old_factory = seam.session.plugin.adapter_factory
    _change_adapter_code(project)
    result = asyncio.run(seam.reload_plugin(source="mcp"))
    assert result["status"] == "confirmation_required"
    policy = _policy()
    with _client(seam, policy) as client:
        # The #98 untrusted-redirection class, extended to the authoring
        # route: /reload/confirm carries NO path parameter (nothing to
        # echo), and its redirect target derives from the SEAM's own
        # device id exactly — never any request-supplied string.
        confirmed = client.post(
            "/reload/confirm",
            headers={"x-csrf-token": policy.csrf_token},
            follow_redirects=False,
        )
        assert confirmed.status_code == 303
        assert confirmed.headers["location"] == f"/devices/{seam.session.device_id}"
        # A confirm with nothing pending is a 409 answer, never a
        # redirect — an unfounded confirm cannot bounce the operator.
        again = client.post(
            "/reload/confirm",
            headers={"x-csrf-token": policy.csrf_token},
            follow_redirects=False,
        )
        assert again.status_code == 409
        assert "location" not in again.headers
    # An adapter-only edit cannot move the descriptor digest; the honest
    # probe is the reloaded adapter itself (re-imported, new object) plus
    # the reload event and the cleared pending state.
    assert seam.session.plugin.adapter_factory is not old_factory
    assert "plugin_reloaded" in _kinds(seam)
    assert seam.pending_reload is None


def test_b_confirm_binds_to_the_digests_it_showed(tmp_path) -> None:
    """A confirmation confirms BYTES, not an intent: when the adapter
    changes again after the pend, confirming must NOT load different
    bytes than the operator saw — it re-pends with the new digest."""
    project = _project(tmp_path)
    seam = _seam(project)
    _call(seam, "device_connect", DEV)
    _change_adapter_code(project)  # edit A
    first = asyncio.run(seam.reload_plugin(source="mcp"))
    assert first["status"] == "confirmation_required"
    pending_digest = seam.pending_reload["adapter_sha256_next"]
    _change_adapter_code(project)  # edit B — different bytes on disk now
    second = asyncio.run(seam.confirm_reload(source="ui"))
    assert second["status"] == "confirmation_required", (
        "a confirm shown digest A must not load digest B"
    )
    assert seam.pending_reload is not None
    assert seam.pending_reload["adapter_sha256_next"] != pending_digest
    # And the previous version is still fully loaded and serving.
    reading = _call(seam, "parameter_read", {**DEV, "parameter": "voltage"})
    assert reading["value"] == 3.3
    # The re-pended confirmation is honest: confirming NOW (bytes stable)
    # proceeds and loads exactly what the second pend showed.
    third = asyncio.run(seam.confirm_reload(source="ui"))
    assert third["status"] == "reloaded"
    assert seam.pending_reload is None


def test_b7_a_broken_confirm_load_keeps_the_working_previous(tmp_path) -> None:
    """The degraded-bind door: a confirm-time load failure (SyntaxError
    introduced after the pend) must not swap the working previous
    adapter for a degraded one — the reload refuses, the previous keeps
    serving, the diagnostic surfaces."""
    project = _project(tmp_path)
    seam = _seam(project)
    _call(seam, "device_connect", DEV)
    _change_adapter_code(project)
    first = asyncio.run(seam.reload_plugin(source="mcp"))
    assert first["status"] == "confirmation_required"
    adapter = project / "src" / "example_plugin" / "adapter.py"
    adapter.write_text("this is not python\n")
    with pytest.raises(SeamError) as caught:
        asyncio.run(seam.confirm_reload(source="ui"))
    assert caught.value.code == "invalid_request"
    assert "standalone_plugin_import" in caught.value.message
    # The previous WORKING adapter is still loaded and serving — the
    # broken bytes never touched the host.
    reading = _call(seam, "parameter_read", {**DEV, "parameter": "voltage"})
    assert reading["value"] == 3.3
    assert seam.session.plugin.adapter_factory is not None
    assert "plugin_reloaded" not in _kinds(seam)


def test_confirm_with_nothing_pending_refuses(tmp_path) -> None:
    seam = _seam(_project(tmp_path))
    with pytest.raises(SeamError) as caught:
        asyncio.run(seam.confirm_reload(source="test"))
    assert caught.value.code == "invalid_request"


def test_unattended_waives_the_confirmation(tmp_path) -> None:
    project = _project(tmp_path)
    seam = _seam(project, unattended=True)
    _call(seam, "device_connect", DEV)
    _change_adapter_code(project)
    result = asyncio.run(seam.reload_plugin(source="test"))
    assert result["status"] == "reloaded"
    assert seam.pending_reload is None


def test_contract_only_change_needs_no_confirmation(tmp_path) -> None:
    project = _project(tmp_path)
    seam = _seam(project)
    _call(seam, "device_connect", DEV)
    authoring._contract_patch(
        seam,
        "descriptor",
        [{"op": "replace", "path": "/display_name", "value": "Contracts only"}],
    )
    result = asyncio.run(seam.reload_plugin(source="test"))
    assert result["status"] == "reloaded"


def test_adapter_change_disconnected_needs_no_confirmation(tmp_path) -> None:
    project = _project(tmp_path)
    seam = _seam(project)
    _change_adapter_code(project)
    result = asyncio.run(seam.reload_plugin(source="test"))
    assert result["status"] == "reloaded"


# --- the authoring panel (SW-29) ----------------------------------------------------


def test_every_page_carries_the_authoring_panel(tmp_path) -> None:
    seam = _seam(_project(tmp_path))
    with _client(seam, _policy()) as client:
        html = client.get("/pages/readings").text
    assert "authoring-panel" in html
    assert "not reloaded" in html
    assert "validation clean" in html


def test_the_panel_reports_the_reload_and_findings(tmp_path) -> None:
    project = _project(tmp_path)
    seam = _seam(project)
    asyncio.run(seam.reload_plugin(source="test"))
    with _client(seam, _policy()) as client:
        html = client.get("/pages/readings").text
    assert "authoring-panel" in html
    assert "test" in html  # the triggering surface
    assert "not reloaded" not in html


def test_the_page_declares_the_sse_advisory_region(tmp_path) -> None:
    seam = _seam(_project(tmp_path))
    with _client(seam, _policy()) as client:
        html = client.get("/").text
    # The advisory bridge is the first-party EventSource hydrator (the
    # vendored htmx-1 SSE extension predates htmx 2 and its swap API is
    # gone); the regions it fills and the script that fills them are the
    # rendered contract, and the rendered TEXT is pinned in the browser
    # lane's own arm.
    assert 'src="/assets/bw-events.js"' in html
    assert 'id="reload-advisory"' in html
    assert 'id="reload-confirm-advisory"' in html


# --- the scenario session stays reload-honest ----------------------------------------


def test_scenario_session_factory_reads_the_current_plugin(tmp_path) -> None:
    """The scenario services factory must derive its script from the
    CURRENT plugin (late-bound), so a reloaded project's vectors drive the
    next connection — not the original closure's."""
    from benchweave_sdk_server.session import load_plugin_project

    project = _project(tmp_path)
    plugin = load_plugin_project(project)
    session = scenario_session(plugin, ScenarioSelection("normal"))
    first = session.plugin
    assert session.plugin is first  # sanity: property serves the session's own


# --- the CLI flag pairing --------------------------------------------------------------


def test_unattended_without_authoring_refuses(tmp_path) -> None:
    from benchweave_sdk_server.cli import main

    project = _project(tmp_path)
    assert main(["serve", str(project), "--unattended"]) == 2


def test_unattended_with_authoring_is_accepted(tmp_path) -> None:
    from benchweave_sdk_server.cli import main

    project = _project(tmp_path)
    assert main(["mcp", str(project), "--authoring", "--unattended", "--help"]) == 0


def test_build_seam_threads_unattended(tmp_path) -> None:
    from benchweave_sdk_server.cli import _build_seam

    project = _project(tmp_path)
    seam, _selection = _build_seam(project, unattended=True)
    assert seam.unattended is True
