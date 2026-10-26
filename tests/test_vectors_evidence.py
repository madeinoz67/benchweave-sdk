# author: Stephen Eaton
"""Issue #566 row 11: the vectors.json evidence vocabulary (golden vectors).

The pure validator's contract. The anti-circularity property itself — bytes
on the wire that no builder can produce — is a property of the WORKFLOW, not
of the bytes: this validator refuses a hardware EVIDENCE CLAIM that travels
without recorded provenance. It cannot verify that a provenance record is
true; that honesty bound is stated in the guide and here on purpose.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchweave_sdk.vectors import validate_vectors_evidence

SOURCE = Path("vectors.json")


def _document(**overrides) -> dict:
    document: dict = {
        "evidence": "synthetic",
        "exchanges": [{"request": "ID?\n", "response": "demo\n"}],
    }
    document.update(overrides)
    return document


def test_absent_evidence_key_defaults_to_synthetic() -> None:
    document = _document()
    del document["evidence"]
    validate_vectors_evidence(document, source=SOURCE)  # no refusal


def test_synthetic_evidence_passes() -> None:
    validate_vectors_evidence(_document(), source=SOURCE)


def test_unknown_evidence_value_refuses_naming_the_vocabulary() -> None:
    with pytest.raises(ValueError, match="standalone_vectors_evidence_unknown:") as caught:
        validate_vectors_evidence(_document(evidence="capture"), source=SOURCE)
    assert "capture" in str(caught.value)
    assert "synthetic" in str(caught.value) and "hardware" in str(caught.value)


def test_hardware_claim_without_recorded_rows_refuses() -> None:
    with pytest.raises(ValueError, match="standalone_vectors_evidence_unrecorded:"):
        validate_vectors_evidence(_document(evidence="hardware"), source=SOURCE)


def test_hardware_claim_with_one_recorded_row_passes() -> None:
    document = _document(
        evidence="hardware",
        exchanges=[
            {"request": "ID?\n", "response": "demo\n"},
            {
                "request": "535441543f0a",
                "response": "53544154000a",
                "evidence": "hardware",
                "recorded": {"when": "2026-10-26T12:00:00+08:00", "transport": "usb"},
            },
        ],
    )
    validate_vectors_evidence(document, source=SOURCE)


def test_recorded_row_without_the_when_field_refuses_naming_the_row() -> None:
    document = _document(
        exchanges=[
            {
                "request": "535441543f0a",
                "response": "53544154000a",
                "evidence": "hardware",
                "recorded": {"transport": "usb"},
            }
        ]
    )
    with pytest.raises(ValueError, match="standalone_vectors_evidence_unrecorded:") as caught:
        validate_vectors_evidence(document, source=SOURCE)
    assert "when" in str(caught.value)


def test_row_hardware_claim_without_recorded_slot_refuses_naming_the_row() -> None:
    document = _document(
        exchanges=[
            {
                "name": "status-probe",
                "request": "535441543f0a",
                "response": "53544154000a",
                "evidence": "hardware",
            }
        ]
    )
    with pytest.raises(ValueError, match="standalone_vectors_evidence_unrecorded:") as caught:
        validate_vectors_evidence(document, source=SOURCE)
    assert "status-probe" in str(caught.value)


def test_unknown_row_evidence_value_refuses_naming_the_row() -> None:
    document = _document(
        exchanges=[
            {
                "name": "identify",
                "request": "ID?\n",
                "response": "demo\n",
                "evidence": "derived",
            }
        ]
    )
    with pytest.raises(ValueError, match="standalone_vectors_evidence_unknown:") as caught:
        validate_vectors_evidence(document, source=SOURCE)
    assert "identify" in str(caught.value)


def test_understated_file_label_with_a_recorded_row_is_not_a_refusal() -> None:
    """Understatement stays honest: a file labelled synthetic whose row
    carries properly-recorded hardware bytes claims LESS than it holds.
    Overstatement — synthetic rows under a hardware label — is the refusal
    above."""
    document = _document(
        exchanges=[
            {
                "request": "535441543f0a",
                "response": "53544154000a",
                "evidence": "hardware",
                "recorded": {"when": "2026-10-26T12:00:00+08:00"},
            }
        ]
    )
    validate_vectors_evidence(document, source=SOURCE)


def test_row_evidence_synthetic_needs_no_recorded_slot() -> None:
    document = _document(
        exchanges=[{"request": "ID?\n", "response": "demo\n", "evidence": "synthetic"}]
    )
    validate_vectors_evidence(document, source=SOURCE)
