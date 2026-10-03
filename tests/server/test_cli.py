"""The CLI: listener rules (verbatim SDK reuse), startup validation order,
and the stdio entry's guard exemption posture."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from benchweave_sdk_server.cli import cli


def test_wildcard_listener_is_refused(starter_project: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["serve", str(starter_project), "--host", "0.0.0.0", "--no-open"]
    )
    assert result.exit_code == 2
    assert "preview_unsafe_listener" in result.output


def test_non_loopback_requires_allow_network(starter_project: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["serve", str(starter_project), "--host", "192.168.1.5", "--no-open"]
    )
    assert result.exit_code == 2
    assert "preview_network_acknowledgement_required" in result.output


def test_invalid_listener_name_is_refused(starter_project: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["serve", str(starter_project), "--host", "not-an-address", "--no-open"]
    )
    assert result.exit_code == 2
    assert "preview_invalid_listener" in result.output


def test_invalid_plugin_refuses_before_any_bind(tmp_path: Path) -> None:
    """SW-05: descriptor validation happens before the port binds — the
    refusal names the plugin, not the listener."""
    runner = CliRunner()
    result = runner.invoke(cli, ["serve", str(tmp_path), "--no-open"])
    assert result.exit_code == 2
    assert "standalone_plugin_project" in result.output


def test_corrupt_descriptor_refuses_with_the_sdk_diagnostics(
    starter_project: Path, tmp_path: Path,
) -> None:
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "corrupt"
    create_project(project, "example_plugin")
    create_ui_resources(project, "example_plugin")
    descriptor = project / "src" / "example_plugin" / "descriptor.json"
    document = json.loads(descriptor.read_text())
    document["parameters"] = "not-a-list"
    descriptor.write_text(json.dumps(document))
    runner = CliRunner()
    result = runner.invoke(cli, ["serve", str(project), "--no-open"])
    assert result.exit_code == 2
    assert "standalone_plugin_invalid" in result.output


def test_mcp_command_builds_without_an_http_listener(starter_project: Path) -> None:
    """The stdio entry constructs the full server; it never binds a port
    (NFR-S4 posture — asserted by building everything short of run())."""
    from benchweave_sdk_server.cli import _build_seam
    from benchweave_sdk_server.mcp import build_mcp, registered_tool_names

    seam = _build_seam(starter_project)
    server = build_mcp(seam, authoring=True)
    names = set(registered_tool_names(server))
    assert "bws_v1_host_info" in names
    assert "plugin_new" in names
