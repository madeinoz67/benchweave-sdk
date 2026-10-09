"""The closed catalogue and its interface-0.1.0 vocabulary pin (gate F half)."""

from __future__ import annotations

import json

import pytest

from benchweave_sdk.served import vendored_root, verify_vendored_digests
from benchweave_sdk_server import catalogue
from benchweave_sdk_server.errors import ERROR_CODES, ERROR_HTTP_STATUS

#: SW-10's closed 18 (in catalogue order) PLUS fork F-2's disclosed delta —
#: rows 19-21 (capture_delete/capture_pin/capture_unpin after events_get;
#: SW-56/SW-59 name the capabilities, SW-10's list omits them — the owner
#: fork is recorded in the I3b design record §7) — I4a's row 22
#: (report_export, the adopted fork F-C: SW-53/SW-56 name the capability),
#: and I4b.1's row 23 (capture_analysis, F-C's adopted posture again:
#: SW-50 names the capability, the closed list omits it).
SW10_NAMES = [
    "host_info", "device_discover", "device_connect", "device_disconnect",
    "device_get", "parameter_read", "parameter_stage", "parameter_apply",
    "preset_list", "preset_apply", "capture_start", "capture_stop",
    "capture_list", "capture_get", "capture_series", "capture_annotate",
    "artifact_read", "events_get",
    "capture_delete", "capture_pin", "capture_unpin",
    "report_export",
    "capture_analysis",
]

#: I3b's flip: every row is implemented — the capture family serves and
#: nothing defers (the pre-I3b set kept the capture rows and artifact_read
#: deferred; the lifecycle is the I3b slices).
SERVED = SW10_NAMES


def vendored_interface_catalog() -> dict:
    """The digest-verified vendored interface catalog (CON-4: one reader)."""
    verify_vendored_digests()
    path = vendored_root() / "interface" / "0.1.0" / "operation-catalog.json"
    return json.loads(path.read_bytes())


def test_catalogue_is_the_closed_sw10_set() -> None:
    assert [row.name for row in catalogue.CATALOGUE] == SW10_NAMES


def test_served_and_deferred_partition_the_catalogue() -> None:
    assert catalogue.served_operations() == tuple(SERVED)
    # I3b's flip: nothing defers — the closed set serves whole, and the
    # deferred partition is empty (the pre-I3b pin carried 7 rows).
    assert catalogue.deferred_operations() == ()


def test_implemented_rows_carry_schemas_and_the_closed_code_set() -> None:
    for row in catalogue.CATALOGUE:
        if row.implemented:
            assert row.input_schema and row.result_schema
            assert row.error_codes == ERROR_CODES
        else:
            assert row.error_codes == frozenset()


def test_error_codes_are_the_interface_subset_the_prd_names() -> None:
    """SW-11: the seven PRD-named codes, pinned against the vendored file."""
    vendored = vendored_interface_catalog()
    interface_codes = set(vendored["error_http_status"])
    assert interface_codes >= ERROR_CODES
    assert {
        "invalid_request", "not_found", "conflict", "not_ready",
        "payload_too_large", "unavailable", "internal_error",
    } == ERROR_CODES
    # Structurally absent: no policy/lease/credential codes can be emitted.
    for absent in ("policy_denied", "forbidden", "unauthenticated",
                   "gone", "rate_limited"):
        assert absent not in ERROR_CODES


def test_http_status_map_equals_the_vendored_rows() -> None:
    vendored = vendored_interface_catalog()["error_http_status"]
    assert {code: vendored[code] for code in ERROR_CODES} == ERROR_HTTP_STATUS


def test_absent_guarantees_are_the_five_disclosed() -> None:
    assert catalogue.ABSENT_GUARANTEES == (
        "leases", "policy", "approvals", "procedures", "runs",
    )


def test_unknown_name_has_no_row() -> None:
    assert catalogue.spec("lease_create") is None


def test_device_summary_carries_the_endpoint_fields() -> None:
    """Issue #385 §1.2's wire-visible widening: every ``device_discover``
    row names its physical endpoint — ``port_path`` always a string,
    ``usb_serial`` string-or-null (the CH3433G-class no-iSerial case),
    both REQUIRED so a consumer never guesses whether the field was
    forgotten. REST and MCP pin from this one schema (the parity gate's
    single authority)."""
    items = catalogue.spec("device_discover").result_schema["properties"][
        "devices"
    ]["items"]
    assert items["required"] == [
        "id", "manufacturer", "model", "transport", "connection_key",
        "port_path", "usb_serial",
    ]
    assert items["properties"]["port_path"] == {"type": ["string", "null"]}
    assert items["properties"]["usb_serial"] == {"type": ["string", "null"]}
    assert items["additionalProperties"] is False


def test_spec_returns_rows_for_every_name() -> None:
    for name in SW10_NAMES:
        row = catalogue.spec(name)
        assert row is not None and row.name == name


def test_vendored_catalog_is_the_gateways_not_ours() -> None:
    """The authority check's own sanity: the vendored interface catalog is the
    gateway's 20-operation catalogue. Exactly three SW-10 names coincide with
    it (the interface-0.1.0-shaped ones); the standalone surface is its own
    closed set, pinned here, never copied from the gateway's."""
    vendored = vendored_interface_catalog()
    vendored_names = {op["name"] for op in vendored["operations"]}
    assert "lease_create" in vendored_names
    assert set(SW10_NAMES) & vendored_names == {
        "device_get", "artifact_read", "events_get",
    }


@pytest.mark.parametrize("name", SW10_NAMES)
def test_every_row_is_well_formed(name: str) -> None:
    row = catalogue.spec(name)
    assert row is not None
    assert row.description
