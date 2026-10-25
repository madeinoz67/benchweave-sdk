"""#556 Track B B3: the composed-member walk (design record
``.claude/deep-review/2026-10-25-issue556-track-b-vocabularies.md`` §3 —
the shared mechanism; the 0.5.0 README's normative section).

Layer 2's document ride and shape discrimination: a declaration carrying
``members`` joins the SAME ``descriptor.contracts[]`` path+sha256 pin seam
as composed action classes and vendor catalogs, discriminated by document
shape in the same walk. A key set is not a shape claim — any overlap of
the member/class/catalog key sets is the R2 ambiguity refusal. Conflicts
refuse ``classref_composed_slot_conflict`` (the refuse-never-merge family);
a ``plot.over_slot`` that does not name the member's own slot is a
document referring to itself inconsistently and refuses its own code,
``classref_composed_plot_slot_mismatch``. A pin whose members apply nowhere
is disclosed, never drift: the applied-nowhere row.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.classref import derive_ui, find_reference

FIXTURES = Path(__file__).parent / "fixtures" / "classref"
REFERENCE = find_reference("otdp.logic_analyser/1.0.0")

#: The second digital role the composing members resolve (the LA class's
#: own channels slot is ``digital_input``; a composed member of that role
#: would fight the reference for the same channels).
COMPOSED_ROLE = "digital_output"
MEMBER_PIN = "member-lanes.json"
CLASS_URN = "otdp.action.veridian_staging/1.0.0"
STAGE_URN = "otdp.veridian_staging.ghost_stage/1.0.0"
VENDOR_URN = "com.meridian.m400.burst_mode/1.0.0"


def _raw(document: object) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _channels_member(
    *,
    slot: str = "trigger_lanes",
    where_role: str = COMPOSED_ROLE,
    page: str = "capture",
) -> dict[str, Any]:
    return {
        "slot": slot,
        "kind": "channels",
        "where_role": where_role,
        "page": page,
    }


def _action_member(
    *,
    slot: str = "burst",
    kind: str = "procedure",
    claims: list[str] | None = None,
    page: str = "capture",
    plot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    member: dict[str, Any] = {
        "slot": slot,
        "kind": kind,
        "claims": claims if claims is not None else [VENDOR_URN],
        "page": page,
    }
    if plot is not None:
        member["plot"] = plot
    return member


def _member_document(
    members: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "contract_version": "0.1.0",
        "members": members if members is not None else [_channels_member()],
    }
    # (#556 B4) An applied action-kind member composes a target naming the
    # declaration's vendor profile row; the walk-machinery arms carry the
    # row so their documents stay the production shape (the refusal for a
    # profile-less APPLIED action member lives in the surfaces file's arms).
    claims = sorted(
        {
            str(claim)
            for member in document["members"]
            if member.get("kind") != "channels"
            for claim in member.get("claims", ())
        }
    )
    if claims:
        document["profiles"] = [
            {
                "id": "com.meridian.m400/1.0.0",
                "title": "Meridian M-400 composed profile",
                "channel_roles": ["digital_input"],
                "required_actions": claims,
                "optional_actions": [],
            }
        ]
    document.update(extra)
    return document


def _vendor_action(descriptor: dict[str, Any]) -> None:
    descriptor["actions"][VENDOR_URN] = {
        "binding": {"kind": "adapter", "key": "fixture"},
        "input_constraints": {"properties": {"burst_count": {"type": "integer"}}},
        "timeout_ms": 30000,
        "side_effect": "state_change",
        "cancellable": True,
        "retry": "never",
    }


def _member_descriptor(
    *,
    document: dict[str, Any] | None = None,
    second_role_channels: bool = True,
    declare_vendor_action: bool = False,
    extra_pins: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The f1 descriptor plus the composed-role channels (and optionally the
    vendor action) the members apply through, and the member pin."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    if second_role_channels:
        descriptor["channels"].extend(
            {
                "id": f"q{i}",
                "label": f"Trigger line {i}",
                "role": COMPOSED_ROLE,
                "quantities": ["digital_level"],
                "parameter_names": [],
            }
            for i in range(2)
        )
    if declare_vendor_action:
        _vendor_action(descriptor)
    if document is None:
        document = _member_document()
    descriptor["contracts"].append(
        {
            "id": "urn:veridian:member-declaration:1.0.0",
            "path": MEMBER_PIN,
            "sha256": hashlib.sha256(_raw(document)).hexdigest(),
        }
    )
    if extra_pins:
        descriptor["contracts"].extend(extra_pins)
    return descriptor


def _scratch(
    destination: Path,
    *,
    document: dict[str, Any],
    descriptor: dict[str, Any],
    extra_documents: dict[str, dict[str, Any]] | None = None,
) -> Path:
    """A scratch project: the descriptor, the member pin and the f1 fixture's
    own vendor catalog, all with matching digests."""
    destination.mkdir(parents=True, exist_ok=True)
    (destination / MEMBER_PIN).write_bytes(_raw(document))
    for name, row in (extra_documents or {}).items():
        (destination / name).write_bytes(_raw(row))
    (destination / "vendor-catalog.json").write_bytes(
        (FIXTURES / "vendor-catalog.json").read_bytes()
    )
    descriptor_path = destination / "descriptor.json"
    descriptor_path.write_bytes(_raw(descriptor))
    return descriptor_path


def _derive(descriptor: dict[str, Any], descriptor_path: Path) -> Any:
    return derive_ui(_raw(descriptor), REFERENCE, descriptor_path=descriptor_path)


# ---------------------------------------------------------------------------
# Shape discrimination and the applied set.
# ---------------------------------------------------------------------------


def test_a_member_pin_applies_and_lands_the_applied_set(tmp_path: Path) -> None:
    """A declaration carrying ``members`` is a member declaration: it derives
    green (no refusal), and the applied member lands on the derivation's
    composed-members inventory — the R1 rule, carried over verbatim: a member
    applies when the descriptor declares its claim (a matching channel role
    for the claim-less channels kind)."""
    descriptor = _member_descriptor()
    path = _scratch(tmp_path / "apply", document=_member_document(), descriptor=descriptor)
    derived = _derive(descriptor, path)
    assert derived.composed_members["channels"] == (
        {"slot": "trigger_lanes", "where_role": COMPOSED_ROLE, "page": "capture"},
    )


def test_an_action_member_applies_when_a_claim_is_declared(tmp_path: Path) -> None:
    """The claim-carrying kinds apply through the R1 rule's action half: one
    declared claim applies the member. Since B4 the procedure surface
    derives too, so the claim rides the production shape — a pinned vendor
    catalog row carrying the catalogue side its target names (an uncatalogued
    claim refuses ``classref_unknown_action``, the surfaces file's arm)."""
    document = _member_document(members=[_action_member(kind="procedure")])
    catalog = {
        "catalog_version": "1.0.0",
        "vendor": "com.meridian",
        "actions": {
            VENDOR_URN: {
                "description": "Burst capture mode.",
                "input_schema": {
                    "type": "object",
                    "properties": {"burst_count": {"type": "integer"}},
                    "$id": "urn:meridian:action:burst:1.0.0:input",
                },
                "output_schema": {"type": "object"},
                "side_effect": "state_change",
            },
        },
    }
    descriptor = _member_descriptor(
        document=document,
        second_role_channels=False,
        declare_vendor_action=True,
        extra_pins=[
            {
                "id": "urn:meridian:burst-catalog:1.0.0",
                "path": "burst-catalog.json",
                "sha256": hashlib.sha256(_raw(catalog)).hexdigest(),
            }
        ],
    )
    path = _scratch(
        tmp_path / "action-apply",
        document=document,
        descriptor=descriptor,
        extra_documents={"burst-catalog.json": catalog},
    )
    derived = _derive(descriptor, path)
    assert derived.composed_members["procedures"] == (
        {"slot": "burst", "action": VENDOR_URN, "page": "capture"},
    )
    assert derived.unapplied_member_pins == ()


def test_a_member_pin_whose_members_apply_nowhere_is_disclosed(
    tmp_path: Path,
) -> None:
    """A claim-less channels member whose role matches no declared channel,
    and an action member whose claims name no declared action, apply nowhere:
    digest-verified, schema-valid, conflict-free — a REPORTED row naming the
    declaration, never drift and never a refusal."""
    document = _member_document(
        members=[_channels_member(where_role="rf_input"), _action_member()]
    )
    descriptor = _member_descriptor(
        document=document, second_role_channels=False, declare_vendor_action=False
    )
    path = _scratch(tmp_path / "nowhere", document=document, descriptor=descriptor)
    derived = _derive(descriptor, path)
    assert derived.composed_members == {}
    assert derived.unapplied_member_pins == (MEMBER_PIN,)


# ---------------------------------------------------------------------------
# The refusals (record §3 rule 4; the README's three typed rules).
# ---------------------------------------------------------------------------


def test_schema_invalid_member_declaration_refuses(tmp_path: Path) -> None:
    """A member kind outside the closed set is schema-invalid and refuses
    typed — the same posture as an invalid composed class, never an ignored
    pin."""
    document = _member_document(
        members=[{**_channels_member(), "kind": "waveform_lanes"}]
    )
    descriptor = _member_descriptor(document=document)
    path = _scratch(tmp_path / "invalid", document=document, descriptor=descriptor)
    with pytest.raises(ValueError, match="^classref_invalid_member_declaration:"):
        _derive(descriptor, path)


def test_member_pin_with_catalog_keys_is_ambiguous(tmp_path: Path) -> None:
    """``members`` beside ``actions`` is a key-set overlap — the R2 ambiguity
    refusal, its own question, never a shape claim."""
    document = _member_document(actions={"com.example.any/1.0.0": {}})
    descriptor = _member_descriptor(document=document)
    path = _scratch(tmp_path / "amb-catalog", document=document, descriptor=descriptor)
    with pytest.raises(ValueError, match="^classref_invalid_composed_class:") as excinfo:
        _derive(descriptor, path)
    assert "ambiguous" in str(excinfo.value)


def test_member_pin_with_class_keys_is_ambiguous(tmp_path: Path) -> None:
    """``members`` beside ``urn`` (or ``claims``) is the same overlap."""
    document = _member_document(urn=CLASS_URN, claims=[STAGE_URN])
    descriptor = _member_descriptor(document=document)
    path = _scratch(tmp_path / "amb-class", document=document, descriptor=descriptor)
    with pytest.raises(ValueError, match="^classref_invalid_composed_class:") as excinfo:
        _derive(descriptor, path)
    assert "ambiguous" in str(excinfo.value)


def test_member_slot_colliding_with_a_reference_slot_refuses(tmp_path: Path) -> None:
    """A member slot key that shadows a reference slot refuses — the
    composed slot composes beside the reference, never over it."""
    document = _member_document(members=[_channels_member(slot="capture")])
    descriptor = _member_descriptor(document=document)
    path = _scratch(tmp_path / "slot-ref", document=document, descriptor=descriptor)
    with pytest.raises(ValueError, match="^classref_composed_slot_conflict:") as excinfo:
        _derive(descriptor, path)
    assert "capture" in str(excinfo.value)


def test_member_slot_colliding_with_another_member_refuses(tmp_path: Path) -> None:
    """Two members declaring one slot key refuse — one slot per member."""
    document = _member_document(
        members=[
            _channels_member(),
            _channels_member(where_role="rf_input"),
        ]
    )
    descriptor = _member_descriptor(document=document)
    path = _scratch(tmp_path / "slot-twin", document=document, descriptor=descriptor)
    with pytest.raises(ValueError, match="^classref_composed_slot_conflict:") as excinfo:
        _derive(descriptor, path)
    assert "trigger_lanes" in str(excinfo.value)


def test_member_claim_colliding_with_a_reference_slot_action_refuses(
    tmp_path: Path,
) -> None:
    """A member claiming an URN a reference slot already binds refuses —
    the reference's placement is not the member's to compose."""
    document = _member_document(
        members=[_action_member(claims=["otdp.logic_analyser.arm/1.0.0"])]
    )
    descriptor = _member_descriptor(
        document=document, second_role_channels=False, declare_vendor_action=True
    )
    path = _scratch(tmp_path / "claim-ref", document=document, descriptor=descriptor)
    with pytest.raises(ValueError, match="^classref_composed_slot_conflict:") as excinfo:
        _derive(descriptor, path)
    assert "otdp.logic_analyser.arm/1.0.0" in str(excinfo.value)


def test_member_claim_colliding_with_another_member_refuses(tmp_path: Path) -> None:
    """Two members claiming one URN refuse — the claim names one member."""
    document = _member_document(
        members=[
            _action_member(slot="burst"),
            _action_member(slot="burst_two", kind="procedure"),
        ]
    )
    descriptor = _member_descriptor(
        document=document, second_role_channels=False, declare_vendor_action=True
    )
    path = _scratch(tmp_path / "claim-twin", document=document, descriptor=descriptor)
    with pytest.raises(ValueError, match="^classref_composed_slot_conflict:") as excinfo:
        _derive(descriptor, path)
    assert VENDOR_URN in str(excinfo.value)


def test_member_claim_colliding_with_a_composed_class_claim_refuses(
    tmp_path: Path,
) -> None:
    """A member claiming an URN a composed action class claims refuses —
    the class owns the catalogue side, the member the placement; one claim,
    one owner."""
    composed = {
        "contract_version": "0.1.0",
        "urn": CLASS_URN,
        "title": "Veridian staging",
        "claims": [STAGE_URN, VENDOR_URN],
        "input_schema": json.loads(
            (FIXTURES / "composed-staging.json").read_bytes()
        )["input_schema"],
        "side_effect": "state_change",
    }
    descriptor = _member_descriptor(
        document=_member_document(members=[_action_member()]),
        second_role_channels=False,
        declare_vendor_action=True,
        extra_pins=[
            {
                "id": "urn:veridian:composed-staging:1.0.0",
                "path": "composed-staging.json",
                "sha256": hashlib.sha256(_raw(composed)).hexdigest(),
            }
        ],
    )
    descriptor["actions"][STAGE_URN] = {
        "binding": {"kind": "adapter", "key": "fixture"},
        "input_constraints": {"properties": {"stage_level": {"type": "number"}}},
        "timeout_ms": 1000,
        "side_effect": "state_change",
        "cancellable": True,
        "retry": "never",
    }
    path = _scratch(
        tmp_path / "claim-class",
        document=_member_document(members=[_action_member()]),
        descriptor=descriptor,
        extra_documents={"composed-staging.json": composed},
    )
    with pytest.raises(ValueError, match="^classref_composed_slot_conflict:") as excinfo:
        _derive(descriptor, path)
    assert VENDOR_URN in str(excinfo.value)


def test_member_page_naming_no_existing_page_refuses(tmp_path: Path) -> None:
    """``page`` must name a page the composed reference declares (README
    rule 1) — a page that does not exist refuses the shared conflict code."""
    document = _member_document(members=[_channels_member(page="no_such_page")])
    descriptor = _member_descriptor(document=document)
    path = _scratch(tmp_path / "bad-page", document=document, descriptor=descriptor)
    with pytest.raises(ValueError, match="^classref_composed_slot_conflict:") as excinfo:
        _derive(descriptor, path)
    assert "no_such_page" in str(excinfo.value)


def test_member_plot_over_slot_mismatch_refuses(tmp_path: Path) -> None:
    """``plot.over_slot`` must equal the member's own slot (README rule 2,
    the schema's named cannot-catch): a mismatch is the document referring
    to itself inconsistently and refuses its own code."""
    document = _member_document(
        members=[
            _action_member(
                kind="dataset",
                plot={"kind": "time_series", "over_slot": "capture", "series": "numeric_variables"},
            )
        ]
    )
    descriptor = _member_descriptor(
        document=document, second_role_channels=False, declare_vendor_action=True
    )
    path = _scratch(tmp_path / "over-slot", document=document, descriptor=descriptor)
    with pytest.raises(
        ValueError, match="^classref_composed_plot_slot_mismatch:"
    ) as excinfo:
        _derive(descriptor, path)
    assert "burst" in str(excinfo.value)
