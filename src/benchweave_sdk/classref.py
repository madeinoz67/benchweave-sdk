"""Class-reference expander (gateway #463 Landing 2).

Turns a class-conformant descriptor plus a ``plugin-ui-class-reference``
reference document into a normal plugin-ui 0.3.1 manifest set, the numeric
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
_EXPECT_NAMES = frozenset(
    {"n_lanes", "n_groups", "n_decoders", "n_run_actions", "n_configure_fields",
     "n_pages"}
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
        raise _refuse(
            "classref_unknown_action",
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
            raise _refuse(
                "classref_unknown_action",
                f"pinned vendor catalog {row.get('path')} unreadable ({exc})",
            ) from exc
        if hashlib.sha256(raw).hexdigest() != row.get("sha256"):
            raise _refuse(
                "classref_unknown_action",
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
    for keyword in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        if keyword in constraint:
            declared_type = (
                catalogue_schema.get("type") if isinstance(catalogue_schema, dict) else None
            )
            if declared_type not in _NUMERIC_TYPES:
                raise _refuse(
                    "classref_effective_schema_conflict",
                    f"action {action_urn} field {property_name}: numeric bound "
                    f"applied to catalogue type {declared_type!r}",
                )
            effective[keyword] = constraint[keyword]
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
        effective = {**effective, "const": constraint["const"]}
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
    """A required field narrowed to an empty admittance set refuses (D13)."""
    if effective.get("const") is not None:
        return
    low = effective.get("minimum", effective.get("exclusiveMinimum"))
    high = effective.get("maximum", effective.get("exclusiveMaximum"))
    if low is None or high is None:
        return
    span = (float(high) - float(low)) if effective.get("type") in _NUMERIC_TYPES else None
    if span is not None and span < 0:
        raise _refuse(
            "classref_effective_schema_empty",
            f"action {action_urn} field {property_name}: bounds admit no value",
        )


def _effective_action_schema(
    action_urn: str, catalogue_action: dict[str, Any], constraints: dict[str, Any]
) -> dict[str, Any]:
    """The action's effective input schema: catalogue AND descriptor
    constraints, per property (D13). Validation lanes stay conjunctive and
    untouched; this derives per-field admittance for control rendering."""
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


def _field_rows(
    action_urn: str, prefix: str, schema: dict[str, Any]
) -> list[dict[str, Any]]:
    """The renderable field rows (numeric bounds / const / enum) of one
    effective schema, descending array items and object properties."""
    rows: list[dict[str, Any]] = []
    for name, sub in (schema.get("properties") or {}).items():
        full = f"{prefix}{name}"
        if sub.get("const") is not None:
            rows.append({"field": full, "mode": "const", "const": sub["const"]})
        elif sub.get("enum") is not None:
            rows.append({"field": full, "mode": "enum", "enum": sub["enum"]})
        elif sub.get("type") in _NUMERIC_TYPES:
            row = {"field": full, "mode": "numeric"}
            for keyword in ("minimum", "maximum", "multipleOf"):
                if keyword in sub:
                    row[keyword] = sub[keyword]
            rows.append(row)
        if isinstance(sub.get("properties"), dict):
            rows.extend(
                _field_rows(action_urn, f"{full}.", sub)
            )
        if isinstance(sub.get("items"), dict) and isinstance(
            sub["items"].get("properties"), dict
        ):
            rows.extend(
                _field_rows(action_urn, f"{full}[].", sub["items"])
            )
    return rows


def _ladder_level(
    effective: dict[str, Any], host_supplied: frozenset[str], slot_kind: str | None
) -> str:
    """The reachability ladder (record §2.5), evaluated first-match.

    A configuration slot's action is L3 (preset-mediated); a dataset slot's
    action is L4 (dataset binding + plot/table). Otherwise the effective
    required set (minus the acquisition-lifecycle names the host supplies)
    decides: empty L1 (bare button), all numeric L2 (staging), and anything
    else L0 (declared deviation required)."""
    if slot_kind == "configuration":
        return "L3"
    if slot_kind == "dataset":
        return "L4"
    required = [name for name in effective["required"] if name not in host_supplied]
    if not required:
        return "L1"
    schemas = effective["properties"]
    if all(
        schemas.get(name, {}).get("type") in _NUMERIC_TYPES for name in required
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
        effective = _effective_action_schema(urn, catalog_actions[urn], constraints)
        level = _ladder_level(effective, host_supplied, slot_kind)
        fields = _field_rows(urn, "", effective)
        slot_key = _slot_name if slot else ""
        page = page_for_slot.get(slot_key, "device-features")
        row: dict[str, Any] = {"level": level, "page": page, "fields": fields}
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
    row = _profile_row(catalog, references)
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
        descriptor_path=descriptor_path,
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
            raise _refuse(
                "classref_unknown_action",
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
                "level": "L4",
                "page": plot_page,
                "fields": [],
                "declared_deviation": False,
                "rendered_by": "decoder annotation lanes",
            }
    return _finish(
        descriptor, references, merged, lanes, actions, catalog_actions,
        plan, divergences, version, descriptor_path=descriptor_path,
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
) -> DerivedUI:
    """Assemble every emitted document from the resolved inventory."""
    import hashlib

    descriptor_raw = (json.dumps(descriptor, indent=2) + "\n").encode()
    descriptor_hash = hashlib.sha256(descriptor_raw).hexdigest()
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
    if capture_key:
        targets.append(
            {
                "id": capture_key,
                "kind": "dataset",
                "action_id": capture_slot["action"],
                "profile_ids": profile_ids,
                "measurement_schema_id": measurement_id,
                "variables": [x_var, *lane_vars],
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
                "variables": [x_var, *lane_vars],
            }
        )
        bindings.append({"id": decode_key, "kind": "dataset", "target_id": decode_key})
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
        rows = [
            b
            for b in page.get("bindings", [])
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
        pages_out, plots, merged["layouts"], plan, vendor_binding_ids
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
        merged, plan, pages_out, plot_group_count=len(plots[0]["lane_groups"]) if plots else 0,
        decoder_count=len(decoder_lanes), numeric_fields=_configure_numeric_count(plan),
        run_actions=[
            urn for urn, row in plan.items()
            if row["level"] in ("L1", "L2") and row["page"] == _capture_page_id(pages_out)
        ],
    )
    declaration = _build_declaration(references, divergences)
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
    admittance source; the same intersection the expander derives)."""
    catalog = _catalog_documents(descriptor)
    actions = dict(catalog.get("actions", {}))
    actions.update(_vendor_catalogs(descriptor, descriptor_path))
    if urn not in actions:
        return []
    constraints = (descriptor.get("actions") or {}).get(urn, {}).get(
        "input_constraints"
    ) or {}
    effective = _effective_action_schema(urn, actions[urn], constraints)
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


def _build_layout(
    pages: list[dict[str, Any]],
    plots: list[dict[str, Any]],
    authored: list[dict[str, Any]],
    plan: dict[str, dict[str, Any]],
    vendor_binding_ids: list[str],
    *,
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
            sections = [
                {**section, "children": list(section.get("children", []))}
                for section in authored_page.get("sections", [])
            ]
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
                    for field_row in plan[urn]["fields"]:
                        if field_row["mode"] == "numeric":
                            children.append(
                                {"binding_id": binding_id, "kind": "numeric",
                                 "field": field_row["field"]}
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
                        {"binding_id": binding_id, "kind": "reading",
                         "reading_kind": "data-table"}
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
                    for field_row in plan_row["fields"]:
                        if field_row["mode"] == "numeric":
                            children.append(
                                {"binding_id": slug, "kind": "numeric",
                                 "field": field_row["field"]}
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
        if sections:
            block_pages.append({"page_id": page_id, "sections": sections})
    # The layout block's contract_version is the FAMILY's active version,
    # derived from the lock like every other stamp (derived, never stated).
    return {
        "contract_version": active_version(_FAMILY),
        "pages": block_pages,
    }


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


def _build_expectation(
    merged: dict[str, Any],
    plan: dict[str, dict[str, Any]],
    pages: list[dict[str, Any]],
    *,
    plot_group_count: int,
    decoder_count: int,
    numeric_fields: int,
    run_actions: list[str],
) -> dict[str, Any]:
    """Resolve the reference's expect expressions into the gate's numeric
    assertion document (record §3.4; closed vocabulary)."""
    inventory = {
        "n_lanes": sum(
            len(row.get("y", [])) for page in pages for row in page.get("plots", [])
        ),
        "n_groups": plot_group_count,
        "n_decoders": decoder_count,
        "n_run_actions": len(run_actions),
        "n_configure_fields": numeric_fields,
        "n_pages": len(pages),
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
    references: list[dict[str, Any]], divergences: list[dict[str, str]]
) -> dict[str, Any]:
    """The birth conformance declaration (D12c): the reference the project
    follows plus the deviation ledger. Presets are commissioned evidence, so
    every configuration action's preset surface carries the birth deviation
    (A02 unamended); intended-vs-derived divergences ride alongside."""
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
    seen = {row["expectation_id"] for row in deviation_rows}
    for row in preset_deviations:
        if row["expectation_id"] not in seen:
            deviation_rows.append(row)
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
def validate_declaration(
    derived: DerivedUI, document: dict[str, Any]
) -> dict[str, Any]:
    vocabulary = set(derived.expectation.get("components", {}))
    vocabulary.update(derived.control_plan)
    for row in document.get("deviations", []):
        expectation_id = str(row.get("expectation_id", ""))
        if expectation_id not in vocabulary:
            raise _refuse(
                "classref_unknown_expectation",
                f"{expectation_id} is outside the reference's expect vocabulary",
            )
        if expectation_id.rsplit(".", 1)[-1].startswith("abort/"):
            raise _refuse(
                "classref_deviation_forbidden",
                f"{expectation_id} names an energy-removing action's reachability; "
                "nothing may stand between the operator and abort",
            )
    return document


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
    derived_binding_ids = {row["id"] for row in composed["bindings"]}
    for row in overrides.get("bindings", []):
        if str(row.get("id")) not in derived_binding_ids:
            raise _refuse(
                "overlay_delete_refused",
                f"binding {row.get('id')!r} is not a derived row (deletions refuse)",
            )
    if "extensions" in overrides:
        composed["extensions"] = {**composed.get("extensions", {}), **overrides["extensions"]}
    result: dict[str, Any] = composed
    return result
