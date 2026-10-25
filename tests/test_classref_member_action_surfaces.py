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
CONFIGURE_URN = "com.meridian.m400.profile_mode/1.0.0"
CONFIGURE_SCHEMA_ID = "urn:meridian:action:profile-mode:1.0.0:input"
#: A configuration-shaped residual: numeric, expressible, unclaimed — the
#: staged-form signature on device-features.
STAGED_URN = "com.meridian.m400.audit_log/1.0.0"

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
            CONFIGURE_URN: {
                "description": "Set the M-400 profile mode.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "profile": {
                            "type": "string",
                            "enum": ["short", "long"],
                        },
                        "aperture_s": {
                            "type": "number",
                            "minimum": 0.01,
                            "maximum": 10.0,
                        },
                    },
                    "required": ["profile", "aperture_s"],
                    "$id": CONFIGURE_SCHEMA_ID,
                },
                "output_schema": {"type": "object"},
                "side_effect": "state_change",
            },
            STAGED_URN: {
                "description": "Set the M-400 audit-log retention.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "retain_days": {"type": "integer", "minimum": 1},
                    },
                    "required": ["retain_days"],
                    "$id": "urn:meridian:action:audit-log:1.0.0:input",
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


def _settings_member(
    *, slot: str = "vendor-configure", claim: str = CONFIGURE_URN
) -> dict[str, Any]:
    return {
        "slot": slot,
        "kind": "configuration",
        "claims": [claim],
        "schema_source": "input_schema",
        "page": "configuration",
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
    descriptor["actions"][CONFIGURE_URN] = {
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


# ---------------------------------------------------------------------------
# V6 — settings idioms (#556 §4 V6): the FULL existing idiom, driven by the
# composed slot — the settings schema asset, the preset scaffold with its
# A02 birth deviation, the configuration target and binding, and the L3
# data-table. A02 carries unchanged: the deviation rides every composed
# settings member exactly as it rides a class slot's.
# ---------------------------------------------------------------------------


def test_a_settings_member_composes_the_full_idiom(tmp_path: Path) -> None:
    """(#556 §4 V6 layer 2) The composed configuration slot drives the
    existing configuration arm end to end: the settings schema ASSET rides
    the manifest beside the class's own, the effective schema is the
    composed catalogue side (D13 unchanged), the preset scaffold names the
    vendor profile id, and the target+binding compose with the same id —
    no partial idiom, no new surface kind."""
    derived = _project(
        tmp_path,
        declaration=_member_declaration(
            [_sweep_member(), _settings_member()],
        ),
    )
    targets = [
        row for row in derived.catalogue["targets"] if row["action_id"] == CONFIGURE_URN
    ]
    assert targets == [
        {
            "id": "vendor-configure",
            "kind": "configuration",
            "action_id": CONFIGURE_URN,
            "profile_ids": [VENDOR_PROFILE_ID],
            "input_schema_id": CONFIGURE_SCHEMA_ID,
            "schema_asset_id": "settings/vendor-configure.schema.json",
            "preset_asset_ids": [],
        }
    ], derived.catalogue["targets"]
    asset_ids = {row["id"] for row in derived.manifest["assets"]}
    assert "settings/vendor-configure.schema.json" in asset_ids
    assert "settings/configure.schema.json" in asset_ids
    # The per-slot map the writer consumes: every configuration slot's
    # effective schema, keyed by its slot.
    assert set(derived.settings_schemas) == {"configure", "vendor-configure"}
    scaffold = derived.preset_scaffolds["vendor-configure"]
    assert scaffold["profile_ids"] == [VENDOR_PROFILE_ID]
    assert scaffold["settings_schema"]["id"] == CONFIGURE_SCHEMA_ID
    assert scaffold["provenance"]["evidence"] == "synthetic"
    assert {"id": "vendor-configure", "kind": "configuration",
            "target_id": "vendor-configure"} in derived.manifest["bindings"]
    assert derived.composed_members["settings"] == (
        {"slot": "vendor-configure", "action": CONFIGURE_URN,
         "page": "configuration"},
    )


def test_the_a02_birth_deviation_rides_composed_settings_members(
    tmp_path: Path,
) -> None:
    """A02 carries unchanged (§4 V6; KILL (d) guards a settings surface
    without the deviation): the preset surface's birth deviation rides the
    composed settings member EXACTLY as it rides the class slot's — same
    reason string, one row per configuration surface, on the ledger the
    gate reads back."""
    derived = _project(
        tmp_path,
        declaration=_member_declaration(
            [_sweep_member(), _settings_member()],
        ),
    )
    deviation_rows = {
        row["expectation_id"]: row["reason"]
        for row in derived.declaration["deviations"]
    }
    expected_reason = (
        "preset surface derived with no commissioned presets at birth; "
        "author ui/presets/ and validate via check-preset"
    )
    assert deviation_rows.get("otdp.logic_analyser.configure/1.0.0") == (
        expected_reason
    ), deviation_rows
    assert deviation_rows.get(CONFIGURE_URN) == expected_reason, deviation_rows


def test_the_configure_numeric_count_sums_every_l3_row(tmp_path: Path) -> None:
    """The expect arithmetic stays true of the COMPOSED device: the
    ``{n_configure_fields}`` inventory names every configuration surface's
    numeric fields — the class slot's and the member's — never the first
    row alone (first-wins under-counted the moment a second settings
    surface existed)."""
    derived = _project(
        tmp_path,
        declaration=_member_declaration(
            [_sweep_member(), _settings_member()],
        ),
    )
    l3_numeric = {
        urn: sum(1 for field in row.get("fields", ()) if field["mode"] == "numeric")
        for urn, row in derived.control_plan.items()
        if row["level"] == "L3"
    }
    assert set(l3_numeric) == {
        "otdp.logic_analyser.configure/1.0.0",
        CONFIGURE_URN,
    }, l3_numeric
    assert all(count > 0 for count in l3_numeric.values()), l3_numeric
    assert derived.expectation["inventory"]["n_configure_fields"] == sum(
        l3_numeric.values()
    )


def test_a_configuration_shaped_residual_action_reports_no_settings_surface(
    tmp_path: Path,
) -> None:
    """(#556 §4 V6 layer 3) A declared action whose controls render STAGED on
    device-features — the settings idiom's control shape without the idiom
    — REPORTs every run: no schema asset, no preset scaffold, no
    data-table. The design's 'configuration-shaped' has no descriptor-side
    signal (verbs are not typed), so the classifier is the derived state:
    unclaimed by any slot AND level L2. The row DISAPPEARS when a settings
    member claims the action (the R10 two-sided rule's direction)."""
    staged = {
        STAGED_URN: {
            "binding": {"kind": "adapter", "key": "fixture"},
            "input_constraints": {
                "properties": {"retain_days": {"type": "integer"}},
                "required": ["retain_days"],
            },
            "timeout_ms": 5000,
            "side_effect": "state_change",
            "cancellable": True,
            "retry": "never",
        }
    }
    residual = _project(
        tmp_path,
        declaration=_member_declaration([_sweep_member()]),
        actions=staged,
    )
    row = next(
        (
            row
            for row in residual.residual_members
            if row.member == STAGED_URN
        ),
        None,
    )
    assert row is not None, residual.residual_members
    assert row.kind == "settings member"
    assert row.vocabulary == "settings idioms"
    assert row.detail == (
        "no settings surface declared (controls render staged on device-features)"
    )
    composed = _project(
        tmp_path / "claimed",
        declaration=_member_declaration(
            [_sweep_member(), _settings_member(claim=STAGED_URN)]
        ),
        actions=staged,
    )
    assert not any(
        row.member == STAGED_URN for row in composed.residual_members
    ), composed.residual_members
    assert composed.composed_members["settings"][-1]["action"] == STAGED_URN
