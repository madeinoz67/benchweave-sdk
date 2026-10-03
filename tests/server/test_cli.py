"""The CLI: listener rules (verbatim SDK reuse), startup validation order,
and the stdio entry's guard exemption posture."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
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


# --- slice A: the console entry degrades gracefully without the extra ------

#: The modules only `benchweave-sdk[server]` installs.
_SERVER_EXTRA_MODULES = ("fastapi", "fastmcp", "uvicorn", "jinja2")


def _simulate_default_install(monkeypatch: pytest.MonkeyPatch, *blocked: str) -> None:
    """Make the extra's modules absent: a None sys.modules entry makes
    ``import <name>`` raise ImportError — the same failure the lazy imports
    hit on an install without the extra. The host modules that import them
    are dropped so their import re-executes against the blocked set.
    """
    for name in blocked:
        monkeypatch.setitem(sys.modules, name, None)
    for module in ("benchweave_sdk_server.web", "benchweave_sdk_server.mcp"):
        monkeypatch.delitem(sys.modules, module, raising=False)


def test_serve_without_the_server_extra_refuses_gracefully(
    starter_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A default install gets the console script but not the stack: serve
    refuses with the prefixed message naming the install command, exit 2 —
    never an ImportError traceback (the R-9 shim pattern, slice A)."""
    _simulate_default_install(monkeypatch, "fastapi", "uvicorn")
    result = CliRunner().invoke(cli, ["serve", str(starter_project), "--no-open"])
    assert result.exit_code == 2
    assert "benchweave_sdk_server_extras_missing:" in result.output
    assert "benchweave-sdk[server]" in result.output


def test_mcp_without_the_server_extra_refuses_gracefully(
    starter_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _simulate_default_install(monkeypatch, "fastmcp")
    result = CliRunner().invoke(cli, ["mcp", str(starter_project)])
    assert result.exit_code == 2
    assert "benchweave_sdk_server_extras_missing:" in result.output


def test_help_works_without_the_server_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI module itself imports nothing from the extra set: --help
    answers on a default install (the cli module is re-imported with the
    whole extra set blocked)."""
    _simulate_default_install(monkeypatch, *_SERVER_EXTRA_MODULES)
    monkeypatch.delitem(sys.modules, "benchweave_sdk_server.cli", raising=False)
    import benchweave_sdk_server.cli as cli_module

    result = CliRunner().invoke(cli_module.cli, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.output
