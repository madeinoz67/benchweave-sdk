# author: Stephen Eaton
"""Issue #394: the byte-stream mock transport for binary section 8.1
SEND/RECEIVE plugins (design of record 2026-10-05, gateway repo).

The seam-level families of the pre-committed 25-cell acceptance matrix
(§9) run here over the synthetic binary fixture
``tests/fixtures/binary_frames_plugin/`` — an invented plugin, no real
device claimed: family A (connect-and-operate over the mock), family B's
typed-refusal cell, family D (the refusal taxonomy surfaced through the
typed ``not_ready`` connect mapping, NFR-Q4/STD-4) and family G (NFR-O3
over the new host). The host-level families (B1, C, the R2 format pin)
live in ``test_mock_bytestream_host.py`` and the SW-61 parity battery
(family E, R1) in ``test_mock_bytestream_parity.py``; both land with the
mechanism commit and their RED control is the design §8 neutralized run.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk_server.errors import SeamError
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.session import (
    PluginSession,
    load_plugin_project,
    mock_plugin_session,
    mock_transport_factory,
)
from benchweave_sdk_server.web import build_app

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "binary_frames_plugin"
DEV = "frames_dev"

#: The capture burst's exact bytes (64 frames of two float64 LE samples),
#: derived the same way the fixture's ``vectors.json`` row was: the digest
#: assert pins the manifest against the primary's real bytes.
_BURST = b"".join(struct.pack("<dd", float(i), -float(i)) for i in range(64))


def _plugin(root: Path = FIXTURE):
    return load_plugin_project(Path(root))


def _seam(plugin) -> StandaloneSeam:
    """A mock seam in the merge-base-compatible shape (no capture root)."""
    return StandaloneSeam(mock_plugin_session(plugin), transport_kind="mock")


def _capture_seam(plugin, tmp: Path) -> StandaloneSeam:
    """A mock seam whose host publishes captures under ``tmp``."""
    return StandaloneSeam(
        mock_plugin_session(plugin, capture_root=tmp),
        transport_kind="mock",
        capture_root=tmp,
    )


def call(seam: StandaloneSeam, operation: str, arguments: dict | None = None) -> dict:
    import asyncio

    return asyncio.run(seam.call(operation, arguments or {}))


def _with_vectors(tmp_path: Path, mutate) -> Path:
    """A copy of the fixture whose vectors.json ``mutate`` rewrote."""
    root = tmp_path / "proj"
    shutil.copytree(FIXTURE, root)
    path = root / "src" / "binary_frames_demo" / "vectors.json"
    document = json.loads(path.read_text())
    mutate(document)
    path.write_text(json.dumps(document, indent=2) + "\n")
    return root


# --- the issue's reproducer shape (design §8) --------------------------------


def test_r0_connect_never_surfaces_a_raw_keyerror(tmp_path: Path) -> None:
    """The issue's symptom: connecting a binary §8.1 SEND/RECEIVE plugin
    on the mock raised ``KeyError: 'request'`` through
    ``standalone_plugin_connect``. Post-fix this file's connect SUCCEEDS
    (it declares ``send_receive``); a connect that cannot be served must
    refuse with a ``standalone_``-prefixed diagnostic, never a raw
    ``KeyError``."""
    seam = _seam(_plugin())
    try:
        result = call(seam, "device_connect", {"device_id": DEV})
        assert result == {"device_id": DEV, "connected": True}
    except SeamError as caught:
        assert caught.code == "not_ready"
        assert "KeyError" not in caught.message
        assert "standalone_" in caught.message


# --- family A: connect and operate over the mock (5 cells) ------------------


def test_a1_connect_completes_identify(tmp_path: Path) -> None:
    seam = _seam(_plugin())
    assert call(seam, "device_connect", {"device_id": DEV}) == {
        "device_id": DEV,
        "connected": True,
    }
    identity = call(seam, "device_get", {"device_id": DEV})
    assert identity["manufacturer"] == "BenchWeave Labs"
    assert identity["model"] == "frames-demo"
    assert identity["serial"] == "SIM-BF1"


def test_a2_parameter_read(tmp_path: Path) -> None:
    seam = _seam(_plugin())
    call(seam, "device_connect", {"device_id": DEV})
    reading = call(seam, "parameter_read", {"device_id": DEV, "parameter": "sample_avg"})
    assert reading["value"] == 2.5
    assert reading["unit"] == "V"
    assert reading["quality"] == "valid"


async def _walk_head(seam: StandaloneSeam) -> None:
    """Walk the fixture's scripted head in order: identify (the connect),
    the read, the write triad. Cells that continue the conversation past
    the head (capture, the poll cycle) start from here — the script is
    linear and demand-ordered."""
    await seam.call("device_connect", {"device_id": DEV})
    reading = await seam.call(
        "parameter_read", {"device_id": DEV, "parameter": "sample_avg"}
    )
    assert reading["value"] == 2.5
    await seam.call(
        "parameter_stage",
        {"device_id": DEV, "parameter": "sample_avg", "value": 3.0},
    )
    applied = await seam.call("parameter_apply", {"device_id": DEV})
    assert applied["applied"][0]["value"] == 3.0


def test_a3_write_stage_apply_readback(tmp_path: Path) -> None:
    seam = _seam(_plugin())
    call(seam, "device_connect", {"device_id": DEV})
    # The fixture's scripted conversation walks identify, read, then the
    # write triad; this read is that conversation's poll step.
    first = call(seam, "parameter_read", {"device_id": DEV, "parameter": "sample_avg"})
    assert first["value"] == 2.5
    staged = call(
        seam, "parameter_stage",
        {"device_id": DEV, "parameter": "sample_avg", "value": 3.0},
    )
    assert staged["staged"] == ["sample_avg"]
    outcome = call(seam, "parameter_apply", {"device_id": DEV})
    assert len(outcome["applied"]) == 1
    row = outcome["applied"][0]
    assert row["parameter"] == "sample_avg"
    assert row["value"] == 3.0, "the read-back row must answer the applied value"


def test_a4_bounded_capture_serves_the_declared_count(tmp_path: Path) -> None:
    import asyncio

    seam = _capture_seam(_plugin(), tmp_path)

    async def scenario() -> dict:
        # One loop for the whole capture: the watcher task the host arms at
        # capture_start must outlive the call (a loop per call would cancel
        # it at each exit — the lifecycle suite's single-scenario shape).
        await seam.call("device_connect", {"device_id": DEV})
        await seam.call(
            "parameter_read", {"device_id": DEV, "parameter": "sample_avg"}
        )
        await seam.call(
            "parameter_stage",
            {"device_id": DEV, "parameter": "sample_avg", "value": 3.0},
        )
        await seam.call("parameter_apply", {"device_id": DEV})
        started = await seam.call(
            "capture_start",
            {
                "device_id": DEV,
                "format": "waveform_f64le",
                "count": 128,
                "sample_interval_s": 0.001,
                "unit": "V",
            },
        )
        assert started["state"] == "capturing"
        assert started["bound"] == {"kind": "count", "count": 128, "bytes": 1024}
        return await seam.await_capture()

    outcome = asyncio.run(scenario())
    assert outcome["state"] == "published"
    assert outcome["stop_reason"] == "completed"
    assert outcome["byte_length"] == 1024
    capture_id = outcome["capture_id"]
    event = tmp_path / capture_id
    primary = (event / f"{capture_id}.f64").read_bytes()
    assert primary == _BURST, "the declared sample count is served exactly"
    manifest = json.loads((event / "manifest.json").read_text())
    assert manifest["sha256"] == hashlib.sha256(_BURST).hexdigest()
    assert manifest["sample_count"] == 128
    assert manifest["byte_length"] == 1024


def test_a5_reconnect_respeaks_the_establishment_head(tmp_path: Path) -> None:
    import asyncio

    seam = _capture_seam(_plugin(), tmp_path)

    async def scenario() -> None:
        await _walk_head(seam)
        started = await seam.call(
            "capture_start",
            {
                "device_id": DEV,
                "format": "waveform_f64le",
                "count": 128,
                "sample_interval_s": 0.001,
                "unit": "V",
            },
        )
        assert started["state"] == "capturing"
        outcome = await seam.await_capture()
        assert outcome["state"] == "published"
        # Polls past the capture row: the response-only status row releases,
        # the tail recycles, and reads keep answering.
        for _ in range(3):
            reading = await seam.call(
                "parameter_read", {"device_id": DEV, "parameter": "sample_avg"}
            )
            assert reading["value"] == 2.5
        assert (
            await seam.call("device_disconnect", {"device_id": DEV})
        )["connected"] is False
        # The M1-fold shape: the reconnect's services are minted fresh and
        # the new conversation starts at the establishment head again.
        assert (
            await seam.call("device_connect", {"device_id": DEV})
        )["connected"] is True
        identity = await seam.call("device_get", {"device_id": DEV})
        assert identity["model"] == "frames-demo"
        reading = await seam.call(
            "parameter_read", {"device_id": DEV, "parameter": "sample_avg"}
        )
        assert reading["value"] == 2.5

    asyncio.run(scenario())


# --- family B: response-only rows on both dialects (2 cells; B1 host-level) --


def test_b2_response_only_row_under_the_default_dialect_is_typed(tmp_path: Path) -> None:
    """The default dialect cannot script an unsolicited frame: the refusal
    is the typed ``standalone_vectors_row_unscriptable:`` naming the row —
    never today's raw ``KeyError: 'request'`` (the issue's symptom 1)."""

    def mutate(document: dict) -> None:
        document.pop("transaction_dialect", None)
        document.pop("encoding", None)
        document["exchanges"] = [
            {"name": "identify", "request": "2a49444e3f0a", "response": "4f4b0a"},
            {"name": "boot", "response": "53544154000a"},
        ]

    root = _with_vectors(tmp_path, mutate)
    seam = _capture_seam(load_plugin_project(root), tmp_path)
    with pytest.raises(SeamError) as caught:
        call(seam, "device_connect", {"device_id": DEV})
    assert caught.value.code == "not_ready"
    message = caught.value.message
    assert "standalone_vectors_row_unscriptable:" in message
    assert "boot" in message
    assert 'transaction_dialect: "send_receive"' in message
    assert "KeyError" not in message


# --- family D: the refusal taxonomy through the typed connect seam (4 cells) -


def test_d1_unknown_dialect_refuses_naming_the_value(tmp_path: Path) -> None:
    def mutate(document: dict) -> None:
        document["transaction_dialect"] = "raw_frames"

    root = _with_vectors(tmp_path, mutate)
    seam = _capture_seam(load_plugin_project(root), tmp_path)
    with pytest.raises(SeamError) as caught:
        call(seam, "device_connect", {"device_id": DEV})
    assert caught.value.code == "not_ready"
    assert "standalone_vectors_dialect_unknown:" in caught.value.message
    assert "raw_frames" in caught.value.message


def test_d2_unknown_encoding_refuses_naming_the_value(tmp_path: Path) -> None:
    def mutate(document: dict) -> None:
        document["encoding"] = "base64"

    root = _with_vectors(tmp_path, mutate)
    seam = _capture_seam(load_plugin_project(root), tmp_path)
    with pytest.raises(SeamError) as caught:
        call(seam, "device_connect", {"device_id": DEV})
    assert caught.value.code == "not_ready"
    assert "standalone_vectors_encoding_unknown:" in caught.value.message
    assert "base64" in caught.value.message


def test_d3_invalid_hex_refuses_naming_the_row(tmp_path: Path) -> None:
    def mutate(document: dict) -> None:
        document["exchanges"][0]["request"] = "zz"

    root = _with_vectors(tmp_path, mutate)
    seam = _capture_seam(load_plugin_project(root), tmp_path)
    with pytest.raises(SeamError) as caught:
        call(seam, "device_connect", {"device_id": DEV})
    assert caught.value.code == "not_ready"
    assert "standalone_vectors_encoding_invalid:" in caught.value.message
    assert "identify" in caught.value.message


def test_d4_malformed_row_refuses_with_row_shape(tmp_path: Path) -> None:
    def mutate(document: dict) -> None:
        document["exchanges"][0] = {"name": "identify"}

    root = _with_vectors(tmp_path, mutate)
    seam = _capture_seam(load_plugin_project(root), tmp_path)
    with pytest.raises(SeamError) as caught:
        call(seam, "device_connect", {"device_id": DEV})
    assert caught.value.code == "not_ready"
    assert "standalone_vectors_row_shape:" in caught.value.message
    assert "identify" in caught.value.message


# --- family G: NFR-O3 over the new host (1 cell) -----------------------------


class _VerbRecorder:
    """Test-only adapter wrapper recording every ``execute()`` verb
    (``test_nowrite.py``'s recording pattern)."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.verbs: list[str] = []

    async def open(self, descriptor, services, context) -> None:
        await self._inner.open(descriptor, services, context)

    async def execute(self, request, context):
        self.verbs.append(str(request.get("verb")))
        return await self._inner.execute(request, context)

    async def next_event(self, subscription_id, context):
        return await self._inner.next_event(subscription_id, context)

    async def close(self, context) -> None:
        await self._inner.close(context)


def _policy() -> GuardPolicy:
    return GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )


def test_g_no_write_on_page_load_reconnect_and_preset_selection(tmp_path: Path) -> None:
    """NFR-O3 proven, not presumed: page loads, a reconnect and the preset
    listing drive only read-side verbs over the byte-stream host — a write
    frame would ConformanceError at the transport and a ``write`` verb
    would appear in the recorder."""
    plugin = _plugin()
    recorder = _VerbRecorder(plugin.adapter_factory())
    seam = StandaloneSeam(
        mock_plugin_session(
            replace(plugin, adapter_factory=lambda: recorder), capture_root=tmp_path
        ),
        transport_kind="mock",
        capture_root=tmp_path,
    )
    policy = _policy()
    with TestClient(
        build_app(seam, policy=policy), base_url="http://127.0.0.1:8477"
    ) as client:
        client.post(
            f"/devices/{DEV}/connect",
            headers={"x-csrf-token": policy.csrf_token},
            follow_redirects=False,
        )
        client.get("/")
        client.get(f"/devices/{DEV}")  # preset selection surface: the page lists presets
        for _ in range(3):
            client.get(f"/devices/{DEV}/readings")
        client.post(
            f"/devices/{DEV}/disconnect",
            headers={"x-csrf-token": policy.csrf_token},
            follow_redirects=False,
        )
        client.post(
            f"/devices/{DEV}/connect",
            headers={"x-csrf-token": policy.csrf_token},
            follow_redirects=False,
        )
        client.get(f"/devices/{DEV}")
    assert set(recorder.verbs) <= {"identify", "read"}, recorder.verbs

def test_g_control_the_recorder_hears_a_driven_write(tmp_path: Path) -> None:
    """The G cell's non-vacuity control (test_nowrite.py's deaf-recorder
    discipline): a write verb driven through the recorder IS recorded — a
    deaf recorder would pass the no-write cell for the wrong reason."""
    import asyncio

    plugin = _plugin()
    recorder = _VerbRecorder(plugin.adapter_factory())
    session = PluginSession(
        replace(plugin, adapter_factory=lambda: recorder),
        mock_transport_factory(plugin, capture_root=tmp_path),
    )

    async def run() -> None:
        await session.connect()
        # Walk the scripted conversation to the write row: read first.
        reading = await session.execute("read", {"parameter": "sample_avg"})
        assert reading["status"] == "ok"
        envelope = await session.execute(
            "write", {"parameter": "sample_avg", "value": 3.0}
        )
        assert envelope["status"] == "ok"
        await session.close()

    asyncio.run(run())
    assert recorder.verbs == ["identify", "read", "write"], recorder.verbs
