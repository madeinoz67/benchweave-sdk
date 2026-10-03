"""The authoring contract-edit tools (I2c §4.2, SW-35/SW-36, NFR-S9):
JSON-Patch contract edits validated-before-write with digests recomputed,
whole-document preset/settings puts, and the remaining SW-35 check tools.

The load-bearing rule: a failing edit writes NOTHING (digest-compared), and
every write lands inside the loaded project's own package — portable
relative paths, no symlink traversal.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from benchweave_sdk_server import authoring
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.session import PluginSession, load_plugin_project
from benchweave_sdk_server.transport import LoopingMockHost

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "setpoint_plugin"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project_files(project: Path) -> dict[str, str]:
    package = project / "src"
    return {
        str(path.relative_to(project)): _digest(path)
        for path in sorted(package.rglob("*.json"))
    }


# --- contract_get --------------------------------------------------------------


def test_contract_get_returns_the_document_and_its_digest(seam, starter_project) -> None:
    package = starter_project / "src" / "example_plugin"
    result = authoring._contract_get(seam, "descriptor")
    assert result["content"]["id"] == "dev.example.example-plugin"
    assert result["sha256"] == _digest(package / "descriptor.json")


def test_contract_get_serves_manifest_and_catalogue(seam, starter_project) -> None:
    package = starter_project / "src" / "example_plugin"
    manifest = authoring._contract_get(seam, "manifest")
    catalogue = authoring._contract_get(seam, "binding_catalogue")
    assert manifest["sha256"] == _digest(package / "ui" / "manifest.json")
    assert catalogue["sha256"] == _digest(package / "binding-catalogue.json")


def test_contract_get_refuses_unknown_documents(seam) -> None:
    with pytest.raises(authoring.AuthoringError) as caught:
        authoring._contract_get(seam, "presentation")
    assert "presentation" in str(caught.value)


# --- contract_patch: the happy paths -------------------------------------------


def test_descriptor_patch_rewrites_the_dependent_digests(seam, starter_project) -> None:
    package = starter_project / "src" / "example_plugin"
    before = _project_files(starter_project)
    result = authoring._contract_patch(
        seam,
        "descriptor",
        [{"op": "replace", "path": "/display_name", "value": "Renamed demo"}],
    )
    assert result["sha256"] == _digest(package / "descriptor.json")
    new_digest = hashlib.sha256(
        (json.dumps(
            json.loads((package / "descriptor.json").read_text()), indent=2
        ) + "\n").encode()
    ).hexdigest()
    assert result["sha256"] == new_digest
    # The dependent documents carry the recomputed digest — they never lie
    # about bytes that no longer exist (digests recomputed on write).
    manifest = json.loads((package / "ui" / "manifest.json").read_text())
    catalogue = json.loads((package / "binding-catalogue.json").read_text())
    envelope = json.loads((package / "presentation.json").read_text())
    assert manifest["descriptor_sha256"] == new_digest
    assert catalogue["descriptor_sha256"] == new_digest
    assert envelope["descriptor_sha256"] == new_digest
    assert envelope["manifest"]["sha256"] == _digest(package / "ui" / "manifest.json")
    # Something was actually written.
    assert before["src/example_plugin/descriptor.json"] != result["sha256"]


def test_manifest_patch_recomputes_the_envelope_digest(seam, starter_project) -> None:
    package = starter_project / "src" / "example_plugin"
    result = authoring._contract_patch(
        seam,
        "manifest",
        [{"op": "replace", "path": "/pages/0/title", "value": "Live readings"}],
    )
    envelope = json.loads((package / "presentation.json").read_text())
    assert envelope["manifest"]["sha256"] == result["sha256"]
    manifest = json.loads((package / "ui" / "manifest.json").read_text())
    assert manifest["pages"][0]["title"] == "Live readings"


def test_descriptor_patch_without_presentation_writes_only_the_descriptor(
    seam_from, tmp_path
) -> None:
    """A project with no UI documents patches its descriptor through the
    descriptor checker alone; nothing else exists to recompute."""
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "bare"
    create_project(project, "example_plugin")
    bare = seam_from(project)
    result = authoring._contract_patch(
        bare,
        "descriptor",
        [{"op": "replace", "path": "/display_name", "value": "Bare"}],
    )
    package = project / "src" / "example_plugin"
    assert result["sha256"] == _digest(package / "descriptor.json")
    assert not (package / "presentation.json").exists()


# --- contract_patch: the refusal arms ------------------------------------------


def test_schema_invalid_patch_writes_nothing(seam, starter_project) -> None:
    before = _project_files(starter_project)
    with pytest.raises(authoring.AuthoringError) as caught:
        authoring._contract_patch(
            seam,
            "descriptor",
            [{"op": "remove", "path": "/identity"}],
        )
    assert caught.value.details.get("findings"), "the SDK's diagnostics must ride"
    assert _project_files(starter_project) == before


def test_malformed_patch_writes_nothing(seam, starter_project) -> None:
    before = _project_files(starter_project)
    with pytest.raises(authoring.AuthoringError) as caught:
        authoring._contract_patch(
            seam,
            "descriptor",
            [{"op": "merge", "path": "/display_name", "value": "x"}],
        )
    assert caught.value.details.get("findings")
    assert _project_files(starter_project) == before


def test_cross_document_rule_breaking_patch_writes_nothing(seam, starter_project) -> None:
    """A descriptor whose parameter set no longer matches the manifest's
    bindings fails the CROSS-document validation even though the descriptor
    alone is schema-clean — the whole result must validate or nothing
    writes."""
    before = _project_files(starter_project)
    with pytest.raises(authoring.AuthoringError) as caught:
        authoring._contract_patch(
            seam,
            "descriptor",
            [
                {
                    "op": "replace",
                    "path": "/parameters/0/name",
                    "value": "renamed_voltage",
                }
            ],
        )
    assert caught.value.details.get("findings")
    assert _project_files(starter_project) == before


def test_manifest_patch_to_an_invalid_page_writes_nothing(seam, starter_project) -> None:
    before = _project_files(starter_project)
    with pytest.raises(authoring.AuthoringError):
        authoring._contract_patch(
            seam,
            "manifest",
            [{"op": "replace", "path": "/pages/0/kind", "value": "hologram"}],
        )
    assert _project_files(starter_project) == before


def test_patch_unknown_document_refuses(seam) -> None:
    with pytest.raises(authoring.AuthoringError):
        authoring._contract_patch(seam, "envelope", [])


# --- presets and settings schemas (whole documents) ------------------------------


def _setpoint_seam(tmp_path: Path) -> tuple[StandaloneSeam, Path]:
    project = tmp_path / "setpoint"
    shutil.copytree(FIXTURE, project)
    plugin = load_plugin_project(project)
    seam = StandaloneSeam(
        PluginSession(plugin, lambda: LoopingMockHost([])),
        transport_kind="mock",
    )
    return seam, project


def test_preset_get_and_put_round_trip(tmp_path) -> None:
    seam, project = _setpoint_seam(tmp_path)
    original = authoring._preset_get(seam, "steady")
    assert original["document"]["id"] == "steady"
    edited = {**original["document"], "title": "Quieter setpoint"}
    result = authoring._preset_put(seam, "steady", edited)
    package = project / "src" / "setpoint_demo"
    assert result["sha256"] == _digest(
        package / "config" / "presets" / "steady.json"
    )
    again = authoring._preset_get(seam, "steady")
    assert again["document"]["title"] == "Quieter setpoint"


def test_preset_put_rejects_an_invalid_document(tmp_path) -> None:
    seam, project = _setpoint_seam(tmp_path)
    before = _project_files(project)
    with pytest.raises(authoring.AuthoringError) as caught:
        authoring._preset_put(seam, "steady", {"id": "steady", "settings": {}})
    assert caught.value.details.get("findings")
    assert _project_files(project) == before


def test_preset_put_rejects_traversal_ids(tmp_path) -> None:
    seam, project = _setpoint_seam(tmp_path)
    for bad in ("../escape", "nested/name", "", ".", ".."):
        with pytest.raises(authoring.AuthoringError):
            authoring._preset_put(seam, bad, {"settings": {}})
    assert not (project / "src" / "setpoint_demo" / ".." / "escape.json").exists()


def test_preset_put_re_pins_the_serving_digest(tmp_path) -> None:
    """The put is the host's OWN authorized write, not tampering: the
    serving pin moves with it, so preset_list serves the new bytes without
    a reload (the tamper-digest posture governs writes the host did not
    make)."""
    import asyncio

    seam, _project = _setpoint_seam(tmp_path)
    original = authoring._preset_get(seam, "steady")
    edited = {**original["document"], "title": "Re-pinned"}
    authoring._preset_put(seam, "steady", edited)
    rows = asyncio.run(seam.call("preset_list", {}))["presets"]
    steady = next(row for row in rows if row["id"] == "steady")
    assert steady["title"] == "Re-pinned"


def test_settings_schema_get_and_put(tmp_path) -> None:
    seam, project = _setpoint_seam(tmp_path)
    original = authoring._settings_schema_get(seam)
    assert original["document"]["title"] == "Setpoint demo settings"
    edited = {**original["document"], "title": "Wider bounds"}
    authoring._settings_schema_put(seam, edited)
    assert authoring._settings_schema_get(seam)["document"]["title"] == "Wider bounds"
    package = project / "src" / "setpoint_demo"
    assert "Wider bounds" in (package / "config" / "settings.schema.json").read_text()


def test_settings_schema_put_rejects_non_objects(tmp_path) -> None:
    seam, _project = _setpoint_seam(tmp_path)
    with pytest.raises(authoring.AuthoringError):
        authoring._settings_schema_put(seam, ["not", "an", "object"])


# --- the remaining SW-35 check tools ---------------------------------------------


def test_preset_check_reports_the_fixture_preset(tmp_path) -> None:
    seam, _project = _setpoint_seam(tmp_path)
    result = authoring._preset_check(seam, "steady")
    assert result["valid"] is True, result


def test_preset_check_names_an_unknown_preset(tmp_path) -> None:
    seam, _project = _setpoint_seam(tmp_path)
    with pytest.raises(authoring.AuthoringError):
        authoring._preset_check(seam, "nope")


def test_inventory_lists_the_loaded_project(seam, starter_project) -> None:
    rows = authoring._inventory(seam)["files"]
    paths = {row["path"] for row in rows}
    assert "src/example_plugin/descriptor.json" in paths
    for row in rows:
        assert row["sha256"] == _digest(starter_project / row["path"])


def test_standards_check_verifies_the_vendored_tree() -> None:
    result = authoring._standards_check()
    assert result["valid"] is True, result
