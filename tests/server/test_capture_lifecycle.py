"""I3b slice 3: the capture lifecycle through the seam (issue #285).

The design record's §1 I3b mechanism over the serial capture services with
an in-process loopback port (no pyserial, AR-1's posture): capture_start
dispatches the descriptor-declared capture verb, the ADAPTER appends through
the services into the per-capture writer, and the HOST finalises or aborts
per the locked ruling — envelope ok finalises ``completed``; an unknown
status/dispatch aborts ``stop_unknown`` (A06: an ambiguous capture is never
published); an error envelope finalises the real bytes ``adapter_error``;
an uncaught exception aborts ``adapter_exception``; a refused finalise
aborts ``finalise_refused``. Cooperative adapters return at their bound;
the host's poll-loop watchdog backstops by cancelling the operation context
at the bound; capture_stop sets a stop event the loop honours.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import shutil
import struct
import time
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.scaffold import create_project
from benchweave_sdk_server.errors import SeamError
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.serial import serial_plugin_session
from benchweave_sdk_server.session import load_plugin_project

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DEV = "example_device"
_PACKAGE = "wavegen_plugin"
_ID_REPLY = b"Bench Fixture,wavegen,SIMW001,1.0.0\n"


class LoopbackPort:
    """The pyserial surface over a scripted reply table (no real port)."""

    def __init__(self, replies: dict[bytes, bytes] | None = None) -> None:
        self.inbound = bytearray()
        self.replies = replies or {}
        self.written: list[bytes] = []
        self.closed = 0

    def write(self, data: bytes) -> int | None:
        self.written.append(bytes(data))
        self.inbound += self.replies.get(bytes(data), b"")
        return len(data)

    def read(self, size: int = 1) -> bytes:
        out = bytes(self.inbound[:size])
        del self.inbound[:size]
        if not out:
            # An idle port's own timeout window — pyserial's opener uses
            # timeout=0.05; a 1 ms nap here made every leaked reader thread
            # a 1 kHz waker and tipped later timing arms in the same process
            # (their CPU measurements are process-wide).
            time.sleep(0.005)
        return out

    def close(self) -> None:
        self.closed += 1


def _patch_descriptor(
    root: Path,
    verbs: tuple[str, ...],
    *,
    max_samples: int = 100_000,
    max_bytes: int = 16 * 1024 * 1024,
) -> None:
    """Declare the capture verbs the test wants in the scaffold's descriptor.

    The vendored OTDP schema's own conditional (allOf: capabilities contains
    capture) requires ``capture_formats`` and ``capture_limits`` — the
    plugin's declared bounds, which the host honours as the commissioned
    ceiling (max_samples/max_bytes), never a host constant.
    """
    path = root / "src" / _PACKAGE / "descriptor.json"
    descriptor = json.loads(path.read_text(encoding="utf-8"))
    descriptor["capabilities"] = ["identify", "read", *verbs]
    for verb in verbs:
        descriptor["operations"][verb] = {
            "timeout_ms": 5000,
            "side_effect": "state_change" if verb == "capture" else "none",
            "retry": "never",
            "cancellable": True,
            "completion": "acknowledged",
        }
    if "capture" in verbs:
        descriptor["capture_formats"] = ["waveform_f64le", "raw_binary"]
        descriptor["capture_limits"] = {"max_samples": max_samples, "max_bytes": max_bytes}
    path.write_text(json.dumps(descriptor, indent=2), encoding="utf-8")


def _host(
    tmp_path: Path,
    *,
    verbs: tuple[str, ...] = ("capture",),
    mode: str = "ok",
    default_count: int = 8,
    max_samples: int = 100_000,
    max_bytes: int = 16 * 1024 * 1024,
) -> StandaloneSeam:
    """A serial-transport seam over the fixture plugin, not yet connected."""
    root = tmp_path / "proj"
    create_project(root, _PACKAGE)
    _patch_descriptor(root, verbs, max_samples=max_samples, max_bytes=max_bytes)
    shutil.copy(FIXTURES / "wavegen_adapter.py", root / "src" / _PACKAGE / "adapter.py")
    (root / "src" / _PACKAGE / "behaviour.json").write_text(
        json.dumps({"mode": mode, "default_count": default_count}), encoding="utf-8"
    )
    loaded = load_plugin_project(root)
    port = LoopbackPort(replies={b"ID?\n": _ID_REPLY})
    captures = tmp_path / "captures"
    session = serial_plugin_session(
        loaded,
        "/dev/fixture-loopback",
        open_port=lambda device, settings: port,
        capture_root=captures,
    )
    return StandaloneSeam(session, transport_kind="serial", capture_root=captures)


async def _connected(host: StandaloneSeam) -> None:
    await host.call("device_connect", {"device_id": DEV})


def _event_dirs(host: StandaloneSeam, tmp_path: Path) -> list[str]:
    """Event DIRECTORIES in the capture root — the library's own index and
    lockfile live there as files and are not events."""
    root = tmp_path / "captures"
    return (
        sorted(entry.name for entry in root.iterdir() if entry.is_dir())
        if root.is_dir()
        else []
    )


def _start(count: int | None = None, **extra: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "device_id": DEV,
        "format": "waveform_f64le",
        "sample_interval_s": 0.001,
        "unit": "V",
    }
    if count is not None:
        arguments["count"] = count
    arguments.update(extra)
    return arguments


# --- the transport gap and the guards --------------------------------------


def test_capture_start_refuses_without_capture_services(seam) -> None:
    """The mock transport's host does not implement the capture members:
    the refusal is unavailable, naming the gap (the conftest disclosure)."""

    async def scenario() -> None:
        await _connected(seam)
        with pytest.raises(SeamError) as caught:
            await seam.call("capture_start", _start(count=4))
        assert "unavailable" in str(caught.value.code)

    asyncio.run(scenario())


def test_capture_start_refuses_while_a_reload_is_pending(seam) -> None:
    """A pending Q11 reload blocks new captures (the guard's capture leg)."""
    seam._pending_reload = {"at": "now", "source": "test"}

    async def scenario() -> None:
        await _connected(seam)
        with pytest.raises(SeamError) as caught:
            await seam.call("capture_start", _start(count=4))
        assert "conflict" in str(caught.value.code)

    asyncio.run(scenario())


def test_max_bytes_below_the_count_bound_refuses_at_start(tmp_path: Path) -> None:
    """A reservation smaller than the declared count bound is refused before
    any dispatch — not left to fail mid-capture at the writer."""
    host = _host(tmp_path)

    async def scenario() -> None:
        await _connected(host)
        with pytest.raises(SeamError) as caught:
            await host.call("capture_start", _start(count=10, max_bytes=16))
        assert "invalid_request" in str(caught.value.code)

    asyncio.run(scenario())


def test_descriptor_capture_limits_bound_the_request(tmp_path: Path) -> None:
    """The configured ceiling is the descriptor's own declared
    capture_limits (the schema-mandated commissioning, A02): a count bound
    above max_samples refuses, and a ceiling below the count bound refuses
    at start — never a mid-capture writer surprise."""
    tight = _host(tmp_path, max_samples=100, max_bytes=256)

    async def scenario() -> None:
        await _connected(tight)
        with pytest.raises(SeamError) as caught:
            await tight.call("capture_start", _start(count=101))
        assert "invalid_request" in str(caught.value.code)
        with pytest.raises(SeamError) as caught:
            await tight.call("capture_start", _start(count=40))
        assert "invalid_request" in str(caught.value.code)
        # Inside both declared limits the capture runs.
        await tight.call("capture_start", _start(count=30))
        outcome = await tight.await_capture()
        assert outcome["state"] == "published"
        assert outcome["byte_length"] == 240

    asyncio.run(scenario())


# --- the happy path (AR-5) ---------------------------------------------------


def test_count_bound_capture_publishes_with_sw54_metadata(tmp_path: Path) -> None:
    host = _host(tmp_path, mode="ok")

    async def scenario() -> dict[str, Any]:
        await _connected(host)
        started = await host.call("capture_start", _start(count=4), surface="rest")
        assert started["state"] == "capturing"
        assert started["bound"] == {"kind": "count", "count": 4, "bytes": 32}
        assert started["format"] == "waveform_f64le"
        return await host.await_capture()

    outcome = asyncio.run(scenario())
    capture_id = outcome["capture_id"]
    assert outcome["state"] == "published"
    assert outcome["stop_reason"] == "completed"
    assert outcome["byte_length"] == 32
    event = tmp_path / "captures" / capture_id
    payload = (event / f"{capture_id}.f64").read_bytes()
    assert len(payload) == 32
    # The host never fabricates data: the manifest digest is the primary's.
    manifest = json.loads((event / "manifest.json").read_text())
    assert manifest["sha256"] == hashlib.sha256(payload).hexdigest()
    assert manifest["sample_count"] == 4  # derived from real staged bytes
    assert manifest["sample_interval_s"] == 0.001
    assert manifest["unit"] == "V"
    metadata = json.loads((event / "metadata.json").read_text())
    assert metadata["capture_id"] == capture_id
    assert metadata["device"]["id"] == DEV
    assert metadata["plugin"]["package"] == _PACKAGE
    assert metadata["surface"] == "rest"
    assert metadata["operator"]
    assert metadata["declared"]["format"] == "waveform_f64le"
    assert metadata["declared"]["bound"] == {"kind": "count", "count": 4, "bytes": 32}
    assert metadata["pinned"] is False
    assert metadata["stop_reason"] == "completed"
    # capture_get serves the published truth from disk
    fetched = asyncio.run(host.call("capture_get", {"capture_id": capture_id}))
    assert fetched["manifest"] == manifest
    assert fetched["metadata"] == metadata
    rows = asyncio.run(host.call("capture_list", {}))["captures"]
    row = next(row for row in rows if row["capture_id"] == capture_id)
    assert row["state"] == "published"
    assert row["pinned"] is False
    assert row["progress_bytes"] is None
    assert row["sha256"] == manifest["sha256"]


def test_capture_series_decimates_preserving_extrema(tmp_path: Path) -> None:
    """AR-5's decimation arm: 400 samples whose true min/max are -9.5/9.5;
    25 columns keep both extrema in at most 50 points; raw serves all."""
    host = _host(tmp_path, mode="ok")

    async def scenario() -> str:
        await _connected(host)
        started = await host.call("capture_start", _start(count=400))
        outcome = await host.await_capture()
        assert outcome["state"] == "published"
        return started["capture_id"]

    capture_id = asyncio.run(scenario())
    series = asyncio.run(
        host.call("capture_series", {"capture_id": capture_id, "max_points": 25})
    )
    assert series["decimated"] is True
    assert len(series["points"]) <= 50
    ys = [point[1] for point in series["points"]]
    assert min(ys) == -9.5 and max(ys) == 9.5
    raw = asyncio.run(
        host.call("capture_series", {"capture_id": capture_id, "max_points": 0})
    )
    assert raw["decimated"] is False
    assert len(raw["points"]) == 400
    assert raw["points"][0] == [0.0, -9.5]


def test_raw_series_above_the_sample_ceiling_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """max_points 0 serves raw points, refused with payload_too_large above
    the sample ceiling (the catalogue's own authored 10M maximum; shrunken
    here so the refusal is testable at fixture scale)."""
    from benchweave_sdk_server import seam as seam_module

    monkeypatch.setattr(seam_module, "_RAW_SAMPLE_CEILING", 200)
    host = _host(tmp_path, mode="ok")

    async def scenario() -> str:
        await _connected(host)
        started = await host.call("capture_start", _start(count=400))
        await host.await_capture()
        return started["capture_id"]

    capture_id = asyncio.run(scenario())

    async def refused() -> None:
        with pytest.raises(SeamError) as caught:
            await host.call(
                "capture_series", {"capture_id": capture_id, "max_points": 0}
            )
        assert "payload_too_large" in str(caught.value.code)

    asyncio.run(refused())


def test_series_unknown_id_is_not_found(tmp_path: Path) -> None:
    host = _host(tmp_path)

    async def scenario() -> None:
        await _connected(host)
        with pytest.raises(SeamError) as caught:
            await host.call("capture_series", {"capture_id": "cap-nothere"})
        assert "not_found" in str(caught.value.code)

    asyncio.run(scenario())


# --- the honest terminal outcomes (ruling 1) --------------------------------


def test_capture_stop_publishes_the_real_bytes(tmp_path: Path) -> None:
    """Stopping mid-stream finalises what actually arrived: byte_length is
    a positive multiple of 8 bounded by the count, stop_reason stopped."""
    host = _host(tmp_path, mode="slow")

    async def scenario() -> dict[str, Any]:
        await _connected(host)
        started = await host.call("capture_start", _start(count=40))
        await asyncio.sleep(0.07)
        return await host.call("capture_stop", {"capture_id": started["capture_id"]})

    stopped = asyncio.run(scenario())
    assert stopped["state"] == "published"
    assert stopped["stop_reason"] == "stopped"
    assert stopped["manifest"]["byte_length"] > 0
    assert stopped["manifest"]["byte_length"] % 8 == 0
    assert stopped["manifest"]["byte_length"] <= 320


def test_stop_unknown_aborts_and_stays_session_scoped(tmp_path: Path) -> None:
    """AR-8: an adapter whose outcome is unknown after appends aborts — the
    artifact is never published complete. The aborted row is session state:
    capture_list shows it, capture_get answers not_found."""
    host = _host(tmp_path, mode="unknown")

    async def scenario() -> str:
        await _connected(host)
        started = await host.call("capture_start", _start(count=6))
        outcome = await host.await_capture()
        assert outcome["state"] == "aborted"
        assert outcome["stop_reason"] == "stop_unknown"
        return started["capture_id"]

    capture_id = asyncio.run(scenario())
    assert _event_dirs(host, tmp_path) == []
    rows = asyncio.run(host.call("capture_list", {}))["captures"]
    row = next(row for row in rows if row["capture_id"] == capture_id)
    assert row["state"] == "aborted"
    assert row["stop_reason"] == "stop_unknown"

    async def refused() -> None:
        with pytest.raises(SeamError) as caught:
            await host.call("capture_get", {"capture_id": capture_id})
        assert "not_found" in str(caught.value.code)

    asyncio.run(refused())


def test_adapter_error_finalises_the_real_bytes(tmp_path: Path) -> None:
    host = _host(tmp_path, mode="error")

    async def scenario() -> dict[str, Any]:
        await _connected(host)
        await host.call("capture_start", _start(count=6))
        return await host.await_capture()

    outcome = asyncio.run(scenario())
    assert outcome["state"] == "published"
    assert outcome["stop_reason"] == "adapter_error"
    assert outcome["byte_length"] == 48


def test_silent_capture_publishes_nothing(tmp_path: Path) -> None:
    """AR-5's RED control: an adapter that appends nothing publishes
    nothing — aborted, no event directory, no manifest anywhere."""
    host = _host(tmp_path, mode="silent")

    async def scenario() -> dict[str, Any]:
        await _connected(host)
        await host.call("capture_start", _start(count=4))
        return await host.await_capture()

    outcome = asyncio.run(scenario())
    assert outcome["state"] == "aborted"
    assert _event_dirs(host, tmp_path) == []


def test_uncaught_adapter_exception_aborts(tmp_path: Path) -> None:
    host = _host(tmp_path, mode="raise")

    async def scenario() -> dict[str, Any]:
        await _connected(host)
        await host.call("capture_start", _start(count=4))
        return await host.await_capture()

    outcome = asyncio.run(scenario())
    assert outcome["state"] == "aborted"
    assert outcome["stop_reason"] == "adapter_exception"


def test_finalise_os_error_settles_and_frees_the_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-F1 (T4 shape): an ENOSPC-class OSError at finalise is a TERMINAL
    outcome, never a wedge — the artifact aborts, the outcome settles
    ``finalise_refused``, the slot frees (a later start works), and
    capture_stopped carries the reason."""
    host = _host(tmp_path, mode="ok")

    async def scenario() -> dict[str, Any]:
        await _connected(host)
        services = host._session.services
        real = services.artifact_finalise

        async def refusing(
            capture_id: str, metadata: dict[str, Any], context: Any
        ) -> dict[str, Any]:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(services, "artifact_finalise", refusing)
        started = await host.call("capture_start", _start(count=4))
        outcome = await host.await_capture()
        monkeypatch.setattr(services, "artifact_finalise", real)
        assert host._capture is None, "the slot must free at the terminal state"
        await host.call("capture_start", _start(count=2))
        settled = await host.await_capture()
        return {"first": outcome, "id": started["capture_id"], "settled": settled}

    result = asyncio.run(scenario())
    assert result["first"]["state"] == "aborted"
    assert result["first"]["stop_reason"] == "finalise_refused"
    assert not (tmp_path / "captures" / result["id"]).exists()
    assert result["settled"]["state"] == "published"
    events = asyncio.run(host.call("events_get", {"after_id": 0}))["events"]
    stopped = next(
        event
        for event in events
        if event["kind"] == "capture_stopped"
        and event["data"]["capture_id"] == result["id"]
    )
    assert stopped["data"]["stop_reason"] == "finalise_refused"


def test_count_bound_backstop_cancels_a_lingering_adapter(tmp_path: Path) -> None:
    """The watchdog: a cooperative adapter that never returns on its own is
    cancelled at the bound and the bound's bytes are finalised."""
    host = _host(tmp_path, mode="linger")

    async def scenario() -> dict[str, Any]:
        await _connected(host)
        await host.call("capture_start", _start(count=3))
        return await host.await_capture()

    outcome = asyncio.run(scenario())
    assert outcome["state"] == "published"
    assert outcome["stop_reason"] == "bound"
    assert outcome["byte_length"] == 24
    assert outcome["sha256"]


def test_duration_bound_ends_the_capture(tmp_path: Path) -> None:
    host = _host(tmp_path, mode="linger", default_count=6)

    async def scenario() -> dict[str, Any]:
        await _connected(host)
        started = await host.call(
            "capture_start", _start(duration_s=0.3, sample_interval_s=0.001, unit="V")
        )
        assert started["bound"] == {"kind": "duration_s", "duration_s": 0.3}
        return await host.await_capture()

    outcome = asyncio.run(scenario())
    assert outcome["state"] == "published"
    assert outcome["stop_reason"] == "bound"
    assert outcome["byte_length"] == 48


def test_second_start_while_in_flight_conflicts(tmp_path: Path) -> None:
    host = _host(tmp_path, mode="slow")

    async def scenario() -> None:
        await _connected(host)
        started = await host.call("capture_start", _start(count=40))
        with pytest.raises(SeamError) as caught:
            await host.call("capture_start", _start(count=4))
        assert "conflict" in str(caught.value.code)
        await host.call("capture_stop", {"capture_id": started["capture_id"]})

    asyncio.run(scenario())


def test_stop_of_an_unknown_capture_is_not_found(tmp_path: Path) -> None:
    host = _host(tmp_path)

    async def scenario() -> None:
        await _connected(host)
        with pytest.raises(SeamError) as caught:
            await host.call("capture_stop", {"capture_id": "cap-nothere"})
        assert "not_found" in str(caught.value.code)

    asyncio.run(scenario())


# --- the verb resolution (ruling 6) -----------------------------------------


def test_the_descriptor_declared_capture_verb_is_dispatched(tmp_path: Path) -> None:
    """Ruling 6: the capture verb is descriptor-declared. The adapter's
    verb log proves the ``capture`` policy ran. (The ``invoke`` fallback is
    implemented in the seam's resolution order but has no fixture arm: a
    descriptor declaring ``invoke`` pulls the measurement-profiles
    machinery — channels/profiles/contracts/actions, the schema's own
    allOf — which is I3b's named DON'T-BUILD. Disclosed.)"""
    host = _host(tmp_path, verbs=("capture",))

    async def scenario() -> str:
        await _connected(host)
        started = await host.call("capture_start", _start(count=2))
        outcome = await host.await_capture()
        assert outcome["state"] == "published"
        return started["capture_id"]

    asyncio.run(scenario())
    log = (tmp_path / "proj" / "src" / _PACKAGE / "verbs.jsonl").read_text()
    assert json.loads(log.strip().splitlines()[-1])["verb"] == "capture"


def test_no_declared_capture_verb_refuses_naming_the_gap(tmp_path: Path) -> None:
    host = _host(tmp_path, verbs=())

    async def scenario() -> None:
        await _connected(host)
        with pytest.raises(SeamError) as caught:
            await host.call("capture_start", _start(count=2))
        assert "unavailable" in str(caught.value.code)
        assert "invoke" in str(caught.value) and "capture" in str(caught.value)

    asyncio.run(scenario())


# --- progress, surface, and the library verbs --------------------------------


def test_progress_is_flushed_plus_buffered_bytes(tmp_path: Path) -> None:
    """Ruling 2: an in-flight row's progress_bytes is the services' flushed
    + buffered count — sub-block captures sit in the buffer."""
    host = _host(tmp_path, mode="slow")

    async def scenario() -> dict[str, Any]:
        await _connected(host)
        started = await host.call("capture_start", _start(count=40))
        await asyncio.sleep(0.07)
        rows = await host.call("capture_list", {})
        row = next(
            row for row in rows["captures"] if row["capture_id"] == started["capture_id"]
        )
        assert row["state"] == "capturing"
        assert row["progress_bytes"] is not None
        assert 0 < row["progress_bytes"] <= 320
        assert row["progress_bytes"] % 8 == 0
        return await host.call("capture_stop", {"capture_id": started["capture_id"]})

    stopped = asyncio.run(scenario())
    assert stopped["state"] == "published"


def test_surface_is_recorded_in_metadata(tmp_path: Path) -> None:
    host = _host(tmp_path, mode="ok")

    async def scenario() -> str:
        await _connected(host)
        started = await host.call("capture_start", _start(count=2), surface="mcp")
        await host.await_capture()
        return started["capture_id"]

    capture_id = asyncio.run(scenario())
    metadata = json.loads(
        (tmp_path / "captures" / capture_id / "metadata.json").read_text()
    )
    assert metadata["surface"] == "mcp"


def test_annotate_pin_unpin_and_delete_round_trip(tmp_path: Path) -> None:
    host = _host(tmp_path, mode="ok")

    async def scenario() -> str:
        await _connected(host)
        started = await host.call("capture_start", _start(count=2))
        await host.await_capture()
        return started["capture_id"]

    capture_id = asyncio.run(scenario())
    annotated = asyncio.run(
        host.call(
            "capture_annotate",
            {"capture_id": capture_id, "notes": "fixture run", "tags": ["night"]},
        )
    )
    assert annotated["notes"] == "fixture run"
    metadata = json.loads(
        (tmp_path / "captures" / capture_id / "metadata.json").read_text()
    )
    assert metadata["notes"] == "fixture run"
    assert metadata["tags"] == ["night"]
    assert asyncio.run(host.call("capture_pin", {"capture_id": capture_id}))["pinned"]

    async def pinned_delete_refuses() -> None:
        with pytest.raises(SeamError) as caught:
            await host.call("capture_delete", {"capture_id": capture_id})
        assert "conflict" in str(caught.value.code)

    asyncio.run(pinned_delete_refuses())
    assert asyncio.run(host.call("capture_unpin", {"capture_id": capture_id}))[
        "pinned"
    ] is False
    deleted = asyncio.run(host.call("capture_delete", {"capture_id": capture_id}))
    assert deleted["deleted"] is True
    assert not (tmp_path / "captures" / capture_id).exists()
    assert _event_dirs(host, tmp_path) == []

    async def gone() -> None:
        with pytest.raises(SeamError) as caught:
            await host.call("capture_get", {"capture_id": capture_id})
        assert "not_found" in str(caught.value.code)

    asyncio.run(gone())


def test_delete_refuses_the_in_flight_capture(tmp_path: Path) -> None:
    host = _host(tmp_path, mode="slow")

    async def scenario() -> None:
        await _connected(host)
        started = await host.call("capture_start", _start(count=40))
        with pytest.raises(SeamError) as caught:
            await host.call("capture_delete", {"capture_id": started["capture_id"]})
        assert "conflict" in str(caught.value.code)
        await host.call("capture_stop", {"capture_id": started["capture_id"]})

    asyncio.run(scenario())


def test_artifact_read_serves_bounded_windows(tmp_path: Path) -> None:
    host = _host(tmp_path, mode="ok")

    async def scenario() -> str:
        await _connected(host)
        started = await host.call("capture_start", _start(count=4))
        await host.await_capture()
        return started["capture_id"]

    capture_id = asyncio.run(scenario())
    window = asyncio.run(
        host.call(
            "artifact_read", {"capture_id": capture_id, "offset": 0, "length": 8}
        )
    )
    assert base64.b64decode(window["data_base64"]) == struct.pack("<d", -9.5)
    assert window["length"] == 8
    clamped = asyncio.run(
        host.call(
            "artifact_read", {"capture_id": capture_id, "offset": 24, "length": 100}
        )
    )
    assert clamped["length"] == 8

    async def beyond_eof() -> None:
        with pytest.raises(SeamError) as caught:
            await host.call(
                "artifact_read", {"capture_id": capture_id, "offset": 64, "length": 8}
            )
        assert "invalid_request" in str(caught.value.code)

    asyncio.run(beyond_eof())
