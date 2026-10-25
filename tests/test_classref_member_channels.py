"""#556 Track B B3: channels layer 2 — per-slot lane resolution (design
record §4 V3; the record's M6 byte-stability rule).

``_resolve_channels`` generalizes from "the first channels slot" to
per-slot resolution: every channels slot the merged reference carries —
the reference's own and every APPLIED composed member's injection —
resolves the channels carrying its ``where_role``, and a page's plot
consumes the lanes of the channels slots placed on that page, keeping
the founding default (the first slot) for pages that place none — which
every vendored reference does, so the founding fixtures derive
byte-identically (M6, asserted by digest at the motion's commit; the
one-class-one-channels-slot invariance that makes it hold is asserted
here, in-repo).
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
MEMBER_PIN = "member-lanes.json"


def _raw(document: object) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _channels_descriptor() -> dict[str, Any]:
    """The f1 fixture plus two composed-role channels and the member pin
    that places them on the capture page."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
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
    declaration = {
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
    descriptor["contracts"].append(
        {
            "id": "urn:veridian:member-declaration:1.0.0",
            "path": MEMBER_PIN,
            "sha256": hashlib.sha256(_raw(declaration)).hexdigest(),
        }
    )
    return descriptor


def _scratch(destination: Path, descriptor: dict[str, Any]) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    (destination / MEMBER_PIN).write_bytes(
        _raw(
            {
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
        )
    )
    (destination / "vendor-catalog.json").write_bytes(
        (FIXTURES / "vendor-catalog.json").read_bytes()
    )
    descriptor_path = destination / "descriptor.json"
    descriptor_path.write_bytes(_raw(descriptor))
    return descriptor_path


def _capture_plot(derived: Any) -> dict[str, Any]:
    return next(
        plot
        for page in derived.manifest["pages"]
        for plot in (page.get("plots") or [])
        if plot["kind"] == "digital_lanes"
    )


def test_every_vendored_reference_declares_exactly_one_channels_slot() -> None:
    """M6's structural premise, asserted in-repo: every vendored class
    reference carries exactly ONE channels slot — the founding fixtures'
    byte stability under per-slot resolution holds by construction, and a
    future corpus reference with two channels slots moves THIS arm, not a
    digest."""
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
        channels_slots = [
            key for key, slot in document.get("slots", {}).items()
            if slot.get("kind") == "channels"
        ]
        assert len(channels_slots) == 1, f"{path.name}: {channels_slots}"


def test_composed_channels_lanes_land_on_the_named_pages_plot(
    tmp_path: Path,
) -> None:
    """The composing arm (the record's LA fixture): a member of a second
    digital role, placed on the capture page, composes its lanes into the
    class's digital-lanes plot — the plot's y, its lane groups, its
    channel hints and the capture dataset's wire shape all carry the
    composed lanes, and no channel reports (every declared channel
    resolves AND renders)."""
    descriptor = _channels_descriptor()
    path = _scratch(tmp_path / "composing", descriptor)
    derived = derive_ui(_raw(descriptor), REFERENCE, descriptor_path=path)
    plot = _capture_plot(derived)
    assert plot["y"] == ["d0", "d1", "q0", "q1"], plot["y"]
    assert plot["channel_hints"][2] == {"variable_id": "q0", "visible": True}
    assert [group["id"] for group in plot["lane_groups"]] == ["lanes-1"]
    assert plot["lane_groups"][0]["member_ids"] == ["d0", "d1", "q0", "q1"]
    assert plot["lane_groups"][0]["label"] == "D1-D4"
    capture = next(
        target
        for target in derived.catalogue["targets"]
        if target["kind"] == "dataset"
    )
    assert [row["id"] for row in capture["variables"]] == ["t", "d0", "d1", "q0", "q1"]
    assert derived.composed_members["channels"] == (
        {"slot": "trigger_lanes", "where_role": COMPOSED_ROLE, "page": "capture"},
    )
    assert [row for row in derived.residual_members if row.kind == "channel"] == []
    # The real gate renders it: the census counts the composed lanes on the
    # capture page (four), the derived expectation names four, and the run
    # is clean with zero REPORTED rows — composed lanes are first-class.
    from benchweave_sdk.classref_gate import verify_ui
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "gate-project"
    create_project(project, "veridian_composed_lanes_plugin", with_ui=False)
    package = project / "src" / "veridian_composed_lanes_plugin"
    (package / "descriptor.json").write_bytes(_raw(descriptor))
    for pinned in ("vendor-catalog.json", MEMBER_PIN):
        (package / pinned).write_bytes((path.parent / pinned).read_bytes())
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
    report = verify_ui(project, reference=REFERENCE)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    # The REPORTED channel carries only the fixture's standing birth
    # deviations (the preset surface's A02 row and the decode deviation
    # control) — no channel row, no composed-member row, no applied-
    # nowhere row: composed lanes are not a deviation.
    assert [row for row in report.reported_deviations if "channel" in row] == [], (
        report.reported_deviations
    )
    assert (
        len(report.reported_deviations) == 2
    ), report.reported_deviations


def test_a_composed_member_on_a_plotless_page_renders_no_lanes(
    tmp_path: Path,
) -> None:
    """Lanes render into the named page's plot alone: a member placed on
    the configuration page (no plot) applies — the slot resolves its
    channels — but no lanes surface carries them, so every composed-role
    channel reports ``resolves to no lanes surface`` (the two-sided
    closure: applied is not rendered)."""
    descriptor = _channels_descriptor()
    for row in descriptor["contracts"]:
        if row.get("path") == MEMBER_PIN:
            break
    declaration = {
        "contract_version": "0.1.0",
        "members": [
            {
                "slot": "trigger_lanes",
                "kind": "channels",
                "where_role": COMPOSED_ROLE,
                "page": "configuration",
            }
        ],
    }
    row["sha256"] = hashlib.sha256(_raw(declaration)).hexdigest()
    scratch = tmp_path / "plotless"
    scratch.mkdir(parents=True)
    (scratch / MEMBER_PIN).write_bytes(_raw(declaration))
    (scratch / "vendor-catalog.json").write_bytes(
        (FIXTURES / "vendor-catalog.json").read_bytes()
    )
    descriptor_path = scratch / "descriptor.json"
    descriptor_path.write_bytes(_raw(descriptor))
    derived = derive_ui(_raw(descriptor), REFERENCE, descriptor_path=descriptor_path)
    plot = _capture_plot(derived)
    assert plot["y"] == ["d0", "d1"], plot["y"]
    # The channels RESOLVED (their role matched the composed slot), so
    # B1's channel closure is quiet; the MEMBER's row discloses the
    # applied-but-unrendered placement.
    assert [row for row in derived.residual_members if row.kind == "channel"] == []
    member_rows = [
        row for row in derived.residual_members if row.kind == "composed channels"
    ]
    assert member_rows == [
        ResidualMember(
            "composed channels",
            "channels and decoders",
            "trigger_lanes",
            "no lane host (page configuration hosts no plot; lanes render "
            "into the named page's plot alone)",
        ),
    ], member_rows
