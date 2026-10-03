"""SerialCaptureServices: the eight-member CaptureServices composition (AR-1).

The guide's conformance cells re-instantiated over SerialCaptureServices
with an in-process loopback Transport — one suite, two backends: the same
cells against ``MockHost`` stay green (the two-backend arm below). AR-1's
RED control: a field-set-validation arm — an extra-field transaction must
be refused BEFORE any byte is written; the loopback records writes and must
show zero.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.scaffold import create_project
from benchweave_sdk.testing import ConformanceError, MockContext, MockHost
from benchweave_sdk_server.serial import SerialCaptureServices, SerialLink

_FRAME = 128  # the scaffold descriptor's max_frame_bytes


def _services(
    port: Any,
    *,
    quiet_s: float = 0.05,
    capture_root: Path | None = None,
    evidence_path: Path | None = None,
    max_frame_bytes: int = _FRAME,
) -> SerialCaptureServices:
    link = SerialLink(port, quiet_s=quiet_s)
    return SerialCaptureServices(
        link,
        max_frame_bytes=max_frame_bytes,
        capture_root=capture_root,
        evidence_path=evidence_path,
    )


def _receive(**fields: Any) -> dict[str, Any]:
    return {
        "kind": "stream_receive",
        "max_bytes": 64,
        "termination": "lf",
        "exact_bytes": None,
        **fields,
    }


def _ctx(timeout_s: float = 2.0) -> Any:
    from benchweave_sdk_server.session import HostOperationContext

    return HostOperationContext(f"op-{time.monotonic_ns()}", timeout_ms=int(timeout_s * 1000))


def _run(coro: Any) -> Any:
    return asyncio.run(coro)



class LoopbackPort:
    """pyserial's surface: ``read`` returns what is buffered, blocking up to
    its own short timeout; ``write`` may append a scripted reply."""

    def __init__(
        self,
        inbound: bytes = b"",
        replies: dict[bytes, bytes] | None = None,
        read_timeout: float = 0.05,
    ) -> None:
        self.inbound = bytearray(inbound)
        self.replies = dict(replies or {})
        self.written: list[bytes] = []
        self.reads = 0
        self.closes = 0
        self.read_timeout = read_timeout
        self._data = threading.Event()
        self._fail_read: Exception | None = None

    def write(self, data: bytes) -> int | None:
        self.written.append(bytes(data))
        reply = self.replies.get(bytes(data))
        if reply is not None:
            self.inbound += reply
            self._data.set()
        return len(data)

    def read(self, size: int = 1) -> bytes:
        self.reads += 1
        if self._fail_read is not None:
            error, self._fail_read = self._fail_read, None
            raise error
        while not self.inbound:
            if not self._data.wait(self.read_timeout):
                return b""
            self._data.clear()
        out = bytes(self.inbound[:size])
        del self.inbound[:size]
        return out

    def close(self) -> None:
        self.closes += 1
        self._data.set()


class ShortWritePort:
    """A port whose write reports ``sent`` bytes, whatever it was given."""

    def __init__(self, sent: int | None) -> None:
        self.written: list[bytes] = []
        self.reads = 0
        self.inbound = bytearray(b"reply\n")
        self.sent = sent

    def write(self, data: bytes) -> int | None:
        self.written.append(bytes(data))
        return self.sent

    def read(self, size: int = 1) -> bytes:
        self.reads += 1
        out = bytes(self.inbound[:size])
        del self.inbound[:size]
        if not out:
            # The port's own short timeout — without it a leaked reader
            # thread hot-spins on an always-empty port.
            time.sleep(0.001)
        return out

    def close(self) -> None:
        pass


def test_all_eight_members_of_the_capture_services_protocol() -> None:

    for name in (
        "monotonic", "utc_now", "transfer", "close_transport", "record_evidence",
        "artifact_append", "artifact_finalise", "artifact_abort",
    ):
        assert callable(getattr(SerialCaptureServices, name)), name


def test_a_scaffolded_plugin_runs_end_to_end_through_the_services(tmp_path: Path) -> None:
    create_project(tmp_path / "proj", "serialdemo_plugin")
    sys.path.insert(0, str(tmp_path / "proj" / "src"))
    try:
        adapter = importlib.import_module("serialdemo_plugin.adapter")
        port = LoopbackPort(replies={
            b"ID?\n": b"SDK Example,demo,SIM001,1.0.0\n",
            b"V?\n": b"3.3\n",
        })
        services = _services(port, max_frame_bytes=128)

        async def run() -> list[dict[str, Any]]:
            plugin = adapter.create_plugin()
            await plugin.open({}, services, _ctx())
            results = []
            for verb, args in (("identify", {}), ("read", {"parameter": "voltage"})):
                context = _ctx()
                request = {
                    "operation_id": context.operation_id,
                    "verb": verb,
                    "arguments": args,
                }
                results.append(await plugin.execute(request, context))
            await plugin.close(_ctx())
            return results

        identify, read = _run(run())
    finally:
        sys.path.remove(str(tmp_path / "proj" / "src"))
        for name in [m for m in sys.modules if m.startswith("serialdemo_plugin")]:
            del sys.modules[name]
    assert identify["status"] == "ok" and identify["data"]["serial"] == "SIM001"
    assert read["status"] == "ok" and read["data"]["value"] == pytest.approx(3.3)
    assert port.written == [b"ID?\n", b"V?\n"] and port.closes == 1


def test_exact_bytes_takes_precedence_and_frames_a_binary_protocol() -> None:
    port = LoopbackPort(b"\xf0\xa1\x03\x02AB\n\xf0")
    services = _services(port)
    header = _run(services.transfer(_receive(exact_bytes=4), _ctx()))
    body = _run(services.transfer(_receive(exact_bytes=2), _ctx()))
    line = _run(services.transfer(_receive(), _ctx()))
    assert (header, body, line) == (
        {"data": b"\xf0\xa1\x03\x02"},
        {"data": b"AB"},
        {"data": b"\n"},
    )
    _run(services.close_transport(_ctx()))


@pytest.mark.parametrize("exact", [None, 4])
def test_a_quiet_line_answers_empty_before_the_deadline(exact: int | None) -> None:
    """No bytes at all within the quiet window: nothing offered, b'' —
    the drain-end answer the telemetry path reads as 'no more data'."""
    services = _services(LoopbackPort(), quiet_s=0.02)
    started = time.monotonic()
    assert _run(services.transfer(_receive(exact_bytes=exact), _ctx(5.0))) == {"data": b""}
    assert time.monotonic() - started < 2.0


def test_an_incomplete_frame_is_never_returned_and_is_kept_for_the_next_receive() -> None:
    port = LoopbackPort(b"3.3")
    services = _services(port)
    with pytest.raises(TimeoutError):
        _run(services.transfer(_receive(), _ctx(0.05)))
    port.inbound += b"\r\n"
    reply = _run(services.transfer(_receive(termination="crlf"), _ctx()))
    assert reply == {"data": b"3.3\r\n"}


def test_a_line_longer_than_max_bytes_is_refused_and_discarded() -> None:
    port = LoopbackPort(b"123456\nOK\n")
    services = _services(port)
    with pytest.raises(ValueError, match="no terminator"):
        _run(services.transfer(_receive(max_bytes=4), _ctx()))
    tail = _run(services.transfer(_receive(max_bytes=8), _ctx()))
    assert tail == {"data": b"56\n"}


@pytest.mark.parametrize(
    "transaction",
    [
        {"kind": "stream_exchange", "data": b"X\n", "max_bytes": 8, "termination": "lf"},
        {**_receive(), "timeout_ms": 5},
        _receive(termination="eom"),
        _receive(exact_bytes=65),
        _receive(max_bytes=0),
        _receive(max_bytes=True),
        {"kind": "stream_send", "data": "text"},
        {"kind": "can_send", "id": 1, "extended": False, "fd": False, "data": b""},
    ],
)
def test_transactions_outside_section_8_1_are_refused_before_any_io(
    transaction: dict[str, Any],
) -> None:
    """AR-1's RED control: the refused transaction writes ZERO bytes —
    grammar validation runs before any I/O. (The link's own reader thread
    drains the port independently by design — the fork's model — so reads
    are not zero; the WRITE log is the I/O that must not happen.)"""
    port = LoopbackPort(b"ignored\n")
    services = _services(port)
    with pytest.raises(ValueError):
        _run(services.transfer(transaction, _ctx()))
    assert port.written == []


def test_a_cancelled_operation_transmits_nothing_and_a_closed_link_is_a_connection_error() -> None:
    port = LoopbackPort()
    services = _services(port)
    context = _ctx()
    context.cancel()
    with pytest.raises(TimeoutError):
        _run(services.transfer({"kind": "stream_send", "data": b"X"}, context))
    assert port.written == []
    _run(services.close_transport(_ctx()))
    with pytest.raises(ConnectionError):
        _run(services.transfer({"kind": "stream_send", "data": b"X"}, _ctx()))


@pytest.mark.parametrize("sent", [0, 3])
@pytest.mark.parametrize("kind", ["stream_send", "stream_exchange"])
def test_a_short_write_is_a_connection_error_and_nothing_is_read(kind: str, sent: int) -> None:
    """pyserial returns a short count without raising when a pending write
    is cancelled or under write_timeout=0; part of a frame on the wire
    must not pass as sent."""
    port = ShortWritePort(sent)
    services = _services(port)
    transaction: dict[str, Any] = {"kind": kind, "data": b"PING"}
    if kind == "stream_exchange":
        transaction = {**_receive(), **transaction}
    with pytest.raises(ConnectionError, match=f"reported {sent} of 4 bytes"):
        _run(services.transfer(transaction, _ctx()))


def test_a_port_that_reports_no_count_is_trusted() -> None:
    port = ShortWritePort(None)
    services = _services(port)
    reply = _run(services.transfer({"kind": "stream_send", "data": b"PING"}, _ctx()))
    assert reply == {}
    assert port.written == [b"PING"]


def test_capture_block_buffering_flushes_at_64k_and_finalise_publishes(tmp_path: Path) -> None:
    port = LoopbackPort()
    services = _services(port, capture_root=tmp_path)
    block = 64 * 1024
    first = bytes(range(256)) * 256  # 64 KiB
    _run(services.artifact_append("cap-block", first, _ctx()))
    # exactly at the flush boundary: one staged chunk, empty buffer
    staging = tmp_path / "cap-block" / "staging"
    assert sorted(p.name for p in staging.iterdir()) == ["0.part"]
    _run(services.artifact_append("cap-block", b"\x01\x02\x03", _ctx()))
    assert sorted(p.name for p in staging.iterdir()) == ["0.part"], "the tail stays buffered"
    manifest = _run(
        services.artifact_finalise(
            "cap-block",
            {"format": "raw_binary", "started_at": "2026-10-04T00:00:00Z"},
            _ctx(),
        )
    )
    assert manifest["byte_length"] == block + 3
    assert manifest["sha256"] == hashlib.sha256(first + b"\x01\x02\x03").hexdigest()
    assert not staging.exists(), "finalise removes staging"


def test_abort_discards_the_buffer_and_publishes_nothing(tmp_path: Path) -> None:
    port = LoopbackPort()
    services = _services(port, capture_root=tmp_path)
    _run(services.artifact_append("cap-abort", b"\x01" * 100, _ctx()))  # buffered only
    _run(services.artifact_abort("cap-abort"))
    assert not (tmp_path / "cap-abort").exists(), "a never-flushed capture leaves no directory"
    with pytest.raises(ValueError):
        _run(
            services.artifact_finalise(
                "cap-abort",
                {"format": "raw_binary", "started_at": "2026-10-04T00:00:00Z"},
                _ctx(),
            )
        )


def test_two_sequential_captures_on_one_services_object(tmp_path: Path) -> None:
    port = LoopbackPort()
    services = _services(port, capture_root=tmp_path)
    for name in ("cap-1", "cap-2"):
        _run(services.artifact_append(name, b"\x07\x08", _ctx()))
        manifest = _run(
            services.artifact_finalise(
                name,
                {"format": "raw_binary", "started_at": "2026-10-04T00:00:00Z"},
                _ctx(),
            )
        )
        assert manifest["byte_length"] == 2
    assert (tmp_path / "cap-1" / "cap-1.bin").read_bytes() == b"\x07\x08"
    assert (tmp_path / "cap-2" / "cap-2.bin").read_bytes() == b"\x07\x08"


def test_evidence_is_appended_as_json_lines_and_host_fields_win(tmp_path: Path) -> None:
    path = tmp_path / "evidence.jsonl"
    port = LoopbackPort()
    services = _services(port, evidence_path=path)
    _run(
        services.record_evidence(
            {"kind": "device_error", "entry": {"code": "E1", "message": "m"}},
            _ctx(),
        )
    )
    assert services.evidence[0]["operation_id"].startswith("op-")
    assert services.evidence[0]["at"].endswith("Z")
    assert path.read_text(encoding="utf-8").count("\n") == 1
    _run(
        services.record_evidence(
            {"kind": "probe", "at": "caller", "operation_id": "spoof"},
            _ctx(),
        )
    )
    assert services.evidence[1]["operation_id"].startswith("op-")
    assert services.evidence[1]["at"].endswith("Z")


def test_two_backends_agree_on_the_adapters_exchange_flow() -> None:
    """One suite, two backends (AR-1): the scaffolded adapter's identify
    flow produces the same envelope over MockHost and over the serial
    services; the MockHost conformance cells stay green."""
    async def over_mock() -> dict[str, Any]:
        host = MockHost([
            (
                {
                    "kind": "stream_exchange",
                    "data": b"ID?\n",
                    "max_bytes": 128,
                    "termination": "lf",
                    "exact_bytes": None,
                },
                {"data": b"SDK Example,demo,SIM001,1.0.0\n"},
            )
        ])
        context = MockContext("identify", deadline_monotonic=host.monotonic() + 2.0)
        await context.mark_dispatch_started()
        return await host.transfer(
            {
                "kind": "stream_exchange",
                "data": b"ID?\n",
                "max_bytes": 128,
                "termination": "lf",
                "exact_bytes": None,
            },
            context,
        )

    async def over_serial() -> dict[str, Any]:
        port = LoopbackPort(replies={b"ID?\n": b"SDK Example,demo,SIM001,1.0.0\n"})
        services = _services(port, max_frame_bytes=128)
        return await services.transfer(
            {
                "kind": "stream_exchange",
                "data": b"ID?\n",
                "max_bytes": 128,
                "termination": "lf",
                "exact_bytes": None,
            },
            _ctx(),
        )

    assert _run(over_mock()) == _run(over_serial())
    # The MockHost cells this suite mirrors stay green: deadline/cancel
    # refusal before the script is consumed, and the exhausted/mismatch
    # ConformanceError discipline.
    host = MockHost([])
    context = MockContext("gone", deadline_monotonic=host.monotonic() + 1.0)
    context.cancel()
    with pytest.raises(TimeoutError):
        _run(host.transfer({"kind": "stream_send", "data": b"X"}, context))
    live = MockContext("live", deadline_monotonic=host.monotonic() + 1.0)
    with pytest.raises(ConformanceError):
        _run(host.transfer({"kind": "stream_send", "data": b"X"}, live))


def test_the_capture_reservation_rides_the_services_configuration(tmp_path: Path) -> None:
    """A02: the capture reservation is the composer's configuration, not a
    silent default — at the design's rate class a default 16 MiB writer
    would cap a serial capture at about 80 seconds."""
    port = LoopbackPort()
    services = SerialCaptureServices(
        SerialLink(port),
        max_frame_bytes=64,
        capture_root=tmp_path,
        capture_max_bytes=8 * 1024,
    )
    # Mid-stream: a single append that crosses the reservation is refused
    # at append (the services guard), naming the reservation.
    _run(services.artifact_append("cap-bound", b"\x01" * (4 * 1024), _ctx()))
    with pytest.raises(ValueError, match="max_bytes reservation"):
        _run(services.artifact_append("cap-bound", b"\x02" * (8 * 1024), _ctx()))
    # Tail: a sub-threshold byte that crosses the reservation refuses at
    # finalise (the writer's own check at the last flush).
    services2 = SerialCaptureServices(
        SerialLink(LoopbackPort()),
        max_frame_bytes=64,
        capture_root=tmp_path / "tail",
        capture_max_bytes=8 * 1024,
    )
    _run(services2.artifact_append("cap-tail", b"\x01" * (8 * 1024), _ctx()))
    _run(services2.artifact_append("cap-tail", b"\x01", _ctx()))
    with pytest.raises(ValueError, match="max_bytes reservation"):
        _run(
            services2.artifact_finalise(
                "cap-tail",
                {"format": "raw_binary", "started_at": "2026-10-04T00:00:00Z"},
                _ctx(),
            )
        )
