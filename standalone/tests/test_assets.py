"""Vendored assets: inventory freshness and serve-time tamper refusal."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from benchweave_standalone.assets import build_inventory, ui_assets_root, verify_ui_assets

ROOT = Path(__file__).parent.parent / "src" / "benchweave_standalone" / "ui_assets"


def test_committed_inventory_matches_the_bytes_on_disk() -> None:
    committed = json.loads((ROOT / "inventory.json").read_text())
    assert committed == build_inventory(ROOT)


def test_vendored_tokens_are_the_canonical_bytes() -> None:
    """tokens.css/themes.css are governed copies of the gateway UI corpus
    (D5 carries the freshness gate; this pins the CURRENT digests so any
    motion here is a visible same-commit diff)."""
    import hashlib

    committed = {row["path"]: row["sha256"] for row in
                 json.loads((ROOT / "inventory.json").read_text())["assets"]}
    for name in ("tokens.css", "themes.css"):
        digest = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        assert digest == committed[name]


def test_ui_assets_root_verifies_and_returns_the_root() -> None:
    root = ui_assets_root()
    assert (root / "tokens.css").is_file()


def test_tampered_asset_refuses_startup(tmp_path: Path) -> None:
    copy = tmp_path / "ui_assets"
    shutil.copytree(ROOT, copy)
    (copy / "tokens.css").write_text("/* tampered */\n")
    with pytest.raises(ValueError, match="standalone_ui_asset_tampered: tokens.css"):
        verify_ui_assets(copy)


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
