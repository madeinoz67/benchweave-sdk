"""Issue #541 slice 2: composed action classes (design records
``.claude/deep-review/2026-10-22-issue541-s2-standards-design.md`` §3/§6 and
``.claude/deep-review/2026-10-22-issue541-classref-composition.md`` §3 layer 2).

Layer 2 of the three-layer resolution: a pinned, digest-verified document
carrying ``urn`` and ``claims`` supplies the catalogue side of the
derivation for the URNs it claims. Two sources, one resolver — the
plugin-package source rides the existing ``descriptor.contracts[]`` pin
seam, the same seam the vendor catalogs ride, so every arm in this file
IS the plugin-local route (a corpus-promoted class is a file move into
the vendored tree, DS4, and has no separate discovery step yet).

The arms follow the records: M3's composed leg (three distinct outcomes
for one URN), the conflict refusals (§8 — refuse, never merge), the
side_effect direction rule (S20 applied at the class layer) feeding the
gate's D7 arms (§6), and the dialect-decoupling structural check (§10 A4,
SDK-side parity over the vendored bytes).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.classref import (
    derive_ui,
    find_reference,
    validate_declaration,
)
from benchweave_sdk.served import active_version

FIXTURES = Path(__file__).parent / "fixtures" / "classref"
REFERENCE = find_reference("otdp.logic_analyser/1.0.0")

#: The composed-leg action URN. It is action-urn-shaped (the claims items
#: pattern admits only ``otdp.<x>.<y>/<semver>`` — a hyphenated vendor URN
#: cannot be claimed), invented, and described by no served catalog row —
#: asserted below so the custom leg of the three-outcome proof is honest.
STAGE_URN = "otdp.veridian_staging.ghost_stage/1.0.0"
STAGE_SLUG = "ghost_stage"
CLASS_URN = "otdp.action.veridian_staging/1.0.0"

#: The slice-1 residual URN, whose vendor-catalog coverage pins the
#: "catalog" leg. It is deliberately NOT claimable (hyphenated namespace):
#: the three-outcome proof runs on STAGE_URN, which can travel all three
#: layers.
SERVED_VENDOR_URN = "com.veridian-labs.auto-threshold/1.0.0"


def _raw(document: object) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _stage_action(
    side_effect: str = "state_change",
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A descriptor action row for the composed-leg fixture action."""
    return {
        "binding": {"kind": "adapter", "key": "ghost_stage"},
        "input_constraints": constraints or {},
        "timeout_ms": 1000,
        "side_effect": side_effect,
        "cancellable": True,
        "retry": "never",
    }


def _composed_pin(path: str, document: dict[str, Any]) -> dict[str, Any]:
    """A descriptor contracts[] row pinning a composed class document."""
    return {
        "id": "urn:veridian:composed-staging:1.0.0",
        "path": path,
        "sha256": hashlib.sha256(_raw(document)).hexdigest(),
    }


def _composed_document(
    *,
    urn: str = CLASS_URN,
    claims: list[str] | None = None,
    side_effect: str = "state_change",
    input_schema: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """The fixture composed class, overridable per arm. ``extra`` merges
    into the document (the ambiguity arm adds an ``actions`` key)."""
    document: dict[str, Any] = {
        "contract_version": "0.1.0",
        "urn": urn,
        "title": "Veridian numeric staging",
        "claims": claims if claims is not None else [STAGE_URN],
        "input_schema": input_schema
        if input_schema is not None
        else json.loads(
            (FIXTURES / "composed-staging.json").read_bytes()
        )["input_schema"],
        "side_effect": side_effect,
    }
    document.update(extra)
    return document


def _pinned_descriptor(
    *,
    side_effect: str = "state_change",
    constraints: dict[str, Any] | None = None,
    document: dict[str, Any] | None = None,
    extra_pins: list[dict[str, Any]] | None = None,
    vendor_actions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The f1 descriptor plus the staging action and its composed pin.

    With ``document=None`` the arm uses the committed fixture bytes (the
    pin digest computed over them); otherwise the caller has already
    written ``document`` beside the descriptor in a scratch project.
    """
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["actions"][STAGE_URN] = _stage_action(side_effect, constraints)
    pins: list[dict[str, Any]] = []
    if document is None:
        digest = hashlib.sha256(
            (FIXTURES / "composed-staging.json").read_bytes()
        ).hexdigest()
        pins.append(
            {
                "id": "urn:veridian:composed-staging:1.0.0",
                "path": "composed-staging.json",
                "sha256": digest,
            }
        )
    else:
        pins.append(_composed_pin("composed-staging.json", document))
    if extra_pins:
        pins.extend(extra_pins)
    if vendor_actions is not None:
        catalog = json.loads((FIXTURES / "vendor-catalog.json").read_bytes())
        catalog["actions"].update(vendor_actions)
        pins.append(
            {
                "id": "urn:veridian:vendor-catalog:2.0.0",
                "path": "vendor-catalog-2.json",
                "sha256": hashlib.sha256(_raw(catalog)).hexdigest(),
            }
        )
    descriptor["contracts"].extend(pins)
    return descriptor


def _derive(
    descriptor: dict[str, Any], descriptor_path: Path
) -> Any:
    return derive_ui(
        _raw(descriptor), REFERENCE, descriptor_path=descriptor_path
    )


def _scratch(
    destination: Path,
    *,
    documents: dict[str, dict[str, Any]],
    descriptor: dict[str, Any],
) -> Path:
    """A scratch project directory: the descriptor plus every named pinned
    document written beside it (digests already computed by the caller).
    The f1 descriptor's own vendor-catalog pin must resolve here too."""
    destination.mkdir(parents=True, exist_ok=True)
    for name, document in documents.items():
        (destination / name).write_bytes(_raw(document))
    (destination / "vendor-catalog.json").write_bytes(
        (FIXTURES / "vendor-catalog.json").read_bytes()
    )
    descriptor_path = destination / "descriptor.json"
    descriptor_path.write_bytes(_raw(descriptor))
    return descriptor_path


# ---------------------------------------------------------------------------
# M3's composed leg closes: three distinct outcomes for one URN, all three
# asserted on this branch (record §7.3's leg-ownership note).
# ---------------------------------------------------------------------------


def test_served_catalogs_do_not_describe_the_stage_urn() -> None:
    """The custom leg's honesty premise, asserted from the mechanism: no
    served OTDP row and no f1 vendor-catalog row describes STAGE_URN."""
    from benchweave_sdk.classref import _catalog_documents

    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    catalog = _catalog_documents(descriptor)
    assert STAGE_URN not in (catalog.get("actions") or {})
    vendor = json.loads((FIXTURES / "vendor-catalog.json").read_bytes())
    assert STAGE_URN not in vendor.get("actions", {})


def test_composed_claim_resolves_layer_two() -> None:
    """A pinned document carrying urn+claims supplies the catalogue side:
    the claimed, descriptor-declared action derives with resolution
    "composed", the class URN (which carries its version) on the row, and
    the class's declared side_effect beside it (record §6)."""
    descriptor = _pinned_descriptor()
    derived = _derive(descriptor, FIXTURES / "descriptor-f1.json")
    row = derived.control_plan[STAGE_URN]
    assert row["resolution"] == "composed"
    assert row["class"] == CLASS_URN
    assert row["side_effect"] == "state_change"
    # The class supplies the schema, so the ladder reads the class's
    # required set: stage_level required and expressible -> L2.
    assert row["level"] == "L2"
    by_field = {field["field"]: field for field in row["fields"]}
    assert by_field["stage_level"]["mode"] == "numeric"
    assert by_field["stage_level"]["minimum"] == 0.0
    assert by_field["stage_level"]["maximum"] == 10.0


def test_m3_one_urn_three_outcomes(tmp_path: Path) -> None:
    """M3 complete (record §7.3): the same URN derives "custom" with no
    catalogue side, "composed" when a plugin-local class claims it, and
    "catalog" when a pinned vendor catalog describes it — three distinct
    outcomes for one URN, each asserted through the real derivation."""
    # custom: declared, described by nothing.
    custom_descriptor = _pinned_descriptor()
    del custom_descriptor["contracts"][-1]  # drop the composed pin
    custom = _derive(custom_descriptor, FIXTURES / "descriptor-f1.json")
    assert custom.control_plan[STAGE_URN]["resolution"] == "custom"
    # composed: the class claims it.
    composed = _derive(_pinned_descriptor(), FIXTURES / "descriptor-f1.json")
    assert composed.control_plan[STAGE_URN]["resolution"] == "composed"
    # catalog: a pinned vendor catalog describes it (claim-free descriptor).
    catalog = json.loads((FIXTURES / "vendor-catalog.json").read_bytes())
    catalog["actions"][STAGE_URN] = {
        "description": "Pinned staging twin.",
        "input_schema": json.loads(
            (FIXTURES / "composed-staging.json").read_bytes()
        )["input_schema"],
        "side_effect": "none",
    }
    vendor_descriptor = _pinned_descriptor()
    del vendor_descriptor["contracts"][-1]  # drop the composed pin
    vendor_descriptor["contracts"].append(
        {
            "id": "urn:veridian:vendor-catalog:2.0.0",
            "path": "vendor-catalog-2.json",
            "sha256": hashlib.sha256(_raw(catalog)).hexdigest(),
        }
    )
    vendor_path = _scratch(
        tmp_path / "catalog-leg",
        documents={"vendor-catalog-2.json": catalog},
        descriptor=vendor_descriptor,
    )
    catalog_leg = _derive(vendor_descriptor, vendor_path)
    assert catalog_leg.control_plan[STAGE_URN]["resolution"] == "catalog"
    # Three DISTINCT outcomes — the layers are distinguishable.
    assert len(
        {
            custom.control_plan[STAGE_URN]["resolution"],
            composed.control_plan[STAGE_URN]["resolution"],
            catalog_leg.control_plan[STAGE_URN]["resolution"],
        }
    ) == 3


def test_composed_input_schema_narrows_under_descriptor_constraints() -> None:
    """D13 runs unchanged on the composed side (record §6): the descriptor's
    constraints NARROW the class's input_schema — the class floor survives,
    the constraint ceiling wins. In the residual mode the constraint alone
    carries no floor, so this row shape distinguishes the layers."""
    descriptor = _pinned_descriptor(
        constraints={
            "properties": {
                "stage_level": {"type": "number", "maximum": 5.0},
            },
        }
    )
    derived = _derive(descriptor, FIXTURES / "descriptor-f1.json")
    row = derived.control_plan[STAGE_URN]
    assert row["resolution"] == "composed"
    stage = {field["field"]: field for field in row["fields"]}["stage_level"]
    assert stage["minimum"] == 0.0  # the class side supplies the floor
    assert stage["maximum"] == 5.0  # the tighter constraint ceiling wins


def test_composed_narrowing_to_empty_refuses(tmp_path: Path) -> None:
    """The §8 survivor holds on the composed side: a class enum narrowed by
    a constraint enum to nothing refuses ``classref_effective_schema_empty``
    (D13 unchanged — layer 2 never launders an empty admittance)."""
    document = _composed_document(
        input_schema={
            "type": "object",
            "properties": {
                "stage_mode": {
                    "type": "string",
                    "enum": ["sweep", "step"],
                }
            },
            "required": ["stage_mode"],
        }
    )
    descriptor = _pinned_descriptor(
        document=document,
        constraints={
            "properties": {
                "stage_mode": {"type": "string", "enum": ["pulse"]},
            },
        },
    )
    descriptor_path = _scratch(
        tmp_path / "empty", documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    with pytest.raises(ValueError, match="^classref_effective_schema_empty:"):
        _derive(descriptor, descriptor_path)


def test_claim_of_undeclared_urn_derives_and_does_not_apply(
    tmp_path: Path,
) -> None:
    """A claim naming an URN the descriptor does not declare is not a
    refusal (record §3 — a corpus-promoted class legitimately claims URNs
    across many plugins); it simply does not apply here."""
    document = _composed_document(
        claims=["otdp.veridian_staging.unrelated/1.0.0", STAGE_URN]
    )
    descriptor = _pinned_descriptor(document=document)
    descriptor["actions"].pop(STAGE_URN)
    descriptor_path = _scratch(
        tmp_path / "undeclared",
        documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    derived = _derive(descriptor, descriptor_path)
    assert "otdp.veridian_staging.unrelated/1.0.0" not in derived.control_plan


# ---------------------------------------------------------------------------
# The refusals (record §8 — conflicts refuse, never merge; the shape
# refusals mirror classref_invalid_reference).
# ---------------------------------------------------------------------------


def test_schema_invalid_composed_class_refuses(tmp_path: Path) -> None:
    """A declaration whose side_effect is outside the closed set is
    schema-invalid and refuses ``classref_invalid_composed_class``."""
    document = _composed_document(side_effect="configuration_write")
    descriptor = _pinned_descriptor(document=document)
    descriptor_path = _scratch(
        tmp_path / "invalid",
        documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    with pytest.raises(ValueError, match="^classref_invalid_composed_class:"):
        _derive(descriptor, descriptor_path)


def test_ambiguous_pin_refuses(tmp_path: Path) -> None:
    """A document carrying BOTH vendor-catalog ``actions`` and composed
    ``urn``/``claims`` keys is an ambiguous pin and refuses the same code
    (record §6 discovery)."""
    document = _composed_document(
        actions={"otdp.veridian_staging.ghost_stage/1.0.0": {"side_effect": "none"}}
    )
    descriptor = _pinned_descriptor(document=document)
    descriptor_path = _scratch(
        tmp_path / "ambiguous",
        documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    with pytest.raises(ValueError, match="^classref_invalid_composed_class:"):
        _derive(descriptor, descriptor_path)


def test_claim_conflict_against_served_catalog_row(tmp_path: Path) -> None:
    """A claim naming an URN a served OTDP catalog row already describes
    refuses ``classref_composed_claim_conflict`` — sort order never picks
    a winner."""
    document = _composed_document(claims=["otdp.logic_analyser.arm/1.0.0"])
    descriptor = _pinned_descriptor(document=document)
    descriptor_path = _scratch(
        tmp_path / "served-conflict",
        documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    with pytest.raises(ValueError, match="^classref_composed_claim_conflict:"):
        _derive(descriptor, descriptor_path)


def test_claim_conflict_against_pinned_vendor_catalog_row(
    tmp_path: Path,
) -> None:
    """A claim naming an URN a PINNED vendor catalog describes is the same
    conflict — the catalogue side is the served set plus every pinned
    actions map."""
    document = _composed_document(claims=["otdp.veridian_staging.primed/1.0.0"])
    catalog = json.loads((FIXTURES / "vendor-catalog.json").read_bytes())
    catalog["actions"]["otdp.veridian_staging.primed/1.0.0"] = {
        "description": "Pinned twin.",
        "input_schema": {"type": "object"},
        "side_effect": "none",
    }
    descriptor = _pinned_descriptor(document=document)
    descriptor["contracts"].append(
        {
            "id": "urn:veridian:vendor-catalog:2.0.0",
            "path": "vendor-catalog-2.json",
            "sha256": hashlib.sha256(_raw(catalog)).hexdigest(),
        }
    )
    descriptor_path = _scratch(
        tmp_path / "vendor-conflict",
        documents={
            "composed-staging.json": document,
            "vendor-catalog-2.json": catalog,
        },
        descriptor=descriptor,
    )
    with pytest.raises(ValueError, match="^classref_composed_claim_conflict:"):
        _derive(descriptor, descriptor_path)


def test_claim_conflict_two_classes_one_urn(tmp_path: Path) -> None:
    """Two classes claiming one URN refuse — never a merge (record §8)."""
    first = _composed_document()
    second = _composed_document(
        urn="otdp.action.veridian_staging_alt/1.0.0",
        title="Veridian numeric staging (alt)",
    )
    descriptor = _pinned_descriptor(document=first)
    descriptor["contracts"].append(
        {
            "id": "urn:veridian:composed-staging-alt:1.0.0",
            "path": "composed-staging-alt.json",
            "sha256": hashlib.sha256(_raw(second)).hexdigest(),
        }
    )
    descriptor_path = _scratch(
        tmp_path / "two-classes",
        documents={
            "composed-staging.json": first,
            "composed-staging-alt.json": second,
        },
        descriptor=descriptor,
    )
    with pytest.raises(ValueError, match="^classref_composed_claim_conflict:"):
        _derive(descriptor, descriptor_path)


def test_same_class_urn_in_two_pins_refuses(tmp_path: Path) -> None:
    """Two pinned documents carrying one class urn refuse — the ledger and
    the plan row cannot name which document is the class."""
    first = _composed_document()
    second = _composed_document(title="Veridian numeric staging (twin)")
    descriptor = _pinned_descriptor(document=first)
    descriptor["contracts"].append(
        {
            "id": "urn:veridian:composed-staging-twin:1.0.0",
            "path": "composed-staging-twin.json",
            "sha256": hashlib.sha256(_raw(second)).hexdigest(),
        }
    )
    descriptor_path = _scratch(
        tmp_path / "twin-urn",
        documents={
            "composed-staging.json": first,
            "composed-staging-twin.json": second,
        },
        descriptor=descriptor,
    )
    with pytest.raises(ValueError, match="^classref_composed_claim_conflict:"):
        _derive(descriptor, descriptor_path)


def test_side_effect_under_classification_refuses(tmp_path: Path) -> None:
    """S20 at the class layer (record §3): a class declaring ``none`` under
    a descriptor action declaring ``state_change`` under-classifies and
    refuses ``classref_composed_side_effect_under``."""
    document = _composed_document(side_effect="none")
    descriptor = _pinned_descriptor(
        document=document, side_effect="state_change"
    )
    descriptor_path = _scratch(
        tmp_path / "under",
        documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    with pytest.raises(ValueError, match="^classref_composed_side_effect_under:"):
        _derive(descriptor, descriptor_path)


def test_side_effect_over_classification_is_legal(tmp_path: Path) -> None:
    """The S20 direction's legal side: ``energy_removing`` over a descriptor
    ``state_change`` derives — over-classification is conservative
    protection on a vendor-declared axis, never a refusal."""
    document = _composed_document(side_effect="energy_removing")
    descriptor = _pinned_descriptor(
        document=document, side_effect="state_change"
    )
    descriptor_path = _scratch(
        tmp_path / "over",
        documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    derived = _derive(descriptor, descriptor_path)
    row = derived.control_plan[STAGE_URN]
    assert row["resolution"] == "composed"
    assert row["side_effect"] == "energy_removing"


# ---------------------------------------------------------------------------
# side_effect feeds the gate's arms (record §6): the D7 set widens by
# declaration — {abort-slug actions} ∪ {actions whose class declares
# energy_removing} — with no refusal code changes.
# ---------------------------------------------------------------------------


def _derived_energy_project(tmp_path: Path) -> tuple[Any, dict[str, Any]]:
    """A derivation whose composed class declares energy_removing."""
    document = _composed_document(side_effect="energy_removing")
    descriptor = _pinned_descriptor(
        document=document, side_effect="state_change"
    )
    descriptor_path = _scratch(
        tmp_path / "energy",
        documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    return _derive(descriptor, descriptor_path), descriptor


def test_energy_removing_deviation_refuses(tmp_path: Path) -> None:
    """A deviation naming an action whose class declares energy_removing
    refuses ``classref_deviation_forbidden`` — the declared value puts the
    action into the D7 set (never downgraded, like the abort class)."""
    derived, _descriptor = _derived_energy_project(tmp_path / "d7")
    ledger = {
        "deviations": [
            {
                "expectation_id": STAGE_URN,
                "reason": "an attempt to launder the reachability",
            }
        ]
    }
    with pytest.raises(ValueError, match="^classref_deviation_forbidden:"):
        validate_declaration(derived, ledger)


def test_energy_removing_intermediated_control_reds(tmp_path: Path) -> None:
    """The forbid arm's intermediated check (``intermediated-energy-
    removing-action``) consumes the declaration: a numeric control staged
    on an energy-removing-declared action's binding is forbidden exactly
    as the abort class's is — the slug guess is replaced where a
    declaration is present."""
    from benchweave_sdk.classref import LAYOUT_EXTENSION_KEY
    from benchweave_sdk.classref_gate import _forbid_findings

    derived, descriptor = _derived_energy_project(tmp_path / "forbid")
    manifest = {
        "pages": [],
        "extensions": {
            LAYOUT_EXTENSION_KEY: {
                "pages": [
                    {
                        "page_id": "device-features",
                        "sections": [
                            {
                                "id": "device-features-section",
                                "children": [
                                    {
                                        "binding_id": STAGE_SLUG,
                                        "kind": "numeric",
                                        "field": "stage_level",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        },
    }
    findings = _forbid_findings(manifest, descriptor, derived.control_plan)
    assert any(
        finding.code == "classref_gate_forbidden"
        and "intermediated-energy-removing-action" in finding.detail
        for finding in findings
    ), [f"{f.code}: {f.detail}" for f in findings]


def test_energy_removing_class_passes_the_real_gate(tmp_path: Path) -> None:
    """The widened D7 set does not break the happy path: a real project
    whose composed class declares energy_removing derives, renders and
    passes the gate clean — with the HONEST energy-removing shape, a bare
    button (L1). A class declaring energy_removing WITH required numeric
    inputs derives the staging the forbid arm reds; that conservative
    cost is the S20 direction taken deliberately (standards record §13
    risk 2), never a silent derivation."""
    from benchweave_sdk.classref import declaration_scaffold
    from benchweave_sdk.classref_gate import verify_ui
    from benchweave_sdk.scaffold import create_project

    document = _composed_document(
        side_effect="energy_removing",
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
            "$id": "urn:veridian:action:staging:1.0.0:input",
        },
    )
    descriptor = _pinned_descriptor(
        document=document, side_effect="state_change"
    )
    project = tmp_path / "gate-project"
    create_project(project, "veridian_composed_plugin", with_ui=False)
    package = project / "src" / "veridian_composed_plugin"
    (package / "composed-staging.json").write_bytes(_raw(document))
    for pinned in ("vendor-catalog.json", "vectors-f1.json"):
        (package / pinned).write_bytes((FIXTURES / pinned).read_bytes())
    descriptor_path = package / "descriptor.json"
    descriptor_path.write_bytes(_raw(descriptor))
    derived = _derive(descriptor, descriptor_path)
    ui = package / "ui"
    ui.mkdir(exist_ok=True)
    (ui / "manifest.json").write_bytes(_raw(derived.manifest))
    (package / "presentation.json").write_bytes(_raw(derived.envelope))
    (package / "binding-catalogue.json").write_bytes(_raw(derived.catalogue))
    settings = ui / "settings"
    settings.mkdir(exist_ok=True)
    (settings / "configure.schema.json").write_bytes(_raw(derived.settings_schema))
    presets = ui / "presets"
    presets.mkdir(exist_ok=True)
    for slug, scaffold_row in derived.preset_scaffolds.items():
        (presets / f"{slug}.json").write_bytes(_raw(scaffold_row))
    (ui / "class-reference.json").write_bytes(_raw(declaration_scaffold(derived)))
    report = verify_ui(project)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]


# ---------------------------------------------------------------------------
# The declaration records the composed inventory (record §8.2): the
# ledger's composed rows land beside slice 1's custom rows.
# ---------------------------------------------------------------------------


def test_declaration_inventories_composed_rows() -> None:
    """The birth declaration carries composed_actions rows (action,
    resolution, class) and composed_classes rows (class urn, the family
    version each was validated against) — the records migrate-ui
    re-stamps."""
    descriptor = _pinned_descriptor()
    derived = _derive(descriptor, FIXTURES / "descriptor-f1.json")
    composed_actions = derived.declaration.get("composed_actions")
    assert composed_actions, "composed members must be inventoried"
    assert composed_actions == [
        {"action": STAGE_URN, "resolution": "composed", "class": CLASS_URN}
    ]
    composed_classes = derived.declaration.get("composed_classes")
    assert composed_classes == [
        {
            "class": CLASS_URN,
            "validated_against": active_version(
                "plugin-ui-class-reference"
            ),
        }
    ]


def test_declaration_composed_inventory_empty_without_composed_members() -> None:
    """A derivation with no composed members carries empty inventories —
    the ledger states what is composed from birth, exactly as the custom
    inventory does."""
    derived = derive_ui(
        (FIXTURES / "descriptor-f1.json").read_bytes(), REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f1.json",
    )
    assert derived.declaration.get("composed_actions") == []
    assert derived.declaration.get("composed_classes") == []


# ---------------------------------------------------------------------------
# The corpus schema, SDK-side parity (standards record §10 A4): the
# dialect version is decoupled from the family directory version, pinned
# over the vendored bytes.
# ---------------------------------------------------------------------------


def _vendored_composed_schema() -> tuple[Path, dict[str, Any]]:
    family = active_version("plugin-ui-class-reference")
    path = (
        Path(__file__).parents[1]
        / "src/benchweave_sdk/standards/plugin-ui-class-reference"
        / family
        / "composed-action-class.schema.json"
    )
    return path, json.loads(path.read_bytes())


def test_vendored_composed_schema_dialect_decoupling() -> None:
    """Over the vendored schema bytes: the dialect version occurs exactly
    twice (title, const) and the family version exactly twice ($id, the
    claims $ref) — a family re-stamp touches only intra-family lines,
    never the dialect bytes that validate a pinned document."""
    path, schema = _vendored_composed_schema()
    raw = path.read_bytes()
    family = active_version("plugin-ui-class-reference")
    # Unquoted byte forms: the title and $id carry their versions inside
    # JSON strings; the const and the $ref carry them as quoted literals.
    # Both spellings count — the property A4 protects is WHERE the bytes
    # sit (dialect-bearing vs intra-family), not their quoting.
    assert raw.count(b"0.1.0") == 2, raw.count(b"0.1.0")
    assert raw.count(family.encode()) == 2, raw.count(family.encode())
    assert schema["properties"]["contract_version"] == {"const": "0.1.0"}


def test_composed_document_survives_a_family_bump_simulation() -> None:
    """The decoupling is structural: re-stamp ONLY the schema's
    family-bearing bytes to a hypothetical next family version and the
    pinned fixture document still validates (the standards record's A4
    future-bump simulation, run SDK-side)."""
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    path, schema = _vendored_composed_schema()
    family = active_version("plugin-ui-class-reference")
    major = int(family.split(".")[0])
    nxt = f"{major + 1}.0.0"
    raw = path.read_bytes()
    bumped = raw.replace(family.encode(), nxt.encode())
    assert bumped != raw, "the simulation must move the family bytes"
    bumped_schema = json.loads(bumped)

    reference_path = path.with_name("class-reference.schema.json")
    reference = json.loads(
        reference_path.read_bytes().replace(family.encode(), nxt.encode())
    )
    registry = Registry().with_resource(
        str(reference["$id"]), Resource.from_contents(reference)
    )
    document = json.loads((FIXTURES / "composed-staging.json").read_bytes())
    findings = list(
        Draft202012Validator(bumped_schema, registry=registry).iter_errors(
            document
        )
    )
    assert not findings, [finding.message for finding in findings]
    # And the dialect const is untouched by the family re-stamp.
    assert b"configuration_write" not in raw
    assert re.search(rb'"const":\s*"0\.1\.0"', bumped)
