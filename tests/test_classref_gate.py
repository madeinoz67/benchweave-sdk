"""The rendered gate: A11 extension-blindness, the banked-baseline RED
(A4), and the F1 render assertions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchweave_sdk.classref import LAYOUT_EXTENSION_KEY, find_reference
from benchweave_sdk.classref_gate import census, verify_ui
from benchweave_sdk.presentation import validate_presentation

FIXTURES = Path(__file__).parent / "fixtures" / "classref"
REFERENCE = find_reference("otdp.logic_analyser/1.0.0")


def _raw(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def test_layout_block_extension_blind_a11(tmp_path: Path) -> None:
    """The extension-blindness control (record §5/5): a layout-bearing
    manifest passes the canonical validator unchanged."""
    from helpers_classref import build_classref_project

    project, derived = build_classref_project(tmp_path / "project")
    report = validate_presentation(
        _raw(derived.envelope),
        descriptor_raw=(FIXTURES / "descriptor-f1.json").read_bytes(),
        resources={
            "manifest.json": _raw(derived.manifest),
            "settings/configure.schema.json": _raw(derived.settings_schema),
        },
        binding_catalogue=derived.catalogue,
    )
    assert report.valid, [(f.code, f.path, f.message) for f in report.findings]
    assert LAYOUT_EXTENSION_KEY in derived.manifest["extensions"]


def test_census_counts_the_contract_surfaces() -> None:
    """The census keys on the §E.1 surfaces the ui-html partials emit."""
    from benchweave_ui_html.data import ButtonData, ModeBannerData, ModeEntry
    from benchweave_ui_html.partials import render_button, render_mode_banner

    html = (
        render_button(ButtonData(label="arm"))
        + render_button(ButtonData(label="abort"))
        + render_mode_banner(
        ModeBannerData(modes=(ModeEntry(key="simulated", wording="Simulated"),))
    )
    )
    seen = census(html)
    assert seen["buttons"] == ["arm", "abort"]
    assert seen["mode_banners"] == 1
    assert seen["confirms"] == 0


def test_f1_project_renders_and_gate_passes(tmp_path: Path) -> None:
    """A1/A10 render arms: the derived project renders; the census shows
    the run buttons in declaration order; the gate passes clean."""
    from helpers_classref import build_classref_project

    project, derived = build_classref_project(tmp_path / "f1")
    report = verify_ui(project, reference=REFERENCE)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    assert report.reported_deviations  # configure birth + decode divergence


def test_banked_baseline_fails_loudly_a4(tmp_path: Path) -> None:
    """A4: the gate FAILS the hand-minimal baseline with >=6 findings."""

    from helpers_classref import build_classref_project

    project, derived = build_classref_project(tmp_path / "baseline")
    package = next((project / "src").iterdir())
    baseline_manifest = {
        "contract_version": derived.manifest["contract_version"],
        "plugin_id": derived.manifest["plugin_id"],
        "descriptor_sha256": derived.manifest["descriptor_sha256"],
        "bindings": [],
        "pages": [
            {
                "id": "readings",
                "title": "Readings",
                "kind": "readings",
                "bindings": [],
                "required": True,
            }
        ],
    }
    (package / "ui" / "manifest.json").write_bytes(_raw(baseline_manifest))
    envelope = dict(derived.envelope)
    import hashlib

    envelope["manifest"] = {
        "path": "manifest.json",
        "sha256": hashlib.sha256(_raw(baseline_manifest)).hexdigest(),
    }
    (package / "presentation.json").write_bytes(_raw(envelope))
    minimal_catalogue = {
        "contract_version": derived.catalogue["contract_version"],
        "descriptor_sha256": derived.catalogue["descriptor_sha256"],
        "targets": [],
    }
    (package / "binding-catalogue.json").write_bytes(_raw(minimal_catalogue))
    report = verify_ui(project, reference=REFERENCE)
    codes = [finding.code for finding in report.findings]
    assert not report.clean
    assert len(report.findings) >= 6, codes
    assert "classref_gate_missing" in codes
