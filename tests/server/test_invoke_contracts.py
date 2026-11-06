"""The pinned-contract resolution behind invoke (issue #589 §3.1, PR-2):
the port of the gateway's resolver, its soft arms, and the parity guard
against a URN-keyed skip ever returning.

The hard/soft split is the gateway's own: present bytes that LIE refuse
construction (``profile_contract_*:``), while an absent path or a half pair
leaves the set unresolved (``None`` — invoke answers ``unavailable`` with
``reason: contracts_unresolved``). The parity guard is an ARM, not prose: a
catalog-invalid document under a NON-OTDP URN refuses construction, and a
live seam never compiles one through a reload — the skip the maintainer
ruled out because the pin's ``id`` is plugin-chosen, so any URN-keyed skip
is a gate the plugin itself operates.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk_server.errors import SeamError
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.session import load_plugin_project, mock_plugin_session


def _seam(project: Path, **kwargs: Any) -> tuple[StandaloneSeam, Any]:
    """Load the project, fish the freshly imported scripted adapter out of
    the module cache, and build a mock-transport seam over it."""
    plugin = load_plugin_project(Path(project))
    adapter = sys.modules[f"{plugin.package}.adapter"]
    return (
        StandaloneSeam(mock_plugin_session(plugin), transport_kind="mock", **kwargs),
        adapter,
    )


def _invalid_profile_document() -> bytes:
    """A profile-SHAPED document where the corpus requires a CATALOG: the
    wrong-shape pin (``profile_id``/``title``, no ``catalog_version``, no
    ``profiles`` array) — invented names, the shape of the real plugin's
    measured mistake."""
    document = {
        "profile_id": "example.vendor/1.0.0",
        "title": "A profile, not a catalog",
        "description": "Profile-shaped: the catalog schema requires "
        "catalog_version and a profiles array.",
    }
    return (json.dumps(document, indent=2) + "\n").encode()


def _add_pin(project: Path, name: str, payload: bytes, identifier: str) -> None:
    """Write one pinned document into the package and add its pin row."""
    package = project / "src" / "example_plugin"
    (package / name).write_bytes(payload)
    descriptor = json.loads((package / "descriptor.json").read_text())
    descriptor.setdefault("contracts", []).append({
        "id": identifier,
        "path": name,
        "sha256": hashlib.sha256(payload).hexdigest(),
    })
    (package / "descriptor.json").write_text(json.dumps(descriptor, indent=2) + "\n")


def _call(seam: StandaloneSeam, operation: str, arguments: dict[str, Any]) -> Any:
    return asyncio.run(seam.call(operation, arguments))


# --- the parity guard (M14): no URN-keyed skip, at either door -----------------


def test_a_catalog_invalid_non_otdp_pin_refuses_construction(
    tmp_path: Path, invoke_project_builder
) -> None:
    """The construction half of the parity guard: a pinned entry that is
    neither measurement-shaped nor catalog-schema-valid refuses
    ``profile_contract_invalid:`` whatever its URN — the resolver matches
    the gateway, whose loader raises ActivationRejected for the same bytes."""
    project = invoke_project_builder(tmp_path / "parity")
    _add_pin(
        project,
        "vendor-profile.json",
        _invalid_profile_document(),
        "https://vendor.example/profile-1",
    )
    with pytest.raises(ValueError, match=r"^profile_contract_invalid:"):
        _seam(project)


def test_a_live_seam_never_compiles_a_catalog_invalid_pin(
    tmp_path: Path, invoke_project_builder
) -> None:
    """The never-compiled half of the parity guard (fold-wave item 8, M16):
    a LIVE seam refuses the reload to an incoming catalog-invalid non-OTDP
    pin BEFORE the session swap, and the previous session keeps serving
    invoke; under a URN-keyed skip the reload would succeed and the skipped
    document's action would be servable."""
    project = invoke_project_builder(tmp_path / "live")
    seam, _adapter = _seam(project)
    _call(seam, "device_connect", {"device_id": "example_device"})
    _add_pin(
        project,
        "vendor-profile.json",
        _invalid_profile_document(),
        "https://vendor.example/profile-1",
    )
    with pytest.raises(SeamError) as caught:
        asyncio.run(seam.reload_plugin(source="test"))
    assert caught.value.code == "invalid_request"
    assert "profile_contract_invalid:" in str(caught.value.details.get("diagnostic"))
    # The previous session is still the loaded one, still connected, and
    # still serves its own resolved action registry.
    result = _call(
        seam, "invoke", {"device_id": "example_device",
                         "action_id": "demo.probe/1.0.0", "input": {}},
    )
    assert result["action_id"] == "demo.probe/1.0.0"


# --- the hard arms: present bytes that lie -------------------------------------


def test_a_digest_mismatch_refuses_construction(
    tmp_path: Path, invoke_project_builder
) -> None:
    project = invoke_project_builder(tmp_path / "mismatch")
    _add_pin(project, "tampered.json",
             (json.dumps({"catalog_version": "lies"}, indent=2) + "\n").encode(),
             "urn:example:tampered:1")
    # Corrupt the descriptor's claim, not the bytes: the pin lies about
    # what the file hashes to.
    package = project / "src" / "example_plugin"
    descriptor = json.loads((package / "descriptor.json").read_text())
    descriptor["contracts"][-1]["sha256"] = "0" * 64
    (package / "descriptor.json").write_text(json.dumps(descriptor, indent=2) + "\n")
    with pytest.raises(ValueError, match=r"^profile_contract_hash_mismatch:"):
        _seam(project)


def test_a_traversing_pin_path_refuses_construction(
    tmp_path: Path, invoke_project_builder
) -> None:
    row = {
        "id": "urn:example:escape:1",
        "path": "../descriptor.json",
        "sha256": "0" * 64,
    }
    project = invoke_project_builder(
        tmp_path / "traversal", pin_catalog=False, pin_measurement=False,
        extra_pins=[row],
    )
    with pytest.raises(ValueError, match=r"^profile_contract_missing:"):
        _seam(project)


def test_an_unparsable_pin_refuses_construction(
    tmp_path: Path, invoke_project_builder
) -> None:
    project = invoke_project_builder(tmp_path / "unparsable")
    _add_pin(project, "broken.json", b"{ not json", "urn:example:broken:1")
    with pytest.raises(ValueError, match=r"^profile_contract_invalid:"):
        _seam(project)


def test_a_second_catalog_refuses_construction(
    tmp_path: Path, invoke_project_builder
) -> None:
    """Two catalog-schema-valid documents leave the same ambiguity two
    measurements would (which input_schema gates I4) — refused, never
    resolved by order (the gateway's NIT-2)."""
    second = {
        "catalog_version": "0.2.4",
        "otdp_version": "0.2.4",
        "profiles": [{
            "id": "example.second/1.0.0", "title": "Second synthetic profile",
            "channel_roles": ["control"],
            "required_actions": ["demo.probe/1.0.0"],
            "optional_actions": [],
        }],
        "actions": {
            "demo.probe/1.0.0": {
                "description": "A rival declaration for the same action.",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "side_effect": "none",
                "lifecycle": "direct",
            },
        },
    }
    project = invoke_project_builder(tmp_path / "two-catalogs")
    _add_pin(project, "second-catalog.json",
             (json.dumps(second, indent=2) + "\n").encode(),
             "urn:example:second:1")
    with pytest.raises(ValueError, match=r"profile_contract_invalid:"):
        _seam(project)


def test_a_degenerate_measurement_dataset_refuses_construction(
    tmp_path: Path, invoke_project_builder
) -> None:
    """A measurement-shaped schema whose dataset definition declares no
    required keys degenerates the dataset-shape detector to every object —
    refused at load (the gateway's fix-wave F4)."""
    degenerate = {
        "$id": "urn:otdp:measurement:9.9.9",
        "$defs": {"dataset": {"type": "object"}},
    }
    project = invoke_project_builder(tmp_path / "degenerate", pin_measurement=False)
    _add_pin(project, "degenerate-measurement.json",
             (json.dumps(degenerate, indent=2) + "\n").encode(),
             "urn:otdp:measurement:9.9.9")
    with pytest.raises(ValueError, match=r"profile_contract_invalid:"):
        _seam(project)


def test_a_catalog_urn_ref_the_pair_does_not_carry_refuses_construction(
    tmp_path: Path, invoke_project_builder
) -> None:
    """The closed-registry probe: the synthetic catalog's measurement_ref
    action references the measurement schema by urn, so pinning the catalog
    WITHOUT the measurement refuses at load — the reference is rooted
    exactly where the runtime validator roots it (the action's input
    subschema), never the bare document."""
    project = invoke_project_builder(
        tmp_path / "dangling-ref",
        pin_measurement=False,
        catalog_with_measurement_ref=True,
    )
    with pytest.raises(ValueError, match=r"profile_contract_invalid:"):
        _seam(project)


def test_a_catalog_urn_ref_resolves_when_the_pair_is_pinned(
    tmp_path: Path, invoke_project_builder
) -> None:
    """The probe's positive half: the same urn-referencing catalog loads
    when the measurement schema it names IS pinned — the closed registry
    resolves in-bundle references, it refuses only what lies outside the
    pinned set."""
    project = invoke_project_builder(
        tmp_path / "resolved-ref", catalog_with_measurement_ref=True
    )
    seam, _adapter = _seam(project)
    contracts = seam._invoke_contracts
    assert contracts is not None
    assert "demo.measurement_ref/1.0.0" in contracts.actions


# --- the soft arms: nothing was verified false ---------------------------------


def _assert_unresolved(seam_and_adapter: tuple[StandaloneSeam, Any]) -> None:
    seam, _ = seam_and_adapter
    _call(seam, "device_connect", {"device_id": "example_device"})
    with pytest.raises(SeamError) as caught:
        _call(
            seam, "invoke",
            {"device_id": "example_device",
             "action_id": "demo.probe/1.0.0", "input": {}},
        )
    assert caught.value.code == "unavailable"
    assert caught.value.details.get("reason") == "contracts_unresolved"


def test_an_absent_pin_path_leaves_the_set_unresolved(
    tmp_path: Path, invoke_project_builder
) -> None:
    row = {
        "id": "urn:example:absent:1",
        "path": "absent-catalog.json",
        "sha256": "1" * 64,
    }
    project = invoke_project_builder(
        tmp_path / "absent", pin_catalog=False, pin_measurement=False,
        extra_pins=[row],
    )
    _assert_unresolved(_seam(project))


def test_a_half_pair_leaves_the_set_unresolved(
    tmp_path: Path, invoke_project_builder
) -> None:
    project = invoke_project_builder(tmp_path / "half", pin_measurement=False)
    _assert_unresolved(_seam(project))


def test_the_measurement_without_a_catalog_leaves_the_set_unresolved(
    tmp_path: Path, invoke_project_builder
) -> None:
    project = invoke_project_builder(tmp_path / "measurement-only", pin_catalog=False)
    _assert_unresolved(_seam(project))


# NOTE, absent arm: an invoke-capable descriptor with NO contracts row is
# schema-unreachable (the descriptor schema requires the key with minItems 1
# for the invoke capability), so "descriptor pins nothing" cannot occur here
# — the resolver's empty-entries None return is exercised by every
# non-invoke plugin the rest of the suite loads.


def test_a_catalog_invalid_pin_maps_to_serve_exit_2(
    tmp_path: Path, invoke_project_builder, capsys
) -> None:
    """The CLI's fail-fast for the contract family (the budget arm's
    sibling): a lying pin refuses serve construction with the typed prefix
    on stderr and exit 2, never a traceback."""
    from benchweave_sdk_server.cli import _build_seam

    project = invoke_project_builder(tmp_path / "exit2")
    _add_pin(
        project,
        "vendor-profile.json",
        _invalid_profile_document(),
        "https://vendor.example/profile-1",
    )
    with pytest.raises(SystemExit) as caught:
        _build_seam(project)
    assert caught.value.code == 2
    assert "profile_contract_invalid:" in capsys.readouterr().err
