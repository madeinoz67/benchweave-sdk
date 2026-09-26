"""Multi-version serving: per-pin validation, refusals, and derived constants.

Issue #203 slice 1 (design §3.2–3.3, acceptance A1–A3/A5): the vendored tree
carries every retained ∧ in-range OTDP version (yanked ones marked), every
schema lookup resolves ``<standard>/<pinned-version>/<file>`` from the
descriptor's own pin, and the pin classification refuses with the five VR-37
fields under stable prefixes — ``version_not_served:`` and
``retired_identifier:`` distinct from ``version_unknown:``.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

from benchweave_sdk.validation import validate, validate_descriptor, validate_request

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = json.loads((ROOT / "standards-lock.json").read_bytes())
ROWS = {
    (str(row["id"]), str(row["version"])): row for row in ACTIVE.get("standards", [])
}


def _carried_otdp() -> set[str]:
    return {version for (identifier, version) in ROWS if identifier == "otdp"}


def _descriptor(name: str) -> dict[str, object]:
    return json.loads(
        (ROOT / "src/benchweave_sdk/standards/otdp/0.2.2/examples" / name).read_bytes()
    )


def test_the_vendored_tree_carries_the_carried_otdp_set() -> None:
    """otdp rows: 0.2.0, 0.2.1 (yank-marked), 0.2.2 (active) — the served set
    (¬yanked) is derived from the markers plus the mirrored policy block."""
    assert _carried_otdp() >= {"0.2.0", "0.2.1", "0.2.2"}
    row_021 = ROWS[("otdp", "0.2.1")]
    assert row_021.get("yanked") is True
    assert ROWS[("otdp", "0.2.2")].get("active") is True
    assert ROWS[("otdp", "0.2.0")].get("active") is False


def test_explicit_path_validation_resolves_served_versions() -> None:
    """The A1 failure class: ``validate`` with an explicit ``otdp/0.2.0/...``
    key resolves (the ADC suite's lookup shape) — no unknown_contract_schema.
    The event envelope lives in the RUNTIME schema; a dataset in the
    measurement schema (both pinned per version)."""
    event = {
        "subscription_id": "sub-1",
        "sequence": 1,
        "kind": "telemetry",
        "reading": {
            "parameter": "voltage",
            "value": 3.3,
            "unit": "V",
            "observed_at": "2026-09-26T00:00:00Z",
            "age_ms": 0,
            "quality": "valid",
            "source": "device",
        },
    }
    validate(event, "otdp/0.2.0/otdp-runtime.schema.json", "event")
    validate(event, "otdp/0.2.2/otdp-runtime.schema.json", "event")
    # The descriptor keys of BOTH versions resolve and validate their own
    # pins (a 0.2.0-pinned copy against 0.2.0's bytes; the 0.2.2 example
    # against its own).
    pinned = _descriptor("class-dc_psu.json")
    pinned["otdp_version"] = "0.2.0"
    validate(pinned, "otdp/0.2.0/otdp-device-descriptor.schema.json")
    validate(_descriptor("class-dc_psu.json"), "otdp/0.2.2/otdp-device-descriptor.schema.json")


def test_descriptor_validates_against_the_pinned_not_active_schema() -> None:
    """A 0.2.0-pinned corpus descriptor (the ADC shape) validates unedited —
    the pin's own bytes, not the active schema's const."""
    descriptor = _descriptor("class-dc_psu.json")
    descriptor["otdp_version"] = "0.2.0"
    # The 0.2.0-era descriptor shape: strip keys 0.2.0's schema does not know
    # is NOT done — the corpus example validates against 0.2.0 only if its
    # body is 0.2.0-compatible; the reference descriptors carry provider-free
    # custom transports, which 0.2.0 admits. Pin flip alone is the test.
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # a served pin never warns
        validate_descriptor(descriptor)


def test_a2_provider_bearing_descriptor_per_pin(tmp_path: Path) -> None:
    """A2 (C2 corrected), four cells. Discriminating element named before
    building: ``transport.provider`` in ``$defs.customTransport`` — present
    in 0.2.1/0.2.2, absent in 0.2.0 with ``additionalProperties: false``.
    A provider-bearing descriptor whose pin correctly names its version is
    ACCEPTED pinned 0.2.2 and REFUSED pinned 0.2.0 (the 0.2.0 schema rejects
    the unknown key; the const cannot produce this — both documents' pins are
    self-consistent). KILL: any cell passing via the ACTIVE schema — the
    pin=0.2.0 arm must refuse even though active is 0.2.2."""
    provider_descriptor = _descriptor("reference-hid-meter.json")
    assert "provider" in provider_descriptor["transport"]  # type: ignore[operator]

    # Cell 1: pin 0.2.2 (as authored) — ACCEPTED.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        validate_descriptor(provider_descriptor)

    # Cell 2: pin flipped 0.2.0 — REFUSED by the 0.2.0 schema (provider key).
    pinned_020 = dict(provider_descriptor)
    pinned_020["otdp_version"] = "0.2.0"
    with pytest.raises(ValueError) as refusal:
        validate_descriptor(pinned_020)
    assert "provider" in str(refusal.value) or "additionalProperties" in str(refusal.value)

    # Reverse arm: pin flipped 0.2.1 <-> 0.2.2 — the SAME body validates
    # against its own pin's bytes both ways (the two schemas differ only in
    # version strings; this proves serving-by-pin, not serving-by-active).
    pinned_021 = dict(provider_descriptor)
    pinned_021["otdp_version"] = "0.2.1"
    with pytest.warns(Warning, match="0.2.2") as yank:
        validate_descriptor(pinned_021)
    assert any("0.2.1" in str(w.message) for w in yank), "the warning names the pin"
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        validate_descriptor(provider_descriptor)  # back on the served 0.2.2


def test_a3_retired_pin_refuses_with_vr37_fields() -> None:
    """A 0.3.0 pin (pre-reset OTDP) refuses ``retired_identifier:`` carrying
    all five VR-37 fields; the prefix is DISTINCT from
    ``version_unknown:`` (retired = used and dead; unknown = never carried)."""
    descriptor = _descriptor("class-dc_psu.json")
    descriptor["otdp_version"] = "0.3.0"
    with pytest.raises(ValueError) as refusal:
        validate_descriptor(descriptor)
    message = str(refusal.value)
    assert message.startswith("retired_identifier:") or "retired_identifier:" in message
    for field in ("otdp", "0.3.0", ">=0.2.0,<0.3.0", "0.2.2"):
        assert field in message, field
    assert "version_unknown:" not in message


def test_unserved_retained_pin_refuses_version_not_served() -> None:
    """0.1.2 is retained but out-of-range: ``version_not_served:`` with the
    five VR-37 fields (a different refusal from retired)."""
    descriptor = _descriptor("class-dc_psu.json")
    descriptor["otdp_version"] = "0.1.2"
    with pytest.raises(ValueError) as refusal:
        validate_descriptor(descriptor)
    message = str(refusal.value)
    assert "version_not_served:" in message
    for field in ("otdp", "0.1.2", ">=0.2.0,<0.3.0", "0.2.2"):
        assert field in message, field
    assert "retired_identifier:" not in message


def test_unknown_pin_refuses_version_not_served() -> None:
    descriptor = _descriptor("class-dc_psu.json")
    descriptor["otdp_version"] = "9.9.9"
    with pytest.raises(ValueError, match="version_not_served:"):
        validate_descriptor(descriptor)


def test_yanked_pin_validates_with_a_warning_naming_the_move_to() -> None:
    """Q10: an explicit 0.2.1 pin stays conforming with a deprecation warning
    naming 0.2.2 (the derived move-to: highest served version >= pin)."""
    descriptor = _descriptor("class-dc_psu.json")
    descriptor["otdp_version"] = "0.2.1"
    with pytest.warns(Warning, match="0.2.1") as recorded:
        validate_descriptor(descriptor)
    assert any("0.2.2" in str(w.message) for w in recorded), "the move-to is named"


def test_constants_derive_from_the_lock() -> None:
    """The five validation.py literals and two __init__ constants retire as a
    CONSEQUENCE of derivation: OTDP_VERSION reads the lock's active row, and
    ADAPTER_API_VERSION reads the active descriptor schema's const."""
    from benchweave_sdk import ADAPTER_API_VERSION, OTDP_VERSION

    active_row = ROWS[("otdp", OTDP_VERSION)]
    assert active_row.get("active") is True
    schema = validate.__globals__["contract_documents"]()[  # noqa: SLF001
        f"otdp/{OTDP_VERSION}/otdp-device-descriptor.schema.json"
    ]
    assert schema["$defs"]["adapter"]["properties"]["api_version"]["const"] == ADAPTER_API_VERSION


def test_served_documents_are_digest_checked_against_the_lock() -> None:
    """PKG-1/VR-32: per-pin validation loads the vendored served set and
    verifies each file's digest against the SDK lock row — a tampered vendored
    file refuses by name, never silently validates."""
    from benchweave_sdk.served import verify_vendored_digests

    verify_vendored_digests()  # clean tree passes

    victim = (
        ROOT
        / "src/benchweave_sdk/standards/otdp/0.2.0/otdp-device-descriptor.schema.json"
    )
    original = victim.read_bytes()
    try:
        victim.write_bytes(original + b"\n")
        with pytest.raises(ValueError, match="vendored_digest_mismatch"):
            verify_vendored_digests()
    finally:
        victim.write_bytes(original)


# --- #215 fix wave: the load path itself is digest-checked; pins never crash. ---


def _clear_document_caches() -> None:
    """Drop every cached view of the vendored tree so a planted byte is read.

    ``contract_documents`` is load-once; without this, whichever test ran
    first would pin the clean bytes for the whole session and the plant
    below could never be observed on the load path.
    """
    import benchweave_sdk.validation as validation_module

    validation_module.contract_documents.cache_clear()
    validation_module._registry.cache_clear()
    validation_module._corpus_known_otdp_features.cache_clear()


def test_planted_vendored_byte_refuses_per_pin_validation() -> None:
    """F1 (design §3.2; §7 risk-1's falsifier): per-pin validation loads the
    vendored served set DIGEST-CHECKED against the SDK lock row. A planted
    byte in a served schema refuses by name (``vendored_digest_mismatch:``)
    instead of silently becoming the schema a descriptor validates against.

    The planted byte is a trailing newline: invisible to the JSON parse, so
    only the digest can see it — exactly the tamper the design's risk
    falsifier names (wrong bytes refuse with a digest prefix, never warn).
    """
    victim = (
        ROOT / "src/benchweave_sdk/standards/otdp/0.2.0/otdp-device-descriptor.schema.json"
    )
    original = victim.read_bytes()
    descriptor = _descriptor("class-dc_psu.json")
    descriptor["otdp_version"] = "0.2.0"
    try:
        _clear_document_caches()
        victim.write_bytes(original + b"\n")
        with pytest.raises(ValueError, match="^vendored_digest_mismatch: ") as refusal:
            validate_descriptor(descriptor)
        assert "otdp/0.2.0/otdp-device-descriptor.schema.json" in str(refusal.value)
    finally:
        victim.write_bytes(original)
        _clear_document_caches()


@pytest.mark.parametrize("pin", ["0.3.0-dev", "abc", "1.x"])
def test_malformed_pins_classify_to_a_typed_refusal(pin: str) -> None:
    """F2: no classification path raises a bare parse error. An unparsable
    pin is an unserved pin — ``version_not_served:`` with the five VR-37
    fields, move-to the highest served version (the best available ordering
    for a string that cannot be ordered) and a detail that names the parse
    failure instead of laundering it."""
    from benchweave_sdk.served import classify_pin, refusal_for

    classification = classify_pin(pin, "otdp")
    assert classification.state == "unserved"
    assert classification.standard == "otdp"
    assert classification.pin == pin
    assert classification.supported_range == ">=0.2.0,<0.3.0"
    assert classification.move_to == "0.2.2"
    assert "not a parseable" in classification.detail
    message = str(refusal_for(classification))
    assert message.startswith("version_not_served:")
    for field in ("otdp", pin, ">=0.2.0,<0.3.0", "0.2.2"):
        assert field in message, field


def test_dev_shaped_descriptor_pin_refuses_typed_not_a_traceback() -> None:
    """F2 end to end: ``_resolve_otdp_pin`` runs before schema validation, so
    a dev-shaped ``otdp_version`` must surface the typed refusal, never a raw
    ``ValueError: invalid literal for int()`` out of version ordering."""
    descriptor = _descriptor("class-dc_psu.json")
    descriptor["otdp_version"] = "0.3.0-dev"
    with pytest.raises(ValueError, match="^version_not_served: ") as refusal:
        validate_descriptor(descriptor)
    assert "0.3.0-dev" in str(refusal.value)


def test_parseable_but_unserved_pins_keep_the_range_detail() -> None:
    """F2 guard: the parse-naming detail belongs to unparsable pins only — a
    pin that parses but is not carried keeps the range detail, so the
    schema's own const errors stay reachable for pins that resolve."""
    from benchweave_sdk.served import classify_pin

    classification = classify_pin("0.1.2", "otdp")
    assert classification.state == "unserved"
    assert "not a parseable" not in classification.detail
    assert "out of the declared range" in classification.detail


# --- #215 fold rows 1 and 25: semver move-to; the yank warning everywhere. ---


def test_move_to_orders_by_semver_not_lexical_sort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fold row 1: the derived move-to is the highest served version by
    SEMVER. Lexical ordering lost 0.10.0 to 0.2.0 ("0.10.0" < "0.2.0" as a
    string), steering a below-both pin to the older version."""
    import benchweave_sdk.served as served

    lock = json.loads((ROOT / "standards-lock.json").read_bytes())
    for row in lock["standards"]:
        if row["id"] == "otdp":
            row["version"] = "0.10.0" if row["version"] == "0.2.2" else row["version"]
            # 0.2.2's row becomes a 0.10.0 row (same bytes, re-versioned key);
            # 0.2.1 stays the yanked row so the served set is {0.2.0, 0.10.0}.
    monkeypatch.setattr(served, "_lock_document", lambda: lock)
    served.lock_rows.cache_clear()
    try:
        classification = served.classify_pin("0.1.2", "otdp")
        assert classification.move_to == "0.10.0"
    finally:
        served.lock_rows.cache_clear()


def test_yank_warning_fires_on_the_envelope_paths() -> None:
    """Fold row 25: the yank deprecation warning is a property of validating
    against a yanked version's bytes — it fires on the envelope entry points
    (``validate_request``/``validate_result``), not only on
    ``validate_descriptor``."""
    request = {"operation_id": "op-1", "verb": "identify", "arguments": {}}
    with pytest.warns(Warning, match="0.2.1") as recorded:
        validate_request(request, otdp_version="0.2.1")
    assert any("0.2.2" in str(w.message) for w in recorded), "the move-to is named"


def test_yank_warning_fires_on_the_explicit_key_path() -> None:
    """Fold row 25, explicit-key arm: ``validate`` against a yanked version's
    schema file warns too — the warning travels with the bytes, whichever
    entry point resolved them."""
    event = {
        "subscription_id": "sub-1",
        "sequence": 1,
        "kind": "telemetry",
        "reading": {
            "parameter": "voltage",
            "value": 3.3,
            "unit": "V",
            "observed_at": "2026-09-26T00:00:00Z",
            "age_ms": 0,
            "quality": "valid",
            "source": "device",
        },
    }
    with pytest.warns(Warning, match="0.2.1"):
        validate(event, "otdp/0.2.1/otdp-runtime.schema.json", "event")


def test_served_version_paths_never_warn() -> None:
    """Fold row 25 control: the warning is the yank's, not validation noise —
    a served (¬yanked) pin validates silently on every path."""
    request = {"operation_id": "op-1", "verb": "identify", "arguments": {}}
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        validate_request(request, otdp_version="0.2.0")
        validate_request(request)  # the derived active version
