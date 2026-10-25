"""#556 Track B B3: the composed-members ledger and its gate read-back
(design record §3 rules 1-2; the B6/R6 discipline).

``ui/class-reference.json`` gains one inventory key, ``composed_members``
— the APPLIED member set per vocabulary, one writer (the composed-member
walk), no schema governing the key set (the D8 posture). The gate reads
it back BOTH directions AND per-member slot mapping: sets alone were
proved insufficient once already in this family's composed action
classes, so a forged row (a member the derivation applied, named with
the wrong mapping) REPORTS, never verifies clean.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from benchweave_sdk.classref import derive_ui, find_reference
from benchweave_sdk.classref_gate import verify_ui
from benchweave_sdk.scaffold import create_project

FIXTURES = Path(__file__).parent / "fixtures" / "classref"
REFERENCE = find_reference("otdp.logic_analyser/1.0.0")

COMPOSED_ROLE = "digital_output"
MEMBER_PIN = "member-lanes.json"
NOWHERE_PIN = "member-nowhere.json"

CHANNELS_ROW = {
    "slot": "trigger_lanes",
    "where_role": COMPOSED_ROLE,
    "page": "capture",
}


def _raw(document: object) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _channels_declaration() -> dict[str, Any]:
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


def _channels_descriptor() -> dict[str, Any]:
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
    descriptor["contracts"].append(
        {
            "id": "urn:veridian:member-declaration:1.0.0",
            "path": MEMBER_PIN,
            "sha256": hashlib.sha256(_raw(_channels_declaration())).hexdigest(),
        }
    )
    return descriptor


def _build(
    tmp_path: Path,
    *,
    ledger_edits: Any = None,
    descriptor: dict[str, Any] | None = None,
    declaration: dict[str, Any] | None = None,
    pin_name: str = MEMBER_PIN,
) -> Any:
    """A scaffolded project with the composing fixture filled and the
    derived documents written; ``ledger_edits`` (a callable on the
    declaration dict) forges the authored ledger per arm."""
    descriptor = descriptor if descriptor is not None else _channels_descriptor()
    declaration = declaration if declaration is not None else _channels_declaration()
    project = tmp_path / "project"
    create_project(project, "veridian_member_ledger_plugin", with_ui=False)
    package = project / "src" / "veridian_member_ledger_plugin"
    (package / "descriptor.json").write_bytes(_raw(descriptor))
    (package / pin_name).write_bytes(_raw(declaration))
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
    declaration_document = dict(derived.declaration)
    if ledger_edits is not None:
        ledger_edits(declaration_document)
    (ui / "class-reference.json").write_bytes(_raw(declaration_document))
    return project, derived


def test_the_ledger_carries_the_applied_member_set(tmp_path: Path) -> None:
    """The ledger key (#556 §3 rule 2): the birth declaration carries
    ``composed_members`` with every vocabulary's APPLIED set — the same
    rows the derivation's inventory holds, one writer, and a derivation
    with no applied members carries the four empty lists (the key's
    shape is stable, like composed_actions beside it)."""
    _project, derived = _build(tmp_path / "birth")
    assert derived.declaration["composed_members"] == {
        "procedures": [],
        "settings": [],
        "datasets": [],
        "channels": [dict(CHANNELS_ROW)],
    }
    plain = derive_ui(
        (FIXTURES / "descriptor-f1.json").read_bytes(),
        REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f1.json",
    )
    assert plain.declaration["composed_members"] == {
        "procedures": [],
        "settings": [],
        "datasets": [],
        "channels": [],
    }


def test_the_birth_ledger_verifies_clean(tmp_path: Path) -> None:
    """The untouched birth ledger carries the applied set by construction;
    the read-back is quiet and the gate stays clean."""
    project, _derived = _build(tmp_path / "clean")
    report = verify_ui(project, reference=REFERENCE)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    member_rows = [
        row for row in report.reported_deviations if "composed member" in row
    ]
    assert member_rows == [], report.reported_deviations


def test_a_forged_slot_mapping_reports(tmp_path: Path) -> None:
    """The R6 rule, from birth: sets alone are insufficient — an authored
    row naming the RIGHT slot with the WRONG mapping (a foreign role)
    REPORTs, as does an authored row naming a member the derivation did
    not apply."""
    def forge(document: dict[str, Any]) -> None:
        document["composed_members"]["channels"] = [
            {**CHANNELS_ROW, "where_role": "rf_input"},
            {**CHANNELS_ROW, "slot": "ghost_lanes"},
        ]

    project, _derived = _build(tmp_path / "forged", ledger_edits=forge)
    report = verify_ui(project, reference=REFERENCE)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    joined = " | ".join(report.reported_deviations)
    assert (
        "composed members mismatch: channels member trigger_lanes derives "
        "where_role digital_output but the authored declaration's "
        "composed_members names rf_input" in joined
    ), joined
    assert (
        "composed members mismatch: the authored declaration's "
        "composed_members names channels member ghost_lanes, which the "
        "derivation applied no member for" in joined
    ), joined


def test_an_omitted_applied_member_reports(tmp_path: Path) -> None:
    """The other direction: a ledger that omits an applied member —
    re-derived descriptor, stale authored file — REPORTs the omission."""
    def drop(document: dict[str, Any]) -> None:
        document["composed_members"]["channels"] = []

    project, _derived = _build(tmp_path / "omitted", ledger_edits=drop)
    report = verify_ui(project, reference=REFERENCE)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    assert (
        "composed members mismatch: channels member trigger_lanes derives "
        "applied but the authored declaration's composed_members omits it"
        in " | ".join(report.reported_deviations)
    ), report.reported_deviations


def test_a_dead_member_beside_an_applying_one_reports_per_member(
    tmp_path: Path,
) -> None:
    """(#556 B3 fold F2) The applied-nowhere disclosure is not pin-level
    alone: a members document with one applying member and one dead one
    applied (so the pin-level row stays quiet BY DESIGN) — the dead MEMBER
    reports anyway, naming its slot and the reason. The refute's shape: a
    channels member that applies beside a procedure member claiming an
    undeclared URN."""
    declaration = {
        "contract_version": "0.1.0",
        "members": [
            {
                "slot": "trigger_lanes",
                "kind": "channels",
                "where_role": COMPOSED_ROLE,
                "page": "capture",
            },
            {
                "slot": "ghost_sweep",
                "kind": "procedure",
                "claims": ["com.example.sweep/1.0.0"],
                "page": "capture",
            },
        ],
    }
    descriptor = _channels_descriptor()
    for row in descriptor["contracts"]:
        if row.get("path") == MEMBER_PIN:
            row["sha256"] = hashlib.sha256(_raw(declaration)).hexdigest()
    project, derived = _build(
        tmp_path / "dead-member", descriptor=descriptor, declaration=declaration
    )
    # The applying member lands its row; the dead one stays out of the
    # ledger (the applied-set keying) and out of the pin-level disclosure
    # (the pin applied).
    assert derived.composed_members["channels"] == (dict(CHANNELS_ROW),)
    assert derived.unapplied_member_pins == ()
    assert derived.unapplied_members == (
        (
            MEMBER_PIN,
            "ghost_sweep",
            "its claims name no action this descriptor declares",
        ),
    ), derived.unapplied_members
    report = verify_ui(project, reference=REFERENCE)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    assert (
        f"composed member declaration {MEMBER_PIN} member ghost_sweep "
        "applied nowhere (its claims name no action this descriptor declares)"
        in report.reported_deviations
    ), report.reported_deviations
    # The pin-level row stays quiet exactly when the pin applied.
    assert not any(
        row == f"composed member declaration {MEMBER_PIN} applied nowhere"
        for row in report.reported_deviations
    ), report.reported_deviations


def test_a_dead_channels_member_names_its_role(
    tmp_path: Path,
) -> None:
    """The channels kind's per-member reason names the role (the R1 rule's
    other half): no declared channel carries it."""
    declaration = {
        "contract_version": "0.1.0",
        "members": [
            {
                "slot": "trigger_lanes",
                "kind": "channels",
                "where_role": COMPOSED_ROLE,
                "page": "capture",
            },
            {
                "slot": "empty_lanes",
                "kind": "channels",
                "where_role": "rf_input",
                "page": "capture",
            },
        ],
    }
    descriptor = _channels_descriptor()
    for row in descriptor["contracts"]:
        if row.get("path") == MEMBER_PIN:
            row["sha256"] = hashlib.sha256(_raw(declaration)).hexdigest()
    project, derived = _build(
        tmp_path / "dead-channels", descriptor=descriptor, declaration=declaration
    )
    assert derived.unapplied_members == (
        (MEMBER_PIN, "empty_lanes", "no declared channel carries role rf_input"),
    ), derived.unapplied_members
    report = verify_ui(project, reference=REFERENCE)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    assert (
        f"composed member declaration {MEMBER_PIN} member empty_lanes "
        "applied nowhere (no declared channel carries role rf_input)"
        in report.reported_deviations
    ), report.reported_deviations


def test_an_unknown_ledger_key_under_composed_members_reports(
    tmp_path: Path,
) -> None:
    """(#556 B3 fold F4) The read-back iterated the four vocabularies
    alone, so authored junk under any other key was ignored silently — an
    unknown key REPORTs in the read-back's own mismatch wording, never a
    findings failure (the no-schema-yet posture, D8)."""
    def forge(document: dict[str, Any]) -> None:
        document["composed_members"]["observations"] = [{"slot": "cv1"}]

    project, _derived = _build(tmp_path / "unknown-key", ledger_edits=forge)
    report = verify_ui(project, reference=REFERENCE)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    assert (
        "composed members mismatch: the authored declaration's "
        "composed_members carries key 'observations', which is no composed "
        "vocabulary (procedures, settings, datasets, channels)"
        in " | ".join(report.reported_deviations)
    ), report.reported_deviations


def test_an_applied_nowhere_pin_reports_through_the_gate(tmp_path: Path) -> None:
    """The applied-nowhere row (§3 rule 1): a pin whose members match
    nothing — no channel carries its role — reports every run, never
    drift and never a refusal, on both gate arms."""
    declaration = {
        "contract_version": "0.1.0",
        "members": [
            {
                "slot": "empty_lanes",
                "kind": "channels",
                "where_role": "rf_input",
                "page": "capture",
            }
        ],
    }
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["contracts"].append(
        {
            "id": "urn:veridian:member-nowhere:1.0.0",
            "path": NOWHERE_PIN,
            "sha256": hashlib.sha256(_raw(declaration)).hexdigest(),
        }
    )
    project, _derived = _build(
        tmp_path / "nowhere",
        descriptor=descriptor,
        declaration=declaration,
        pin_name=NOWHERE_PIN,
    )
    report = verify_ui(project, reference=REFERENCE)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    assert (
        f"composed member declaration {NOWHERE_PIN} applied nowhere"
        in report.reported_deviations
    ), report.reported_deviations


def test_the_reference_less_arm_reads_the_ledger_too(tmp_path: Path) -> None:
    """Both arms read the same authored file (the W10 discipline): a
    project whose profile matches no vendored class derives no composed
    member, so every authored composed_members row REPORTs as unapplied —
    never silently green."""
    from benchweave_sdk.presentation import create_ui_resources

    project = tmp_path / "refless"
    create_project(project, "veridian_refless_member_plugin", with_ui=False)
    package = project / "src" / "veridian_refless_member_plugin"
    descriptor = json.loads((package / "descriptor.json").read_bytes())
    declaration = _channels_declaration()
    descriptor.setdefault("contracts", []).append(
        {
            "id": "urn:veridian:member-declaration:1.0.0",
            "path": MEMBER_PIN,
            "sha256": hashlib.sha256(_raw(declaration)).hexdigest(),
        }
    )
    (package / "descriptor.json").write_bytes(_raw(descriptor))
    (package / MEMBER_PIN).write_bytes(_raw(declaration))
    create_ui_resources(project, "veridian_refless_member_plugin")
    # The authored ledger the arm reads back: an applied-set row naming a
    # member the reference-less derivation cannot apply.
    (package / "ui" / "class-reference.json").write_bytes(
        _raw(
            {
                "contract_version": "0.5.0",
                "profile_ids": [],
                "reference_version": "0.5.0",
                "deviations": [],
                "custom_actions": [],
                "composed_actions": [],
                "composed_classes": [],
                "composed_members": {
                    "procedures": [],
                    "settings": [],
                    "datasets": [],
                    "channels": [dict(CHANNELS_ROW)],
                },
            }
        )
    )
    report = verify_ui(project, reference=None)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    assert (
        "composed members mismatch: the authored declaration's "
        "composed_members names channels member trigger_lanes, which the "
        "derivation applied no member for"
        in " | ".join(report.reported_deviations)
    ), report.reported_deviations
