"""D13 effective-schema intersection + D14 ladder tests (A9/A10/A12)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchweave_sdk.classref import derive_ui, find_reference

FIXTURES = Path(__file__).parent / "fixtures" / "classref"
REFERENCE = find_reference("otdp.logic_analyser/1.0.0")


def _derive(name: str):
    return derive_ui((FIXTURES / name).read_bytes(), REFERENCE, descriptor_path=FIXTURES / name)


def _controls(derived) -> dict:
    return derived.control_plan


def test_f3a_const_renders_read_only_a9() -> None:
    derived = _derive("descriptor-f3a.json")
    controls = _controls(derived)
    configure = controls["otdp.logic_analyser.configure/1.0.0"]
    # const threshold_v: read-only fixed display, never an editable offer.
    {row["field"]: row for row in configure["fields"]}
    threshold = next(
        row for row in configure["fields"] if row["field"].endswith("threshold_v")
    )
    assert threshold["mode"] == "const"
    assert threshold["const"] == 1.5
    # No optional actions declared: no trigger button, no decoder lanes.
    assert "otdp.logic_analyser.trigger/1.0.0" not in controls
    plot = derived.manifest["pages"][0]["plots"][0]
    assert plot["decoder_lanes"] == []


def test_f3b_bounds_equal_constraint_bytes_a9() -> None:
    derived = _derive("descriptor-f3b.json")
    controls = _controls(derived)
    configure = controls["otdp.logic_analyser.configure/1.0.0"]
    threshold = next(
        row for row in configure["fields"] if row["field"].endswith("threshold_v")
    )
    assert threshold["minimum"] == -0.5
    assert threshold["maximum"] == 5.0
    rate = next(
        row for row in configure["fields"] if row["field"] == "sample_rate_hz"
    )
    assert rate["minimum"] == 1000
    assert rate["maximum"] == 100000000
    # trigger declared: its button derives 1/1.
    trigger = controls["otdp.logic_analyser.trigger/1.0.0"]
    assert trigger["level"] == "L1"
    # 34 channels: one partial group D33-D34.
    plot = derived.manifest["pages"][0]["plots"][0]
    labels = [g["label"] for g in plot["lane_groups"]]
    assert labels[-1] == "D33-D34"
    # 4 full groups (floor(34/8)) + the one partial group D33-D34.
    assert len(plot["lane_groups"]) == 5


def test_unsupported_constraint_keyword_refused() -> None:
    descriptor = json.loads((FIXTURES / "descriptor-f3b.json").read_bytes())
    descriptor["actions"]["otdp.logic_analyser.arm/1.0.0"]["input_constraints"] = {
        "properties": {"max_duration_ms": {"minLength": 2}}
    }
    with pytest.raises(ValueError, match="^classref_constraint_unsupported:"):
        derive_ui(
            json.dumps(descriptor).encode(), REFERENCE,
            descriptor_path=FIXTURES / "descriptor-f3b.json",
        )


def test_type_family_conflict_refused() -> None:
    descriptor = json.loads((FIXTURES / "descriptor-f3b.json").read_bytes())
    descriptor["actions"]["otdp.logic_analyser.arm/1.0.0"]["input_constraints"] = {
        "properties": {"max_duration_ms": {"type": "string"}}
    }
    with pytest.raises(ValueError, match="^classref_effective_schema_conflict:"):
        derive_ui(
            json.dumps(descriptor).encode(), REFERENCE,
            descriptor_path=FIXTURES / "descriptor-f3b.json",
        )


def test_empty_admittance_refused() -> None:
    descriptor = json.loads((FIXTURES / "descriptor-f3b.json").read_bytes())
    descriptor["actions"]["otdp.logic_analyser.arm/1.0.0"]["input_constraints"] = {
        "properties": {"max_duration_ms": {"minimum": 10, "maximum": 5}}
    }
    with pytest.raises(ValueError, match="^classref_effective_schema_empty:"):
        derive_ui(
            json.dumps(descriptor).encode(), REFERENCE,
            descriptor_path=FIXTURES / "descriptor-f3b.json",
        )


def test_ladder_levels_a10() -> None:
    derived = _derive("descriptor-f3b.json")
    controls = _controls(derived)
    assert controls["otdp.logic_analyser.arm/1.0.0"]["level"] == "L2"
    assert controls["otdp.logic_analyser.abort/1.0.0"]["level"] == "L1"
    assert controls["otdp.logic_analyser.fetch/1.0.0"]["level"] == "L4"
    assert controls["otdp.logic_analyser.trigger/1.0.0"]["level"] == "L1"
    assert controls["otdp.logic_analyser.configure/1.0.0"]["level"] == "L3"
    assert controls["otdp.logic_analyser.decode/1.0.0"]["level"] == "L4"
    vendor = controls["com.veridian-labs.auto-threshold/1.0.0"]
    assert vendor["level"] == "L2"
    assert vendor["page"] == "device-features"
    # F3b coverage: 7/7 (5 rendered + 2 declared configure-preset / decode-enum).
    declared = {urn for urn, row in controls.items() if row["declared_deviation"]}
    assert declared == {
        "otdp.logic_analyser.configure/1.0.0",
        "otdp.logic_analyser.decode/1.0.0",
    }


def test_preset_scaffold_refused_by_check_preset_a12() -> None:
    from benchweave_sdk.presentation import validate_preset

    derived = _derive("descriptor-f1.json")
    scaffold = derived.preset_scaffolds["configure"]
    # Synthetic provenance; zero commissionable values.
    assert scaffold["provenance"]["evidence"] == "synthetic"
    assert scaffold["settings"] == {}
    report = validate_preset(
        json.dumps(scaffold).encode(),
        descriptor_raw=(FIXTURES / "descriptor-f1.json").read_bytes(),
        settings_schema_raw=json.dumps(derived.settings_schema).encode(),
        firmware=None,
        action_id="otdp.logic_analyser.configure/1.0.0",
    )
    assert not report.valid


def test_multi_profile_slot_conflict_refused() -> None:
    reference2 = json.loads(json.dumps(REFERENCE))
    reference2["profile_id"] = "otdp.dmm/1.0.0"
    reference2["slots"] = {"arm2": REFERENCE["slots"]["arm"]}
    reference2["pages"] = [
        {"id": "dmm-control", "title": "DMM control", "kind": "configuration",
         "binding_slots": ["arm2"]},
    ]
    with pytest.raises(ValueError, match="^classref_profile_slot_conflict:"):
        derive_ui(
            (FIXTURES / "descriptor-f1.json").read_bytes(), [REFERENCE, reference2],
            descriptor_path=FIXTURES / "descriptor-f1.json",
        )


def test_decode_annotated_overlay_derives_lanes_rc4() -> None:
    """RC-4's named test: with the descriptor declaring decode_annotated and
    pinning decoder documents, decoder lanes derive (the annotation form)
    and the action's coverage rides the rendered annotation surface (L4 on
    the capture page) instead of an unofferable vendor-lane control."""
    derived = _derive("descriptor-f1-da.json")
    plot = derived.manifest["pages"][0]["plots"][0]
    assert len(plot["decoder_lanes"]) == 1
    lane = plot["decoder_lanes"][0]
    assert lane["decoder"] == "uart"
    # The other-action rule: the lanes bind the decode dataset binding on
    # the capture page; decode_annotated's coverage rides that rendered
    # annotation surface.
    assert lane["binding_id"] == "decode"
    row = derived.control_plan["otdp.logic_analyser.decode_annotated/1.0.0"]
    assert row["level"] == "L4"
    assert row["page"] == "capture"
    assert not row["declared_deviation"]


def test_h1_looser_bound_cannot_widen_past_catalogue() -> None:
    """H1 (refute lane 1): the intersection must INTERSECT, not replace —
    a looser descriptor bound leaves the catalogue bound intact; the
    control must never offer a value the catalogue refuses."""
    descriptor = json.loads((FIXTURES / "descriptor-f3b.json").read_bytes())
    descriptor["actions"]["otdp.logic_analyser.configure/1.0.0"]["input_constraints"] = {
        "type": "object",
        "properties": {
            # Catalogue sample_count is minimum 1, maximum 1000000.
            "sample_count": {"type": "integer", "minimum": 10, "maximum": 5000000}
        },
    }
    derived = derive_ui(
        json.dumps(descriptor).encode(), REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f3b.json",
    )
    row = next(
        field
        for field in derived.control_plan["otdp.logic_analyser.configure/1.0.0"]["fields"]
        if field["field"] == "sample_count"
    )
    assert row["minimum"] == 10, "the tighter low end still applies"
    assert row["maximum"] == 1000000, "the catalogue ceiling cannot widen"


def test_h1_const_outside_catalogue_enum_refuses() -> None:
    """H1: a const outside the catalogue's enum is a CONFLICT, not a
    replace that pops the enum."""
    descriptor = json.loads((FIXTURES / "descriptor-f3b.json").read_bytes())
    descriptor["actions"]["otdp.logic_analyser.arm/1.0.0"]["input_constraints"] = {
        "properties": {"max_duration_ms": {"const": 99}}
    }
    # max_duration_ms is integer-bounded, not an enum: pin the conflict arm
    # on an enum-bearing field instead — decode's protocol enum via a const.
    descriptor["actions"]["otdp.logic_analyser.decode/1.0.0"]["input_constraints"] = {
        "properties": {"protocol": {"const": "can"}}
    }
    with pytest.raises(ValueError, match="^classref_effective_schema_conflict:"):
        derive_ui(
            json.dumps(descriptor).encode(), REFERENCE,
            descriptor_path=FIXTURES / "descriptor-f3b.json",
        )


def test_m6_exclusive_boundary_admittance_is_empty() -> None:
    """M6: minimum == exclusiveMaximum (and exclusiveMinimum == maximum)
    admit nothing — the span test alone misses both boundaries."""
    for fragment in (
        {"properties": {"max_duration_ms": {"minimum": 5, "exclusiveMaximum": 5}}},
        {"properties": {"max_duration_ms": {"exclusiveMinimum": 5, "maximum": 5}}},
    ):
        descriptor = json.loads((FIXTURES / "descriptor-f3b.json").read_bytes())
        descriptor["actions"]["otdp.logic_analyser.arm/1.0.0"]["input_constraints"] = fragment
        with pytest.raises(ValueError, match="^classref_effective_schema_empty:"):
            derive_ui(
                json.dumps(descriptor).encode(), REFERENCE,
                descriptor_path=FIXTURES / "descriptor-f3b.json",
            )


def test_m6_exclusive_bounds_carry_on_control_rows() -> None:
    """M6: the control rows carry the exclusive flags the render needs."""
    descriptor = json.loads((FIXTURES / "descriptor-f3b.json").read_bytes())
    descriptor["actions"]["otdp.logic_analyser.arm/1.0.0"]["input_constraints"] = {
        "properties": {"max_duration_ms": {"exclusiveMinimum": 0, "maximum": 60000}}
    }
    derived = derive_ui(
        json.dumps(descriptor).encode(), REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f3b.json",
    )
    row = next(
        field
        for field in derived.control_plan["otdp.logic_analyser.arm/1.0.0"]["fields"]
        if field["field"] == "max_duration_ms"
    )
    assert row["exclusiveMinimum"] is True
    assert row["minimum"] == 0
    assert row["maximum"] == 60000
