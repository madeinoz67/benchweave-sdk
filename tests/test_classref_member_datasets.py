"""#556 Track B B5: the dataset-kind member injection — V4 datasets and
capture shapes, V5 plot kinds (design record §4 V4 and V5;
``.claude/deep-review/2026-10-25-issue556-track-b-vocabularies.md``).

The injection seam's dataset half: a member of kind ``dataset`` injects the
reference slot branch's own closed fields into the merged reference, and the
dataset arm composes the target with the vendor profile id the declaration
supplies (the seam, §0.2) and the measurement schema id from the descriptor's
pinned measurement contract — the existing target shape, driven by the
composed slot. The derivation refinement the record states for this slice:
``_dataset_shape`` for a slot with no plot spec of its own INHERITS the
binding page's plot kind (the founding fall-through derived the
digital-lanes string-lane shape, which for a vendor capture bound beside a
waveform plot mis-derives the wire shape — the inheritance rule fixes
exactly that).

V5's composing half rides the member's ``plot`` field: the vendor chooses
among the EXISTING three kinds for a page that hosts no plot template,
validated against the family schema's own plot def (the 0.5.0 member schema
carries it verbatim). A page that already hosts a plot keeps the class's and
the member's choice discloses (the B3 row); the nine measurement kinds beyond
the three presentation kinds are the honest terminal state — no fourth kind
is invented, and a dataset no presentation kind hosts derives the disclosure
row this module arms.

The byte-stability premise (the record's rule that a dataset-shape change
which moves an existing device's derived bytes is a regression): every
vendored reference places no dataset slot on a page whose plot hosts another
slot's over-slot, asserted structurally below — a future corpus reference
that breaks it moves THIS arm, not a digest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.classref import derive_ui, find_reference

FIXTURES = Path(__file__).parent / "fixtures" / "classref"
REFERENCE = find_reference("otdp.daq/1.0.0")

#: Invented vendor identity throughout (CLAUDE.md §4).
VENDOR_PROFILE_ID = "com.meridian.m400/1.0.0"
#: The vendor capture verb the extended M-400 fixture declares and the
#: dataset member claims (V4's declaration surface: a capture verb action).
SEGMENT_CAPTURE_URN = "com.meridian.m400.segment_capture/1.0.0"
SEGMENT_CAPTURE_SCHEMA_ID = "urn:meridian:action:segment-capture:1.0.0:input"
#: The pinned measurement contract the M-400 descriptor carries — the
#: measurement schema id a composed dataset target names.
MEASUREMENT_ID = "urn:otdp:measurement:0.2.3"
#: The M-400's analogue channels (the default lanes a waveform shape derives
#: its trace variables from): ids and quantities, from the fixture bytes.
LANE_TRACE_IDS = ("ch1-voltage", "ch2-voltage", "ch3-strain")

MEMBER_PIN = "member-declaration-m400.json"
CATALOG_PIN = "meridian-actions.json"


def _raw(document: object) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _vendor_profile_row(actions: list[str]) -> dict[str, Any]:
    """The device-profile-catalog's own row shape, verbatim field set."""
    return {
        "id": VENDOR_PROFILE_ID,
        "title": "Meridian M-400 composed profile",
        "channel_roles": ["analogue_input"],
        "required_actions": actions,
        "optional_actions": [],
    }


def _catalog_row() -> dict[str, Any]:
    """The pinned vendor catalog's row for the capture verb (the catalogue
    side of the composed control; the dataset target needs no input schema
    id — this row exists so the claimed action resolves ``catalog``, the
    production shape the fixture pins)."""
    return {
        "description": "Capture one M-400 waveform segment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "duration_s": {"type": "number", "minimum": 0.1},
            },
            "required": ["duration_s"],
            "$id": SEGMENT_CAPTURE_SCHEMA_ID,
        },
        "output_schema": {"type": "object"},
        "side_effect": "state_change",
    }


def _dataset_member(
    *,
    slot: str = "segment-capture",
    claim: str = SEGMENT_CAPTURE_URN,
    page: str = "capture",
    plot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    member: dict[str, Any] = {
        "slot": slot,
        "kind": "dataset",
        "claims": [claim],
        "schema_source": "output_measurement",
        "page": page,
    }
    if plot is not None:
        member["plot"] = plot
    return member


def _declaration(
    members: list[dict[str, Any]],
    *,
    profile: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    """One member declaration over the given members. ``profile=None`` (the
    default) lists every claim-carrying member's claim in the vendor row —
    the seam's admission half, the row the canonical validator reads from
    the pinned document; ``profile="omit"`` writes no ``profiles`` key at
    all (the no-row refusal arm)."""
    if profile == "omit":
        return {"contract_version": "0.1.0", "members": members}
    if profile is None:
        claims = sorted(
            {
                str(claim)
                for member in members
                if member.get("kind") != "channels"
                for claim in member.get("claims", ())
            }
        )
        profile = _vendor_profile_row(claims)
    return {
        "contract_version": "0.1.0",
        "profiles": [profile],
        "members": members,
    }


def _project(
    tmp_path: Path,
    declaration: dict[str, Any],
    *,
    extra_actions: dict[str, Any] | None = None,
    with_catalog_row: bool = True,
) -> Any:
    """Derive over the M-400 fixture body with the member declaration (and
    the capture verb's catalog row) re-pinned beside the descriptor — the
    B4 scratch shape, over the daq-profile fixture this slice extends."""
    descriptor = json.loads((FIXTURES / "descriptor-m400.json").read_bytes())
    if extra_actions:
        descriptor["actions"].update(extra_actions)
    if with_catalog_row:
        catalog = json.loads((FIXTURES / CATALOG_PIN).read_bytes())
        catalog["actions"][SEGMENT_CAPTURE_URN] = _catalog_row()
    pins: list[tuple[str, dict[str, Any]]] = [(MEMBER_PIN, declaration)]
    if with_catalog_row:
        pins.append((CATALOG_PIN, catalog))
    by_name = {name: document for name, document in pins}
    descriptor["contracts"] = [
        row
        for row in descriptor["contracts"]
        if row.get("path") not in by_name
    ]
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
    for pinned in (
        "composed-burst.json",
        "device-profile-catalog.json",
        "otdp-measurement.schema.json",
    ):
        source = FIXTURES / pinned
        if source.is_file():
            (scratch / pinned).write_bytes(source.read_bytes())
    return derive_ui(
        (scratch / "descriptor.json").read_bytes(),
        REFERENCE,
        descriptor_path=scratch / "descriptor.json",
    )


def _dataset_targets(derived: Any) -> list[dict[str, Any]]:
    return [row for row in derived.catalogue["targets"] if row["kind"] == "dataset"]


# ---------------------------------------------------------------------------
# V4 layer 2 — the dataset member composes target + binding through the
# existing dataset arm (§4 V4).
# ---------------------------------------------------------------------------


def test_a_dataset_member_composes_target_and_binding(tmp_path: Path) -> None:
    """(#556 §4 V4 layer 2) A dataset member's injected slot rides the
    dataset arm: the target composes with the vendor profile id the
    declaration supplies — the seam — and the measurement schema id from the
    descriptor's pinned measurement contract, beside the binding. No new
    target shape, no new page, no new node kind."""
    derived = _project(tmp_path, _declaration([_dataset_member()]))
    targets = [
        row
        for row in _dataset_targets(derived)
        if row["action_id"] == SEGMENT_CAPTURE_URN
    ]
    assert targets == [
        {
            "id": "segment-capture",
            "kind": "dataset",
            "action_id": SEGMENT_CAPTURE_URN,
            "profile_ids": [VENDOR_PROFILE_ID],
            "measurement_schema_id": MEASUREMENT_ID,
            "variables": [
                {"id": "t", "type": "number", "unit": "s", "shape": "vector",
                 "axis_role": "x"},
                *[
                    {"id": lane, "type": "number", "unit": None,
                     "shape": "vector"}
                    for lane in LANE_TRACE_IDS
                ],
            ],
        }
    ], derived.catalogue["targets"]
    assert {"id": "segment-capture", "kind": "dataset",
            "target_id": "segment-capture"} in derived.manifest["bindings"]


def test_the_dataset_shape_inherits_the_binding_pages_plot_kind(
    tmp_path: Path,
) -> None:
    """The derivation refinement the record states for this slice (#556 §4
    V4): a dataset slot with no plot spec of its own INHERITS the binding
    page's plot kind. The daq capture page hosts a waveform plot over the
    class ``capture`` slot, so the member bound beside it derives the
    WAVEFORM wire shape — the explicit time axis and one vector trace per
    lane quantity — never the founding digital-lanes string-lane shape
    ``[x_var, *lane_vars]`` that would contradict the page."""
    derived = _project(tmp_path, _declaration([_dataset_member()]))
    member_target = next(
        row
        for row in _dataset_targets(derived)
        if row["id"] == "segment-capture"
    )
    class_target = next(
        row for row in _dataset_targets(derived) if row["id"] == "capture"
    )
    assert [row["id"] for row in member_target["variables"]] == [
        "t",
        *LANE_TRACE_IDS,
    ], member_target
    # The inherited shape is the class's own waveform shape over the same
    # default lanes — same ids, same vector shape, same axis.
    assert [row["id"] for row in member_target["variables"]] == [
        row["id"] for row in class_target["variables"]
    ]
    assert all(
        row["shape"] == "vector" for row in member_target["variables"]
    ), member_target


def test_the_ledger_row_carries_the_slot_action_page_and_plot_kind(
    tmp_path: Path,
) -> None:
    """Provenance (§4 V4): the ledger row is the applied member's own —
    ``composed_members.datasets`` with the slot, the action, the page and,
    when the member declares one, the ``plot_kind`` (V5's provenance
    surface: the derived plot row is wire-shaped BY DESIGN, so the ledger is
    where the vendor's choice is recorded)."""
    derived = _project(
        tmp_path,
        _declaration(
            [
                _dataset_member(
                    plot={
                        "kind": "time_series",
                        "over_slot": "segment-capture",
                        "series": "numeric_variables",
                    }
                )
            ]
        ),
    )
    assert derived.composed_members["datasets"] == (
        {
            "slot": "segment-capture",
            "action": SEGMENT_CAPTURE_URN,
            "page": "capture",
            "plot_kind": "time_series",
        },
    )
    assert derived.declaration["composed_members"]["datasets"] == [
        {
            "slot": "segment-capture",
            "action": SEGMENT_CAPTURE_URN,
            "page": "capture",
            "plot_kind": "time_series",
        }
    ]
    # Without a declared plot the row carries no plot_kind key at all.
    bare = _project(tmp_path / "bare", _declaration([_dataset_member()]))
    assert bare.composed_members["datasets"] == (
        {
            "slot": "segment-capture",
            "action": SEGMENT_CAPTURE_URN,
            "page": "capture",
        },
    )


def test_a_dataset_member_without_a_profile_row_refuses(tmp_path: Path) -> None:
    """The B4 admission rule's dataset half, lifted with the surface it
    guards: an APPLIED dataset member composes a target naming the
    declaration's vendor profile row, so a declaration carrying no row is
    malformed for the surface it requests — a cross-array conditional the
    0.1.0 dialect schema cannot express, refusing under the member
    declaration's own invalidity code. A member that applies nowhere
    composes nothing and stays the applied-nowhere disclosure."""
    with pytest.raises(
        ValueError, match="^classref_invalid_member_declaration:"
    ) as raised:
        _project(
            tmp_path,
            _declaration([_dataset_member()], profile="omit"),
        )
    assert "segment-capture" in str(raised.value)
    assert "dataset" in str(raised.value)


def test_a_dead_dataset_member_reports_the_applied_nowhere_row(
    tmp_path: Path,
) -> None:
    """(§4 V4; the B3 fold's F2 wording family) A member whose action the
    descriptor does not declare applies nowhere and reports on the per-member
    applied-nowhere row — no refusal, no surface, the claim half mirroring
    the composed-class row's own wording."""
    derived = _project(
        tmp_path,
        _declaration(
            [_dataset_member(claim="com.meridian.m400.undeclared/1.0.0")]
        ),
    )
    assert derived.unapplied_members == (
        (
            MEMBER_PIN,
            "segment-capture",
            "its claims name no action this descriptor declares",
        ),
    ), derived.unapplied_members
    assert not any(
        row["action_id"] == "com.meridian.m400.undeclared/1.0.0"
        for row in _dataset_targets(derived)
    )


def test_no_vendored_reference_places_a_dataset_slot_beside_a_foreign_plot() -> None:
    """The byte-stability premise, asserted structurally (the B3 M6
    pattern): no vendored reference places a dataset slot on a page whose
    plot hosts another slot's over-slot, so the page-kind inheritance moves
    no committed fixture's derived bytes. A future corpus reference that
    breaks the premise moves THIS arm, not a digest."""
    root = (
        Path(__file__).resolve().parents[1]
        / "src/benchweave_sdk/standards/plugin-ui-class-reference"
    )
    references = sorted(
        path
        for path in root.glob("*/class-*.json")
        if not path.name.endswith(".schema.json")
    )
    assert len(references) >= 8
    for path in references:
        document = json.loads(path.read_bytes())
        for key, slot in document.get("slots", {}).items():
            if slot.get("kind") != "dataset":
                continue
            for page in document["pages"]:
                if key not in page.get("binding_slots", []):
                    continue
                plot = page.get("plot")
                if plot is not None and str(plot.get("over_slot")) != key:
                    raise AssertionError(
                        f"{path.name}: dataset slot {key} sits on page "
                        f"{page['id']} whose plot hosts over_slot "
                        f"{plot.get('over_slot')!r}"
                    )
