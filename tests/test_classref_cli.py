"""The derive-ui / verify-ui CLI commands."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner
from helpers_classref import build_classref_project

from benchweave_sdk.cli import cli


def test_derive_then_verify_clean_roundtrip(tmp_path: Path) -> None:
    project, _derived = build_classref_project(tmp_path / "proj")
    # verify-ui first: the helper already wrote the derived set.
    runner = CliRunner()
    result = runner.invoke(cli, ["verify-ui", str(project)])
    assert result.exit_code == 0, result.output
    # A dirty manifest refuses without --force.
    manifest = next((project / "src").iterdir()) / "ui" / "manifest.json"
    manifest.write_bytes(manifest.read_bytes().replace(b"capture", b"renamed"))
    result = runner.invoke(cli, ["derive-ui", str(project)])
    assert result.exit_code != 0
    assert "derive_ui_dirty_tree" in result.output
    result = runner.invoke(cli, ["derive-ui", str(project), "--force"])
    assert result.exit_code == 0, result.output
    assert "cannot_derive" in result.output
