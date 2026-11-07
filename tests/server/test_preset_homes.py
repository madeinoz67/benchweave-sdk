"""The preset homes and the lane the document declares (issue #589 PR-6,
fold rows D12+D13): the host serves the presets the plugin actually has —
both documented homes — refuses an id duplicated across them, and applies
each preset through the lane its own document declares (the corpus action
lane when the settings schema pins a corpus action input, the parameter
lane otherwise).

The fixture pins the vendored corpus pair verbatim (the 0.2.4 profile
catalog and measurement schema) and commissions one preset against the
corpus ``configure`` action's own input schema, so the lane resolver sees
exactly what a commissioned preset of a real plugin project shows it. The
adapter is the scripted recording fake: invented identity, corpus action
URNs only, no device vocabulary beyond the corpus's own.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.scaffold import create_project
from benchweave_sdk_server.errors import SeamError
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.session import load_plugin_project, mock_plugin_session

REPO = Path(__file__).resolve().parents[2]
VENDORED = REPO / "src" / "benchweave_sdk" / "standards" / "otdp" / "0.2.4"
ADAPTER = (REPO / "tests" / "server" / "fixtures" / "scripted_invoke_adapter.py").read_bytes()

DEV = "example_device"
PACKAGE = "example_plugin"
#: The corpus's own configure action — corpus vocabulary, not a device name.
CONFIGURE = "otdp.logic_analyser.configure/1.0.0"
ARM = "otdp.logic_analyser.arm/1.0.0"
INPUT_ID = "urn:otdp:action:logic_analyser.configure:1.0.0:input"
#: A stem-shaped manifest asset id, so the collision arm can mirror it as a
#: config file stem (asset ids and stems share one namespace: preset ids).
PRESET_ID = "fast-acquisition.json"
SCHEMA_ASSET_ID = "acquisition.schema.json"


def _corpus_action(action_id: str) -> dict[str, Any]:
    catalog = json.loads((VENDORED / "device-profile-catalog.json").read_text())
    return catalog["actions"][action_id]


def _corpus_input_schema() -> dict[str, Any]:
    return _corpus_action(CONFIGURE)["input_schema"]


def _raw(document: object) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _settings() -> dict[str, Any]:
    """The commissioned configuration input (the corpus action's own
    required set; the rate and per-channel threshold ride VERBATIM)."""
    return {
        "configuration_id": "fast-capture",
        "channels": [{"channel": "bank_a", "threshold_v": 1.65}],
        "sample_rate_hz": 12_500_000.0,
        "sample_count": 65_536,
        "trigger": {"kind": "immediate"},
    }


def _effective_output() -> dict[str, Any]:
    """A result valid against the corpus action's OUTPUT schema (the
    ``effective_configuration`` read-back home)."""
    return {
        "configuration_id": "fast-capture",
        "effective_configuration": {
            "configuration_id": "fast-capture",
            "channels": [{"channel": "bank_a", "threshold_v": 1.65}],
            "sample_rate_hz": 12_500_000.0,
            "sample_count": 65_536,
            "trigger": {"kind": "immediate"},
        },
    }


def _preset_document(
    descriptor_id: str, schema_bytes: bytes, settings: dict[str, Any]
) -> dict[str, Any]:
    return {
        "contract_version": "0.4.0",
        "id": PRESET_ID,
        "title": "Fast acquisition",
        "revision": "1",
        "plugin_id": descriptor_id,
        "profile_ids": ["otdp.logic_analyser/1.0.0"],
        "supported_firmware": ["1.0.0"],
        "settings_schema": {
            "id": INPUT_ID,
            "sha256": hashlib.sha256(schema_bytes).hexdigest(),
        },
        "settings": settings,
        "provenance": {
            "author": "commissioned via check-preset (synthetic fixture)",
            "revision": "1",
            "evidence": "synthetic",
        },
    }


def _build(
    destination: Path,
    *,
    with_presentation: bool = True,
    declared_action: str = CONFIGURE,
    config_preset_stem: str | None = None,
    supported_firmware: tuple[str, ...] = ("1.0.0",),
    settings: dict[str, Any] | None = None,
) -> Path:
    """Scaffold, rewire for invoke over the corpus pins, and add the
    presentation set (one configuration target, one commissioned preset
    asset) — the derivation's own output shape written as fixture bytes."""
    create_project(destination, PACKAGE)
    package = destination / "src" / PACKAGE

    catalog_bytes = (VENDORED / "device-profile-catalog.json").read_bytes()
    measurement_bytes = (VENDORED / "otdp-measurement.schema.json").read_bytes()
    (package / "profile-catalog.json").write_bytes(catalog_bytes)
    (package / "measurement.json").write_bytes(measurement_bytes)

    descriptor = json.loads((package / "descriptor.json").read_text())
    # The commissioned firmware policy: the load-time presentation check
    # judges every target-declared preset with firmware None, and a listed
    # policy refuses an unknown firmware there — commissioned with no
    # descriptor-side list is the honest offline posture (the apply-time
    # gate still demands the established firmware be a member).
    descriptor["identity"]["firmware_policy"] = "commissioned"
    descriptor["identity"].pop("supported_firmware", None)
    descriptor["capabilities"] = ["identify", "invoke"]
    descriptor["operations"].pop("read", None)
    descriptor["operations"]["invoke"] = {
        "timeout_ms": 30000,
        "side_effect": "none",
        "retry": "never",
        "cancellable": True,
        "completion": "acknowledged",
    }
    descriptor["required_features"] = sorted(
        set(descriptor.get("required_features", []))
        | {
            "otdp.profile_actions/0.1.0",
            "otdp.measurement/0.1.0",
            "otdp.logic_analyser/1.0.0",
        }
    )
    descriptor["profiles"] = ["otdp.logic_analyser/1.0.0"]
    descriptor["channels"] = [
        {
            "id": "bank_a",
            "label": "Bank A",
            "role": "digital_input",
            "quantities": ["digital"],
            "parameter_names": [],
        }
    ]
    descriptor["actions"] = {
        declared_action: {
            "binding": {"kind": "adapter", "key": declared_action},
            "input_constraints": {},
            "timeout_ms": 30000,
            "side_effect": "state_change",
            "cancellable": True,
            "retry": "never",
        }
    }
    descriptor["contracts"] = [
        # The corpus example's own pin convention (urn:otdp: ids): the
        # presentation's pinned-document merge admits only plugin-authored
        # pins, so the vendored pair joins the invoke resolution without
        # shadowing the served corpus (#556).
        {
            "id": "urn:otdp:profile-catalog:0.2.4",
            "path": "profile-catalog.json",
            "sha256": hashlib.sha256(catalog_bytes).hexdigest(),
        },
        {
            "id": "urn:otdp:measurement:0.2.4",
            "path": "measurement.json",
            "sha256": hashlib.sha256(measurement_bytes).hexdigest(),
        },
    ]
    descriptor_raw = _raw(descriptor)
    (package / "descriptor.json").write_bytes(descriptor_raw)
    (package / "adapter.py").write_bytes(ADAPTER)

    if with_presentation:
        schema_bytes = _raw(_corpus_input_schema())
        settings = settings if settings is not None else _settings()
        preset = _preset_document(descriptor["id"], schema_bytes, settings)
        preset["supported_firmware"] = list(supported_firmware)
        preset_bytes = _raw(preset)
        (package / "ui" / "settings").mkdir(parents=True, exist_ok=True)
        (package / "ui" / "presets").mkdir(parents=True, exist_ok=True)
        (package / "ui" / "settings" / "acquisition.schema.json").write_bytes(
            schema_bytes
        )
        (package / "ui" / "presets" / PRESET_ID).write_bytes(preset_bytes)
        manifest = {
            "contract_version": "0.4.0",
            "plugin_id": descriptor["id"],
            "descriptor_sha256": hashlib.sha256(descriptor_raw).hexdigest(),
            "assets": [
                {
                    "id": SCHEMA_ASSET_ID,
                    "path": "settings/acquisition.schema.json",
                    "sha256": hashlib.sha256(schema_bytes).hexdigest(),
                },
                {
                    "id": PRESET_ID,
                    "path": f"presets/{PRESET_ID}",
                    "sha256": hashlib.sha256(preset_bytes).hexdigest(),
                },
            ],
            "bindings": [
                {
                    "id": "acquisition",
                    "kind": "configuration",
                    "target_id": "acquisition",
                    "preset_ids": [PRESET_ID],
                }
            ],
            "pages": [
                {
                    "id": "acquisition",
                    "title": "Acquisition",
                    "kind": "configuration",
                    "bindings": ["acquisition"],
                    "required": True,
                }
            ],
        }
        manifest_raw = _raw(manifest)
        (package / "ui" / "manifest.json").write_bytes(manifest_raw)
        (package / "presentation.json").write_bytes(
            _raw(
                {
                    "contract_version": "0.4.0",
                    "descriptor_sha256": hashlib.sha256(descriptor_raw).hexdigest(),
                    "resource_root": "ui",
                    "manifest": {
                        "path": "manifest.json",
                        "sha256": hashlib.sha256(manifest_raw).hexdigest(),
                    },
                }
            )
        )
        (package / "binding-catalogue.json").write_bytes(
            _raw(
                {
                    "contract_version": "0.4.0",
                    "descriptor_sha256": hashlib.sha256(descriptor_raw).hexdigest(),
                    "targets": [
                        {
                            "id": "acquisition",
                            "kind": "configuration",
                            "action_id": declared_action,
                            "profile_ids": ["otdp.logic_analyser/1.0.0"],
                            "input_schema_id": (
                                _corpus_action(declared_action)["input_schema"]["$id"]
                            ),
                            "schema_asset_id": SCHEMA_ASSET_ID,
                            "preset_asset_ids": [PRESET_ID],
                        }
                    ],
                }
            )
        )
    if config_preset_stem is not None:
        # The config home (A2/A3/A9): a commissioned preset against the SAME
        # corpus input schema, pinned by config/settings.schema.json.
        schema_bytes = _raw(_corpus_input_schema())
        (package / "config").mkdir(parents=True, exist_ok=True)
        (package / "config" / "settings.schema.json").write_bytes(schema_bytes)
        (package / "config" / "presets").mkdir(parents=True, exist_ok=True)
        preset = _preset_document(descriptor["id"], schema_bytes, _settings())
        preset["supported_firmware"] = list(supported_firmware)
        (package / "config" / "presets" / f"{config_preset_stem}.json").write_bytes(
            _raw(preset)
        )
    return destination


def _seam(project: Path, **kwargs: Any) -> tuple[StandaloneSeam, Any]:
    """Load, fish the scripted adapter, connect (the arms run connected)."""
    plugin = load_plugin_project(Path(project))
    adapter = sys.modules[f"{plugin.package}.adapter"]
    seam = StandaloneSeam(mock_plugin_session(plugin), transport_kind="mock", **kwargs)
    call(seam, "device_connect", {"device_id": DEV})
    return seam, adapter


def call(seam: StandaloneSeam, operation: str, arguments: dict[str, Any] | None = None) -> Any:
    return asyncio.run(seam.call(operation, arguments or {}))


def apply_args(preset_id: str = PRESET_ID) -> dict[str, Any]:
    return {"device_id": DEV, "preset_id": preset_id}


# --- A1: the ui home is served ---------------------------------------------------


def test_a1_manifest_preset_is_served_from_the_ui_home(tmp_path: Path) -> None:
    project = _build(tmp_path / "ui-only")
    seam, adapter = _seam(project)
    assert adapter.CALLS == ["identify"], "no device op but identify"
    rows = call(seam, "preset_list")["presets"]
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["id"] == PRESET_ID
    assert row["home"] == "ui"
    manifest = json.loads(
        (project / "src" / PACKAGE / "ui" / "manifest.json").read_text()
    )
    pinned = next(a for a in manifest["assets"] if a["id"] == PRESET_ID)
    assert row["sha256"] == pinned["sha256"], "the served digest is the manifest pin"
    disk = (project / "src" / PACKAGE / "ui" / "presets" / PRESET_ID).read_bytes()
    assert hashlib.sha256(disk).hexdigest() == row["sha256"]


# --- A2: the config home keeps its rows, now carrying home ------------------------


def test_a2_config_home_rows_carry_home_config(tmp_path: Path) -> None:
    from benchweave_sdk_server.session import PluginSession, mock_exchanges
    from benchweave_sdk_server.transport import LoopingMockHost

    fixture = Path(__file__).resolve().parent.parent / "fixtures" / "setpoint_plugin"
    loaded = load_plugin_project(fixture)
    seam = StandaloneSeam(
        PluginSession(loaded, lambda: LoopingMockHost(mock_exchanges(loaded))),
        transport_kind="mock",
    )
    rows = call(seam, "preset_list")["presets"]
    assert [row["id"] for row in rows] == ["steady"]
    assert rows[0]["home"] == "config"
    raw = (
        fixture / "src" / "setpoint_demo" / "config" / "presets" / "steady.json"
    ).read_bytes()
    assert rows[0]["sha256"] == hashlib.sha256(raw).hexdigest()


# --- A3: the collision refuses construction and reload-before-swap ----------------


def test_a3_same_id_in_both_homes_refuses_construction_and_reload(
    tmp_path: Path,
) -> None:
    project = _build(tmp_path / "collide", config_preset_stem=PRESET_ID)
    plugin = load_plugin_project(project)
    with pytest.raises(ValueError) as caught:
        StandaloneSeam(mock_plugin_session(plugin), transport_kind="mock")
    message = str(caught.value)
    assert message.startswith("standalone_preset_home_conflict:")
    assert PRESET_ID in message
    assert "config/presets" in message and "manifest" in message, message

    # The reload half: the conflicted INCOMING plugin refuses BEFORE the
    # swap and the previous session keeps serving.
    clean = _build(tmp_path / "clean")
    seam, adapter = _seam(clean)
    before = call(seam, "host_info")["plugin"]["descriptor_sha256"]
    # Turn the clean project into the conflicted one, in place.
    package = clean / "src" / PACKAGE
    schema_bytes = _raw(_corpus_input_schema())
    (package / "config").mkdir(exist_ok=True)
    (package / "config" / "settings.schema.json").write_bytes(schema_bytes)
    (package / "config" / "presets").mkdir(parents=True, exist_ok=True)
    preset = _preset_document(
        json.loads((package / "descriptor.json").read_text())["id"],
        schema_bytes,
        _settings(),
    )
    (package / "config" / "presets" / f"{PRESET_ID}.json").write_bytes(_raw(preset))
    with pytest.raises(SeamError) as reload_caught:
        asyncio.run(seam.reload_plugin(source="test"))
    assert reload_caught.value.code == "invalid_request"
    assert "standalone_preset_home_conflict:" in reload_caught.value.message
    assert reload_caught.value.message.startswith("reload refused")
    # The previous session keeps serving its own (single, ui-home) row.
    rows = call(seam, "preset_list")["presets"]
    assert [row["id"] for row in rows] == [PRESET_ID]
    assert rows[0]["home"] == "ui"
    assert call(seam, "host_info")["plugin"]["descriptor_sha256"] == before


# --- A4: drifted ui-lane bytes refuse list and apply ------------------------------


def test_a4_drifted_ui_preset_refuses_list_and_apply(tmp_path: Path) -> None:
    project = _build(tmp_path / "drift")
    seam, adapter = _seam(project)
    target = project / "src" / PACKAGE / "ui" / "presets" / PRESET_ID
    document = json.loads(target.read_text())
    document["title"] = "tampered while running"
    target.write_text(json.dumps(document, indent=2))
    with pytest.raises(SeamError) as listed:
        call(seam, "preset_list")
    assert listed.value.code == "invalid_request"
    assert listed.value.details.get("finding") == "digest_mismatch"
    adapter.CALLS.clear()
    with pytest.raises(SeamError) as applied:
        call(seam, "preset_apply", apply_args())
    assert applied.value.code == "invalid_request"
    assert applied.value.details.get("finding") == "digest_mismatch"
    assert "invoke" not in adapter.CALLS, "no dispatch may occur on drift"


# --- A5+A6: the commissioned preset applies through the action lane ----------------


def _connected_action_lane(tmp_path: Path, name: str) -> tuple[Any, dict[str, Any], Any]:
    project = _build(tmp_path / name)
    seam, adapter = _seam(project)
    adapter.SCRIPT["invoke"] = _effective_output()
    return adapter, _settings(), seam


def test_a5_commissioned_preset_applies_through_the_action_lane(
    tmp_path: Path,
) -> None:
    adapter, settings, seam = _connected_action_lane(tmp_path, "action-lane")
    result = call(seam, "preset_apply", apply_args())
    assert result["home"] == "ui"
    assert result["action_id"] == CONFIGURE
    assert result["invoke_result"] == {
        "action_id": CONFIGURE,
        "result": _effective_output(),
    }
    assert "applied" not in result, "one lane fills one shape, never both"
    assert [
        {"action_id": CONFIGURE, "input": settings}
    ] == adapter.INVOKE_ARGUMENTS, adapter.INVOKE_ARGUMENTS
    assert "write" not in adapter.CALLS, "the action lane writes no parameters"
    event = [
        row
        for row in call(seam, "events_get", {"after_id": 0})["events"]
        if row["kind"] == "preset_apply"
    ][-1]
    assert event["data"]["home"] == "ui"
    assert event["data"]["action_id"] == CONFIGURE


def test_a6_input_values_reach_the_adapter_verbatim(tmp_path: Path) -> None:
    """The genericity arm: every input value — the rate and the per-channel
    threshold among them — reaches the adapter VERBATIM through a host that
    nowhere names them (corpus URNs and invented ids only in the fixture)."""
    adapter, settings, seam = _connected_action_lane(tmp_path, "verbatim")
    call(seam, "preset_apply", apply_args())
    dispatched = adapter.INVOKE_ARGUMENTS[0]
    assert dispatched["input"] == settings
    assert dispatched["input"]["sample_rate_hz"] == 12_500_000.0
    assert dispatched["input"]["channels"][0]["threshold_v"] == 1.65


# --- A8: the validator's findings refuse a drifted schema asset --------------------


def test_a8_schema_asset_drift_refuses_with_validator_findings(
    tmp_path: Path,
) -> None:
    """The load-time check binds the preset's pin to the target's schema
    asset, so the pristine-invalid case cannot pass a load. The reachable
    drift is the asset's BYTES after construction: the same shared
    validator answers with its findings and nothing dispatches."""
    project = _build(tmp_path / "schema-drift")
    seam, adapter = _seam(project)
    target = project / "src" / PACKAGE / "ui" / "settings" / "acquisition.schema.json"
    target.write_text(
        json.dumps(
            {"$id": INPUT_ID, "$schema": "https://json-schema.org/draft/2020-12/schema",
             "type": "object", "properties": {}, "additionalProperties": False},
            indent=2,
        )
        + "\n"
    )
    adapter.CALLS.clear()
    with pytest.raises(SeamError) as caught:
        call(seam, "preset_apply", apply_args())
    assert caught.value.code == "invalid_request"
    codes = {row["code"] for row in caught.value.details.get("findings", [])}
    assert "digest_mismatch" in codes, caught.value.details
    assert "invoke" not in adapter.CALLS


# --- A9: the composition reuses invoke's I2 gate ----------------------------------


def test_a9_undeclared_action_refuses_with_invoke_i2_shape(tmp_path: Path) -> None:
    """A preset pinning a corpus action's input schema for an action the
    descriptor does NOT declare: the refusal is invoke's own I2 message
    naming the action (the lane composes the gate, it does not copy it)."""
    project = _build(
        tmp_path / "undeclared",
        with_presentation=False,
        declared_action=ARM,
        config_preset_stem="rate",
    )
    seam, adapter = _seam(project)
    adapter.CALLS.clear()
    with pytest.raises(SeamError) as caught:
        call(seam, "preset_apply", apply_args("rate"))
    assert caught.value.code == "invalid_request"
    assert CONFIGURE in caught.value.message
    assert "is not declared by the descriptor actions map" in caught.value.message
    assert "invoke" not in adapter.CALLS


# --- A10: the firmware gate runs before any dispatch on the action lane ------------


def test_a10_firmware_gate_refuses_before_action_lane_dispatch(
    tmp_path: Path,
) -> None:
    project = _build(tmp_path / "firmware", supported_firmware=("9.9.9",))
    seam, adapter = _seam(project)
    adapter.SCRIPT["invoke"] = _effective_output()
    adapter.CALLS.clear()
    with pytest.raises(SeamError) as caught:
        call(seam, "preset_apply", apply_args())
    assert caught.value.code == "conflict"
    assert "invoke" not in adapter.CALLS, "the gate fires before any dispatch"


# --- A11: the deadlock falsifier — the action lane completes under the mutex -------


def test_a11_action_lane_apply_completes_under_the_op_mutex(tmp_path: Path) -> None:
    """The apply span holds ``_op_mutex`` throughout; ``asyncio.Lock`` is
    not reentrant, so the composition MUST call the lock-free invoke core.
    The arm's own completion inside the timeout IS the control: routing the
    action lane through the locked handler hangs it."""
    project = _build(tmp_path / "deadlock")
    seam, adapter = _seam(project)
    adapter.SCRIPT["invoke"] = _effective_output()

    async def scenario() -> dict[str, Any]:
        return await asyncio.wait_for(
            seam.call("preset_apply", apply_args()), timeout=5.0
        )

    result = asyncio.run(scenario())
    assert result["action_id"] == CONFIGURE


# --- the unknown id names both homes searched -------------------------------------


def test_unknown_preset_names_both_homes_searched(tmp_path: Path) -> None:
    project = _build(tmp_path / "unknown")
    seam, adapter = _seam(project)
    with pytest.raises(SeamError) as caught:
        call(seam, "preset_apply", apply_args("missing"))
    assert caught.value.code == "not_found"
    assert "config/presets/" in caught.value.message
    assert "presentation manifest" in caught.value.message


# --- the authoring write cannot create the dual-home state ------------------------


def test_authoring_put_refuses_a_manifest_preset_id(tmp_path: Path) -> None:
    """The construction check governs loads; the runtime writer must obey
    the same one-authoritative-copy rule or a ``preset_put`` recreates the
    collision while the host runs. Refused before any byte is written."""
    from benchweave_sdk_server import authoring
    from benchweave_sdk_server.authoring import AuthoringError

    project = _build(tmp_path / "authoring")
    seam, adapter = _seam(project)
    with pytest.raises(AuthoringError) as caught:
        authoring._preset_put(seam, PRESET_ID, {"settings": {}})
    assert str(caught.value).startswith("standalone_preset_home_conflict:")
    assert not (
        project / "src" / PACKAGE / "config" / "presets" / f"{PRESET_ID}.json"
    ).exists(), "nothing was written"
    # The manifest's own row keeps serving.
    rows = call(seam, "preset_list")["presets"]
    assert [row["id"] for row in rows] == [PRESET_ID]
