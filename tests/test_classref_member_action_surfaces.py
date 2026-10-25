"""#556 Track B B4: the action-kind member injections — V1 procedures and
V6 settings idioms (design record §4 V1 and V6; ``.claude/deep-review/
2026-10-25-issue556-track-b-vocabularies.md``).

The injection seam's action half: a member of kind ``procedure`` or
``configuration`` injects the reference slot branch's own closed fields
into the merged reference, and the EXISTING derivation arms — the
procedure loop, the configuration arm, ``_complete_authored_buttons``,
``_build_layout`` — run unchanged on the injected rows. No new component,
no new page, no new node kind. The target composes with the vendor
profile id the declaration supplies (the seam, §0.2 — B4 motion 1 wired
it into the production check-ui path), so the canonical validator admits
the vendor action a served profile row never lists.

V1's REPORTED surface is the applied-nowhere family alone (§4 V1): a
declared procedure member always derives at least its control, so no
derives-nothing row exists for it and none is invented here.
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

#: Invented vendor identity throughout (CLAUDE.md §4).
VENDOR_PROFILE_ID = "com.meridian.m400/1.0.0"
SWEEP_URN = "com.meridian.m400.sweep/1.0.0"
SWEEP_SCHEMA_ID = "urn:meridian:action:sweep:1.0.0:input"

MEMBER_PIN = "member-actions.json"
CATALOG_PIN = "meridian-actions.json"


def _raw(document: object) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _vendor_profile_row(
    actions: list[str], *, profile_id: str = VENDOR_PROFILE_ID
) -> dict[str, Any]:
    """The device-profile-catalog's own row shape, verbatim field set."""
    return {
        "id": profile_id,
        "title": "Meridian M-400 composed profile",
        "channel_roles": ["digital_input"],
        "required_actions": actions,
        "optional_actions": [],
    }


def _vendor_catalog() -> dict[str, Any]:
    return {
        "catalog_version": "1.0.0",
        "vendor": "com.meridian",
        "actions": {
            SWEEP_URN: {
                "description": "Run the M-400 frequency sweep.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dwell_s": {"type": "number", "minimum": 0.001},
                    },
                    "$id": SWEEP_SCHEMA_ID,
                },
                "output_schema": {"type": "object"},
                "side_effect": "state_change",
            },
        },
    }


def _member_declaration(
    members: list[dict[str, Any]],
    *,
    profiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if profiles is None:
        claims = sorted(
            {
                str(claim)
                for member in members
                if member.get("kind") != "channels"
                for claim in member.get("claims", ())
            }
        )
        profiles = [_vendor_profile_row(claims)]
    return {
        "contract_version": "0.1.0",
        "profiles": profiles,
        "members": members,
    }


def _sweep_member(page: str = "capture") -> dict[str, Any]:
    return {
        "slot": "sweep",
        "kind": "procedure",
        "claims": [SWEEP_URN],
        "page": page,
    }


def _project(
    tmp_path: Path,
    *,
    declaration: dict[str, Any],
    actions: dict[str, Any] | None = None,
    with_catalog: bool = True,
) -> Any:
    """Derive over the f1 fixture body with the member declaration and the
    vendor catalog pinned beside the descriptor."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["profiles"].append(VENDOR_PROFILE_ID)
    descriptor["actions"].update(actions or {})
    descriptor["actions"][SWEEP_URN] = {
        "binding": {"kind": "adapter", "key": "fixture"},
        "input_constraints": {},
        "timeout_ms": 30000,
        "side_effect": "state_change",
        "cancellable": True,
        "retry": "never",
    }
    catalog = _vendor_catalog()
    pins: list[tuple[str, dict[str, Any]]] = [(MEMBER_PIN, declaration)]
    if with_catalog:
        pins.append((CATALOG_PIN, catalog))
    for name, document in pins:
        descriptor["contracts"].append(
            {
                "id": f"urn:meridian:{name.removesuffix('.json')}:1.0.0",
                "path": name,
                "sha256": hashlib.sha256(_raw(document)).hexdigest(),
            }
        )
    scratch = tmp_path / "project"
    scratch.mkdir(parents=True)
    (scratch / "descriptor.json").write_bytes(_raw(descriptor))
    for name, document in pins:
        (scratch / name).write_bytes(_raw(document))
    (scratch / "vendor-catalog.json").write_bytes(
        (FIXTURES / "vendor-catalog.json").read_bytes()
    )
    return derive_ui(
        (scratch / "descriptor.json").read_bytes(),
        REFERENCE,
        descriptor_path=scratch / "descriptor.json",
    )


def _procedure_targets(derived: Any) -> list[dict[str, Any]]:
    return [row for row in derived.catalogue["targets"] if row["kind"] == "procedure"]


def test_a_procedure_member_composes_target_and_binding(tmp_path: Path) -> None:
    """(#556 §4 V1 layer 2) A procedure member's injected slot rides the
    EXISTING procedure loop unchanged: the target composes with the vendor
    profile id the declaration supplies — the seam — beside the binding,
    and the canonical validator admits the vendor action because the merged
    pinned row lists it. No new component, no new page, no new node kind."""
    derived = _project(tmp_path, declaration=_member_declaration([_sweep_member()]))
    targets = [
        row for row in _procedure_targets(derived) if row["action_id"] == SWEEP_URN
    ]
    assert targets == [
        {
            "id": "sweep",
            "kind": "procedure",
            "action_id": SWEEP_URN,
            "profile_ids": [VENDOR_PROFILE_ID],
            "input_schema_id": SWEEP_SCHEMA_ID,
        }
    ], derived.catalogue["targets"]
    assert {"id": "sweep", "kind": "procedure", "target_id": "sweep"} in (
        derived.manifest["bindings"]
    )


def test_a_procedure_member_places_its_control_on_the_named_page(
    tmp_path: Path,
) -> None:
    """The plan row's page comes from the slot (§4 V1): the sweep control
    derives on the named capture page — level L1 (the vendor catalog row
    declares no required input), resolution catalog — and the authored
    page's completion pass welds the button through the existing arm."""
    derived = _project(tmp_path, declaration=_member_declaration([_sweep_member()]))
    row = derived.control_plan[SWEEP_URN]
    assert row["page"] == "capture"
    assert row["level"] == "L1"
    capture = next(
        page
        for page in derived.layout_block["pages"]
        if page["page_id"] == "capture"
    )
    buttons = [
        node
        for section in capture["sections"]
        for node in section.get("children", [])
        if node.get("kind") == "button"
    ]
    assert {"binding_id": "sweep", "kind": "button"} in buttons, buttons


def test_the_ledger_records_the_applied_procedure_member(tmp_path: Path) -> None:
    """Provenance (§4 V1): the ledger row is the applied member's own —
    one writer, the composed-member walk (the B3 machinery), carried on
    ``composed_members.procedures`` with the slot, the action and the
    page."""
    derived = _project(tmp_path, declaration=_member_declaration([_sweep_member()]))
    assert derived.composed_members["procedures"] == (
        {"slot": "sweep", "action": SWEEP_URN, "page": "capture"},
    )
    assert derived.declaration["composed_members"]["procedures"] == [
        {"slot": "sweep", "action": SWEEP_URN, "page": "capture"}
    ]


def test_an_action_member_without_a_profile_row_refuses(tmp_path: Path) -> None:
    """A procedure member composes a target that names the declaration's
    vendor profile row; a declaration carrying no row is malformed for the
    surface it requests — a declaration conflict the 0.1.0 schema cannot
    express (a cross-array conditional), refusing under the member
    declaration's own invalidity code. What this does NOT catch: a profile
    row whose required/optional actions omit the member's claim — the
    canonical validator reports that as ``capability_mismatch`` at
    check-ui, a finding, never a refusal here."""
    declaration = _member_declaration([_sweep_member()], profiles=[])
    declaration.pop("profiles")
    with pytest.raises(
        ValueError, match="^classref_invalid_member_declaration:"
    ) as raised:
        _project(tmp_path, declaration=declaration)
    assert "sweep" in str(raised.value)


def test_an_applied_member_claiming_an_uncatalogued_action_refuses(
    tmp_path: Path,
) -> None:
    """The D4 rule's member half: an applied procedure member's target names
    the catalogue side (``input_schema_id``), and an action no served or
    pinned catalog describes has none — the canonical validator would
    refuse the derived target twice over (``unresolved_reference`` and
    ``capability_mismatch``), so the derivation refuses at the claim under
    the reference-slot rule's own code. The author's fix is the
    declaration's environment: pin the vendor catalog row."""
    with pytest.raises(ValueError, match="^classref_unknown_action:") as raised:
        _project(
            tmp_path,
            declaration=_member_declaration([_sweep_member()]),
            with_catalog=False,
        )
    assert SWEEP_URN in str(raised.value)
