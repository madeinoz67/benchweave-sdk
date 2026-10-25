"""Class-reference expander (gateway #463 Landing 2).

Turns a class-conformant descriptor plus a ``plugin-ui-class-reference``
reference document into a normal plugin-ui 0.4.0 manifest set, the numeric
expectation document the rendered gate asserts, the
``plugin-ui-class-reference:layout`` block (the namespaced extension seam),
the effective settings schema and preset scaffolds.

Structure, not data (D2): the reference authors structure only; every data
value resolves here from the descriptor and the served OTDP catalog. The
effective schema (D13) is a NARROWING composition only (catalogue AND
descriptor ``input_constraints``); nothing here widens admittance and no
bench policy is invented (A02).

Successful derivation is never admission, approval to apply settings or
permission to operate hardware.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .presentation import read_file
from .served import active_version
from .validation import contract_documents, validate_descriptor

LAYOUT_EXTENSION_KEY = "plugin-ui-class-reference:layout"

_LANE_CEILING = 64
#: The ``y`` ceiling the manifest schema puts on a time_series/waveform plot
#: (``ui-manifest.schema.json`` ``$defs.plot`` allOf, the analog branch:
#: ``y.maxItems`` 16). ``_LANE_CEILING`` is the same pattern for the
#: digital-lanes branch's 64; the vendored schema is the authority and
#: ``test_scope_b1_the_series_ceiling_matches_the_manifest_schema`` reads it
#: so this constant cannot drift from it silently.
_PLOT_SERIES_CEILING = 16
_GROUP_SIZE = 8
_HOST_SUPPLIED_UNIVERSAL = ("acquisition_id", "configuration_id")
_NUMERIC_TYPES = ("number", "integer")
#: The layout-node kind each field-row mode emits (the L5 widening, gateway
#: #463). A literal const renders the §E.1 select's read-only fixed display —
#: the F2 ruling (design-record addendum, 2026-10-16): the landed contract
#: row and the renderer both say a const renders the fixed display.
_MODE_KIND: dict[str, str] = {
    "numeric": "numeric",
    "text": "text",
    "const": "select",
    "enum": "select",
    "boolean": "boolean",
}
#: The closed constraint vocabulary (record §3.7): the first group narrows a
#: rendered control; the riders (required/properties/items/min/max/unique)
#: ride the conjunctive validation lanes untouched and derive no controls.
#: #541 W9 fold (2026-10-22 review): minLength/maxLength join the control
#: group — a vendor action declaring a string length bound used to refuse
#: classref_constraint_unsupported, so "never refuses" was false for that
#: input class. The corpus README's closed-vocabulary prose gains the two
#: keywords at slice 2's 0.4.0 copy (deferral D8 records the obligation).
_CONSTRAINT_CONTROL_KEYWORDS = frozenset(
    {"type", "enum", "const", "minimum", "maximum",
     "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "pattern",
     "minLength", "maxLength"}
)
_CONSTRAINT_RIDER_KEYWORDS = frozenset(
    {"required", "properties", "items", "minItems", "maxItems", "uniqueItems"}
)
#: The closed counter grammar the corpus authors (0.3.0 README, §Class
#: reference documents): the founding six plus the L11/L13 readings and
#: capture counters. An expect expression outside this set refuses
#: ``classref_expect_expression`` — the SDK adds no name the corpus does
#: not carry.
_EXPECT_NAMES = frozenset(
    {"n_lanes", "n_groups", "n_decoders", "n_run_actions", "n_configure_fields",
     "n_pages", "n_source_channels", "n_scalar_variables", "n_reading_tiles",
     "n_analogue_channels", "n_trace_variables"}
)
_FAMILY = "plugin-ui-class-reference"
_DECLARATION_FILENAME = "class-reference.json"


def _refuse(prefix: str, detail: str) -> ValueError:
    return ValueError(f"{prefix}: {detail}")


@dataclass(frozen=True)
class ResidualMember:
    """(#556 Track B §3 rule 3) One row on the gate's REPORTED channel.

    ``kind`` names the member's vocabulary surface (``observation variable``,
    ``channel``, ``custom decoder``); ``member`` identifies the member
    (a channel row carries its role beside the id); ``detail`` states what
    the derivation did not produce, or — V2's composed-state row — what it
    did produce instead. The gate renders ``"<kind> <member>: <detail>"``.
    """

    kind: str
    vocabulary: str
    member: str
    detail: str


@dataclass(frozen=True)
class DerivedUI:
    """Everything one expander run emits; the gate's assertion input."""

    manifest: dict[str, Any]
    envelope: dict[str, Any]
    catalogue: dict[str, Any]
    settings_schema: dict[str, Any]
    preset_scaffolds: dict[str, dict[str, Any]]
    layout_block: dict[str, Any]
    expectation: dict[str, Any]
    control_plan: dict[str, dict[str, Any]]
    reference: dict[str, Any]
    cannot_derive: list[dict[str, str]]
    declaration: dict[str, Any]
    #: Pins whose documents matched neither shape discriminator (B7):
    #: digest-verified, contributed nothing, disclosed — never dropped
    #: silently. Empty tuple on derivations with no such pins.
    ignored_pins: tuple[str, ...] = ()
    #: Pin-declared composed classes that applied nowhere (R1, 2026-10-23
    #: fold wave 3): digest-verified, schema-valid, but their claims name
    #: no action this descriptor declares — carried as (class urn, pin
    #: path) pairs and disclosed through the gate's REPORTED channel, the
    #: B7 mechanism. The ledger's ``composed_classes`` records what the
    #: derivation APPLIED, so these classes stay out of it by design.
    unapplied_classes: tuple[tuple[str, str], ...] = ()
    #: Pins whose vendor-catalog documents declare an empty actions map
    #: (R5): shape-valid, contributed nothing — disclosed beside the
    #: unapplied classes, never silent.
    empty_action_pins: tuple[str, ...] = ()
    #: Declared members carried on the gate's REPORTED channel every run
    #: (R10, 2026-10-23 fold; #556 Track B §3 rule 3). Two kinds of row ride
    #: this inventory: a member that derives NO surface of its vocabulary (a
    #: decoder no derived plot hosts, a channel whose role matches no resolved
    #: lanes slot), and V2's composed-state disclosure — a computed variable
    #: DOES derive, into dataset variables, and never a tile, so its row
    #: states what it derives instead of naming a deferral (including the
    #: targets it was dropped from: a base-id collision, or a plot ``y``
    #: ceiling, both named in the row's detail). Layer 3's promise
    #: is two-sided — never refuses AND never silent — and silence here is
    #: indistinguishable from "we rendered it and it looked fine".
    residual_members: tuple[ResidualMember, ...] = ()
    #: (#556 track B §3 rule 1) The APPLIED composed-member set per
    #: vocabulary (procedures/settings/datasets/channels) — a member
    #: applies when the descriptor declares its claim (an action the
    #: member claims is declared; a declared channel carries its
    #: ``where_role``). Only the composed-member walk writes it; the
    #: ledger's ``composed_members`` records exactly this set, so a pin
    #: whose members apply nowhere stays out BY DESIGN and is the
    #: ``unapplied_member_pins`` disclosure instead — never drift.
    composed_members: Mapping[str, tuple[dict[str, str], ...]] = dataclass_field(
        default_factory=dict
    )
    #: Pins whose member declarations applied nowhere (#556 §3 rule 1):
    #: digest-verified, schema-valid, conflict-free, but no member's claim
    #: names a declared action and no declared channel matches its role —
    #: disclosed on the REPORTED channel every run, the R1 discipline.
    unapplied_member_pins: tuple[str, ...] = ()


@cache
def _family_schemas() -> dict[str, Any]:
    """The family's own machine schemas, from the vendored, lock-verified tree.

    #541 slice 2: the family triple — reference, layout, composed — loads
    through one seam; the composed schema joined the family at 0.4.0 and
    the lock moved in the same arc, so a tree that serves an older active
    family refuses loudly here rather than resolving composed pins as
    silently-empty vendor catalogs."""
    from .validation import contract_documents

    prefix = f"{_FAMILY}/{active_version(_FAMILY)}/"
    documents = contract_documents()
    reference = documents.get(f"{prefix}class-reference.schema.json")
    layout = documents.get(f"{prefix}layout.schema.json")
    composed = documents.get(f"{prefix}composed-action-class.schema.json")
    if reference is None or layout is None or composed is None:
        raise RuntimeError(
            "plugin-ui-class-reference schemas missing from the vendored tree; "
            "run sync-standards or reinstall the SDK"
        )
    return {"reference": reference, "layout": layout, "composed": composed}


def layout_schema() -> dict[str, Any]:
    """The family's layout vocabulary schema (the block's only authority)."""
    schema: dict[str, Any] = _family_schemas()["layout"]
    return schema


def _validate_reference_bytes(raw: bytes) -> dict[str, Any]:
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _refuse("classref_invalid_reference", f"not JSON: {exc}") from exc
    return _validate_reference(document)


def _validate_reference(document: Any) -> dict[str, Any]:
    schema = _family_schemas()["reference"]
    layout = _family_schemas()["layout"]
    registry = Registry().with_resource(
        str(layout.get("$id")), Resource.from_contents(layout)
    )
    findings = sorted(
        Draft202012Validator(schema, registry=registry).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if findings:
        first = findings[0]
        where = "/".join(str(part) for part in first.path) or "(root)"
        raise _refuse(
            "classref_invalid_reference", f"{where}: {first.message}"
        )
    return document  # type: ignore[no-any-return]


def find_reference(profile_id: str) -> dict[str, Any] | None:
    """The vendored reference document for one profile id, or None.

    The vendored family tree is the SDK's served copy of the admitted
    standard; profile matching is by the document's own ``profile_id``.
    """
    root = Path(__file__).with_name("standards") / _FAMILY / active_version(_FAMILY)
    if not root.is_dir():
        return None
    for path in sorted(root.glob("class-*.json")):
        try:
            document = json.loads(read_file(path))
        except (ValueError, OSError):
            continue
        if isinstance(document, dict) and document.get("profile_id") == profile_id:
            found: dict[str, Any] = _validate_reference(document)
            return found
    return None


def _satisfies_target(active: str, target: str) -> bool:
    """Per-parsed-operator comparison (record §2.2 admission-fold note):
    the active version A satisfies ``>=V`` iff A >= V, ``>V`` iff A > V,
    ``<V`` iff A < V, ``<=V`` iff A <= V."""
    match = re.fullmatch(r"(>=|<=|>|<)?(\d+(?:\.\d+)*)", target)
    if match is None:
        raise _refuse("classref_invalid_reference", f"target {target!r} unparsable")
    operator, version = match.group(1) or ">=", match.group(2)
    def parts(text: str) -> tuple[int, ...]:
        return tuple(int(piece) for piece in text.split("."))
    left, right = parts(active), parts(version)
    width = max(len(left), len(right))
    left += (0,) * (width - len(left))
    right += (0,) * (width - len(right))
    if operator == ">=":
        return left >= right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    return left < right


def _catalog_documents(descriptor: dict[str, Any]) -> dict[str, Any]:
    """The served documents for the descriptor's pins: the OTDP catalog row
    carrier plus every pinned vendor catalog (a contract row whose id is not
    an otdp URN). Vendor catalog digests verify against the pinned bytes."""
    documents = contract_documents()
    row_key = f"otdp/{descriptor['otdp_version']}/device-profile-catalog.json"
    catalog = documents.get(row_key)
    if catalog is None:
        # #541 record §1: a platform fault (incomplete installation), never
        # the recoverable knowledge gap — its own code since the split.
        raise _refuse(
            "classref_profile_catalog_unserved",
            f"the descriptor's profile catalog {row_key} is not served",
        )
    served: dict[str, Any] = catalog
    return served


@dataclass(frozen=True)
class ComposedClass:
    """One pinned, digest-verified composed action-class declaration
    (#541 layer 2): the document that supplies the catalogue side of the
    derivation for the URNs it claims."""

    urn: str
    side_effect: str
    input_schema: dict[str, Any]
    claims: tuple[str, ...]
    pin_path: str


@dataclass(frozen=True)
class ComposedMemberDeclaration:
    """One pinned, digest-verified composed-member declaration (#556 track
    B layer 2): the vendor-authored document that supplies the reference
    side — one slot per member, its page placement, optionally one vendor
    profile row — the served corpus does not carry.

    ``profile`` is the declaration's one vendor profile row (the
    device-profile-catalog row shape, carried under the plural ``profiles``
    key the canonical validator's map reads) or None; ``members`` are the
    raw schema-validated member rows; ``pin_path`` names the pinned file."""

    profile: dict[str, Any] | None
    members: tuple[dict[str, Any], ...]
    pin_path: str


def _validate_composed_class(
    document: Any, pin_path: Any
) -> dict[str, Any]:
    """One pinned document against the vendored composed-class schema.

    The claims items $ref resolves through the family's reference schema,
    so both documents ride one registry (the same cross-file $ref style
    ``_validate_reference`` uses for the layout schema)."""
    schemas = _family_schemas()
    registry = Registry().with_resource(
        str(schemas["reference"].get("$id")),
        Resource.from_contents(schemas["reference"]),
    )
    findings = sorted(
        Draft202012Validator(schemas["composed"], registry=registry).iter_errors(
            document
        ),
        key=lambda error: list(error.path),
    )
    if findings:
        first = findings[0]
        where = "/".join(str(part) for part in first.path) or "(root)"
        raise _refuse(
            "classref_invalid_composed_class",
            f"pinned document {pin_path}: {where}: {first.message}",
        )
    return document  # type: ignore[no-any-return]


def validate_composed_class(document: Any, pin_path: Any) -> dict[str, Any]:
    """The public name for ``_validate_composed_class`` (the presentation
    layer's migrate-ui leg re-validates ledger-named classes against the
    same vendored schema — #541 slice 2, standards record §8.3)."""
    return _validate_composed_class(document, pin_path)


@cache
def _member_declaration_schema() -> dict[str, Any]:
    """The family's composed-member-declaration schema, from the vendored,
    lock-verified tree (#556 track B; the family gained the schema at
    0.5.0). Resolved lazily — a tree serving an older family derives
    member-pin-free projects unchanged; a member PIN on such a tree is a
    platform fault and refuses loudly here, never a silently-empty read."""
    key = (
        f"{_FAMILY}/{active_version(_FAMILY)}"
        "/composed-member-declaration.schema.json"
    )
    schema = contract_documents().get(key)
    if schema is None:
        raise RuntimeError(
            "plugin-ui-class-reference member-declaration schema missing from "
            "the vendored tree; run sync-standards or reinstall the SDK"
        )
    return schema  # type: ignore[no-any-return]


def _validate_member_declaration(
    document: Any, pin_path: Any
) -> dict[str, Any]:
    """One pinned document against the vendored member-declaration schema
    (every closed set in it is an owner's own — the reference schema's
    slot vocabulary, the page id shape, the plot block verbatim, the
    profile-catalog row shape)."""
    findings = sorted(
        Draft202012Validator(_member_declaration_schema()).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if findings:
        first = findings[0]
        where = "/".join(str(part) for part in first.path) or "(root)"
        raise _refuse(
            "classref_invalid_member_declaration",
            f"pinned document {pin_path}: {where}: {first.message}",
        )
    return document  # type: ignore[no-any-return]


def composed_ledger_inventory(
    descriptor: dict[str, Any], descriptor_path: Path | None
) -> tuple[set[str], dict[str, str], set[str]]:
    """The ledger's set arithmetic over the current descriptor and pins
    (#541 slice 2, standards record §8.4; R1, 2026-10-23 fold wave 3):
    ``(custom, composed_of, applied_classes)`` where custom = declared −
    (catalog ∪ composed-claimed), ``composed_of`` maps each DECLARED action
    a class claims to that class's urn, and ``applied_classes`` is the set
    of pin-declared classes at least one of whose claims the descriptor
    declares. Both the ledger and migrate-ui's drift arithmetic key to
    the APPLIED set — the ledger records what the derivation applied, so
    a class that applies nowhere (its claims name no action this
    descriptor declares — a shape §3 sanctions) is the gate's disclosure,
    never drift. Raises the resolution's own refusals — a project whose
    pins cannot resolve honestly cannot have its ledger re-stamped;
    migrate-ui refuses, never silently upgrades."""
    catalog = _catalog_documents(descriptor)
    served = dict(catalog.get("actions", {}))
    (
        vendor_actions,
        classes,
        _ignored,
        _unapplied,
        _empty,
        _members,
    ) = _vendor_documents(descriptor, descriptor_path, served)
    covered = set(served) | set(vendor_actions)
    declared_actions = descriptor.get("actions") or {}
    declared = set(declared_actions)
    composed_of = {
        urn: str(vendor_actions[urn]["composed_class"])
        for urn in declared
        if isinstance(vendor_actions.get(urn), dict)
        and "composed_class" in vendor_actions[urn]
    }
    applied = _applied_class_urns(classes, declared_actions)
    return declared - covered, composed_of, applied


def _applied_class_urns(
    classes: dict[str, ComposedClass], declared: dict[str, Any]
) -> set[str]:
    """The classes the derivation APPLIES (R1, 2026-10-23 fold wave 3): a
    class applies when at least one of its claims names an action this
    descriptor declares. The ledger's ``composed_classes`` and the
    drift arithmetic both key to exactly this set — keying to the
    pin-declared set instead made a sanctioned claims-nowhere class
    refuse ``migrate_ui_ledger_drift`` against a ledger derive-ui had
    just written, so the author's re-derive looped on byte-identical
    output."""
    return {
        urn
        for urn, cls in classes.items()
        if any(claim in declared for claim in cls.claims)
    }


#: The ledger vocabulary each member kind lands under (#556 §3 rule 2):
#: one key per composed vocabulary, the design's own names.
_MEMBER_VOCABULARY = {
    "procedure": "procedures",
    "configuration": "settings",
    "dataset": "datasets",
    "channels": "channels",
}


def _member_applies(member: Mapping[str, Any], descriptor: dict[str, Any]) -> bool:
    """(#556 §3 rule 1, the R1 rule verbatim) A member applies when the
    descriptor declares its claim: an action member (dataset,
    configuration, procedure) when any claimed URN names a declared
    action; the claim-less channels kind when any declared channel carries
    its ``where_role``."""
    if member.get("kind") == "channels":
        role = str(member.get("where_role", ""))
        return any(
            isinstance(row, dict) and str(row.get("role")) == role
            for row in descriptor.get("channels") or ()
        )
    declared = descriptor.get("actions") or {}
    return any(str(claim) in declared for claim in member.get("claims") or ())


def _applied_member_row(
    member: Mapping[str, Any], descriptor: dict[str, Any]
) -> dict[str, str]:
    """The ledger row one APPLIED member lands (#556 §4's per-vocabulary
    rows): channels carry ``where_role``; the claim-carrying kinds carry
    the action — the FIRST claim the descriptor declares, in document
    claim order (the design's rows are one action per row; a multi-claim
    member whose every claim is declared names its first, and the
    per-claim surface question belongs to the slices that derive those
    vocabularies)."""
    row = {
        "slot": str(member.get("slot", "")),
        "page": str(member.get("page", "")),
    }
    if member.get("kind") == "channels":
        row["where_role"] = str(member.get("where_role", ""))
    else:
        declared = descriptor.get("actions") or {}
        row["action"] = next(
            str(claim) for claim in member.get("claims") or () if str(claim) in declared
        )
    return row


def _composed_member_inventory(
    declarations: tuple[ComposedMemberDeclaration, ...],
    descriptor: dict[str, Any],
) -> tuple[dict[str, tuple[dict[str, str], ...]], tuple[str, ...]]:
    """(#556 §3 rules 1-2) The composed-members inventory: the APPLIED set
    per vocabulary, and the pins whose members apply nowhere.

    Only the composed-member walk feeds this; the ledger's
    ``composed_members`` records exactly the applied set, so a pin whose
    members apply nowhere (a shape the schema sanctions) stays out of it
    BY DESIGN and rides back as its pin path for the REPORTED channel —
    the R1 discipline, never drift."""
    rows: dict[str, list[dict[str, str]]] = {}
    unapplied: list[str] = []
    for declaration in declarations:
        applied_any = False
        for member in declaration.members:
            if not _member_applies(member, descriptor):
                continue
            applied_any = True
            vocabulary = _MEMBER_VOCABULARY[str(member.get("kind", ""))]
            rows.setdefault(vocabulary, []).append(
                _applied_member_row(member, descriptor)
            )
        if not applied_any:
            unapplied.append(declaration.pin_path)
    frozen = {key: tuple(value) for key, value in rows.items()}
    return frozen, tuple(unapplied)


def _check_member_reference_conflicts(
    merged: dict[str, Any],
    declarations: tuple[ComposedMemberDeclaration, ...],
) -> None:
    """(#556 §3 rule 4; README rules 1 and 3) The reference-side member
    conflicts, over the MERGED reference (final page ids and slot keys —
    later profiles' ids carry their slug): a member slot key a reference
    slot already holds, a claim a reference slot already binds, and a
    ``page`` naming no page the composed reference declares all refuse
    ``classref_composed_slot_conflict`` — the composed slot composes
    BESIDE the reference, never over it."""
    pages = {str(page.get("id")) for page in merged["pages"]}
    for declaration in declarations:
        for member in declaration.members:
            slot = str(member.get("slot", ""))
            if slot in merged["slots"]:
                raise _refuse(
                    "classref_composed_slot_conflict",
                    f"member slot {slot} is already a slot of the composed "
                    "reference",
                )
            page = str(member.get("page", ""))
            if page not in pages:
                raise _refuse(
                    "classref_composed_slot_conflict",
                    f"member {slot} names page {page}, which the composed "
                    "reference does not declare",
                )
            for claim in member.get("claims") or ():
                claim = str(claim)
                for key, ref_slot in merged["slots"].items():
                    if str(ref_slot.get("action", "")) == claim:
                        raise _refuse(
                            "classref_composed_slot_conflict",
                            f"member {slot} claims {claim}, which reference "
                            f"slot {key} already binds",
                        )


def _vendor_documents(
    descriptor: dict[str, Any],
    descriptor_path: Path | None,
    served_actions: dict[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, ComposedClass],
    tuple[str, ...],
    tuple[tuple[str, str], ...],
    tuple[str, ...],
    tuple[ComposedMemberDeclaration, ...],
]:
    """Action rows, composed classes, ignored pins, unapplied classes,
    empty-catalog pins and composed-member declarations from the
    descriptor's pinned documents (the proven vendor-catalog walk, #541
    record §2).

    #541 slice 2 (standards record §6): the same walk discriminates by
    document shape — a document carrying ``urn`` AND ``claims`` (the
    fold's B1 row: the record's "plus" is conjunctive) is a composed
    action class, validated against the vendored
    ``composed-action-class.schema.json``; a document carrying ``actions``
    together with ``urn`` OR ``claims`` is an AMBIGUOUS pin and refuses
    the same code (the R2 row, 2026-10-23 fold wave 3: "is this a
    composed class?" and "is this pin ambiguous?" are different
    questions — B1's AND rode the ambiguity test down with the composed
    one, so ``{actions, claims}`` and ``{actions, urn}`` absorbed the
    catalog actions and disclosed nothing); a document carrying neither
    shape is IGNORED — it contributes nothing, is returned in ``ignored``
    (the fold's B7 row: the drop is disclosed on the derivation and
    through the gate's REPORTED channel, never silent). A vendor catalog
    whose ``actions`` is not a JSON object refuses typed (R4 — the walk
    crashed on a bare AttributeError, the crash class B7 removed); one
    whose ``actions`` map is EMPTY contributed nothing and is returned in
    ``empty_pins`` for the same disclosure channel (R5). A composed class
    none of whose claims the descriptor declares applied NOWHERE — it is
    returned in ``unapplied`` as (class urn, pin path) pairs for the
    gate's REPORTED channel, and the ledger's ``composed_classes`` omits
    it BY DESIGN (R1). Integrity refusals (unreadable, digest mismatch,
    non-object) are unchanged and fire before any discrimination — a
    pinned file's bytes are verified whatever shape they turn out to
    carry.

    #556 track B (§3): a document carrying ``members`` is a composed
    MEMBER declaration, validated against the vendored
    ``composed-member-declaration.schema.json`` — the R2 ambiguity
    question generalizes to the three key sets (a key set is not a shape
    claim: any overlap of the member/class/catalog keys refuses the R2
    code, naming the carried keys). A member's ``plot.over_slot`` naming
    a slot other than its own is the document referring to itself
    inconsistently and refuses ``classref_composed_plot_slot_mismatch``
    (the README's named cannot-catch; the schema cannot compare two
    instance values). Member conflicts refuse
    ``classref_composed_slot_conflict`` (record §3 rule 4, the
    refuse-never-merge family): a slot key two members declare, and a
    claim held by another member or by a composed action class. The
    reference-side conflicts (a member slot key a reference slot already
    holds, a claim a reference slot already binds, a page the reference
    does not declare) run at the injection seam
    (``_check_member_reference_conflicts``), where the merged reference
    exists.

    Conflicts refuse, never merge (record §8): a claim against a served
    or pinned catalogue row, a claim another class already holds, and a
    second document carrying one class urn all refuse
    ``classref_composed_claim_conflict`` — naming WHICH side the claim
    collided with (the served OTDP catalog, or the pinned document's
    path); a class ``side_effect`` of ``none`` under a descriptor action
    declaring ``state_change`` under-classifies (the S20 direction at
    the class layer) and refuses
    ``classref_composed_side_effect_under``. Survivors keep their codes:
    the walk's own integrity refusals never change.
    """
    import hashlib

    actions: dict[str, Any] = {}
    classes: dict[str, ComposedClass] = {}
    ignored: list[str] = []
    empty_pins: list[str] = []
    member_declarations: list[ComposedMemberDeclaration] = []
    pinned_sources: dict[str, str] = {}
    for row in descriptor.get("contracts", []):
        identifier = str(row.get("id", ""))
        if identifier.startswith("urn:otdp:"):
            continue
        if descriptor_path is None:
            continue
        path = descriptor_path.parent / str(row.get("path", ""))
        try:
            raw = read_file(path)
        except (ValueError, OSError) as exc:
            # #541 record §1: a platform or project fault, not a knowledge
            # gap — the pinned file is unreadable, whatever the action set.
            raise _refuse(
                "classref_vendor_catalog_unreadable",
                f"pinned vendor catalog {row.get('path')} unreadable ({exc})",
            ) from exc
        if hashlib.sha256(raw).hexdigest() != row.get("sha256"):
            # #541 record §1: an integrity fault — tampering or corruption
            # — refused under its own code since the split.
            raise _refuse(
                "classref_vendor_catalog_digest_mismatch",
                f"pinned vendor catalog {row.get('path')} digest mismatch",
            )
        document = json.loads(raw)
        if not isinstance(document, dict):
            # The fold's B7 row: a non-object pin refuses typed — the
            # pre-fold walk crashed on a bare AttributeError/TypeError
            # (``document.get`` on a list), which is not an SDK error face
            # (STD-4). It stays a refusal, never an ignored pin.
            raise _refuse(
                "classref_vendor_catalog_invalid",
                f"pinned vendor catalog {row.get('path')} is not a JSON object",
            )
        # R2 generalized (#556 §3): the ambiguity question is KEY-SET
        # overlap — a key set is not a shape claim. The member keys, the
        # composed-class keys and the catalog keys are three disjoint
        # vocabularies; a pin carrying keys from more than one refuses,
        # naming the carried keys (the pre-#556 predicate — actions AND
        # (urn OR claims) — is this rule's catalog/class row exactly).
        shape_groups: list[str] = []
        if "members" in document:
            shape_groups.append("members")
        if "urn" in document or "claims" in document:
            shape_groups.append("composed-class")
        if "actions" in document:
            shape_groups.append("actions")
        if len(shape_groups) > 1:
            carried = sorted(
                key
                for key in ("members", "urn", "claims", "actions")
                if key in document
            )
            raise _refuse(
                "classref_invalid_composed_class",
                f"pinned document {row.get('path')} carries keys of more "
                f"than one pin shape ({', '.join(shape_groups)}: "
                f"{', '.join(carried)}) — an ambiguous pin",
            )
        composed_keys = "urn" in document and "claims" in document
        if "members" in document:
            _validate_member_declaration(document, row.get("path"))
            # The self-reference rule (README rule 2): ``plot.over_slot``
            # names the member's own slot or the document contradicts
            # itself — refused here, before any member can inject.
            for member in document["members"]:
                slot = str(member.get("slot", ""))
                plot = member.get("plot")
                if (
                    isinstance(plot, dict)
                    and str(plot.get("over_slot", "")) != slot
                ):
                    raise _refuse(
                        "classref_composed_plot_slot_mismatch",
                        f"member {slot} carries plot.over_slot "
                        f"{plot.get('over_slot')!r}, which is not the "
                        "member's own slot (a document referring to itself "
                        "inconsistently)",
                    )
            member_declarations.append(
                ComposedMemberDeclaration(
                    profile=(
                        document["profiles"][0]
                        if isinstance(document.get("profiles"), list)
                        and document["profiles"]
                        else None
                    ),
                    members=tuple(document["members"]),
                    pin_path=str(row.get("path", "")),
                )
            )
            continue
        if composed_keys:
            _validate_composed_class(document, row.get("path"))
            cls = ComposedClass(
                urn=str(document["urn"]),
                side_effect=str(document["side_effect"]),
                input_schema=document["input_schema"],
                claims=tuple(str(claim) for claim in document["claims"]),
                pin_path=str(row.get("path", "")),
            )
            existing = classes.get(cls.urn)
            if existing is not None:
                raise _refuse(
                    "classref_composed_claim_conflict",
                    f"class urn {cls.urn} is declared by two pinned "
                    f"documents ({existing.pin_path} and {cls.pin_path})",
                )
            classes[cls.urn] = cls
        else:
            if "actions" not in document:
                # Neither shape discriminator: digest-verified, then
                # dropped — returned in ``ignored`` so the derivation and
                # the gate can disclose it (B7: never silently).
                ignored.append(str(row.get("path", "")))
            elif not isinstance(document["actions"], dict):
                # R4 (2026-10-23 fold, wave 3): B7 typed the DOCUMENT
                # (non-object → typed refusal) but left the actions MAP
                # untyped — a digest-valid pin carrying ``{"actions": 5}``
                # crashed the walk on a bare AttributeError at
                # ``.items()``. Authoring-error reachable, typed refusal.
                raise _refuse(
                    "classref_vendor_catalog_invalid",
                    f"pinned vendor catalog {row.get('path')} 'actions' is "
                    "not a JSON object (got "
                    f"{type(document['actions']).__name__})",
                )
            elif not document["actions"]:
                # R5 (2026-10-23 fold, wave 3): a shape-valid catalog that
                # declares NO actions contributed nothing — disclosed
                # through the same channel as the unapplied classes,
                # never silent and never blamed on the descriptor alone.
                empty_pins.append(str(row.get("path", "")))
            else:
                for action_urn, action_row in document["actions"].items():
                    if (
                        isinstance(action_row, dict)
                        and "composed_class" in action_row
                    ):
                        # N2 (2026-10-23 fold): composed provenance is
                        # written only by the composed walk above — a
                        # vendor-catalog row carrying a stray
                        # ``composed_class`` key (with a ``side_effect``
                        # riding it into the D7-feeding plan row) is not
                        # composed and must not launder the label. The
                        # review's disposition expected B1's AND to make
                        # this true; it did not (the stray key rides
                        # INSIDE an action row, which the AND never sees),
                        # so the strip makes it structurally unreadable.
                        action_row = {
                            key: value
                            for key, value in action_row.items()
                            if key != "composed_class"
                        }
                    actions[action_urn] = action_row
                    pinned_sources[action_urn] = str(row.get("path", ""))
    descriptor_actions = descriptor.get("actions") or {}
    claimant: dict[str, str] = {}
    for cls_urn in sorted(classes):
        cls = classes[cls_urn]
        for claim in cls.claims:
            if claim in served_actions:
                raise _refuse(
                    "classref_composed_claim_conflict",
                    f"class {cls_urn} claims {claim}, which the served "
                    "OTDP catalog describes",
                )
            if claim in actions:
                raise _refuse(
                    "classref_composed_claim_conflict",
                    f"class {cls_urn} claims {claim}, which pinned "
                    f"document {pinned_sources.get(claim, 'unknown')} "
                    "describes",
                )
            holder = claimant.get(claim)
            if holder is not None:
                raise _refuse(
                    "classref_composed_claim_conflict",
                    f"{claim} is claimed by both class {holder} and class "
                    f"{cls_urn}",
                )
            claimant[claim] = cls_urn
    for cls_urn in sorted(classes):
        cls = classes[cls_urn]
        for claim in sorted(cls.claims):
            declared = descriptor_actions.get(claim)
            if (
                isinstance(declared, dict)
                and declared.get("side_effect") == "state_change"
                and cls.side_effect == "none"
            ):
                raise _refuse(
                    "classref_composed_side_effect_under",
                    f"class {cls_urn} declares side_effect 'none' for "
                    f"{claim}, whose descriptor action declares "
                    "'state_change' (the S20 direction at the class layer: "
                    "over-classification is legal, under-classification "
                    "refuses)",
                )
    # Claimed URNs join the catalogue side of the derivation (D13 runs
    # unchanged on them), marked so the plan row can name the layer and
    # the class. A claim the descriptor does not declare simply does not
    # apply (a corpus-promoted class legitimately claims URNs across many
    # plugins); carrying it here also lets a named reference slot bind a
    # composed-claimed URN (DS3, admitted by design).
    for cls_urn in sorted(classes):
        cls = classes[cls_urn]
        for claim in cls.claims:
            actions[claim] = {
                "input_schema": cls.input_schema,
                "side_effect": cls.side_effect,
                "composed_class": cls_urn,
            }
    # R1 (2026-10-23 fold, wave 3): the classes that applied nowhere —
    # every claim names an action this descriptor does not declare —
    # ride back as (class urn, pin path) pairs for the gate's REPORTED
    # channel; the ledger records only what applied.
    unapplied = tuple(
        (urn, classes[urn].pin_path)
        for urn in sorted(classes)
        if not any(claim in descriptor_actions for claim in classes[urn].claims)
    )
    # #556 §3 rule 4: member conflicts across the whole pin set — a slot
    # key two members declare (whatever pin each rode), and a claim held
    # by another member or by a composed action class (the class owns the
    # catalogue side, the member the placement; one claim, one owner).
    # One slot per member, one claim per owner — refuse, never merge.
    member_slot_owner: dict[str, str] = {}
    member_claim_owner: dict[str, str] = {}
    class_claims = {
        claim: cls_urn
        for cls_urn, cls in classes.items()
        for claim in cls.claims
    }
    for declaration in member_declarations:
        for member in declaration.members:
            slot = str(member.get("slot", ""))
            holder_pin = member_slot_owner.get(slot)
            if holder_pin is not None:
                raise _refuse(
                    "classref_composed_slot_conflict",
                    f"member slot {slot} is declared by two members "
                    f"({holder_pin} and {declaration.pin_path})",
                )
            member_slot_owner[slot] = declaration.pin_path
            for claim in member.get("claims") or ():
                claim = str(claim)
                member_holder = member_claim_owner.get(claim)
                if member_holder is not None:
                    raise _refuse(
                        "classref_composed_slot_conflict",
                        f"{claim} is claimed by both member {member_holder} "
                        f"and member {slot}",
                    )
                class_holder = class_claims.get(claim)
                if class_holder is not None:
                    raise _refuse(
                        "classref_composed_slot_conflict",
                        f"member {slot} claims {claim}, which composed class "
                        f"{class_holder} claims",
                    )
                member_claim_owner[claim] = slot
    return (
        actions,
        classes,
        tuple(ignored),
        unapplied,
        tuple(empty_pins),
        tuple(member_declarations),
    )


def _intersect_property(
    action_urn: str, property_name: str, catalogue_schema: dict[str, Any],
    constraint: dict[str, Any],
) -> dict[str, Any]:
    """One property's effective admittance: catalogue AND constraint (D13).

    Narrowing only; a fragment that would offer an unadmitted value refuses
    loudly instead of being dropped."""
    for keyword in constraint:
        if keyword in _CONSTRAINT_CONTROL_KEYWORDS or keyword in _CONSTRAINT_RIDER_KEYWORDS:
            continue
        raise _refuse(
            "classref_constraint_unsupported",
            f"action {action_urn} field {property_name}: keyword {keyword!r} "
            "is outside the closed intersection vocabulary",
        )
    # G4 fold: both SIDES of the intersection are value-typed before any
    # comparison — an ill-typed catalogue or constraint bound used to
    # crash the max()/min() intersection arithmetic, and an ill-typed
    # length bound rode silently into the row.
    _check_value_types(action_urn, property_name, constraint)
    _check_value_types(action_urn, property_name, catalogue_schema)
    effective = dict(catalogue_schema)
    declared_type = (
        catalogue_schema.get("type") if isinstance(catalogue_schema, dict) else None
    )
    # Bounds INTERSECT (H1, refute lane 1): a looser constraint can never
    # widen the catalogue's admittance — the tighter end of each side wins,
    # the exclusivity flags carry, and an empty result refuses.
    def _bound(
        source: dict[str, Any], exclusive_key: str, plain_key: str
    ) -> tuple[Any, bool] | None:
        if exclusive_key in source:
            return source[exclusive_key], True
        if plain_key in source:
            return source[plain_key], False
        return None

    # Both sides break a value TIE the same way: the EXCLUSIVE end is the
    # tighter one. Tuple ordering cannot express that — (v, False) sorts
    # before (v, True), so min() at the high end kept the inclusive
    # catalogue ceiling and ADMITTED the shared value the constraint
    # refuses (the widening direction). Compare the pair explicitly on
    # both sides so one restatement cannot drift from the other.
    def _tighter_low(
        left: tuple[Any, bool], right: tuple[Any, bool]
    ) -> tuple[Any, bool]:
        if left[0] != right[0]:
            return left if left[0] > right[0] else right
        return (left[0], True) if left[1] or right[1] else (left[0], False)

    def _tighter_high(
        left: tuple[Any, bool], right: tuple[Any, bool]
    ) -> tuple[Any, bool]:
        if left[0] != right[0]:
            return left if left[0] < right[0] else right
        return (left[0], True) if left[1] or right[1] else (left[0], False)

    low_catalogue = _bound(effective, "exclusiveMinimum", "minimum")
    high_catalogue = _bound(effective, "exclusiveMaximum", "maximum")
    low_constraint = _bound(constraint, "exclusiveMinimum", "minimum")
    high_constraint = _bound(constraint, "exclusiveMaximum", "maximum")
    if (
        low_constraint is not None or high_constraint is not None
    ) and declared_type not in _NUMERIC_TYPES:
            raise _refuse(
                "classref_effective_schema_conflict",
                f"action {action_urn} field {property_name}: numeric bound "
                f"applied to catalogue type {declared_type!r}",
            )
    low: tuple[Any, bool] | None
    if low_catalogue is None:
        low = low_constraint
    elif low_constraint is None:
        low = low_catalogue
    else:
        low = _tighter_low(low_catalogue, low_constraint)
    high: tuple[Any, bool] | None
    if high_catalogue is None:
        high = high_constraint
    elif high_constraint is None:
        high = high_catalogue
    else:
        high = _tighter_high(high_catalogue, high_constraint)
    for keyword in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        effective.pop(keyword, None)
    if low is not None:
        value, exclusive = low
        effective["exclusiveMinimum" if exclusive else "minimum"] = value
    if high is not None:
        value, exclusive = high
        effective["exclusiveMaximum" if exclusive else "maximum"] = value
    if "multipleOf" in constraint:
        effective["multipleOf"] = constraint["multipleOf"]
    if "enum" in constraint:
        catalogue_enum = catalogue_schema.get("enum")
        if catalogue_enum is not None:
            allowed = [value for value in constraint["enum"] if value in catalogue_enum]
        else:
            allowed = list(constraint["enum"])
        if not allowed:
            raise _refuse(
                "classref_effective_schema_empty",
                f"action {action_urn} field {property_name}: enum intersection empty",
            )
        effective["enum"] = allowed
        effective.pop("minimum", None)
        effective.pop("maximum", None)
        effective.pop("exclusiveMinimum", None)
        effective.pop("exclusiveMaximum", None)
    if "const" in constraint:
        # A const NARROWS to one value; outside the catalogue's own
        # admittance it is a conflict (H1: never a replace that pops the
        # enum or the bounds).
        value = constraint["const"]
        catalogue_enum = catalogue_schema.get("enum")
        if catalogue_enum is not None and value not in catalogue_enum:
            raise _refuse(
                "classref_effective_schema_conflict",
                f"action {action_urn} field {property_name}: const {value!r} "
                f"outside the catalogue enum {list(catalogue_enum)!r}",
            )
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            for bound, edge in ((low_catalogue, "minimum"), (high_catalogue, "maximum")):
                if bound is None:
                    continue
                bound_value, exclusive = bound
                outside = (
                    value < bound_value or (exclusive and value == bound_value)
                    if edge == "minimum"
                    else value > bound_value or (exclusive and value == bound_value)
                )
                if outside:
                    raise _refuse(
                        "classref_effective_schema_conflict",
                        f"action {action_urn} field {property_name}: const "
                        f"{value!r} outside the catalogue {edge} {bound_value!r}",
                    )
        effective = {**effective, "const": value}
        effective.pop("enum", None)
        for keyword in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
            effective.pop(keyword, None)
    if "pattern" in constraint:
        effective["pattern"] = constraint["pattern"]
    # #541 W9 fold: string length bounds are inside the closed vocabulary
    # and INTERSECT like the numeric ones — the tighter end of each side
    # wins. An accepted keyword the intersection silently dropped would be
    # a narrowing the rendered control never sees; a length bound on a
    # non-string catalogue type is the same conflict the numeric bounds
    # raise.
    if "minLength" in constraint or "maxLength" in constraint:
        if declared_type != "string":
            raise _refuse(
                "classref_effective_schema_conflict",
                f"action {action_urn} field {property_name}: length bound "
                f"applied to catalogue type {declared_type!r}",
            )
        if "minLength" in constraint:
            current = effective.get("minLength")
            effective["minLength"] = (
                max(current, constraint["minLength"])
                if current is not None
                else constraint["minLength"]
            )
        if "maxLength" in constraint:
            current = effective.get("maxLength")
            effective["maxLength"] = (
                min(current, constraint["maxLength"])
                if current is not None
                else constraint["maxLength"]
            )
    if "type" in constraint:
        declared = catalogue_schema.get("type")
        wanted = constraint["type"]
        same_family = wanted == declared or (
            wanted in _NUMERIC_TYPES and declared in _NUMERIC_TYPES
        )
        if not same_family:
            raise _refuse(
                "classref_effective_schema_conflict",
                f"action {action_urn} field {property_name}: constraint type "
                f"{wanted!r} vs catalogue type {declared!r}",
            )
        effective["type"] = wanted
    return effective


def _check_admittance(
    action_urn: str, property_name: str, effective: dict[str, Any]
) -> None:
    """A field narrowed to an empty admittance set refuses (D13).

    M6: exclusivity is part of emptiness — a closed bound meeting an open
    bound at the same value admits nothing, in both crossing directions.
    #541 W5 fold: an empty declared enum is the same emptiness — a select
    that admits no value never derives, residual or catalogued alike; and
    inverted string length bounds (W9) admit no string either."""
    if effective.get("const") is not None:
        return
    enum_values = effective.get("enum")
    if isinstance(enum_values, list) and not enum_values:
        raise _refuse(
            "classref_effective_schema_empty",
            f"action {action_urn} field {property_name}: enum admits no value",
        )
    min_length = effective.get("minLength")
    max_length = effective.get("maxLength")
    if (
        isinstance(min_length, (int, float))
        and not isinstance(min_length, bool)
        and isinstance(max_length, (int, float))
        and not isinstance(max_length, bool)
        and min_length > max_length
    ):
        raise _refuse(
            "classref_effective_schema_empty",
            f"action {action_urn} field {property_name}: string length "
            "bounds admit no value",
        )
    if "minimum" in effective:
        low: tuple[float, bool] | None = (float(effective["minimum"]), False)
    elif "exclusiveMinimum" in effective:
        low = (float(effective["exclusiveMinimum"]), True)
    else:
        low = None
    if "maximum" in effective:
        high: tuple[float, bool] | None = (float(effective["maximum"]), False)
    elif "exclusiveMaximum" in effective:
        high = (float(effective["exclusiveMaximum"]), True)
    else:
        high = None
    if low is None or high is None:
        return
    if effective.get("type") not in _NUMERIC_TYPES:
        return
    empty = (
        low[0] > high[0]
        or (low[0] == high[0] and (low[1] or high[1]))
    )
    if empty:
        raise _refuse(
            "classref_effective_schema_empty",
            f"action {action_urn} field {property_name}: bounds admit no value",
        )


def _bounds_of(
    fragment: dict[str, Any],
) -> tuple[tuple[float, bool] | None, tuple[float, bool] | None]:
    """The fragment's declared numeric bounds as (value, exclusive) pairs,
    the exclusive spelling winning when both appear."""
    def _one(exclusive_key: str, plain_key: str) -> tuple[float, bool] | None:
        if exclusive_key in fragment:
            return float(fragment[exclusive_key]), True
        if plain_key in fragment:
            return float(fragment[plain_key]), False
        return None
    return _one("exclusiveMinimum", "minimum"), _one("exclusiveMaximum", "maximum")


def _check_value_types(
    action_urn: str, property_name: str, fragment: dict[str, Any]
) -> None:
    """A CONTROL keyword whose value is ill-typed refuses
    ``classref_constraint_unsupported`` (#541 G4 fold, 2026-10-22): W9
    admitted keywords to the closed vocabulary without validating their
    values, and `enum` under `minLength: "3"` crashed derive_ui with a
    bare TypeError (``len(value) < "3"`` in the narrowing). The rider
    covers every control keyword's value type — on the constraint side,
    the catalogue side and the row-descent side alike, wherever a
    fragment enters. `const` admits any JSON value: nothing orders or
    lens it before the row is minted."""
    def _refuse_value(keyword: str, wanted: str, value: Any) -> ValueError:
        return _refuse(
            "classref_constraint_unsupported",
            f"action {action_urn} field {property_name}: {keyword} "
            f"must be {wanted}, got {value!r}",
        )

    for keyword in (
        "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    ):
        if keyword in fragment:
            value = fragment[keyword]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise _refuse_value(keyword, "a number", value)
    for keyword in ("minLength", "maxLength"):
        if keyword in fragment:
            value = fragment[keyword]
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise _refuse_value(keyword, "a non-negative integer", value)
    if "pattern" in fragment and not isinstance(fragment["pattern"], str):
        raise _refuse_value("pattern", "a string", fragment["pattern"])
    if "enum" in fragment and not isinstance(fragment["enum"], list):
        raise _refuse_value("enum", "a list", fragment["enum"])
    if "type" in fragment:
        # The committed corpus's own nullable spelling is a type ARRAY
        # (JSON Schema's `type` array — `['number', 'null']` on the
        # function-generator class's load_ohm): admitted, consumed
        # inexpressible exactly as before this rider. A value that is
        # neither a string nor a non-empty list of strings keys no
        # consumer comparison anywhere in the module.
        value = fragment["type"]
        if not (
            isinstance(value, str)
            or (
                isinstance(value, list)
                and value
                and all(isinstance(item, str) for item in value)
            )
        ):
            raise _refuse_value("type", "a string or a list of strings", value)


def _check_residual_fragment(
    action_urn: str, name: str, fragment: dict[str, Any]
) -> None:
    """The residual mode's gates, applied at EVERY depth (#541 W2 fold):
    the closed keyword vocabulary, the empty-admittance refusal, and the
    bound/type conflicts the catalogued intersection raises — a fragment
    under ``properties``/``items`` is as much a declared constraint as a
    top-level one, and its catalogued twin refuses the same shape through
    ``_merge_deep``'s recursion."""
    for keyword in fragment:
        if (
            keyword in _CONSTRAINT_CONTROL_KEYWORDS
            or keyword in _CONSTRAINT_RIDER_KEYWORDS
        ):
            continue
        raise _refuse(
            "classref_constraint_unsupported",
            f"action {action_urn} field {name}: keyword {keyword!r} "
            "is outside the closed intersection vocabulary",
        )
    # G4 fold: value-typed before the admittance and bound checks —
    # _bounds_of floats and _check_admittance lens, and a string or
    # boolean length bound crashed or skipped silently before this.
    _check_value_types(action_urn, name, fragment)
    _check_admittance(action_urn, name, fragment)
    declared_type = fragment.get("type")
    value_typed = "enum" in fragment or "const" in fragment
    low, high = _bounds_of(fragment)
    if (
        (low is not None or high is not None)
        and declared_type is not None
        and declared_type not in _NUMERIC_TYPES
        and not value_typed
    ):
        # #541 W3 fold: numeric bounds on a declared non-numeric type are a
        # self-contradiction — the catalogued twin refuses the same shape
        # when a constraint's bounds meet a non-numeric catalogue type. A
        # fragment carrying enum/const is handled at row time, where the
        # declared values intersect the bounds.
        raise _refuse(
            "classref_effective_schema_conflict",
            f"action {action_urn} field {name}: numeric bound "
            f"applied to declared type {declared_type!r}",
        )
    if (
        ("minLength" in fragment or "maxLength" in fragment)
        and declared_type is not None
        and declared_type != "string"
        and not value_typed
    ):
        raise _refuse(
            "classref_effective_schema_conflict",
            f"action {action_urn} field {name}: length bound "
            f"applied to declared type {declared_type!r}",
        )
    for sub_name, sub in (fragment.get("properties") or {}).items():
        if not isinstance(sub, dict):
            raise _refuse(
                "classref_constraint_unsupported",
                f"action {action_urn} field {name}.{sub_name}: constraint "
                "fragment must be an object",
            )
        _check_residual_fragment(action_urn, f"{name}.{sub_name}", sub)
    items = fragment.get("items")
    if isinstance(items, dict):
        _check_residual_fragment(action_urn, f"{name}[]", items)


def _intersect_declared_values(
    action_urn: str, property_name: str, fragment: dict[str, Any]
) -> None:
    """A fragment declaring a value set (enum/const) under declared bounds
    renders exactly the values both admit (#541 W3 fold — the acceptance
    rule's own KILL (d) shape: the generic surface admits what the
    declaration admits, no more). A non-empty enum NARROWS to the admitted
    subset; an emptied one refuses under the §8 empty-admittance survivor;
    a const outside the bounds is a conflict, never a silently dropped
    bound. Applied where rows are minted, so every path (catalogue row,
    intersection, residual) gets it at every depth; the conjunctive
    validation schemas keep both keywords untouched."""
    low, high = _bounds_of(fragment)
    min_length = fragment.get("minLength")
    max_length = fragment.get("maxLength")
    if (
        low is None and high is None
        and min_length is None and max_length is None
    ):
        return

    def _admitted(value: Any) -> bool:
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        if low is not None or high is not None:
            if not numeric:
                return False
            if low is not None:
                edge, exclusive = low
                if value < edge or (exclusive and value == edge):
                    return False
            if high is not None:
                edge, exclusive = high
                if value > edge or (exclusive and value == edge):
                    return False
        if min_length is not None or max_length is not None:
            if not isinstance(value, str):
                return False
            if min_length is not None and len(value) < min_length:
                return False
            if max_length is not None and len(value) > max_length:
                return False
        return True

    if "const" in fragment:
        if not _admitted(fragment["const"]):
            raise _refuse(
                "classref_effective_schema_conflict",
                f"action {action_urn} field {property_name}: const "
                f"{fragment['const']!r} outside the declared bounds",
            )
        return
    enum_values = fragment.get("enum")
    if isinstance(enum_values, list) and enum_values:
        allowed = [value for value in enum_values if _admitted(value)]
        if not allowed:
            raise _refuse(
                "classref_effective_schema_empty",
                f"action {action_urn} field {property_name}: every declared "
                "enum value falls outside the declared bounds",
            )
        if allowed != enum_values:
            fragment["enum"] = allowed


def _effective_action_schema(
    action_urn: str,
    catalogue_action: dict[str, Any] | None,
    constraints: dict[str, Any],
) -> dict[str, Any]:
    """The action's effective input schema: catalogue AND descriptor
    constraints, per property (D13). Validation lanes stay conjunctive and
    untouched; this derives per-field admittance for control rendering.

    #541 layer 3: a None catalogue row is the residual mode — no served
    catalog describes the action, so the effective schema is the
    descriptor's own constraints, still gated by the same closed keyword
    vocabulary and the same empty-admittance refusal. The SDK invents no
    admittance a catalogue granted; it renders the plugin's own declared
    constraints and the plan row carries resolution "custom"."""
    properties: dict[str, Any] = {}
    required: set[str] = set()
    if catalogue_action is not None:
        catalogue_input = catalogue_action.get("input_schema", {}) or {}
        # Deep-copy: the served catalog is cached module state shared across
        # runs; the intersection must never narrow the served bytes in place.
        catalogue_input = json.loads(json.dumps(catalogue_input))
        properties = {
            name: dict(schema)
            for name, schema in (catalogue_input.get("properties") or {}).items()
            if isinstance(schema, dict)
        }
        required = set(catalogue_input.get("required") or ())
        # G4 fold: the catalogue side validates too — a served or
        # vendor-pinned row with an ill-typed control value refuses typed
        # where it enters, never at the row descent's crash.
        for name, schema in properties.items():
            _check_value_types(action_urn, name, schema)
    constraint_properties = constraints.get("properties") or {}
    for keyword in constraints:
        if keyword in _CONSTRAINT_CONTROL_KEYWORDS or keyword in _CONSTRAINT_RIDER_KEYWORDS:
            continue
        raise _refuse(
            "classref_constraint_unsupported",
            f"action {action_urn}: top-level keyword {keyword!r} is outside the "
            "closed intersection vocabulary",
        )
    for name, fragment in constraint_properties.items():
        if not isinstance(fragment, dict):
            raise _refuse(
                "classref_constraint_unsupported",
                f"action {action_urn} field {name}: constraint fragment must be "
                "an object",
            )
        base = properties.get(name)
        if base is None and catalogue_action is None:
            # Residual: no catalogue side exists to intersect — the
            # declared fragment IS the effective schema, verbatim, after
            # the same closed-vocabulary and admittance gates — applied at
            # EVERY depth (#541 W2 fold): a nested fragment under
            # properties/items is as much a declared constraint as a
            # top-level one, and its catalogued twin refuses the same
            # shapes through the recursive intersection (_merge_deep).
            # Slice 2's composed classes need the same recursion — their
            # declared input_schema must not reopen the gap this closes.
            _check_residual_fragment(action_urn, name, fragment)
            properties[name] = json.loads(json.dumps(fragment))
            continue
        if base is None:
            base = {"type": fragment.get("type", "object")}
            properties[name] = base
        if "properties" in fragment or "items" in fragment:
            properties[name] = _merge_deep(action_urn, name, base, fragment)
        else:
            properties[name] = _intersect_property(
                action_urn, name, base, fragment
            )
            _check_admittance(action_urn, name, properties[name])
    required.update(constraints.get("required") or ())
    return {"properties": properties, "required": sorted(required)}


def _merge_deep(
    action_urn: str, prefix: str, base: dict[str, Any], fragment: dict[str, Any]
) -> dict[str, Any]:
    """Intersect nested ``properties``/``items`` shapes one level at a time."""
    effective = dict(base)
    constraint_props = fragment.get("properties") or {}
    base_props = dict(base.get("properties") or {})
    items_fragment = fragment.get("items")
    if isinstance(items_fragment, dict) and "properties" in items_fragment:
        items_base = dict(base.get("items") or {"type": "object"})
        effective["items"] = _merge_deep(
            action_urn, f"{prefix}[]", items_base, items_fragment
        )
    for name, sub in constraint_props.items():
        sub_base = dict(base_props.get(name) or {"type": sub.get("type", "object")})
        if "properties" in sub or "items" in sub:
            effective.setdefault("properties", {})[name] = _merge_deep(
                action_urn, f"{prefix}{name}.", sub_base, sub
            )
        else:
            merged = _intersect_property(action_urn, f"{prefix}{name}", sub_base, sub)
            _check_admittance(action_urn, f"{prefix}{name}", merged)
            effective.setdefault("properties", {})[name] = merged
    if "required" in fragment:
        effective["required"] = sorted(
            set(effective.get("required") or ()) | set(fragment["required"])
        )
    return effective


def _row_mode(fragment: dict[str, Any]) -> str | None:
    """The field-row mode one property fragment renders, or None when the
    fragment is inexpressible: a pattern-narrowed string admits values no
    staging control can enumerate, so it derives no row and keeps its
    action off L2 (RC-L5-3/4, the closed intersection vocabulary)."""
    if fragment.get("const") is not None:
        return "const"
    if fragment.get("enum") is not None:
        return "enum"
    declared = fragment.get("type")
    if declared == "string":
        return None if "pattern" in fragment else "text"
    if declared == "boolean":
        return "boolean"
    if declared in _NUMERIC_TYPES:
        return "numeric"
    return None


def _field_rows(
    action_urn: str,
    prefix: str,
    schema: dict[str, Any],
    _seen: set[str] | None = None,
) -> list[dict[str, Any]]:
    """The renderable field rows (numeric bounds / const / enum / text /
    boolean) of one effective schema, descending array items and object
    properties. A pattern-narrowed string emits no row (inexpressible).

    Fully-qualified field names are REFUSED on collision: dotted flattening
    gives a nested ``a``→``b`` and a flat property literally named ``a.b``
    the same name, and two rows under one name render two controls for one
    declared field. The collision refuses typed, naming the field."""
    rows: list[dict[str, Any]] = []
    seen = _seen if _seen is not None else set()
    for name, sub in (schema.get("properties") or {}).items():
        full = f"{prefix}{name}"
        # #541 W3 fold: a declared value set under declared bounds narrows
        # here — one mechanism for every path a fragment arrives by
        # (catalogue row, intersection, residual), at every depth this
        # descent visits. The #541 G4 fold value-types the fragment first:
        # a nested catalogue fragment reaches this descent too, and an
        # ill-typed value refuses here rather than crashing the narrowing.
        _check_value_types(action_urn, full, sub)
        _intersect_declared_values(action_urn, full, sub)
        mode = _row_mode(sub)
        if mode is not None:
            if full in seen:
                raise _refuse(
                    "classref_duplicate_field",
                    f"{action_urn} mints field {full!r} from two schema paths "
                    "(a nested object/array descent and a literal property "
                    "name collide after qualification)",
                )
            seen.add(full)
            row: dict[str, Any] = {"field": full, "mode": mode}
            if mode == "const":
                row["const"] = sub["const"]
            elif mode == "enum":
                row["enum"] = sub["enum"]
            elif mode == "text":
                for keyword in ("minLength", "maxLength"):
                    if keyword in sub:
                        row[keyword] = sub[keyword]
            elif mode == "numeric":
                for keyword in (
                    "minimum", "maximum", "multipleOf",
                    "exclusiveMinimum", "exclusiveMaximum",
                ):
                    if keyword in sub:
                        row[keyword] = sub[keyword]
            rows.append(row)
        if isinstance(sub.get("properties"), dict):
            rows.extend(
                _field_rows(action_urn, f"{full}.", sub, seen)
            )
        if isinstance(sub.get("items"), dict) and isinstance(
            sub["items"].get("properties"), dict
        ):
            rows.extend(
                _field_rows(action_urn, f"{full}[].", sub["items"], seen)
            )
    return rows


def _ladder_level(
    effective: dict[str, Any], host_supplied: frozenset[str], slot_kind: str | None
) -> str:
    """The reachability ladder (record §2.5), evaluated first-match.

    A configuration slot's action is L3 (preset-mediated); a dataset slot's
    action is L4 (dataset binding + plot/table). Otherwise the effective
    required set (minus the acquisition-lifecycle names the host supplies)
    decides: empty L1 (bare button), all-required-expressible L2 (staging —
    the L5 widening: a field is expressible when the derivation renders it,
    numeric, text, enum, const or boolean; a pattern-narrowed string stays
    inexpressible), and anything else L0 (declared deviation required)."""
    if slot_kind == "configuration":
        return "L3"
    if slot_kind == "dataset":
        return "L4"
    required = [name for name in effective["required"] if name not in host_supplied]
    if not required:
        return "L1"
    schemas = effective["properties"]
    if all(
        _row_mode(schemas.get(name, {})) is not None for name in required
    ):
        return "L2"
    return "L0"


_SLOT_LEVEL_MATCH = {"button": "L1", "staging": "L2", "preset": "L3"}


def _catalogue_row(
    action_urn: str, catalog_actions: dict[str, Any]
) -> dict[str, Any] | None:
    """One action's served catalogue row, or None (#541 W4 fold). A key
    ABSENT from the map is the residual mode — no served catalog describes
    the action. A key PRESENT with a non-object row is a malformed catalog
    entry and refuses typed: reading it as "no catalog" would mint a false
    ``custom`` provenance (and the pre-split code crashed on it with a bare
    AttributeError downstream)."""
    if action_urn not in catalog_actions:
        return None
    row = catalog_actions[action_urn]
    if not isinstance(row, dict):
        raise _refuse(
            "classref_catalog_row_invalid",
            f"the served catalog describes {action_urn} with a "
            f"{type(row).__name__} row, not an object",
        )
    return row


def _derive_controls(
    actions: dict[str, Any],
    catalog_actions: dict[str, Any],
    slot_for_urn: dict[str, tuple[str, dict[str, Any]]],
    page_for_slot: dict[str, str],
    intended_controls: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """Per-action ladder level + renderable fields + intended divergence.

    A divergence between the reference's intended control (``expect.controls``)
    and the derived ladder level requires a declared deviation (record §3.9);
    the expander mints the expectation id and the declaration scaffold carries
    it, so the ledger and the derivation cannot disagree."""
    plan: dict[str, dict[str, Any]] = {}
    divergences: list[dict[str, str]] = []
    for urn in sorted(actions):
        raw_constraints = actions[urn].get("input_constraints")
        constraints = raw_constraints or {}
        slot_kind = None
        host_supplied: frozenset[str] = frozenset(_HOST_SUPPLIED_UNIVERSAL)
        _slot_name, slot = slot_for_urn.get(urn, ("", {}))
        if slot:
            slot_kind = str(slot.get("kind"))
            if slot_kind != "vendor_actions":
                host_supplied = frozenset(slot.get("host_supplied") or ())
        # #541 three-layer resolution (record §3): a catalogue row (served
        # OTDP or pinned vendor) resolves layer 1; no row at all resolves
        # layer 3 — the residual member derives from the descriptor's own
        # constraints, never refuses for being unknown. Slice 2 adds the
        # composed layer between them: a row the composed walk injected is
        # layer 2 — the class document supplied the catalogue side, and
        # the row names the class (its URN carries the class's version).
        # The value names the layer that produced the row (record §4.1 —
        # provenance is data, not a log).
        catalogue_row = _catalogue_row(urn, catalog_actions)
        composed_of = (
            catalogue_row.get("composed_class")
            if catalogue_row is not None
            else None
        )
        composed_side_effect = (
            catalogue_row.get("side_effect")
            if catalogue_row is not None
            else None
        )
        if composed_of is not None:
            resolution = "composed"
        elif catalogue_row is not None:
            resolution = "catalog"
        else:
            resolution = "custom"
        effective = _effective_action_schema(urn, catalogue_row, constraints)
        level = _ladder_level(effective, host_supplied, slot_kind)
        # #541 W7 fold: "declares nothing" and "declares no inputs" are
        # different states. A residual action whose input_constraints
        # carries no properties key at all declared NOTHING — silence must
        # not become a one-click dispatch (an L1 button), so it derives L0
        # with a disclosure naming the absence. An explicit properties
        # (even {}) declared no inputs, and the ladder reads it as before.
        declared_no_input = not (
            isinstance(raw_constraints, dict) and "properties" in raw_constraints
        )
        if catalogue_row is None and declared_no_input:
            level = "L0"
        fields = _field_rows(urn, "", effective)
        slot_key = _slot_name if slot else ""
        page = page_for_slot.get(slot_key, "device-features")
        row: dict[str, Any] = {
            "level": level,
            "page": page,
            "fields": fields,
            "resolution": resolution,
        }
        if composed_of is not None:
            # The class's declared side_effect rides the plan row (record
            # §6): it is evidence about the action, consumed by the gate's
            # D7 arms — {abort-slug actions} ∪ {actions whose class
            # declares energy_removing} — replacing the slug guess where
            # a declaration is present.
            row["class"] = composed_of
            row["side_effect"] = composed_side_effect
        if catalogue_row is None and declared_no_input:
            row["input_undeclared"] = True
        intended = intended_controls.get(urn)
        if intended is not None and _SLOT_LEVEL_MATCH.get(intended) != level:
            row["intended"] = intended
            row["divergence"] = (
                f"intended {intended} but derived {level}"
            )
            divergences.append(
                {"expectation_id": urn, "reason": row["divergence"]}
            )
        # The preset surface's birth deviation (A02: presets are commissioned
        # evidence) rides every configuration action's plan row.
        row["declared_deviation"] = (
            bool(intended == "deviation")
            or level == "L0"
            or slot_kind == "configuration"
        )
        plan[urn] = row
    return plan, divergences




def derive_ui(
    descriptor_raw: bytes,
    reference: dict[str, Any] | list[dict[str, Any]],
    *,
    descriptor_path: Path | None = None,
) -> DerivedUI:
    """Expand (descriptor, reference) into the plugin-ui document set.

    Multi-profile devices pass a list: references merge under one ownership
    domain (first profile's ids stay bare; later profiles prefix their
    page ids with the profile slug; ``classref_profile_slot_conflict`` on a
    URN claimed by named slots in two references)."""
    descriptor = json.loads(descriptor_raw)
    validate_descriptor(descriptor)
    references = [reference] if isinstance(reference, dict) else list(reference)
    references = [_validate_reference(item) for item in references]
    references.sort(key=lambda item: str(item["profile_id"]))
    _check_slot_conflicts(references)
    for item in references:
        profile = str(item["profile_id"])
        if profile not in (descriptor.get("profiles") or []):
            raise _refuse(
                "classref_invalid_reference",
                f"profile {profile} is not claimed by the descriptor",
            )
    for item in references:
        if not _satisfies_target(active_version("plugin-ui"), item["targets"]["plugin_ui"]):
            raise _refuse(
                "classref_target_version",
                f"active plugin-ui {active_version('plugin-ui')} does not satisfy "
                f"the reference target {item['targets']['plugin_ui']}",
            )
    catalog = _catalog_documents(descriptor)
    catalog_actions: dict[str, Any] = dict(catalog.get("actions", {}))
    (
        vendor_actions,
        _composed,
        ignored_pins,
        unapplied,
        empty_pins,
        member_declarations,
    ) = _vendor_documents(descriptor, descriptor_path, catalog_actions)
    catalog_actions.update(vendor_actions)
    # #556 §3 rule 1: the applied member set (per vocabulary) and the pins
    # whose members applied nowhere — computed from the descriptor here so
    # every consumer (the ledger, the gate's REPORTED channel) reads ONE
    # derivation of application.
    composed_members, unapplied_member_pins = _composed_member_inventory(
        member_declarations, descriptor
    )
    actions = descriptor.get("actions") or {}
    # #541 layer 3: a descriptor action no served catalog describes is a
    # residual member, not a refusal — it derives from the descriptor's own
    # input_constraints and its plan row carries resolution "custom". The
    # reference-slot site below keeps refusing (D4): a class's own slot
    # naming an unserved URN is a corpus fault, not a vendor gap.
    for item in references:
        slot_keys = set(item.get("slots", {}))
        for page in item.get("pages", []):
            unknown = [key for key in page.get("binding_slots", []) if key not in slot_keys]
            if unknown:
                raise _refuse(
                    "classref_unknown_slot",
                    f"page {page.get('id')!r} binds unknown slot(s) "
                    f"{', '.join(sorted(unknown))}",
                )
    # M7: the §3.8 merge path checks EVERY claimed profile's required
    # actions — the sort order must not decide which profile gets checked.
    for item in references:
        row = _profile_row(catalog, [item])
        for urn in row.get("required_actions", []):
            if urn not in actions:
                raise _classref_required_absent(urn)
    for item in references:
        for key, slot in item.get("slots", {}).items():
            urn = slot.get("action")
            if urn and urn not in catalog_actions:
                raise _refuse(
                    "classref_unknown_action",
                    f"slot {key} names {urn}, absent from the served catalogs",
                )
    return _assemble(
        descriptor, references, actions, catalog_actions,
        descriptor_path=descriptor_path, descriptor_raw=descriptor_raw,
        ignored_pins=ignored_pins, unapplied_classes=unapplied,
        empty_action_pins=empty_pins,
        member_declarations=member_declarations,
        composed_members=composed_members,
        unapplied_member_pins=unapplied_member_pins,
    )


def _check_slot_conflicts(references: list[dict[str, Any]]) -> None:
    seen: dict[str, str] = {}
    for item in references:
        for key, slot in item.get("slots", {}).items():
            urn = slot.get("action")
            if not urn:
                continue
            if urn in seen and seen[urn] != key:
                raise _refuse(
                    "classref_profile_slot_conflict",
                    f"{urn} claimed by slots {seen[urn]!r} and {key!r}",
                )
            seen[urn] = key


def _profile_row(
    catalog: dict[str, Any], references: list[dict[str, Any]]
) -> dict[str, list[str]]:
    profiles = catalog.get("profiles", [])
    rows = {
        str(row.get("id")): row
        for row in profiles
        if isinstance(row, dict) and row.get("id")
    }
    for item in references:
        profile_id = str(item["profile_id"])
        if profile_id not in rows:
            # #541 record §1: a platform fault — the profile catalog is
            # served but carries no row for this profile.
            raise _refuse(
                "classref_profile_absent",
                f"profile {profile_id} absent from the served profile catalog",
            )
    first: dict[str, Any] = rows[references[0]["profile_id"]]
    return first


def _classref_required_absent(urn: str) -> ValueError:
    return _refuse(
        "classref_required_action_absent",
        f"required-class action {urn} is not declared by the descriptor",
    )




def _merge_references(references: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic multi-profile merge (record §3.8): sorted bytewise by
    profile id; the first reference keeps bare ids, every later one prefixes
    page ids and binding ids with its profile slug; layouts prefix to match."""
    merged: dict[str, Any] = {
        "slots": {},
        "pages": [],
        "layouts": [],
        "expect": {"components": {}, "controls": {}, "forbid": []},
        "cannot_derive": [],
    }
    for index, item in enumerate(references):
        slug = ""
        if index > 0:
            slug = str(item["profile_id"]).split("/")[0].replace(".", "-")
        slot_map: dict[str, str] = {}
        for key, slot in item.get("slots", {}).items():
            merged["slots"][f"{slug}-{key}" if slug else key] = slot
            slot_map[key] = f"{slug}-{key}" if slug else key
        for page in item.get("pages", []):
            row = dict(page)
            if slug:
                row["id"] = f"{slug}-{page['id']}"
            row["bindings"] = [
                slot_map.get(key, key) for key in page.get("binding_slots", [])
            ]
            row["_slot_keys"] = list(page.get("binding_slots", []))
            merged["pages"].append(row)
        for layout_page in item.get("layouts", []):
            row = dict(layout_page)
            if slug:
                row["page_id"] = f"{slug}-{layout_page['page_id']}"
            merged["layouts"].append(row)
        for name, row in item.get("expect", {}).get("components", {}).items():
            merged["expect"]["components"][name] = dict(row)
        for urn, intended in item.get("expect", {}).get("controls", {}).items():
            merged["expect"]["controls"][urn] = intended
        merged["expect"]["forbid"].extend(item.get("expect", {}).get("forbid", []))
        merged["cannot_derive"].extend(item.get("cannot_derive", []))
    return merged


def _channels_slot(merged: dict[str, Any]) -> dict[str, Any] | None:
    """The ONE channels slot this derivation resolves lanes for — the first
    in merge order (#556 B1 keeps the founding one-slot rule; the per-slot
    channels generalization is a later slice). ``residual_members`` uses it to
    name the one role a channel can still resolve against."""
    return next(
        (slot for slot in merged["slots"].values() if slot.get("kind") == "channels"),
        None,
    )


def _resolve_channels(descriptor: dict[str, Any], merged: dict[str, Any]) -> list[dict[str, Any]]:
    """The class-role lanes, in declaration order; fail-closed count
    refusals (record §3.3)."""
    slot = _channels_slot(merged)
    if slot is None:
        return []
    role = str(slot.get("where_role", ""))
    lanes = [row for row in descriptor.get("channels", []) if str(row.get("role")) == role]
    if not lanes:
        raise _refuse("classref_no_lanes", "0 channels carry role " + role)
    if len(lanes) > _LANE_CEILING:
        raise _refuse(
            "classref_lane_ceiling",
            f"{len(lanes)} channels carry role {role} (ceiling {_LANE_CEILING})",
        )
    return lanes


def _assemble(
    descriptor: dict[str, Any],
    references: list[dict[str, Any]],
    actions: dict[str, Any],
    catalog_actions: dict[str, Any],
    descriptor_path: Path | None = None,
    descriptor_raw: bytes | None = None,
    ignored_pins: tuple[str, ...] = (),
    unapplied_classes: tuple[tuple[str, str], ...] = (),
    empty_action_pins: tuple[str, ...] = (),
    member_declarations: tuple[ComposedMemberDeclaration, ...] = (),
    composed_members: Mapping[str, tuple[dict[str, str], ...]] | None = None,
    unapplied_member_pins: tuple[str, ...] = (),
) -> DerivedUI:
    version = active_version("plugin-ui")
    merged = _merge_references(references)
    # #556 §3 rule 4: the reference-side member conflicts run over the
    # MERGED reference (final page ids and slot keys) and before any
    # member injects — the composed slot composes beside the reference,
    # never over it.
    _check_member_reference_conflicts(merged, member_declarations)
    lanes = _resolve_channels(descriptor, merged)
    slot_for_urn = {
        slot["action"]: (key, slot)
        for key, slot in merged["slots"].items()
        if slot.get("action")
    }
    page_for_slot: dict[str, str] = {}
    for page in merged["pages"]:
        for key in page.get("_slot_keys", []):
            page_for_slot.setdefault(key, str(page["id"]))
    plan, divergences = _derive_controls(
        actions, catalog_actions, slot_for_urn, page_for_slot,
        merged["expect"]["controls"],
    )
    plot_page = next(
        (
            str(page["id"])
            for page in merged["pages"]
            if page.get("plot")
        ),
        "",
    )
    for urn in actions:
        if urn.split("/")[0].rsplit(".", 1)[-1] != "decode_annotated":
            continue
        if descriptor.get("decoders") and plot_page:
            plan[urn] = {
                **plan[urn],
                "level": "L4",
                "page": plot_page,
                "fields": [],
                "declared_deviation": False,
                # R9 (#541 slice 3 fold): the "rendered_by" advertisement is
                # stamped in _finish, after the plots exist — a row claims a
                # rendering only when that rendering occurs.
            }
    return _finish(
        descriptor, references, merged, lanes, actions, catalog_actions,
        plan, divergences, version, descriptor_path=descriptor_path,
        descriptor_file_raw=descriptor_raw,
        ignored_pins=ignored_pins, unapplied_classes=unapplied_classes,
        empty_action_pins=empty_action_pins,
        composed_members=composed_members or {},
        unapplied_member_pins=unapplied_member_pins,
    )


def residual_members(
    descriptor: dict[str, Any],
    derived_decoder_ids: Iterable[str],
    *,
    channel_roles: Iterable[str] = (),
    dataset_variables: Mapping[str, Collection[str]] | None = None,
    series_overflow: Mapping[str, Collection[str]] | None = None,
    plot_kinds: Iterable[str] = (),
) -> tuple[ResidualMember, ...]:
    """(#541 slice 3 fold R10; #556 Track B §3 rule 3) declared members whose
    surface the derivation owes an account of, as REPORTED rows.

    Layer 3's promise is two-sided — never refuses AND never silent. Silence
    is indistinguishable from "we rendered it and it looked fine", so every
    declared member lands either a derived surface or a row here.

    Computed variables (``derived_variables``, the measurement vocabulary
    measurement-model.md §8 owns — V2): since #556 B1 the derivation composes
    them into every dataset target's variable set (``_dataset_shape``), so
    their row is a COMPOSED-STATE disclosure, never a deferral: it states the
    surface that exists and the one that must not (a tile names a
    ``parameter_id``; a computed variable has no parameter to read). When no
    dataset target derives — the reference-less arm, or a class with no
    dataset slot — the row states that terminal state instead of claiming a
    dataset variable no wire carries. A computed id that collides with ANY
    variable id a dataset's wire shape already carries — the axis, a lane, a
    quantity or a trace variable — cannot be composed into that dataset (the
    emitted variable set would carry a duplicate id); the row names the id's
    targets. A composed series the plot kind's ``y`` ceiling forces off the
    plot is named too: the variable still derives into the dataset, the plot
    just cannot carry it inside the manifest schema.

    Decoders (V3): ``derived_decoder_ids`` is the set whose lanes a derived
    PLOT carries, never the set that was BUILT — the lane machinery can build
    lanes that no plot hosts (a waveform or time-series plot has no
    ``decoder_lanes`` key; they land in a digital-lanes plot alone), and
    building is not rendering. ``plot_kinds`` is the kinds the derived plots
    carry, so the row can name the structural reason lanes did not land.

    Channels (V3, #556 B1): a channel whose role matches no channels slot the
    derivation resolves lanes for derives nothing, and used to disappear
    without a word anywhere. It now reports every run against
    ``channel_roles`` — the role(s) the run actually resolved lanes for — and
    a channel that resolves never reports.
    """
    rows: list[ResidualMember] = []
    base_ids = dict(dataset_variables or {})
    overflow = dict(series_overflow or {})
    for row in descriptor.get("derived_variables") or []:
        member = str(row.get("id", "")) if isinstance(row, dict) else ""
        if not member:
            continue
        rows.append(
            ResidualMember(
                "observation variable",
                "observation variables",
                member,
                _computed_variable_detail(member, base_ids, overflow),
            )
        )
    resolved_roles = {str(role) for role in channel_roles}
    for row in descriptor.get("channels") or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        role = str(row.get("role", ""))
        if role in resolved_roles:
            continue
        rows.append(
            ResidualMember(
                "channel",
                "channels and decoders",
                f"{row['id']} (role {role})",
                "resolves to no lanes surface",
            )
        )
    derived_ids = {str(value) for value in derived_decoder_ids}
    decoder_detail = _decoder_no_host_detail(plot_kinds)
    for pin in descriptor.get("decoders") or []:
        member = str(pin.get("id", "")) if isinstance(pin, dict) else ""
        if member and member not in derived_ids:
            rows.append(
                ResidualMember(
                    "custom decoder",
                    "channels and decoders",
                    member,
                    decoder_detail,
                )
            )
    return tuple(rows)


def _decoder_no_host_detail(plot_kinds: Iterable[str]) -> str:
    """V3's decoder row detail (#556 Track B §4 V3 layer 3): the structural
    reason the decoder's lanes have no host.

    The canonical manifest schema admits ``decoder_lanes`` on a
    ``digital_lanes`` plot alone (the 0.4.0 ``$defs.plot`` allOf bans them on
    the analog kinds), so only a class whose plot IS digital_lanes can host a
    decoder at all. When such a plot derives and the lanes still do not land,
    the reason is not the kind — the row says no derived plot carries them
    rather than blaming a plot kind that admits them.
    """
    kinds = sorted({str(kind) for kind in plot_kinds if kind})
    if not kinds or "digital_lanes" in kinds:
        return (
            "no lane host (no derived plot carries its lanes; lanes host in "
            "digital_lanes plots alone)"
        )
    if len(kinds) == 1:
        return (
            f"no lane host (this class's plot is {kinds[0]}; lanes host in "
            "digital_lanes plots alone)"
        )
    return (
        f"no lane host (this class's plots are {', '.join(kinds)}; lanes host "
        "in digital_lanes plots alone)"
    )


def _computed_variable_detail(
    member: str,
    dataset_variables: Mapping[str, Collection[str]],
    series_overflow: Mapping[str, Collection[str]],
) -> str:
    """V2's row detail (#556 Track B §4 V2), naming what the computed
    variable actually derives into and what it was dropped from.

    ``dataset_variables`` maps each derived dataset target's id to the
    variable ids its wire shape carries WITHOUT the computed rows — the
    axis, the lane or the quantity/trace variables. A target whose base set
    already holds the computed id cannot compose it: the dataset shape would
    then hold two rows with one id, which the canonical validator refuses
    (``contracts.py::_unique_rows``).

    ``series_overflow`` maps a target whose PLOT ``y`` set the kind's schema
    ceiling forced to drop composed series, to the ids dropped. The variable
    still derives into the dataset's variable set — the wire carries it —
    but the plot cannot show it without breaching the manifest schema
    (``ui-manifest.schema.json`` allOf: time_series/waveform ``y.maxItems``
    16, mirrored by ``_PLOT_SERIES_CEILING``).
    """
    if not dataset_variables:
        return (
            "computes no dataset variable (no dataset target derives); "
            "no tile (no parameter to read)"
        )
    collided = sorted(
        target for target, ids in dataset_variables.items() if member in ids
    )
    total = len(dataset_variables)
    if len(collided) == total:
        detail = (
            f"id collides with a dataset variable on {', '.join(collided)}; "
            "no tile (no parameter to read)"
        )
    elif collided:
        detail = (
            f"id collides with a dataset variable on {', '.join(collided)}; "
            f"derives into {total - len(collided)} of {total} dataset targets "
            "(no tile; no parameter to read)"
        )
    else:
        detail = (
            "computed variable derives into dataset variables "
            "(no tile; no parameter to read)"
        )
    overflow = sorted(
        target for target, ids in series_overflow.items() if member in ids
    )
    if overflow:
        detail += (
            f"; no plot series on {', '.join(overflow)} (the plot's y admits "
            f"{_PLOT_SERIES_CEILING} numeric series)"
        )
    return detail


def _finish(
    descriptor: dict[str, Any],
    references: list[dict[str, Any]],
    merged: dict[str, Any],
    lanes: list[dict[str, Any]],
    actions: dict[str, Any],
    catalog_actions: dict[str, Any],
    plan: dict[str, dict[str, Any]],
    divergences: list[dict[str, str]],
    version: str,
    descriptor_path: Path | None = None,
    descriptor_file_raw: bytes | None = None,
    ignored_pins: tuple[str, ...] = (),
    unapplied_classes: tuple[tuple[str, str], ...] = (),
    empty_action_pins: tuple[str, ...] = (),
    composed_members: Mapping[str, tuple[dict[str, str], ...]] | None = None,
    unapplied_member_pins: tuple[str, ...] = (),
) -> DerivedUI:
    """Assemble every emitted document from the resolved inventory."""
    import hashlib

    # M4: the envelope pins the FILE bytes (the legacy path's discipline),
    # never re-serialised virtual bytes — a non-canonical descriptor file
    # still yields a pin check-ui accepts.
    pin_bytes = descriptor_file_raw if descriptor_file_raw is not None else (
        json.dumps(descriptor, indent=2) + "\n"
    ).encode()
    descriptor_hash = hashlib.sha256(pin_bytes).hexdigest()
    profile_ids = sorted({str(row["profile_id"]) for row in references})

    bindings: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    {
        slot["action"]: (key, slot)
        for key, slot in merged["slots"].items()
        if slot.get("action")
    }
    dataset_slots = {
        key: slot
        for key, slot in merged["slots"].items()
        if slot.get("kind") == "dataset"
    }
    capture_key = next(iter(dataset_slots), None)
    capture_slot: dict[str, Any] = dataset_slots.get(capture_key or "", {})
    measurement_id = next(
        (
            str(row["id"])
            for row in descriptor.get("contracts", [])
            if str(row.get("id", "")).startswith("urn:otdp:measurement")
        ),
        f"urn:otdp:measurement:{descriptor['otdp_version']}",
    )
    # The wire's logic alphabet renders as string/vector samples; the time
    # axis is a vector in seconds (the vendored digital_lanes plot rules).
    lane_vars = [
        {"id": row["id"], "type": "string", "unit": None, "shape": "vector"}
        for row in lanes
    ]
    x_var = {
        "id": "t", "type": "number", "unit": "s",
        "shape": "vector", "axis_role": "x",
    }
    # The plot kind each dataset slot serves, from the reference's page
    # templates (the 0.3.0 vocabulary widening): a slot's variables are the
    # wire shape its kind declares — the digital_lanes logic alphabet, the
    # scalar variables of a measure dataset (one per channel and declared
    # quantity), or the array-valued traces of a waveform dataset over the
    # explicit time axis. A slot with no plot keeps the founding shape.
    plot_kind_for_slot: dict[str, str] = {}
    for page in merged["pages"]:
        spec = page.get("plot")
        if spec:
            plot_kind_for_slot.setdefault(
                str(spec.get("over_slot", "")),
                str(spec.get("kind", "digital_lanes")),
            )
    readings_slots = {
        key
        for page in merged["pages"]
        if str(page.get("kind", "readings")) == "readings"
        for key in page.get("_slot_keys", [])
        if key in dataset_slots
    }
    parameter_rows = (
        _resolve_parameters(descriptor, lanes) if readings_slots else {}
    )
    quantity_vars: list[dict[str, Any]] = [
        {
            "id": f"{row['id']}-{quantity}",
            "type": "number",
            "unit": (parameter_rows.get((str(row["id"]), str(quantity))) or {}).get(
                "unit"
            ),
            "shape": "scalar",
            "axis_role": "value",
        }
        for row in lanes
        for quantity in row.get("quantities") or []
    ]
    trace_vars: list[dict[str, Any]] = [
        {
            "id": f"{row['id']}-{quantity}",
            "type": "number",
            "unit": (parameter_rows.get((str(row["id"]), str(quantity))) or {}).get(
                "unit"
            ),
            "shape": "vector",
        }
        for row in lanes
        for quantity in row.get("quantities") or []
    ]
    # time_series speaks receipt time (the canonical validator's own rule:
    # the x axis is receipt_time in seconds, every axis scalar); waveform
    # speaks the explicit time-axis vector alongside its traces.
    receipt_var = {
        "id": "time", "type": "number", "unit": "s",
        "shape": "scalar", "axis_role": "receipt_time",
    }

    # (#556 Track B §4 V2) A computed measurement — the descriptor's own
    # ``derived_variables`` declaration — is an ordinary value variable of
    # EVERY dataset target: the host computes the value into the dataset, so
    # the wire carries it and the derived shape asserting it is honest. The
    # shape follows the dataset's own wire shape: a time_series dataset's
    # value variables are scalars (one sample per receipt time), while a
    # waveform or digital-lanes dataset carries a vector per sample, so the
    # computed variable is a vector there. A scalar row on a waveform dataset
    # would describe a wire shape the dataset does not carry — and the
    # canonical validator refuses a scalar y series on a waveform plot
    # (contracts.py `_plot_findings`: y's shape must match the kind's).
    # The variable rides the numeric series rule where the kind admits it
    # (time_series and waveform y sets; a digital-lanes plot's y channels are
    # the wire's string logic alphabet, so it stays in the dataset alone).
    computed_rows = [
        {
            "id": str(row["id"]),
            "type": "number",
            "unit": str(row["unit"]),
        }
        for row in descriptor.get("derived_variables") or []
        if isinstance(row, dict) and row.get("id")
    ]
    computed_ids = {str(row["id"]) for row in computed_rows}

    def _dataset_base(slot_key: str) -> tuple[list[dict[str, Any]], str]:
        """The wire shape a dataset slot carries WITHOUT the computed rows,
        and its axis variable id."""
        kind = plot_kind_for_slot.get(slot_key, "digital_lanes")
        if kind == "time_series":
            return [receipt_var, *quantity_vars], str(receipt_var["id"])
        if kind == "waveform":
            return [x_var, *trace_vars], str(x_var["id"])
        return [x_var, *lane_vars], str(x_var["id"])

    def _dataset_shape(slot_key: str) -> list[dict[str, Any]]:
        kind = plot_kind_for_slot.get(slot_key, "digital_lanes")
        wire_shape = "scalar" if kind == "time_series" else "vector"
        base, _axis = _dataset_base(slot_key)
        # A computed id equal to ANY variable id the base wire shape carries
        # — the axis, a lane, a quantity or a trace variable — would put two
        # rows with one id into the variable set; the residual channel names
        # that collision (_computed_variable_detail) rather than emitting a
        # document the canonical validator refuses.
        base_ids = {row["id"] for row in base}
        return [
            *base,
            *[
                {**row, "shape": wire_shape}
                for row in computed_rows
                if row["id"] not in base_ids
            ],
        ]

    if capture_key:
        targets.append(
            {
                "id": capture_key,
                "kind": "dataset",
                "action_id": capture_slot["action"],
                "profile_ids": profile_ids,
                "measurement_schema_id": measurement_id,
                "variables": _dataset_shape(capture_key),
            }
        )
        bindings.append(
            {"id": capture_key, "kind": "dataset", "target_id": capture_key}
        )
    capture_binding_id = capture_key or ""
    decode_key = next(
        (key for key in dataset_slots if key != capture_key), None
    )
    decode_slot: dict[str, Any] = dataset_slots.get(decode_key or "", {})
    decode_declared = bool(
        decode_slot and str(decode_slot.get("action")) in actions
    )
    # RC-4's decode_annotated overlay: the annotation form derives the same
    # pinned-decoder lanes (same code surface); its coverage rides them.
    decode_annotated_urn = next(
        (
            urn
            for urn in actions
            if urn.split("/")[0].rsplit(".", 1)[-1] == "decode_annotated"
        ),
        None,
    )
    decoder_lanes: list[dict[str, Any]] = []
    if (
        (decode_declared or decode_annotated_urn)
        and descriptor.get("decoders")
        and descriptor_path is not None
    ):
        for pin in descriptor["decoders"]:
            decoder_path = descriptor_path.parent / str(pin.get("path", ""))
            try:
                doc = json.loads(read_file(decoder_path))
                line_ids = [
                    str(row.get("id"))
                    for row in (doc.get("optional_channels") or doc.get("channels") or [])
                    if isinstance(row, dict) and row.get("id")
                ]
            except (ValueError, OSError, json.JSONDecodeError):
                line_ids = []
            if not line_ids or len(line_ids) > len(lanes):
                continue
            sources = [row["id"] for row in lanes[: len(line_ids)]]
            settings = {
                str(line): source
                for line, source in zip(line_ids, sources, strict=False)
            }
            decoder_lanes.append(
                {
                    "id": f"decode-{pin['id']}",
                    "label": str(doc.get("name", pin["id"])),
                    "decoder": str(pin["id"]),
                    "settings": settings,
                    "source_channel_ids": sources,
                    "binding_id": decode_key,
                }
            )
    if decoder_lanes and decode_key and not decode_declared:
        # Annotation-form lanes with no decode declaration bind the capture
        # dataset binding (no decode target exists to carry them).
        for lane_row in decoder_lanes:
            lane_row["binding_id"] = capture_binding_id
    if decode_key and decode_declared:
        targets.append(
            {
                "id": decode_key,
                "kind": "dataset",
                "action_id": decode_slot["action"],
                "profile_ids": profile_ids,
                "measurement_schema_id": measurement_id,
                "variables": _dataset_shape(decode_key),
            }
        )
        bindings.append({"id": decode_key, "kind": "dataset", "target_id": decode_key})
    # The readings expansion (the L11 rule): a readings page's rendered
    # tiles are OBSERVATION bindings — one per scalar variable of its
    # dataset slot — each naming the descriptor parameter the channel
    # binds to that quantity. The layout's authored reading-tile nodes are
    # consumed by this expansion (see _build_layout): one authored child
    # becomes n_reading_tiles rendered tiles on the page, never an
    # admittance table beside them.
    observation_ids_for_page: dict[str, list[str]] = {}
    observation_value_ids: dict[str, str] = {}
    for page in merged["pages"]:
        if str(page.get("kind", "readings")) != "readings":
            continue
        page_id = str(page["id"])
        for key in page.get("_slot_keys", []):
            if key not in dataset_slots:
                continue
            ids: list[str] = []
            for row in lanes:
                for quantity in row.get("quantities") or []:
                    binding_id = f"{key}-{row['id']}-{quantity}"
                    value_id = f"{row['id']}-{quantity}"
                    parameter = parameter_rows.get(
                        (str(row["id"]), str(quantity))
                    )
                    if parameter is None:
                        raise _refuse(
                            "classref_parameter_map",
                            f"channel {row.get('id')!r} quantity {quantity!r} "
                            "has no named readable parameter to read",
                        )
                    target_id = binding_id
                    targets.append(
                        {
                            "id": target_id,
                            "kind": "observation",
                            "parameter_id": str(parameter.get("name")),
                            # The canonical observation shape (the
                            # scaffold's own): receipt time in seconds plus
                            # the one value variable this tile reads.
                            "variables": [
                                {
                                    "id": "time",
                                    "type": "number",
                                    "unit": "s",
                                    "shape": "scalar",
                                    "axis_role": "receipt_time",
                                },
                                {
                                    "id": value_id,
                                    "type": "number",
                                    "unit": parameter.get("unit"),
                                    "shape": "scalar",
                                    "axis_role": "value",
                                },
                            ],
                        }
                    )
                    bindings.append(
                        {
                            "id": binding_id,
                            "kind": "observation",
                            "target_id": target_id,
                        }
                    )
                    ids.append(binding_id)
                    observation_value_ids[binding_id] = value_id
            observation_ids_for_page.setdefault(page_id, []).extend(ids)
    configuration_slots = {
        key: slot for key, slot in merged["slots"].items()
        if slot.get("kind") == "configuration"
    }
    settings_schema: dict[str, Any] = {"type": "object", "properties": {}}
    preset_scaffolds: dict[str, dict[str, Any]] = {}
    config_binding_ids: list[str] = []
    for config_key, config_slot in configuration_slots.items():
        urn = str(config_slot["action"])
        if urn not in actions:
            continue
        slot_catalogue_row = _catalogue_row(urn, catalog_actions)
        effective = _effective_action_schema(
            urn, slot_catalogue_row, actions[urn].get("input_constraints") or {}
        )
        catalogue_input = (slot_catalogue_row or {}).get("input_schema", {}) or {}
        settings_schema = {
            **effective,
            "$id": catalogue_input.get("$id", f"urn:otdp:action:{urn}:input"),
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
        }
        schema_name = f"settings/{config_key}.schema.json"
        assets.append(
            {
                "id": schema_name,
                "path": schema_name,
                "sha256": hashlib.sha256(
                    (json.dumps(settings_schema, indent=2) + "\n").encode()
                ).hexdigest(),
            }
        )
        preset_scaffolds[config_key] = {
            "contract_version": version,
            "id": f"scaffold-{config_key}",
            "title": f"Scaffold preset for {config_key}",
            "revision": "0",
            "plugin_id": str(descriptor["id"]),
            "profile_ids": profile_ids,
            "supported_firmware": [
                str(row)
                for row in descriptor.get("identity", {}).get("supported_firmware", [])
                or ["0"]
            ],
            "settings_schema": {
                "id": settings_schema["$id"],
                "sha256": hashlib.sha256(
                    (json.dumps(settings_schema, indent=2) + "\n").encode()
                ).hexdigest(),
            },
            "settings": {},
            "provenance": {
                "author": "benchweave-sdk expander (scaffold; commission values via check-preset)",
                "revision": "0",
                "evidence": "synthetic",
            },
        }
        config_binding_ids.append(config_key)
        targets.append(
            {
                "id": config_key,
                "kind": "configuration",
                "action_id": urn,
                "profile_ids": profile_ids,
                "input_schema_id": catalogue_input.get("$id"),
                "schema_asset_id": schema_name,
                "preset_asset_ids": [],
            }
        )
        bindings.append(
            {"id": config_key, "kind": "configuration", "target_id": config_key}
        )
    procedure_slots = {
        key: slot for key, slot in merged["slots"].items()
        if slot.get("kind") == "procedure"
    }
    for proc_key, proc_slot in procedure_slots.items():
        urn = str(proc_slot["action"])
        if urn not in actions:
            continue  # when_declared slot the descriptor does not declare
        targets.append(
            {
                "id": proc_key,
                "kind": "procedure",
                "action_id": urn,
                "profile_ids": profile_ids,
                "input_schema_id": (_catalogue_row(urn, catalog_actions) or {})
                .get("input_schema", {})
                .get("$id"),
            }
        )
        bindings.append({"id": proc_key, "kind": "procedure", "target_id": proc_key})
    claimed = {slot.get("action") for slot in merged["slots"].values() if slot.get("action")}
    # D14 Device features: unclaimed URNs render through the layout block
    # only. The vendored validator admits catalogue targets for profile
    # actions only (an empty or non-profile profile_ids row is a
    # capability_mismatch), so vendor actions carry no manifest target —
    # the coverage arm checks their rendered controls in the DOM.
    vendor_urms = [urn for urn in sorted(actions) if urn not in claimed]
    vendor_binding_ids: list[str] = [
        urn.split("/")[0].rsplit(".", 1)[-1] for urn in vendor_urms
    ]
    resolved = {row["id"] for row in bindings}
    binding_kind = {row["id"]: row["kind"] for row in bindings}
    # The validator's page-kind/binding-kind vocabulary: a dataset page
    # carries dataset bindings only, a configuration page carries
    # configuration and procedure bindings. Procedure bindings stay in the
    # manifest binding list (the layout block references them); the page
    # row lists only the kinds its own kind admits. Decoder lanes name the
    # decode dataset binding on the plot's page (the other-action rule).
    allowed_by_kind = {
        "dataset": {"dataset"},
        "configuration": {"configuration", "procedure"},
        "readings": {"observation"},
    }
    pages_out: list[dict[str, Any]] = []
    for page in merged["pages"]:
        page_id = str(page["id"])
        kind = str(page.get("kind", "readings"))
        allowed = allowed_by_kind.get(kind, {"observation"})
        candidates = list(page.get("bindings", [])) + observation_ids_for_page.get(
            page_id, []
        )
        rows = [
            b
            for b in dict.fromkeys(candidates)
            if b in resolved and binding_kind.get(b, "") in allowed
        ]
        pages_out.append(
            {
                "id": page_id,
                "title": str(page["title"]) if "title" in page else page_id,
                "kind": kind,
                "bindings": rows,
                "required": True,
            }
        )
    if decoder_lanes and decode_key and capture_key:
        for page in pages_out:
            if page["id"] == str(
                next(row["id"] for row in merged["pages"] if row.get("plot"))
            ):
                if decode_key not in page["bindings"]:
                    page["bindings"].append(decode_key)
                break
    plots: list[dict[str, Any]] = []
    # Slots whose plot ``y`` set the kind's schema ceiling forced to drop
    # composed series: slot key -> the ids dropped (#556 B1 fold F2). The
    # residual channel names them; the dataset's variable set still carries
    # them.
    series_overflow: dict[str, tuple[str, ...]] = {}
    for page in pages_out:
        template = next(
            (row for row in merged["pages"] if str(row["id"]) == page["id"]), None
        )
        plot_spec = (template or {}).get("plot")
        if plot_spec is None:
            continue
        over_key = str(plot_spec.get("over_slot", ""))
        if over_key not in merged["slots"] or over_key not in resolved:
            continue
        kind = str(plot_spec.get("kind", "digital_lanes"))
        if kind in ("time_series", "waveform"):
            # The scalar/trace plot (the 0.3.0 widening): no group
            # machinery (the schema bans it exactly as for the other
            # non-lanes kind). A dataset-page plot binds its slot and
            # carries one series per numeric variable (the closed
            # ``series: "numeric_variables"`` rule). A READINGS page admits
            # observation bindings only and one observation target carries
            # one value variable, so its trend binds the page's first
            # observation — the wire's series set is the bound
            # observation's (reported, design §3.1.2 vs the canonical
            # validator's observation cardinality).
            if kind == "time_series" and observation_ids_for_page.get(
                str(page["id"])
            ):
                bound = observation_ids_for_page[str(page["id"])][0]
                y_ids = [observation_value_ids[bound]]
                x_id = "time"
            else:
                shape = _dataset_shape(over_key)
                x_id = "time" if kind == "time_series" else "t"
                y_ids = [row["id"] for row in shape if row["id"] != x_id]
                # (#556 B1 fold F2) The analog kinds cap ``y`` at the
                # manifest schema's ceiling, and B1's road is the COMPOSED
                # series: the overflow drops composed rows and nothing else.
                # A class whose own traces already exceed the ceiling is the
                # pre-existing shape (design record addendum 2026-10-25) and
                # is left untouched — dropping a class-declared trace would
                # be a behaviour change outside this slice.
                base_y = [
                    identifier
                    for identifier in y_ids
                    if identifier not in computed_ids
                ]
                budget = max(0, _PLOT_SERIES_CEILING - len(base_y))
                composed_y = [
                    identifier
                    for identifier in y_ids
                    if identifier in computed_ids
                ]
                if len(composed_y) > budget:
                    overflow = composed_y[budget:]
                    dropped = set(overflow)
                    y_ids = [
                        identifier
                        for identifier in y_ids
                        if identifier not in dropped
                    ]
                    series_overflow[str(over_key)] = tuple(overflow)
                bound = over_key
            plots.append(
                {
                    "kind": kind,
                    "binding_id": bound,
                    "x": x_id,
                    "y": y_ids,
                }
            )
            page["plots"] = [plots[-1]]
            continue
        groups = []
        n = len(lane_vars)
        full = n // _GROUP_SIZE
        remainder = n % _GROUP_SIZE
        # A trailing remainder of exactly 1 forms no group (member_ids
        # minItems 2); 2..7 forms the one partial group.
        total = full + (1 if remainder >= 2 else 0)
        for k in range(total):
            start = k * _GROUP_SIZE
            width = _GROUP_SIZE if k < full else remainder
            members = [row["id"] for row in lane_vars[start : start + width]]
            groups.append(
                {
                    "id": f"lanes-{k + 1}",
                    "label": f"D{start + 1}-D{start + width}",
                    "member_ids": members,
                    "radix": str(plot_spec.get("group_radix", "hex")),
                }
            )
        plots.append(
            {
                "kind": "digital_lanes",
                "binding_id": capture_binding_id,
                "x": "t",
                "y": [row["id"] for row in lane_vars],
                "channel_hints": [
                    {"variable_id": row["id"], "visible": True} for row in lane_vars
                ],
                "lane_groups": groups,
                "decoder_lanes": decoder_lanes,
            }
        )
        page["plots"] = [plots[-1]]
    # R9 (#541 slice 3 fold): a plan row advertises a rendering only when that
    # rendering occurs. The decode-annotated overlay points its row at the
    # decoder annotation lanes; those lanes derive into a digital-lanes
    # plot's ``decoder_lanes`` key alone, so a class whose plot is a waveform
    # or time-series never renders them. Stamping the claim here — after the
    # plots are built — is what keeps the advertisement true: when no plot
    # carries the lanes, the row carries no claim, and the residual-member
    # disclosure (and R10's deferred-decoder row) is what names the gap.
    if any(plot.get("decoder_lanes") for plot in plots):
        for urn, row in plan.items():
            if urn.split("/")[0].rsplit(".", 1)[-1] == "decode_annotated":
                row["rendered_by"] = "decoder annotation lanes"
    layout_block = _build_layout(
        pages_out, plots, merged["layouts"], plan, vendor_binding_ids,
        templates={str(row["id"]): row for row in merged["pages"]},
    )
    manifest = {
        "contract_version": version,
        "plugin_id": str(descriptor["id"]),
        "descriptor_sha256": descriptor_hash,
        "bindings": bindings,
        "pages": pages_out,
        "assets": assets,
        "extensions": {LAYOUT_EXTENSION_KEY: layout_block},
    }
    manifest_raw = (json.dumps(manifest, indent=2) + "\n").encode()
    envelope = {
        "contract_version": version,
        "descriptor_sha256": descriptor_hash,
        "resource_root": "ui",
        "manifest": {
            "path": "manifest.json",
            "sha256": hashlib.sha256(manifest_raw).hexdigest(),
        },
    }
    catalogue = {
        "contract_version": version,
        "descriptor_sha256": descriptor_hash,
        "targets": targets,
    }
    expectation = _build_expectation(
        merged, plan, pages_out,
        plot_group_count=sum(
            len(plot.get("lane_groups", ())) for plot in plots
        ),
        decoder_count=len(decoder_lanes), numeric_fields=_configure_numeric_count(plan),
        run_actions=[
            urn for urn, row in plan.items()
            if row["level"] in ("L1", "L2") and row["page"] == _capture_page_id(pages_out)
        ],
        channel_count=len(lanes),
        variable_count=sum(len(row.get("quantities") or ()) for row in lanes),
    )
    declaration = _build_declaration(
        references, divergences, plan, ignored_pins
    )
    cannot = list(merged["cannot_derive"])
    # The residual inventory (#556 Track B §3 rule 3) needs four facts about
    # THIS run: which channel roles resolved lanes, which dataset targets
    # derived (and the base variable ids their wire shape carries), which
    # composed series the plot ceiling forced off a plot, and which plot
    # kinds derived.
    channels_slot = _channels_slot(merged)
    residual = residual_members(
        descriptor,
        # The rendered set, not the built set (R10's condition): lanes a
        # derived PLOT carries. Building a lane is not rendering it.
        {
            str(lane.get("decoder", ""))
            for plot in plots
            for lane in (plot.get("decoder_lanes") or [])
        },
        # The founding rule resolves ONE channels slot, so at most one role
        # resolves lanes here; a channel of another role reports (#556 B1).
        channel_roles=(
            (str(channels_slot.get("where_role", "")),)
            if channels_slot is not None
            else ()
        ),
        dataset_variables={
            str(target["id"]): frozenset(
                str(row["id"]) for row in _dataset_base(str(target["id"]))[0]
            )
            for target in targets
            if target["kind"] == "dataset"
        },
        series_overflow=series_overflow,
        plot_kinds=[str(plot.get("kind", "")) for plot in plots],
    )
    result = DerivedUI(
        manifest=manifest,
        envelope=envelope,
        catalogue=catalogue,
        settings_schema=settings_schema,
        preset_scaffolds=preset_scaffolds,
        layout_block=layout_block,
        expectation=expectation,
        control_plan=plan,
        reference=references[0],
        cannot_derive=cannot,
        declaration=declaration,
        ignored_pins=ignored_pins,
        unapplied_classes=unapplied_classes,
        empty_action_pins=empty_action_pins,
        residual_members=residual,
        composed_members=composed_members or {},
        unapplied_member_pins=unapplied_member_pins,
    )
    return result

def effective_action_fields(
    descriptor: dict[str, Any], urn: str, descriptor_path: Path | None = None
) -> list[dict[str, Any]]:
    """The effective field rows for one action, resolved from the served
    catalogs and the descriptor's constraints (the host composition's
    admittance source; the same intersection the expander derives). A
    declared action no catalog describes resolves residual (#541): the
    descriptor's own constraints, exactly as the plan row derives them."""
    catalog = _catalog_documents(descriptor)
    actions = dict(catalog.get("actions", {}))
    (
        vendor_actions,
        _composed,
        _ignored,
        _unapplied,
        _empty,
        _member_declarations,
    ) = _vendor_documents(descriptor, descriptor_path, actions)
    actions.update(vendor_actions)
    constraints = (descriptor.get("actions") or {}).get(urn, {}).get(
        "input_constraints"
    ) or {}
    effective = _effective_action_schema(urn, _catalogue_row(urn, actions), constraints)
    return _field_rows(urn, "", effective)


def coverage_plan_without_reference(
    descriptor: dict[str, Any],
    descriptor_path: Path | None = None,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, Any],
    tuple[str, ...],
    tuple[tuple[str, str], ...],
    tuple[str, ...],
]:
    """The D14 coverage plan for a descriptor with NO class reference:
    every declared action through the ladder with no named slots (the
    acquisition-lifecycle names stay host-supplied; actions land on the
    project's first page). D14 binds every plugin — the plan, not a
    reference, is what the always-on arm checks. The trailing elements
    are the pin disclosures, mirroring ``DerivedUI``'s: the ignored-pin
    set (B7: the reference-less gate arm discloses them too, exactly as
    the reference-carrying arm does), the unapplied composed classes and
    the empty-catalog pins (R1/R5, 2026-10-23 fold wave 3 — the same
    disclosures, the same channel)."""
    catalog = _catalog_documents(descriptor)
    actions_map: dict[str, Any] = dict(catalog.get("actions", {}))
    (
        vendor_actions,
        _composed,
        ignored,
        unapplied,
        empty_pins,
        _member_declarations,
    ) = _vendor_documents(descriptor, descriptor_path, actions_map)
    actions_map.update(vendor_actions)
    actions = descriptor.get("actions") or {}
    # #541 layer 3, the same treatment as derive_ui: a catalog-absent
    # declared action is a residual member that derives, resolution
    # "custom" — the reference-less plan cannot disagree with the
    # reference-carrying derivation.
    plan, _divergences = _derive_controls(
        actions, actions_map, {}, {}, {}
    )
    return plan, actions_map, ignored, unapplied, empty_pins


def _capture_page_id(pages: list[dict[str, Any]]) -> str:
    for page in pages:
        if page.get("plots"):
            return str(page["id"])
    return str(pages[0]["id"]) if pages else ""


def _configure_numeric_count(plan: dict[str, dict[str, Any]]) -> int:
    for row in plan.values():
        if row["level"] == "L3":
            return sum(1 for field in row["fields"] if field["mode"] == "numeric")
    return 0


def _numeric_nodes(binding_id: str, fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"binding_id": binding_id, "kind": "numeric", "field": field["field"]}
        for field in fields
        if field["mode"] == "numeric"
    ]


def _staging_nodes(binding_id: str, fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-mode staging nodes (the L5 widening): numeric→numeric, text→text,
    enum/const→select, boolean→boolean. Inexpressible fields emit no node
    (they derived no row)."""
    out: list[dict[str, Any]] = []
    for field in fields:
        kind = _MODE_KIND.get(field["mode"])
        if kind is not None:
            out.append({"binding_id": binding_id, "kind": kind, "field": field["field"]})
    return out


def _build_layout(
    pages: list[dict[str, Any]],
    plots: list[dict[str, Any]],
    authored: list[dict[str, Any]],
    plan: dict[str, dict[str, Any]],
    vendor_binding_ids: list[str],
    *,
    templates: dict[str, dict[str, Any]] | None = None,
    plan_is_placeholder: bool = False,
) -> dict[str, Any]:
    """The namespaced layout block: authored sections where the reference
    carries them, derived sections otherwise — the main derived section,
    plus the expander-minted custom section when residual members render on
    the page (#541). Numeric staging nodes derive from the ladder plan (L2
    actions render their fields)."""
    by_page = {str(row.get("page_id")): row for row in authored}
    block_pages: list[dict[str, Any]] = []
    plot_done = False
    for page in pages:
        page_id = str(page["id"])
        authored_page = by_page.get(page_id)
        if authored_page is not None:
            # The reading-tile expansion consumes authored reading-tile
            # children (they become the page's observation tiles — see
            # _finish); a section left empty by the expansion drops with
            # them. data-table children render as always.
            sections = []
            for section in authored_page.get("sections", []):
                kept = [
                    child
                    for child in section.get("children", [])
                    if child.get("kind") != "reading-tile"
                ]
                if kept:
                    sections.append({**section, "children": kept})
        else:
            children: list[dict[str, Any]] = []
            custom_children: list[dict[str, Any]] = []
            if page.get("plots") and not plot_done and plots:
                children.append({"plot_index": 0})
                plot_done = True
            for row in page.get("bindings", []):
                binding_id = str(row if isinstance(row, str) else row.get("id"))
                urn = _urn_for_binding(plan, binding_id)
                level = plan.get(urn, {}).get("level") if urn else None
                if level == "L2" and urn is not None:
                    children.extend(
                        _staging_nodes(binding_id, plan[urn]["fields"])
                    )
                if level in ("L1", "L2"):
                    children.append({"binding_id": binding_id, "kind": "button"})
                if level == "L3" and urn is not None:
                    # L3 is preset-mediated; the numeric fields still offer
                    # their effective admittance beside the preset surface.
                    for field_row in plan[urn]["fields"]:
                        if field_row["mode"] == "numeric":
                            children.append(
                                {"binding_id": binding_id, "kind": "numeric",
                                 "field": field_row["field"]}
                            )
                    children.append(
                        {"binding_id": binding_id, "kind": "data-table"}
                    )
            # D14: actions whose bindings carry no page (vendor actions)
            # still derive their controls on their plan page. #541: a
            # residual member's controls derive into the page's CUSTOM
            # section instead — the visible label for uncatalogued actions
            # (record §4.2), minted the way the expander mints every other
            # derived id. Catalogued vendor actions keep the main section,
            # so resolution partitions the two, never mixes them.
            bound = {
                str(row if isinstance(row, str) else row.get("id"))
                for row in page.get("bindings", [])
            }
            for urn, plan_row in sorted(plan.items()):
                if str(plan_row["page"]) != str(page["id"]):
                    continue
                slug = urn.split("/")[0].rsplit(".", 1)[-1]
                if slug in bound or plan_row["level"] == "L4":
                    continue
                if plan_row["level"] in ("L1", "L2", "L3"):
                    target = (
                        custom_children
                        if plan_row.get("resolution") == "custom"
                        else children
                    )
                    if plan_row["level"] == "L3":
                        # L3 is preset-mediated; its numeric admittance
                        # renders beside the preset surface and data-table
                        # (the pinned family shape — no per-mode widening
                        # on this arm).
                        target.extend(
                            _numeric_nodes(slug, plan_row["fields"])
                        )
                    else:
                        target.extend(
                            _staging_nodes(slug, plan_row["fields"])
                        )
                    if plan_row["level"] in ("L1", "L2"):
                        target.append({"binding_id": slug, "kind": "button"})
            sections = []
            if children:
                sections.append({
                    "id": f"{page_id}-section",
                    "title": str(page.get("title", page_id)),
                    "surface": "raised",
                    "span": 12,
                    "children": children,
                })
            if custom_children:
                # The custom section exists exactly when residual members
                # rendered on this page. It never appends into an authored
                # page: this whole branch is the no-authored-layout path
                # (record §11 risk 4 — an authored device-features layout
                # stands as authored, and the residual member surfaces
                # through the plan, the declaration and the gate instead).
                sections.append({
                    "id": f"{page_id}-custom",
                    "title": "Custom device actions",
                    "surface": "raised",
                    "span": 12,
                    "children": custom_children,
                })
        _complete_authored_buttons(sections, plan, page_id)
        # #541 W1 fold: completion runs BEFORE the ladder-numeric insert —
        # a button the completion pass appends (a when-declared action on
        # an authored page, a catalogued vendor action on an authored
        # device-features page) must arrive in time for the insert to give
        # it its numeric staging pair, or the action reds
        # classref_gate_uncovered with a button and no staged fields.
        _insert_ladder_numerics(sections, plan)
        if not sections:
            # Every declared page renders as a panel (the expect row's
            # meaning): a page whose surface is fully placed — or whose
            # actions surface as REPORTED rows elsewhere — derives the
            # honest disclosure text, never a page without its panel.
            template = (templates or {}).get(page_id, {})
            sections = [
                {
                    "id": f"{page_id}-section",
                    "title": str(page.get("title", page_id)),
                    "surface": "raised",
                    "span": 12,
                    "children": [
                        {
                            "body": (
                                "No additional device features."
                                if template.get("vendor_features")
                                else "No additional surfaces for this page."
                            )
                        }
                    ],
                }
            ]
        block_pages.append({"page_id": page_id, "sections": sections})
    block = {
        "contract_version": active_version(_FAMILY),
        "pages": block_pages,
    }
    # Internal consistency arm (H2): the expander's own emission satisfies
    # the family schema — a violation is a bug here, refused loudly.
    from jsonschema import Draft202012Validator

    findings = sorted(
        Draft202012Validator(layout_schema()).iter_errors(block),
        key=lambda error: list(error.path),
    )
    if findings:
        raise _refuse(
            "classref_layout_invalid",
            "the expander's derived block violates the family schema: "
            f"{findings[0].message}",
        )
    return block


def _complete_authored_buttons(
    sections: list[dict[str, Any]],
    plan: dict[str, dict[str, Any]],
    page_id: str,
) -> None:
    """A9's F3b arm: the reference's authored sections name only the
    always-present bindings — a when-declared action (trigger) that
    derives onto this page owes its button node too, or the census and
    the coverage arm both miss it.

    #541 W1 fold, two scoping rules: a residual member never welds into
    the reference's authored sections (an authored page stands as
    authored — record §11 risk 4; the member surfaces through the plan,
    the declaration and the gate), and the append targets the page's
    MAIN derived section when one exists — after slice 1 the last section
    may be the custom one, and a catalogued action's button must never
    land there."""
    if not sections:
        return
    present: set[str] = set()
    for section in sections:
        for node in section.get("children", []):
            if node.get("kind") == "button":
                present.add(str(node.get("binding_id", "")))
    target = next(
        (
            section
            for section in sections
            if section.get("id") == f"{page_id}-section"
        ),
        sections[-1],
    )
    for urn, row in sorted(plan.items()):
        if str(row.get("page", "")) != page_id:
            continue
        if row.get("level") not in ("L1", "L2"):
            continue
        if row.get("resolution") == "custom":
            continue
        slug = urn.split("/")[0].rsplit(".", 1)[-1]
        if slug in present:
            continue
        target.setdefault("children", []).append(
            {"binding_id": slug, "kind": "button"}
        )


def _urn_for_binding(plan: dict[str, dict[str, Any]], binding_id: str) -> str | None:
    for urn in plan:
        if urn.split("/")[0].rsplit(".", 1)[-1] == binding_id:
            return urn
    return None


def _insert_ladder_numerics(
    sections: list[dict[str, Any]], plan: dict[str, dict[str, Any]]
) -> None:
    """Authored button nodes for an L2 action gain the action's numeric
    field nodes immediately before the button (the staging pair order).

    #541 W8 fold: a numeric node the section already carries — a derived
    page's staging emission, or a layout that authored its own numerics —
    is not re-emitted: one field, one control (the pair used to render
    twice on every derived page, catalogued pairs included)."""
    for section in sections:
        children = section.get("children", [])
        present = {
            (str(node.get("binding_id")), node.get("field"))
            for node in children
            if node.get("kind") == "numeric"
        }
        out: list[dict[str, Any]] = []
        for node in children:
            if (
                node.get("kind") == "button"
                and isinstance(node.get("binding_id"), str)
            ):
                urn = _urn_for_binding(plan, str(node["binding_id"]))
                row = plan.get(urn or "", {}) if urn else {}
                for field_row in row.get("fields", []):
                    if field_row["mode"] != "numeric":
                        continue
                    key = (str(node["binding_id"]), field_row["field"])
                    if key in present:
                        continue
                    present.add(key)
                    out.append(
                        {"binding_id": node["binding_id"], "kind": "numeric",
                         "field": field_row["field"]}
                    )
            out.append(node)
        section["children"] = out


def _resolve_parameters(
    descriptor: dict[str, Any], lanes: list[dict[str, Any]]
) -> dict[tuple[str, str], dict[str, Any]]:
    """The descriptor parameters the channels bind to their declared
    quantities: ``parameter_names`` positionally over ``quantities`` (the
    descriptor's own channel-level mapping). The descriptor owns every
    data path, so a readings page that owes a tile per scalar variable and
    meets a quantity with no named readable parameter refuses typed — the
    tile's data path is structure the expander cannot invent."""
    parameters = {
        str(row.get("name")): row
        for row in descriptor.get("parameters", [])
        if row.get("access") in ("ro", "rw")
    }
    mapping: dict[tuple[str, str], dict[str, Any]] = {}
    for channel in lanes:
        names = [str(name) for name in channel.get("parameter_names") or []]
        for index, quantity in enumerate(channel.get("quantities") or []):
            if index >= len(names):
                raise _refuse(
                    "classref_parameter_map",
                    f"channel {channel.get('id')!r} declares quantity "
                    f"{quantity!r} with no named parameter (parameter_names "
                    "covers quantities positionally)",
                )
            row = parameters.get(names[index])
            if row is None:
                raise _refuse(
                    "classref_parameter_map",
                    f"channel {channel.get('id')!r} quantity {quantity!r} "
                    f"names {names[index]!r}, which is no declared readable "
                    "parameter",
                )
            mapping[(str(channel.get("id")), str(quantity))] = row
    return mapping


def _build_expectation(
    merged: dict[str, Any],
    plan: dict[str, dict[str, Any]],
    pages: list[dict[str, Any]],
    *,
    plot_group_count: int,
    decoder_count: int,
    numeric_fields: int,
    run_actions: list[str],
    channel_count: int,
    variable_count: int,
) -> dict[str, Any]:
    """Resolve the reference's expect expressions into the gate's numeric
    assertion document (record §3.4; closed vocabulary)."""
    inventory = {
        "n_lanes": sum(
            len(row.get("y", []))
            for page in pages
            for row in page.get("plots", [])
            if row.get("kind", "digital_lanes") == "digital_lanes"
        ),
        "n_groups": plot_group_count,
        "n_decoders": decoder_count,
        "n_run_actions": len(run_actions),
        "n_configure_fields": numeric_fields,
        "n_pages": len(pages),
        # The 0.3.0 widening's counters (L11/L13): the channels slot's
        # role-resolved channel count and one variable per channel and
        # declared quantity — the readings tiles (one per scalar variable)
        # and the waveform traces (array-valued, one per pair) derive from
        # the same resolved inventory.
        "n_source_channels": channel_count,
        "n_scalar_variables": variable_count,
        "n_reading_tiles": variable_count,
        "n_analogue_channels": channel_count,
        "n_trace_variables": variable_count,
    }
    components: dict[str, Any] = {}
    for name, row in merged["expect"]["components"].items():
        count = row.get("count")
        if isinstance(count, str):
            if count.isdigit():
                resolved = int(count)
            else:
                match = re.fullmatch(r"\{([a-z_]+)\}", count)
                if match is None or match.group(1) not in _EXPECT_NAMES:
                    raise _refuse(
                        "classref_expect_expression", f"count {count!r} unresolved"
                    )
                resolved = inventory[match.group(1)]
        else:
            resolved = count
        resolved_row: dict[str, Any] = {"count": resolved}
        if row.get("per_page") is not None:
            resolved_row["per_page"] = str(row["per_page"])
        attribute = {}
        for key, expr in (row.get("attribute") or {}).items():
            match = re.fullmatch(r"\{([a-z_]+)\}", str(expr))
            if match is None or match.group(1) not in _EXPECT_NAMES:
                raise _refuse(
                    "classref_expect_expression", f"attribute {expr!r} unresolved"
                )
            attribute[key] = inventory[match.group(1)]
        if attribute:
            resolved_row["attribute"] = attribute
        components[name] = resolved_row
    return {
        "inventory": inventory,
        "components": components,
        "controls": dict(merged["expect"]["controls"]),
        "forbid": list(merged["expect"]["forbid"]),
    }


def _build_declaration(
    references: list[dict[str, Any]],
    divergences: list[dict[str, str]],
    plan: dict[str, dict[str, Any]],
    ignored_pins: tuple[str, ...] = (),
) -> dict[str, Any]:
    """The birth conformance declaration (D12c): the reference the project
    follows plus the deviation ledger. Presets are commissioned evidence, so
    every configuration action's preset surface carries the birth deviation
    (A02 unamended); intended-vs-derived divergences ride alongside. An L0
    row (no staged control derives) REPORTS at birth — the corpus's own
    "REPORTED, never silent" rule — and the D7 carve-out is structural: the
    abort class never appears on any ledger, birth included."""
    deviation_rows = [
        {"expectation_id": row["expectation_id"], "reason": row["reason"]}
        for row in divergences
    ]
    preset_deviations = []
    for item in references:
        for _key, slot in item.get("slots", {}).items():
            if slot.get("kind") == "configuration":
                preset_deviations.append(
                    {
                        "expectation_id": str(slot["action"]),
                        "reason": (
                            "preset surface derived with no commissioned "
                            "presets at birth; author ui/presets/ and validate "
                            "via check-preset"
                        ),
                    }
                )
    ladder_deviations = [
        {
            "expectation_id": urn,
            "reason": (
                "L0 at birth: no staged control derives; the deviation is "
                "REPORTED, never silent"
            ),
        }
        for urn, row in sorted(plan.items())
        if row.get("level") == "L0"
        and row.get("divergence") is None
        # #541 (W6 fold): a residual member is not a divergence from the
        # reference — the reference never claimed it. Its disclosure
        # channel is the custom inventory below, level-aware; keeping it
        # out of the deviation ledger stops the same member reporting
        # through two channels with two different stories.
        and row.get("resolution") != "custom"
        and urn.split("/")[0].rsplit(".", 1)[-1] != "abort"
    ]
    seen = {row["expectation_id"] for row in deviation_rows}
    for row in preset_deviations + ladder_deviations:
        if row["expectation_id"] not in seen:
            deviation_rows.append(row)
            seen.add(row["expectation_id"])
    # #541 record §4.4: the custom inventory. Not deviations — a residual
    # member is not a divergence from the reference; it is an action the
    # reference never claimed. The declaration states what is uncatalogued
    # from birth so the project's own conformance record (the file
    # upgrade and migrate-ui watch) can never lose it. No schema governs
    # this document's key set (only the deviation vocabulary is validated),
    # so the inventory lands without a standards motion. The reason is
    # LEVEL-AWARE (W6 fold): it names what actually derives — controls, or
    # nothing — and for the W7 shape it names the absence itself (the
    # descriptor declared no input schema), never a derivation that does
    # not happen.
    custom_rows: list[dict[str, Any]] = []
    for urn, row in sorted(plan.items()):
        if row.get("resolution") != "custom":
            continue
        # B7 (2026-10-23 fold): when a pinned, digest-verified document
        # was presented and contributed nothing, the reason says so —
        # presenting the descriptor's emptiness as the whole cause
        # misstates what happened (the vendor's pin may declare exactly
        # the schema; the SDK dropped it for its shape, and discloses
        # that drop on every surface).
        ignored_clause = (
            "; pinned document "
            + ", ".join(ignored_pins)
            + " contributed nothing (shape matched neither a vendor "
            "catalog nor a composed class)"
            if ignored_pins
            else ""
        )
        if row.get("level") == "L0":
            reason = (
                "no served catalog describes this action and the descriptor "
                "declares no input schema"
                + ignored_clause
                + "; nothing derives (L0)"
                if row.get("input_undeclared")
                else "no served catalog describes this action"
                + ignored_clause
                + "; no staged control derives from the declared "
                "input_constraints (L0)"
            )
        else:
            reason = (
                "no served catalog describes this action"
                + ignored_clause
                + "; controls derive from the descriptor's own "
                "input_constraints"
            )
        custom_rows.append(
            {"action": urn, "resolution": "custom", "reason": reason}
        )
    # #541 slice 2 (standards record §8.2): the composed inventory, beside
    # slice 1's custom rows. composed_actions names every member a class
    # claimed and the descriptor declared (the migrate-ui drift arithmetic
    # reads this set); composed_classes names each consumed class urn and
    # the family version it was validated against — the stamp migrate-ui
    # re-resolves and re-stamps across a family bump. A class urn's own
    # version is content and is never re-stamped by anything.
    composed_rows: list[dict[str, Any]] = [
        {"action": urn, "resolution": "composed", "class": row["class"]}
        for urn, row in sorted(plan.items())
        if row.get("resolution") == "composed"
    ]
    composed_classes: list[dict[str, Any]] = [
        {"class": class_urn, "validated_against": active_version(_FAMILY)}
        for class_urn in sorted(
            {
                row["class"]
                for row in plan.values()
                if row.get("resolution") == "composed"
            }
        )
    ]
    return {
        "contract_version": active_version(_FAMILY),
        "profile_ids": sorted({str(item["profile_id"]) for item in references}),
        "reference_version": active_version(_FAMILY),
        "deviations": deviation_rows,
        "custom_actions": custom_rows,
        "composed_actions": composed_rows,
        "composed_classes": composed_classes,
    }


def declaration_scaffold(derived: DerivedUI) -> dict[str, Any]:
    """The emitted ui/class-reference.json document."""
    return dict(derived.declaration)


#: The expectation ids a declaration may name: the reference's component
#: rows plus the resolved control-plan rows (action URNs). An unknown id
#: cannot launder a divergence (record §4).
def validate_declaration_vocabulary(
    vocabulary: set[str],
    document: dict[str, Any],
    *,
    energy_removing: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Validate one ledger (authored or birth) against an id vocabulary.

    H3: the D7 guard matches the URN's action slug — the abort class per
    the record §4 — so a versioned URN is what it sees, and it runs on
    EVERY ledger the gate consumes, authored or derived, in both gate
    arms. #541 slice 2: the D7 set widens by declaration — a class
    declaring ``energy_removing`` puts its actions beside the abort class
    (never downgraded), with no refusal-code change (record §6)."""
    for row in document.get("deviations", []):
        expectation_id = str(row.get("expectation_id", ""))
        if expectation_id not in vocabulary:
            raise _refuse(
                "classref_unknown_expectation",
                f"{expectation_id} is outside the reference's expect vocabulary",
            )
        slug = expectation_id.split("/")[0].rsplit(".", 1)[-1]
        if slug == "abort" or expectation_id in energy_removing:
            raise _refuse(
                "classref_deviation_forbidden",
                f"{expectation_id} names an energy-removing action's reachability; "
                "nothing may stand between the operator and abort",
            )
    return document


def _declared_energy_removing(
    plan: dict[str, dict[str, Any]],
) -> frozenset[str]:
    """The URNs whose composed class declares ``energy_removing`` — the
    declared half of the widened D7 set (the abort-slug half stays
    structural)."""
    return frozenset(
        urn
        for urn, row in plan.items()
        if str(row.get("side_effect", "")) == "energy_removing"
    )


def declared_energy_removing(
    plan: dict[str, dict[str, Any]],
) -> frozenset[str]:
    """The public name for ``_declared_energy_removing`` — the gate
    consumes the declared D7 half through the same vendored derivation
    (the ``validate_composed_class`` precedent, #541 slice 2): a
    cross-module private import is not an importable face."""
    return _declared_energy_removing(plan)


def validate_declaration(
    derived: DerivedUI, document: dict[str, Any]
) -> dict[str, Any]:
    vocabulary = set(derived.expectation.get("components", {}))
    vocabulary.update(derived.control_plan)
    return validate_declaration_vocabulary(
        vocabulary, document,
        energy_removing=_declared_energy_removing(derived.control_plan),
    )


def compose_manifest(
    derived_manifest: dict[str, Any], overrides: dict[str, Any]
) -> dict[str, Any]:
    """Derived core AND author overlay, composed by id (record §4). The
    overlay cannot delete derived rows and cannot touch identity fields;
    the composed result still owes the canonical validator a clean pass."""
    composed = json.loads(json.dumps(derived_manifest))
    protected = ("contract_version", "plugin_id", "descriptor_sha256")
    for key in overrides:
        if key in protected:
            raise _refuse(
                "overlay_immutable_field", f"{key} is expander-owned"
            )
    if "pages" in overrides and not overrides["pages"]:
        raise _refuse(
            "overlay_delete_refused",
            "an empty pages overlay would delete every derived page",
        )
    for row in overrides.get("pages", []):
        existing = next(
            (page for page in composed["pages"] if page["id"] == row.get("id")),
            None,
        )
        if existing is None:
            composed["pages"].append(json.loads(json.dumps(row)))
            continue
        for key, value in row.items():
            if key == "id":
                continue
            existing[key] = json.loads(json.dumps(value))
    derived_bindings = {row["id"]: row for row in composed["bindings"]}
    for row in overrides.get("bindings", []):
        binding_id = str(row.get("id"))
        if binding_id not in derived_bindings:
            # M9: a NEW binding id is not an overlay edit — the overlay
            # vocabulary cannot introduce bindings, distinct from deletion.
            raise _refuse(
                "classref_binding_unknown",
                f"binding {binding_id!r} is not a derived row; the overlay "
                "composes derived bindings, it does not append them",
            )
        derived_bindings[binding_id].update(
            json.loads(json.dumps(row))
        )
    if "extensions" in overrides:
        composed["extensions"] = {**composed.get("extensions", {}), **overrides["extensions"]}
    result: dict[str, Any] = composed
    return result
