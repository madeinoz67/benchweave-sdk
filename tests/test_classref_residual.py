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


def test_m3_same_urn_custom_without_catalog_row() -> None:
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
    # W8 fold tighten: exact ordered children — the set this arm used to
    # assert cannot see the same node emitted twice, and the staging
    # emission plus the ladder-numeric insert both emitted the numeric
    # pair before the button (measured in a real host render:
    # action-ghost-holdoff_ms twice).
    assert custom["children"] == [
        {"binding_id": "ghost", "kind": "numeric", "field": "holdoff_ms"},
        {"binding_id": "ghost", "kind": "text", "field": "label"},
        {"binding_id": "ghost", "kind": "button"},
    ]
    # The catalogued vendor action stays in the main section, never in the
    # custom one: resolution partitions the two. The exact list carries
    # the same partition (and the no-duplication reading) for the main
    # section too.
    assert all(node.get("binding_id") != "auto-threshold" for node in custom["children"])
    main = sections["device-features-section"]
    assert main["children"] == [
        {"binding_id": "auto-threshold", "kind": "numeric", "field": "margin_ppm"},
        {"binding_id": "auto-threshold", "kind": "numeric", "field": "hysteresis_mv"},
        {"binding_id": "auto-threshold", "kind": "button"},
    ]
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
    # W1 fold tighten: not only the section ids — no authored section's
    # CHILDREN carry a custom member's binding_id. The completion pass
    # used to weld the residual button into the authored sections with
    # its required fields rendered nowhere.
    for section in page["sections"]:
        assert all(
            node.get("binding_id") != "ghost"
            for node in section.get("children", [])
        ), section
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


def _scaffold_residual_project(
    destination: Path,
    *,
    reference: dict[str, Any] | None = None,
    ghost_constraints: dict[str, Any] | None = None,
    extra_actions: dict[str, dict[str, Any]] | None = None,
) -> Path:
    """A real scaffolded plugin carrying the acceptance descriptor and its
    pinned files, with the derived set written — the verify_ui input. The
    fold arms pass a modified reference (an authored device-features
    layout, a diverged expect.controls row), ghost constraints and extra
    residual actions (the G1 sibling); the defaults keep the slice-1
    acceptance shape."""
    from benchweave_sdk.classref import declaration_scaffold
    from benchweave_sdk.scaffold import create_project

    def raw(document: object) -> bytes:
        return (json.dumps(document, indent=2) + "\n").encode()

    descriptor = _acceptance_descriptor()
    if ghost_constraints is not None:
        descriptor["actions"][GHOST_URN]["input_constraints"] = ghost_constraints
    if extra_actions:
        descriptor["actions"].update(extra_actions)
    active_reference = REFERENCE if reference is None else reference
    create_project(destination, "veridian_residual_plugin", with_ui=False)
    package = destination / "src" / "veridian_residual_plugin"
    descriptor_raw = raw(descriptor)
    (package / "descriptor.json").write_bytes(descriptor_raw)
    for pinned in ("vendor-catalog.json", "vectors-f1.json"):
        (package / pinned).write_bytes((FIXTURES / pinned).read_bytes())
    derived = derive_ui(
        descriptor_raw, active_reference, descriptor_path=package / "descriptor.json"
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


# ---------------------------------------------------------------------------
# The 2026-10-22 review fold (rows W1–W11). Each arm names its row and
# was shown RED against the pre-fold mechanism before its fix landed.
# ---------------------------------------------------------------------------


def _derive_ghost(constraints: dict[str, Any]) -> Any:
    """The f1 descriptor plus one residual action carrying the given
    constraints, derived against the served reference."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["actions"][GHOST_URN] = _ghost_action(constraints)
    return derive_ui(
        json.dumps(descriptor).encode(), REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f1.json",
    )


def _refuse_ghost(constraints: dict[str, Any], pattern: str) -> None:
    """The same shape, asserted to refuse with the given code prefix."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["actions"][GHOST_URN] = _ghost_action(constraints)
    with pytest.raises(ValueError, match=pattern):
        derive_ui(
            json.dumps(descriptor).encode(), REFERENCE,
            descriptor_path=FIXTURES / "descriptor-f1.json",
        )


# --- W1: the completion pass, its target, and its ordering -----------------


def test_w1_authored_page_passes_the_real_gate(tmp_path: Path) -> None:
    """W1's ordering defect, proven with a real gate run (refute-b's P14
    control): on an authored device-features page the catalogued vendor
    action's button arrives only through the completion pass, and it used
    to arrive AFTER the ladder-numeric insert — no staging nodes, and the
    action reds classref_gate_uncovered. Completion now runs first (the
    staging pair order is restored), the residual member is skipped
    (never welded into authored sections), and the gate is clean with the
    member disclosed as rendering nothing."""
    from benchweave_sdk.classref_gate import census, verify_ui
    from benchweave_sdk.classref_gate_render import render_pages

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
    reference = {**REFERENCE, "layouts": [*REFERENCE["layouts"], authored]}
    project = _scaffold_residual_project(tmp_path / "authored", reference=reference)
    report = verify_ui(project, reference=reference)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    assert f"custom, renders nothing: {GHOST_URN}" in report.reported_deviations, (
        report.reported_deviations
    )
    html = render_pages(project, ["device-features"])["device-features"]
    seen = census(html)
    assert "ghost" not in seen["buttons"], seen["buttons"]
    assert "action-auto-threshold-margin_ppm" in seen["staged_control_ids"], (
        seen["staged_control_ids"]
    )


def test_w1_button_completion_targets_the_main_derived_section() -> None:
    """W1's targeting defect: after slice 1 the LAST section of a derived
    page may be the custom one, and a catalogued action's completion
    button must never land in it — a catalogued action labelled custom by
    placement. The completion targets the page's main section
    ({page_id}-section) when one exists."""
    from benchweave_sdk.classref import _complete_authored_buttons

    sections = [
        {
            "id": "device-features-section",
            "title": "Device features",
            "surface": "raised",
            "span": 12,
            "children": [],
        },
        {
            "id": "device-features-custom",
            "title": "Custom device actions",
            "surface": "raised",
            "span": 12,
            "children": [],
        },
    ]
    plan = {
        "com.veridian-labs.auto-threshold/1.0.0": {
            "level": "L2",
            "page": "device-features",
            "fields": [],
            "resolution": "catalog",
        },
    }
    _complete_authored_buttons(sections, plan, "device-features")
    assert sections[0]["children"] == [
        {"binding_id": "auto-threshold", "kind": "button"}
    ]
    assert sections[1]["children"] == []


# --- W2: the residual gates apply at every depth ----------------------------


def test_w2_nested_fragment_outside_the_vocabulary_refuses() -> None:
    """W2 (refute-a F1 HIGH, P3 shape): the residual mode's gates used to
    run on the top-level fragment only — a nested fragment under
    `properties` rode verbatim where its catalogued twin refuses the
    keyword through the recursive intersection. The closed vocabulary now
    applies at every depth, naming the nested path."""
    _refuse_ghost(
        {
            "properties": {
                "sweep": {
                    "type": "object",
                    "properties": {
                        "contact": {"type": "string", "format": "email"},
                    },
                }
            }
        },
        r"^classref_constraint_unsupported: action .* field sweep\.contact",
    )


def test_w2_nested_empty_bounds_refuse() -> None:
    """W2 (refute-a F1, P4 shape): a nested fragment under `items` whose
    bounds admit nothing derives no numeric control admitting no value —
    the empty-admittance refusal applies at every depth too."""
    _refuse_ghost(
        {
            "properties": {
                "entries": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 10, "maximum": 5},
                }
            }
        },
        r"^classref_effective_schema_empty: action .* field entries\[\]",
    )


# --- W3: a declared value set under declared bounds -------------------------


def test_w3_enum_narrows_through_the_declared_bounds() -> None:
    """W3 (refute-a F2): a fragment declaring an enum under declared
    bounds used to render every declared value — the select offered what
    the declaration itself excludes (the acceptance rule's own KILL (d)
    shape). The row now offers exactly the values both admit."""
    derived = _derive_ghost(
        {
            "properties": {"mode": {"type": "integer", "enum": [1, 10], "minimum": 5}},
            "required": ["mode"],
        }
    )
    mode = {row["field"]: row for row in derived.control_plan[GHOST_URN]["fields"]}[
        "mode"
    ]
    assert mode["mode"] == "enum"
    assert mode["enum"] == [10]


def test_w3_enum_entirely_outside_the_bounds_refuses() -> None:
    """W3's emptied intersection: every declared value outside the bounds
    refuses under the §8 empty-admittance survivor's code — a select that
    admits nothing never derives."""
    _refuse_ghost(
        {
            "properties": {"mode": {"type": "integer", "enum": [1, 2], "minimum": 5}},
            "required": ["mode"],
        },
        r"^classref_effective_schema_empty: action .* field mode",
    )


def test_w3_const_outside_the_bounds_refuses() -> None:
    """W3's const face: a const is one declared value — outside the
    declared bounds it is a conflict, never a silently dropped bound."""
    _refuse_ghost(
        {"properties": {"mode": {"type": "integer", "const": 1, "minimum": 5}}},
        r"^classref_effective_schema_conflict: action .* field mode",
    )


def test_w3_numeric_bound_on_a_boolean_refuses() -> None:
    """W3's boolean face: numeric bounds on a declared boolean are a
    self-contradiction — the catalogued twin refuses the same shape when
    a constraint's bounds meet a non-numeric catalogue type."""
    _refuse_ghost(
        {"properties": {"invert": {"type": "boolean", "minimum": 5}}},
        r"^classref_effective_schema_conflict: action .* field invert",
    )


# --- W4: a present-but-malformed catalog row is not "no catalog" -----------


@pytest.mark.parametrize("bad_row", [None, "described-but-not-an-object"])
def test_w4_present_non_object_catalog_row_refuses(
    tmp_path: Path, bad_row: object
) -> None:
    """W4 (refute-a F4): `catalog_actions.get(urn)` returned None for a
    present-but-null row, so a malformed catalog entry read as "no catalog
    describes this" — a false `custom` provenance (the pre-split code
    crashed on it with a bare AttributeError). A missing key is the
    residual mode; a present non-object row is a catalog fault and
    refuses typed."""
    import hashlib

    project = _copy_project_files(tmp_path / "malformed")
    catalog = json.loads((project / "vendor-catalog.json").read_bytes())
    catalog["actions"][GHOST_URN] = bad_row
    raw_catalog = (json.dumps(catalog, indent=2) + "\n").encode()
    (project / "vendor-catalog.json").write_bytes(raw_catalog)
    descriptor = json.loads((project / "descriptor-f1.json").read_bytes())
    descriptor["actions"][GHOST_URN] = _ghost_action(
        {
            "properties": {"holdoff_ms": {"type": "integer", "minimum": 0}},
            "required": ["holdoff_ms"],
        }
    )
    for row in descriptor["contracts"]:
        if row["id"].startswith("urn:veridian:vendor-catalog"):
            row["sha256"] = hashlib.sha256(raw_catalog).hexdigest()
    with pytest.raises(ValueError, match="^classref_catalog_row_invalid:"):
        derive_ui(
            json.dumps(descriptor).encode(), REFERENCE,
            descriptor_path=project / "descriptor-f1.json",
        )


# --- W5: an empty enum is an empty admittance -------------------------------


def test_w5_empty_enum_refuses() -> None:
    """W5 (critic 1): a declared `enum: []` used to derive an L2 select
    admitting nothing with a green gate, while the catalogued twin refuses
    the emptied intersection. The empty-admittance check covers enums
    under the same code."""
    _refuse_ghost(
        {
            "properties": {"mode": {"type": "integer", "enum": []}},
            "required": ["mode"],
        },
        r"^classref_effective_schema_empty: action .* field mode",
    )


# --- W6: the disclosure says what rendered; conformance still runs ----------


def test_w6_custom_reason_is_level_aware() -> None:
    """W6 face 1: the declaration's custom_actions reason used to claim
    controls derive from the descriptor's constraints even when the level
    is L0 and nothing derives. The reason now names the state — and the
    L0 member still mints no custom section (nothing renders, nothing is
    labelled custom on the page; that part stays correct)."""
    derived = _derive_ghost(
        {
            "properties": {"label": {"type": "string", "pattern": "^veridian"}},
            "required": ["label"],
        }
    )
    ghost = derived.control_plan[GHOST_URN]
    assert ghost["level"] == "L0"
    custom_rows = derived.declaration["custom_actions"]
    assert [row["action"] for row in custom_rows] == [GHOST_URN]
    assert "no staged control derives" in custom_rows[0]["reason"]
    assert "(L0)" in custom_rows[0]["reason"]
    page = _layout_page(derived, "device-features")
    assert all(
        section["id"] != CUSTOM_SECTION_ID for section in page["sections"]
    )


def test_w6_custom_divergence_reds_the_gate(tmp_path: Path) -> None:
    """W6 face 2: the gate's custom branch used to `continue` ahead of
    the divergence and coverage checks, so a residual member could never
    fail for anything while a catalogued action with the same divergence
    reds classref_gate_undeclared. An intended control the derivation
    does not reach is an undeclared divergence and fails the gate —
    custom exempts the member from needing a catalogue, never from
    conformance."""
    from benchweave_sdk.classref_gate import verify_ui

    reference = {
        **REFERENCE,
        "expect": {
            **REFERENCE["expect"],
            "controls": {**REFERENCE["expect"]["controls"], GHOST_URN: "button"},
        },
    }
    project = _scaffold_residual_project(
        tmp_path / "diverged",
        reference=reference,
        ghost_constraints={
            "properties": {"label": {"type": "string", "pattern": "^veridian"}},
            "required": ["label"],
        },
    )
    package = project / "src" / "veridian_residual_plugin"
    declaration = json.loads((package / "ui" / "class-reference.json").read_bytes())
    declaration["deviations"] = [
        row
        for row in declaration["deviations"]
        if row["expectation_id"] != GHOST_URN
    ]
    (package / "ui" / "class-reference.json").write_bytes(
        (json.dumps(declaration, indent=2) + "\n").encode()
    )
    report = verify_ui(project, reference=reference)
    undeclared = [
        finding
        for finding in report.findings
        if finding.code == "classref_gate_undeclared" and GHOST_URN in finding.detail
    ]
    assert undeclared, [f"{f.code}: {f.detail}" for f in report.findings]


# --- W7: "declares nothing" vs "declares no inputs" ------------------------


def test_w7_declares_nothing_derives_l0_with_disclosure() -> None:
    """W7: a residual action whose input_constraints carries NO properties
    key declared nothing — silence used to become a one-click dispatch
    (L1). It derives L0 with a disclosure naming the absence."""
    derived = _derive_ghost({})
    ghost = derived.control_plan[GHOST_URN]
    assert ghost["level"] == "L0"
    custom_rows = derived.declaration["custom_actions"]
    assert [row["action"] for row in custom_rows] == [GHOST_URN]
    assert "declares no input schema" in custom_rows[0]["reason"]


def test_w7_explicit_empty_properties_declares_no_inputs() -> None:
    """W7's other side of the line: an explicit `properties: {}` declared
    no INPUTS, and the ladder reads it as it did before — a bare button
    (L1). The line is the properties key, never a refusal."""
    derived = _derive_ghost({"properties": {}})
    assert derived.control_plan[GHOST_URN]["level"] == "L1"


# --- W9: string length bounds join the closed vocabulary -------------------


def test_w9_residual_string_lengths_derive() -> None:
    """W9: minLength/maxLength were outside the closed vocabulary, so a
    vendor action declaring a string length bound refused — "never
    refuses" was false for that input class. Both keywords are inside
    the vocabulary now and ride the text row."""
    derived = _derive_ghost(
        {
            "properties": {
                "label": {"type": "string", "minLength": 1, "maxLength": 8},
            },
            "required": ["label"],
        }
    )
    label = {
        row["field"]: row for row in derived.control_plan[GHOST_URN]["fields"]
    }["label"]
    assert label["mode"] == "text"
    assert label["minLength"] == 1
    assert label["maxLength"] == 8


def test_w9_catalogued_length_bounds_intersect(tmp_path: Path) -> None:
    """W9's catalogued side: a constraint's length bounds INTERSECT the
    catalogue's (the tighter end wins) — an accepted keyword the
    intersection silently dropped would be a narrowing the rendered
    control never sees. An inverted intersection admits nothing and
    refuses under the empty-admittance code."""
    import hashlib

    def _project(name: str, min_length: int) -> Any:
        project = _copy_project_files(tmp_path / name)
        catalog = json.loads((project / "vendor-catalog.json").read_bytes())
        catalog["actions"][GHOST_URN] = {
            "description": "Length-bounded text twin.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "maxLength": 10},
                },
                "required": ["name"],
            },
            "side_effect": "none",
        }
        raw_catalog = (json.dumps(catalog, indent=2) + "\n").encode()
        (project / "vendor-catalog.json").write_bytes(raw_catalog)
        descriptor = json.loads((project / "descriptor-f1.json").read_bytes())
        descriptor["actions"][GHOST_URN] = _ghost_action(
            {"properties": {"name": {"type": "string", "minLength": min_length}}}
        )
        for row in descriptor["contracts"]:
            if row["id"].startswith("urn:veridian:vendor-catalog"):
                row["sha256"] = hashlib.sha256(raw_catalog).hexdigest()
        return derive_ui(
            json.dumps(descriptor).encode(), REFERENCE,
            descriptor_path=project / "descriptor-f1.json",
        )

    derived = _project("tighter", 4)
    name = {
        row["field"]: row for row in derived.control_plan[GHOST_URN]["fields"]
    }["name"]
    assert name["mode"] == "text"
    assert name["minLength"] == 4
    assert name["maxLength"] == 10
    with pytest.raises(
        ValueError, match=r"^classref_effective_schema_empty: action .* field name"
    ):
        _project("inverted", 12)


# --- W10: the declaration's custom inventory is read back ------------------


def _tamper_declaration(package: Path, mutate: Any) -> None:
    declaration = json.loads((package / "ui" / "class-reference.json").read_bytes())
    mutate(declaration)
    (package / "ui" / "class-reference.json").write_bytes(
        (json.dumps(declaration, indent=2) + "\n").encode()
    )


def test_w10_ledger_that_omits_a_residual_member_is_reported(
    tmp_path: Path,
) -> None:
    """W10: the declaration's custom inventory was write-only — an
    authored ledger could omit every uncatalogued member and pass. The
    read-back compares the authored custom_actions against the derived
    custom set and REPORTS the mismatch (the REPORTED channel, never a
    refusal)."""
    from benchweave_sdk.classref_gate import verify_ui

    project = _scaffold_residual_project(tmp_path / "omit")
    package = project / "src" / "veridian_residual_plugin"

    def mutate(declaration: dict[str, Any]) -> None:
        declaration["custom_actions"] = []

    _tamper_declaration(package, mutate)
    report = verify_ui(project)
    assert any(
        row.startswith("custom mismatch: ") and GHOST_URN in row
        for row in report.reported_deviations
    ), report.reported_deviations
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]


def test_w10_ledger_forged_custom_row_is_reported(tmp_path: Path) -> None:
    """W10's other direction: a forged row naming an URN no plan carries
    as residual is reported too — the read-back runs both ways (the
    forged row and the omitted member both surface)."""
    from benchweave_sdk.classref_gate import verify_ui

    project = _scaffold_residual_project(tmp_path / "forged")
    package = project / "src" / "veridian_residual_plugin"

    def mutate(declaration: dict[str, Any]) -> None:
        declaration["custom_actions"] = [
            {
                "action": "com.veridian-labs.nope/1.0.0",
                "resolution": "custom",
                "reason": "forged",
            }
        ]

    _tamper_declaration(package, mutate)
    report = verify_ui(project)
    assert any(
        row.startswith("custom mismatch: ") and "nope" in row
        for row in report.reported_deviations
    ), report.reported_deviations
    assert any(
        row.startswith("custom mismatch: ") and GHOST_URN in row
        for row in report.reported_deviations
    ), report.reported_deviations


def test_w10_reference_less_arm_reads_the_ledger_too(tmp_path: Path) -> None:
    """W10's second arm: the read-back runs in the reference-less verify
    arm as well — both arms read the same authored declaration file. A
    scalar scaffold (no class reference, no residual members) carrying an
    authored declaration whose custom_actions names an URN no plan holds
    as residual gets the mismatch reported there too."""
    from benchweave_sdk.classref_gate import verify_ui
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project
    from benchweave_sdk.served import active_version

    project = tmp_path / "scalar"
    create_project(project, "veridian_scalar_plugin", with_ui=True)
    create_ui_resources(project, "veridian_scalar_plugin")
    package = project / "src" / "veridian_scalar_plugin"
    declaration = {
        "contract_version": active_version("plugin-ui-class-reference"),
        "deviations": [],
        "custom_actions": [
            {
                "action": "com.veridian-labs.nope/1.0.0",
                "resolution": "custom",
                "reason": "forged",
            }
        ],
    }
    (package / "ui" / "class-reference.json").write_bytes(
        (json.dumps(declaration, indent=2) + "\n").encode()
    )
    report = verify_ui(project, reference=None)
    assert any(
        row.startswith("custom mismatch: ") and "nope" in row
        for row in report.reported_deviations
    ), report.reported_deviations


# ---------------------------------------------------------------------------
# The 2026-10-22 second fold wave (rows G1–G5, the refute lane's confirmed
# defects on the first fold). Each arm names its row; the RED evidence for
# every arm (and the neutralizations that produced it) is quoted in the
# fold commit's message.
# ---------------------------------------------------------------------------

#: The G1 siblings, the refute lane's two L0 shapes: a residual action
#: that derives L0 because NOTHING it declares is expressible (a
#: pattern-narrowed required string), and one that derives L0 because it
#: declares nothing at all (the W7 shape — no properties key). Both mint
#: no control node BY DESIGN: the disclosure, never a render defect.
SPECTRE_URN = "com.veridian-labs.spectre/1.0.0"
WRAITH_URN = "com.veridian-labs.wraith/1.0.0"


def _spectre_action() -> dict[str, Any]:
    return _ghost_action(
        {
            "properties": {"tag": {"type": "string", "pattern": "^spectre"}},
            "required": ["tag"],
        }
    )


def _wraith_action() -> dict[str, Any]:
    return _ghost_action({})


# --- G1: the coverage discriminator is per ACTION, not per page ------------


def test_g1_l0_residual_siblings_on_a_custom_page_stay_disclosures(
    tmp_path: Path,
) -> None:
    """G1 (HIGH, a regression the first fold introduced): the W6 coverage
    discriminator was per-PAGE — a page carrying one L2 residual action
    mints the custom section, and every L0 residual sibling on that page
    then reded "renders no control at L0" although the fold's own rule
    says an L0 member renders nothing BY DESIGN (and the same fold kept
    custom rows out of the deviation ledger, so no sanctioned pass
    existed either — the trap). The discriminator is per ACTION now: a
    custom member reds only when the DERIVATION minted control nodes for
    THAT action — read from derived.layout_block, never the served
    manifest — and the render lacks them.

    The lane's exact fixture: an L2 custom action that renders, plus BOTH
    L0 shapes — the declares-nothing member (W7) and the
    pattern-narrowed member — on one page. One surface each: a
    renders-nothing-by-design member appears in the REPORTED channel
    only, never simultaneously as a finding and a "renders nothing"
    disclosure (the two-channels-two-stories state W6 exists to remove).
    A member whose MINTED controls are missing keeps its report row (M2:
    never silent) and gains the finding — the channels agree there; the
    eliminated state is the by-design member failing."""
    from benchweave_sdk.classref_gate import verify_ui

    project = _scaffold_residual_project(
        tmp_path / "mixed-level",
        extra_actions={
            SPECTRE_URN: _spectre_action(),
            WRAITH_URN: _wraith_action(),
        },
    )
    report = verify_ui(project)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    # The L2 member rendered its controls: covered, labelled plain custom.
    assert f"custom: {GHOST_URN}" in report.reported_deviations, (
        report.reported_deviations
    )
    # Both L0 siblings rendered nothing BY DESIGN: disclosures only —
    # never findings, on the same page that mints the custom section.
    for urn in (SPECTRE_URN, WRAITH_URN):
        assert (
            f"custom, renders nothing: {urn}" in report.reported_deviations
        ), report.reported_deviations
        assert not any(urn in finding.detail for finding in report.findings), [
            f"{f.code}: {f.detail}" for f in report.findings
        ]


def _drop_custom_section(project: Path) -> None:
    """The G2 overlay shape as a reusable probe: a compose_manifest
    extensions overlay that drops the device-features custom section —
    the derivation minted the controls, the served manifest omits them.
    The envelope is re-pinned (the same motion the gate baseline test
    performs) so the load reaches the GATE, never a digest refusal."""
    import hashlib

    from benchweave_sdk.classref import LAYOUT_EXTENSION_KEY, compose_manifest

    package = next((project / "src").iterdir())
    manifest = json.loads((package / "ui" / "manifest.json").read_bytes())
    block = manifest["extensions"][LAYOUT_EXTENSION_KEY]
    page = next(p for p in block["pages"] if p["page_id"] == "device-features")
    page["sections"] = [
        section for section in page["sections"] if section["id"] != CUSTOM_SECTION_ID
    ]
    composed = compose_manifest(
        manifest, {"extensions": {LAYOUT_EXTENSION_KEY: block}}
    )
    composed_raw = (json.dumps(composed, indent=2) + "\n").encode()
    (package / "ui" / "manifest.json").write_bytes(composed_raw)
    envelope = json.loads((package / "presentation.json").read_bytes())
    envelope["manifest"] = {
        "path": "manifest.json",
        "sha256": hashlib.sha256(composed_raw).hexdigest(),
    }
    (package / "presentation.json").write_bytes(
        (json.dumps(envelope, indent=2) + "\n").encode()
    )


def test_g1_an_authored_deviation_is_the_sanctioned_pass_for_a_red_shape(
    tmp_path: Path,
) -> None:
    """G1's suppression question, answered by arm: the fold kept custom
    rows out of the BIRTH deviation ledger, so the only red shape left —
    a member whose MINTED controls the render lacks — needs an authored
    pass. It has one: a hand-authored deviation row naming the URN (plan
    URNs are inside the declaration vocabulary) downgrades the failure
    to REPORTED. No ledger restoration is needed for any shape."""
    from benchweave_sdk.classref_gate import verify_ui

    project = _scaffold_residual_project(tmp_path / "sanctioned")
    _drop_custom_section(project)
    package = next((project / "src").iterdir())

    def mutate(declaration: dict[str, Any]) -> None:
        declaration["deviations"].append(
            {
                "expectation_id": GHOST_URN,
                "reason": (
                    "overlay drops the custom section; the author renders "
                    "these controls elsewhere by decision"
                ),
            }
        )

    _tamper_declaration(package, mutate)
    report = verify_ui(project)
    assert not any(
        finding.code == "classref_gate_uncovered" and GHOST_URN in finding.detail
        for finding in report.findings
    ), [f"{f.code}: {f.detail}" for f in report.findings]
    # The member stays on the report — M2's never-silent rule holds
    # through the downgrade (the deviation row names it).
    assert GHOST_URN in report.reported_deviations, report.reported_deviations


# --- G2: the red criterion is the DERIVED block, never the served manifest --


def test_g2_overlay_dropping_the_custom_section_reds(tmp_path: Path) -> None:
    """G2 (MEDIUM, false-green direction): the discriminator read the
    SERVED manifest's section ids, so a compose_manifest extensions
    overlay that drops the custom section left the gate clean over a real
    render miss. The derivation's own layout block is the statement of
    what should have rendered: the minted controls are owed wherever the
    served manifest drops them."""
    from benchweave_sdk.classref import LAYOUT_EXTENSION_KEY, compose_manifest
    from benchweave_sdk.classref_gate import verify_ui

    project = _scaffold_residual_project(tmp_path / "dropped")
    package = project / "src" / "veridian_residual_plugin"
    manifest = json.loads((package / "ui" / "manifest.json").read_bytes())
    block = manifest["extensions"][LAYOUT_EXTENSION_KEY]
    page = next(p for p in block["pages"] if p["page_id"] == "device-features")
    page["sections"] = [
        section for section in page["sections"] if section["id"] != CUSTOM_SECTION_ID
    ]
    composed = compose_manifest(
        manifest, {"extensions": {LAYOUT_EXTENSION_KEY: block}}
    )
    composed_raw = (json.dumps(composed, indent=2) + "\n").encode()
    (package / "ui" / "manifest.json").write_bytes(composed_raw)
    # The envelope pins the manifest bytes; an overlay edit re-pins it (the
    # same motion the gate baseline test performs) so the load reaches the
    # GATE, never a pin refusal.
    import hashlib

    envelope = json.loads((package / "presentation.json").read_bytes())
    envelope["manifest"] = {
        "path": "manifest.json",
        "sha256": hashlib.sha256(composed_raw).hexdigest(),
    }
    (package / "presentation.json").write_bytes(
        (json.dumps(envelope, indent=2) + "\n").encode()
    )
    report = verify_ui(project)
    uncovered = [
        finding
        for finding in report.findings
        if finding.code == "classref_gate_uncovered" and GHOST_URN in finding.detail
    ]
    assert uncovered, [f"{f.code}: {f.detail}" for f in report.findings]


def test_g2_authored_section_carrying_the_custom_id_is_no_red(
    tmp_path: Path,
) -> None:
    """G2 (MEDIUM, false-red direction): an authored section merely
    CARRYING the `-custom` id with no controls reded the member — the
    served manifest's id spelled like the minted section was enough. An
    authored page stands as authored (record §11 risk 4): the member
    renders nothing there by design and stays a disclosure."""
    from benchweave_sdk.classref_gate import verify_ui

    authored = {
        "page_id": "device-features",
        "sections": [
            {
                "id": CUSTOM_SECTION_ID,
                "title": "Device features",
                "surface": "raised",
                "span": 12,
                "children": [
                    {"body": "Vendor features are authored by this reference."}
                ],
            }
        ],
    }
    reference = {**REFERENCE, "layouts": [*REFERENCE["layouts"], authored]}
    project = _scaffold_residual_project(
        tmp_path / "authored-custom-id", reference=reference
    )
    report = verify_ui(project, reference=reference)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    assert (
        f"custom, renders nothing: {GHOST_URN}" in report.reported_deviations
    ), report.reported_deviations


# --- G3: declared values intersect their bounds on BOTH paths ---------------


def _catalogued_ghost_derive(
    tmp_path: Path, name: str, enum_values: list[int]
) -> Any:
    """A CATALOGUED vendor-catalog row for the ghost action whose own
    input_schema declares an enum under a bound; the descriptor declares
    `properties: {}` for the action, so any narrowing or refusal can come
    only from the catalogue row the catalogued path consumes — never from
    a residual fragment."""
    import hashlib

    project = _copy_project_files(tmp_path / name)
    catalog = json.loads((project / "vendor-catalog.json").read_bytes())
    catalog["actions"][GHOST_URN] = {
        "description": "Catalogued enum-under-bounds twin.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {"type": "integer", "enum": enum_values, "minimum": 5},
            },
            "required": ["mode"],
        },
        "side_effect": "none",
    }
    raw_catalog = (json.dumps(catalog, indent=2) + "\n").encode()
    (project / "vendor-catalog.json").write_bytes(raw_catalog)
    descriptor = json.loads((project / "descriptor-f1.json").read_bytes())
    descriptor["actions"][GHOST_URN] = _ghost_action({"properties": {}})
    for row in descriptor["contracts"]:
        if row["id"].startswith("urn:veridian:vendor-catalog"):
            row["sha256"] = hashlib.sha256(raw_catalog).hexdigest()
    return derive_ui(
        json.dumps(descriptor).encode(), REFERENCE,
        descriptor_path=project / "descriptor-f1.json",
    )


def test_g3_catalogued_vendor_row_narrows_enum_under_its_own_bounds(
    tmp_path: Path,
) -> None:
    """G3: `_intersect_declared_values` runs where rows are minted, so the
    CATALOGUED path narrows too — a vendor-catalog row whose enum sits
    under its own bound offers exactly the values both admit. A select
    offering a value the bounds exclude is the KILL (d) shape; the
    behaviour is asserted here so the record's §9 claim can state it."""
    derived = _catalogued_ghost_derive(tmp_path, "g3-narrows", [1, 10])
    ghost = derived.control_plan[GHOST_URN]
    assert ghost["resolution"] == "catalog"
    mode = {row["field"]: row for row in ghost["fields"]}["mode"]
    assert mode["mode"] == "enum"
    assert mode["enum"] == [10]


def test_g3_catalogued_vendor_row_enum_outside_bounds_refuses(
    tmp_path: Path,
) -> None:
    """G3's refusal face on the catalogued path: a vendor-catalog row
    whose every enum value falls outside its own bound is a contradictory
    declaration and refuses under the §8 empty-admittance survivor."""
    with pytest.raises(
        ValueError, match=r"^classref_effective_schema_empty: action .* field mode"
    ):
        _catalogued_ghost_derive(tmp_path, "g3-refuses", [1, 2])


# --- G4: ill-typed constraint VALUES refuse typed, never a bare crash --------


@pytest.mark.parametrize(
    ("fragment", "keyword"),
    [
        # The lane's reproduction: `enum` + `minLength: "3"` crashed with a
        # bare TypeError from `len(value) < "3"`.
        ({"type": "string", "enum": ["ab", "cdef"], "minLength": "3"}, "minLength"),
        ({"type": "string", "minLength": -1}, "minLength"),
        ({"type": "string", "maxLength": 2.5}, "maxLength"),
        ({"type": "integer", "minimum": "5"}, "minimum"),
        ({"type": "integer", "maximum": True}, "maximum"),
        ({"type": "integer", "multipleOf": "2"}, "multipleOf"),
        ({"type": "string", "pattern": 7}, "pattern"),
        ({"type": "integer", "enum": "fast"}, "enum"),
        ({"type": 5}, "type"),
    ],
)
def test_g4_ill_typed_constraint_value_refuses_typed(
    fragment: dict[str, Any], keyword: str
) -> None:
    """G4 (LOW-MEDIUM): W9 admitted keywords to the closed vocabulary
    without validating that their VALUES are well-typed — the rider
    value-type check refuses `classref_constraint_unsupported` (the code
    the shape got before W9 admitted the keyword) for every CONTROL
    keyword, not only the two W9 named."""
    _refuse_ghost(
        {"properties": {"mode": fragment}},
        rf"^classref_constraint_unsupported: .* {keyword} must be",
    )


@pytest.mark.parametrize(
    ("catalogue_property", "constraint_fragment", "keyword"),
    [
        # The silent class: an ill-typed length bound rode into the row.
        ({"type": "string", "maxLength": 10}, {"type": "string", "minLength": "3"}, "minLength"),
        # The crash class: an ill-typed numeric bound met the catalogue's
        # bound in the max()/min() intersection arithmetic.
        ({"type": "integer", "minimum": 0}, {"type": "integer", "minimum": "5"}, "minimum"),
    ],
)
def test_g4_catalogued_ill_typed_constraint_value_refuses_typed(
    tmp_path: Path,
    catalogue_property: dict[str, Any],
    constraint_fragment: dict[str, Any],
    keyword: str,
) -> None:
    """G4's catalogued face: the same ill-typed value on a constraint
    fragment intersecting a catalogue row — the intersection used to
    carry the bad value into the row silently (the length class) or
    crash the max()/min() arithmetic the moment the catalogue carried
    the twin bound (the numeric class). The rider check guards both
    sides of every intersection."""
    import hashlib

    project = _copy_project_files(tmp_path / "g4-catalogued")
    catalog = json.loads((project / "vendor-catalog.json").read_bytes())
    catalog["actions"][GHOST_URN] = {
        "description": "Value-typed intersection twin.",
        "input_schema": {
            "type": "object",
            "properties": {"name": catalogue_property},
            "required": ["name"],
        },
        "side_effect": "none",
    }
    raw_catalog = (json.dumps(catalog, indent=2) + "\n").encode()
    (project / "vendor-catalog.json").write_bytes(raw_catalog)
    descriptor = json.loads((project / "descriptor-f1.json").read_bytes())
    descriptor["actions"][GHOST_URN] = _ghost_action(
        {"properties": {"name": constraint_fragment}}
    )
    for row in descriptor["contracts"]:
        if row["id"].startswith("urn:veridian:vendor-catalog"):
            row["sha256"] = hashlib.sha256(raw_catalog).hexdigest()
    with pytest.raises(
        ValueError, match=rf"^classref_constraint_unsupported: .* {keyword} must be"
    ):
        derive_ui(
            json.dumps(descriptor).encode(), REFERENCE,
            descriptor_path=project / "descriptor-f1.json",
        )


# --- G5: a reference-less project has no declaration to read back ----------


def test_g5_reference_less_without_declaration_reports_inventory_unavailable(
    tmp_path: Path,
) -> None:
    """G5 (LOW): the reference-less arm reported custom-inventory
    MISMATCHES against a file no tool writes — a project with no class
    reference has no ui/class-reference.json at all (deferral D2: no
    derive path exists to birth one). The report now says the inventory
    is UNAVAILABLE because no declaration exists; a hand-authored
    declaration (the W10 arm) still gets the real comparison."""
    from benchweave_sdk.classref_gate import verify_ui
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "refless"
    create_project(project, "veridian_refless_plugin", with_ui=False)
    package = project / "src" / "veridian_refless_plugin"
    descriptor = json.loads((package / "descriptor.json").read_bytes())
    descriptor["actions"] = {
        GHOST_URN: _ghost_action(
            {
                "properties": {
                    "holdoff_ms": {"type": "integer", "minimum": 0, "maximum": 5000}
                },
                "required": ["holdoff_ms"],
            }
        )
    }
    (package / "descriptor.json").write_bytes(
        (json.dumps(descriptor, indent=2) + "\n").encode()
    )
    create_ui_resources(project, "veridian_refless_plugin")
    # D2, pinned: no tool writes the declaration on the reference-less path.
    assert not (package / "ui" / "class-reference.json").exists()
    report = verify_ui(project, reference=None)
    assert any(
        row.startswith("custom inventory unavailable") for row in report.reported_deviations
    ), report.reported_deviations
    # The honest state is UNAVAILABLE, never a mismatch blaming a ledger
    # that does not exist.
    assert not any(
        row.startswith("custom mismatch: ") for row in report.reported_deviations
    ), report.reported_deviations
    assert (
        f"custom, renders nothing: {GHOST_URN}" in report.reported_deviations
    ), report.reported_deviations
