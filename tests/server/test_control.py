"""The staged/apply and preset control surface (I2b §4.1, gate I2-S).

The proof plugin is ``tests/fixtures/setpoint_plugin`` — a hand-authored,
scaffold-shaped synthetic plugin declaring one ``rw`` setpoint parameter with
range + ``max_age_ms``, a write exchange in ``vectors.json`` and one preset
under ``config/presets/``. Its scripted host is write-through (a write
changes what the next read serves), so apply's read-back can only ever come
from the device — the no-optimistic-copy rule's strongest witness.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk.testing import ConformanceError
from benchweave_sdk_server import presentation as host_presentation
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.session import PluginSession, load_plugin_project
from benchweave_sdk_server.transport import LoopingMockHost
from benchweave_sdk_server.web import build_app

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "setpoint_plugin"
DEV = "setpoint_dev"
PARAM = "current_limit"


class VerbRecorder:
    """Test-only adapter wrapper: records every ``execute()`` verb."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.verbs: list[str] = []

    async def open(self, descriptor: Any, services: Any, context: Any) -> None:
        await self._inner.open(descriptor, services, context)

    async def execute(self, request: Any, context: Any) -> Any:
        self.verbs.append(str(request.get("verb")))
        return await self._inner.execute(request, context)

    async def next_event(self, subscription_id: Any, context: Any) -> Any:
        return await self._inner.next_event(subscription_id, context)

    async def close(self, context: Any) -> None:
        await self._inner.close(context)


class SetpointHost(LoopingMockHost):
    """The fixture's write-through scripted device.

    Serves exactly the exchanges ``vectors.json`` declares (the identity,
    read and write frames are the declared bytes; a frame nothing declared
    raises, preserving the exact-match discipline), with one state rule the
    evidence file pins: the write exchange accepts the setpoint, and reads
    serve it afterwards. ``reject_writes`` answers the declared write frame
    with the protocol's ERR line instead — the device-rejection arm.
    """

    def __init__(self, *, reject_writes: bool = False) -> None:
        super().__init__([], establishment=0)
        self.reject_writes = reject_writes
        self.limit = 2.0
        self.frames: list[bytes] = []

    async def transfer(self, transaction: Any, context: Any) -> dict[str, Any]:
        self._check(context)
        if not getattr(context, "dispatched", False):
            raise ConformanceError("Transmission needs a dispatch marker")
        data = bytes(transaction.get("data", b""))
        self.frames.append(data)
        if data == b"ID?\n":
            return {"data": b"BenchWeave Labs,setpoint-demo,SIM-SP1,1.0.0\n"}
        if data == b"LIM?\n":
            return {"data": f"{self.limit:g}\n".encode("ascii")}
        if data.startswith(b"LIM ") and data.endswith(b"\n"):
            if self.reject_writes:
                return {"data": b"ERR\n"}
            self.limit = float(data[4:-1].decode("ascii"))
            return {"data": b"OK\n"}
        raise ConformanceError(f"unscripted exchange: {data!r}")


def _policy() -> GuardPolicy:
    return GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )


def _recorder_seam(
    project: Path = FIXTURE, *, reject_writes: bool = False
) -> tuple[StandaloneSeam, VerbRecorder]:
    plugin = load_plugin_project(project)
    recorder = VerbRecorder(plugin.adapter_factory())
    seam = StandaloneSeam(
        PluginSession(
            replace(plugin, adapter_factory=lambda: recorder),
            lambda: SetpointHost(reject_writes=reject_writes),
        ),
        transport_kind="mock",
    )
    return seam, recorder


def _client(seam: StandaloneSeam) -> tuple[TestClient, GuardPolicy]:
    policy = _policy()
    return TestClient(build_app(seam, policy=policy), base_url="http://127.0.0.1:8477"), policy


def _csrf(client: TestClient) -> str:
    body = client.get(f"/devices/{DEV}").text
    marker = 'hx-headers=\'{"X-CSRF-Token": "'
    return body.split(marker, 1)[1].split('"', 1)[0]


@pytest.fixture()
def connected() -> Iterator[tuple[TestClient, StandaloneSeam, VerbRecorder, GuardPolicy]]:
    seam, recorder = _recorder_seam()
    client, policy = _client(seam)
    with client:
        client.post(
            f"/devices/{DEV}/connect", headers={"x-csrf-token": _csrf(client)}
        )
        yield client, seam, recorder, policy


def _repin_presentation(project: Path) -> None:
    """Re-point the presentation documents at a doctored descriptor: the
    envelope, manifest and binding catalogue each pin the descriptor's
    sha256, so a copy whose descriptor changed must re-pin all three."""
    import hashlib as _hashlib

    pkg = project / "src" / "setpoint_demo"
    descriptor_raw = (pkg / "descriptor.json").read_bytes()
    descriptor_hash = _hashlib.sha256(descriptor_raw).hexdigest()
    manifest = json.loads((pkg / "ui" / "manifest.json").read_text())
    manifest["descriptor_sha256"] = descriptor_hash
    manifest_raw = (json.dumps(manifest, indent=2) + "\n").encode()
    (pkg / "ui" / "manifest.json").write_bytes(manifest_raw)
    envelope_pin = {
        "manifest": {
            "path": "manifest.json",
            "sha256": _hashlib.sha256(manifest_raw).hexdigest(),
        }
    }
    for name, mutate in (
        ("presentation.json", envelope_pin),
        ("binding-catalogue.json", {}),
    ):
        document = json.loads((pkg / name).read_text())
        document["descriptor_sha256"] = descriptor_hash
        document.update(mutate)
        (pkg / name).write_text(json.dumps(document, indent=2) + "\n")


def _stage(seam: StandaloneSeam, value: Any = 2.5, parameter: str = PARAM) -> Any:
    import asyncio

    return asyncio.run(
        seam.call(
            "parameter_stage",
            {"device_id": DEV, "parameter": parameter, "value": value},
        )
    )


# --- staging: host state, validated from the descriptor, no I/O -------------


def test_stage_performs_no_io_and_reports_the_staging_order(
    connected: tuple[TestClient, StandaloneSeam, VerbRecorder, GuardPolicy],
) -> None:
    _client_unused, seam, recorder, _token = connected
    before = list(recorder.verbs)
    result = _stage(seam, 2.5)
    assert recorder.verbs == before, "staging performed device I/O"
    assert result["staged"] == [PARAM]
    assert result["value"] == 2.5


def test_stage_leaves_the_tile_at_the_device_value(connected) -> None:
    """SW-23/E.3: the staged value never reaches the tile — the tile keeps
    serving the device read until apply's read-back changes it."""
    client, seam, _recorder, _token = connected
    _stage(seam, 2.5)
    page = client.get("/pages/readings").text
    tile = page.split('bw-reading__value">', 1)[1].split("<", 1)[0]
    assert tile.startswith("2.0"), "the tile moved to the staged value"
    assert "Set 2.0" in page, "set evidence left the device read"


def test_the_optimistic_control_hook_is_real(connected) -> None:
    """The no-optimistic-copy control (I2-S): the test hook renders the
    staged echo into the tile — with it on, the tile DOES move, proving the
    stage arm above discriminates an optimistic renderer from the honest
    one (the hook is the mechanism through which that arm can be fooled)."""
    client, seam, _recorder, _token = connected
    _stage(seam, 2.5)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(host_presentation, "STAGED_ECHO_TILES", True)
        page = client.get("/pages/readings").text
    tile = page.split('bw-reading__value">', 1)[1].split("<", 1)[0]
    assert tile.startswith("2.5"), "the control hook did not stage-echo the tile"


def test_stage_refuses_readonly_unknown_and_out_of_range(
    starter_project: Path,
) -> None:
    """The starter's ``voltage`` is ro; the fixture has no ``nope``; 5.5 is
    outside the declared [0.0, 5.0]; a boolean is not the declared float."""
    import asyncio

    from benchweave_sdk_server.session import mock_exchanges

    starter = load_plugin_project(starter_project)
    starter_seam = StandaloneSeam(
        PluginSession(
            starter, lambda: LoopingMockHost(mock_exchanges(starter))
        ),
        transport_kind="mock",
    )
    fixture_seam, _recorder = _recorder_seam()

    for seam, arguments in (
        (starter_seam, {"device_id": "example_device", "parameter": "voltage",
                        "value": 1.0}),
        (fixture_seam, {"device_id": DEV, "parameter": "nope", "value": 1.0}),
        (fixture_seam, {"device_id": DEV, "parameter": PARAM, "value": 5.5}),
        (fixture_seam, {"device_id": DEV, "parameter": PARAM, "value": True}),
    ):
        with pytest.raises(Exception) as caught:
            asyncio.run(seam.call("parameter_stage", arguments))
        error = caught.value
        assert getattr(error, "code", "") == "invalid_request", arguments
        assert arguments["parameter"] in error.message, (
            "the refusal must name the parameter"
        )


# --- apply: write under the declared verb bound, then read back only -------


def test_apply_writes_then_reads_and_clears_staging(
    connected: tuple[TestClient, StandaloneSeam, VerbRecorder, GuardPolicy],
) -> None:
    import asyncio

    client_unused, seam, recorder, _token = connected
    _stage(seam, 2.5)
    before = list(recorder.verbs)
    result = asyncio.run(seam.call("parameter_apply", {"device_id": DEV}))
    assert recorder.verbs[len(before):] == ["write", "read"], recorder.verbs
    assert result["applied"][0]["parameter"] == PARAM
    assert result["applied"][0]["value"] == 2.5, "the value must be the read-back"
    # The staging map cleared: a second apply refuses.
    with pytest.raises(Exception) as caught:
        asyncio.run(seam.call("parameter_apply", {"device_id": DEV}))
    assert caught.value.code == "invalid_request"


def test_the_tile_updates_from_the_read_back_only(connected) -> None:
    client, seam, _recorder, policy = connected
    _stage(seam, 2.5)
    client.post(
        "/pages/readings/apply", headers={"x-csrf-token": policy.csrf_token}
    )
    page = client.get("/pages/readings").text
    tile = page.split('bw-reading__value">', 1)[1].split("<", 1)[0]
    assert tile.startswith("2.5"), "the tile did not take the read-back value"
    assert "Set 2.5" in page, "set evidence did not follow the read-back"


def test_device_rejection_renders_the_refusal_and_retains_staged() -> None:
    seam, recorder = _recorder_seam(reject_writes=True)
    client, policy = _client(seam)
    with client:
        client.post(
            f"/devices/{DEV}/connect", headers={"x-csrf-token": _csrf(client)}
        )
        _stage(seam, 2.5)
        response = client.post(
            "/v1/parameter_apply",
            headers={"authorization": f"Bearer {policy.bearer_token}"},
            json={"device_id": DEV},
        )
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "conflict"
        assert error["details"]["adapter"]["code"] == "DEVICE_REJECTED"
        # Retained: the page still stages the value in its input.
        page = client.get("/pages/readings").text
        assert 'value="2.5"' in page, "the staged value was silently discarded"


def test_apply_with_nothing_staged_is_invalid_request(connected) -> None:
    client, _seam, _recorder, policy = connected
    response = client.post(
        "/v1/parameter_apply",
        headers={"authorization": f"Bearer {policy.bearer_token}"},
        json={"device_id": DEV},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_apply_refuses_an_undeclared_write_verb_without_transmitting(
    tmp_path: Path,
) -> None:
    """``standalone_verb_unbounded``: a descriptor with an ``rw`` parameter
    but no declared ``write`` operation policy refuses BEFORE any write
    frame — the recorder must not hear a write."""
    import asyncio

    project = tmp_path / "unbounded"
    shutil.copytree(FIXTURE, project)
    descriptor_path = project / "src" / "setpoint_demo" / "descriptor.json"
    document = json.loads(descriptor_path.read_text())
    document["capabilities"].remove("write")
    del document["operations"]["write"]
    descriptor_path.write_text(json.dumps(document))
    _repin_presentation(project)

    seam, recorder = _recorder_seam(project)
    asyncio.run(seam.call("device_connect", {"device_id": DEV}))
    _stage(seam, 2.5)
    before = list(recorder.verbs)
    with pytest.raises(Exception) as caught:
        asyncio.run(seam.call("parameter_apply", {"device_id": DEV}))
    assert caught.value.code == "unavailable"
    assert "standalone_verb_unbounded" in caught.value.message
    assert recorder.verbs == before, "a write was transmitted on a refusal"


# --- no write on load, re-proven over the control surface -------------------


def test_no_write_on_page_load_over_the_setpoint_plugin() -> None:
    """The #309-B proof re-run over the writable plugin: pages, polls and
    preset listing leave the verbs read-side (staged UI is host state)."""
    seam, recorder = _recorder_seam()
    client, _policy_ = _client(seam)
    with client:
        client.post(
            f"/devices/{DEV}/connect", headers={"x-csrf-token": _csrf(client)}
        )
        client.get("/")
        client.get(f"/devices/{DEV}")
        client.get("/pages/readings")
        for _ in range(2):
            client.get("/pages/readings/readings")
    assert set(recorder.verbs) == {"identify", "read"}, recorder.verbs


def test_the_stage_and_apply_posts_are_csrf_guarded(connected) -> None:
    client, _seam, _recorder, _token = connected
    assert client.post("/pages/readings/stage", data={}).status_code == 403
    assert client.post("/pages/readings/apply").status_code == 403


# --- presets ----------------------------------------------------------------


def test_preset_list_names_the_declared_preset_with_its_digest(
    connected: tuple[TestClient, StandaloneSeam, VerbRecorder, GuardPolicy],
) -> None:
    import asyncio

    _client_unused, seam, _recorder, _token = connected
    result = asyncio.run(seam.call("preset_list", {}))
    rows = {row["id"]: row for row in result["presets"]}
    assert set(rows) == {"steady"}
    raw = (FIXTURE / "src" / "setpoint_demo" / "config" / "presets" / "steady.json").read_bytes()
    assert rows["steady"]["sha256"] == hashlib.sha256(raw).hexdigest()


def test_preset_apply_stages_and_applies_with_read_backs(
    connected: tuple[TestClient, StandaloneSeam, VerbRecorder, GuardPolicy],
) -> None:
    import asyncio

    _client_unused, seam, recorder, _token = connected
    before = list(recorder.verbs)
    result = asyncio.run(
        seam.call("preset_apply", {"device_id": DEV, "preset_id": "steady"})
    )
    assert recorder.verbs[len(before):] == ["write", "read"], recorder.verbs
    assert result["preset_id"] == "steady"
    assert result["applied"][0]["value"] == 2.5


def test_preset_firmware_mismatch_refuses_before_any_write(
    tmp_path: Path,
) -> None:
    """The firmware gate: a preset declaring only 9.9.9 against the
    established 1.0.0 refuses ``conflict`` naming both — and the recorder
    hears no write verb at all."""
    import asyncio

    project = tmp_path / "mismatch"
    shutil.copytree(FIXTURE, project)
    preset_path = project / "src" / "setpoint_demo" / "config" / "presets" / "steady.json"
    preset = json.loads(preset_path.read_text())
    preset["supported_firmware"] = ["9.9.9"]
    preset_path.write_text(json.dumps(preset))

    seam, recorder = _recorder_seam(project)
    asyncio.run(seam.call("device_connect", {"device_id": DEV}))
    before = list(recorder.verbs)
    with pytest.raises(Exception) as caught:
        asyncio.run(
            seam.call("preset_apply", {"device_id": DEV, "preset_id": "steady"})
        )
    assert caught.value.code == "conflict"
    assert "1.0.0" in caught.value.message and "9.9.9" in caught.value.message
    assert recorder.verbs == before, "a write preceded the firmware gate"


def test_preset_apply_refuses_before_identity_is_established(
    tmp_path: Path,
) -> None:
    """No identify capability ⇒ no established identity ⇒ the firmware gate
    cannot run, so preset apply refuses before anything is staged."""
    import asyncio

    seam, _recorder = _recorder_seam()
    asyncio.run(seam.call("device_connect", {"device_id": DEV}))
    # A real transport establishes identity at connect; an identity that
    # carries no firmware cannot run the gate — set the established
    # identity directly (the gate consumes whatever is established).
    seam.session.identity = {"manufacturer": "BenchWeave Labs", "firmware": ""}
    with pytest.raises(Exception) as caught:
        asyncio.run(
            seam.call("preset_apply", {"device_id": DEV, "preset_id": "steady"})
        )
    assert caught.value.code == "not_ready"


def test_preset_apply_refuses_a_drifted_preset_file(tmp_path: Path) -> None:
    """CON-1 at host scale: the seam pins every preset digest at
    construction; bytes tampered while the host runs refuse at apply."""
    import asyncio

    project = tmp_path / "drifted"
    shutil.copytree(FIXTURE, project)
    preset_path = project / "src" / "setpoint_demo" / "config" / "presets" / "steady.json"

    seam, _recorder = _recorder_seam(project)
    asyncio.run(seam.call("device_connect", {"device_id": DEV}))
    listed = asyncio.run(seam.call("preset_list", {}))
    digest = {row["id"]: row["sha256"] for row in listed["presets"]}["steady"]
    assert digest, "the listing carries the pinned digest"

    preset = json.loads(preset_path.read_text())
    preset["title"] = "tampered while running"
    preset_path.write_text(json.dumps(preset))

    with pytest.raises(Exception) as caught:
        asyncio.run(
            seam.call("preset_apply", {"device_id": DEV, "preset_id": "steady"})
        )
    assert caught.value.code == "invalid_request"
    assert "drifted" in caught.value.message


def test_preset_settings_must_name_writable_parameters(tmp_path: Path) -> None:
    """A preset whose settings name a parameter the descriptor does not
    declare writable refuses by name at the staging gate."""
    import asyncio

    project = tmp_path / "readonly-setting"
    shutil.copytree(FIXTURE, project)
    pkg = project / "src" / "setpoint_demo"
    schema_path = pkg / "config" / "settings.schema.json"
    schema = json.loads(schema_path.read_text())
    schema["properties"] = {"voltage": {"type": "number"}}
    schema["required"] = ["voltage"]
    schema_bytes = (json.dumps(schema, indent=2) + "\n").encode()
    schema_path.write_bytes(schema_bytes)
    preset_path = pkg / "config" / "presets" / "steady.json"
    preset = json.loads(preset_path.read_text())
    preset["settings"] = {"voltage": 1.0}
    preset["settings_schema"]["sha256"] = hashlib.sha256(schema_bytes).hexdigest()
    preset_path.write_text(json.dumps(preset))

    seam, _recorder = _recorder_seam(project)
    asyncio.run(seam.call("device_connect", {"device_id": DEV}))
    with pytest.raises(Exception) as caught:
        asyncio.run(
            seam.call("preset_apply", {"device_id": DEV, "preset_id": "steady"})
        )
    assert caught.value.code == "invalid_request"
    assert "voltage" in caught.value.message


def test_preset_selection_in_the_ui_performs_no_io(
    connected: tuple[TestClient, StandaloneSeam, VerbRecorder, GuardPolicy],
) -> None:
    client, _seam, recorder, _token = connected
    before = list(recorder.verbs)
    page = client.get(f"/devices/{DEV}").text
    assert "steady" in page, "the preset form did not list the preset"
    assert recorder.verbs == before


# --- the refute folds (RED-first; rulings from the review battery) ----------

SECOND_PARAMETER = {
    "name": "drive_level",
    "description": "Synthetic drive-level setpoint (second writable surface)",
    "type": "float",
    "access": "rw",
    "semantic": "setpoint",
    "unit": "V",
    "range": [0.0, 1.0],
    "hazard_class": "unknown",
    "binding": {"kind": "adapter", "key": "drive_level"},
    "read_policy": {"max_age_ms": 2000, "destructive": False},
    "write_policy": {
        "effect": "setting",
        "completion": "readback",
        "retry": "never",
        "verification_parameter": "drive_level",
        "settling_timeout_ms": 100,
    },
}


def test_preset_apply_scopes_to_its_own_settings(tmp_path: Path) -> None:
    """FOLD-A (the converged ruling): preset_apply writes exactly the
    preset's settings. An abandoned staged write is RETAINED, never flushed
    under the preset action — the catalogue's one-row-per-setting promise
    stays true, and the same condition that guards I2c's reload is a guard
    here, not a silent flush."""
    import asyncio

    project = tmp_path / "twoparam"
    shutil.copytree(FIXTURE, project)
    descriptor_path = project / "src" / "setpoint_demo" / "descriptor.json"
    document = json.loads(descriptor_path.read_text())
    document["parameters"].append(SECOND_PARAMETER)
    descriptor_path.write_text(json.dumps(document))
    _repin_presentation(project)

    seam, recorder = _recorder_seam(project)
    asyncio.run(seam.call("device_connect", {"device_id": DEV}))
    _stage(seam, 0.5, parameter="drive_level")
    before = list(recorder.verbs)
    result = asyncio.run(
        seam.call("preset_apply", {"device_id": DEV, "preset_id": "steady"})
    )
    assert recorder.verbs[len(before):] == ["write", "read"], recorder.verbs
    assert [row["parameter"] for row in result["applied"]] == [PARAM]
    assert seam.staged == {"drive_level": 0.5}, "prior staging was disturbed"


def test_apply_guards_the_read_verb_before_any_write(tmp_path: Path) -> None:
    """FOLD-B: a descriptor-only project (no presentation documents — the
    reachability key) with an rw parameter and no read operation must
    refuse ``standalone_verb_unbounded`` BEFORE any frame; today the write
    lands and the read's KeyError launders as internal_error."""
    import asyncio

    project = tmp_path / "no-read"
    shutil.copytree(FIXTURE, project)
    pkg = project / "src" / "setpoint_demo"
    for document_name in ("presentation.json", "binding-catalogue.json"):
        (pkg / document_name).unlink()
    shutil.rmtree(pkg / "ui")
    descriptor_path = pkg / "descriptor.json"
    document = json.loads(descriptor_path.read_text())
    document["capabilities"].remove("read")
    del document["operations"]["read"]
    descriptor_path.write_text(json.dumps(document))

    seam, recorder = _recorder_seam(project)
    asyncio.run(seam.call("device_connect", {"device_id": DEV}))
    _stage(seam, 2.5)
    before = list(recorder.verbs)
    with pytest.raises(Exception) as caught:
        asyncio.run(seam.call("parameter_apply", {"device_id": DEV}))
    assert caught.value.code == "unavailable"
    assert "standalone_verb_unbounded" in caught.value.message
    assert "read" in caught.value.message
    assert recorder.verbs == before, "a write landed before the read guard"


def test_staging_an_unrepresentable_number_refuses_typed(connected) -> None:
    """FOLD-C(i): a value outside the numeric format is a typed
    invalid_request, never a bare 500 from the float conversion."""
    _client, seam, _recorder, _policy = connected
    with pytest.raises(Exception) as caught:
        _stage(seam, int("9" * 400))
    assert caught.value.code == "invalid_request"
    assert PARAM in caught.value.message


def test_the_control_step_stays_finite_on_extreme_ranges() -> None:
    """FOLD-C(ii): a declared span that overflows the numeric format must
    not render step="inf" (invalid HTML; the browser silently falls back)."""
    from benchweave_sdk_server.presentation import staged_control_html

    wide = {
        "name": "wide",
        "type": "float",
        "unit": None,
        "range": [-1.7e308, 1.7e308],
    }
    html = staged_control_html(wide, staged=None, device_value=None)
    assert 'step="inf"' not in html
    assert "inf" not in html, html[:200]


def test_a_refused_stage_renders_the_true_label(connected) -> None:
    """FOLD-D: the refused-action notice names the action that was
    refused — a refused STAGE is not an 'Apply refused'."""
    client, _seam, _recorder, policy = connected
    response = client.post(
        "/pages/readings/stage",
        headers={"x-csrf-token": policy.csrf_token},
        data={PARAM: "5.5"},
    )
    assert response.status_code == 200
    assert "Stage refused" in response.text
    assert "Apply refused" not in response.text
