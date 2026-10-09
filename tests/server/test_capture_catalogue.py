"""I3b slice 1: the catalogue flip — the seven capture rows serve, three new
rows land (the design record's fork F-2, catalogue rows 19-21), and the MCP
registration + schema pinning extend to all of them (gate F's readback).

The row set: SW-10's closed 18, plus ``capture_delete``/``capture_pin``/
``capture_unpin`` — a disclosed PRD delta (SW-56/SW-59 name the capabilities,
SW-10's list omits them).
"""

from __future__ import annotations

import asyncio

from jsonschema import Draft202012Validator

from benchweave_sdk_server import catalogue
from benchweave_sdk_server.mcp import (
    build_mcp,
    operation_tool_schema,
    registered_tool_names,
    tool_name,
)
from benchweave_sdk_server.seam import StandaloneSeam

#: The seven rows the flip serves (six capture operations plus the artifact
#: window read), and the three NEW rows beyond SW-10's closed 18.
FLIPPED = [
    "capture_start", "capture_stop", "capture_list", "capture_get",
    "capture_series", "capture_annotate", "artifact_read",
]
NEW_ROWS = ["capture_delete", "capture_pin", "capture_unpin"]
#: I4a's disclosed delta (adopted fork F-C): row 22.
REPORT_ROWS = ["report_export"]
#: I4b.1's disclosed delta (F-C's adopted posture): row 23.
ANALYSIS_ROWS = ["capture_analysis"]


def call(seam: StandaloneSeam, operation: str, arguments: dict | None = None) -> dict:
    return asyncio.run(seam.call(operation, arguments or {}))


def validate(instance: object, schema: dict) -> list[str]:
    return sorted(
        error.message
        for error in Draft202012Validator(schema).iter_errors(instance)
    )


def test_capture_rows_are_served() -> None:
    for name in FLIPPED + NEW_ROWS + REPORT_ROWS + ANALYSIS_ROWS:
        row = catalogue.spec(name)
        assert row is not None, name
        assert row.implemented, name
        assert row.input_schema and row.result_schema, name
        assert row.error_codes, name


def test_new_rows_sit_after_sw10s_closed_18() -> None:
    """Fork F-2's disclosure: rows 19-21 follow SW-10's closed 18; I4a's
    report_export (adopted fork F-C) is row 22; I4b.1's capture_analysis
    (F-C's adopted posture) is row 23."""
    names = [row.name for row in catalogue.CATALOGUE]
    assert names[18:] == NEW_ROWS + REPORT_ROWS + ANALYSIS_ROWS
    assert len(names) == 23


def test_capture_start_requires_exactly_one_bound() -> None:
    """SW-33: the bound is required, exactly one of count / duration_s."""
    schema = catalogue.spec("capture_start").input_schema
    good = {"device_id": "d"}
    assert validate({**good, "count": 5}, schema) == []
    assert validate({**good, "duration_s": 0.5}, schema) == []
    both = validate({**good, "count": 5, "duration_s": 0.5}, schema)
    assert both, "count and duration_s together must be refused"
    neither = validate(good, schema)
    assert neither, "a capture without a bound must be refused"


def test_capture_start_bound_ceilings() -> None:
    """SW-33: bounds carry ceilings. count 10M samples is the record's own
    10-minute class at 8 B/sample against the fork's 250 KiB/s line rate
    (about 5.3 minutes); duration_s 600 s is the same class directly."""
    schema = catalogue.spec("capture_start").input_schema
    props = schema["properties"]
    assert props["count"]["maximum"] == 10_000_000
    assert props["duration_s"]["maximum"] == 600
    assert validate({"device_id": "d", "count": 10_000_001}, schema)
    assert validate({"device_id": "d", "duration_s": 600.5}, schema)
    assert validate({"device_id": "d", "count": 10_000_000}, schema) == []
    assert validate({"device_id": "d", "duration_s": 600}, schema) == []


def test_capture_start_waveform_needs_the_sample_grid() -> None:
    """A waveform_f64le capture declares the operator-commissioned sample
    grid (interval + unit): the writer's corpus allOf requires them at
    finalise, so the start refusal precedes any staging."""
    schema = catalogue.spec("capture_start").input_schema
    base = {"device_id": "d", "count": 4}
    assert validate({**base, "format": "waveform_f64le"}, schema)
    assert (
        validate(
            {
                **base,
                "format": "waveform_f64le",
                "sample_interval_s": 0.001,
                "unit": "V",
            },
            schema,
        )
        == []
    )
    assert validate({**base, "format": "raw_binary"}, schema) == []


def test_capture_start_rejects_unknown_fields() -> None:
    schema = catalogue.spec("capture_start").input_schema
    assert validate(
        {"device_id": "d", "count": 1, "surface": "mcp"}, schema
    ), "the originating surface is host knowledge, never a client argument"


def test_capture_stop_get_series_annotate_pin_unpin_delete_inputs() -> None:
    stop = catalogue.spec("capture_stop").input_schema
    assert validate({"capture_id": "cap-x"}, stop) == []
    assert validate({}, stop)
    for name in ("capture_get", "capture_series", "capture_annotate",
                 "capture_delete", "capture_pin", "capture_unpin",
                 "artifact_read"):
        row = catalogue.spec(name)
        assert row is not None
        assert "capture_id" in row.input_schema.get("properties", {}), name


def test_capture_series_decimation_defaults() -> None:
    """SW-33: decimate by default (max_points 2000), 0 serves raw points."""
    schema = catalogue.spec("capture_series").input_schema
    assert validate({"capture_id": "cap-x"}, schema) == []
    assert validate({"capture_id": "cap-x", "max_points": 0}, schema) == []
    assert validate({"capture_id": "cap-x", "max_points": 2000}, schema) == []
    assert validate({"capture_id": "cap-x", "max_points": -1}, schema)


def test_capture_list_is_empty_input() -> None:
    assert validate({}, catalogue.spec("capture_list").input_schema) == []


def test_mcp_serves_the_full_tool_set(seam) -> None:
    """Gate F's readback: every implemented row is a registered tool whose
    pinned schemas are the catalogue's verbatim."""
    mcp = build_mcp(seam)
    expected = sorted(tool_name(name) for name in catalogue.served_operations())
    assert registered_tool_names(mcp) == expected
    for row in catalogue.CATALOGUE:
        if not row.implemented:
            continue
        served = operation_tool_schema(mcp, tool_name(row.name))
        assert served is not None
        assert served.input_schema == row.input_schema, row.name
        assert served.result_schema == row.result_schema, row.name


def test_mcp_handlers_cover_the_new_rows(seam) -> None:
    build_mcp(seam)  # the drift check raises on any missing handler
    for name in NEW_ROWS + FLIPPED:
        assert name in catalogue.served_operations()


def test_host_info_served_set_carries_the_flip(seam) -> None:
    info = call(seam, "host_info")
    assert set(FLIPPED + NEW_ROWS) <= set(info["served_operations"])
    assert info["deferred_operations"] == []


def test_deferred_set_is_now_empty(seam) -> None:
    call(seam, "host_info")
    assert catalogue.deferred_operations() == ()
