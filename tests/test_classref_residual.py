"""Issue #541 slice 1: residual action resolution (design record
``.claude/deep-review/2026-10-22-issue541-classref-composition.md``).

Three-layer action resolution, actions arm. This file pins the split of the
seven former ``classref_unknown_action`` sites into integrity faults (still
refusing, each with its own code) and the recoverable knowledge gap (the
residual member derives, provenance-labelled, never silent).

Arms follow the record's acceptance metrics: M1 (the refusal is gone for the
recoverable case), M2 (nothing degrades silently), M3 (the layers are
distinguishable), M4 (the integrity refusals survive), M5 (RED-sanity — run
manually per the record; the neutralizations are ``cp``-backed, never
``git checkout``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.classref import (
    coverage_plan_without_reference,
    derive_ui,
    find_reference,
)

FIXTURES = Path(__file__).parent / "fixtures" / "classref"
REFERENCE = find_reference("otdp.logic_analyser/1.0.0")

#: A residual action: declared by the descriptor, described by no served
#: OTDP row and no pinned vendor catalog. Invented identity throughout.
GHOST_URN = "com.veridian-labs.ghost/1.0.0"


def _ghost_action(constraints: dict[str, Any] | None = None) -> dict[str, Any]:
    """A descriptor action row for the residual fixture action."""
    return {
        "binding": {"kind": "adapter", "key": "ghost"},
        "input_constraints": constraints or {},
        "timeout_ms": 1000,
        "side_effect": "none",
        "cancellable": True,
        "retry": "never",
    }


def _acceptance_descriptor() -> dict[str, Any]:
    """The slice-1 acceptance descriptor: mostly a class (logic analyser),
    plus one action no served catalog describes (record §7 M1)."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["actions"][GHOST_URN] = _ghost_action(
        {
            "properties": {
                "holdoff_ms": {"type": "integer", "minimum": 0, "maximum": 5000},
                "label": {"type": "string"},
            },
            "required": ["holdoff_ms"],
        }
    )
    return descriptor


def _copy_project_files(destination: Path) -> Path:
    """The f1 descriptor plus its pinned files, copied so a test can tamper
    with the pinned bytes without touching the shared fixtures."""
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("descriptor-f1.json", "vendor-catalog.json", "vectors-f1.json"):
        (destination / name).write_bytes((FIXTURES / name).read_bytes())
    return destination


# ---------------------------------------------------------------------------
# M4 — the integrity refusals survive, each with its own code (record §7.4).
# The four former integrity sites of the ``classref_unknown_action`` split
# (record §1) keep refusing; only the code names change.
# ---------------------------------------------------------------------------


def test_m4_tampered_vendor_catalog_digest_refuses(tmp_path: Path) -> None:
    """A pinned vendor catalog whose bytes do not match its sha256 pin is an
    integrity fault (tampering or corruption) and refuses typed — never the
    old shared ``classref_unknown_action``."""
    project = _copy_project_files(tmp_path / "digest")
    catalog = json.loads((project / "vendor-catalog.json").read_bytes())
    catalog["actions"]["com.veridian-labs.ghost/1.0.0"] = {
        "input_schema": {"type": "object"},
        "side_effect": "none",
    }
    (project / "vendor-catalog.json").write_bytes(
        (json.dumps(catalog, indent=2) + "\n").encode()
    )
    # The pin still names the ORIGINAL digest: the bytes moved under it.
    with pytest.raises(
        ValueError, match="^classref_vendor_catalog_digest_mismatch:"
    ):
        derive_ui(
            (project / "descriptor-f1.json").read_bytes(), REFERENCE,
            descriptor_path=project / "descriptor-f1.json",
        )


def test_m4_unreadable_vendor_catalog_refuses(tmp_path: Path) -> None:
    """A pinned vendor catalog that cannot be read is a platform or project
    fault and refuses with its own code."""
    project = _copy_project_files(tmp_path / "unreadable")
    (project / "vendor-catalog.json").unlink()
    with pytest.raises(ValueError, match="^classref_vendor_catalog_unreadable:"):
        derive_ui(
            (project / "descriptor-f1.json").read_bytes(), REFERENCE,
            descriptor_path=project / "descriptor-f1.json",
        )


def test_m4_missing_profile_catalog_refuses() -> None:
    """A descriptor whose otdp_version has no served profile catalog row is
    a platform fault (incomplete installation) and refuses with its own
    code. The reference-less coverage seam is the public path that reaches
    the catalog resolution without a prior descriptor-schema refusal."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["otdp_version"] = "9.9.9"
    with pytest.raises(ValueError, match="^classref_profile_catalog_unserved:"):
        coverage_plan_without_reference(descriptor, FIXTURES / "descriptor-f1.json")


def test_m4_absent_profile_row_refuses() -> None:
    """A reference whose profile is absent from the served profile catalog
    is a platform fault and refuses with its own code."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["profiles"] = ["otdp.logic_analyser/9.9.9"]
    reference = {**REFERENCE, "profile_id": "otdp.logic_analyser/9.9.9"}
    with pytest.raises(ValueError, match="^classref_profile_absent:"):
        derive_ui(
            json.dumps(descriptor).encode(), reference,
            descriptor_path=FIXTURES / "descriptor-f1.json",
        )


# ---------------------------------------------------------------------------
# M1 — the refusal is gone for the recoverable case (record §7.1).
# ---------------------------------------------------------------------------


def test_m1_residual_descriptor_derives_zero_refusals() -> None:
    """The acceptance descriptor (mostly a class, plus one action no catalog
    describes) derives with zero refusals, and 100% of the descriptor's
    declared actions appear in the control plan with a non-null resolution.
    The denominator is asserted from the descriptor, never a literal."""
    descriptor = _acceptance_descriptor()
    derived = derive_ui(
        json.dumps(descriptor).encode(), REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f1.json",
    )
    declared = set(descriptor["actions"])
    assert declared, "the acceptance descriptor declares actions"
    planned = set(derived.control_plan)
    assert planned == declared
    missing = declared - planned
    assert not missing, f"declared but unplanned: {sorted(missing)}"
    unresolved = sorted(
        urn for urn, row in derived.control_plan.items() if not row.get("resolution")
    )
    assert not unresolved, f"plan rows without resolution: {unresolved}"


def test_m1_residual_row_is_honest_about_its_constraints() -> None:
    """KILL (d) arm: the residual row's field rows match the descriptor's
    declared input_constraints — the generic surface admits exactly what the
    plugin declared, no more."""
    descriptor = _acceptance_descriptor()
    derived = derive_ui(
        json.dumps(descriptor).encode(), REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f1.json",
    )
    ghost = derived.control_plan[GHOST_URN]
    assert ghost["resolution"] == "custom"
    by_field = {row["field"]: row for row in ghost["fields"]}
    holdoff = by_field["holdoff_ms"]
    assert holdoff["mode"] == "numeric"
    assert holdoff["minimum"] == 0
    assert holdoff["maximum"] == 5000
    label = by_field["label"]
    assert label["mode"] == "text"
    # holdoff_ms is required and expressible: the action is L2 (staging).
    assert ghost["level"] == "L2"


# ---------------------------------------------------------------------------
# M3 — the layers are distinguishable (record §7.3). Slice-1 legs: the same
# URN derives "custom" with no catalog row and "catalog" when a served
# catalog describes it. (The "composed" leg is slice 2.)
# ---------------------------------------------------------------------------


def test_m3_same_urn_custom_without_catalog_row(tmp_path: Path) -> None:
    descriptor = _acceptance_descriptor()
    derived = derive_ui(
        json.dumps(descriptor).encode(), REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f1.json",
    )
    assert derived.control_plan[GHOST_URN]["resolution"] == "custom"


def test_m3_same_urn_catalog_when_a_served_catalog_describes_it(
    tmp_path: Path,
) -> None:
    """The same URN, described by a pinned vendor catalog this time, derives
    resolution "catalog" — one URN, two distinct outcomes, the layer decided
    by what describes the action, never by the URN's spelling."""
    import hashlib

    project = _copy_project_files(tmp_path / "pinned")
    catalog = json.loads((project / "vendor-catalog.json").read_bytes())
    catalog["actions"][GHOST_URN] = {
        "description": "Pinned residual twin.",
        "input_schema": {
            "type": "object",
            "properties": {
                "holdoff_ms": {"type": "integer", "minimum": 0, "maximum": 5000},
                "label": {"type": "string"},
            },
            "required": ["holdoff_ms"],
        },
        "side_effect": "none",
    }
    raw_catalog = (json.dumps(catalog, indent=2) + "\n").encode()
    (project / "vendor-catalog.json").write_bytes(raw_catalog)
    descriptor = json.loads((project / "descriptor-f1.json").read_bytes())
    descriptor["actions"][GHOST_URN] = _ghost_action(
        {
            "properties": {
                "holdoff_ms": {"type": "integer", "minimum": 0, "maximum": 5000},
                "label": {"type": "string"},
            },
            "required": ["holdoff_ms"],
        }
    )
    for row in descriptor["contracts"]:
        if row["id"].startswith("urn:veridian:vendor-catalog"):
            row["sha256"] = hashlib.sha256(raw_catalog).hexdigest()
    derived = derive_ui(
        json.dumps(descriptor).encode(), REFERENCE,
        descriptor_path=project / "descriptor-f1.json",
    )
    assert derived.control_plan[GHOST_URN]["resolution"] == "catalog"


def test_m3_reference_less_plan_matches_derive_ui() -> None:
    """The same treatment on the reference-less path: coverage plans cannot
    disagree with derive_ui — the residual member derives, resolution
    "custom", where the old path refused."""
    descriptor = _acceptance_descriptor()
    plan, _actions = coverage_plan_without_reference(
        descriptor, FIXTURES / "descriptor-f1.json"
    )
    assert set(plan) == set(descriptor["actions"])
    assert plan[GHOST_URN]["resolution"] == "custom"


# ---------------------------------------------------------------------------
# The narrowing discipline survives in the no-catalogue-row mode: the closed
# keyword vocabulary and the empty-admittance refusal keep refusing (record
# §8 — unchanged for layer 3).
# ---------------------------------------------------------------------------


def test_residual_mode_refuses_outside_the_closed_vocabulary() -> None:
    """A residual constraint fragment using a keyword outside the closed
    intersection vocabulary refuses classref_constraint_unsupported — no
    catalogue row does not mean no vocabulary."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["actions"][GHOST_URN] = _ghost_action(
        {"properties": {"label": {"type": "string", "format": "email"}}}
    )
    with pytest.raises(ValueError, match="^classref_constraint_unsupported:"):
        derive_ui(
            json.dumps(descriptor).encode(), REFERENCE,
            descriptor_path=FIXTURES / "descriptor-f1.json",
        )


def test_residual_mode_refuses_empty_admittance() -> None:
    """A residual required field whose declared bounds admit nothing refuses
    classref_effective_schema_empty — the generic surface never renders a
    control that admits no value (record §8, unchanged)."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["actions"][GHOST_URN] = _ghost_action(
        {
            "properties": {
                "holdoff_ms": {"type": "integer", "minimum": 10, "maximum": 5},
            },
            "required": ["holdoff_ms"],
        }
    )
    with pytest.raises(ValueError, match="^classref_effective_schema_empty:"):
        derive_ui(
            json.dumps(descriptor).encode(), REFERENCE,
            descriptor_path=FIXTURES / "descriptor-f1.json",
        )


# ---------------------------------------------------------------------------
# The custom section (record §4.2): residual members derive into their own
# expander-minted section on their page, so a custom member is visibly
# custom. Per-control badges need a layout-vocabulary widening (D3) — the
# section is slice 1's visible label.
# ---------------------------------------------------------------------------

CUSTOM_SECTION_ID = "device-features-custom"


def _layout_page(derived: Any, page_id: str) -> dict[str, Any]:
    return next(
        page for page in derived.layout_block["pages"]
        if page["page_id"] == page_id
    )


def test_custom_section_holds_the_residual_controls() -> None:
    """The residual member's controls derive into their own section on the
    device-features page — an id and title the expander mints, the same
    authority that mints {page_id}-section ids — while the catalogued
    vendor action stays in the main derived section."""
    descriptor = _acceptance_descriptor()
    derived = derive_ui(
        json.dumps(descriptor).encode(), REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f1.json",
    )
    page = _layout_page(derived, "device-features")
    sections = {section["id"]: section for section in page["sections"]}
    assert CUSTOM_SECTION_ID in sections, sorted(sections)
    custom = sections[CUSTOM_SECTION_ID]
    assert custom["title"] == "Custom device actions"
    custom_nodes = {
        (node.get("binding_id"), node.get("kind"), node.get("field"))
        for node in custom["children"]
    }
    assert ("ghost", "numeric", "holdoff_ms") in custom_nodes
    assert ("ghost", "text", "label") in custom_nodes
    assert ("ghost", "button", None) in custom_nodes
    # The catalogued vendor action stays in the main section, never in the
    # custom one: resolution partitions the two.
    assert all(node.get("binding_id") != "auto-threshold" for node in custom["children"])
    main = sections["device-features-section"]
    assert any(
        node.get("binding_id") == "auto-threshold" for node in main["children"]
    )
    assert not any(
        node.get("binding_id") == "ghost" for node in main["children"]
    )


def test_no_residuals_no_custom_section() -> None:
    """A derivation with no residual members mints no custom section — the
    section exists exactly when residual members do (nothing degrades
    silently, nothing fabricates a label either)."""
    derived = derive_ui(
        (FIXTURES / "descriptor-f1.json").read_bytes(), REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f1.json",
    )
    page = _layout_page(derived, "device-features")
    assert all(section["id"] != CUSTOM_SECTION_ID for section in page["sections"])


def test_custom_section_never_appends_into_an_authored_page() -> None:
    """Record §11 risk 4: a reference that authors its own device-features
    layout keeps it authored — the derived custom section appends only
    where the page has no authored layout block. The residual member is
    still never silent (plan row, declaration inventory, gate report); it
    just never welds itself onto a page whose layout the reference wrote."""
    descriptor = _acceptance_descriptor()
    authored = {
        "page_id": "device-features",
        "sections": [
            {
                "id": "vendor-features-authored",
                "title": "Device features",
                "surface": "raised",
                "span": 12,
                "children": [
                    {"body": "Vendor features are authored by this reference."}
                ],
            }
        ],
    }
    reference = {
        **REFERENCE,
        "layouts": [*REFERENCE["layouts"], authored],
    }
    derived = derive_ui(
        json.dumps(descriptor).encode(), reference,
        descriptor_path=FIXTURES / "descriptor-f1.json",
    )
    page = _layout_page(derived, "device-features")
    assert [section["id"] for section in page["sections"]] == [
        "vendor-features-authored"
    ]
    # The residual member still derives — into the plan, labelled custom.
    assert derived.control_plan[GHOST_URN]["resolution"] == "custom"


# ---------------------------------------------------------------------------
# M2 — nothing degrades silently (record §7.2). A custom member lands in
# GateReport.reported_deviations labelled "custom" through the existing
# REPORTED channel, every run, and the declaration records the custom
# inventory — non-empty exactly when residuals exist. A custom member is
# never a findings failure: it is a disclosure.
# ---------------------------------------------------------------------------


def test_m2_declaration_inventory_non_empty_exactly_when_residuals_exist() -> None:
    """The birth declaration carries the custom inventory: the residual
    member is named when it exists, and the inventory is empty when no
    residual does — the project's own conformance record states what is
    uncatalogued from birth (record §4.4)."""
    descriptor = _acceptance_descriptor()
    with_residuals = derive_ui(
        json.dumps(descriptor).encode(), REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f1.json",
    )
    inventory = with_residuals.declaration.get("custom_actions")
    assert inventory, "residual members must be inventoried"
    assert [row["action"] for row in inventory] == [GHOST_URN]
    assert all(row["resolution"] == "custom" for row in inventory)
    without_residuals = derive_ui(
        (FIXTURES / "descriptor-f1.json").read_bytes(), REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f1.json",
    )
    assert not without_residuals.declaration.get("custom_actions")


def _scaffold_residual_project(destination: Path) -> Path:
    """A real scaffolded plugin carrying the acceptance descriptor and its
    pinned files, with the derived set written — the verify_ui input."""
    from benchweave_sdk.classref import declaration_scaffold
    from benchweave_sdk.scaffold import create_project

    def raw(document: object) -> bytes:
        return (json.dumps(document, indent=2) + "\n").encode()

    descriptor = _acceptance_descriptor()
    create_project(destination, "veridian_residual_plugin", with_ui=False)
    package = destination / "src" / "veridian_residual_plugin"
    descriptor_raw = raw(descriptor)
    (package / "descriptor.json").write_bytes(descriptor_raw)
    for pinned in ("vendor-catalog.json", "vectors-f1.json"):
        (package / pinned).write_bytes((FIXTURES / pinned).read_bytes())
    derived = derive_ui(
        descriptor_raw, REFERENCE, descriptor_path=package / "descriptor.json"
    )
    ui = package / "ui"
    ui.mkdir(exist_ok=True)
    (ui / "manifest.json").write_bytes(raw(derived.manifest))
    (package / "presentation.json").write_bytes(raw(derived.envelope))
    (package / "binding-catalogue.json").write_bytes(raw(derived.catalogue))
    settings = ui / "settings"
    settings.mkdir(exist_ok=True)
    (settings / "configure.schema.json").write_bytes(raw(derived.settings_schema))
    presets = ui / "presets"
    presets.mkdir(exist_ok=True)
    for slug, scaffold in derived.preset_scaffolds.items():
        (presets / f"{slug}.json").write_bytes(raw(scaffold))
    (ui / "class-reference.json").write_bytes(raw(declaration_scaffold(derived)))
    return destination


def test_m2_gate_reports_custom_members_labelled(tmp_path: Path) -> None:
    """Through the real gate (render, census, assert): every custom member
    lands in reported_deviations labelled "custom" — never silent, and
    never a findings failure. The custom controls render on the custom
    section (KILL d: the rendered surface matches the declared
    constraints), which keeps the gate clean."""
    from benchweave_sdk.classref_gate import verify_ui

    project = _scaffold_residual_project(tmp_path / "residual")
    report = verify_ui(project)
    assert f"custom: {GHOST_URN}" in report.reported_deviations, (
        report.reported_deviations
    )
    assert not any(GHOST_URN in finding.detail for finding in report.findings), [
        f"{f.code}: {f.detail}" for f in report.findings
    ]
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
