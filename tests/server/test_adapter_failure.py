"""The loader split (§4.5): document failures refuse startup; adapter
failures degrade to not_ready + diagnostic + layout render."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk_server.cli import _build_seam
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.session import PluginSession, load_plugin_project
from benchweave_sdk_server.web import build_app

DEV = "example_device"


def _broken_entry_point(project: Path, entry_point: str) -> None:
    descriptor = project / "src" / "example_plugin" / "descriptor.json"
    document = json.loads(descriptor.read_text())
    document["integration"]["adapter"]["entry_point"] = entry_point
    descriptor.write_text(json.dumps(document))


def _import_broken_project(tmp_path: Path) -> Path:
    """A scaffold whose entry point names a module that does not exist."""
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "broken-import"
    create_project(project, "example_plugin")
    _broken_entry_point(project, "example_plugin.absent:create_plugin")
    return project


def _malformed_project(tmp_path: Path) -> Path:
    """A scaffold whose entry point string does not name a factory inside
    the plugin package."""
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "malformed-entry"
    create_project(project, "example_plugin")
    _broken_entry_point(project, "other_package.adapter:create_plugin")
    return project


def _policy() -> GuardPolicy:
    return GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )


# --- the loader degrades instead of refusing ---------------------------------


def test_a_missing_adapter_module_degrades_with_the_diagnostic(tmp_path: Path) -> None:
    plugin = load_plugin_project(_import_broken_project(tmp_path))
    assert plugin.adapter_factory is None
    assert plugin.load_diagnostic is not None
    assert plugin.load_diagnostic.startswith("standalone_plugin_import:")


def test_a_malformed_entry_point_degrades_with_the_diagnostic(tmp_path: Path) -> None:
    plugin = load_plugin_project(_malformed_project(tmp_path))
    assert plugin.adapter_factory is None
    assert plugin.load_diagnostic is not None
    assert plugin.load_diagnostic.startswith("standalone_plugin_entry_point:")


def test_document_failures_still_refuse_startup(tmp_path: Path) -> None:
    """SW-05 unchanged (the SRF-2/R-10 arm): an invalid presentation is a
    DOCUMENT failure — the loader refuses, nothing degrades."""
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project
    from benchweave_sdk_server.session import PluginLoadError

    project = tmp_path / "bad-presentation"
    create_project(project, "example_plugin")
    create_ui_resources(project, "example_plugin")
    manifest = project / "src" / "example_plugin" / "ui" / "manifest.json"
    document = json.loads(manifest.read_text())
    document["plugin_id"] = "something.else"
    manifest.write_text(json.dumps(document))
    with pytest.raises(PluginLoadError, match="standalone_plugin_invalid:"):
        load_plugin_project(project)


# --- the degraded session answers not_ready -----------------------------------


def test_connect_refuses_not_ready_with_the_diagnostic(tmp_path: Path) -> None:
    plugin = load_plugin_project(_import_broken_project(tmp_path))
    session = PluginSession(plugin, lambda: None)  # type: ignore[arg-type]

    async def run() -> None:
        with pytest.raises(RuntimeError, match="standalone_plugin_import:"):
            await session.connect()

    asyncio.run(run())


def test_the_seam_answers_device_ops_not_ready_with_the_detail(tmp_path: Path) -> None:
    plugin = load_plugin_project(_import_broken_project(tmp_path))
    seam = StandaloneSeam(PluginSession(plugin, lambda: None), transport_kind="mock")  # type: ignore[arg-type]

    async def run() -> None:
        for operation, arguments in (
            ("device_connect", {"device_id": DEV}),
            ("parameter_read", {"device_id": DEV, "parameter": "voltage"}),
            ("device_get", {"device_id": DEV}),
        ):
            with pytest.raises(Exception) as caught:
                await seam.call(operation, arguments)
            error = caught.value
            assert getattr(error, "code", "") == "not_ready", operation
            assert error.details.get("load_diagnostic", "").startswith(
                "standalone_plugin_import:"
            ), operation

    asyncio.run(run())


# --- the pages render their layout with the diagnostic ------------------------


def test_the_pages_render_the_layout_with_the_diagnostic(tmp_path: Path) -> None:
    plugin = load_plugin_project(_import_broken_project(tmp_path))
    seam = StandaloneSeam(PluginSession(plugin, lambda: None), transport_kind="mock")  # type: ignore[arg-type]
    policy = _policy()
    with TestClient(build_app(seam, policy=policy), base_url="http://127.0.0.1:8477") as client:
        for page in ("/", f"/devices/{DEV}"):
            response = client.get(page)
            assert response.status_code == 200, page
        body = client.get(f"/devices/{DEV}").text
        assert "Adapter not loaded" in body
        assert "standalone_plugin_import" in body
        assert "voltage" in body  # the declared parameter rows still render
        connect = client.post(
            f"/devices/{DEV}/connect",
            headers={"x-csrf-token": policy.csrf_token},
            follow_redirects=True,
        )
        assert "not_ready" in connect.text
        assert "standalone_plugin_import" in connect.text


def test_rest_device_connect_answers_not_ready(tmp_path: Path) -> None:
    plugin = load_plugin_project(_import_broken_project(tmp_path))
    seam = StandaloneSeam(PluginSession(plugin, lambda: None), transport_kind="mock")  # type: ignore[arg-type]
    policy = _policy()
    with TestClient(build_app(seam, policy=policy), base_url="http://127.0.0.1:8477") as client:
        response = client.post(
            "/v1/device_connect",
            json={"device_id": DEV},
            headers={"authorization": f"Bearer {policy.bearer_token}"},
        )
        assert response.status_code == 409
        body = response.json()
        assert body["error"]["code"] == "not_ready"
        assert body["error"]["details"]["load_diagnostic"].startswith(
            "standalone_plugin_import:"
        )


# --- serve binds with the diagnostic; scenario mode composes ------------------


def test_serve_prints_the_diagnostic_and_proceeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """serve exits 0 with the diagnostic on stderr — the port binds; the
    author sees a UI before the adapter works."""
    from click.testing import CliRunner

    from benchweave_sdk_server.cli import cli

    reached_run: dict[str, bool] = {}
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: reached_run.update(run=True))
    result = CliRunner().invoke(
        cli, ["serve", str(_import_broken_project(tmp_path)), "--no-open"]
    )
    assert result.exit_code == 0, result.output
    assert reached_run.get("run") is True
    assert "standalone_plugin_import" in result.output


@pytest.mark.parametrize(
    ("scenario_id", "outcome"),
    [
        ("normal", "ok"),
        ("loading", "absent"),
        ("stale", "ok"),
        ("disconnected", "refused"),
        ("warning", "ok"),
        ("critical", "ok"),
        ("trip", "ok"),
        ("recovery", "ok"),
        ("request-rejected", "rejected"),
    ],
)
def test_scenario_mode_serves_the_nine_on_a_broken_adapter(
    tmp_path: Path, scenario_id: str, outcome: str
) -> None:
    """§4.5 composes with §4.2: scenario mode never imports the author's
    adapter, so the broken project still serves all nine states — driven
    through the SEAM (the refute fold: the earlier direct session.connect()
    bypassed the seam's degraded-refusal path, the exact layer where the
    composition broke)."""
    import asyncio

    from benchweave_sdk_server.errors import SeamError

    project = _import_broken_project(tmp_path)
    seam, _ = _build_seam(project, scenario=scenario_id)

    async def run() -> None:
        if outcome == "refused":
            with pytest.raises(SeamError) as caught:
                await seam.call("device_connect", {"device_id": DEV})
            assert caught.value.code == "not_ready"
            return
        await seam.call("device_connect", {"device_id": DEV})
        if outcome == "rejected":
            with pytest.raises(SeamError) as caught:
                await seam.call(
                    "parameter_read", {"device_id": DEV, "parameter": "voltage"}
                )
            assert caught.value.details["adapter"]["code"] == "DEVICE_REJECTED"
            return
        data = await seam.call(
            "parameter_read", {"device_id": DEV, "parameter": "voltage"}
        )
        if outcome == "absent":
            assert data["value"] is None
        else:
            assert data["source"] == "scenario"
        await seam.call("device_disconnect", {"device_id": DEV})

    asyncio.run(run())


# --- FOLD-1 (refute HIGH, both lanes): degraded+scenario composes -------------


@pytest.mark.parametrize(
    ("scenario_id", "connects"),
    [
        ("normal", True),
        ("loading", True),
        ("stale", True),
        ("disconnected", False),
        ("warning", True),
        ("critical", True),
        ("trip", True),
        ("recovery", True),
        ("request-rejected", True),
    ],
)
def test_a_degraded_project_serves_all_nine_over_the_seam(
    tmp_path: Path, scenario_id: str, connects: bool
) -> None:
    """The design's §4.2/§4.5 headline, proven at the SEAM layer (the
    refute lanes' finding: scenario_session's replace() preserved
    load_diagnostic, so the seam refused every device op although the
    scenario adapter — the host-shipped one — was healthy; the old test
    drove session.connect() directly and bypassed exactly this refusal)."""
    from fastapi.testclient import TestClient

    project = _import_broken_project(tmp_path)
    seam, _ = _build_seam(project, scenario=scenario_id)
    policy = _policy()
    with TestClient(build_app(seam, policy=policy), base_url="http://127.0.0.1:8477") as client:
        connect = client.post(
            "/v1/device_connect",
            json={"device_id": DEV},
            headers={"authorization": f"Bearer {policy.bearer_token}"},
        )
        if not connects:
            assert connect.status_code == 409
            assert connect.json()["error"]["code"] == "not_ready"
            return
        assert connect.status_code == 200, connect.text
        read = client.post(
            "/v1/parameter_read",
            json={"device_id": DEV, "parameter": "voltage"},
            headers={"authorization": f"Bearer {policy.bearer_token}"},
        )
        if scenario_id == "request-rejected":
            assert read.status_code == 409
            assert read.json()["error"]["details"]["adapter"]["code"] == "DEVICE_REJECTED"
            return
        assert read.status_code == 200, read.text
        assert read.json()["data"]["source"] == "scenario"


def test_non_scenario_degraded_mode_still_shows_the_diagnostic(tmp_path: Path) -> None:
    """FOLD-1 arm (c): clearing the diagnostic in scenario mode must not
    weaken the honest degrade — plain serve still refuses device ops and
    renders the diagnostic."""
    import asyncio

    plugin = load_plugin_project(_import_broken_project(tmp_path))
    seam = StandaloneSeam(PluginSession(plugin, lambda: None), transport_kind="mock")  # type: ignore[arg-type]

    async def run() -> None:
        with pytest.raises(Exception) as caught:
            await seam.call("device_connect", {"device_id": DEV})
        assert caught.value.code == "not_ready"
        assert caught.value.details["load_diagnostic"].startswith("standalone_plugin_import:")

    asyncio.run(run())
