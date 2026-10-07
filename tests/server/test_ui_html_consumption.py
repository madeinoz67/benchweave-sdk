"""Consuming the published benchweave-ui-html wheel (§4.6, Q5, I1-D5's
closure) and the server-identity renames (the brief's named residuals)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("benchweave_ui_html", reason="the [server] extra installs ui-html")

from benchweave_ui_html import assets as ui_html_assets  # noqa: E402

from benchweave_sdk_server import catalogue  # noqa: E402
from benchweave_sdk_server.cli import _build_seam  # noqa: E402
from benchweave_sdk_server.security import GuardPolicy, new_token  # noqa: E402
from benchweave_sdk_server.web import build_app  # noqa: E402

DEV = "example_device"
HOST_ASSETS = Path(__file__).resolve().parents[2] / "src" / "benchweave_sdk_server" / "ui_assets"


def _policy() -> GuardPolicy:
    return GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )


def test_the_host_no_longer_carries_copies_of_the_renderer_assets() -> None:
    """I1-D5 closes: tokens.css/themes.css come from the installed
    benchweave_ui_html package; the host's ui_assets tree lists only
    host-owned files (plus the analyse view's page-scoped brush, I4a)."""
    for name in ("tokens.css", "themes.css"):
        assert not (HOST_ASSETS / name).exists(), name
    inventory = json.loads((HOST_ASSETS / "inventory.json").read_text())
    listed = {row["path"] for row in inventory["assets"]}
    assert listed == {
        "htmx.min.js",
        "standalone.css",
        "uplot.min.js",
        "uplot.css",
        "uplot-LICENCE",
        "uplot-SOURCES.md",
        "bw-plot.js",
        "bw-events.js",
        "analyse.js",
    }


def test_the_assets_route_serves_the_installed_package_bytes(starter_project) -> None:
    """Q5's mechanism: a contract change reaches standalone through a
    package release and a pin bump — the served bytes ARE the installed
    benchweave_ui_html bytes (its own verifier is the authority)."""
    seam, _ = _build_seam(starter_project)
    from fastapi.testclient import TestClient

    with TestClient(build_app(seam, policy=_policy()), base_url="http://127.0.0.1:8477") as client:
        for name in ("tokens.css", "themes.css"):
            served = client.get(f"/assets/{name}")
            assert served.status_code == 200, name
            assert served.content == (ui_html_assets.ASSETS_DIR / name).read_bytes(), name


def test_a_tampered_renderer_package_refuses_startup(
    starter_project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The verifier's discipline holds from the INSTALLED location: a
    corrupted package copy makes build_app itself refuse."""
    import shutil

    corrupted = tmp_path / "renderer-assets"
    shutil.copytree(ui_html_assets.ASSETS_DIR, corrupted)
    (corrupted / "tokens.css").write_text("/* tampered */\n")
    monkeypatch.setattr(ui_html_assets, "ASSETS_DIR", corrupted)
    seam, _ = _build_seam(starter_project)
    with pytest.raises(ValueError, match="standalone_ui_asset_renderer"):
        build_app(seam, policy=_policy())


# --- the server identity (the pyproject name is the machine source) ----------


def test_the_mcp_server_bears_the_server_identity(starter_project) -> None:
    from benchweave_sdk_server.mcp import build_mcp

    seam, _ = _build_seam(starter_project)
    server = build_mcp(seam)
    assert server.name == "benchweave-sdk-server"


def test_the_http_app_bears_the_server_identity(starter_project) -> None:
    seam, _ = _build_seam(starter_project)
    app = build_app(seam, policy=_policy())
    assert app.title == "BenchWeave SDK server"


def test_the_standalone_names_that_name_the_mode_stay() -> None:
    """The residual ruling: standalone_plugin_* prefixes and standalone.css
    NAME THE MODE, not the package — they stay. The I1 banner literal is
    retired (I2a §3.2): the §D.1 component carries SW-27's intent now."""
    from benchweave_sdk_server.presentation import mode_banner_entries

    entries = {entry.key: entry.wording for entry in mode_banner_entries(simulated=False).modes}
    assert entries["no-gateway"] == "NO GATEWAY · LOCAL PRESENTATION ONLY"
    assert (HOST_ASSETS / "standalone.css").is_file()


# --- the reading result schema admits the declared value types -----------------


def test_the_reading_result_admits_absent_and_non_numeric_values() -> None:
    """Scenario reads serve the declared parameter types (float/int/bool/
    enum/string) and an ABSENT value (loading) — the pinned MCP output
    schema must admit what the pipeline can honestly serve (fastmcp
    validates structured output against it)."""
    schema = catalogue.spec("parameter_read").result_schema
    assert schema is not None
    assert schema["properties"]["value"]["type"] == [
        "number",
        "string",
        "boolean",
        "null",
    ]


def test_a_loading_read_validates_over_mcp(starter_project) -> None:
    """The live proof of the widened schema: a loading-scenario read (value
    null) passes fastmcp's structured-output validation."""
    import asyncio

    from fastmcp import Client

    from benchweave_sdk_server.mcp import build_mcp

    seam, _ = _build_seam(starter_project, scenario="loading")

    async def run() -> None:
        await seam.session.connect()
        server = build_mcp(seam)
        async with Client(server) as client:
            result = await client.call_tool(
                "bws_v1_parameter_read", {"device_id": DEV, "parameter": "voltage"}
            )
            data = result.structured_content or {}
            assert data["value"] is None
            assert data["quality"] == "loading"

    asyncio.run(run())
