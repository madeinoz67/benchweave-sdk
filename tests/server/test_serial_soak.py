"""AR-2: the structural flatness soak — link → services → writer.

A 10-second soak at >=200 KiB/s through the full path asserts the four
pre-committed arms: the ring stays within capacity at every checkpoint;
staged bytes equal appended bytes (checksum); staging chunk-file count
stays <= total/64 KiB + 1 (block buffering); after finalise, staging is
gone and the manifest digest matches. Loopback only — no pyserial, no real
port, no hardware claim (the evidence boundary the design record states).
"""

from __future__ import annotations

import asyncio
import hashlib
import struct
import threading
import time
from pathlib import Path

import pytest

from benchweave_sdk_server.serial import SerialCaptureServices, SerialLink
from benchweave_sdk_server.session import HostOperationContext

_FRAME = 262  # the fork plugin's max_frame_bytes class
_RATE = 200 * 1024  # bytes per second, the design's rate class
_SOAK_S = 10.0
_BLOCK = 64 * 1024


class FeedPort:
    """A loopback fed by a producer thread at the measured rate."""

    def __init__(self) -> None:
        self.inbound = bytearray()
        self.written: list[bytes] = []
        self.reads = 0
        self.closes = 0
        self.produced_bytes = 0
        self.produced_frames = 0
        self.sequence = 0
        self._data = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def write(self, data: bytes) -> int | None:
        self.written.append(bytes(data))
        return len(data)

    def read(self, size: int = 1) -> bytes:
        self.reads += 1
        while not self.inbound:
            if self._stop.is_set() or not self._data.wait(0.05):
                return b""
            self._data.clear()
        out = bytes(self.inbound[:size])
        del self.inbound[:size]
        return out

    def close(self) -> None:
        self.closes += 1
        self._stop.set()
        self._data.set()

    def start(self, rate: float) -> None:
        interval = _FRAME / rate

        def produce() -> None:
            next_at = time.monotonic()
            while not self._stop.is_set():
                body = bytes([self.sequence % 256]) * (_FRAME - 4)
                frame = struct.pack("<I", self.sequence % 0xFFFF) + body
                self.inbound += frame
                self.sequence += 1
                self.produced_bytes += _FRAME
                self.produced_frames += 1
                self._data.set()
                next_at += interval
                delay = next_at - time.monotonic()
                if delay > 0:
                    self._stop.wait(delay)

        self._thread = threading.Thread(target=produce, daemon=True)
        self._thread.start()


def _ctx(timeout_s: float = 5.0) -> HostOperationContext:
    return HostOperationContext(f"soak-{time.monotonic_ns()}", timeout_ms=int(timeout_s * 1000))


@pytest.mark.timing
def test_ar2_ten_second_soak_keeps_every_structural_bound(tmp_path: Path) -> None:
    port = FeedPort()
    link = SerialLink(port, quiet_s=0.1)
    services = SerialCaptureServices(link, max_frame_bytes=_FRAME, capture_root=tmp_path)
    port.start(_RATE)
    received = bytearray()
    digest = hashlib.sha256()
    ring_seen = 0
    chunk_peak = 0

    async def soak() -> None:
        nonlocal ring_seen, chunk_peak
        started = time.monotonic()
        while time.monotonic() - started < _SOAK_S:
            context = _ctx()
            reply = await services.transfer(
                {
                    "kind": "stream_receive",
                    "max_bytes": _FRAME,
                    "termination": "lf",
                    "exact_bytes": _FRAME,
                },
                context,
            )
            frame = reply["data"]
            assert len(frame) == _FRAME
            received.extend(frame)
            digest.update(frame)
            await services.artifact_append("cap-soak", frame, context)
            staging = tmp_path / "cap-soak" / "staging"
            if staging.is_dir():
                chunk_peak = max(chunk_peak, len(list(staging.iterdir())))
            ring_seen = max(ring_seen, link.ring_length())

    asyncio.run(soak())
    port._stop.set()
    port._data.set()
    if port._thread is not None:
        port._thread.join(timeout=2)
    # Drain whatever the producer staged after the last receive.
    while link.ring_length() > 0:
        reply = asyncio.run(
            services.transfer(
                {
                    "kind": "stream_receive",
                    "max_bytes": _FRAME,
                    "termination": "lf",
                    "exact_bytes": _FRAME,
                },
                _ctx(),
            )
        )
        received += reply["data"]
        digest.update(reply["data"])
        asyncio.run(services.artifact_append("cap-soak", reply["data"], _ctx()))
    elapsed = _SOAK_S
    throughput = port.produced_bytes / elapsed
    manifest = asyncio.run(
        services.artifact_finalise(
            "cap-soak",
            {"format": "raw_binary", "started_at": "2026-10-04T00:00:00Z"},
            _ctx(),
        )
    )
    # The producer actually sustained the rate class.
    assert throughput >= _RATE, f"producer sustained {throughput:.0f} B/s, wanted >= {_RATE}"
    # Arm 1: the ring stayed within capacity at every checkpoint.
    assert ring_seen <= link.ring_capacity
    # Arm 2: staged bytes == appended bytes (checksum); ring never lost one.
    assert len(received) == port.produced_bytes, (
        f"received {len(received)} of {port.produced_bytes} produced bytes"
    )
    # Arm 3: staging chunk files bounded by the block buffer.
    assert chunk_peak <= port.produced_bytes / _BLOCK + 1, (
        f"peak staging files {chunk_peak} exceeded bytes/64KiB + 1"
    )
    # Arm 4: finalise — staging gone, manifest digest matches the bytes.
    staging = tmp_path / "cap-soak" / "staging"
    assert not staging.exists(), "finalise removes staging"
    assert manifest["byte_length"] == len(received)
    assert manifest["sha256"] == digest.hexdigest()
    primary = tmp_path / "cap-soak" / "cap-soak.bin"
    assert primary.read_bytes() == bytes(received)
    asyncio.run(services.close_transport(_ctx()))
