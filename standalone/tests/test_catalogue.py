"""The closed catalogue and its interface-0.1.0 vocabulary pin (gate F half)."""

from __future__ import annotations

import json

import pytest
from benchweave_sdk.served import vendored_root, verify_vendored_digests

from benchweave_standalone import catalogue
from benchweave_standalone.errors import ERROR_CODES, ERROR_HTTP_STATUS

SW10_NAMES = [
    "host_info", "device_discover", "device_connect", "device_disconnect",
    "device_get", "parameter_read", "parameter_stage", "parameter_apply",
    "preset_list", "preset_apply", "capture_start", "capture_stop",
    "capture_list", "capture_get", "capture_series", "capture_annotate",
    "artifact_read", "events_get",
]

SERVED = [
    "host_info", "device_discover", "device_connect", "device_disconnect",
    "device_get", "parameter_read",
]


def vendored_interface_catalog() -> dict:
    """The digest-verified vendored interface catalog (CON-4: one reader)."""
    verify_vendored_digests()
    path = vendored_root() / "interface" / "0.1.0" / "operation-catalog.json"
    return json.loads(path.read_bytes())


def test_catalogue_is_the_closed_sw10_set() -> None:
    assert [row.name for row in catalogue.CATALOGUE] == SW10_NAMES


def test_served_and_deferred_partition_the_catalogue() -> None:
    assert catalogue.served_operations() == tuple(SERVED)
    deferred = [name for name in SW10_NAMES if name not in SERVED]
    assert catalogue.deferred_operations() == tuple(deferred)
    assert len(catalogue.deferred_operations()) == 12


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
