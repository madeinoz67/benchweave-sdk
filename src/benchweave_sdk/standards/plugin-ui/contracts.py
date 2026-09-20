"""Pure offline presentation validation, bundled byte-for-byte into the SDK."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

MAX_DOCUMENT_BYTES = 262144
MAX_DEPTH = 32
SCHEMA_ROOT = "https://benchweave.dev/contracts/plugin-ui/0.2.0/"


class DocumentError(ValueError):
    """A bounded JSON document could not be decoded."""

    def __init__(self, message: str, code: str = "invalid_document") -> None:
        super().__init__(message)
        self.code = code


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DocumentError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise DocumentError("Nonfinite JSON number")


def _float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise DocumentError("Nonfinite JSON number")
    return result


def parse_document(raw: bytes) -> dict[str, Any]:
    """Decode finite UTF-8 JSON without duplicate keys or excessive nesting."""
    if not isinstance(raw, bytes):
        raise DocumentError("Document must contain bytes")
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise DocumentError("Document byte limit exceeded", "limit_exceeded")
    try:
        text = raw.decode("utf-8")
        depth = 0
        quoted = False
        escaped = False
        for character in text:
            if quoted:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    quoted = False
            elif character == '"':
                quoted = True
            elif character in "[{":
                depth += 1
                if depth > MAX_DEPTH:
                    raise DocumentError("Document nesting limit exceeded", "limit_exceeded")
            elif character in "]}":
                depth -= 1
        value = json.loads(
            text, object_pairs_hook=_object, parse_constant=_constant, parse_float=_float
        )
    except DocumentError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise DocumentError("Invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise DocumentError("Document must be a JSON object")
    return value


@dataclass(frozen=True)
class Finding:
    """A stable diagnostic code and document location, without settings values."""

    code: str
    path: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    """Validation results convey compatibility, never permission to apply settings."""

    findings: tuple[Finding, ...]
    unavailable_pages: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.findings


def _schema_findings(
    document: dict[str, Any],
    schema: dict[str, Any],
    documents: Mapping[str, dict[str, Any]],
    *,
    path: str,
    code: str = "invalid_document",
) -> tuple[Finding, ...]:
    """Use only caller-supplied schemas; the registry has no network retriever."""
    try:
        Draft202012Validator.check_schema(schema)
        registry: Registry = Registry()
        for uri, candidate in documents.items():
            resource = Resource.from_contents(candidate, default_specification=DRAFT202012)
            registry = registry.with_resource(uri, resource)
            if "$id" in candidate:
                registry = registry.with_resource(candidate["$id"], resource)
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        if "$id" in schema:
            registry = registry.with_resource(schema["$id"], resource)
        validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
        error = next(validator.iter_errors(document), None)
        if error is not None:
            return (Finding(code, path, "Document does not satisfy its schema"),)
    except Unresolvable:
        return (Finding("unresolved_reference", path, "Schema reference is unavailable"),)
    except (SchemaError, ValueError, TypeError, RecursionError):
        return (Finding("invalid_schema", path, "Schema cannot be evaluated"),)
    return ()


def resolve_preset_action(
    preset: Mapping[str, Any],
    schema_documents: Mapping[str, dict[str, Any]],
) -> str | None:
    """Return the corpus action whose input schema carries the preset's identity.

    Exact, not heuristic: lane 2 requires the settings-schema ``$id`` to
    equal the bound action's corpus input-schema ``$id`` (``identity_mismatch``
    otherwise), so every preset that could pass lane 2 resolves to its own
    action, and corpus input-schema ``$id``s are urn-per-action, so the match
    cannot be ambiguous. A preset whose authored schema carries a custom
    ``$id`` resolves to ``None`` — lane 1 then applies no envelope and the
    CLI says so; inferring an action for such a preset is the heuristic this
    resolver refuses.
    """
    reference = preset.get("settings_schema")
    if not isinstance(reference, dict):
        return None
    identifier = reference.get("id")
    if not isinstance(identifier, str):
        return None
    for document in schema_documents.values():
        actions = document.get("actions")
        if not isinstance(actions, dict):
            continue
        for action_id, action in actions.items():
            if not isinstance(action, dict):
                continue
            schema = action.get("input_schema")
            if isinstance(schema, dict) and schema.get("$id") == identifier:
                return str(action_id)
    return None


def _preset_envelope_findings(
    preset: Mapping[str, Any],
    action_id: str | None,
    descriptor: Mapping[str, Any],
    documents: Mapping[str, dict[str, Any]],
    *,
    path: str,
) -> tuple[Finding, ...]:
    """Apply the action envelope AND-wise: the canonical corpus action input
    schema when resolvable, and the descriptor action's input_constraints
    (an empty constraint schema is a natural no-op under Draft202012Validator,
    same as lane 2 has always treated an unconstrained action)."""
    if action_id is None:
        return ()
    findings: list[Finding] = []
    for document in documents.values():
        actions = document.get("actions")
        if not isinstance(actions, dict) or action_id not in actions:
            continue
        action = actions[action_id]
        schema = action.get("input_schema") if isinstance(action, dict) else None
        if isinstance(schema, dict):
            findings.extend(
                _schema_findings(
                    preset["settings"], schema, documents, path=path, code="invalid_settings"
                )
            )
        break
    actions = descriptor.get("actions")
    constraints: dict[str, Any] = {}
    if isinstance(actions, dict) and isinstance(actions.get(action_id), dict):
        constraints = actions[action_id].get("input_constraints", {})
    findings.extend(
        _schema_findings(
            preset["settings"], constraints, documents, path=path, code="invalid_settings"
        )
    )
    return tuple(findings)


def validate_preset(
    raw: bytes,
    *,
    descriptor_raw: bytes,
    settings_schema_raw: bytes,
    schema_documents: Mapping[str, dict[str, Any]],
    firmware: str | None,
    action_id: str | None = None,
) -> ValidationReport:
    """Check a complete preset offline; do not merge defaults or perform device I/O.

    The descriptor is supplied by the caller's existing admission or SDK checks.
    This helper establishes preset compatibility and does not admit that descriptor.

    ``action_id`` names the action whose envelope applies: an explicit id wins
    (one absent from the descriptor is refused as ``unresolved_reference`` on
    ``preset.action``, never silently skipped); with no explicit id the action
    resolves from the preset's settings-schema identity
    (``resolve_preset_action``) — a custom-``$id`` schema applies no envelope.
    """
    decoded = []
    for path, source in (
        ("preset", raw),
        ("descriptor", descriptor_raw),
        ("settings_schema", settings_schema_raw),
    ):
        try:
            decoded.append(parse_document(source))
        except DocumentError as exc:
            return ValidationReport((Finding(exc.code, path, str(exc)),))
    preset, descriptor, settings_schema = decoded
    if preset.get("contract_version") != "0.2.0":
        return ValidationReport(
            (
                Finding(
                    "unsupported_version", "preset.contract_version", "Unsupported preset version"
                ),
            )
        )
    preset_schema = schema_documents.get(SCHEMA_ROOT + "configuration-preset.schema.json")
    if preset_schema is None:
        return ValidationReport(
            (Finding("invalid_schema", "preset", "Canonical preset schema is unavailable"),)
        )
    findings = list(_schema_findings(preset, preset_schema, schema_documents, path="preset"))
    if findings:
        return ValidationReport(tuple(findings))
    if descriptor.get("id") != preset["plugin_id"]:
        findings.append(
            Finding("identity_mismatch", "preset.plugin_id", "Preset targets a different plugin")
        )
    profiles = descriptor.get("profiles", [])
    if not isinstance(profiles, list) or any(
        profile not in profiles for profile in preset["profile_ids"]
    ):
        findings.append(
            Finding(
                "capability_mismatch", "preset.profile_ids", "Preset requires unavailable profiles"
            )
        )
    identity = descriptor.get("identity", {})
    if not isinstance(identity, dict):
        identity = {}
    if (
        firmware is None
        or firmware not in preset["supported_firmware"]
        or (
            identity.get("firmware_policy") != "any"
            and firmware not in identity.get("supported_firmware", [])
        )
    ):
        findings.append(
            Finding(
                "incompatible_firmware",
                "preset.supported_firmware",
                "A known firmware compatible with the descriptor and preset is required",
            )
        )
    reference = preset["settings_schema"]
    if hashlib.sha256(settings_schema_raw).hexdigest() != reference["sha256"]:
        findings.append(
            Finding(
                "digest_mismatch", "preset.settings_schema.sha256", "Settings schema bytes differ"
            )
        )
    if settings_schema.get("$id") != reference["id"]:
        findings.append(
            Finding(
                "identity_mismatch", "preset.settings_schema.id", "Settings schema identity differs"
            )
        )
    findings.extend(
        _schema_findings(
            preset["settings"],
            settings_schema,
            schema_documents,
            path="preset.settings",
            code="invalid_settings",
        )
    )
    if action_id is not None and action_id not in descriptor.get("actions", {}):
        findings.append(
            Finding(
                "unresolved_reference",
                "preset.action",
                "Named action is absent from the descriptor",
            )
        )
    else:
        resolved = (
            action_id
            if action_id is not None
            else resolve_preset_action(preset, schema_documents)
        )
        findings.extend(
            _preset_envelope_findings(
                preset, resolved, descriptor, schema_documents, path="preset.settings"
            )
        )
    return ValidationReport(tuple(findings))


def safe_resource_path(name: str) -> bool:
    """Accept portable relative paths without normalising away escapes."""
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-/"
    return (
        isinstance(name, str)
        and 0 < len(name) <= 1024
        and all(character in alphabet for character in name)
        and all(part not in ("", ".", "..") for part in name.split("/"))
    )


class _Rejected(Exception):
    def __init__(self, findings: tuple[Finding, ...]) -> None:
        self.findings = findings


def _checked_document(
    raw: bytes, name: str, documents: Mapping[str, dict[str, Any]]
) -> dict[str, Any]:
    document = parse_document(raw)
    if document.get("contract_version") != "0.2.0":
        raise _Rejected((Finding("unsupported_version", name, "Unsupported contract version"),))
    schema = documents.get(SCHEMA_ROOT + name + ".schema.json")
    if schema is None:
        raise _Rejected((Finding("invalid_schema", name, "Canonical schema unavailable"),))
    findings = _schema_findings(document, schema, documents, path=name)
    if findings:
        raise _Rejected(findings)
    return document


def _unique_rows(rows: list[dict[str, Any]], path: str) -> dict[str, dict[str, Any]]:
    result = {row["id"]: row for row in rows}
    if len(result) != len(rows):
        raise _Rejected((Finding("invalid_document", path, "Duplicate identifiers"),))
    return result


def _resource(reference: dict[str, Any], resources: Mapping[str, bytes]) -> bytes:
    name = reference["path"]
    if not safe_resource_path(name):
        raise _Rejected((Finding("unsafe_path", "resource", "Unsafe resource path"),))
    if name not in resources:
        raise _Rejected((Finding("unresolved_reference", name, "Resource unavailable"),))
    raw = resources[name]
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise _Rejected((Finding("digest_mismatch", name, "Resource bytes differ"),))
    return raw


def _target_findings(
    target: dict[str, Any],
    descriptor: dict[str, Any],
    documents: Mapping[str, dict[str, Any]],
) -> list[Finding]:
    findings = []
    path = "targets." + target["id"]
    mismatch = Finding("capability_mismatch", path, "Target exceeds descriptor capabilities")
    variables = _unique_rows(target.get("variables", []), path + ".variables")
    if target["kind"] == "observation":
        parameters = {row["name"]: row for row in descriptor.get("parameters", [])}
        parameter = parameters.get(target["parameter_id"])
        if (
            parameter is None
            or parameter.get("access") not in ("ro", "rw")
            or "read" not in descriptor.get("capabilities", [])
        ):
            return [mismatch]
        types = {"float": "number", "int": "integer", "bool": "boolean", "string": "string"}
        values = [row for row in variables.values() if row.get("axis_role") != "receipt_time"]
        if len(values) != 1 or any(
            row["type"] != types.get(parameter["type"])
            or row["unit"] != parameter.get("unit")
            or row["shape"] != "scalar"
            for row in values
        ):
            findings.append(mismatch)
        times = [row for row in variables.values() if row.get("axis_role") == "receipt_time"]
        if len(times) > 1 or any(
            row["type"] != "number" or row["unit"] != "s" or row["shape"] != "scalar"
            for row in times
        ):
            findings.append(mismatch)
        if "channel_id" in target and not any(
            channel["id"] == target["channel_id"]
            and target["parameter_id"] in channel.get("parameter_names", [])
            for channel in descriptor.get("channels", [])
        ):
            findings.append(mismatch)
    else:
        action = target["action_id"]
        if (
            action not in descriptor.get("actions", {})
            or "invoke" not in descriptor.get("capabilities", [])
            or any(p not in descriptor.get("profiles", []) for p in target["profile_ids"])
        ):
            findings.append(mismatch)
        profile_map = {
            profile["id"]: profile
            for document in documents.values()
            for profile in document.get("profiles", [])
            if isinstance(profile, dict) and "id" in profile
        }
        if not target["profile_ids"] or any(
            profile not in profile_map
            or action
            not in (
                profile_map[profile].get("required_actions", [])
                + profile_map[profile].get("optional_actions", [])
            )
            for profile in target["profile_ids"]
        ):
            findings.append(mismatch)
        schema_id = target.get("input_schema_id", target.get("measurement_schema_id"))
        if target["kind"] == "dataset" and not any(
            reference.get("id") == schema_id for reference in descriptor.get("contracts", [])
        ):
            findings.append(mismatch)
        if schema_id not in documents:
            findings.append(Finding("unresolved_reference", path, "Target schema unavailable"))
        if "input_schema_id" in target:
            action_schemas = [
                document["actions"][action].get("input_schema", {}).get("$id")
                for document in documents.values()
                if isinstance(document.get("actions"), dict) and action in document["actions"]
            ]
            if schema_id not in action_schemas:
                findings.append(mismatch)
    return findings


def _plot_findings(
    page: dict[str, Any],
    bindings: dict[str, dict[str, Any]],
    targets: dict[str, dict[str, Any]],
) -> list[Finding]:
    findings = []
    for plot in page.get("plots", []):
        path = "pages." + page["id"] + ".plots"
        binding = bindings.get(plot["binding_id"], {})
        target = targets.get(binding.get("target_id", ""), {})
        variables = {row["id"]: row for row in target.get("variables", [])}
        axes = [variables.get(name) for name in [plot["x"], *plot["y"]]]
        x_axis = variables.get(plot["x"], {})
        shape = "vector" if plot["kind"] == "waveform" else "scalar"
        if (
            plot["binding_id"] not in page["bindings"]
            or target.get("kind") not in ("observation", "dataset")
            or any(
                row is None or row["type"] not in ("number", "integer") or row["shape"] != shape
                for row in axes
            )
            or plot["x"] in plot["y"]
        ):
            findings.append(Finding("invalid_plot", path, "Plot axes are incompatible"))
        elif plot["kind"] == "time_series" and (
            x_axis.get("axis_role") != "receipt_time" or x_axis["unit"] != "s"
        ):
            findings.append(
                Finding("invalid_plot", path, "Time series needs receipt time in seconds")
            )
        # channel_hints (introduced 0.1.1): membership in THIS plot's y and
        # duplicate ids are semantic checks on the Python seam; shape, enum,
        # booleans and item counts are the schema's job in the corpus. A
        # variable of the bound target that this plot does not list in y is
        # not hintable here.
        hinted: set[str] = set()
        for hint in plot.get("channel_hints", []):
            variable_id = hint["variable_id"]
            if variable_id not in plot["y"]:
                findings.append(
                    Finding(
                        "unresolved_reference",
                        path + ".channel_hints",
                        "Channel hint names a variable outside this plot's y channels",
                    )
                )
            elif variable_id in hinted:
                findings.append(
                    Finding("invalid_document", path + ".channel_hints", "Duplicate identifiers")
                )
            hinted.add(variable_id)
    return findings


def validate_presentation(
    envelope_raw: bytes,
    *,
    descriptor_raw: bytes,
    resources: Mapping[str, bytes],
    binding_catalogue: Mapping[str, Any],
    schema_documents: Mapping[str, dict[str, Any]],
    supported_features: frozenset[str],
    supported_panels: frozenset[str],
    firmware: str | None,
) -> ValidationReport:
    """Check a candidate without loading code or activating a plugin.

    Resource keys are relative to resource_root. The caller must obtain that
    exact resource set through admission or confined SDK file checks. The
    catalogue and schema corpus come from the trusted host.
    """
    findings: list[Finding] = []
    unavailable: list[str] = []
    try:
        if len(resources) > 257 or sum(len(raw) for raw in resources.values()) > 64 * 1024 * 1024:
            raise DocumentError("Resource collection exceeds limit", "limit_exceeded")
        for name, raw in resources.items():
            if not safe_resource_path(name):
                raise _Rejected((Finding("unsafe_path", "resources", "Unsafe resource path"),))
            if not isinstance(raw, bytes):
                raise DocumentError("Resource must contain bytes")
            if len(raw) > 16 * 1024 * 1024:
                raise DocumentError("Resource byte limit exceeded", "limit_exceeded")
        documents = dict(schema_documents)
        for document in tuple(documents.values()):
            if "$id" in document:
                documents[document["$id"]] = document
            for action in document.get("actions", {}).values():
                for key in ("input_schema", "output_schema"):
                    schema = action.get(key, {})
                    if "$id" in schema:
                        documents[schema["$id"]] = schema
        descriptor = parse_document(descriptor_raw)
        expected = hashlib.sha256(descriptor_raw).hexdigest()
        envelope = _checked_document(envelope_raw, "presentation-envelope", documents)
        if not safe_resource_path(envelope["resource_root"]):
            raise _Rejected((Finding("unsafe_path", "resource_root", "Unsafe resource root"),))
        manifest = _checked_document(
            _resource(envelope["manifest"], resources), "ui-manifest", documents
        )
        catalogue = _checked_document(
            json.dumps(dict(binding_catalogue), allow_nan=False).encode(),
            "binding-catalogue",
            documents,
        )
        for name, document in (
            ("envelope", envelope),
            ("manifest", manifest),
            ("catalogue", catalogue),
        ):
            if document["descriptor_sha256"] != expected:
                findings.append(Finding("digest_mismatch", name, "Descriptor bytes differ"))
        if manifest["plugin_id"] != descriptor.get("id"):
            findings.append(
                Finding("identity_mismatch", "manifest.plugin_id", "Plugin identity differs")
            )
        if any(f not in supported_features for f in manifest.get("required_ui_features", [])):
            findings.append(
                Finding("unsupported_feature", "manifest", "Required UI feature unavailable")
            )
        assets = _unique_rows(manifest.get("assets", []), "assets")
        asset_bytes = {name: _resource(asset, resources) for name, asset in assets.items()}
        if len({row["path"] for row in assets.values()}) != len(assets):
            raise _Rejected((Finding("invalid_document", "assets", "Duplicate asset paths"),))
        targets = _unique_rows(catalogue["targets"], "targets")
        bindings = _unique_rows(manifest["bindings"], "bindings")
        pages = _unique_rows(manifest["pages"], "pages")
        for catalogue_target in targets.values():
            findings.extend(_target_findings(catalogue_target, descriptor, documents))
        for binding in bindings.values():
            target = targets.get(binding["target_id"])
            if target is None:
                findings.append(
                    Finding("unresolved_reference", binding["id"], "Binding target unavailable")
                )
                continue
            if binding["kind"] != target["kind"]:
                findings.append(
                    Finding("capability_mismatch", binding["id"], "Binding kind differs")
                )
            if binding["kind"] == "configuration" and target["kind"] == "configuration":
                # Membership only: a binding may expose a subset of the
                # target's declared presets, but never one it does not declare.
                for preset_id in binding.get("preset_ids", []):
                    if preset_id not in target["preset_asset_ids"] or preset_id not in asset_bytes:
                        findings.append(
                            Finding("unresolved_reference", binding["id"], "Preset unavailable")
                        )
        declared: set[str] = set()
        for target in targets.values():
            if target["kind"] != "configuration":
                continue
            path = "targets." + target["id"]
            schema_raw = asset_bytes.get(target["schema_asset_id"])
            if schema_raw is None:
                findings.append(
                    Finding("unresolved_reference", path, "Settings schema unavailable")
                )
                continue
            schema = parse_document(schema_raw)
            if schema.get("$id") != target["input_schema_id"]:
                findings.append(
                    Finding("identity_mismatch", path, "Settings schema identity differs")
                )
            # Every target-declared preset is validated whether or not any
            # binding lists it: the author wired it by declaring it, binding
            # exposure is a UI choice. A preset two bindings list is
            # validated once here (finding de-duplication on multi-binding
            # packages).
            for preset_id in target["preset_asset_ids"]:
                declared.add(preset_id)
                if preset_id not in asset_bytes:
                    findings.append(Finding("unresolved_reference", path, "Preset unavailable"))
                    continue
                report = validate_preset(
                    asset_bytes[preset_id],
                    descriptor_raw=descriptor_raw,
                    settings_schema_raw=schema_raw,
                    schema_documents=documents,
                    firmware=firmware,
                    action_id=target["action_id"],
                )
                findings.extend(report.findings)
        for asset_id, raw in asset_bytes.items():
            if asset_id in declared:
                continue
            try:
                candidate = parse_document(raw)
            except DocumentError:
                # Not preset-shaped (or over the document limit): the probe
                # refuses to guess wiring, it does not parse assets further.
                continue
            if all(key in candidate for key in ("contract_version", "settings", "settings_schema")):
                # Refused, not validated: an unclaimed preset has no action
                # association and no schema association, and inferring either
                # is the heuristic this sweep refuses. The author wires it
                # (then the target loop validates it fully) or deletes it.
                findings.append(
                    Finding(
                        "unreferenced_preset",
                        asset_id,
                        "Preset-shaped asset no configuration target declares",
                    )
                )
        allowed = {
            "configuration": {"configuration", "procedure"},
            "readings": {"observation"},
            "dataset": {"dataset"},
        }
        for page in pages.values():
            for name in page["bindings"]:
                if name not in bindings:
                    findings.append(
                        Finding("unresolved_reference", page["id"], "Page binding unavailable")
                    )
                elif (
                    page["kind"] in allowed and bindings[name]["kind"] not in allowed[page["kind"]]
                ):
                    findings.append(
                        Finding("capability_mismatch", page["id"], "Page binding kind differs")
                    )
            panel = page.get("panel_id")
            if panel is not None and panel not in supported_panels:
                unavailable.append(page["id"])
                if page["required"]:
                    findings.append(
                        Finding("panel_unavailable", page["id"], "Required panel unavailable")
                    )
            findings.extend(_plot_findings(page, bindings, targets))
    except _Rejected as exc:
        findings.extend(exc.findings)
    except DocumentError as exc:
        findings.append(Finding(exc.code, "presentation", str(exc)))
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        findings.append(Finding("invalid_document", "presentation", "Malformed presentation input"))
    return ValidationReport(tuple(findings), tuple(unavailable))
