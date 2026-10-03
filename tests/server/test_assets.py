"""Vendored assets: inventory freshness and serve-time tamper refusal."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from benchweave_sdk_server.assets import build_inventory, ui_assets_root, verify_ui_assets

ROOT = Path(__file__).resolve().parents[2] / "src" / "benchweave_sdk_server" / "ui_assets"


def test_committed_inventory_matches_the_bytes_on_disk() -> None:
    committed = json.loads((ROOT / "inventory.json").read_text())
    assert committed == build_inventory(ROOT)


def test_the_inventory_lists_only_host_owned_files() -> None:
    """tokens.css/themes.css/globals.css serve from the installed ui-html
    package (§4.6, D-B3); this tree owns the host shell assets plus the
    plot wrapper's vendored uPlot bytes (I2a §3.3, #310's host-side
    ruling)."""
    committed = json.loads((ROOT / "inventory.json").read_text())
    assert {row["path"] for row in committed["assets"]} == {
        "htmx.min.js",
        "sse.js",
        "standalone.css",
        "uplot.min.js",
        "uplot.css",
        "uplot-LICENCE",
        "uplot-SOURCES.md",
        "bw-plot.js",
    }


def test_ui_assets_root_verifies_and_returns_the_root() -> None:
    root = ui_assets_root()
    assert (root / "htmx.min.js").is_file()


def test_missing_asset_refuses_startup(tmp_path: Path) -> None:
    copy = tmp_path / "ui_assets"
    shutil.copytree(ROOT, copy)
    (copy / "htmx.min.js").unlink()
    with pytest.raises(ValueError, match="standalone_ui_asset_tampered: htmx.min.js"):
        verify_ui_assets(copy)


def test_traversal_row_refuses(tmp_path: Path) -> None:
    copy = tmp_path / "ui_assets"
    shutil.copytree(ROOT, copy)
    inventory = json.loads((copy / "inventory.json").read_text())
    inventory["assets"][0]["path"] = "../outside.css"
    (copy / "inventory.json").write_text(json.dumps(inventory))
    with pytest.raises(ValueError, match="standalone_ui_asset_unsafe"):
        verify_ui_assets(copy)


def test_invalid_inventory_refuses(tmp_path: Path) -> None:
    copy = tmp_path / "ui_assets"
    shutil.copytree(ROOT, copy)
    (copy / "inventory.json").write_text("{not json")
    with pytest.raises(ValueError, match="standalone_ui_asset_inventory_invalid"):
        verify_ui_assets(copy)


def test_tampered_asset_refuses_startup() -> None:
    """M2 RED arm: the STARTUP claim — tampered bytes make build_app itself
    refuse, not a per-request 500 after the shell already served."""
    import shutil


    package_root = ROOT.parent
    backup = package_root.parent / "ui_assets.backup"
    shutil.copytree(ROOT, backup)
    try:
        (ROOT / "htmx.min.js").write_text("/* tampered */\n")
        with pytest.raises(ValueError, match="standalone_ui_asset_tampered"):
            build_test_app(package_root)
    finally:
        shutil.rmtree(ROOT)
        shutil.move(str(backup), str(ROOT))


def build_test_app(package_root):
    from benchweave_sdk_server import web
    from benchweave_sdk_server.seam import StandaloneSeam

    class _NullSeam(StandaloneSeam):
        def __init__(self) -> None:
            pass

    return web.build_app(_NullSeam(), policy=_test_policy())


def _test_policy():
    from benchweave_sdk_server.security import GuardPolicy

    return GuardPolicy.complete(
        bound_host="127.0.0.1", bound_port=8477, bearer_token="t", csrf_token="t"
    )


def test_the_htmx_indicator_rules_have_a_same_origin_equivalent() -> None:
    """Fold R-f: htmx injects a <style> for its indicator classes at boot,
    which the strict style-src 'self' CSP blocks - the host ships the same
    rules from its own stylesheet so the blocked injection loses nothing."""
    css = (ROOT / "standalone.css").read_text(encoding="utf-8")
    assert ".htmx-indicator" in css
    assert "opacity: 0" in css
    assert ".htmx-request" in css
