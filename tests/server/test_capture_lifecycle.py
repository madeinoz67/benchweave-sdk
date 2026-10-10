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
import sys
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
    max_bytes: int | None = 16 * 1024 * 1024,
    verb_timeout_ms: int = 5000,
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
    # The declared identity names the unit the wavegen fixture SIMULATES
    # (_ID_REPLY) — pre-trust-5 the descriptor kept the scaffold's default
    # identity while the port answered Bench Fixture/wavegen, drift no
    # check ever surfaced; the establishment comparison refuses it now.
    descriptor["identity"]["manufacturer"] = "Bench Fixture"
    descriptor["identity"]["model"] = "wavegen"
    for verb in verbs:
        descriptor["operations"][verb] = {
            "timeout_ms": verb_timeout_ms,
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
    verb_timeout_ms: int = 5000,
    stubborn_s: float | None = None,
    retention: Any | None = None,
) -> StandaloneSeam:
    """A serial-transport seam over the fixture plugin, not yet connected."""
    root = tmp_path / "proj"
    create_project(root, _PACKAGE)
    _patch_descriptor(
        root, verbs, max_samples=max_samples, max_bytes=max_bytes,
        verb_timeout_ms=verb_timeout_ms,
    )
    shutil.copy(FIXTURES / "wavegen_adapter.py", root / "src" / _PACKAGE / "adapter.py")
    behaviour: dict[str, Any] = {"mode": mode, "default_count": default_count}
    if stubborn_s is not None:
        behaviour["stubborn_s"] = stubborn_s
    (root / "src" / _PACKAGE / "behaviour.json").write_text(
        json.dumps(behaviour), encoding="utf-8"
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
    return StandaloneSeam(
        session, transport_kind="serial", capture_root=captures, retention=retention
    )


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


@pytest.mark.timing
def test_a_stop_during_the_bound_grace_wins_over_the_bound(
    tmp_path: Path,
) -> None:
    """A-F2/B-F6 (T5 shape): the operator's stop inside the 0.30 s bound
    grace is honored — the reason is ``stopped``, never misattributed to
    the armed bound, and the settle latency stays well inside the grace."""
    host = _host(tmp_path, mode="linger")

    async def scenario() -> tuple[dict[str, Any], float]:
        await _connected(host)
        started = await host.call("capture_start", _start(count=3))
        await asyncio.sleep(0.15)
        asked = time.monotonic()
        stopped = await host.call(
            "capture_stop", {"capture_id": started["capture_id"]}
        )
        return stopped, time.monotonic() - asked

    stopped, elapsed = asyncio.run(scenario())
    assert stopped["state"] == "published"
    assert stopped["stop_reason"] == "stopped"
    assert stopped["manifest"]["byte_length"] == 24
    # The settle is real IO (finalise + publish + manifest). On POSIX the
    # 0.30 s bound discriminates a fast settle from a stop that blocks until
    # the bound fires (~0.15 s of grace remaining at the ask). Windows CI's
    # tmp-path IO + real-time Defender scanning routinely costs 0.3-0.5 s of
    # settle latency with the mechanism healthy — observed 0.3018 s against
    # the 0.30 bound, serial and unloaded, run 37390768609 — so the wall
    # clock there carries an IO-class allowance and the semantic row above
    # (stop_reason == "stopped", never misattributed to the bound) carries
    # the arm's contract.
    settle_limit = 0.30 if sys.platform != "win32" else 1.5
    assert elapsed < settle_limit, f"stop settle took {elapsed:.4f}s (limit {settle_limit}s)"


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


def test_a_stubborn_adapter_stopped_then_ok_publishes_stopped(
    tmp_path: Path,
) -> None:
    """B-F2 (P3 shape): an adapter that ignores the stop, keeps its head
    down, and eventually returns ok publishes with the OPERATOR's reason —
    ``stopped``, never relabelled ``completed``."""
    host = _host(tmp_path, mode="stubborn_ok")

    async def scenario() -> dict[str, Any]:
        await _connected(host)
        started = await host.call("capture_start", _start(count=8))
        await asyncio.sleep(0.1)
        return await host.call(
            "capture_stop", {"capture_id": started["capture_id"]}
        )

    stopped = asyncio.run(scenario())
    assert stopped["state"] == "published"
    assert stopped["stop_reason"] == "stopped"
    assert stopped["manifest"]["byte_length"] == 64


def test_a_count_bound_overrun_records_bound(tmp_path: Path) -> None:
    """B-F2 (P11 shape): an adapter that blows past its declared count
    (declared 8, stages 24) and returns ok after the bound's cancellation
    publishes the real bytes with the reason ``bound`` — the overrun is
    never laundered into ``completed``."""
    host = _host(tmp_path, mode="overrun")

    async def scenario() -> dict[str, Any]:
        await _connected(host)
        await host.call("capture_start", _start(count=8))
        return await host.await_capture()

    outcome = asyncio.run(scenario())
    assert outcome["state"] == "published"
    assert outcome["stop_reason"] == "bound"
    assert outcome["byte_length"] == 192


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


def test_stop_unknown_surfaces_the_envelope_verbatim(tmp_path: Path) -> None:
    """B-F1 (AR-8's honest sentence): an unknown-dispatch stop aborts and
    the stop RESULT carries the envelope's dispatch_state and message
    verbatim in ``details`` — the ambiguity is surfaced, not swallowed."""
    host = _host(tmp_path, mode="unknown")

    async def scenario() -> dict[str, Any]:
        await _connected(host)
        started = await host.call("capture_start", _start(count=6))
        return await host.call(
            "capture_stop", {"capture_id": started["capture_id"]}
        )

    stopped = asyncio.run(scenario())
    assert stopped["state"] == "aborted"
    assert stopped["stop_reason"] == "stop_unknown"
    assert stopped["manifest"] is None
    assert stopped["details"]["dispatch_state"] == "unknown"
    assert stopped["details"]["message"] == "outcome uncertain after appends"


def test_a_stop_timeout_frees_the_bench(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B-F5 (P3 stubborn shape): an adapter that absorbs every
    cancellation wedged the bench for the process's life — capture_stop
    answered internal_error, the watcher looped forever, the slot stayed
    held. The timeout now settles out-of-band: the outcome records
    stop_timeout, the slot frees, capture_stopped fires, and a later
    capture_start works."""
    from benchweave_sdk_server import seam as seam_module

    monkeypatch.setattr(seam_module, "_STOP_SETTLE_MARGIN_S", 0.5)
    host = _host(
        tmp_path, mode="zombie", verb_timeout_ms=500, stubborn_s=3.0
    )

    async def scenario() -> dict[str, Any]:
        await _connected(host)
        started = await host.call("capture_start", _start(count=4))
        with pytest.raises(SeamError) as caught:
            await host.call(
                "capture_stop", {"capture_id": started["capture_id"]}
            )
        assert "internal_error" in str(caught.value.code)
        # The escape: the slot must be free — a new capture starts.
        second = await host.call("capture_start", _start(count=2))
        settled = await host.await_capture()
        return {"first_id": started["capture_id"], "second": second, "settled": settled}

    result = asyncio.run(scenario())
    assert result["settled"]["state"] == "published"
    rows = asyncio.run(host.call("capture_list", {}))["captures"]
    first_row = next(
        row for row in rows if row["capture_id"] == result["first_id"]
    )
    assert first_row["state"] == "aborted"
    assert first_row["stop_reason"] == "stop_timeout"
    events = asyncio.run(host.call("events_get", {"after_id": 0}))["events"]
    assert any(
        event["kind"] == "capture_stopped"
        and event["data"]["capture_id"] == result["first_id"]
        and event["data"]["stop_reason"] == "stop_timeout"
        for event in events
    )


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


def test_the_sidecar_names_the_effective_reservation(tmp_path: Path) -> None:
    """B-F3 (P1 shape): the SW-54 sidecar's config records the EFFECTIVE
    reservation — min(requested, descriptor ceiling), the value the writer
    enforces — not the raw requested argument."""
    host = _host(tmp_path, max_bytes=1000, mode="ok")

    async def scenario() -> str:
        await _connected(host)
        started = await host.call(
            "capture_start", _start(count=4, max_bytes=10_000)
        )
        await host.await_capture()
        return started["capture_id"]

    capture_id = asyncio.run(scenario())
    metadata = json.loads(
        (tmp_path / "captures" / capture_id / "metadata.json").read_text()
    )
    assert metadata["config"]["max_bytes"] == 1000


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


def test_stale_index_rows_refuse_closed_and_self_heal(tmp_path: Path) -> None:
    """B-F4 (P6 shape): an out-of-band deleted event dir leaves a stale
    index row — annotate and pin answer not_found (never a raw
    FileNotFoundError) and the stale row is dropped from capture_list
    (delete-style self-heal)."""
    host = _host(tmp_path, mode="ok")

    async def scenario() -> str:
        await _connected(host)
        started = await host.call("capture_start", _start(count=2))
        await host.await_capture()
        return started["capture_id"]

    capture_id = asyncio.run(scenario())
    shutil.rmtree(tmp_path / "captures" / capture_id)

    async def refused(operation: str, arguments: dict[str, Any]) -> None:
        with pytest.raises(SeamError) as caught:
            await host.call(operation, arguments)
        assert "not_found" in str(caught.value.code)

    asyncio.run(
        refused(
            "capture_annotate",
            {"capture_id": capture_id, "notes": "too late", "tags": ["x"]},
        )
    )
    asyncio.run(refused("capture_pin", {"capture_id": capture_id}))
    rows = asyncio.run(host.call("capture_list", {}))["captures"]
    assert all(row["capture_id"] != capture_id for row in rows)


def test_series_on_an_unparseable_manifest_is_not_found(tmp_path: Path) -> None:
    """B-F4 (P10 shape): capture_get wraps an unparseable manifest into
    not_found; capture_series refuses the same way — never a raw
    JSONDecodeError."""
    host = _host(tmp_path, mode="ok")

    async def scenario() -> str:
        await _connected(host)
        started = await host.call("capture_start", _start(count=2))
        await host.await_capture()
        return started["capture_id"]

    capture_id = asyncio.run(scenario())
    (tmp_path / "captures" / capture_id / "manifest.json").write_text("{nope")

    async def refused() -> None:
        with pytest.raises(SeamError) as caught:
            await host.call("capture_series", {"capture_id": capture_id})
        assert "not_found" in str(caught.value.code)

    asyncio.run(refused())


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


def test_reload_refuses_while_a_capture_is_in_flight(tmp_path: Path) -> None:
    """I3c-design finding A: the reload guard read a flag nothing ever
    armed — a reload swapped the plugin under a LIVE capture. The guard
    reads the capture slot itself (one source of truth: capture_start
    arms it, the watcher clears it at the terminal state)."""
    host = _host(tmp_path, mode="slow")

    async def scenario() -> None:
        await _connected(host)
        started = await host.call("capture_start", _start(count=1000))
        with pytest.raises(SeamError) as caught:
            await host.reload_plugin(source="test")
        assert "conflict" in str(caught.value.code)
        assert "capture is in flight" in str(caught.value.message)
        await host.call("capture_stop", {"capture_id": started["capture_id"]})
        # AR-12's second half: once the capture settles, the same reload
        # proceeds — the guard read the live slot, and the watcher cleared
        # it at the terminal state.
        reloaded = await host.reload_plugin(source="test")
        assert reloaded["status"] == "reloaded"

    asyncio.run(scenario())


# --- the storage reserve guard (SW-58, AR-10) ---------------------------------


def _reserve(**overrides: Any) -> Any:
    """A retention config whose reserve arms the guard (rules empty — the
    reserve is independent of the rules, the A02 posture)."""
    from benchweave_sdk_server.retention import RetentionConfig

    fields: dict[str, Any] = {"reserve_bytes": 100_000}
    fields.update(overrides)
    return RetentionConfig(**fields)


def test_storage_reserve_refuses_a_count_bound_start_that_would_breach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AR-10(i): a start whose worst case cannot be cleared against the
    configured reserve refuses unavailable before any dispatch, message
    prefixed standalone_storage_reserve:."""
    from benchweave_sdk_server import seam as seam_module

    monkeypatch.setattr(seam_module, "_disk_free_bytes", lambda root: 50_000)
    host = _host(tmp_path, mode="ok", retention=_reserve())

    async def scenario() -> None:
        await _connected(host)
        with pytest.raises(SeamError) as caught:
            await host.call("capture_start", _start(count=400))
        assert "unavailable" in str(caught.value.code)
        assert str(caught.value.message).startswith("standalone_storage_reserve:")
        # The refusal names its numbers (claim discipline).
        assert "50000" in str(caught.value.message)
        assert "100000" in str(caught.value.message)

    asyncio.run(scenario())


def test_storage_reserve_refuses_an_unbounded_duration_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AR-10(ii): a duration bound with no reservation has an unbounded
    worst case — the guard cannot clear it and refuses with the reason,
    naming the declaration that would fix it (missing information blocks
    control, A02).

    Disclosed drift: the vendored schema's conditionals mandate
    capture_limits.max_bytes for BOTH capture verbs (the capability
    conditional and the operations-side not-required-invoke/capture
    conditionals close every load-valid shape without a ceiling), and the
    landed start logic adopts that ceiling as the effective reservation —
    so this input is unreachable through a schema-valid load and the guard
    branch is defense-in-depth. The arm presents the shape the branch
    exists for by clearing the loaded plugin's in-memory limits (the seam
    re-reads the descriptor per start, its own defensive posture)."""
    from benchweave_sdk_server import seam as seam_module

    monkeypatch.setattr(seam_module, "_disk_free_bytes", lambda root: 10**12)
    host = _host(tmp_path, mode="ok", retention=_reserve())
    host.session.plugin.descriptor.pop("capture_limits", None)

    async def scenario() -> None:
        await _connected(host)
        with pytest.raises(SeamError) as caught:
            await host.call("capture_start", _start(duration_s=5))
        assert "unavailable" in str(caught.value.code)
        message = str(caught.value.message)
        assert message.startswith("standalone_storage_reserve:")
        assert "unbounded" in message
        assert "max_bytes" in message

    asyncio.run(scenario())


def test_midrun_reserve_breach_publishes_under_reserve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AR-10(iii): a running capture that reaches the reserve stops and
    FINALISES — state published, stop_reason reserve, byte_length the real
    staged bytes at the stop, never relabelled completed (the B-F2 rule
    extended by membership). The sampler is fixture-scripted: the start
    guard and the first watcher sample clear, the second breaches."""
    from benchweave_sdk_server import seam as seam_module

    calls = {"n": 0}

    def scripted_free(root: Any) -> int:
        calls["n"] += 1
        return 10**12 if calls["n"] <= 2 else 0

    monkeypatch.setattr(seam_module, "_disk_free_bytes", scripted_free)
    host = _host(tmp_path, mode="slow", retention=_reserve())

    async def scenario() -> dict[str, Any]:
        await _connected(host)
        started = await host.call("capture_start", _start(count=120))
        assert started["state"] == "capturing"
        return await host.await_capture()

    outcome = asyncio.run(scenario())
    assert outcome["state"] == "published"
    assert outcome["stop_reason"] == "reserve"
    assert outcome["byte_length"] is not None
    assert 0 < int(outcome["byte_length"]) < 120 * 8
    assert int(outcome["byte_length"]) % 8 == 0


def test_the_storage_guard_is_inert_without_a_configured_reserve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AR-10(iv), the RED control: with the configuration absent the same
    starts proceed — inert-by-default is the parameterised posture (A02:
    no hardcoded reserve ships)."""
    from benchweave_sdk_server import seam as seam_module

    monkeypatch.setattr(seam_module, "_disk_free_bytes", lambda root: 0)
    host = _host(tmp_path, mode="ok")

    async def scenario() -> list[str]:
        await _connected(host)
        reasons: list[str] = []
        for arguments in (_start(count=8), _start(duration_s=0.3)):
            started = await host.call("capture_start", arguments)
            outcome = await host.await_capture()
            assert started["state"] == "capturing"
            assert outcome["state"] == "published"
            reasons.append(str(outcome["stop_reason"]))
        return reasons

    # The duration start finishes its eight appends inside its 0.3 s bound,
    # so both publish completed — the arm's substance is that NEITHER start
    # was refused (the sampler read 0 free the whole time).
    reasons = asyncio.run(scenario())
    assert reasons == ["completed", "completed"]


# --- the shutdown close-down (NFR-O1, AR-11) ----------------------------------


def test_lifespan_exit_settles_an_in_flight_capture(tmp_path: Path) -> None:
    """AR-11: a capture in flight at lifespan exit is settled honestly —
    every event directory published or removed, no *.tmp primaries, the
    index consistent with the root, the outcome recorded."""
    from fastapi.testclient import TestClient

    from benchweave_sdk_server.security import GuardPolicy, new_token
    from benchweave_sdk_server.web import build_app

    host = _host(tmp_path, mode="slow")
    policy = GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )
    app = build_app(host, policy=policy)
    headers = {"authorization": f"Bearer {policy.bearer_token}"}
    with TestClient(app, base_url="http://127.0.0.1:8477") as client:
        client.post("/v1/device_connect", json={"device_id": DEV}, headers=headers)
        started = client.post(
            "/v1/capture_start", json=_start(count=4000), headers=headers
        )
        capture_id = started.json()["data"]["capture_id"]
        assert host.in_flight_capture_id == capture_id  # the settle's premise
    # The lifespan's finally settled the capture before releasing anything.
    root = tmp_path / "captures"
    outcomes = dict(host._capture_outcomes)
    assert capture_id in outcomes
    assert outcomes[capture_id]["state"] in ("published", "aborted")
    assert host._capture is None  # the slot freed
    # No half-written primaries anywhere; every event dir is a publication.
    assert not list(root.rglob("*.tmp"))
    for entry in root.iterdir():
        if entry.is_dir():
            assert (entry / "manifest.json").is_file(), entry
    # The index agrees with the root (a fresh library rebuilds over it).
    from benchweave_sdk_server.library import CaptureLibrary

    library = CaptureLibrary(root)
    try:
        on_disk = {
            entry.name
            for entry in root.iterdir()
            if entry.is_dir() and (entry / "manifest.json").is_file()
        }
        assert {row["capture_id"] for row in library.list_captures()} == on_disk
    finally:
        library.close()


def test_shutdown_settle_escapes_a_hostile_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AR-11's hostile arm: an adapter that ignores the stop and even
    cancellation cannot hold the close-down — the B-F5 escape fires inside
    the stop timeout + margin and the process exits (the settle margin is
    test-shrunk here; it is a host scheduling constant, not a protective
    envelope)."""
    from benchweave_sdk_server import seam as seam_module

    monkeypatch.setattr(seam_module, "_STOP_SETTLE_MARGIN_S", 0.5)
    # stubborn_s outlives the shrunk escape window (0.3 + 0.3 + 0.5 = 1.1 s)
    # but not the test: the settle returns at the escape while the zombie
    # keeps swallowing cancellation until its own deadline — this loop's
    # shutdown then reaps it (the disclosed B-F5 residual; a real process's
    # exit never waits on it, the loop is already gone).
    host = _host(tmp_path, mode="stubborn_ok", stubborn_s=3.0, verb_timeout_ms=300)

    async def scenario() -> dict[str, Any]:
        await _connected(host)
        started = await host.call("capture_start", _start(count=64))
        settle = await host.settle_capture_for_shutdown()
        assert settle is not None
        assert started["capture_id"] == settle["capture_id"]
        return settle

    began = time.monotonic()
    outcome = asyncio.run(scenario())
    elapsed = time.monotonic() - began
    assert outcome["state"] == "aborted"
    assert outcome["stop_reason"] == "stop_timeout"
    assert host._capture is None
    # The escape fired inside the shrunk window (verb 0.3 + grace 0.3 +
    # margin 0.5 = 1.1 s) plus the zombie's own 3 s reap at loop shutdown.
    assert elapsed < 6.0


def test_stdio_settle_aborts_when_the_watchers_loop_is_gone(
    tmp_path: Path,
) -> None:
    """The stdio entry's shape: server.run() returns with a capture in
    flight — its watcher died with that loop, so a fresh-loop settle cannot
    await it. The close-down aborts the capture DIRECTLY (staging discarded,
    the event directory removed — no half-written primary) and records the
    outcome, honestly labelled with the host shutdown."""
    host = _host(tmp_path, mode="slow")

    async def arm() -> str:
        await _connected(host)
        started = await host.call("capture_start", _start(count=4000))
        return str(started["capture_id"])

    capture_id = asyncio.run(arm())  # the loop (and the watcher) died here

    async def settle() -> dict[str, Any] | None:
        return await host.settle_capture_for_shutdown()

    outcome = asyncio.run(settle())  # a FRESH loop
    assert outcome is not None
    assert outcome["capture_id"] == capture_id
    assert outcome["state"] == "aborted"
    assert str(outcome["stop_reason"]).startswith("host_shutdown")
    root = tmp_path / "captures"
    assert not (root / capture_id).exists()
    assert not list(root.rglob("*.tmp"))
    assert host._capture is None


def test_settle_returns_none_with_no_capture_in_flight(tmp_path: Path) -> None:
    host = _host(tmp_path, mode="ok")

    async def settle() -> dict[str, Any] | None:
        return await host.settle_capture_for_shutdown()

    assert asyncio.run(settle()) is None


# --- fold wave 2 (lane 2): the stdio close-down runs on EVERY exit path ------


def _mcp_interrupt_scenario(tmp_path: Path, *, interrupt: bool):
    """Drive the mcp command with a scripted server: run() arms a capture
    (its loop owning — and closing — the watcher, the stdio shape) and
    then either returns normally or raises KeyboardInterrupt the way
    SIGINT unwinds out of run(). Returns (host, invoke-result)."""
    from click.testing import CliRunner

    import benchweave_sdk_server.cli as cli_module
    from benchweave_sdk_server.cli import cli as server_cli

    host = _host(tmp_path, mode="slow")
    project_root = tmp_path / "proj"  # _host already scaffolded this one

    class FakeServer:
        # The fallback builder (issue #440) appends the mode marker to the
        # served instructions — the double carries the attribute.
        instructions = ""

        def run(self) -> None:
            async def arm() -> str:
                await _connected(host)
                started = await host.call("capture_start", _start(count=4000))
                return str(started["capture_id"])

            asyncio.run(arm())
            if interrupt:
                raise KeyboardInterrupt

    def fake_build(seam, authoring=False):  # type: ignore[no-untyped-def]
        assert seam is host
        return FakeServer()

    original_build_seam = cli_module._build_seam
    import benchweave_sdk_server.mcp as mcp_module

    original_build_mcp = mcp_module.build_mcp
    cli_module._build_seam = lambda *args, **kwargs: (host, None)  # type: ignore[assignment]
    mcp_module.build_mcp = fake_build  # type: ignore[assignment]
    escaped: list[BaseException] = []
    try:
        # No runner wrapping: the KeyboardInterrupt must be observable RAW
        # (click's standalone mode would re-cast it as Abort/SystemExit(1)).
        result = CliRunner().invoke(
            server_cli,
            ["mcp", str(project_root)],
            standalone_mode=False,
            catch_exceptions=False,
        )
    except BaseException as exc:  # noqa: BLE001 - the interrupt under test
        escaped.append(exc)
        result = None
    finally:
        cli_module._build_seam = original_build_seam  # type: ignore[assignment]
        mcp_module.build_mcp = original_build_mcp  # type: ignore[assignment]
    return host, (escaped[0] if escaped else result)


def test_the_mcp_entry_settles_an_in_flight_capture_on_interrupt(
    tmp_path: Path,
) -> None:
    """NFR-O1's close-down must run on EVERY exit from server.run() — the
    clean return AND the interrupt paths. SIGINT raises KeyboardInterrupt
    out of run(); without a try/finally the settle and the root lock's
    release never execute, and the guide's claim ("on exit, through an
    interrupt or a terminal close, a capture in flight is settled
    honestly") is false. The interrupt propagates AFTER the cleanup."""
    from click.exceptions import Abort

    host, outcome = _mcp_interrupt_scenario(tmp_path, interrupt=True)
    # click re-casts a KeyboardInterrupt out of run() to its Abort idiom;
    # either surface means the interrupt propagated AFTER the cleanup.
    assert isinstance(outcome, (KeyboardInterrupt, Abort))
    assert host.in_flight_capture_id is None  # the slot freed
    assert any(host._capture_outcomes.values())  # the settle outcome exists
    assert not (tmp_path / "captures" / "library.lock").exists()


def test_the_mcp_entry_settles_on_a_clean_return(tmp_path: Path) -> None:
    """The clean-return arm (kept green): run() returning normally settles
    the capture and releases the root the same way."""
    host, outcome = _mcp_interrupt_scenario(tmp_path, interrupt=False)
    assert not isinstance(outcome, BaseException)
    assert outcome.exit_code == 0
    assert host.in_flight_capture_id is None
    assert any(host._capture_outcomes.values())
    assert not (tmp_path / "captures" / "library.lock").exists()
