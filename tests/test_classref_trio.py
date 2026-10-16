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
    derived = _derive("descriptor-f5-trio.json")
    block = derived.manifest["extensions"][LAYOUT_EXTENSION_KEY]
    assert block["contract_version"] == "0.2.0"
    page = next(p for p in block["pages"] if p["page_id"] == "device-features")
    children = page["sections"][0]["children"]
    assert [(n.get("kind"), n.get("field")) for n in children] == [
        ("text", "label"),
        ("select", "band_class"),
        ("boolean", "holdoff_enable"),
        ("button", None),
    ]


# --- B2/B7: the gate passes F5 with the trio censused 1/1/1 -----------------


def test_f5_gate_passes_with_trio_census(tmp_path: Path) -> None:
    from helpers_classref import build_classref_project

    from benchweave_sdk.classref_gate import census, verify_ui

    project, derived = build_classref_project(
        tmp_path / "f5", descriptor_fixture="descriptor-f5-trio.json"
    )
    report = verify_ui(project)
    assert report.findings == (), [
        (f.code, f.detail) for f in report.findings
    ]
    from benchweave_sdk.classref_gate_render import render_pages

    pages = [str(p["id"]) for p in derived.manifest["pages"]]
    rendered = render_pages(project, pages)
    seen = census(rendered["device-features"])
    assert seen["text"] == 1
    assert seen["select"] == 1
    assert seen["boolean"] == 1
    assert seen["numerics"] == 0
    # A02 bound honesty (design R6): the free string carries no declared
    # bound, so the served text field renders the ABSENT attributes.
    html = rendered["device-features"]
    assert "minlength=" not in html
    assert "maxlength=" not in html


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
    from benchweave_sdk.classref_gate import _coverage_findings

    plan = {TRIO_URN: {"level": "L2", "page": "device-features"}}
    declaration: dict[str, Any] = {"deviations": []}
    censused = {
        "device-features": {
            "buttons": ["auto-band"],
            "numerics": 0,
            "text": 1,
            "select": 1,
            "boolean": 1,
        }
    }
    findings, _reported = _coverage_findings(plan, censused, declaration)
    assert findings == []
    empty = {
        "device-features": {
            "buttons": ["auto-band"],
            "numerics": 0,
            "text": 0,
            "select": 0,
            "boolean": 0,
        }
    }
    findings, _reported = _coverage_findings(plan, empty, declaration)
    assert [f.code for f in findings] == ["classref_gate_uncovered"]
