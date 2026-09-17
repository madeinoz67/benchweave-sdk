"""Regression tests for descriptor semantic checks and validation errors."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from benchweave_sdk.validation import contract_documents, validate, validate_descriptor


def _reference_descriptor() -> dict[str, Any]:
    document = contract_documents()["otdp/0.1.0/examples/reference-psu.json"]
    return deepcopy(document)


def test_reference_descriptor_passes() -> None:
    validate_descriptor(_reference_descriptor())


def test_s02_rejects_reversed_bounds() -> None:
    descriptor = _reference_descriptor()
    for parameter in descriptor["parameters"]:
        if parameter.get("range"):
            parameter["range"] = list(reversed(parameter["range"]))
            break
    else:
        pytest.fail("reference descriptor carries no ranged parameter")
    with pytest.raises(ValueError, match="S02"):
        validate_descriptor(descriptor)


def test_s02_accepts_equal_bounds() -> None:
    descriptor = _reference_descriptor()
    for parameter in descriptor["parameters"]:
        if parameter.get("range"):
            parameter["range"] = [5, 5]
            break
    validate_descriptor(descriptor)


def test_unknown_schema_file_is_a_clear_error() -> None:
    with pytest.raises(ValueError, match="Unknown contract schema"):
        validate({}, "otdp/0.1.0/no-such-schema.json")


def test_schema_failure_is_a_domain_error() -> None:
    descriptor = _reference_descriptor()
    descriptor.pop("identity")
    with pytest.raises(ValueError, match="Contract validation failed"):
        validate_descriptor(descriptor)
