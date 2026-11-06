"""L5 input-trio widening (gateway #463 L5; design
2026-10-16-classref-l5-plugin-ui-0-4-0-design.md §4 SDK rows, §9 B2/B3/B7).

The classref derivation emits the §E.1 input trio: a required free string
renders a ``text`` control node, an enum (any length) and a ``const``
render ``select`` nodes (a single-option enum / const renders the
read-only fixed display — the F2 ruling), and a boolean renders a
``boolean`` node. RED-first: committed before the widening.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.classref import (
    LAYOUT_EXTENSION_KEY,
    _field_rows,
    _ladder_level,
    derive_ui,
    find_reference,
)

FIXTURES = Path(__file__).parent / "fixtures" / "classref"
REFERENCE = find_reference("otdp.logic_analyser/1.0.0")
TRIO_URN = "com.veridian-labs.auto-band/1.0.0"


def _derive(name: str, reference: dict[str, Any] | None = None):
    return derive_ui(
        (FIXTURES / name).read_bytes(),
        reference if reference is not None else REFERENCE,
        descriptor_path=FIXTURES / name,
    )


# --- B2/B3: the trio derives L2 with one node per field ---------------------


def test_field_rows_emit_the_trio_modes() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "band_class": {"enum": ["wide", "narrow"]},
            "holdoff_enable": {"type": "boolean"},
            "bounded": {"type": "string", "pattern": "^x$"},
            "count": {"type": "integer", "minimum": 0},
            "fixed": {"const": 1.5},
        },
    }
    modes = {row["field"]: row["mode"] for row in _field_rows("urn:t/1.0.0", "", schema)}
    assert modes == {
        "label": "text",
        "band_class": "enum",
        "holdoff_enable": "boolean",
        "count": "numeric",
        "fixed": "const",
    }  # `bounded` — a pattern-narrowed string — emits no row (RC-L5-3/4)


def test_enum_of_any_length_including_empty_emits_enum_mode() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "empty": {"enum": []},
            "single": {"enum": ["only"]},
            "pinned": {"const": "k1"},
        },
    }
    modes = {row["field"]: row["mode"] for row in _field_rows("urn:t/1.0.0", "", schema)}
    assert modes == {"empty": "enum", "single": "enum", "pinned": "const"}


def test_mode_kind_mapping_carries_the_f2_ruling() -> None:
    """The F2 ruling: a literal const emits a select node — the landed
    contract row and the renderer both say a const renders the fixed
    display."""
    from benchweave_sdk.classref import _MODE_KIND

    assert _MODE_KIND == {
        "numeric": "numeric",
        "text": "text",
        "const": "select",
        "enum": "select",
        "boolean": "boolean",
    }


def test_pattern_narrowed_string_keeps_l0() -> None:
    """A required pattern-narrowed string is inexpressible (RC-L5-3/4):
    no row, so the ladder stays L0. The free string is expressible — L2."""
    patterned: dict[str, Any] = {
        "required": ["format"],
        "properties": {"format": {"type": "string", "pattern": "^[A-Z]{4}$"}},
    }
    assert _ladder_level(patterned, frozenset(), None) == "L0"
    free: dict[str, Any] = {
        "required": ["label"],
        "properties": {"label": {"type": "string"}},
    }
    assert _ladder_level(free, frozenset(), None) == "L2"


def test_f5_derives_l2_and_the_ladder_stays() -> None:
    derived = _derive("descriptor-f5-trio.json")
    plan = derived.control_plan
    row = plan[TRIO_URN]
    assert row["level"] == "L2"
    assert [(f["field"], f["mode"]) for f in row["fields"]] == [
        ("label", "text"),
        ("band_class", "enum"),
        ("holdoff_enable", "boolean"),
    ]
    stays = _derive("descriptor-f1-da.json")
    other = stays.control_plan
    # The stays (design B3). Note the measured mechanism: decode and
    # decode_annotated both ride the decode slot's dataset kind to L4 —
    # the slot decides before the field ladder runs — so the design's
    # "decode stays L0 via line_map/settings objects" is proven on the
    # FIELD LADDER itself (the synthetic-schema arm below), where the
    # objects keep a no-slot action at L0. (trigger L1 is pinned on f3b
    # by test_classref_effective.test_ladder_levels_a10.)
    assert other["otdp.logic_analyser.decode/1.0.0"]["level"] == "L4"
    assert other["otdp.logic_analyser.decode_annotated/1.0.0"]["level"] == "L4"
    assert other["otdp.logic_analyser.arm/1.0.0"]["level"] == "L2"
    assert other["otdp.logic_analyser.configure/1.0.0"]["level"] == "L3"


def test_field_ladder_keeps_object_fields_at_l0() -> None:
    """The RC-4 field-ladder arm: an enum plus object fields keeps a
    no-slot action at L0 even though the enum became expressible."""
    enum_and_objects: dict[str, Any] = {
        "required": ["protocol", "line_map", "settings"],
        "properties": {
            "protocol": {"enum": ["uart", "spi"]},
            "line_map": {"type": "object"},
            "settings": {"type": "object"},
        },
    }
    assert _ladder_level(enum_and_objects, frozenset(), None) == "L0"


def test_f5_layout_emits_exactly_three_trio_nodes() -> None:
    from benchweave_sdk.served import active_version

    derived = _derive("descriptor-f5-trio.json")
    block = derived.manifest["extensions"][LAYOUT_EXTENSION_KEY]
    assert block["contract_version"] == active_version(
        "plugin-ui-class-reference"
    )
    page = next(p for p in block["pages"] if p["page_id"] == "device-features")
    children = page["sections"][0]["children"]
    assert [(n.get("kind"), n.get("field")) for n in children] == [
        ("text", "label"),
        ("select", "band_class"),
        ("boolean", "holdoff_enable"),
        ("button", None),
    ]


# --- B2/B7: the gate passes F5 with the trio censused 1/1/1 -----------------


def test_f5_gate_refuses_with_the_trio_pin(tmp_path: Path) -> None:
    """The staged-gate arm (#589 PR-2 inversion): the f5-trio fixture's
    vendor catalog is pinned under contracts[], so verify-ui REFUSES at
    seam construction — the arm's pre-PR-2 form ("gate passes with trio
    census 1/1/1", zero findings, absent bound attributes in the served
    HTML) asserted a shippable claim that was FALSE on both hosts (the
    gateway's loader refuses the same bytes at activation). The gate's
    census coverage for the trio returns only with the R2 corpus motion
    (vendor pins move out of contracts[], main-side); the arm still
    proves the staged project builds and derives (the helper), and that
    the gate's refusal is the typed one naming the pinned catalog. The
    trio's DERIVATION coverage (nodes, ladder, layout) stays green in
    this module's other arms."""
    from helpers_classref import build_classref_project

    from benchweave_sdk.classref_gate import verify_ui

    project, _derived = build_classref_project(
        tmp_path / "f5", descriptor_fixture="descriptor-f5-trio.json"
    )
    with pytest.raises(
        ValueError,
        match=r"profile_contract_invalid: urn:veridian:vendor-catalog-trio:1.0.0",
    ):
        verify_ui(project)


def test_gate_census_map_carries_the_trio() -> None:
    from benchweave_sdk.classref_gate import _assert_expect

    expectation = {
        "components": {
            "text-input": {"count": 1, "per_page": "device-features"},
            "select": {"count": 1, "per_page": "device-features"},
            "boolean-input": {"count": 1, "per_page": "device-features"},
        },
        "controls": {},
        "forbid": [],
        "inventory": {},
    }
    censused = {
        "device-features": {
            "panels": 1,
            "buttons": [],
            "numerics": 0,
            "mode_banners": 1,
            "lanes_figures": 0,
            "lane_kinds": {},
            "confirms": 0,
            "data_tables": 0,
            "lane_labels": [],
            "text": 1,
            "select": 1,
            "boolean": 1,
        }
    }
    findings, reported = _assert_expect(expectation, censused)
    assert findings == []
    assert reported == []
    censused["device-features"]["select"] = 0
    findings, _reported = _assert_expect(expectation, censused)
    assert [f.code for f in findings] == ["classref_gate_missing"]


def test_coverage_counts_the_trio_as_staging() -> None:
    """The D14 L2 arm, updated to the per-action fold (row 2): the trio
    action is covered by ITS OWN control ids, not the page's summed input
    count — a sibling L2 action's controls standing on the page do not
    cover it."""
    from benchweave_sdk.classref_gate import _coverage_findings

    plan = {
        TRIO_URN: {
            "level": "L2",
            "page": "device-features",
            "fields": [
                {"field": "label", "mode": "text"},
                {"field": "band_class", "mode": "enum"},
                {"field": "holdoff_enable", "mode": "boolean"},
            ],
        }
    }
    declaration: dict[str, Any] = {"deviations": []}
    censused = {
        "device-features": {
            "buttons": ["auto-band", "re-band"],
            "numerics": 0,
            "text": 1,
            "select": 2,
            "boolean": 1,
            "staged_control_ids": [
                "action-auto-band-label",
                "action-auto-band-band_class",
                "action-auto-band-holdoff_enable",
                "action-re-band-stacked",
            ],
        }
    }
    findings, _reported = _coverage_findings(plan, censused, declaration)
    assert findings == []
    # A sibling L2 action's controls still stand (select 1) — the page-summed
    # arm would launder the stripped action; the per-action arm does not.
    sibling_only = {
        "device-features": {
            "buttons": ["auto-band", "re-band"],
            "numerics": 0,
            "text": 0,
            "select": 1,
            "boolean": 0,
            "staged_control_ids": ["action-re-band-stacked"],
        }
    }
    findings, _reported = _coverage_findings(plan, sibling_only, declaration)
    assert [f.code for f in findings] == ["classref_gate_uncovered"]


# --- L5 fold rows 1/3/4 (refute folds) --------------------------------------


def test_classref_docstring_names_the_active_manifest_set() -> None:
    """L5 fold row 1 (sync lane, LOW): the module docstring's manifest-set
    version tracks the active plugin-ui version — prose defers to the
    machine source (it read 0.3.1 past the 0.4.0 bump)."""
    import benchweave_sdk.classref as classref_module
    from benchweave_sdk.served import active_version

    docstring = classref_module.__doc__ or ""
    assert f"plugin-ui {active_version('plugin-ui')} manifest set" in docstring


def test_field_rows_refuse_duplicate_qualified_field_names() -> None:
    """L5 fold row 3 (derivation lane F3's guard path): the dotted-flattening
    collision — a flat property literally named ``a.b`` beside a nested
    ``a``→``b`` — mints two rows under one name and doubles the rendered
    control (the numeric doubling's legal path). The derivation refuses
    instead, naming the colliding field."""
    colliding: dict[str, Any] = {
        "type": "object",
        "properties": {
            "a": {"type": "object", "properties": {"b": {"type": "string"}}},
            "a.b": {"type": "string"},
        },
    }
    with pytest.raises(ValueError, match="^classref_duplicate_field:"):
        _field_rows("urn:t/1.0.0", "", colliding)


def test_derive_refuses_the_flattening_field_collision(tmp_path: Path) -> None:
    """Row 3 end to end: a descriptor whose vendor action carries the
    dotted-flattening collision refuses through the full derivation — today
    it derives and the collision doubles the rendered control silently."""
    import hashlib
    import json

    descriptor = json.loads(
        (FIXTURES / "descriptor-f5-trio.json").read_bytes()
    )
    catalog = {
        "catalog_version": "1.0.0",
        "vendor": "com.veridian-labs",
        "actions": {
            "com.veridian-labs.auto-band/1.0.0": {
                "description": "Colliding flattening fixture.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "a": {
                            "type": "object",
                            "properties": {"b": {"type": "string"}},
                        },
                        "a.b": {"type": "string"},
                    },
                    "required": ["a", "a.b"],
                    "additionalProperties": False,
                    "$id": "urn:veridian:action:auto-band:1.0.0:input",
                },
                "output_schema": {"type": "object"},
                "side_effect": "state_change",
            }
        },
    }
    raw = (json.dumps(catalog, indent=2) + "\n").encode()
    (tmp_path / "vendor-catalog-collide.json").write_bytes(raw)
    for row in descriptor["contracts"]:
        if str(row.get("path")) == "vendor-catalog-trio.json":
            row["path"] = "vendor-catalog-collide.json"
            row["sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="^classref_duplicate_field:"):
        derive_ui(
            json.dumps(descriptor).encode(),
            REFERENCE,
            descriptor_path=tmp_path / "descriptor.json",
        )


def test_boolean_enum_options_arm_refuses_the_pinned_pair(tmp_path: Path) -> None:
    """L5 fold row 4 (#589 PR-2 inversion): the f6-pair fixture's vendor
    catalog is pinned under contracts[], so the render — whose seam
    construction PR-2 made refuse the same bytes the gateway's loader
    refuses at activation — REFUSES typed before any page renders. The
    arm's pre-PR-2 form (the boolean options' JSON form ``true``/
    ``false`` in the served HTML) asserted a servable claim that was
    FALSE on both hosts; the rendered-form check returns only with the
    R2 corpus motion (vendor pins move out of contracts[], main-side).
    The arm still proves the staged project builds and derives, and that
    the refusal names the pinned pair catalog."""
    from helpers_classref import build_classref_project

    from benchweave_sdk.classref_gate_render import render_pages

    project, _derived = build_classref_project(
        tmp_path / "f6opt", descriptor_fixture="descriptor-f6-pair.json"
    )
    with pytest.raises(
        ValueError,
        match=r"profile_contract_invalid: urn:veridian:vendor-catalog-pair:1.0.0",
    ):
        render_pages(project, ["device-features"])
