"""Resolve the descriptor's pinned profile contracts for the invoke path
(issue #589 §3.1, PR-2).

A port of the gateway's ``registry/otdp_contracts.py::resolve_otdp_contracts``,
one boundary over: the gateway resolves pins against a bundle inventory its
loader already digest-verified; this host reads the pinned bytes from the
plugin's own package through the same strict no-follow containment
``verify_provider_pin`` uses. The refusal taxonomy is the gateway's —
integrity-hard at construction, completeness-soft at the verb:

* CONSTRUCTION-hard (:class:`ValueError`, the ``profile_contract_*:`` STD-4
  family) — pinned bytes that ARE present and LIE: a pin that does not name
  a contained regular file (traversal, absolute, symlinked), a digest
  mismatch, unparsable bytes, a document that is neither measurement-shaped
  nor valid against the vendored profile-catalog schema — WHATEVER its URN,
  the maintainer's final ruling (2026-11-06): the pin's ``id`` is
  plugin-chosen, so any skip keyed on the URN would be a gate the plugin
  itself operates, and the gateway raises ActivationRejected at load for
  the same bytes — more than one catalog, more than one measurement schema,
  a measurement schema whose dataset definition declares no required keys
  (the detector would degenerate to "every object"), and any ``$ref`` or
  ``$dynamicRef`` that does not resolve within the pinned set, rooted
  exactly where the runtime validators root it (each action's input AND
  output subschema, and the measurement dataset wrapper).
* VERB-level soft — a pin whose path names no file in the package, or a
  cleanly-resolving half pair, resolves NO class surface: ``None`` comes
  back and ``invoke`` answers ``unavailable`` with
  ``reason: contracts_unresolved`` (nothing was verified false — the class
  surface simply cannot be assembled from this bundle).

External ``$ref`` retrieval is disabled: the compiled validators resolve
through a CLOSED ``referencing`` registry holding exactly the pinned
documents and their embedded ``$id`` subschemas (the classref
vendor-catalog precedent) — no retrieve callable, so an in-bundle ref
resolves and anything else raises at the load-time probe, never lazily at
dispatch.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from benchweave_sdk.served import active_version
from benchweave_sdk.validation import contract_documents

from .session import LoadedPlugin

#: The catalog document's schema (the ACTIVE vendored version, never a
#: hardcoded version constant — the gateway's ``CATALOG_SCHEMA_NAME`` rule).
CATALOG_SCHEMA_NAME = "device-profile-catalog.schema.json"

_MEASUREMENT_URN_PREFIX = "urn:otdp:measurement:"

_CATALOG_VALIDATOR: Draft202012Validator | None = None


@dataclass(frozen=True, slots=True)
class CompiledAction:
    """One catalog action's compiled validators and declarations, compiled
    once per resolution and cached (the gateway's CompiledAction shape)."""

    input_validator: Draft202012Validator
    output_validator: Draft202012Validator
    side_effect: str
    lifecycle: str


@dataclass(frozen=True, slots=True)
class ResolvedContracts:
    """The complete pinned class surface: the catalog's compiled action
    registry and the pinned measurement schema's dataset shape.

    ``dataset_required_keys`` is the dataset-shaped detector (a result
    carrying every ``$defs/dataset`` required key); ``dataset_validator``
    is the compiled dataset half, carried here so the pair stays one
    resolution — the dataset admission path (PR-3) consumes it.
    """

    actions: Mapping[str, CompiledAction]
    dataset_required_keys: frozenset[str]
    dataset_validator: Draft202012Validator

    def is_dataset_shaped(self, result: Any) -> bool:
        """The manifest's required keys all present (required keys only, so
        the honest channel for a dataset-shaped result names the absent
        admission surface, not a subschema miss)."""
        return isinstance(result, dict) and (
            self.dataset_required_keys <= set(result)
        )


def _catalog_validator() -> Draft202012Validator:
    """The vendored catalog-schema validator, resolved through the same
    digest-verified loader every vendored document reads through."""
    global _CATALOG_VALIDATOR
    if _CATALOG_VALIDATOR is None:
        key = f"otdp/{active_version('otdp')}/{CATALOG_SCHEMA_NAME}"
        schema = contract_documents().get(key)
        if not isinstance(schema, dict):
            raise ValueError(
                f"profile_contract_invalid: the vendored tree carries no "
                f"{key} to validate pinned catalogs against; re-run "
                "sync-standards or reinstall the SDK"
            )
        _CATALOG_VALIDATOR = Draft202012Validator(
            schema, format_checker=FormatChecker()
        )
    return _CATALOG_VALIDATOR


def _is_measurement_schema(document: dict[str, Any]) -> bool:
    """The pinned measurement schema, identified by its ``$id`` urn and
    ``$defs/dataset`` presence (shape, never the pin's own id claim)."""
    identifier = document.get("$id")
    defs = document.get("$defs")
    return (
        isinstance(identifier, str)
        and identifier.startswith(_MEASUREMENT_URN_PREFIX)
        and isinstance(defs, dict)
        and "dataset" in defs
    )


def _walk_refs(node: Any, refs: list[str]) -> None:
    """Collect every reference target — ``$ref`` AND ``$dynamicRef`` (a
    dangling dynamic reference raises lazily at validation exactly a
    dangling static one does)."""
    if isinstance(node, dict):
        for keyword in ("$ref", "$dynamicRef"):
            ref = node.get(keyword)
            if isinstance(ref, str):
                refs.append(ref)
        for value in node.values():
            _walk_refs(value, refs)
    elif isinstance(node, list):
        for item in node:
            _walk_refs(item, refs)


def _walk_ids(node: Any, ids: list[tuple[str, dict[str, Any]]]) -> None:
    """Collect every ``$id``-bearing subschema."""
    if isinstance(node, dict):
        identifier = node.get("$id")
        if isinstance(identifier, str):
            ids.append((identifier, node))
        for value in node.values():
            _walk_ids(value, ids)
    elif isinstance(node, list):
        for item in node:
            _walk_ids(item, ids)


def _closed_registry(documents: list[tuple[str, dict[str, Any]]]) -> Registry:
    """A registry over exactly the pinned set: every ``$id``-bearing
    subschema (embedded action schemas included) as its own resource,
    crawled so subschema ids and anchors resolve. No retrieve callable —
    resolution outside the pinned set is impossible by construction."""
    registry: Registry = Registry()
    for _identifier, document in documents:
        ids: list[tuple[str, dict[str, Any]]] = []
        _walk_ids(document, ids)
        for uri, subschema in ids:
            registry = registry.with_resource(
                uri,
                Resource.from_contents(subschema, default_specification=DRAFT202012),
            )
    return registry.crawl()


def _probe_runtime_schemas(
    catalog: tuple[str, dict[str, Any]] | None,
    measurement: tuple[str, dict[str, Any]] | None,
    registry: Registry,
) -> None:
    """The load-time reference probe: every ``$ref`` and ``$dynamicRef`` in
    every schema the RUNTIME validators are built from must resolve within
    the pinned set, rooted exactly where the runtime roots it — each
    action's input AND output schema (the per-action subschema the
    validators validate against, NOT the catalog document) and the
    measurement dataset wrapper. An unresolvable reference is a
    construction refusal, never a lazy PointerToNowhere escaping
    dispatch-time validation."""
    roots: list[tuple[str, dict[str, Any]]] = []
    if catalog is not None:
        for action_id, spec in catalog[1].get("actions", {}).items():
            roots.append((f"{catalog[0]}:{action_id}:input", spec["input_schema"]))
            roots.append((f"{catalog[0]}:{action_id}:output", spec["output_schema"]))
    if measurement is not None:
        defs = measurement[1].get("$defs", {})
        roots.append(
            (f"{measurement[0]}:dataset", {"$ref": "#/$defs/dataset", "$defs": defs})
        )
    for label, schema in roots:
        refs: list[str] = []
        _walk_refs(schema, refs)
        if not refs:
            continue
        resolver = registry.resolver_with_root(
            Resource.from_contents(schema, default_specification=DRAFT202012)
        )
        for ref in dict.fromkeys(refs):
            try:
                resolver.lookup(ref)
            except Unresolvable:
                raise ValueError(
                    f"profile_contract_invalid: {label}: {ref} does not "
                    "resolve within the pinned contract set"
                ) from None


def _read_pin(package_root: Path, relative: Any) -> bytes | None:
    """Read one pinned file from the plugin's package.

    The pin must name a package-relative regular file through the strict
    no-follow posture ``verify_provider_pin`` established (no traversal, no
    absolute path, no drive-colon segment, no symlinked component). A
    contained path that names no file is the SOFT unresolved arm — None —
    never a refusal: no bytes exist to disagree with anything.
    """
    from benchweave_sdk.presentation import INPUT_BYTE_LIMIT

    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        # A colon segment anchors a Windows join outside the package;
        # judged as a string so the rule is platform-blind.
        or ":" in relative
        or PurePosixPath(relative).is_absolute()
        or any(part in (".", "..") for part in relative.split("/"))
        or any(not part for part in relative.split("/"))
    ):
        raise ValueError(
            f"profile_contract_missing: {relative!r} is not a package-relative "
            "pin path"
        )
    target = package_root
    for part in PurePosixPath(relative).parts:
        target = target / part
        if target.is_symlink():
            raise ValueError(
                f"profile_contract_missing: {relative!r} crosses a symlink; "
                "the SDK reads contract pins through a strict no-follow "
                "posture"
            )
    if not target.is_file():
        return None
    if not target.resolve().is_relative_to(package_root.resolve()):
        raise ValueError(
            f"profile_contract_missing: {relative!r} does not name a "
            "contained regular file in the plugin package"
        )
    size = target.stat().st_size
    if size > INPUT_BYTE_LIMIT:
        # The SDK-wide bounded-read cap, disclosed as the provider pin's
        # own known wound: an SDK resource bound, not a semantic
        # disagreement the gateway shares.
        raise ValueError(
            f"profile_contract_invalid: {relative!r} is {size} bytes, above "
            f"the SDK's {INPUT_BYTE_LIMIT}-byte bounded-read cap"
        )
    try:
        return target.read_bytes()
    except OSError as exc:
        raise ValueError(
            f"profile_contract_missing: {relative!r} could not be read "
            f"(os error {exc.errno})"
        ) from exc


def resolve_invoke_contracts(plugin: LoadedPlugin) -> ResolvedContracts | None:
    """Resolve the descriptor's ``contracts`` entries against the plugin's
    own package bytes.

    Returns the complete class surface when the pinned set resolves to
    exactly one catalog-schema-valid profile catalog AND the measurement
    schema; ``None`` when the descriptor pins no contracts, a pinned path
    is absent from the package, or the pair is incomplete (the soft
    unresolved arms — ``invoke`` refuses ``unavailable`` at the verb, never
    the load). Every integrity failure of PRESENT bytes raises
    :class:`ValueError` with a ``profile_contract_*:`` prefix at
    construction or reload, before any dispatch.
    """
    entries = plugin.descriptor.get("contracts")
    if not isinstance(entries, list) or not entries:
        return None
    package_root = plugin.package_dir
    catalog: tuple[str, dict[str, Any]] | None = None
    measurement: tuple[str, dict[str, Any]] | None = None
    documents: list[tuple[str, dict[str, Any]]] = []
    unresolved = False
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(
                "profile_contract_invalid: a contracts entry is not an object"
            )
        identifier = entry.get("id")
        relative = entry.get("path")
        declared = entry.get("sha256")
        if (
            not isinstance(identifier, str)
            or not identifier
            or not isinstance(relative, str)
            or not relative
            or not isinstance(declared, str)
            or re.fullmatch(r"[0-9a-f]{64}", declared) is None
        ):
            raise ValueError(
                "profile_contract_invalid: a contracts entry is malformed "
                "(id, path and a 64-hex sha256 are required)"
            )
        data = _read_pin(package_root, relative)
        if data is None:
            # The soft unresolved arm: no bytes exist to disagree with
            # anything — the class surface cannot be assembled from this
            # bundle, which refuses the VERB, never the load.
            unresolved = True
            continue
        digest = hashlib.sha256(data).hexdigest()
        if digest != declared:
            raise ValueError(
                f"profile_contract_hash_mismatch: {relative!r} hashes to "
                f"{digest} but the descriptor pins {declared}"
            )
        try:
            document = json.loads(data)
        except (UnicodeDecodeError, ValueError):
            raise ValueError(
                f"profile_contract_invalid: {relative!r} is not parsable JSON"
            ) from None
        if not isinstance(document, dict):
            raise ValueError(
                f"profile_contract_invalid: {relative!r} is not a JSON object"
            )
        if _is_measurement_schema(document):
            if measurement is not None:
                # Two measurement schemas leave the same ambiguity (which
                # one compiles for the dataset path) two catalogs do.
                raise ValueError(
                    "profile_contract_invalid: the pinned set carries more "
                    "than one measurement schema"
                )
            measurement = (identifier, document)
        else:
            error = next(iter(_catalog_validator().iter_errors(document)), None)
            if error is not None:
                raise ValueError(
                    f"profile_contract_invalid: {identifier} is neither "
                    "measurement-shaped nor valid against the vendored "
                    f"profile-catalog schema at {error.json_path}: "
                    f"{error.message}"
                )
            if catalog is not None:
                raise ValueError(
                    "profile_contract_invalid: the pinned set carries more "
                    "than one profile catalog (overlapping action ids would "
                    "let merge order silently pick the input schema that "
                    "gates I4)"
                )
            catalog = (identifier, document)
        documents.append((identifier, document))
    registry = _closed_registry(documents)
    _probe_runtime_schemas(catalog, measurement, registry)
    if unresolved or catalog is None or measurement is None:
        # The soft arms: an unassemblable set or a cleanly-resolving half
        # pair — no compiled registry, verb-level unavailable.
        return None
    actions: dict[str, CompiledAction] = {}
    for action_id, spec in catalog[1].get("actions", {}).items():
        actions[action_id] = CompiledAction(
            input_validator=Draft202012Validator(
                spec["input_schema"], registry=registry
            ),
            output_validator=Draft202012Validator(
                spec["output_schema"], registry=registry
            ),
            side_effect=str(spec["side_effect"]),
            lifecycle=str(spec["lifecycle"]),
        )
    defs = measurement[1].get("$defs", {})
    dataset_def = defs.get("dataset")
    if not isinstance(dataset_def, dict):
        raise ValueError(
            "profile_contract_invalid: the pinned measurement schema "
            "carries no dataset definition"
        )
    required = frozenset(str(key) for key in dataset_def.get("required", []))
    if not required:
        # Present bytes that lie: an empty required set degenerates the
        # dataset-shape detector to "every object" — every dict result
        # would read as a dataset. Refuse at construction.
        raise ValueError(
            "profile_contract_invalid: the pinned measurement schema's "
            "$defs/dataset declares no required keys"
        )
    dataset_validator = Draft202012Validator(
        {"$ref": "#/$defs/dataset", "$defs": defs}, registry=registry
    )
    return ResolvedContracts(
        actions=actions,
        dataset_required_keys=required,
        dataset_validator=dataset_validator,
    )


def check_action_budget_feasibility(plugin: LoadedPlugin) -> None:
    """The load-time cross-field check (issue #589 §3.2, D8 MITIGATED not
    PREVENTED): every declared action's ``timeout_ms`` must fit the serving
    invoke verb's declared budget, refused with
    ``standalone_action_budget_infeasible:`` naming the action, its timeout
    and the governing budget.

    A bound-coherence guard, NOT a completion guarantee: the per-attempt
    cost is nowhere in the descriptor, so an action whose parameter maxima
    admit work the budget cannot fit still loads (the record's worked
    example — an action at 60000 ms against a 60000 ms budget passes while
    three attempts cannot complete). What actually mitigates D8 is the
    honoured action deadline: the overrun becomes a visible typed timeout.
    """
    operations = plugin.descriptor.get("operations", {})
    invoke_policy = (
        operations.get("invoke") if isinstance(operations, dict) else None
    )
    if not isinstance(invoke_policy, dict):
        return
    budget = invoke_policy.get("timeout_ms")
    if not isinstance(budget, int) or budget <= 0:
        return
    actions = plugin.descriptor.get("actions")
    if not isinstance(actions, dict):
        return
    for action_id, row in actions.items():
        if not isinstance(row, dict):
            continue
        timeout = row.get("timeout_ms")
        if isinstance(timeout, int) and timeout > budget:
            raise ValueError(
                f"standalone_action_budget_infeasible: action {action_id} "
                f"declares timeout_ms {timeout}, above the serving invoke "
                f"verb's budget {budget}; raise the invoke operation's "
                "timeout_ms or lower the action's"
            )
