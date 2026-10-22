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
from dataclasses import dataclass
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
_CONSTRAINT_CONTROL_KEYWORDS = frozenset(
    {"type", "enum", "const", "minimum", "maximum",
     "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "pattern"}
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


@cache
def _family_schemas() -> dict[str, Any]:
    """The family's own machine schemas, from the vendored, lock-verified tree."""
    from .validation import contract_documents

    prefix = f"{_FAMILY}/{active_version(_FAMILY)}/"
    documents = contract_documents()
    reference = documents.get(f"{prefix}class-reference.schema.json")
    layout = documents.get(f"{prefix}layout.schema.json")
    if reference is None or layout is None:
        raise RuntimeError(
            "plugin-ui-class-reference schemas missing from the vendored tree; "
            "run sync-standards or reinstall the SDK"
        )
    return {"reference": reference, "layout": layout}


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


def _vendor_catalogs(
    descriptor: dict[str, Any], descriptor_path: Path | None
) -> dict[str, Any]:
    """Action schemas from the descriptor's pinned vendor catalogs."""
    import hashlib

    actions: dict[str, Any] = {}
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
        actions.update(document.get("actions", {}))
    return actions


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
    if low_catalogue is None or low_constraint is None:
        low = low_catalogue if low_constraint is None else low_constraint
    else:
        low = max(low_catalogue, low_constraint)
    high: tuple[Any, bool] | None
    if high_catalogue is None or high_constraint is None:
        high = high_catalogue if high_constraint is None else high_constraint
    else:
        high = min(high_catalogue, high_constraint)
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
    """A required field narrowed to an empty admittance set refuses (D13).

    M6: exclusivity is part of emptiness — a closed bound meeting an open
    bound at the same value admits nothing, in both crossing directions."""
    if effective.get("const") is not None:
        return
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
            # the same closed-vocabulary and admittance gates.
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
            effective_fragment = json.loads(json.dumps(fragment))
            _check_admittance(action_urn, name, effective_fragment)
            properties[name] = effective_fragment
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
        constraints = actions[urn].get("input_constraints") or {}
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
        # composed layer between them; the value names the layer that
        # produced the row (record §4.1 — provenance is data, not a log).
        catalogue_row = catalog_actions.get(urn)
        resolution = "catalog" if catalogue_row is not None else "custom"
        effective = _effective_action_schema(urn, catalogue_row, constraints)
        level = _ladder_level(effective, host_supplied, slot_kind)
        fields = _field_rows(urn, "", effective)
        slot_key = _slot_name if slot else ""
        page = page_for_slot.get(slot_key, "device-features")
        row: dict[str, Any] = {
            "level": level,
            "page": page,
            "fields": fields,
            "resolution": resolution,
        }
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
    catalog_actions.update(_vendor_catalogs(descriptor, descriptor_path))
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


def _resolve_channels(descriptor: dict[str, Any], merged: dict[str, Any]) -> list[dict[str, Any]]:
    """The class-role lanes, in declaration order; fail-closed count
    refusals (record §3.3)."""
    slot = next(
        (slot for slot in merged["slots"].values() if slot.get("kind") == "channels"),
        None,
    )
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
) -> DerivedUI:
    version = active_version("plugin-ui")
    merged = _merge_references(references)
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
                "rendered_by": "decoder annotation lanes",
            }
    return _finish(
        descriptor, references, merged, lanes, actions, catalog_actions,
        plan, divergences, version, descriptor_path=descriptor_path,
        descriptor_file_raw=descriptor_raw,
    )


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

    def _dataset_shape(slot_key: str) -> list[dict[str, Any]]:
        kind = plot_kind_for_slot.get(slot_key, "digital_lanes")
        if kind == "time_series":
            return [receipt_var, *quantity_vars]
        if kind == "waveform":
            return [x_var, *trace_vars]
        return [x_var, *lane_vars]

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
        effective = _effective_action_schema(
            urn, catalog_actions[urn], actions[urn].get("input_constraints") or {}
        )
        catalogue_input = catalog_actions[urn].get("input_schema", {}) or {}
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
                "input_schema_id": catalog_actions[urn].get("input_schema", {}).get("$id"),
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
    declaration = _build_declaration(references, divergences, plan)
    cannot = list(merged["cannot_derive"])
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
    actions.update(_vendor_catalogs(descriptor, descriptor_path))
    constraints = (descriptor.get("actions") or {}).get(urn, {}).get(
        "input_constraints"
    ) or {}
    effective = _effective_action_schema(urn, actions.get(urn), constraints)
    return _field_rows(urn, "", effective)


def coverage_plan_without_reference(
    descriptor: dict[str, Any],
    descriptor_path: Path | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """The D14 coverage plan for a descriptor with NO class reference:
    every declared action through the ladder with no named slots (the
    acquisition-lifecycle names stay host-supplied; actions land on the
    project's first page). D14 binds every plugin — the plan, not a
    reference, is what the always-on arm checks."""
    catalog = _catalog_documents(descriptor)
    actions_map: dict[str, Any] = dict(catalog.get("actions", {}))
    actions_map.update(_vendor_catalogs(descriptor, descriptor_path))
    actions = descriptor.get("actions") or {}
    # #541 layer 3, the same treatment as derive_ui: a catalog-absent
    # declared action is a residual member that derives, resolution
    # "custom" — the reference-less plan cannot disagree with the
    # reference-carrying derivation.
    plan, _divergences = _derive_controls(
        actions, actions_map, {}, {}, {}
    )
    return plan, actions_map


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
    carries them, derived single-section pages otherwise. Numeric staging
    nodes derive from the ladder plan (L2 actions render their fields)."""
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
            # still derive their controls on their plan page.
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
                    if plan_row["level"] == "L3":
                        # L3 is preset-mediated; its numeric admittance
                        # renders beside the preset surface and data-table
                        # (the pinned family shape — no per-mode widening
                        # on this arm).
                        children.extend(
                            _numeric_nodes(slug, plan_row["fields"])
                        )
                    else:
                        children.extend(
                            _staging_nodes(slug, plan_row["fields"])
                        )
                    if plan_row["level"] in ("L1", "L2"):
                        children.append({"binding_id": slug, "kind": "button"})
            sections = [{
                "id": f"{page_id}-section",
                "title": str(page.get("title", page_id)),
                "surface": "raised",
                "span": 12,
                "children": children,
            }] if children else []
        _insert_ladder_numerics(sections, plan)
        _complete_authored_buttons(sections, plan, page_id)
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
    the coverage arm both miss it."""
    present: set[str] = set()
    for section in sections:
        for node in section.get("children", []):
            if node.get("kind") == "button":
                present.add(str(node.get("binding_id", "")))
    if not sections:
        return
    for urn, row in sorted(plan.items()):
        if str(row.get("page", "")) != page_id:
            continue
        if row.get("level") not in ("L1", "L2"):
            continue
        slug = urn.split("/")[0].rsplit(".", 1)[-1]
        if slug in present:
            continue
        sections[-1].setdefault("children", []).append(
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
    field nodes immediately before the button (the staging pair order)."""
    for section in sections:
        children = section.get("children", [])
        out: list[dict[str, Any]] = []
        for node in children:
            if (
                node.get("kind") == "button"
                and isinstance(node.get("binding_id"), str)
            ):
                urn = _urn_for_binding(plan, str(node["binding_id"]))
                row = plan.get(urn or "", {}) if urn else {}
                for field_row in row.get("fields", []):
                    if field_row["mode"] == "numeric":
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
        and urn.split("/")[0].rsplit(".", 1)[-1] != "abort"
    ]
    seen = {row["expectation_id"] for row in deviation_rows}
    for row in preset_deviations + ladder_deviations:
        if row["expectation_id"] not in seen:
            deviation_rows.append(row)
            seen.add(row["expectation_id"])
    return {
        "contract_version": active_version(_FAMILY),
        "profile_ids": sorted({str(item["profile_id"]) for item in references}),
        "reference_version": active_version(_FAMILY),
        "deviations": deviation_rows,
    }


def declaration_scaffold(derived: DerivedUI) -> dict[str, Any]:
    """The emitted ui/class-reference.json document."""
    return dict(derived.declaration)


#: The expectation ids a declaration may name: the reference's component
#: rows plus the resolved control-plan rows (action URNs). An unknown id
#: cannot launder a divergence (record §4).
def validate_declaration_vocabulary(
    vocabulary: set[str], document: dict[str, Any]
) -> dict[str, Any]:
    """Validate one ledger (authored or birth) against an id vocabulary.

    H3: the D7 guard matches the URN's action slug — the abort class per
    the record §4 — so a versioned URN is what it sees, and it runs on
    EVERY ledger the gate consumes, authored or derived, in both gate
    arms."""
    for row in document.get("deviations", []):
        expectation_id = str(row.get("expectation_id", ""))
        if expectation_id not in vocabulary:
            raise _refuse(
                "classref_unknown_expectation",
                f"{expectation_id} is outside the reference's expect vocabulary",
            )
        slug = expectation_id.split("/")[0].rsplit(".", 1)[-1]
        if slug == "abort":
            raise _refuse(
                "classref_deviation_forbidden",
                f"{expectation_id} names an energy-removing action's reachability; "
                "nothing may stand between the operator and abort",
            )
    return document


def validate_declaration(
    derived: DerivedUI, document: dict[str, Any]
) -> dict[str, Any]:
    vocabulary = set(derived.expectation.get("components", {}))
    vocabulary.update(derived.control_plan)
    return validate_declaration_vocabulary(vocabulary, document)


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
