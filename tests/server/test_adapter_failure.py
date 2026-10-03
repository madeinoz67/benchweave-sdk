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


def _broken_entry_point(project: Path, entry_point: str, package: str = "example_plugin") -> None:
    descriptor = project / "src" / package / "descriptor.json"
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


# --- FOLD-2 (refute lane-2 F2): the degrade taxonomy covers the real classes ---


def _module_project(tmp_path: Path, module_source: str, module_name: str) -> Path:
    """A scaffold whose entry point names a purpose-built module, under a
    UNIQUE package: the suite imports many example_plugin projects, and a
    cached package would resolve the submodule against an earlier
    project's path (the SystemExit arm passed vacuously that way — a
    ModuleNotFoundError is not the class under test)."""
    from benchweave_sdk.scaffold import create_project

    package = f"probe_{module_name}"
    project = tmp_path / f"mod-{module_name}"
    create_project(project, package)
    (project / "src" / package / f"{module_name}.py").write_text(module_source)
    _broken_entry_point(project, f"{package}.{module_name}:create_plugin", package)
    return project


def test_a_syntax_error_module_degrades(tmp_path: Path) -> None:
    """Import-time class (the most common authoring failure): a module-level
    SyntaxError currently escapes as a raw traceback (serve exit 1)."""
    project = _module_project(tmp_path, "def create_plugin(:\n", "broken_syntax")
    plugin = load_plugin_project(project)
    assert plugin.adapter_factory is None
    assert plugin.load_diagnostic is not None
    assert plugin.load_diagnostic.startswith("standalone_plugin_import:")


def test_a_system_exit_module_degrades(tmp_path: Path) -> None:
    """Import-time class: a module calling sys.exit() at import currently
    swallows serve into the plugin's own exit code."""
    project = _module_project(
        tmp_path,
        "import sys\nsys.exit(7)\n\n\ndef create_plugin():\n    raise AssertionError\n",
        "exits",
    )
    plugin = load_plugin_project(project)
    assert plugin.adapter_factory is None
    assert plugin.load_diagnostic is not None
    assert plugin.load_diagnostic.startswith("standalone_plugin_import:")


def _seam_over_project(project: Path) -> StandaloneSeam:
    plugin = load_plugin_project(project)
    from benchweave_sdk_server.session import mock_exchanges
    from benchweave_sdk_server.transport import LoopingMockHost

    return StandaloneSeam(
        PluginSession(plugin, lambda: LoopingMockHost(mock_exchanges(plugin))),
        transport_kind="mock",
    )


def _rest_connect(seam: StandaloneSeam):
    from fastapi.testclient import TestClient

    policy = _policy()
    app = build_app(seam, policy=policy)
    with TestClient(app, base_url="http://127.0.0.1:8477") as client:
        return client.post(
            "/v1/device_connect",
            json={"device_id": DEV},
            headers={"authorization": f"Bearer {policy.bearer_token}"},
        )


def test_a_factory_that_raises_answers_typed_not_ready(tmp_path: Path) -> None:
    """Connect-time class: a factory raising on call currently surfaces as
    a bare 500; it must answer not_ready carrying a prefixed diagnostic."""
    project = _module_project(
        tmp_path,
        "def create_plugin():\n    raise ValueError('boom at factory')\n",
        "bad_factory",
    )
    response = _rest_connect(_seam_over_project(project))
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"]["code"] == "not_ready"
    assert "standalone_plugin_connect:" in body["error"]["message"]


def test_a_factory_returning_none_answers_typed_not_ready(tmp_path: Path) -> None:
    """Connect-time class: a factory returning a non-Adapter currently
    AttributeErrors into a bare 500."""
    project = _module_project(tmp_path, "def create_plugin():\n    return None\n", "none_factory")
    response = _rest_connect(_seam_over_project(project))
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"]["code"] == "not_ready"
    assert "standalone_plugin_connect:" in body["error"]["message"]


def test_an_open_that_raises_answers_typed_not_ready(tmp_path: Path) -> None:
    """Connect-time class: adapter.open() raising a non-RuntimeError
    currently surfaces as a bare 500."""
    project = _module_project(
        tmp_path,
        (
            "class Plugin:\n"
            "    async def open(self, descriptor, services, context):\n"
            "        raise ValueError('boom at open')\n"
            "    async def execute(self, request, context):\n"
            "        raise AssertionError\n"
            "    async def next_event(self, subscription_id, context):\n"
            "        return None\n"
            "    async def close(self, context):\n"
            "        return None\n"
            "\n"
            "\n"
            "def create_plugin():\n"
            "    return Plugin()\n"
        ),
        "bad_open",
    )
    response = _rest_connect(_seam_over_project(project))
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"]["code"] == "not_ready"
    assert "standalone_plugin_connect:" in body["error"]["message"]


def test_an_underivable_scenario_script_answers_typed_not_ready(
    starter_project: Path, tmp_path: Path
) -> None:
    """Lane-1 F4 rides the same path: an enum whose canonical value cannot
    be represented in the ASCII line protocol (a comma) makes the script
    build raise INSIDE the connect-time services factory — a typed refusal,
    never a bare 500."""
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "comma-enum"
    create_project(project, "example_plugin")
    descriptor = project / "src" / "example_plugin" / "descriptor.json"
    document = json.loads(descriptor.read_text())
    document["parameters"][0]["type"] = "enum"
    document["parameters"][0]["enum_values"] = ["a,b"]
    descriptor.write_text(json.dumps(document))
    seam, _ = _build_seam(project, scenario="normal")
    response = _rest_connect(seam)
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"]["code"] == "not_ready"
    assert "standalone_scenario_script" in body["error"]["message"]
