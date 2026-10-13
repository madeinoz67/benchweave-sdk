"""Plugin-authored profile documents: the profile-shadow rule and the pinned-$id merge guard.

Issue #446 slice 2, the SDK twin leg. The vendored plugin-ui contracts
module — the exact bytes the gateway's presentation validator runs — gains
the profile-shadow rule and the pinned-$id merge guard, and these arms pin
the same behavior the gateway's tests/unit/test_presentation_profiles.py
pins (design: gateway-repo
.claude/deep-review/2026-10-12-issue446-invoke-profile-map-design.md §3.2):
a digest-pinned plugin-authored contract document may re-declare a corpus
profile id — divergent rows refuse (`profile_shadow`); identical rows stay
benign dedup. A pinned document may not embed a `$id` that shadows a served
schema `$id` (`merge_pinned_documents` refuses `pinned_id_shadow`).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import benchweave_sdk
from benchweave_sdk.presentation import _contract

type JsonObject = dict[str, Any]

# The vendored twin module, loaded from the committed standards tree the
# same way every SDK entry point loads it. `merge_pinned_documents` is
# reached as `contract.merge_pinned_documents` inside the merge-guard arms,
# so the RED state (the function absent) fails per-test, not at collection.
contract = _contract()

ROOT = Path(benchweave_sdk.__file__).resolve().parent

VENDOR_PROFILE_ID = "vendor.la34/1.0.0"
CORPUS_PROFILE_ID = "otdp.dc_psu/1.0.0"
CORPUS_ACTION = "otdp.dc_psu.configure/1.0.0"


def encode(value: object) -> bytes:
    return json.dumps(value).encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load(path: str) -> JsonObject:
    document: JsonObject = json.loads((ROOT / path).read_bytes())
    return document


DOCUMENTS: JsonObject | None = None
CATALOG: JsonObject | None = None
DESCRIPTOR: JsonObject | None = None


def documents() -> JsonObject:
    """The trusted-host corpus document set: plugin-ui 0.3.1 schemas + OTDP 0.2.2 catalog."""
    global DOCUMENTS, CATALOG
    if DOCUMENTS is None:
        set_: JsonObject = {}
        for path in (ROOT / "standards/plugin-ui/0.3.1").glob("*.schema.json"):
            document = json.loads(path.read_bytes())
            set_[document["$id"]] = document
        CATALOG = load("standards/otdp/0.2.2/device-profile-catalog.json")
        set_["catalog"] = CATALOG
        DOCUMENTS = set_
    return DOCUMENTS


def corpus_catalog() -> JsonObject:
    documents()
    assert CATALOG is not None
    return CATALOG


def base_descriptor() -> JsonObject:
    global DESCRIPTOR
    if DESCRIPTOR is None:
        DESCRIPTOR = load("standards/otdp/0.2.2/examples/class-dc_psu.json")
    return DESCRIPTOR


def corpus_profile_row() -> JsonObject:
    row = [p for p in corpus_catalog()["profiles"] if p["id"] == CORPUS_PROFILE_ID][0]
    copy: JsonObject = json.loads(json.dumps(row))  # deep copy
    return copy


def pinned_catalog(
    profile_rows: list[JsonObject],
    *,
    id_: str = "urn:vendor-la34:profile-catalog:1.0.0",
    actions: JsonObject | None = None,
) -> JsonObject:
    document: JsonObject = {
        "$id": id_,
        "contract_version": "0.3.1",
        "catalog_version": "0.2.2",
        "otdp_version": "0.2.2",
        "profiles": profile_rows,
        "actions": actions if actions is not None else {},
    }
    return document


def validate_with(
    documents: JsonObject,
    *,
    descriptor: JsonObject | None = None,
    target: JsonObject | None = None,
) -> object:
    """Validate a configuration-target specimen over the given document set."""
    descriptor = descriptor if descriptor is not None else base_descriptor()
    if target is None:
        action_schema = corpus_catalog()["actions"][CORPUS_ACTION]["input_schema"]
        target = {
            "id": "configure",
            "kind": "configuration",
            "action_id": CORPUS_ACTION,
            "profile_ids": [CORPUS_PROFILE_ID],
            "input_schema_id": action_schema["$id"],
            "schema_asset_id": "settings",
            "preset_asset_ids": [],
        }
    descriptor_raw = encode(descriptor)
    manifest = {
        "contract_version": "0.3.1",
        "plugin_id": descriptor["id"],
        "descriptor_sha256": digest(descriptor_raw),
        "bindings": [
            {"id": "configuration", "kind": "configuration", "target_id": "configure"}
        ],
        "pages": [
            {
                "id": "settings",
                "kind": "configuration",
                "title": "Settings",
                "bindings": ["configuration"],
                "required": True,
            }
        ],
    }
    action_schema_raw = encode(corpus_catalog()["actions"][CORPUS_ACTION]["input_schema"])
    assets = {"settings": action_schema_raw}
    manifest["assets"] = [
        {"id": name, "path": name + ".json", "sha256": digest(raw)} for name, raw in assets.items()
    ]
    manifest_raw = encode(manifest)
    catalogue = {
        "contract_version": "0.3.1",
        "descriptor_sha256": digest(descriptor_raw),
        "targets": [target],
    }
    envelope = {
        "contract_version": "0.3.1",
        "descriptor_sha256": digest(descriptor_raw),
        "resource_root": "ui",
        "manifest": {"path": "manifest.json", "sha256": digest(manifest_raw)},
    }
    resources = {name + ".json": raw for name, raw in assets.items()}
    resources["manifest.json"] = manifest_raw
    return contract.validate_presentation(
        encode(envelope),
        descriptor_raw=descriptor_raw,
        resources=resources,
        binding_catalogue=catalogue,
        schema_documents=documents,
        supported_features=frozenset(),
        supported_panels=frozenset(),
        firmware="1.0",
    )


def test_corpus_specimen_is_valid_without_pinned_documents() -> None:
    """Baseline: the corpus-only set validates (0.3.0 behavior unchanged)."""
    report = validate_with(documents())
    assert report.valid, report.findings


def test_pinned_duplicate_identical_rows_admits() -> None:
    """Identical duplicate = benign dedup: the target binds the same rows either way."""
    set_ = dict(documents())
    set_["pinned:vendor-cat"] = pinned_catalog([corpus_profile_row()])
    report = validate_with(set_)
    assert report.valid, report.findings


def test_pinned_duplicate_divergent_rows_refuses() -> None:
    """Divergent duplicate + target binds the shadowed id → `profile_shadow`."""
    divergent = corpus_profile_row()
    divergent["optional_actions"] = ["otdp.dc_psu.measure/1.0.0"]
    set_ = dict(documents())
    set_["pinned:vendor-cat"] = pinned_catalog([divergent])
    report = validate_with(set_)
    assert not report.valid
    assert contract.Finding(
        "profile_shadow",
        "targets.configure",
        'Profile id "otdp.dc_psu/1.0.0" is declared with divergent rows by multiple documents',
    ) in report.findings


def test_merge_guard_refuses_planted_corpus_id() -> None:
    """A pinned document may not embed a served schema `$id` (the poisoning vector)."""
    planted = pinned_catalog(
        [corpus_profile_row()], id_=contract.SCHEMA_ROOT + "ui-manifest.schema.json"
    )
    with pytest.raises(contract.DocumentError) as excinfo:
        contract.merge_pinned_documents(documents(), {"vendor-cat": planted})
    assert excinfo.value.code == "pinned_id_shadow"
    assert "vendor-cat" in str(excinfo.value)
    assert "ui-manifest" in str(excinfo.value)


def test_merge_guard_refuses_action_schema_id_collision() -> None:
    """The guard also scans a pinned document's action-schema `$id`s."""
    action_schema_id = corpus_catalog()["actions"][CORPUS_ACTION]["input_schema"]["$id"]
    planted = pinned_catalog(
        [corpus_profile_row()],
        actions={CORPUS_ACTION: {"input_schema": {"$id": action_schema_id}}},
    )
    with pytest.raises(contract.DocumentError) as excinfo:
        contract.merge_pinned_documents(documents(), {"vendor-cat": planted})
    assert excinfo.value.code == "pinned_id_shadow"
    assert action_schema_id in str(excinfo.value)


def test_merge_guard_refuses_pinned_pairwise_collision() -> None:
    """Two pinned documents aliasing one `$id` refuse (the within-set residual)."""
    vendor = pinned_catalog([corpus_profile_row()])
    with pytest.raises(contract.DocumentError) as excinfo:
        contract.merge_pinned_documents(
            documents(),
            {"vendor-cat": vendor, "vendor-cat-2": pinned_catalog([], id_=vendor["$id"])},
        )
    assert excinfo.value.code == "pinned_id_shadow"


def test_merge_guard_admits_unique_vendor_ids() -> None:
    """A pinned document with unique vendor `$id`s merges under its pinned: key."""
    vendor = pinned_catalog([corpus_profile_row()])
    merged = contract.merge_pinned_documents(documents(), {"vendor-cat": vendor})
    assert merged["pinned:vendor-cat"] is vendor
    assert merged["catalog"] is corpus_catalog()
    # The merged set validates the corpus specimen unchanged.
    report = validate_with(merged)
    assert report.valid, report.findings
