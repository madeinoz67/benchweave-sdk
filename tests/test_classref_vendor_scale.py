"""Issue #560: a device with many real vendor operations derives and verifies.

The expander emits one node per control into the derived device-features
section — one numeric node per host-supplied field, one button per action —
so a device whose vendor surface is larger than the family layout schema's
per-section children bound is refused by the expander's own internal
consistency arm (H2) with ``classref_layout_invalid``. A real instrument can
legitimately carry dozens of vendor operations; the derivation must not cap
them.

RED-first: committed before the corpus motion. Every assertion names the
ACTIVE vendored family version's behaviour, never a version literal, so the
suite REDs under the capped corpus and GREENs under the uncapped one.
Sizes 8 and 40 both ride every arm — a raised-but-finite bound cannot pass
(8 vendor operations derive 24 children, 40 derive 120, and any finite
section bound admits one shape and refuses the other).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.classref import (
    LAYOUT_EXTENSION_KEY,
    declaration_scaffold,
    derive_ui,
    find_reference,
    layout_schema,
)
from benchweave_sdk.classref_gate import verify_ui
from benchweave_sdk.presentation import validate_presentation
from benchweave_sdk.scaffold import create_project
from benchweave_sdk.served import active_version

FIXTURES = Path(__file__).parent / "fixtures" / "classref"
REFERENCE = find_reference("otdp.logic_analyser/1.0.0")

#: The custom section uncatalogued vendor actions derive into (#541 layer 3):
#: its id and title are the expander's minted vocabulary, corpus-pinned.
_CUSTOM_SECTION_ID = "device-features-custom"


def _raw(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _vendor_descriptor(vendor_ops: int) -> bytes:
    """descriptor-f1 plus N synthetic uncatalogued vendor operations, each
    carrying two host-supplied integer fields (invented names, Veridian
    family) — the plan row per operation is L2 with two numeric fields, so
    the derived custom section owns three children per operation."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    for index in range(vendor_ops):
        descriptor["actions"][f"com.veridian-labs.vendor-op-{index:02d}/1.0.0"] = {
            "binding": {"kind": "adapter", "key": "fixture"},
            "input_constraints": {
                "type": "object",
                "properties": {
                    f"threshold_{index}": {
                        "type": "integer", "minimum": -100, "maximum": 100,
                    },
                    f"window_{index}": {
                        "type": "integer", "minimum": 1, "maximum": 5000,
                    },
                },
                "required": [f"threshold_{index}", f"window_{index}"],
            },
            "timeout_ms": 30000,
            "side_effect": "state_change",
            "cancellable": True,
            "retry": "never",
        }
    return _raw(descriptor)


def _derive(vendor_ops: int):
    if REFERENCE is None:
        pytest.fail("no vendored reference for otdp.logic_analyser/1.0.0")
    return derive_ui(
        _vendor_descriptor(vendor_ops),
        REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f1.json",
    )


def _custom_section(block: dict[str, Any]) -> dict[str, Any]:
    for page in block["pages"]:
        for section in page["sections"]:
            if section.get("id") == _CUSTOM_SECTION_ID:
                return section
    pytest.fail(f"no {_CUSTOM_SECTION_ID!r} section in the derived block")


@pytest.mark.parametrize("vendor_ops", [8, 40])
def test_many_vendor_operations_derive_and_validate(vendor_ops: int) -> None:
    """The acceptance shape: derive succeeds, every operation's controls are
    present in the derived block, the emitted child count equals the
    expected control count, and the canonical validator accepts the written
    manifest. Under the capped corpus this REDs at the derive call with the
    expander's own refusal."""
    derived = _derive(vendor_ops)
    block = derived.manifest["extensions"][LAYOUT_EXTENSION_KEY]
    assert block["contract_version"] == active_version(
        "plugin-ui-class-reference"
    )
    section = _custom_section(block)
    kinds = [
        (node.get("binding_id"), node["kind"], node.get("field"))
        for node in section["children"]
    ]
    # One numeric node per host-supplied field plus one button per action,
    # grouped per operation in sorted URN order: the exact expected control
    # set, so a silently dropped or duplicated control fails by name.
    expected = [
        child
        for index in range(vendor_ops)
        for child in (
            (f"vendor-op-{index:02d}", "numeric", f"threshold_{index}"),
            (f"vendor-op-{index:02d}", "numeric", f"window_{index}"),
            (f"vendor-op-{index:02d}", "button", None),
        )
    ]
    assert kinds == expected
    assert len(section["children"]) == 3 * vendor_ops
    report = validate_presentation(
        _raw(derived.envelope),
        descriptor_raw=_vendor_descriptor(vendor_ops),
        resources={
            "manifest.json": _raw(derived.manifest),
            "settings/configure.schema.json": _raw(derived.settings_schema),
            **{
                f"presets/{slug}.json": _raw(scaffold)
                for slug, scaffold in derived.preset_scaffolds.items()
            },
        },
        binding_catalogue=derived.catalogue,
    )
    assert report.valid, [(f.code, f.path, f.message) for f in report.findings]


@pytest.mark.parametrize("vendor_ops", [8, 40])
def test_many_vendor_operations_pass_the_rendered_gate(
    vendor_ops: int, tmp_path: Path
) -> None:
    """The gate path (verify-ui): a scaffolded project carrying the derived
    documents verifies with zero findings — the written manifest's layout
    block re-validates against the family schema (H2), renders, and censuses
    clean, so a device with many vendor operations is shippable, not merely
    derivable."""
    if REFERENCE is None:
        pytest.fail("no vendored reference for otdp.logic_analyser/1.0.0")
    project = tmp_path / "project"
    create_project(project, "veridian_classref_plugin", with_ui=False)
    package = project / "src" / "veridian_classref_plugin"
    descriptor_raw = _vendor_descriptor(vendor_ops)
    (package / "descriptor.json").write_bytes(descriptor_raw)
    for pinned in ("vendor-catalog.json", "vectors-f1.json"):
        (package / pinned).write_bytes((FIXTURES / pinned).read_bytes())
    derived = derive_ui(
        descriptor_raw, REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f1.json",
    )
    ui = package / "ui"
    ui.mkdir(exist_ok=True)
    (ui / "manifest.json").write_bytes(_raw(derived.manifest))
    (package / "presentation.json").write_bytes(_raw(derived.envelope))
    (package / "binding-catalogue.json").write_bytes(_raw(derived.catalogue))
    settings = ui / "settings"
    settings.mkdir(exist_ok=True)
    for slug, schema in derived.settings_schemas.items():
        (settings / f"{slug}.schema.json").write_bytes(_raw(schema))
    presets = ui / "presets"
    presets.mkdir(exist_ok=True)
    for slug, scaffold in derived.preset_scaffolds.items():
        (presets / f"{slug}.json").write_bytes(_raw(scaffold))
    (ui / "class-reference.json").write_bytes(_raw(declaration_scaffold(derived)))
    report = verify_ui(project, reference=REFERENCE)
    assert not report.findings, list(report.findings)


def _children_schemas(node: Any) -> list[dict[str, Any]]:
    """Every array schema reachable under a ``children`` key in ``$defs``."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "children" and isinstance(value, dict):
                found.append(value)
            found.extend(_children_schemas(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_children_schemas(item))
    return found


def test_active_layout_schema_places_no_bound_on_children() -> None:
    """The structural witness: no ``children`` array in the ACTIVE vendored
    layout schema's ``$defs`` carries ``maxItems`` — the cap is gone from
    the corpus, not merely raised above today's fixtures. Reading through
    ``layout_schema()`` pins the same document the expander's H2 arm and the
    gate validate against, so the witness cannot diverge from the served
    authority. The at-least-one guard keeps the walk honest: a schema that
    renames ``children`` fails loudly instead of passing vacuously.

    What this does NOT catch: nothing here exercises the renderer or the
    served page with an unbounded section — a renderer that degrades on a
    120-child section still passes this witness; the rendered-gate arm above
    carries that half. It also does not bound ``pages`` or ``sections``
    arrays, whose own maxItems rows are separate corpus decisions.
    """
    schema = layout_schema()
    children = _children_schemas(schema.get("$defs", {}))
    assert children, "no children arrays in the active layout schema $defs"
    bounded = [
        definition for definition in children if "maxItems" in definition
    ]
    assert not bounded, (
        "the active layout schema bounds children arrays: "
        f"{[definition['maxItems'] for definition in bounded]}"
    )
