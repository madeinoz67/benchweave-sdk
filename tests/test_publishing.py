"""The entry-gate battery and packaging discipline (A4, CR-1..CR-6, CR-35..50).

Six mutants refuse with stable prefixes; six control arms (mutant + missing
piece restored) pass packaging. Determinism, component-deletion arms and the
namespace rules are pinned alongside.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.publishing import (
    PublishingError,
    build_submission,
    check_namespace,
    closure_digest_of_dependencies,
    parse_dependency,
    validate_submission_draft,
    validate_transport_triple,
)

HEX40 = "1" * 40
HEX64 = "2" * 64
CAPABILITIES_NONE = {
    "network_egress": False,
    "subprocess_or_native_library": False,
    "filesystem_writes_beyond_evidence_retention": False,
}

_DESCRIPTOR: dict[str, Any] = {
    "otdp_version": "0.2.2",
    "descriptor_version": "0.2.0",
    "id": "org.example.widget",
    "display_name": "Widget fixture",
    "description": "Synthetic widget fixture for the publishing battery.",
    "identity": {
        "strategy": "adapter",
        "manufacturer": "Exampleworks",
        "model": "widget-1",
        "firmware_policy": "commissioned",
    },
    "integration": {
        "mode": "adapter",
        "adapter": {
            "entry_point": "benchweave_wgt_widget.adapter:create_plugin",
            "api_version": "1.1",
            "version": "0.1.0",
            "dependencies": [],
            "permissions": [],
        },
    },
    "transport": {"type": "serial", "connection_key": "widget"},
    "capabilities": ["identify", "read"],
}


def make_plugin(root: Path, name: str = "wgt_widget") -> Path:
    plugin = root / name
    source = plugin / "src" / f"benchweave_{name}"
    source.mkdir(parents=True, exist_ok=True)
    (source / "descriptor.json").write_bytes(json.dumps(_DESCRIPTOR, indent=2).encode())
    (source / "adapter.py").write_text("def create_plugin():\n    return object()\n")
    (source / "__init__.py").write_text("")
    docs = plugin / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "protocol-evidence.md").write_text("# Evidence\n\nSynthetic mock exchanges only.\n")
    (plugin / "LICENSE").write_text("MIT (fixture)\n")
    (plugin / "README.md").write_text("# Widget fixture\n")
    (plugin / "pyproject.toml").write_text(
        '[project]\nname = "widget"\nversion = "0.1.0"\nrequires-python = ">=3.13"\n'
    )
    return plugin


def make_registry_clone(root: Path) -> Path:
    clone = root / "registry-clone"
    (clone / "records").mkdir(parents=True, exist_ok=True)
    (clone / "records" / "publishers.json").write_bytes(
        b'{"publishers":[{"github":"madeinoz67","namespace":"madeinoz67",'
        b'"publisher_id":"madeinoz67","publisher_repo_protections":[{"protection":"push-protection",'
        b'"state":"declared-not-verified"}],"vetted_at":"2026-10-01T00:00:00Z"}],"publishers_version":1}\n'
    )
    (clone / "lane-rules.json").write_bytes(
        json.dumps(
            {
                "rules_version": 1,
                "namespace_rules": {
                    "id_grammar": "publisher/plugin",
                    "reserved_namespaces": ["benchweave", "otdp", "dev", "stg"],
                    "reserved_plugins": ["sim-psu"],
                    "dev_registry_prefix": "dev-",
                },
                "similarity_rule": {
                    "params": {
                        "case_sensitive": False,
                        "separator_characters": ["-", "_", ".", "/"],
                        "confusable_map": {"0": "o", "1": "l", "5": "s"},
                        "max_edit_distance": 2,
                    }
                },
            }
        ).encode()
        + b"\n"
    )
    return clone


def build(tmp_path: Path, *, plugin: Path | None = None, **overrides: Any) -> Any:
    resolved = plugin or make_plugin(tmp_path)
    clone = make_registry_clone(tmp_path)
    kwargs: dict[str, Any] = {
        "registry_clone": clone,
        "source_url": "https://github.com/example/widget",
        "revision": HEX40,
        "publisher": "madeinoz67",
        "capability_declaration": dict(CAPABILITIES_NONE),
    }
    kwargs.update(overrides)
    return build_submission(resolved, **kwargs)


# --- A4: the six-mutant entry-gate battery ---------------------------------------


def test_dev_lineage_dependency_is_refused(tmp_path: Path) -> None:
    dep = {
        "registry_id": "dev-local",
        "package_id": "dev/widget",
        "version": "1.0.0",
        "manifest_sha256": HEX64,
    }
    with pytest.raises(PublishingError) as exc:
        build(tmp_path, dependencies=[dep])
    assert str(exc.value).startswith("dev_lineage_refused:")


def test_dev_lineage_control_arm_passes(tmp_path: Path) -> None:
    dep = {
        "registry_id": "benchweave-registry",
        "package_id": "madeinoz67/widget-descriptor",
        "version": "1.0.0",
        "manifest_sha256": HEX64,
    }
    artifacts = build(tmp_path, dependencies=[dep])
    assert artifacts.manifest["dependencies"] == [dep]


def test_mutable_source_ref_is_refused(tmp_path: Path) -> None:
    for revision in ("main", "v1", "latest", "release-branch"):
        with pytest.raises(PublishingError) as exc:
            build(tmp_path, revision=revision)
        assert str(exc.value).startswith("source_ref_mutable:"), revision


def test_immutable_source_ref_control_arm_passes(tmp_path: Path) -> None:
    artifacts = build(tmp_path, revision=HEX64)
    assert artifacts.manifest["source"]["revision"] == HEX64


def test_missing_capability_declaration_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PublishingError) as exc:
        build(tmp_path, capability_declaration=None)
    assert str(exc.value).startswith("capability_declaration_absent:")


def test_capability_none_control_arm_passes(tmp_path: Path) -> None:
    artifacts = build(tmp_path)
    assert artifacts.submission["capability_declaration"] == CAPABILITIES_NONE


def test_firmware_without_attestation_is_refused(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path)
    firmware = plugin / "src" / "benchweave_wgt_widget" / "firmware"
    firmware.mkdir()
    (firmware / "blob.bin").write_bytes(b"\x00\x01")
    with pytest.raises(PublishingError) as exc:
        build(tmp_path, plugin=plugin)
    assert str(exc.value).startswith("firmware_provenance_absent:")


def test_firmware_attestation_control_arm_passes(tmp_path: Path) -> None:
    """The restored arm: vendor attestation pinned, firmware vendor-distributed
    (not bundled) — the shape the spec's redistribution clause sanctions."""
    plugin = make_plugin(tmp_path)
    artifacts = build(
        tmp_path,
        plugin=plugin,
        firmware_attestation={"vendor": "Exampleworks", "manifest": "firmware/vendor.manifest"},
    )
    assert artifacts.submission["firmware_attestation"]["vendor"] == "Exampleworks"
    assert not any(
        entry["path"].startswith("firmware/")
        for entry in artifacts.manifest["payload"]["files"]
    )


def test_bundled_firmware_with_attestation_publishes_vendor_distributed(
    tmp_path: Path,
) -> None:
    """Owner ruling (issue #223 rework): attested firmware is stated, not
    refused — enforcement is the client's decision. The bytes never bundle
    (the payload-role enum carries no firmware role); the attestation and the
    exclusion are recorded in the draft."""
    plugin = make_plugin(tmp_path)
    firmware = plugin / "src" / "benchweave_wgt_widget" / "firmware"
    firmware.mkdir()
    (firmware / "blob.bin").write_bytes(b"\x00\x01")
    artifacts = build(
        tmp_path,
        plugin=plugin,
        firmware_attestation={"vendor": "Exampleworks", "manifest": "firmware/vendor.manifest"},
    )
    recorded = artifacts.submission["firmware_attestation"]
    assert recorded["vendor"] == "Exampleworks"
    assert recorded["bytes"] == "vendor-distributed"
    assert recorded["files"] == ["firmware/blob.bin"]
    assert not any(
        entry["path"].startswith("firmware/")
        for entry in artifacts.manifest["payload"]["files"]
    ), "attested firmware bytes stay vendor-distributed, never bundled"


def test_same_author_next_version_routes_to_closure_diff(tmp_path: Path) -> None:
    """F2 (issue #223 rework): --version 0.2.0 on an existing same-author
    package publishes, carrying the closure diff against the 0.1.0 prior."""
    plugin = make_plugin(tmp_path)
    clone = make_registry_clone(tmp_path)
    prior = clone / "releases" / "benchweave-registry" / "madeinoz67" / "wgt_widget" / "0.1.0"
    prior.mkdir(parents=True)
    (prior / "manifest.json").write_bytes(
        json.dumps(
            {
                "registry_id": "benchweave-registry",
                "package_id": "madeinoz67/wgt_widget",
                "version": "0.1.0",
                "publisher_id": "madeinoz67",
                "dependencies": [],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    artifacts = build(tmp_path, plugin=plugin, version="0.2.0")
    assert artifacts.manifest["version"] == "0.2.0"
    assert artifacts.submission["closure"]["prior"] == {"version": "0.1.0"}


def test_cross_author_existing_id_still_collides(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path)
    clone = make_registry_clone(tmp_path)
    hijacked = clone / "releases" / "benchweave-registry" / "acme-labs" / "wgt_widget" / "1.0.0"
    hijacked.mkdir(parents=True)
    (hijacked / "manifest.json").write_bytes(
        json.dumps(
            {
                "registry_id": "benchweave-registry",
                "package_id": "acme-labs/wgt_widget",
                "version": "1.0.0",
                "publisher_id": "someone-else",
                "dependencies": [],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    with pytest.raises(PublishingError) as exc:
        build(tmp_path, plugin=plugin, publisher="acme-labs")
    assert str(exc.value).startswith("namespace_collision:")


def test_transport_declaration_without_triples_is_refused(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path)
    descriptor_path = plugin / "src" / "benchweave_wgt_widget" / "descriptor.json"
    descriptor = dict(_DESCRIPTOR)
    descriptor["contracts"] = [
        {"id": "otdp.transport.mock/1.0.0", "path": "contracts/mock.json", "sha256": HEX64}
    ]
    descriptor_path.write_bytes(json.dumps(descriptor).encode())
    with pytest.raises(PublishingError) as exc:
        build(tmp_path, plugin=plugin)
    assert str(exc.value).startswith("transport_triples_absent:")


def test_transport_triples_control_arm_passes(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path)
    descriptor_path = plugin / "src" / "benchweave_wgt_widget" / "descriptor.json"
    descriptor = dict(_DESCRIPTOR)
    descriptor["contracts"] = [
        {"id": "otdp.transport.mock/1.0.0", "path": "contracts/mock.json", "sha256": HEX64}
    ]
    descriptor_path.write_bytes(json.dumps(descriptor).encode())
    triple = {"id": "otdp.transport.mock/1.0.0", "version": "1.0.0", "sha256": HEX64}
    artifacts = build(tmp_path, plugin=plugin, transport_triples=(triple,))
    assert artifacts.submission["transport_triples"] == [triple]


def test_publish_record_without_closure_diff_is_refused(tmp_path: Path) -> None:
    artifacts = build(tmp_path)
    member_paths = {entry["path"] for entry in artifacts.manifest["payload"]["files"]}
    mutant = dict(artifacts.submission)
    del mutant["closure"]
    with pytest.raises(PublishingError) as exc:
        validate_submission_draft(mutant, member_paths)
    assert str(exc.value).startswith("closure_diff_absent:")


def test_closure_diff_control_arm_passes(tmp_path: Path) -> None:
    artifacts = build(tmp_path)
    member_paths = {entry["path"] for entry in artifacts.manifest["payload"]["files"]}
    validate_submission_draft(artifacts.submission, member_paths)


# --- determinism (A1's second run) -------------------------------------------------


def test_packaging_is_byte_reproducible(tmp_path: Path) -> None:
    first = build(tmp_path)
    second = build(tmp_path)
    assert first.manifest_bytes == second.manifest_bytes
    assert first.payload_bytes == second.payload_bytes
    assert first.submission_bytes == second.submission_bytes


# --- component-deletion arms (A2's tool half, CR-1) --------------------------------


@pytest.mark.parametrize(
    ("remove", "component"),
    [
        ("descriptor", "descriptor"),
        ("sources", "adapter-source"),
        ("evidence", "conformance-evidence"),
        ("licence", "licence"),
    ],
)
def test_deleted_component_refuses_naming_it(tmp_path: Path, remove: str, component: str) -> None:
    plugin = make_plugin(tmp_path)
    source = plugin / "src" / "benchweave_wgt_widget"
    if remove == "descriptor":
        (source / "descriptor.json").unlink()
    elif remove == "sources":
        shutil.rmtree(source)
        source.mkdir()
        (source / "descriptor.json").write_bytes(json.dumps(_DESCRIPTOR).encode())
    elif remove == "evidence":
        shutil.rmtree(plugin / "docs")
    elif remove == "licence":
        (plugin / "LICENSE").unlink()
    clone = make_registry_clone(tmp_path)
    with pytest.raises(PublishingError) as exc:
        build_submission(
            plugin,
            registry_clone=clone,
            source_url="https://github.com/example/widget",
            revision=HEX40,
            publisher="madeinoz67",
            capability_declaration=dict(CAPABILITIES_NONE),
        )
    assert "component_absent:" in str(exc.value) and component in str(exc.value)


# --- namespace rules (CR-15/16/39) --------------------------------------------------


def _rules() -> Any:
    from benchweave_sdk.publishing import LaneRules

    return LaneRules(
        reserved_namespaces=frozenset({"benchweave", "otdp", "dev", "stg"}),
        reserved_plugins=frozenset({"sim-psu"}),
        similarity_max_distance=2,
        confusables={"0": "o", "1": "l", "5": "s"},
    )


def test_reserved_namespace_is_refused() -> None:
    findings = check_namespace("benchweave/labs", _rules(), set(), {})
    assert any(f.startswith("namespace_reserved:") for f in findings)


def test_cross_owner_same_id_collides() -> None:
    """A different author's claim to an existing package id still collides."""
    findings = check_namespace(
        "madeinoz67/dps150", _rules(), set(), {"madeinoz67/dps150": {"acme-labs"}}
    )
    assert any(f.startswith("namespace_collision:") for f in findings)


def test_own_next_version_is_not_a_collision() -> None:
    """Owner ruling (issue #223 rework): a publisher's own next version of an
    existing id routes to closure-diff, never namespace_collision."""
    findings = check_namespace(
        "madeinoz67/dps150", _rules(), set(), {"madeinoz67/dps150": {"madeinoz67"}}
    )
    assert findings == []


def test_same_device_name_under_another_namespace_is_allowed() -> None:
    """Two different authors may register the same device name."""
    findings = check_namespace(
        "acme-labs/dps150", _rules(), {"madeinoz67"}, {"madeinoz67/dps150": {"madeinoz67"}}
    )
    assert findings == []


def test_lookalike_is_flagged_not_refused() -> None:
    findings = check_namespace("madeinoz68/pub", _rules(), {"madeinoz67"}, {})
    assert any(f.startswith("namespace_lookalike:") for f in findings)


def test_distinct_namespace_is_clean() -> None:
    findings = check_namespace(
        "acme-power/psu", _rules(), {"madeinoz67"}, {"madeinoz67/dps150": {"madeinoz67"}}
    )
    assert findings == []


# --- parsers -------------------------------------------------------------------------


def test_dependency_parser_round_trip() -> None:
    dep = parse_dependency("benchweave-registry/madeinoz67/dps150-descriptor@1.0.0:" + HEX64)
    assert dep == {
        "registry_id": "benchweave-registry",
        "package_id": "madeinoz67/dps150-descriptor",
        "version": "1.0.0",
        "manifest_sha256": HEX64,
    }


def test_dependency_parser_refuses_garbage() -> None:
    with pytest.raises(PublishingError):
        parse_dependency("dev-local/x@latest:zzz")


def test_transport_triple_parser() -> None:
    triple = validate_transport_triple("otdp.transport.mock/1.0.0@1.0.0:" + HEX64)
    assert triple["sha256"] == HEX64


def test_closure_digest_is_definition_pinned() -> None:
    deps = [
        {
            "registry_id": "benchweave-registry",
            "package_id": "madeinoz67/x-descriptor",
            "version": "1.0.0",
            "manifest_sha256": HEX64,
        }
    ]
    digest = closure_digest_of_dependencies(deps)
    pins = sorted(
        (dep["registry_id"], dep["package_id"], dep["version"], dep["manifest_sha256"])
        for dep in deps
    )
    expected = hashlib.sha256(
        json.dumps(pins, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    ).hexdigest()
    assert digest == expected


def test_generated_submission_manifest_is_canonical(tmp_path: Path) -> None:
    artifacts = build(tmp_path)
    assert json.loads(artifacts.manifest_bytes) == artifacts.manifest
    assert artifacts.manifest_bytes.endswith(b"\n")

# --- M3 (CR-49 fold): the scoped_transport permission form ---------------------


def test_scoped_transport_without_admission_is_refused(tmp_path: Path) -> None:
    """The tier rule reaches the permission form: the dps150's own shape
    (scoped_transport, zero triples, no recorded admission) refuses."""
    plugin = make_plugin(tmp_path)
    descriptor_path = plugin / "src" / "benchweave_wgt_widget" / "descriptor.json"
    descriptor = json.loads(descriptor_path.read_bytes())
    descriptor["integration"]["adapter"]["permissions"] = ["scoped_transport"]
    descriptor_path.write_bytes(json.dumps(descriptor).encode())
    with pytest.raises(PublishingError) as exc:
        build(tmp_path, plugin=plugin)
    assert str(exc.value).startswith("transport_triples_absent:")


def test_scoped_transport_with_recorded_admission_passes(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path)
    descriptor_path = plugin / "src" / "benchweave_wgt_widget" / "descriptor.json"
    descriptor = json.loads(descriptor_path.read_bytes())
    descriptor["integration"]["adapter"]["permissions"] = ["scoped_transport"]
    descriptor_path.write_bytes(json.dumps(descriptor).encode())
    clone = make_registry_clone(tmp_path)
    rules = json.loads((clone / "lane-rules.json").read_bytes())
    rules["transport_tier_rule"] = {"admissions": ["madeinoz67"]}
    (clone / "lane-rules.json").write_bytes(json.dumps(rules).encode() + b"\n")
    artifacts = build_submission(
        plugin,
        registry_clone=clone,
        source_url="https://github.com/example/widget",
        revision=HEX40,
        publisher="madeinoz67",
        capability_declaration=dict(CAPABILITIES_NONE),
    )
    assert artifacts.manifest["permissions"] == ["scoped_transport"]


# --- F5 (fold): the lookalike flag rides the artefact set ----------------------


def test_lookalike_flags_ride_the_submission_draft(tmp_path: Path) -> None:
    """CR-39's flag is computed, recorded and surfaced — never discarded."""
    plugin = make_plugin(tmp_path)
    clone = make_registry_clone(tmp_path)
    publishers = json.loads((clone / "records" / "publishers.json").read_bytes())
    publishers["publishers"].append(
        {
            "github": "near-twin",
            "namespace": "madeinoz68",
            "publisher_id": "madeinoz68",
            "publisher_repo_protections": [
                {"protection": "push-protection", "state": "declared-not-verified"}
            ],
            "vetted_at": "2026-10-01T00:00:00Z",
        }
    )
    (clone / "records" / "publishers.json").write_bytes(
        json.dumps(publishers, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    artifacts = build(tmp_path, plugin=plugin, publisher="madeinoz68")
    assert artifacts.lookalikes, "the similarity finding must not be discarded"
    assert any(
        flag.startswith("namespace_lookalike:") for flag in artifacts.lookalikes
    )
    assert artifacts.submission["namespace_lookalikes"] == artifacts.lookalikes
    assert "namespace_lookalikes" in json.loads(artifacts.submission_bytes)

