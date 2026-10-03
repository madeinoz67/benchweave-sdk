"""The closed operation catalogue: the one contract behind REST, HTML and MCP.

SW-10's full 18-name set is defined here as data on day one; I1 marks six
operations implemented and the seam refuses the other twelve with
``unavailable`` and a ``reason: increment_deferral`` detail rather than
silently omitting them — ``host_info`` reports both sets so an agent cannot
assume a capability the increment does not ship (the SW-32 honesty rule
applied to our own roadmap).

The error vocabulary and its HTTP statuses live in :mod:`.errors`, pinned
against the vendored interface catalog by test. Nothing in this module is
inferred from a Python signature: input and result schemas are explicit data,
and the MCP registration pins them verbatim onto the served tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_IDENT = {"type": "string", "minLength": 1, "description": "Device id"}


@dataclass(frozen=True, slots=True)
class OperationSpec:
    """One catalogue row: name, implementation state, and wire schemas.

    ``error_codes`` is the closed interface-0.1.0 vocabulary
    (:data:`benchweave_sdk_server.errors.ERROR_CODES`), uniform across
    operations: the refusal model is the seam's, not per-operation.
    """

    name: str
    implemented: bool
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    result_schema: dict[str, Any] = field(default_factory=dict)
    error_codes: frozenset[str] = field(default_factory=lambda: frozenset())

    def __post_init__(self) -> None:
        if not self.implemented:
            return
        if not self.input_schema or not self.result_schema:
            raise ValueError(f"standalone_catalogue_schema_missing: {self.name}")


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_HOST_INFO_RESULT = _object(
    {
        "mode": {"type": "string", "const": "standalone"},
        "absent_guarantees": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Gateway guarantees this host does not provide",
        },
        "served_operations": {"type": "array", "items": {"type": "string"}},
        "deferred_operations": {"type": "array", "items": {"type": "string"}},
        "plugin": {
            "type": "object",
            "properties": {
                "package": {"type": "string"},
                "version": {"type": "string"},
                "descriptor_sha256": {"type": "string"},
            },
            "required": ["package", "version", "descriptor_sha256"],
            "additionalProperties": False,
        },
        "transport": {"type": "string"},
        "sdk_version": {"type": "string"},
        "presentation": {
            "type": "object",
            "properties": {
                "features": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "UI features this host declares (SW-41)",
                },
                "panels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Host panels this host declares",
                },
                "unavailable_pages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional manifest pages whose panel this host lacks",
                },
            },
            "required": ["features", "panels", "unavailable_pages"],
            "additionalProperties": False,
        },
    },
    ["mode", "absent_guarantees", "served_operations", "deferred_operations",
     "plugin", "transport", "sdk_version", "presentation"],
)

_DEVICE_SUMMARY = {
    "type": "object",
    "properties": {
        "id": _IDENT,
        "manufacturer": {"type": "string"},
        "model": {"type": "string"},
        "transport": {"type": "string"},
        "connection_key": {"type": "string"},
    },
    "required": ["id", "manufacturer", "model", "transport", "connection_key"],
    "additionalProperties": False,
}

_IDENTITY_RESULT = _object(
    {
        "manufacturer": {"type": "string"},
        "model": {"type": "string"},
        "serial": {"type": "string"},
        "firmware": {"type": "string"},
        "source": {"type": "string"},
    },
    ["manufacturer", "model", "serial", "firmware", "source"],
)

_READING_RESULT = _object(
    {
        "parameter": {"type": "string"},
        # The value is whatever the descriptor's parameter type declares
        # (float/int are number, bool is boolean, enum/string are string)
        # or null when the device serves no value (the loading state) —
        # fastmcp validates structured output against this schema, so it
        # must admit what the pipeline can honestly serve.
        "value": {"type": ["number", "string", "boolean", "null"]},
        "unit": {"type": ["string", "null"]},
        "observed_at": {"type": "string"},
        "age_ms": {"type": "integer"},
        "quality": {"type": "string"},
        "source": {"type": "string"},
    },
    ["parameter", "value", "unit", "observed_at", "age_ms", "quality", "source"],
)


# The staged value carries whatever the descriptor's parameter type
# declares (float/int are number, bool is boolean, enum/string are string).
_STAGE_VALUE = {"type": ["number", "string", "boolean"]}

_STAGE_RESULT = _object(
    {
        "device_id": _IDENT,
        "parameter": {"type": "string", "minLength": 1},
        "value": _STAGE_VALUE,
        "staged": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Every staged parameter name, in staging order",
        },
    },
    ["device_id", "parameter", "value", "staged"],
)

_APPLIED_ROW = _object(
    {
        "parameter": {"type": "string"},
        "value": {"type": ["number", "string", "boolean", "null"]},
        "unit": {"type": ["string", "null"]},
        "observed_at": {"type": "string"},
        "age_ms": {"type": "integer"},
        "quality": {"type": "string"},
        "source": {"type": "string"},
    },
    ["parameter", "value", "unit", "observed_at", "age_ms", "quality", "source"],
)

_APPLY_RESULT = _object(
    {
        "device_id": _IDENT,
        "applied": {
            "type": "array",
            "items": _APPLIED_ROW,
            "description": "One row per applied parameter, from the read-back",
        },
    },
    ["device_id", "applied"],
)

_PRESET_ROW = _object(
    {
        "id": {"type": "string", "minLength": 1},
        "title": {"type": "string"},
        "sha256": {"type": "string", "minLength": 64, "maxLength": 64},
    },
    ["id", "title", "sha256"],
)

_PRESET_LIST_RESULT = _object(
    {"presets": {"type": "array", "items": _PRESET_ROW}}, ["presets"]
)

_PRESET_APPLY_RESULT = _object(
    {
        "device_id": _IDENT,
        "preset_id": {"type": "string", "minLength": 1},
        "applied": {
            "type": "array",
            "items": _APPLIED_ROW,
            "description": "One row per preset setting, from the read-back",
        },
    },
    ["device_id", "preset_id", "applied"],
)


def _spec(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    result_schema: dict[str, Any],
) -> OperationSpec:
    from .errors import ERROR_CODES

    return OperationSpec(
        name=name,
        implemented=True,
        description=description,
        input_schema=input_schema,
        result_schema=result_schema,
        error_codes=ERROR_CODES,
    )


def _deferred(name: str, description: str) -> OperationSpec:
    return OperationSpec(
        name=name,
        implemented=False,
        description=description,
        error_codes=frozenset(),
    )


#: The closed SW-10 catalogue, in the PRD's own listing order. Implemented
#: rows carry the closed error vocabulary; deferred rows carry none (they
#: are refused before any vocabulary-bearing execution happens).
CATALOGUE: tuple[OperationSpec, ...] = (
    _spec(
        "host_info",
        (
            "This host's identity and honesty snapshot: mode standalone, the "
            "gateway guarantees it does not provide, the served and deferred "
            "operation sets, the loaded plugin, the transport kind and the "
            "SDK version."
        ),
        _object({}, []),
        _HOST_INFO_RESULT,
    ),
    _spec(
        "device_discover",
        "List the devices this host's one adapter session can serve.",
        _object({}, []),
        _object({"devices": {"type": "array", "items": _DEVICE_SUMMARY}}, ["devices"]),
    ),
    _spec(
        "device_connect",
        "Open the adapter session bound to one device.",
        _object({"device_id": _IDENT}, ["device_id"]),
        _object(
            {"device_id": _IDENT, "connected": {"type": "boolean"}},
            ["device_id", "connected"],
        ),
    ),
    _spec(
        "device_disconnect",
        "Close the adapter session; idempotent per device.",
        _object({"device_id": _IDENT}, ["device_id"]),
        _object(
            {"device_id": _IDENT, "connected": {"type": "boolean"}},
            ["device_id", "connected"],
        ),
    ),
    _spec(
        "device_get",
        "Identify one connected device through its adapter.",
        _object({"device_id": _IDENT}, ["device_id"]),
        _IDENTITY_RESULT,
    ),
    _spec(
        "parameter_read",
        "Read one readable parameter from a connected device.",
        _object(
            {"device_id": _IDENT, "parameter": {"type": "string", "minLength": 1}},
            ["device_id", "parameter"],
        ),
        _READING_RESULT,
    ),
    _spec(
        "parameter_stage",
        (
            "Stage one parameter value as host state, validated against the "
            "descriptor's declared access, type and range. Staging performs "
            "no device I/O (SW-23)."
        ),
        _object(
            {"device_id": _IDENT, "parameter": {"type": "string", "minLength": 1},
             "value": _STAGE_VALUE},
            ["device_id", "parameter", "value"],
        ),
        _STAGE_RESULT,
    ),
    _spec(
        "parameter_apply",
        (
            "Apply every staged value in staging order: one write per "
            "parameter under the descriptor's declared write timeout, then "
            "a read-back — the results come only from the read-back (SW-23)."
        ),
        _object({"device_id": _IDENT}, ["device_id"]),
        _APPLY_RESULT,
    ),
    _spec(
        "preset_list",
        (
            "List the plugin's declared configuration presets with their "
            "content digests. Reads local plugin files only; no device I/O "
            "(SW-43)."
        ),
        _object({}, []),
        _PRESET_LIST_RESULT,
    ),
    _spec(
        "preset_apply",
        (
            "Apply one configuration preset: validated offline, firmware-gated "
            "against the established device identity before any write, then "
            "applied through the write/read-back path — exactly the preset's "
            "own settings; previously staged values are neither applied nor "
            "discarded (SW-43)."
        ),
        _object(
            {"device_id": _IDENT, "preset_id": {"type": "string", "minLength": 1}},
            ["device_id", "preset_id"],
        ),
        _PRESET_APPLY_RESULT,
    ),
    _deferred("capture_start", "Start a bounded capture (I3: capture, SW-50)."),
    _deferred("capture_stop", "Stop a running capture (I3: capture, SW-51)."),
    _deferred("capture_list", "List stored captures (I3: capture, SW-49)."),
    _deferred("capture_get", "Fetch one capture's manifest (I3: capture)."),
    _deferred("capture_series", "Fetch a decimated capture series (I3: capture, SW-33)."),
    _deferred("capture_annotate", "Annotate a stored capture (I3: capture, SW-54)."),
    _deferred("artifact_read", "Read a bounded artifact window (I3: capture artifacts)."),
    _spec(
        "events_get",
        (
            "Fetch the seam's events after a cursor: every state change "
            "(connect, disconnect, stage, apply, preset, reload and the "
            "refusal classes) in one monotonic gap-free order — the same "
            "sequence the /events stream carries."
        ),
        _object(
            {
                "after_id": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Return events with id greater than this cursor",
                }
            },
            ["after_id"],
        ),
        _object(
            {
                "events": {
                    "type": "array",
                    "items": _object(
                        {
                            "id": {"type": "integer"},
                            "kind": {"type": "string"},
                            "data": {"type": "object"},
                        },
                        ["id", "kind", "data"],
                    ),
                },
                "last_id": {
                    "type": "integer",
                    "description": "The newest event id (0 when nothing published)",
                },
            },
            ["events", "last_id"],
        ),
    ),
)

_BY_NAME: dict[str, OperationSpec] = {row.name: row for row in CATALOGUE}


def spec(name: str) -> OperationSpec | None:
    """Return the catalogue row for ``name``, or ``None`` when unknown."""
    return _BY_NAME.get(name)


def served_operations() -> tuple[str, ...]:
    """The implemented operation names, in catalogue order."""
    return tuple(row.name for row in CATALOGUE if row.implemented)


def deferred_operations() -> tuple[str, ...]:
    """The refused-but-declared operation names, in catalogue order."""
    return tuple(row.name for row in CATALOGUE if not row.implemented)


#: The gateway guarantees a standalone host does not provide (SW-32/NFR-S7
#: disclosure; surfaced by ``host_info`` and the UI banner's title attribute).
ABSENT_GUARANTEES: tuple[str, ...] = (
    "leases",
    "policy",
    "approvals",
    "procedures",
    "runs",
)
