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

from benchweave_sdk.classref import ResidualMember, derive_ui, find_reference

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


def _plotless_reference() -> dict[str, Any]:
    """The daq reference with the capture page's waveform plot stripped: a
    dataset page that hosts NO plot template — the page shape V5's member
    ``plot`` choice exists for (every vendored dataset/readings page hosts
    one; the composing arm needs the plot-less page the corpus does not
    carry, built here as the authoring-side test fixture it is)."""
    reference = json.loads(json.dumps(REFERENCE))
    for page in reference["pages"]:
        if str(page["id"]) == "capture":
            page.pop("plot", None)
    return reference


def _derive_custom(
    tmp_path: Path, declaration: dict[str, Any], reference: dict[str, Any]
) -> Any:
    """_project's shape over a CUSTOM reference (the plot-less arm)."""
    descriptor = json.loads((FIXTURES / "descriptor-m400.json").read_bytes())
    catalog = json.loads((FIXTURES / CATALOG_PIN).read_bytes())
    catalog["actions"][SEGMENT_CAPTURE_URN] = _catalog_row()
    by_name = {MEMBER_PIN: declaration, CATALOG_PIN: catalog}
    descriptor["contracts"] = [
        row for row in descriptor["contracts"] if row.get("path") not in by_name
    ]
    for name, document in by_name.items():
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
    for name, document in by_name.items():
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
        reference,
        descriptor_path=scratch / "descriptor.json",
    )


def _plotless_project(
    tmp_path: Path,
    plot: dict[str, Any],
) -> Any:
    """Derive over the M-400 body with ONE dataset member carrying ``plot``
    against the plot-less reference."""
    return _derive_custom(
        tmp_path, _declaration([_dataset_member(plot=plot)]), _plotless_reference()
    )


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


# ---------------------------------------------------------------------------
# V5 layer 2 — the member's ``plot`` choice derives on a plot-less page
# (§4 V5): among the EXISTING three kinds, validated against the family
# schema's own plot def, through the existing plot emission.
# ---------------------------------------------------------------------------


def test_a_waveform_plot_choice_derives_on_a_plotless_page(tmp_path: Path) -> None:
    """(#556 §4 V5 layer 2) A dataset member's ``plot`` on a page hosting no
    plot template DERIVES: the existing emission renders the waveform over
    the member's own slot — binding the member's dataset, x the explicit
    time axis, y the shape's trace variables — and the member's dataset
    shape speaks the chosen kind (the plot registers in
    ``plot_kind_for_slot`` through the injected page template)."""
    derived = _plotless_project(
        tmp_path,
        {"kind": "waveform", "over_slot": "segment-capture",
         "series": "numeric_variables"},
    )
    (plot,) = [
        plot
        for page in derived.manifest["pages"]
        for plot in (page.get("plots") or [])
    ]
    assert plot == {
        "kind": "waveform",
        "binding_id": "segment-capture",
        "x": "t",
        "y": list(LANE_TRACE_IDS),
    }, plot
    target = next(
        row for row in _dataset_targets(derived) if row["id"] == "segment-capture"
    )
    assert [row["id"] for row in target["variables"]] == [
        "t", *LANE_TRACE_IDS,
    ], target
    # The R9 stamp (§4 V4 provenance): a composed dataset row advertises a
    # rendering only when a derived plot carries its binding — this one
    # does, so the row carries rendered_by.
    assert (
        derived.control_plan[SEGMENT_CAPTURE_URN]["rendered_by"] == "the page plot"
    ), derived.control_plan[SEGMENT_CAPTURE_URN]
    # No residual row for a member whose plot derives (R10's direction).
    assert not any(
        row.member == "segment-capture" for row in derived.residual_members
    ), derived.residual_members


def test_a_time_series_plot_choice_derives_on_a_plotless_page(
    tmp_path: Path,
) -> None:
    """The second of the three kinds: time_series speaks receipt time and
    scalar value variables — x ``time``, y one per lane quantity, all
    scalars (the wire shape the kind declares)."""
    derived = _plotless_project(
        tmp_path,
        {"kind": "time_series", "over_slot": "segment-capture",
         "series": "numeric_variables"},
    )
    (plot,) = [
        plot
        for page in derived.manifest["pages"]
        for plot in (page.get("plots") or [])
    ]
    assert plot == {
        "kind": "time_series",
        "binding_id": "segment-capture",
        "x": "time",
        "y": list(LANE_TRACE_IDS),
    }, plot
    target = next(
        row for row in _dataset_targets(derived) if row["id"] == "segment-capture"
    )
    assert [row["id"] for row in target["variables"]] == [
        "time", *LANE_TRACE_IDS,
    ], target
    assert all(
        row["shape"] == "scalar"
        for row in target["variables"]
        if row["id"] != "time"
    ), target


def test_a_digital_lanes_plot_choice_derives_on_a_plotless_page(
    tmp_path: Path,
) -> None:
    """The third kind: digital_lanes over the member's own slot binds the
    MEMBER's dataset — whose digital-lanes shape carries exactly these lane
    string variables — never the class capture binding, whose waveform
    shape carries none of them. The lane groups and channel hints derive
    through the founding machinery."""
    derived = _plotless_project(
        tmp_path,
        {"kind": "digital_lanes", "over_slot": "segment-capture"},
    )
    (plot,) = [
        plot
        for page in derived.manifest["pages"]
        for plot in (page.get("plots") or [])
    ]
    assert plot["kind"] == "digital_lanes", plot
    assert plot["binding_id"] == "segment-capture", plot
    assert plot["y"] == ["ch1", "ch2", "ch3"], plot
    assert [group["member_ids"] for group in plot["lane_groups"]] == [
        ["ch1", "ch2", "ch3"]
    ], plot
    target = next(
        row for row in _dataset_targets(derived) if row["id"] == "segment-capture"
    )
    assert [row["id"] for row in target["variables"]] == [
        "t", "ch1", "ch2", "ch3",
    ], target
    assert all(
        row["type"] == "string"
        for row in target["variables"]
        if row["id"] != "t"
    ), target


def test_the_plot_choice_survives_the_real_gate(tmp_path: Path) -> None:
    """The composed plot through the real gate: the project derives, the
    host renders, the census counts the member's plot on the capture page
    (the reference's own engineering-plot expectation, still one — the
    member's plot replaced the stripped template), and the run is clean
    with the L4 dataset surface covered by the member's own plot."""
    from benchweave_sdk.classref_gate import verify_ui
    from benchweave_sdk.scaffold import create_project

    derived = _derive_custom(
        tmp_path / "derive",
        _declaration(
            [
                _dataset_member(
                    plot={
                        "kind": "waveform",
                        "over_slot": "segment-capture",
                        "series": "numeric_variables",
                    }
                )
            ]
        ),
        _plotless_reference(),
    )
    scratch = tmp_path / "derive" / "project"
    project = tmp_path / "gate-project"
    create_project(project, "veridian_dataset_plot_plugin", with_ui=False)
    package = project / "src" / "veridian_dataset_plot_plugin"
    for path in sorted(scratch.iterdir()):
        if path.is_file():
            (package / path.name).write_bytes(path.read_bytes())
    ui = package / "ui"
    ui.mkdir()
    (ui / "manifest.json").write_bytes(_raw(derived.manifest))
    (package / "presentation.json").write_bytes(_raw(derived.envelope))
    (package / "binding-catalogue.json").write_bytes(_raw(derived.catalogue))
    settings = ui / "settings"
    settings.mkdir()
    # One settings asset per configuration surface — the B4 writer shape;
    # the single-slot convenience pins the wrong bytes on a composed
    # project.
    for slot_key, schema in derived.settings_schemas.items():
        (settings / f"{slot_key}.schema.json").write_bytes(_raw(schema))
    presets = ui / "presets"
    presets.mkdir()
    for slug, scaffold in derived.preset_scaffolds.items():
        (presets / f"{slug}.json").write_bytes(_raw(scaffold))
    (ui / "class-reference.json").write_bytes(_raw(derived.declaration))
    report = verify_ui(project, reference=_plotless_reference())
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    # The dataset member's surface is not a deviation: no composed-plot row,
    # no composed-dataset row, no applied-nowhere row rides the channel.
    assert [
        row for row in report.reported_deviations if "composed" in row
    ] == [], report.reported_deviations


# ---------------------------------------------------------------------------
# The residual rows B5 mints: the placement limit (a page the manifest
# schema admits no plot on), the dataset no-binding disclosure (risk #6's
# falsifier — REPORTED, never laundered by the neighbour plot's census
# coverage), and V4's layer-3 classifier for the unclaimed capture verb.
# ---------------------------------------------------------------------------


def test_a_member_plot_on_a_page_admitting_no_plot_reports(tmp_path: Path) -> None:
    """The 2026-10-25 capacity-versus-declaration boundary's placement half:
    a member ``plot`` naming a configuration page contradicts nothing the
    member schema can see (the family's own plot def carries no page-kind
    rule; the MANIFEST schema admits plots on dataset and readings pages
    alone), so it never refuses — the page kind is a placement limit the
    declaration cannot see, and the row discloses it every run."""
    derived = _project(
        tmp_path,
        _declaration(
            [
                _dataset_member(
                    page="configuration",
                    plot={
                        "kind": "time_series",
                        "over_slot": "segment-capture",
                        "series": "numeric_variables",
                    },
                )
            ]
        ),
    )
    rows = [
        row for row in derived.residual_members if row.kind == "composed plot"
    ]
    assert rows == [
        ResidualMember(
            "composed plot",
            "datasets and capture shapes",
            "segment-capture",
            "page configuration admits no plot (plots render on dataset "
            "and readings pages alone)",
        ),
    ], derived.residual_members


def test_a_composed_dataset_no_plot_carries_reports_not_launder(
    tmp_path: Path,
) -> None:
    """(Record §9 risk #6's falsifier — the R9 lesson: building is not
    rendering) A composed dataset slot on a plot-bearing page whose plot
    does NOT carry its binding must REPORT, never pass silently on the
    neighbour plot's census coverage: the M-400's production shape (the
    member beside the class capture plot, no plot of its own) derives its
    dataset surface and carries the disclosure row, and the plan row
    carries NO rendered_by advertisement — the row claims a rendering only
    when that rendering occurs."""
    derived = _project(tmp_path, _declaration([_dataset_member()]))
    rows = [
        row
        for row in derived.residual_members
        if row.kind == "composed dataset"
    ]
    assert rows == [
        ResidualMember(
            "composed dataset",
            "datasets and capture shapes",
            "segment-capture",
            "no plot carries its binding (the plot on page capture binds "
            "capture)",
        ),
    ], derived.residual_members
    assert "rendered_by" not in derived.control_plan[SEGMENT_CAPTURE_URN]
    # The other direction (R10's rule is two-sided): when a derived plot
    # carries the binding, no row and the stamp lands — the composing arm
    # above asserts the stamp; this asserts the row's disappearance on the
    # same body.
    composed = _plotless_project(
        tmp_path / "plotted",
        {"kind": "waveform", "over_slot": "segment-capture",
         "series": "numeric_variables"},
    )
    assert not any(
        row.kind == "composed dataset" for row in composed.residual_members
    ), composed.residual_members


def test_a_capture_shaped_residual_action_reports_no_dataset_surface(
    tmp_path: Path,
) -> None:
    """(#556 §4 V4 layer 3) A declared action whose bare button renders on
    device-features — the capture verb's control shape — carries the
    dataset vocabulary's residual row: it derives its action control only,
    no dataset surface names it. The design's 'capture-shaped' has no
    descriptor-side signal (OTDP types no verbs; ``capture_formats`` is
    device-level and read by nothing), so the classifier is the derived
    state — the V6 precedent: unclaimed (page device-features) AND level
    L1, EXCEPT an action a served profile row of a claimed profile lists
    (the one honest class-action signal). The row DISAPPEARS when a dataset
    member claims the action."""
    capture_verb = {
        "com.meridian.m400.scope_shot/1.0.0": {
            "binding": {"kind": "adapter", "key": "scope_shot"},
            "input_constraints": {"properties": {}},
            "timeout_ms": 5000,
            "side_effect": "state_change",
            "cancellable": True,
            "retry": "never",
        }
    }
    residual = _project(
        tmp_path,
        _declaration([_dataset_member()]),
        extra_actions=capture_verb,
    )
    row = next(
        (
            row
            for row in residual.residual_members
            if row.member == "com.meridian.m400.scope_shot/1.0.0"
        ),
        None,
    )
    assert row is not None, residual.residual_members
    assert row.kind == "dataset member"
    assert row.vocabulary == "datasets and capture shapes"
    assert row.detail == (
        "no dataset surface declared (the action's control renders on "
        "device-features)"
    )
    claimed = _project(
        tmp_path / "claimed",
        _declaration([_dataset_member(claim="com.meridian.m400.scope_shot/1.0.0")]),
        extra_actions=capture_verb,
    )
    assert not any(
        row.member == "com.meridian.m400.scope_shot/1.0.0"
        for row in claimed.residual_members
    ), claimed.residual_members
