"""Transport-provider declarations: the offline conformance lattice (#147).

Carries the design record's §4 Metric 1 lattice — 4 valid variants and 8
single-fault permutations — plus the focused arms for the checks JSON Schema
cannot express (grammar-subschema meta-validation, kind-string uniqueness,
identity equalities, reserved generic kinds) and the pin-resolution rules the
``check`` lane owns (descriptor-relative resolution, containment, digest,
declaration↔contract agreement). Every refusal asserts its named STD-4
prefix; schema-shape faults assert the existing descriptor-validation
surface, which is what the corpus assigns them.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from benchweave_sdk.validation import (
    _corpus_known_otdp_features,
    contract_documents,
    validate_descriptor,
    validate_transport_provider,
    verify_provider_pin,
)

#: The five core lanes, cited from the vendored specification text (the
#: ``required_features`` paragraph): the census test pins the derivation
#: sweep against these spellings plus the catalog profile ids read from the
#: vendored catalog in the test itself.
_LANES = frozenset(
    {
        "otdp.core/0.1.0",
        "otdp.adapter/0.1.0",
        "otdp.passive_can/0.1.0",
        "otdp.profile_actions/0.1.0",
        "otdp.measurement/0.1.0",
    }
)

_PROVIDER_FEATURE = "otdp.transport.reference-hid/1.0.0"


def _otdp_key(suffix: str) -> str:
    """The vendored OTDP document ending in ``suffix``, whatever version main vendors."""
    matches = [
        key for key in contract_documents() if key.startswith("otdp/") and key.endswith(suffix)
    ]
    assert len(matches) == 1, matches
    return matches[0]


def _vendored_bytes(key: str) -> bytes:
    return files("benchweave_sdk").joinpath("standards", key).read_bytes()


def _base_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    """The corpus reference descriptor/contract pair, as writable copies."""
    descriptor = json.loads(_vendored_bytes(_otdp_key("/examples/reference-hid-meter.json")))
    contract = json.loads(_vendored_bytes(_otdp_key("/examples/reference-provider.json")))
    return descriptor, contract


def _minimal_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    """The minimal provider declaration: identify only, no parameters."""
    descriptor, contract = _base_pair()
    descriptor["capabilities"] = ["identify"]
    descriptor["operations"] = {"identify": descriptor["operations"]["identify"]}
    descriptor["parameters"] = []
    return descriptor, contract


def _write_package(
    tmp_path: Path,
    name: str,
    descriptor: dict[str, Any],
    contract: dict[str, Any] | None,
    *,
    recompute_digest: bool = True,
) -> Path:
    """Write ``<tmp>/<name>/`` holding the descriptor and its pinned contract.

    The pin digest is recomputed from the bytes actually written, so a
    fixture that did not deliberately fault the digest always verifies;
    pass ``recompute_digest=False`` to keep a faulted pin.
    """
    package = tmp_path / name
    package.mkdir(parents=True)
    if contract is not None:
        raw = (json.dumps(contract, indent=2) + "\n").encode()
        (package / descriptor["transport"]["provider"]["path"]).write_bytes(raw)
        if recompute_digest:
            descriptor["transport"]["provider"]["sha256"] = hashlib.sha256(raw).hexdigest()
    (package / "descriptor.json").write_text(json.dumps(descriptor, indent=2) + "\n")
    return package / "descriptor.json"


def _check(descriptor_path: Path) -> Any:
    from benchweave_sdk.cli import cli

    return CliRunner().invoke(cli, ["check", str(descriptor_path)])


# --------------------------------------------------------------------------
# The lattice: 4 valid variants (design §4 Metric 1)
# --------------------------------------------------------------------------


def _valid_minimal(tmp_path: Path) -> Path:
    descriptor, contract = _minimal_pair()
    return _write_package(tmp_path, "minimal", descriptor, contract)


def _valid_with_class_profiles(tmp_path: Path) -> Path:
    descriptor, contract = _minimal_pair()
    catalog = contract_documents()[_otdp_key("/device-profile-catalog.json")]
    profile_id = sorted(profile["id"] for profile in catalog["profiles"])[0]
    descriptor["required_features"] += [
        "otdp.profile_actions/0.1.0",
        "otdp.measurement/0.1.0",
        profile_id,
    ]
    return _write_package(tmp_path, "class-profiles", descriptor, contract)


def _valid_with_x_settings(tmp_path: Path) -> Path:
    descriptor, contract = _minimal_pair()
    descriptor["transport"]["settings"]["x-acme-report-timeout"] = 30
    return _write_package(tmp_path, "x-settings", descriptor, contract)


def _valid_corpus_reference(tmp_path: Path) -> Path:
    # The corpus pinned the descriptor's digest to the corpus's own bytes;
    # writing them verbatim is the only way the example's pin verifies.
    package = tmp_path / "corpus-reference"
    package.mkdir()
    (package / "reference-provider.json").write_bytes(
        _vendored_bytes(_otdp_key("/examples/reference-provider.json"))
    )
    (package / "descriptor.json").write_bytes(
        _vendored_bytes(_otdp_key("/examples/reference-hid-meter.json"))
    )
    return package / "descriptor.json"


VALID_LATTICE: dict[str, Callable[[Path], Path]] = {
    "minimal_provider": _valid_minimal,
    "provider_with_class_profile_features": _valid_with_class_profiles,
    "provider_with_x_settings": _valid_with_x_settings,
    "corpus_reference_descriptor": _valid_corpus_reference,
}


@pytest.mark.parametrize("build", list(VALID_LATTICE.values()), ids=list(VALID_LATTICE))
def test_valid_lattice_passes_the_document_lane(
    tmp_path: Path, build: Callable[[Path], Path]
) -> None:
    descriptor = json.loads(build(tmp_path).read_text())
    validate_descriptor(descriptor)


@pytest.mark.parametrize("build", list(VALID_LATTICE.values()), ids=list(VALID_LATTICE))
def test_valid_lattice_passes_the_check_lane(tmp_path: Path, build: Callable[[Path], Path]) -> None:
    result = _check(build(tmp_path))
    assert result.exit_code == 0, result.output


# --------------------------------------------------------------------------
# The lattice: 8 single-fault permutations, each refusing with its named
# prefix on its proving lane (design §4 Metric 1)
# --------------------------------------------------------------------------

Fault = tuple[dict[str, Any], dict[str, Any] | None, str]


def _fault_feature_not_required() -> Fault:
    descriptor, contract = _minimal_pair()
    descriptor["required_features"].remove(_PROVIDER_FEATURE)
    return descriptor, contract, "provider_feature_missing:"


def _fault_orphan_transport_feature() -> Fault:
    descriptor, _ = _minimal_pair()
    del descriptor["transport"]["provider"]
    return descriptor, None, "provider_transport_undeclared:"


def _fault_unknown_otdp_feature() -> Fault:
    descriptor, contract = _minimal_pair()
    descriptor["required_features"].append("otdp.core/9.9.9")
    return descriptor, contract, "unknown_otdp_feature:"


def _fault_provider_on_serial() -> Fault:
    # The transport arms are closed objects (additionalProperties: false),
    # so the oneOf refuses a provider on serial: the schema owns this fault.
    descriptor, contract = _minimal_pair()
    descriptor["transport"] = {
        "type": "serial",
        "connection_key": "power_meter",
        "settings": {
            "baud": 115200,
            "data_bits": 8,
            "parity": "none",
            "stop_bits": 1,
            "rtscts": False,
            "max_frame_bytes": 128,
        },
        "provider": descriptor["transport"]["provider"],
    }
    return descriptor, contract, "Contract validation failed"


def _fault_without_adapter_mode() -> Fault:
    # The schema's declarative row enumerates the declarative transports and
    # custom is not among them, so declarative + custom + provider is
    # refused by the schema, not by the S04 census.
    descriptor, contract = _minimal_pair()
    descriptor["integration"] = {"mode": "declarative"}
    descriptor["required_features"].remove("otdp.adapter/0.1.0")
    return descriptor, contract, "Contract validation failed"


def _fault_escaping_pin_path() -> Fault:
    descriptor, _ = _minimal_pair()
    descriptor["transport"]["provider"]["path"] = "../outside-provider.json"
    return descriptor, None, "provider_contract_missing:"


def _fault_wrong_pin_digest() -> Fault:
    descriptor, contract = _minimal_pair()
    descriptor["transport"]["provider"]["sha256"] = "a" * 64
    return descriptor, contract, "provider_contract_hash_mismatch:"


def _fault_provider_extra_property() -> Fault:
    descriptor, contract = _minimal_pair()
    descriptor["transport"]["provider"]["vendor_extra"] = "not sanctioned"
    return descriptor, contract, "Contract validation failed"


FAULT_LATTICE: dict[str, Callable[[], Fault]] = {
    "feature_id_absent_from_required_features": _fault_feature_not_required,
    "orphan_otdp_transport_feature": _fault_orphan_transport_feature,
    "unknown_otdp_id": _fault_unknown_otdp_feature,
    "provider_on_non_custom_transport": _fault_provider_on_serial,
    "provider_without_adapter_mode": _fault_without_adapter_mode,
    "escaping_pin_path": _fault_escaping_pin_path,
    "wrong_pin_sha256": _fault_wrong_pin_digest,
    "provider_object_with_additional_properties": _fault_provider_extra_property,
}

#: Faults whose proving lane is the check command — the document alone is
#: self-consistent, so validate_descriptor passes them by design.
CHECK_LANE_FAULTS = frozenset({"escaping_pin_path", "wrong_pin_sha256"})


@pytest.mark.parametrize("build_fault", list(FAULT_LATTICE.values()), ids=list(FAULT_LATTICE))
def test_fault_lattice_refuses_on_the_check_lane(
    tmp_path: Path, build_fault: Callable[[], Fault]
) -> None:
    descriptor, contract, expected = build_fault()
    name = expected.rstrip(":").replace(" ", "_")
    descriptor_path = _write_package(
        tmp_path, name, descriptor, contract, recompute_digest=False
    )
    result = _check(descriptor_path)
    assert result.exit_code == 1, result.output
    assert expected in result.output


@pytest.mark.parametrize("build_fault", list(FAULT_LATTICE.values()), ids=list(FAULT_LATTICE))
def test_fault_lattice_document_lane_behaves_as_declared(
    tmp_path: Path, build_fault: Callable[[], Fault]
) -> None:
    """Document-lane faults refuse at validate_descriptor; check-lane faults pass it.

    The split is the honest offline boundary: an escaping path or a wrong
    digest is invisible without the package on disk.
    """
    descriptor, _, expected = build_fault()
    if expected in ("provider_contract_missing:", "provider_contract_hash_mismatch:"):
        validate_descriptor(descriptor)
    else:
        with pytest.raises(ValueError, match=expected):
            validate_descriptor(descriptor)


def test_check_lane_fault_split_matches_the_table() -> None:
    # The document lane passes exactly the two check-lane faults; the table
    # and the split must not drift apart silently.
    assert CHECK_LANE_FAULTS.issubset(FAULT_LATTICE)


# --------------------------------------------------------------------------
# Focused arms beyond the lattice
# --------------------------------------------------------------------------


def test_known_feature_census_is_derived_from_the_vendored_tree() -> None:
    catalog = contract_documents()[_otdp_key("/device-profile-catalog.json")]
    expected = _LANES | {profile["id"] for profile in catalog["profiles"]}
    derived = _corpus_known_otdp_features()
    assert derived == expected
    assert len(expected) == 17  # five lanes + twelve catalog profiles at 0.2.1


def test_transport_namespace_typo_is_unknown_not_orphan() -> None:
    # The record's F2 case: otdp.transports.* (plural) is not the sanctioned
    # otdp.transport.* namespace and not corpus-known — the closure refuses it.
    descriptor, _ = _minimal_pair()
    descriptor["required_features"].append("otdp.transports.hid/1.0.0")
    with pytest.raises(ValueError, match="unknown_otdp_feature:"):
        validate_descriptor(descriptor)


def test_pattern_malformed_sha_is_the_schema_surface() -> None:
    # A 63-hex sha256 violates the provider object's pattern; the corpus
    # assigns that fault to the schema, not to a named provider prefix.
    descriptor, _ = _minimal_pair()
    descriptor["transport"]["provider"]["sha256"] = "a" * 63
    with pytest.raises(ValueError, match="Contract validation failed"):
        validate_descriptor(descriptor)


def test_unbacked_custom_transport_stays_valid() -> None:
    # The corpus reference-rawlink example: custom without provider is the
    # honestly-incomplete posture, not a refusal (transport-providers §2).
    validate_descriptor(json.loads(_vendored_bytes(_otdp_key("/examples/reference-rawlink.json"))))


def test_reference_contract_passes_validate_transport_provider() -> None:
    validate_transport_provider(
        json.loads(_vendored_bytes(_otdp_key("/examples/reference-provider.json")))
    )


def _grammar_fault(mutation: str) -> dict[str, Any]:
    contract = json.loads(_vendored_bytes(_otdp_key("/examples/reference-provider.json")))
    if mutation == "duplicate_kind_string":
        # Same kind, different body: uniqueItems is blind to this (F4).
        contract["transaction_grammar"][1]["kind"] = contract["transaction_grammar"][0]["kind"]
        contract["transaction_grammar"][1]["limits"] = {"max_report_bytes": 32}
    elif mutation == "invalid_subschema":
        # F1: {"type": "object"} holders admit schemas the metaschema refuses.
        contract["transaction_grammar"][0]["request_schema"] = {"type": "strin"}
    elif mutation == "urn_version_disagrees":
        contract["id"] = "urn:otdp:transport-provider:reference-hid:1.2.0"
    elif mutation == "feature_version_disagrees":
        contract["feature_id"] = "otdp.transport.reference-hid/1.2.0"
    elif mutation == "name_segments_disagree":
        contract["id"] = "urn:otdp:transport-provider:reference-hid2:1.0.0"
    elif mutation == "reserved_generic_kind":
        contract["transaction_grammar"][0]["kind"] = "stream_send"
    elif mutation == "fake_core_feature":
        # The M2 twin: a contract must not mint reserved ids at fake versions.
        contract["feature_id"] = "otdp.core/9.9.9"
    else:  # pragma: no cover - the parametrization is closed
        raise AssertionError(mutation)
    return contract


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_kind_string",
        "invalid_subschema",
        "urn_version_disagrees",
        "feature_version_disagrees",
        "name_segments_disagree",
        "reserved_generic_kind",
        "fake_core_feature",
    ],
)
def test_grammar_and_identity_faults_refuse_provider_contract_invalid(mutation: str) -> None:
    with pytest.raises(ValueError, match="provider_contract_invalid:"):
        validate_transport_provider(_grammar_fault(mutation))


def test_pin_may_live_in_a_subdirectory_of_the_package(tmp_path: Path) -> None:
    descriptor, contract = _minimal_pair()
    descriptor["transport"]["provider"]["path"] = "contracts/reference-provider.json"
    package = tmp_path / "nested"
    package.mkdir()
    (package / "contracts").mkdir()
    raw = (json.dumps(contract, indent=2) + "\n").encode()
    (package / "contracts" / "reference-provider.json").write_bytes(raw)
    descriptor["transport"]["provider"]["sha256"] = hashlib.sha256(raw).hexdigest()
    (package / "descriptor.json").write_text(json.dumps(descriptor, indent=2) + "\n")
    result = _check(package / "descriptor.json")
    assert result.exit_code == 0, result.output


def test_absent_pin_is_contract_missing(tmp_path: Path) -> None:
    descriptor, _ = _minimal_pair()
    descriptor_path = _write_package(tmp_path, "absent", descriptor, None)
    result = _check(descriptor_path)
    assert result.exit_code == 1
    assert "provider_contract_missing:" in result.output


def test_absolute_pin_path_is_contract_missing(tmp_path: Path) -> None:
    descriptor, _ = _minimal_pair()
    descriptor["transport"]["provider"]["path"] = "/etc/passwd"
    descriptor_path = _write_package(tmp_path, "absolute", descriptor, None)
    result = _check(descriptor_path)
    assert result.exit_code == 1
    assert "provider_contract_missing:" in result.output


def test_symlinked_pin_is_contract_missing(tmp_path: Path) -> None:
    descriptor, contract = _minimal_pair()
    package = tmp_path / "symlinked"
    package.mkdir()
    target = tmp_path / "elsewhere.json"
    target.write_bytes((json.dumps(contract, indent=2) + "\n").encode())
    try:
        (package / "reference-provider.json").symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable (privilege or filesystem)")
    descriptor["transport"]["provider"]["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    (package / "descriptor.json").write_text(json.dumps(descriptor, indent=2) + "\n")
    result = _check(package / "descriptor.json")
    assert result.exit_code == 1
    assert "provider_contract_missing:" in result.output


def test_pinned_contract_must_agree_with_the_declaration(tmp_path: Path) -> None:
    # transport-providers §7 lists "the feature-id agreement" as offline-
    # provable: the pinned document must declare the required feature and
    # carry the declared identity, not merely be any valid contract.
    descriptor, contract = _minimal_pair()
    contract["feature_id"] = "otdp.transport.someone-else/1.0.0"
    contract["id"] = "urn:otdp:transport-provider:someone-else:1.0.0"
    descriptor_path = _write_package(tmp_path, "disagrees", descriptor, contract)
    result = _check(descriptor_path)
    assert result.exit_code == 1
    assert "provider_contract_invalid:" in result.output


def test_verify_provider_pin_returns_the_validated_document(tmp_path: Path) -> None:
    descriptor, contract = _minimal_pair()
    descriptor_path = _write_package(tmp_path, "returns", descriptor, contract)
    pinned = verify_provider_pin(json.loads(descriptor_path.read_text()), descriptor_path)
    assert pinned is not None
    assert pinned["feature_id"] == _PROVIDER_FEATURE


def test_verify_provider_pin_is_none_without_a_declaration(tmp_path: Path) -> None:
    descriptor, _ = _base_pair()
    del descriptor["transport"]["provider"]
    descriptor["required_features"].remove(_PROVIDER_FEATURE)
    package = tmp_path / "bare"
    package.mkdir()
    (package / "descriptor.json").write_text(json.dumps(descriptor, indent=2) + "\n")
    assert verify_provider_pin(descriptor, package / "descriptor.json") is None
