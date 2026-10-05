"""The closed operation catalogue: the one contract behind REST, HTML and MCP.

SW-10's 18-name set is defined here as data; I3b flips the last seven
deferred rows (the six capture operations and ``artifact_read``) and adds
three new rows — ``capture_delete``/``capture_pin``/``capture_unpin`` (the
design record's fork F-2, a disclosed PRD delta: SW-56/SW-59 name the
capabilities, SW-10's closed list omits them). Every row is now served; the
seam's ``unavailable`` refusal stays for future increments rather than for
this catalogue's names.

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

# --- capture (I3b): the flipped rows and fork F-2's three new rows ---------

_FORMATS = {"enum": ["waveform_f64le", "raw_binary"]}

#: SW-33's ceilings, with their denominators: 10M samples is the record's
#: own 10-minute class at 8 B/sample against the fork's published 2 Mbaud
#: line rate (about 250 KiB/s), and 600 s is that class directly.
_COUNT_CEILING = 10_000_000
_DURATION_CEILING_S = 600

#: The writer's development-tooling reservation default (capture.py) is the
#: reservation ceiling a start request may name; the bench's configured
#: reservation (the services' constructor bound) remains the authority the
#: effective reservation never exceeds (A02).
_MAX_BYTES_CEILING = 16 * 1024 * 1024

_CAPTURE_START_INPUT = {
    "type": "object",
    "properties": {
        "device_id": _IDENT,
        "count": {
            "type": "integer",
            "minimum": 1,
            "maximum": _COUNT_CEILING,
            "description": "Sample bound (waveform_f64le: 8 B/sample; "
            "raw_binary: 1 B/sample)",
        },
        "duration_s": {
            "type": "number",
            "exclusiveMinimum": 0,
            "maximum": _DURATION_CEILING_S,
            "description": "Wall-clock bound in seconds",
        },
        "format": {
            **_FORMATS,
            "description": "The primary artifact's format (default raw_binary)",
            "default": "raw_binary",
        },
        "sample_interval_s": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "Sample interval (waveform_f64le captures)",
        },
        "unit": {
            "type": "string",
            "minLength": 1,
            "description": "Sample unit (waveform_f64le captures)",
        },
        "max_bytes": {
            "type": "integer",
            "minimum": 1,
            "maximum": _MAX_BYTES_CEILING,
            "description": "Requested byte reservation for this capture; the "
            "bench's configured reservation caps it",
        },
        "project": {"type": "string", "minLength": 1},
        "tags": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        },
        "notes": {"type": "string"},
    },
    "required": ["device_id"],
    "additionalProperties": False,
    # Exactly one of count / duration_s (SW-33): both branches pass when both
    # keys are present, so oneOf refuses the pair; neither key fails both.
    "oneOf": [{"required": ["count"]}, {"required": ["duration_s"]}],
    "allOf": [
        {
            "if": {
                "properties": {"format": {"const": "waveform_f64le"}},
                "required": ["format"],
            },
            "then": {
                "properties": {
                    "format": {"const": "waveform_f64le"},
                    "sample_interval_s": {"type": "number", "exclusiveMinimum": 0},
                    "unit": {"type": "string", "minLength": 1},
                },
                "required": ["sample_interval_s", "unit"],
            },
        }
    ],
}

_CAPTURE_START_RESULT = _object(
    {
        "capture_id": {"type": "string", "minLength": 1},
        "device_id": _IDENT,
        "state": {"const": "capturing"},
        "bound": {"type": "object"},
        "format": _FORMATS,
    },
    ["capture_id", "device_id", "state", "bound", "format"],
)

_CAPTURE_STOP_RESULT = _object(
    {
        "capture_id": {"type": "string", "minLength": 1},
        "state": {"enum": ["published", "aborted"]},
        "stop_reason": {"type": "string"},
        "manifest": {"type": ["object", "null"]},
        "details": {
            "type": ["object", "null"],
            "description": "The terminal ambiguity, verbatim: the adapter "
            "envelope's dispatch_state and message on the unknown path, or "
            "the aborting condition's own message; null when the outcome "
            "carries no ambiguity (AR-8).",
            "properties": {
                "dispatch_state": {"type": ["string", "null"]},
                "message": {"type": "string"},
            },
            "required": ["dispatch_state", "message"],
            "additionalProperties": False,
        },
    },
    ["capture_id", "state", "stop_reason", "manifest", "details"],
)

_CAPTURE_ROW = _object(
    {
        "capture_id": {"type": "string", "minLength": 1},
        "state": {"enum": ["capturing", "published", "aborted"]},
        "started_at": {"type": "string"},
        "format": {"type": "string"},
        "byte_length": {"type": ["integer", "null"]},
        "sha256": {"type": ["string", "null"]},
        "surface": {"type": ["string", "null"]},
        "project": {"type": ["string", "null"]},
        "tags": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
        "pinned": {"type": "boolean"},
        "stop_reason": {"type": ["string", "null"]},
        "progress_bytes": {"type": ["integer", "null"]},
    },
    [
        "capture_id", "state", "started_at", "format", "byte_length",
        "sha256", "surface", "project", "tags", "notes", "pinned",
        "stop_reason", "progress_bytes",
    ],
)

_CAPTURE_LIST_RESULT = _object(
    {"captures": {"type": "array", "items": _CAPTURE_ROW}}, ["captures"]
)

_CAPTURE_GET_RESULT = _object(
    {
        "capture_id": {"type": "string", "minLength": 1},
        "manifest": {"type": "object"},
        "metadata": {"type": "object"},
    },
    ["capture_id", "manifest", "metadata"],
)

_CAPTURE_SERIES_RESULT = _object(
    {
        "capture_id": {"type": "string", "minLength": 1},
        "format": {"type": "string"},
        "decimated": {"type": "boolean"},
        "max_points": {"type": "integer"},
        "points": {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
            },
            "description": "[x, y] pairs in acquisition order",
        },
    },
    ["capture_id", "format", "decimated", "max_points", "points"],
)

_CAPTURE_ANNOTATE_INPUT = _object(
    {
        "capture_id": {"type": "string", "minLength": 1},
        "notes": {"type": "string"},
        "tags": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        },
    },
    ["capture_id"],
)

_CAPTURE_ANNOTATE_RESULT = _object(
    {
        "capture_id": {"type": "string", "minLength": 1},
        "notes": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    ["capture_id", "notes", "tags"],
)

_CAPTURE_ID_INPUT = _object(
    {"capture_id": {"type": "string", "minLength": 1}}, ["capture_id"]
)

_PIN_RESULT = _object(
    {"capture_id": {"type": "string", "minLength": 1}, "pinned": {"type": "boolean"}},
    ["capture_id", "pinned"],
)

_DELETE_RESULT = _object(
    {"capture_id": {"type": "string", "minLength": 1}, "deleted": {"const": True}},
    ["capture_id", "deleted"],
)

_ARTIFACT_READ_INPUT = _object(
    {
        "capture_id": {"type": "string", "minLength": 1},
        "offset": {"type": "integer", "minimum": 0},
        "length": {"type": "integer", "minimum": 1, "maximum": 262_144},
    },
    ["capture_id", "offset", "length"],
)

_ARTIFACT_READ_RESULT = _object(
    {
        "capture_id": {"type": "string", "minLength": 1},
        "artifact_id": {"type": "string"},
        "offset": {"type": "integer", "minimum": 0},
        "length": {"type": "integer", "minimum": 0},
        "data_base64": {"type": "string"},
    },
    ["capture_id", "artifact_id", "offset", "length", "data_base64"],
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
    _spec(
        "capture_start",
        (
            "Start a bounded capture on a connected device: the adapter's "
            "declared capture verb runs and appends device bytes through "
            "the capture services; the host watches the bound (SW-33) and "
            "finalises or aborts honestly at the bound, an explicit stop, "
            "or an ambiguous stop outcome (an unknown stop never publishes "
            "complete — A06)."
        ),
        _CAPTURE_START_INPUT,
        _CAPTURE_START_RESULT,
    ),
    _spec(
        "capture_stop",
        (
            "Stop one running capture and terminal it (publish or abort); "
            "an ambiguous stop outcome aborts with stop_reason stop_unknown "
            "and the result's details carry the adapter envelope's "
            "dispatch_state and message verbatim (A06)."
        ),
        _CAPTURE_ID_INPUT,
        _CAPTURE_STOP_RESULT,
    ),
    _spec(
        "capture_list",
        (
            "List the stored captures: published rows from the rebuildable "
            "index, the in-flight capture, and this session's aborted "
            "outcomes."
        ),
        _object({}, []),
        _CAPTURE_LIST_RESULT,
    ),
    _spec(
        "capture_get",
        "Fetch one published capture's manifest and metadata.",
        _CAPTURE_ID_INPUT,
        {**_CAPTURE_GET_RESULT, "required": ["capture_id", "manifest", "metadata"]},
    ),
    _spec(
        "capture_series",
        (
            "Fetch a capture's series, decimated by default through host-side "
            "min/max-per-column decimation (SW-33: max_points 2000 default, "
            "0 serves raw points refused above the sample ceiling)."
        ),
        _object(
            {
                "capture_id": {"type": "string", "minLength": 1},
                "max_points": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 10_000_000,
                    "description": "Column budget (default 2000); 0 = raw",
                },
            },
            ["capture_id"],
        ),
        _CAPTURE_SERIES_RESULT,
    ),
    _spec(
        "capture_annotate",
        "Edit a stored capture's notes and tags (SW-54: they stay editable; "
        "everything else is fixed at start).",
        _CAPTURE_ANNOTATE_INPUT,
        _CAPTURE_ANNOTATE_RESULT,
    ),
    _spec(
        "artifact_read",
        (
            "Read a bounded window of a published capture's primary artifact "
            "as base64 (SW-31's interface-0.1.0 semantics)."
        ),
        _ARTIFACT_READ_INPUT,
        {
            **_ARTIFACT_READ_RESULT,
            "required": [
                "capture_id", "artifact_id", "offset", "length", "data_base64"
            ],
        },
    ),
    _spec(
        "events_get",
        (
            "Fetch the seam's events after a cursor: the state changes "
            "(connect, disconnect, stage, apply, preset, reload) and "
            "every refused seam operation — unknown, deferred, "
            "invalid-argument and adapter-reported alike — in one "
            "monotonic gap-free order, the same sequence the /events "
            "stream carries."
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
    # Fork F-2's disclosed delta: rows 19-21, beyond SW-10's closed 18.
    _spec(
        "capture_delete",
        (
            "Delete one stored capture: removes the event directory and its "
            "index row; refuses pinned captures and an in-flight id (SW-59)."
        ),
        _CAPTURE_ID_INPUT,
        _DELETE_RESULT,
    ),
    _spec(
        "capture_pin",
        "Pin a capture: retention (I3c) will never prune it automatically "
        "(SW-56).",
        _CAPTURE_ID_INPUT,
        _PIN_RESULT,
    ),
    _spec(
        "capture_unpin",
        "Unpin a capture (SW-56).",
        _CAPTURE_ID_INPUT,
        _PIN_RESULT,
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
