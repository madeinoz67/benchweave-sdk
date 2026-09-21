"""Regression tests for descriptor semantic checks and validation errors."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from benchweave_sdk.validation import contract_documents, validate, validate_descriptor


def _otdp_key(suffix: str) -> str:
    """The vendored OTDP document ending in ``suffix``, whatever version main vendors."""
    matches = [
        key for key in contract_documents() if key.startswith("otdp/") and key.endswith(suffix)
    ]
    assert len(matches) == 1, matches
    return matches[0]


def _reference_descriptor() -> dict[str, Any]:
    document = contract_documents()[_otdp_key("/examples/reference-psu.json")]
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
    # snake_case prefix: machine-matchable like its sibling refusals.
    with pytest.raises(ValueError, match="unknown_contract_schema"):
        validate({}, "otdp/no-such-version/no-such-schema.json")


def test_schema_failure_is_a_domain_error() -> None:
    descriptor = _reference_descriptor()
    descriptor.pop("identity")
    with pytest.raises(ValueError, match="Contract validation failed"):
        validate_descriptor(descriptor)


def test_deep_document_is_a_domain_error_not_a_recursion_crash() -> None:
    # A document nested past the interpreter's recursion limit used to escape
    # as a bare RecursionError; it is a document failure and must wrap.
    document: Any = "leaf"
    for _ in range(20000):
        document = [document]
    with pytest.raises(ValueError, match="Contract validation failed"):
        validate(document, _otdp_key("/otdp-runtime.schema.json"))


def test_definition_against_idless_schema_is_a_domain_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A bundled schema without '$id' cannot anchor a $defs reference; the
    # KeyError this produced was a crash, not the documented ValueError.
    from benchweave_sdk import validation

    fake = {
        "fake/no-id.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {"thing": {"type": "object"}},
        }
    }
    monkeypatch.setattr(validation, "contract_documents", lambda: fake)
    with pytest.raises(ValueError, match="definitions cannot be addressed"):
        validation.validate({}, "fake/no-id.schema.json", "thing")
