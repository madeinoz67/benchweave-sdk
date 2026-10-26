# author: Stephen Eaton
"""Issue #567 row 13: read receipts are a contract, not a convention.

The vendored runtime schema already defines the ``reading`` shape
(required keys, typed value, quality and source vocabularies); the
descriptor's parameter row adds the typed contract (float/int/bool/enum/
string, unit, range, enum_values). A receipt that satisfies neither used
to reach the readings page and render ``None`` with no gate firing. The
validator refuses it by name instead. ``value: null`` stays legal — the
schema declares it for ``quality: "invalid"``/``"stale"`` readings; the
typed contract applies to non-null values.
"""

from __future__ import annotations

import pytest

from benchweave_sdk.validation import validate_read_receipt


def _receipt(**overrides) -> dict:
    receipt = {
        "parameter": "voltage",
        "value": 3.3,
        "unit": "V",
        "observed_at": "2026-10-26T00:00:00Z",
        "age_ms": 0,
        "quality": "valid",
        "source": "device",
    }
    receipt.update(overrides)
    return receipt


def _contract(**overrides) -> dict:
    row = {"name": "voltage", "type": "float", "access": "ro", "unit": "V"}
    row.update(overrides)
    return row


def test_standard_receipt_passes() -> None:
    validate_read_receipt(_receipt(), _contract(), parameter="voltage")


def test_missing_value_key_refuses_naming_the_parameter() -> None:
    broken = _receipt()
    del broken["value"]
    with pytest.raises(ValueError, match="read_receipt_invalid:") as caught:
        validate_read_receipt(broken, _contract(), parameter="voltage")
    assert "voltage" in str(caught.value)


def test_list_value_refuses() -> None:
    with pytest.raises(ValueError, match="read_receipt_invalid:"):
        validate_read_receipt(_receipt(value=[1]), _contract(), parameter="voltage")


def test_type_mismatch_refuses() -> None:
    with pytest.raises(ValueError, match="read_receipt_invalid:"):
        validate_read_receipt(_receipt(value="3.3"), _contract(), parameter="voltage")


def test_unit_mismatch_refuses() -> None:
    with pytest.raises(ValueError, match="read_receipt_invalid:"):
        validate_read_receipt(_receipt(unit="mV"), _contract(), parameter="voltage")


def test_range_violation_refuses() -> None:
    contract = _contract(range=[0.0, 5.0])
    with pytest.raises(ValueError, match="read_receipt_invalid:"):
        validate_read_receipt(_receipt(value=9.0), contract, parameter="voltage")


def test_enum_value_outside_the_set_refuses() -> None:
    contract = _contract(type="enum", enum_values=["on", "off"], unit=None)
    with pytest.raises(ValueError, match="read_receipt_invalid:"):
        validate_read_receipt(
            _receipt(value="maybe", unit=None), contract, parameter="voltage"
        )


def test_int_contract_refuses_a_fraction() -> None:
    contract = _contract(type="int")
    with pytest.raises(ValueError, match="read_receipt_invalid:"):
        validate_read_receipt(_receipt(value=3.5), contract, parameter="voltage")


def test_null_value_with_invalid_quality_passes() -> None:
    """The schema's declared no-reading shape: value may be null when the
    quality says so. Refusing it would break every honest degraded read."""
    validate_read_receipt(
        _receipt(value=None, quality="invalid"), _contract(), parameter="voltage"
    )


def test_envelope_shape_is_the_schema_reading_def() -> None:
    """A receipt missing a required envelope key refuses: the required
    list the vendored reading shape declares, re-checked at the gate (the
    closed quality/source enums stay out — see the validator docstring)."""
    broken = _receipt()
    del broken["quality"]
    with pytest.raises(ValueError, match="read_receipt_invalid:"):
        validate_read_receipt(broken, _contract(), parameter="voltage")
