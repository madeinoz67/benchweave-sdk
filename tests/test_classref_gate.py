"""The rendered gate: A11 extension-blindness, the banked-baseline RED
(A4), and the F1 render assertions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

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


def test_scalar_scaffold_coverage_passes_vacuously_a10(tmp_path: Path) -> None:
    """A10's scalar arm (record §5.1): a fresh scalar scaffold (no class
    reference; its descriptor declares no invoke-class actions) PASSES
    coverage — the gate invents no obligations the descriptor does not
    create, and the class-expect arm skips."""
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "scalar"
    create_project(project, "veridian_scalar_plugin", with_ui=True)
    create_ui_resources(project, "veridian_scalar_plugin")
    report = verify_ui(project, reference=None)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    assert report.reported_deviations == ()


def test_h3_abort_deviation_refused_by_predicate(tmp_path: Path) -> None:
    """H3 (convergent): a deviation naming the energy-removing action's
    URN refuses classref_deviation_forbidden — the predicate must match a
    versioned URN."""
    from helpers_classref import build_classref_project

    from benchweave_sdk.classref import validate_declaration

    _project, derived = build_classref_project(tmp_path / "f1")
    document = {
        **derived.declaration,
        "deviations": [
            {
                "expectation_id": "otdp.logic_analyser.abort/1.0.0",
                "reason": "attempting to place a gate between the operator and abort",
            }
        ],
    }
    with pytest.raises(ValueError, match="^classref_deviation_forbidden:"):
        validate_declaration(derived, document)


def test_h3_authored_abort_deviation_fails_the_gate(tmp_path: Path) -> None:
    """H3 end to end: an authored ledger naming abort must fail verify-ui
    (typed refusal, exit 1) — never be silently ignored."""
    from click.testing import CliRunner

    from benchweave_sdk.cli import cli
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "scalar"
    create_project(project, "veridian_scalar_plugin", with_ui=True)
    create_ui_resources(project, "veridian_scalar_plugin")
    package = next((project / "src").iterdir())
    declaration = {
        "contract_version": "0.1.0",
        "profile_ids": [],
        "reference_version": "0.1.0",
        "deviations": [
            {
                "expectation_id": "otdp.logic_analyser.abort/1.0.0",
                "reason": "unauthorised gate before abort",
            }
        ],
    }
    (package / "ui" / "class-reference.json").write_bytes(_raw(declaration))
    result = CliRunner().invoke(cli, ["verify-ui", str(project)])
    assert result.exit_code != 0
    assert "classref_deviation_forbidden" in result.output or (
        "classref_unknown_expectation" in result.output
    )


def test_h2_derived_layout_block_matches_family_schema(tmp_path: Path) -> None:
    """H2: the derived block must satisfy its own family schema — today the
    reading nodes emit {kind: \"reading\", reading_kind: ...}, a shape the
    schema's enum refuses."""
    import jsonschema
    from helpers_classref import build_classref_project

    from benchweave_sdk.classref import layout_schema

    _project, derived = build_classref_project(tmp_path / "f1")
    errors = list(
        jsonschema.Draft202012Validator(layout_schema()).iter_errors(
            derived.layout_block
        )
    )
    assert not errors, [e.message for e in errors[:3]]


def test_h2_malformed_layout_block_refuses(tmp_path: Path) -> None:
    """H2: a manifest carrying a block that fails the family schema refuses
    classref_layout_invalid at the gate — it never renders, never passes."""
    import hashlib

    from helpers_classref import build_classref_project

    project, derived = build_classref_project(tmp_path / "f1")
    package = next((project / "src").iterdir())
    manifest = json.loads((package / "ui" / "manifest.json").read_bytes())
    block = manifest["extensions"]["plugin-ui-class-reference:layout"]
    block["pages"][0]["sections"][0].pop("surface")  # schema-required key
    manifest["extensions"]["plugin-ui-class-reference:layout"] = block
    raw = (json.dumps(manifest, indent=2) + "\n").encode()
    (package / "ui" / "manifest.json").write_bytes(raw)
    envelope = json.loads((package / "presentation.json").read_bytes())
    envelope["manifest"]["sha256"] = hashlib.sha256(raw).hexdigest()
    (package / "presentation.json").write_bytes(
        (json.dumps(envelope, indent=2) + "\n").encode()
    )
    with pytest.raises(ValueError, match="^classref_layout_invalid:"):
        verify_ui(project, reference=REFERENCE)


def test_m8_attribute_rows_are_asserted() -> None:
    """M8/F2: the census-vs-expect lane asserts the attribute census —
    lane-kind counts laundered in the render must fail."""
    from benchweave_sdk.classref_gate import _assert_expect

    expectation = {
        "components": {
            "digital-lanes": {
                "count": 1,
                "per_page": "capture",
                "attribute": {
                    "data-bw-lane-kind=channel": 2,
                    "data-bw-lane-kind=group": 1,
                },
            }
        }
    }
    censused = {
        "capture": {
            "lanes_figures": 1, "buttons": [], "numerics": 0, "panels": 1,
            "mode_banners": 1, "lane_kinds": {"channel": 2, "group": 3},
            "confirms": 0, "data_tables": 0,
        }
    }
    findings, reported = _assert_expect(expectation, censused)
    assert findings, "a laundered group count must fail"
    assert "classref_gate_excess" in findings[0].code


def test_m10_per_page_naming_a_non_rendered_page_refuses() -> None:
    """M10/F7: an expectation row whose per_page names a page the render
    did not serve refuses — no silent pooling over an absent page."""
    from benchweave_sdk.classref_gate import _assert_expect

    expectation = {
        "components": {"button": {"count": 1, "per_page": "ghost-page"}}
    }
    censused = {"capture": {"buttons": ["arm"], "panels": 1, "mode_banners": 1,
                             "lanes_figures": 0, "numerics": 0, "lane_kinds": {},
                             "confirms": 0, "data_tables": 0}}
    with pytest.raises(ValueError, match="^classref_gate_page:"):
        _assert_expect(expectation, censused)


def test_m10_unknown_component_refuses() -> None:
    """M10/F7: an expectation component the census cannot key on the
    contract-pinned §E.1 surfaces refuses — the record's underpowered
    branch is a refusal, not silence."""
    from benchweave_sdk.classref_gate import _assert_expect

    expectation = {"components": {"sparkline": {"count": 1}}}
    censused = {"capture": {"buttons": [], "panels": 1, "mode_banners": 1,
                             "lanes_figures": 0, "numerics": 0, "lane_kinds": {},
                             "confirms": 0, "data_tables": 0}}
    with pytest.raises(ValueError, match="^classref_gate_unknown_component:"):
        _assert_expect(expectation, censused)


def test_m9_known_binding_overlay_applies_content(tmp_path: Path) -> None:
    """M9: an overlay row for a DERIVED binding id applies its content;
    a NEW binding id is refused with the unknown-binding message."""
    from helpers_classref import build_classref_project

    from benchweave_sdk.classref import compose_manifest

    _project, derived = build_classref_project(tmp_path / "m9")
    composed = compose_manifest(
        derived.manifest,
        {"bindings": [
            {"id": "arm", "kind": "procedure", "target_id": "arm",
             "preset_ids": []},
        ]},
    )
    arm = next(row for row in composed["bindings"] if row["id"] == "arm")
    assert arm["kind"] == "procedure"  # composed content, not ignored
    with pytest.raises(ValueError, match="^classref_binding_unknown:"):
        compose_manifest(
            derived.manifest,
            {"bindings": [{"id": "brand-new", "kind": "procedure",
                           "target_id": "brand-new"}]},
        )


def test_l11_l3_coverage_needs_its_named_controls(tmp_path: Path) -> None:
    """L11/F9: L3 is covered by its plan-named controls (the effective
    settings surface on the configuration page), not by any button. The
    auto-deviant arm: with the ledger declaring the preset birth, the row
    REPORTS; the failable arm for the whole coverage emission is the
    baseline (undeclared rows fail classref_gate_uncovered)."""
    from helpers_classref import build_classref_project

    project, derived = build_classref_project(tmp_path / "l11")
    report = verify_ui(project, reference=REFERENCE)
    assert report.clean
    assert "otdp.logic_analyser.configure/1.0.0" in report.reported_deviations
    # The configuration page renders the L3 surface (data table + numerics).
    from benchweave_sdk.classref_gate import census
    from benchweave_sdk.classref_gate_render import render_pages

    html = render_pages(project, ["configuration"])["configuration"]
    seen = census(html)
    assert seen["data_tables"] == 1
    assert seen["numerics"] >= 1


def test_m5_coverage_emission_is_load_bearing(tmp_path: Path) -> None:
    """M5's mutation-survival arm: an undeclared unreachable action fails
    the gate with classref_gate_uncovered — deleting the uncovered
    emission cannot survive this test."""
    import json as _json

    from helpers_classref import build_classref_project

    project, derived = build_classref_project(tmp_path / "m5")
    package = next((project / "src").iterdir())
    declaration = _json.loads(
        (package / "ui" / "class-reference.json").read_bytes()
    )
    # Drop every deviation: the declared-coverage arm must now FAIL.
    declaration["deviations"] = []
    (package / "ui" / "class-reference.json").write_bytes(
        (json.dumps(declaration, indent=2) + "\n").encode()
    )
    report = verify_ui(project, reference=REFERENCE)
    codes = [finding.code for finding in report.findings]
    assert not report.clean
    assert "classref_gate_uncovered" in codes or "classref_gate_undeclared" in codes, codes


def test_f4_color_role_hint_on_lanes_forbidden(tmp_path: Path) -> None:
    """F4: a color-role hint on a digital_lanes channel is forbidden in
    the composed manifest (belt over the schema's own refusal)."""
    import hashlib

    from helpers_classref import build_classref_project

    project, derived = build_classref_project(tmp_path / "f4c")
    package = next((project / "src").iterdir())
    manifest = json.loads((package / "ui" / "manifest.json").read_bytes())
    plot = manifest["pages"][0]["plots"][0]
    plot["channel_hints"] = [
        {"variable_id": "d0", "visible": True, "color_role": "accent"}
    ]
    raw = (json.dumps(manifest, indent=2) + "\n").encode()
    (package / "ui" / "manifest.json").write_bytes(raw)
    envelope = json.loads((package / "presentation.json").read_bytes())
    envelope["manifest"]["sha256"] = hashlib.sha256(raw).hexdigest()
    (package / "presentation.json").write_bytes(
        (json.dumps(envelope, indent=2) + "\n").encode()
    )
    with pytest.raises(ValueError, match="^classref_gate_forbidden:"):
        verify_ui(project, reference=REFERENCE)


def test_f4_intermediated_energy_removing_action(tmp_path: Path) -> None:
    """F4: a staging control on the abort binding — any control between
    the operator and the energy-removing action — is forbidden."""
    import hashlib

    from helpers_classref import build_classref_project

    project, derived = build_classref_project(tmp_path / "f4i")
    package = next((project / "src").iterdir())
    manifest = json.loads((package / "ui" / "manifest.json").read_bytes())
    block = manifest["extensions"]["plugin-ui-class-reference:layout"]
    run = next(
        section for page in block["pages"] if page["page_id"] == "capture"
        for section in page["sections"] if section["id"] == "run"
    )
    run["children"].append({"binding_id": "abort", "kind": "numeric",
                            "field": "max_duration_ms"})
    raw = (json.dumps(manifest, indent=2) + "\n").encode()
    (package / "ui" / "manifest.json").write_bytes(raw)
    envelope = json.loads((package / "presentation.json").read_bytes())
    envelope["manifest"]["sha256"] = hashlib.sha256(raw).hexdigest()
    (package / "presentation.json").write_bytes(
        (json.dumps(envelope, indent=2) + "\n").encode()
    )
    with pytest.raises(ValueError, match="^classref_gate_forbidden:"):
        verify_ui(project, reference=REFERENCE)


def test_f4_untraceable_lane_label(tmp_path: Path) -> None:
    """F4: a lane label not traceable to the descriptor's channel
    identity or the group pattern is forbidden."""
    import hashlib

    from helpers_classref import build_classref_project

    project, derived = build_classref_project(tmp_path / "f4u")
    package = next((project / "src").iterdir())
    catalogue = json.loads((package / "binding-catalogue.json").read_bytes())
    target = next(t for t in catalogue["targets"] if t["id"] == "capture")
    target["variables"].append(
        {"id": "ghost", "type": "string", "unit": None, "shape": "vector"}
    )
    (package / "binding-catalogue.json").write_bytes(
        (json.dumps(catalogue, indent=2) + "\n").encode()
    )
    manifest = json.loads((package / "ui" / "manifest.json").read_bytes())
    plot = manifest["pages"][0]["plots"][0]
    plot["y"] = ["ghost", "d1"]
    plot["channel_hints"] = [{"variable_id": "ghost", "visible": True}]
    plot["lane_groups"] = []
    raw = (json.dumps(manifest, indent=2) + "\n").encode()
    (package / "ui" / "manifest.json").write_bytes(raw)
    envelope = json.loads((package / "presentation.json").read_bytes())
    envelope["manifest"]["sha256"] = hashlib.sha256(raw).hexdigest()
    (package / "presentation.json").write_bytes(
        (json.dumps(envelope, indent=2) + "\n").encode()
    )
    report = verify_ui(project, reference=REFERENCE)
    forbidden = [f for f in report.findings if f.code == "classref_gate_forbidden"]
    assert forbidden, [f"{f.code}: {f.detail}" for f in report.findings]


def test_m5_uncovered_alone_is_pinned() -> None:
    """M5-residual (lane 1): a plan row with no divergence, no control
    and no ledger entry yields classref_gate_uncovered ALONE — the
    uncovered emission cannot die under the undeclared disjunction."""
    from benchweave_sdk.classref_gate import _coverage_findings

    plan = {
        "otdp.logic_analyser.trigger/1.0.0": {
            "level": "L1", "page": "capture", "fields": [],
            "declared_deviation": False,
        }
    }
    censused = {
        "capture": {"buttons": [], "lanes_figures": 0, "panels": 1,
                     "numerics": 0, "mode_banners": 1, "lane_kinds": {},
                     "confirms": 0, "data_tables": 0, "lane_labels": []}
    }
    findings, reported = _coverage_findings(plan, censused, {"deviations": []})
    assert [f.code for f in findings] == ["classref_gate_uncovered"]
    assert findings[0].detail.startswith("otdp.logic_analyser.trigger/1.0.0")
    assert reported == []


def test_l8_absent_bounds_render_without_fabricated_values(tmp_path: Path) -> None:
    """L8: the F1 arm's max_duration_ms has no catalogue maximum; the
    render must not fabricate max=\"0\" (or min/step zeros)."""
    from helpers_classref import build_classref_project

    from benchweave_sdk.classref_gate_render import render_pages

    project, _derived = build_classref_project(tmp_path / "l8")
    html = render_pages(project, ["capture"])["capture"]
    assert 'max="0"' not in html, "a fabricated ceiling escaped the render"
    assert 'min="0"' not in html, "a fabricated floor escaped the render"
    assert "action-arm-max_duration_ms" in html  # the control still renders


def test_f5_component_id_downgrades_missing(tmp_path: Path) -> None:
    """F5-component (record §4's letter): a declared deviation downgrades
    exactly that expectation — a component id is in the vocabulary and
    the missing count becomes REPORTED."""
    import hashlib

    from helpers_classref import build_classref_project

    project, derived = build_classref_project(tmp_path / "f5")
    package = next((project / "src").iterdir())
    # The ledger declares the numeric-input expectation id.
    declaration = json.loads((package / "ui" / "class-reference.json").read_bytes())
    declaration["deviations"].append(
        {"expectation_id": "numeric-input",
         "reason": "numeric surfaces deferred at birth"}
    )
    (package / "ui" / "class-reference.json").write_bytes(
        (json.dumps(declaration, indent=2) + "\n").encode()
    )
    # Strip every numeric control from the render (strip the layout nodes).
    manifest = json.loads((package / "ui" / "manifest.json").read_bytes())
    block = manifest["extensions"]["plugin-ui-class-reference:layout"]
    for page in block["pages"]:
        for section in page["sections"]:
            section["children"] = [
                node for node in section["children"]
                if node.get("kind") != "numeric"
            ]
    raw = (json.dumps(manifest, indent=2) + "\n").encode()
    (package / "ui" / "manifest.json").write_bytes(raw)
    envelope = json.loads((package / "presentation.json").read_bytes())
    envelope["manifest"]["sha256"] = hashlib.sha256(raw).hexdigest()
    (package / "presentation.json").write_bytes(
        (json.dumps(envelope, indent=2) + "\n").encode()
    )
    report = verify_ui(project, reference=REFERENCE)
    numeric_missing = [
        f for f in report.findings if f.code == "classref_gate_missing"
        and "numeric-input" in f.detail
    ]
    assert not numeric_missing, [f.detail for f in numeric_missing]
    assert "numeric-input" in report.reported_deviations


def test_l11_l3_needs_the_named_surface_not_any_button(tmp_path: Path) -> None:
    """L11: an L3 row is covered by its plan-named surface (the settings
    data-table), not by any button that happens to render on the page."""
    import hashlib

    from helpers_classref import build_classref_project

    project, derived = build_classref_project(tmp_path / "l11b")
    package = next((project / "src").iterdir())
    # Strip the configuration page's data-table and its ledger row; leave
    # a foreign button so the any-button predicate would wrongly cover.
    manifest = json.loads((package / "ui" / "manifest.json").read_bytes())
    block = manifest["extensions"]["plugin-ui-class-reference:layout"]
    config_page = next(p for p in block["pages"] if p["page_id"] == "configuration")
    for section in config_page["sections"]:
        section["children"] = [
            node for node in section["children"]
            if node.get("kind") != "data-table"
        ] + [{"binding_id": "arm", "kind": "button"}]
    raw = (json.dumps(manifest, indent=2) + "\n").encode()
    (package / "ui" / "manifest.json").write_bytes(raw)
    envelope = json.loads((package / "presentation.json").read_bytes())
    envelope["manifest"]["sha256"] = hashlib.sha256(raw).hexdigest()
    (package / "presentation.json").write_bytes(
        (json.dumps(envelope, indent=2) + "\n").encode()
    )
    declaration = json.loads((package / "ui" / "class-reference.json").read_bytes())
    declaration["deviations"] = [
        row for row in declaration["deviations"]
        if row["expectation_id"] != "otdp.logic_analyser.configure/1.0.0"
    ]
    (package / "ui" / "class-reference.json").write_bytes(
        (json.dumps(declaration, indent=2) + "\n").encode()
    )
    report = verify_ui(project, reference=REFERENCE)
    uncovered = [f for f in report.findings
                 if f.code == "classref_gate_uncovered"
                 and "configure" in f.detail]
    assert uncovered, [f"{f.code}: {f.detail}" for f in report.findings]


def test_f4c_decoder_pinned_project_passes_the_gate_e2e(tmp_path: Path) -> None:
    """F4c: the traceable set includes the pinned decoder names — the
    decoder-labeled lanes of a decoder-pinned project trace (this e2e arm
    is the suite gap that hid the omission)."""
    from helpers_classref import build_classref_project

    project, _derived = build_classref_project(
        tmp_path / "f1da",
        descriptor_fixture="descriptor-f1-da.json",
    )
    report = verify_ui(project, reference=REFERENCE)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]


def test_f3b_gate_passes_end_to_end_a9(tmp_path: Path) -> None:
    """A9's F3b acceptance, end to end: the gate passes with trigger and
    the partial group rendered (the arm that never ran)."""
    from helpers_classref import build_classref_project

    from benchweave_sdk.classref_gate import census
    from benchweave_sdk.classref_gate_render import render_pages

    project, derived = build_classref_project(
        tmp_path / "f3b",
        descriptor_fixture="descriptor-f3b.json",
    )
    report = verify_ui(project, reference=REFERENCE)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    html = render_pages(project, ["capture"])["capture"]
    seen = census(html)
    assert "trigger" in seen["buttons"], seen["buttons"]
    assert seen["numerics"] >= 1


def test_f8b_reference_less_unknown_action_is_typed(tmp_path: Path) -> None:
    """F8b scalar arm: the coverage_plan_without_reference path refuses
    classref_unknown_action for a catalog-absent URN — never KeyError."""
    from benchweave_sdk.classref import coverage_plan_without_reference

    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["actions"]["com.veridian-labs.ghost/1.0.0"] = {
        "binding": {"kind": "adapter", "key": "ghost"},
        "input_constraints": {},
        "timeout_ms": 1000,
        "side_effect": "none",
        "cancellable": True,
        "retry": "never",
    }
    with pytest.raises(ValueError, match="^classref_unknown_action:"):
        coverage_plan_without_reference(
            descriptor, FIXTURES / "descriptor-f1.json"
        )


def test_l2_coverage_is_per_action_not_per_page(tmp_path: Path) -> None:
    """L5 fold row 2 (derivation lane F1, MEDIUM): the D14 L2 arm covers an
    action by ITS OWN rendered inputs, never by the page's summed input
    count. Two L2 vendor actions share device-features; stripping ONE
    action's inputs (keeping its button) leaves the other action's inputs
    standing — the stripped action must be named classref_gate_uncovered,
    while a page-summed arm would launder it with the sibling's controls."""
    import hashlib

    from helpers_classref import build_classref_project

    project, _derived = build_classref_project(
        tmp_path / "f6cov", descriptor_fixture="descriptor-f6-pair.json"
    )
    package = next((project / "src").iterdir())
    # Baseline: both L2 vendor actions render their own inputs — clean.
    baseline = verify_ui(project, reference=REFERENCE)
    assert baseline.clean, [f"{f.code}: {f.detail}" for f in baseline.findings]
    manifest = json.loads((package / "ui" / "manifest.json").read_bytes())
    block = manifest["extensions"]["plugin-ui-class-reference:layout"]
    page = next(p for p in block["pages"] if p["page_id"] == "device-features")
    stripped_kinds = {"text", "select", "boolean", "numeric"}
    for section in page["sections"]:
        section["children"] = [
            node
            for node in section["children"]
            if not (
                node.get("binding_id") == "auto-band"
                and node.get("kind") in stripped_kinds
            )
        ]
    raw = (json.dumps(manifest, indent=2) + "\n").encode()
    (package / "ui" / "manifest.json").write_bytes(raw)
    envelope = json.loads((package / "presentation.json").read_bytes())
    envelope["manifest"]["sha256"] = hashlib.sha256(raw).hexdigest()
    (package / "presentation.json").write_bytes(
        (json.dumps(envelope, indent=2) + "\n").encode()
    )
    report = verify_ui(project, reference=REFERENCE)
    uncovered = [f for f in report.findings if f.code == "classref_gate_uncovered"]
    assert any(
        "com.veridian-labs.auto-band/1.0.0" in f.detail for f in uncovered
    ), [(f.code, f.detail) for f in report.findings]
