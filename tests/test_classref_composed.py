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

#: The composed-leg action URN. It is action-urn-shaped, invented, and
#: described by no served catalog row — asserted below so the custom leg
#: of the three-outcome proof is honest. Since the owner's 2026-10-23
#: claims widening (any versioned action key — the arms below pin it on a
#: hyphenated vendor URN) the claims pattern no longer excludes vendor
#: shapes; this URN stays ``otdp.``-shaped because the M3 triple needs one
#: URN the served catalogs never describe.
STAGE_URN = "otdp.veridian_staging.ghost_stage/1.0.0"
STAGE_SLUG = "ghost_stage"
CLASS_URN = "otdp.action.veridian_staging/1.0.0"

#: The slice-1 residual URN, whose vendor-catalog coverage pins the
#: "catalog" leg. It IS claimable under the widened claims pattern (the
#: M3 arm below runs the whole three-outcome proof on this URN); the
#: primary triple runs on STAGE_URN, which predates the widening.
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


def _scratch_without_served_vendor(
    destination: Path,
    *,
    documents: dict[str, dict[str, Any]],
    descriptor: dict[str, Any],
) -> Path:
    """A scratch project whose pinned vendor catalog does NOT describe
    SERVED_VENDOR_URN (the row removed, the pin digest recomputed) — the
    fixture shape the widened-claims arms need: a real vendor-namespaced
    URN no catalogue row describes, so a composed class may claim it
    (claiming the fixture catalog's own row would be a claim conflict)."""
    destination.mkdir(parents=True, exist_ok=True)
    for name, document in documents.items():
        (destination / name).write_bytes(_raw(document))
    catalog = json.loads((FIXTURES / "vendor-catalog.json").read_bytes())
    catalog["actions"].pop(SERVED_VENDOR_URN, None)
    raw_catalog = _raw(catalog)
    (destination / "vendor-catalog.json").write_bytes(raw_catalog)
    for row in descriptor["contracts"]:
        if row.get("path") == "vendor-catalog.json":
            row["sha256"] = hashlib.sha256(raw_catalog).hexdigest()
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
    with pytest.raises(ValueError, match="^classref_composed_claim_conflict:") as excinfo:
        _derive(descriptor, descriptor_path)
    # B2 (2026-10-23 fold): the refusal names WHICH side collided — the
    # served OTDP catalog, never a conflated "served or pinned" phrase.
    assert "which the served OTDP catalog describes" in str(excinfo.value)


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
    with pytest.raises(ValueError, match="^classref_composed_claim_conflict:") as excinfo:
        _derive(descriptor, descriptor_path)
    # B2: the pinned side names the DOCUMENT — which pinned catalog
    # describes the claim is known to the walk, so the refusal says it.
    assert "which pinned document vendor-catalog-2.json describes" in str(
        excinfo.value
    )


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
    twice (title, const) and the family version exactly once ($id) — a
    family re-stamp touches only intra-family lines, never the dialect
    bytes that validate a pinned document. The claims ``$ref`` went LOCAL
    in the owner's 2026-10-23 widening (``#/$defs/claimed_action_urn``
    replaces the family-schema ``action_urn`` cross-ref, gateway
    6d633db0), so the family version's second intra-family occurrence
    moved out of this file entirely."""
    path, schema = _vendored_composed_schema()
    raw = path.read_bytes()
    family = active_version("plugin-ui-class-reference")
    # Unquoted byte forms: the title and $id carry their versions inside
    # JSON strings; the const carries its own as a quoted literal.
    # Both spellings count — the property A4 protects is WHERE the bytes
    # sit (dialect-bearing vs intra-family), not their quoting.
    assert raw.count(b"0.1.0") == 2, raw.count(b"0.1.0")
    assert raw.count(family.encode()) == 1, raw.count(family.encode())
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


# ---------------------------------------------------------------------------
# The 2026-10-23 fold wave (review rows B1/B2/B6/B7). Each arm names its
# row; the RED evidence for every arm is quoted in the fold commit's
# message.
# ---------------------------------------------------------------------------


def test_urn_only_pin_contributes_nothing(tmp_path: Path) -> None:
    """B1: a pinned document carrying only ``urn`` (no ``claims``) matches
    neither shape discriminator — the pin contributes nothing and the
    derivation stays clean, the staged action falling to the residual
    layer. The discriminator is AND (the standards record §6 says ``urn``
    PLUS ``claims``); the shipped OR refused this previously accepted pin
    through the composed schema's required set."""
    document = _composed_document()
    del document["claims"]
    descriptor = _pinned_descriptor(document=document)
    descriptor_path = _scratch(
        tmp_path / "urn-only",
        documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    derived = _derive(descriptor, descriptor_path)
    row = derived.control_plan[STAGE_URN]
    assert row["resolution"] == "custom"
    assert "class" not in row
    # The ignored pin is disclosed (B7), never dropped silently.
    assert derived.ignored_pins == ("composed-staging.json",)


def test_claims_only_pin_contributes_nothing(tmp_path: Path) -> None:
    """B1's mirrored arm: ``claims`` without ``urn`` is not a composed
    class either — same contribution-nothing outcome, same disclosure.
    These two arms are the first to pin the AND semantics (switching
    OR->AND left all 21 composed tests green, so nothing else did)."""
    document = _composed_document()
    del document["urn"]
    descriptor = _pinned_descriptor(document=document)
    descriptor_path = _scratch(
        tmp_path / "claims-only",
        documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    derived = _derive(descriptor, descriptor_path)
    row = derived.control_plan[STAGE_URN]
    assert row["resolution"] == "custom"
    assert "class" not in row
    assert derived.ignored_pins == ("composed-staging.json",)


def test_widened_claims_admit_slice1_vendor_urn(tmp_path: Path) -> None:
    """The owner's 2026-10-23 ruling (gateway 6d633db0): claims admit ANY
    versioned action key. SERVED_VENDOR_URN — slice 1's own fixture URN,
    and the shape the first cut's ``action_urn`` cross-ref refused — now
    claims: the class is the only catalogue side (this project's pinned
    vendor catalog does not describe the URN), and the row derives
    composed with the class and its declared side_effect recorded."""
    document = _composed_document(claims=[SERVED_VENDOR_URN])
    descriptor = _pinned_descriptor(document=document)
    descriptor["actions"].pop(STAGE_URN)
    descriptor["actions"][SERVED_VENDOR_URN] = _stage_action()
    descriptor_path = _scratch_without_served_vendor(
        tmp_path / "vendor-urn",
        documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    derived = _derive(descriptor, descriptor_path)
    row = derived.control_plan[SERVED_VENDOR_URN]
    assert row["resolution"] == "composed"
    assert row["class"] == CLASS_URN
    assert row["side_effect"] == "state_change"


def test_m3_three_outcomes_on_a_vendor_namespaced_urn(
    tmp_path: Path,
) -> None:
    """M3 re-run on the shape that used to be impossible (the fold
    instruction): SERVED_VENDOR_URN travels all three layers — custom
    when nothing covers it, composed when the class claims it, catalog
    when the pinned vendor catalog describes it. Three distinct
    resolutions for one vendor-namespaced URN, each through the real
    derivation."""
    # custom: no composed pin, and the pinned catalog does not carry the row.
    custom_descriptor = _pinned_descriptor()
    del custom_descriptor["contracts"][-1]  # drop the composed pin
    custom_descriptor["actions"].pop(STAGE_URN)
    custom_descriptor["actions"][SERVED_VENDOR_URN] = _stage_action()
    custom_path = _scratch_without_served_vendor(
        tmp_path / "vendor-custom",
        documents={},
        descriptor=custom_descriptor,
    )
    custom = _derive(custom_descriptor, custom_path)
    assert custom.control_plan[SERVED_VENDOR_URN]["resolution"] == "custom"
    # composed: the class claims it (the arm above, restated for the triple).
    composed_descriptor = _pinned_descriptor(
        document=_composed_document(claims=[SERVED_VENDOR_URN])
    )
    composed_descriptor["actions"].pop(STAGE_URN)
    composed_descriptor["actions"][SERVED_VENDOR_URN] = _stage_action()
    composed_path = _scratch_without_served_vendor(
        tmp_path / "vendor-composed",
        documents={
            "composed-staging.json": _composed_document(
                claims=[SERVED_VENDOR_URN]
            )
        },
        descriptor=composed_descriptor,
    )
    composed = _derive(composed_descriptor, composed_path)
    assert composed.control_plan[SERVED_VENDOR_URN]["resolution"] == "composed"
    # catalog: the UNMODIFIED fixture vendor catalog describes it.
    catalog_descriptor = _pinned_descriptor()
    del catalog_descriptor["contracts"][-1]  # drop the composed pin
    catalog_descriptor["actions"].pop(STAGE_URN)
    catalog_descriptor["actions"][SERVED_VENDOR_URN] = _stage_action()
    catalog_leg = _derive(
        catalog_descriptor, FIXTURES / "descriptor-f1.json"
    )
    assert catalog_leg.control_plan[SERVED_VENDOR_URN]["resolution"] == "catalog"
    assert len(
        {
            custom.control_plan[SERVED_VENDOR_URN]["resolution"],
            composed.control_plan[SERVED_VENDOR_URN]["resolution"],
            catalog_leg.control_plan[SERVED_VENDOR_URN]["resolution"],
        }
    ) == 3


def test_unversioned_claim_still_refuses(tmp_path: Path) -> None:
    """The boundary the widening kept (N6's disposition keeps this arm
    SDK-side): a claim with no version suffix is not a versioned action
    key and refuses ``classref_invalid_composed_class`` — the permissive
    side is pinned by the two arms above; the floor is pinned here."""
    document = _composed_document(claims=["set_trigger_position"])
    descriptor = _pinned_descriptor(document=document)
    descriptor_path = _scratch(
        tmp_path / "unversioned",
        documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    with pytest.raises(
        ValueError, match="^classref_invalid_composed_class:"
    ):
        _derive(descriptor, descriptor_path)


def test_vendor_catalog_row_cannot_smuggle_composed_provenance(
    tmp_path: Path,
) -> None:
    """N2 (2026-10-23 fold): a pinned vendor-catalog action row carrying
    a stray ``composed_class`` key is NOT composed — the composed walk is
    the only writer of that provenance. Pre-fix, the row laundered
    resolution "composed" (and its ``side_effect`` into the D7-feeding
    plan row) with no class document ever being validated; the fold
    strips the key at the vendor-catalog merge so the smuggled label is
    structurally unreadable."""
    catalog = json.loads((FIXTURES / "vendor-catalog.json").read_bytes())
    catalog["actions"][STAGE_URN] = {
        "description": "Smuggled provenance.",
        "input_schema": json.loads(
            (FIXTURES / "composed-staging.json").read_bytes()
        )["input_schema"],
        "side_effect": "energy_removing",
        "composed_class": "otdp.action.veridian_smuggled/1.0.0",
    }
    descriptor = _pinned_descriptor()
    del descriptor["contracts"][-1]  # no composed pin — the catalog is the only carrier
    descriptor["contracts"].append(
        {
            "id": "urn:veridian:vendor-catalog:2.0.0",
            "path": "vendor-catalog-2.json",
            "sha256": hashlib.sha256(_raw(catalog)).hexdigest(),
        }
    )
    descriptor_path = _scratch(
        tmp_path / "smuggle",
        documents={"vendor-catalog-2.json": catalog},
        descriptor=descriptor,
    )
    derived = _derive(descriptor, descriptor_path)
    row = derived.control_plan[STAGE_URN]
    assert row["resolution"] == "catalog"
    assert "class" not in row
    # The smuggled side_effect did not ride the key into the D7-feeding row.
    assert "side_effect" not in row


def test_ignored_pin_is_disclosed_and_the_reason_names_it(
    tmp_path: Path,
) -> None:
    """B7: a pinned document satisfying NEITHER shape discriminator is
    digest-verified then contributes nothing — that drop is disclosed on
    the derivation (``ignored_pins``), and the ledger's custom reason
    names the pin instead of presenting the descriptor's emptiness as
    the whole cause (the vendor's pinned, digest-verified document may
    declare exactly the schema the reason says nobody did)."""
    document = {
        "title": "Veridian numeric staging (wrong shape)",
        "input_schema": json.loads(
            (FIXTURES / "composed-staging.json").read_bytes()
        )["input_schema"],
    }
    descriptor = _pinned_descriptor(document=document, constraints=None)
    descriptor["actions"][STAGE_URN]["input_constraints"] = {}
    descriptor_path = _scratch(
        tmp_path / "ignored",
        documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    derived = _derive(descriptor, descriptor_path)
    assert derived.ignored_pins == ("composed-staging.json",)
    row = derived.control_plan[STAGE_URN]
    assert row["resolution"] == "custom"
    reason = next(
        item["reason"]
        for item in derived.declaration["custom_actions"]
        if item["action"] == STAGE_URN
    )
    assert "pinned document composed-staging.json contributed nothing" in reason


def test_ignored_pin_reports_through_the_gate(tmp_path: Path) -> None:
    """B7's gate surface: the ignored pin's disclosure reaches
    ``GateReport.reported_deviations`` every run — REPORTED, never a
    findings failure and never silent."""
    from benchweave_sdk.classref import declaration_scaffold
    from benchweave_sdk.classref_gate import verify_ui
    from benchweave_sdk.scaffold import create_project

    document = {
        "title": "Veridian numeric staging (wrong shape)",
        "input_schema": json.loads(
            (FIXTURES / "composed-staging.json").read_bytes()
        )["input_schema"],
    }
    descriptor = _pinned_descriptor(document=document)
    descriptor["actions"][STAGE_URN]["input_constraints"] = {}
    project = tmp_path / "ignored-gate"
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
    assert any(
        row == "pinned document composed-staging.json contributed nothing"
        for row in report.reported_deviations
    ), report.reported_deviations


def test_non_object_pin_refuses_typed(tmp_path: Path) -> None:
    """B7: a pin whose bytes are not a JSON object refuses typed
    (``classref_vendor_catalog_invalid``) — the pre-fold walk crashed on a
    bare ``TypeError`` (``"urn" in 1.5``), which is not an SDK error face.
    The refusal stays a refusal; the ignored-pin disclosure is for shape-
    recognized objects only."""
    project = tmp_path / "non-object"
    project.mkdir(parents=True)
    raw_list = b'["not", "an", "object"]\n'
    (project / "composed-staging.json").write_bytes(raw_list)
    (project / "vendor-catalog.json").write_bytes(
        (FIXTURES / "vendor-catalog.json").read_bytes()
    )
    descriptor = _pinned_descriptor()
    for row in descriptor["contracts"]:
        if row["path"] == "composed-staging.json":
            row["sha256"] = hashlib.sha256(raw_list).hexdigest()
    descriptor_path = project / "descriptor.json"
    descriptor_path.write_bytes(_raw(descriptor))
    with pytest.raises(
        ValueError, match="^classref_vendor_catalog_invalid:"
    ):
        _derive(descriptor, descriptor_path)


# --- B6: the composed inventory is read back (the W10 mirror) -------------


def _composed_gate_project(tmp_path: Path) -> Any:
    """A real scaffolded project whose composed class resolves and whose
    birth ledger carries the composed rows (the read-back input)."""
    from benchweave_sdk.classref import declaration_scaffold
    from benchweave_sdk.scaffold import create_project

    descriptor = _pinned_descriptor()
    project = tmp_path
    create_project(project, "veridian_composed_plugin", with_ui=False)
    package = project / "src" / "veridian_composed_plugin"
    for pinned in ("composed-staging.json", "vendor-catalog.json", "vectors-f1.json"):
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
    return project, package


def _tamper_ledger(package: Path, mutate: Any) -> None:
    ledger_path = package / "ui" / "class-reference.json"
    ledger = json.loads(ledger_path.read_bytes())
    mutate(ledger)
    ledger_path.write_bytes(_raw(ledger))


def test_b6_ledger_that_omits_composed_classes_is_reported(
    tmp_path: Path,
) -> None:
    """B6 (the s2 fold, lane B F2): the ledger's composed inventory was
    write-only on the verify surface — deleting the ``composed_classes``
    rows left verify-ui green. The read-back mirrors slice 1's
    ``_custom_inventory_findings``: the authored class rows compare
    against the derived class set, both directions, REPORTED and never a
    findings failure."""
    from benchweave_sdk.classref_gate import verify_ui

    project, package = _composed_gate_project(tmp_path / "omit-classes")

    def mutate(ledger: dict[str, Any]) -> None:
        ledger["composed_classes"] = []

    _tamper_ledger(package, mutate)
    report = verify_ui(project)
    assert any(
        row.startswith("composed mismatch: ") and CLASS_URN in row
        for row in report.reported_deviations
    ), report.reported_deviations
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]


def test_b6_ledger_with_forged_composed_class_is_reported(
    tmp_path: Path,
) -> None:
    """B6's other direction: a forged ``composed_classes`` row naming a
    class no pin declares is reported too."""
    from benchweave_sdk.classref_gate import verify_ui

    project, package = _composed_gate_project(tmp_path / "forged-class")

    def mutate(ledger: dict[str, Any]) -> None:
        ledger["composed_classes"].append(
            {
                "class": "otdp.action.veridian_ghost/1.0.0",
                "validated_against": active_version("plugin-ui-class-reference"),
            }
        )

    _tamper_ledger(package, mutate)
    report = verify_ui(project)
    assert any(
        row.startswith("composed mismatch: ")
        and "otdp.action.veridian_ghost/1.0.0" in row
        for row in report.reported_deviations
    ), report.reported_deviations
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]


def test_b6_ledger_that_omits_composed_actions_is_reported(
    tmp_path: Path,
) -> None:
    """B6, the actions set: an authored ledger that drops a derived
    composed member from ``composed_actions`` gets the mismatch reported
    — the same write-only hole, one key over."""
    from benchweave_sdk.classref_gate import verify_ui

    project, package = _composed_gate_project(tmp_path / "omit-actions")

    def mutate(ledger: dict[str, Any]) -> None:
        ledger["composed_actions"] = []

    _tamper_ledger(package, mutate)
    report = verify_ui(project)
    assert any(
        row.startswith("composed mismatch: ") and STAGE_URN in row
        for row in report.reported_deviations
    ), report.reported_deviations
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]


def test_b6_ledger_with_forged_composed_action_is_reported(
    tmp_path: Path,
) -> None:
    """B6's forged direction for the actions set: a row naming an URN no
    plan derives composed is reported."""
    from benchweave_sdk.classref_gate import verify_ui

    project, package = _composed_gate_project(tmp_path / "forged-action")

    def mutate(ledger: dict[str, Any]) -> None:
        ledger["composed_actions"] = [
            {
                "action": "otdp.veridian_staging.unclaimed/1.0.0",
                "resolution": "composed",
                "class": CLASS_URN,
            }
        ]

    _tamper_ledger(package, mutate)
    report = verify_ui(project)
    assert any(
        row.startswith("composed mismatch: ")
        and "otdp.veridian_staging.unclaimed/1.0.0" in row
        for row in report.reported_deviations
    ), report.reported_deviations
    # The omitted direction reports too (the derived member is missing).
    assert any(
        row.startswith("composed mismatch: ") and STAGE_URN in row
        for row in report.reported_deviations
    ), report.reported_deviations
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]


# ---------------------------------------------------------------------------
# The 2026-10-23 fold wave 3 (review rows R1-R7). Each arm names its row;
# the RED evidence for every arm is quoted in the fold commit's message.
# ---------------------------------------------------------------------------


def _pinned_gate_project(
    tmp_path: Path,
    *,
    documents: dict[str, dict[str, Any]],
    descriptor: dict[str, Any],
) -> tuple[Path, Path]:
    """A real scaffolded project carrying arbitrary pinned documents (the
    wave-3 disclosure arms' input): scaffold, write the pins, derive, and
    write the full derived document set with the birth ledger."""
    from benchweave_sdk.classref import declaration_scaffold
    from benchweave_sdk.scaffold import create_project

    project = tmp_path
    create_project(project, "veridian_composed_plugin", with_ui=False)
    package = project / "src" / "veridian_composed_plugin"
    for name, document in documents.items():
        (package / name).write_bytes(_raw(document))
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
    return project, package


def test_r1_unapplied_class_is_disclosed_on_the_derivation(
    tmp_path: Path,
) -> None:
    """R1 (HIGH): a pin-declared class whose claims name no action this
    descriptor declares — the shape the standards record §3 sanctions —
    applies nowhere. The ledger's ``composed_classes`` records what the
    derivation APPLIED, so it is empty BY DESIGN, and the unapplied class
    is disclosed as (class urn, pin path) pairs on the derivation — the
    B7 mechanism, never a new surface."""
    document = _composed_document(
        claims=["otdp.veridian_staging.unrelated/1.0.0"]
    )
    descriptor = _pinned_descriptor(document=document)
    descriptor["actions"].pop(STAGE_URN)
    descriptor_path = _scratch(
        tmp_path / "unapplied",
        documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    derived = _derive(descriptor, descriptor_path)
    assert derived.declaration["composed_classes"] == []
    assert derived.unapplied_classes == ((CLASS_URN, "composed-staging.json"),)
    assert derived.ignored_pins == ()  # a different disclosure, not B7's


def test_r1_unapplied_class_reports_through_the_gate(tmp_path: Path) -> None:
    """R1's REPORTED channel: the unapplied class names the class URN and
    states that its claims name no action this descriptor declares —
    every run, never silent, never a findings failure."""
    from benchweave_sdk.classref_gate import verify_ui

    document = _composed_document(
        claims=["otdp.veridian_staging.unrelated/1.0.0"]
    )
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["contracts"].append(
        _composed_pin("composed-staging.json", document)
    )
    project, _package = _pinned_gate_project(
        tmp_path / "unapplied-gate",
        documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    report = verify_ui(project)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    assert any(
        row.startswith(f"composed class {CLASS_URN}")
        and "claims name no action this descriptor declares" in row
        for row in report.reported_deviations
    ), report.reported_deviations


def test_r2_actions_and_claims_pin_refuses(tmp_path: Path) -> None:
    """R2 (MEDIUM): "is this a composed class?" (urn AND claims) and "is
    this pin ambiguous?" (actions AND urn-or-claims) are different
    questions. B1's AND narrowing rode the ambiguity test down with the
    composed one, so {actions, claims} absorbed the catalog actions,
    dropped the composed key and disclosed nothing — it refuses, naming
    why."""
    document = _composed_document(
        actions={STAGE_URN: {"input_schema": {"type": "object"}, "side_effect": "none"}}
    )
    del document["urn"]
    descriptor = _pinned_descriptor(document=document)
    descriptor_path = _scratch(
        tmp_path / "ambiguous-claims",
        documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    with pytest.raises(
        ValueError, match="^classref_invalid_composed_class:"
    ) as excinfo:
        _derive(descriptor, descriptor_path)
    assert "ambiguous" in str(excinfo.value)
    assert "claims" in str(excinfo.value)


def test_r2_actions_and_urn_pin_refuses(tmp_path: Path) -> None:
    """R2's mirrored arm: {actions, urn} is the same ambiguity — the
    vendor-catalog half and a composed-class key in one pin."""
    document = _composed_document(
        actions={STAGE_URN: {"input_schema": {"type": "object"}, "side_effect": "none"}}
    )
    del document["claims"]
    descriptor = _pinned_descriptor(document=document)
    descriptor_path = _scratch(
        tmp_path / "ambiguous-urn",
        documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    with pytest.raises(
        ValueError, match="^classref_invalid_composed_class:"
    ) as excinfo:
        _derive(descriptor, descriptor_path)
    assert "ambiguous" in str(excinfo.value)
    assert "urn" in str(excinfo.value)


def test_r4_non_object_actions_pin_refuses_typed(tmp_path: Path) -> None:
    """R4 (LOW-MEDIUM): B7 typed the DOCUMENT (non-object → typed
    refusal) but left the actions MAP untyped — ``{"actions": 5}`` through
    a digest-valid pin crashed the walk on ``document["actions"].items()``
    with a bare AttributeError, which is not an SDK error face. The
    actions map is typed at the discriminator: a non-object refuses
    ``classref_vendor_catalog_invalid``, authoring-error reachable and
    typed."""
    document = {"actions": 5}
    descriptor = _pinned_descriptor(document=document)
    descriptor_path = _scratch(
        tmp_path / "actions-int",
        documents={"composed-staging.json": document},
        descriptor=descriptor,
    )
    with pytest.raises(
        ValueError, match="^classref_vendor_catalog_invalid:"
    ) as excinfo:
        _derive(descriptor, descriptor_path)
    assert "'actions'" in str(excinfo.value)


def test_r5_empty_actions_pin_is_disclosed(tmp_path: Path) -> None:
    """R5 (LOW): a pin whose vendor-catalog document declares an EMPTY
    actions map matches the vendor-catalog discriminator, contributes
    nothing and was disclosed nowhere — the ledger reason blamed the
    descriptor alone. It discloses through the same channel as R1's
    unapplied classes, and the staged action falls to the residual layer."""
    document = {"actions": {}}
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["actions"][STAGE_URN] = _stage_action()
    descriptor["contracts"].append(
        {
            "id": "urn:veridian:empty-catalog:1.0.0",
            "path": "empty-catalog.json",
            "sha256": hashlib.sha256(_raw(document)).hexdigest(),
        }
    )
    descriptor_path = _scratch(
        tmp_path / "empty-catalog",
        documents={"empty-catalog.json": document},
        descriptor=descriptor,
    )
    derived = _derive(descriptor, descriptor_path)
    assert derived.control_plan[STAGE_URN]["resolution"] == "custom"
    assert derived.empty_action_pins == ("empty-catalog.json",)
    assert derived.ignored_pins == ()  # shape-recognized: not B7's channel


def test_r5_empty_catalog_pin_reports_through_the_gate(tmp_path: Path) -> None:
    """R5's REPORTED channel: the empty-actions pin's row names the pin and
    says its vendor-catalog actions map is empty — every run, never
    silent."""
    from benchweave_sdk.classref_gate import verify_ui

    document = {"actions": {}}
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["actions"][STAGE_URN] = _stage_action()
    descriptor["contracts"].append(
        {
            "id": "urn:veridian:empty-catalog:1.0.0",
            "path": "empty-catalog.json",
            "sha256": hashlib.sha256(_raw(document)).hexdigest(),
        }
    )
    project, _package = _pinned_gate_project(
        tmp_path / "empty-catalog-gate",
        documents={"empty-catalog.json": document},
        descriptor=descriptor,
    )
    report = verify_ui(project)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    assert any(
        row.startswith("pinned document empty-catalog.json")
        and "actions map is empty" in row
        for row in report.reported_deviations
    ), report.reported_deviations


def test_r6_read_back_compares_the_action_class_mapping(
    tmp_path: Path,
) -> None:
    """R6 (LOW): the composed read-back compared two SETS — a ledger whose
    ``composed_actions`` row names the WRONG class for an action
    (internally inconsistent with its own ``composed_classes``, which
    carries the right one) verified clean and migrated with "nothing to
    do". The read-back compares the action -> class MAPPING."""
    from benchweave_sdk.classref_gate import verify_ui

    project, package = _composed_gate_project(tmp_path / "wrong-class")

    def mutate(ledger: dict[str, Any]) -> None:
        ledger["composed_actions"][0]["class"] = (
            "otdp.action.veridian_staging_alt/1.0.0"
        )

    _tamper_ledger(package, mutate)
    report = verify_ui(project)
    assert any(
        row.startswith("composed mismatch: ")
        and STAGE_URN in row
        and "otdp.action.veridian_staging_alt/1.0.0" in row
        for row in report.reported_deviations
    ), report.reported_deviations
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
