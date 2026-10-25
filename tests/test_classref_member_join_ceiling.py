"""#556 Track B B3 fold: the page-level lane join is bounded (the
2026-10-25 capacity-versus-declaration boundary, join half).

Per-slot ``_resolve_channels`` bounds each slot alone against
``_LANE_CEILING``; the page-level JOIN of the first slot's lanes with
every placed member slot's lanes bounded nothing — a 32-lane reference
role plus a 40-lane composed role derives a 72-entry ``y`` against the
manifest schema's 64, with zero disclosures, and the real ``verify_ui``
raises an unhandled ``PluginLoadError`` (the refute's F1, measured). The
join is a capacity limit no single declaration is at fault for: the
overflow drops from the plot alone — the wire shape keeps every joined
lane, the B1 discipline — and each dropped lane REPORTs, never refuses.
The per-slot refusal (``classref_lane_ceiling``, a single slot over the
ceiling) stays exactly as it is — armed in ``test_classref_expand.py`` —
a lane has no surface other than the plot, so truncating one slot's own
declaration would misrepresent the capture.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from benchweave_sdk.classref import ResidualMember, derive_ui, find_reference

FIXTURES = Path(__file__).parent / "fixtures" / "classref"
REFERENCE = find_reference("otdp.logic_analyser/1.0.0")

COMPOSED_ROLE = "digital_output"
MEMBER_PIN = "member-join.json"


def _raw(document: object) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _join_declaration() -> dict[str, Any]:
    return {
        "contract_version": "0.1.0",
        "members": [
            {
                "slot": "trigger_lanes",
                "kind": "channels",
                "where_role": COMPOSED_ROLE,
                "page": "capture",
            }
        ],
    }


def _channels(count: int, role: str, prefix: str) -> list[dict[str, Any]]:
    return [
        {
            "id": f"{prefix}{i}",
            "label": f"{prefix} line {i}",
            "role": role,
            "quantities": ["digital_level"],
            "parameter_names": [],
        }
        for i in range(count)
    ]


def _join_descriptor(composed_count: int) -> dict[str, Any]:
    """The f1 fixture with a 32-lane reference role (inside the per-slot
    ceiling on its own) plus ``composed_count`` composed-role channels and
    the member pin placing them on the capture page — the refute's shape."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["channels"] = [
        *_channels(32, "digital_input", "d"),
        *_channels(composed_count, COMPOSED_ROLE, "q"),
    ]
    descriptor["contracts"].append(
        {
            "id": "urn:veridian:member-join:1.0.0",
            "path": MEMBER_PIN,
            "sha256": hashlib.sha256(_raw(_join_declaration())).hexdigest(),
        }
    )
    return descriptor


def _persist(
    tmp_path: Path, name: str, descriptor: dict[str, Any]
) -> tuple[Any, Any]:
    """Derive over a scratch project and run the REAL gate on the persisted
    documents: on the pre-fold code the 72-entry ``y`` is refused by the
    manifest schema inside the host load and escapes as an unhandled
    ``PluginLoadError`` — the failure this fold pins."""
    from benchweave_sdk.classref_gate import verify_ui
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / name
    create_project(project, "veridian_join_ceiling_plugin", with_ui=False)
    package = project / "src" / "veridian_join_ceiling_plugin"
    (package / "descriptor.json").write_bytes(_raw(descriptor))
    (package / MEMBER_PIN).write_bytes(_raw(_join_declaration()))
    (package / "vendor-catalog.json").write_bytes(
        (FIXTURES / "vendor-catalog.json").read_bytes()
    )
    derived = derive_ui(
        _raw(descriptor), REFERENCE, descriptor_path=package / "descriptor.json"
    )
    ui = package / "ui"
    ui.mkdir()
    (ui / "manifest.json").write_bytes(_raw(derived.manifest))
    (package / "presentation.json").write_bytes(_raw(derived.envelope))
    (package / "binding-catalogue.json").write_bytes(_raw(derived.catalogue))
    settings = ui / "settings"
    settings.mkdir()
    (settings / "configure.schema.json").write_bytes(_raw(derived.settings_schema))
    presets = ui / "presets"
    presets.mkdir()
    for slug, scaffold in derived.preset_scaffolds.items():
        (presets / f"{slug}.json").write_bytes(_raw(scaffold))
    (ui / "class-reference.json").write_bytes(_raw(derived.declaration))
    return derived, verify_ui(project, reference=REFERENCE)


def _capture_plot(derived: Any) -> dict[str, Any]:
    return next(
        plot
        for page in derived.manifest["pages"]
        for plot in (page.get("plots") or [])
        if plot["kind"] == "digital_lanes"
    )


def _capture_dataset(derived: Any) -> dict[str, Any]:
    return next(
        target for target in derived.catalogue["targets"]
        if target["kind"] == "dataset"
    )


def test_a_page_join_past_the_lane_ceiling_drops_and_discloses(
    tmp_path: Path,
) -> None:
    """The boundary at 64 and at 65+ joined lanes, through the real derive
    path: exactly at the ceiling nothing drops and no row appears; one lane
    past it, the plot keeps the first 64 and every dropped lane REPORTs on
    the residual channel. The wire shape keeps every joined lane — dropped
    from the plot alone, the B1 discipline — and no resolves-to-no-lanes
    row fires (every declared channel's role resolved): the dropped lane's
    own row is the disclosure."""
    from benchweave_sdk.classref import _LANE_CEILING

    # Exactly at the ceiling: 32 reference lanes + 32 composed lanes = 64.
    at_ceiling, at_report = _persist(
        tmp_path / "at" / "inner", "gate", _join_descriptor(32)
    )
    plot = _capture_plot(at_ceiling)
    assert len(plot["y"]) == _LANE_CEILING, plot["y"]
    assert plot["y"] == [f"d{i}" for i in range(32)] + [
        f"q{i}" for i in range(32)
    ], plot["y"]
    assert not any(
        row.kind == "composed lane" for row in at_ceiling.residual_members
    ), at_ceiling.residual_members
    assert at_report.clean, [f"{f.code}: {f.detail}" for f in at_report.findings]

    # One lane past it, exactly: 32 + 33 = 65 joined, the 65th drops and
    # reports alone.
    one_past, one_past_report = _persist(
        tmp_path / "one-past" / "inner", "gate", _join_descriptor(33)
    )
    assert one_past_report.clean, [
        f"{f.code}: {f.detail}" for f in one_past_report.findings
    ]
    assert _capture_plot(one_past)["y"] == [f"d{i}" for i in range(32)] + [
        f"q{i}" for i in range(32)
    ], _capture_plot(one_past)["y"]
    assert [
        row.member for row in one_past.residual_members
        if row.kind == "composed lane"
    ] == ["q32 (role digital_output)"], one_past.residual_members

    # Further past it: 32 + 40 = 72 joined, 8 dropped.
    over, report = _persist(
        tmp_path / "over" / "inner", "gate", _join_descriptor(40)
    )
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    plot = _capture_plot(over)
    assert len(plot["y"]) == _LANE_CEILING, plot["y"]
    assert plot["y"] == [f"d{i}" for i in range(32)] + [
        f"q{i}" for i in range(32)
    ], plot["y"]
    assert len(plot["channel_hints"]) == _LANE_CEILING
    dropped = [f"q{i}" for i in range(32, 40)]
    # One row per dropped lane, in the residual wording family, each naming
    # the page, the joined count and the ceiling — the same channel the
    # gate renders "composed lane <member>: <detail>" from.
    rows = [row for row in over.residual_members if row.kind == "composed lane"]
    assert rows == [
        ResidualMember(
            "composed lane",
            "channels and decoders",
            f"{lane} (role {COMPOSED_ROLE})",
            "no lane surface on page capture (the page's channels slots "
            f"join to 72 lanes; the plot's y admits {_LANE_CEILING})",
        )
        for lane in dropped
    ], rows
    assert {
        f"composed lane {lane} (role {COMPOSED_ROLE}): no lane surface on "
        "page capture (the page's channels slots join to 72 lanes; the "
        f"plot's y admits {_LANE_CEILING})"
        for lane in dropped
    } <= set(report.reported_deviations), report.reported_deviations
    # Dropped from the PLOT alone: the capture dataset's wire shape still
    # carries every joined lane — the axis plus all 72.
    capture = _capture_dataset(over)
    assert [row["id"] for row in capture["variables"]] == [
        "t", *[f"d{i}" for i in range(32)], *[f"q{i}" for i in range(40)]
    ], capture["variables"]
    # The roles resolved, so the B1 channel closure stays quiet — the
    # dropped lane's own row is the disclosure, not a second one.
    assert [row for row in over.residual_members if row.kind == "channel"] == []
    assert not any(
        "resolves to no lanes" in row for row in report.reported_deviations
    ), report.reported_deviations
