# author: Stephen Eaton
"""Issue #394, family E: RECEIVE outcome parity, mock vs the serial backend
(the shared conformance cells SW-61 named, built here as one parametrized
battery over a host factory — the same wire bytes on both hosts).

Six behaviours × two hosts: ``exact_bytes`` precedence over ``termination``;
``lf`` termination including the terminator; ``crlf`` termination;
no-terminator-within-``max_bytes`` → discard + the same ``ValueError``;
the quiet line → ``{"data": b""}``; a partial frame at the deadline →
``TimeoutError`` with the bytes retained. Outcome asserts only (R6): the
mock's quiet line answers immediately where the backend answers after its
quiet window, and the mock raises the partial-frame ``TimeoutError`` at
once where the backend reaches it at the deadline — no cell asserts a
wall-clock duration. The R1 recycle soak runs here too: ≥50 poll cycles
asserting the frame sequence repeats exactly.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk_server.serial import SerialCaptureServices, SerialLink
from benchweave_sdk_server.session import FrameRow, HostOperationContext
from benchweave_sdk_server.transport import ByteStreamMockHost

_MAX_FRAME = 128


class _ReplyPort:
    """pyserial's surface over a scripted reply table (no real port): a
    write appends its scripted reply, a read returns what is buffered."""

    def __init__(self, replies: dict[bytes, bytes] | None = None) -> None:
        self.inbound = bytearray()
        self.replies = dict(replies or {})
        self.written: list[bytes] = []
        self._data = threading.Event()

    def write(self, data: bytes) -> int | None:
        self.written.append(bytes(data))
        reply = self.replies.get(bytes(data))
        if reply is not None:
            self.inbound += reply
            self._data.set()
        return len(data)

    def read(self, size: int = 1) -> bytes:
        while not self.inbound:
            if not self._data.wait(0.02):
                return b""
            self._data.clear()
        out = bytes(self.inbound[:size])
        del self.inbound[:size]
        return out

    def close(self) -> None:
        self._data.set()


class _MockLeg:
    """The byte-stream mock as a transfer surface fed by scripted rows."""

    name = "bytestream_mock"

    def __init__(self, rows: list[FrameRow]) -> None:
        self._host = ByteStreamMockHost(rows, max_frame_bytes=_MAX_FRAME)

    async def transfer(self, transaction: dict[str, Any], context: Any) -> dict[str, Any]:
        return await self._host.transfer(transaction, context)

    async def feed(self, data: bytes) -> None:
        """Feed extra wire bytes mid-conversation (the partial-frame cell):
        on the mock the only source is the next scripted row's response, so
        the cell scripts the completing row as a request the driver sends."""

    async def close(self) -> None:
        await self._host.close_transport(_context())


class _SerialLeg:
    """The serial backend over the loopback port, the same wire bytes."""

    name = "serial_backend"

    def __init__(self, replies: dict[bytes, bytes]) -> None:
        self._port = _ReplyPort(replies)
        self._link = SerialLink(self._port, quiet_s=0.05)
        self._services = SerialCaptureServices(self._link, max_frame_bytes=_MAX_FRAME)

    async def transfer(self, transaction: dict[str, Any], context: Any) -> dict[str, Any]:
        return await self._services.transfer(transaction, context)

    async def feed(self, data: bytes) -> None:
        """Feed extra wire bytes mid-conversation (the partial-frame cell):
        the port's inbound stream IS the wire."""
        self._port.inbound += data
        self._port._data.set()

    async def close(self) -> None:
        self._link.close()


def _context(timeout_ms: int = 1000) -> HostOperationContext:
    return HostOperationContext("parity", timeout_ms=timeout_ms)


def _exchange(data: bytes, **receive: Any) -> dict[str, Any]:
    transaction = {
        "kind": "stream_exchange",
        "data": data,
        "max_bytes": _MAX_FRAME,
        "termination": "lf",
        "exact_bytes": None,
    }
    transaction.update(receive)
    return transaction


def _receive(**receive: Any) -> dict[str, Any]:
    return {
        "kind": "stream_receive",
        "max_bytes": _MAX_FRAME,
        "termination": "lf",
        "exact_bytes": None,
        **receive,
    }


@pytest.fixture(
    params=[_MockLeg, _SerialLeg],
    ids=["bytestream-mock", "serial-backend"],
)
def leg(request: pytest.FixtureRequest) -> Any:
    return request.param


CMD = b"CMD\n"


def _mock_rows(reply: bytes) -> list[FrameRow]:
    return [FrameRow("cmd", CMD, reply)]


def _serial_replies(reply: bytes) -> dict[bytes, bytes]:
    return {CMD: reply}


# --- the six behaviours ------------------------------------------------------


def test_e1_exact_bytes_takes_precedence_over_termination(leg: Any) -> None:
    """A terminator within the window does not satisfy an exact-bound
    receive: the exact count wins on both hosts."""

    async def flow() -> None:
        surface = (
            leg(_mock_rows(b"AB\nCD"))
            if leg is _MockLeg
            else leg(_serial_replies(b"AB\nCD"))
        )
        try:
            context = _context()
            await context.mark_dispatch_started()
            reply = await surface.transfer(_exchange(CMD, exact_bytes=2), context)
            assert reply == {"data": b"AB"}
        finally:
            await surface.close()

    asyncio.run(flow())


def test_e2_lf_termination_includes_the_terminator(leg: Any) -> None:
    async def flow() -> None:
        surface = (
            leg(_mock_rows(b"3.3\nnext"))
            if leg is _MockLeg
            else leg(_serial_replies(b"3.3\nnext"))
        )
        try:
            context = _context()
            await context.mark_dispatch_started()
            reply = await surface.transfer(_exchange(CMD), context)
            assert reply == {"data": b"3.3\n"}
        finally:
            await surface.close()

    asyncio.run(flow())


def test_e3_crlf_termination_matches_the_two_byte_terminator(leg: Any) -> None:
    async def flow() -> None:
        surface = (
            leg(_mock_rows(b"OK\r\nrest"))
            if leg is _MockLeg
            else leg(_serial_replies(b"OK\r\nrest"))
        )
        try:
            context = _context()
            await context.mark_dispatch_started()
            reply = await surface.transfer(_exchange(CMD, termination="crlf"), context)
            assert reply == {"data": b"OK\r\n"}
        finally:
            await surface.close()

    asyncio.run(flow())


def test_e4_no_terminator_within_max_bytes_discards_and_refuses(leg: Any) -> None:
    """An overlong unterminated run is discarded and refused with the SAME
    ValueError on both hosts; the following bytes resynchronise."""

    async def flow() -> None:
        surface = (
            leg(_mock_rows(b"123456\n"))
            if leg is _MockLeg
            else leg(_serial_replies(b"123456\n"))
        )
        try:
            context = _context()
            await context.mark_dispatch_started()
            with pytest.raises(ValueError, match="no terminator within 4 bytes"):
                await surface.transfer(_exchange(CMD, max_bytes=4), context)
            follow = await surface.transfer(_receive(max_bytes=8), _context())
            assert follow == {"data": b"56\n"}
        finally:
            await surface.close()

    asyncio.run(flow())


def test_e5_a_quiet_line_answers_empty_not_an_error(leg: Any) -> None:
    async def flow() -> None:
        surface = (
            leg([FrameRow("quiet-cmd", CMD, b"")])
            if leg is _MockLeg
            else leg({})
        )
        try:
            started = time.monotonic()
            reply = await surface.transfer(_receive(), _context(timeout_ms=2000))
            assert reply == {"data": b""}
            # Outcome-only (R6): generous sanity bound, no duration assert —
            # the backend answers after its quiet window, the mock at once.
            assert time.monotonic() - started < 1.5
        finally:
            await surface.close()

    asyncio.run(flow())


def test_e6_partial_frame_at_the_deadline_is_retained(leg: Any) -> None:
    """A partial frame at the deadline raises TimeoutError on both hosts
    and the buffered bytes survive to complete the next receive."""

    async def flow() -> None:
        if leg is _MockLeg:
            # The mock's wire is the script: the partial comes from one row,
            # the completing bytes from the next row's response.
            surface = leg(
                [FrameRow("go", b"GO\n", b"3.3"), FrameRow("fin", b"FIN\n", b"\n")]
            )
        else:
            surface = leg({b"GO\n": b"3.3", b"FIN\n": b"\n"})
        try:
            context = _context(timeout_ms=150)
            await context.mark_dispatch_started()
            with pytest.raises(TimeoutError):
                await surface.transfer(_exchange(b"GO\n"), context)
            follow = _context()
            await follow.mark_dispatch_started()
            if leg is _MockLeg:
                reply = await surface.transfer(_exchange(b"FIN\n"), follow)
            else:
                await surface.feed(b"\n")
                reply = await surface.transfer(_receive(), follow)
            assert reply == {"data": b"3.3\n"}
        finally:
            await surface.close()

    asyncio.run(flow())


# --- R1: the recycle soak over the mock (≥50 cycles, exact sequence) ---------


def test_r1_fifty_poll_cycles_repeat_the_exact_frame_sequence() -> None:
    """R1's falsifier: the byte-stream tail restore must not drift from
    LoopingMockHost's. A drain-then-poll server over a [poll, status] cycle
    must observe the exact same frame sequence on every cycle."""

    async def flow() -> None:
        host = ByteStreamMockHost(
            [
                FrameRow("identify", b"*IDN?\n", b"DEV,1\n"),
                FrameRow("poll", b"AVG?\n", b"2.5\n"),
                FrameRow("status", None, b"STAT\x00\n"),
            ],
            max_frame_bytes=_MAX_FRAME,
        )
        context = _context()
        await context.mark_dispatch_started()
        await host.transfer(_exchange(b"*IDN?\n"), context)
        for cycle in range(51):
            # The drain idiom: receive until the quiet line, then poll.
            drained = []
            while True:
                probe = await host.transfer(_receive(), _context())
                if probe["data"] == b"":
                    break
                drained.append(probe["data"])
            assert drained == ([b"STAT\x00\n"] if cycle else []), (
                f"cycle {cycle}: the status frame must release exactly once "
                "per cycle, at the first drain"
            )
            poll_context = _context()
            await poll_context.mark_dispatch_started()
            reply = await host.transfer(_exchange(b"AVG?\n"), poll_context)
            assert reply == {"data": b"2.5\n"}, f"cycle {cycle}"
        assert host.plays >= 51
        await host.close_transport(context)

    asyncio.run(flow())


# The fixture's own cycle start (regression pin for the selector's
# establishment derivation over the real fixture file).


def test_the_fixture_script_recycles_its_poll_tail_not_its_head(tmp_path: Path) -> None:
    from benchweave_sdk_server.session import (
        _cycle_start,
        frame_script,
        load_plugin_project,
    )

    plugin = load_plugin_project(
        Path(__file__).resolve().parent.parent / "fixtures" / "binary_frames_plugin"
    )
    rows = frame_script(plugin)
    assert _cycle_start(rows) == 5, "head = identify..capture; cycle = poll+status"
    del tmp_path  # the cell needs no capture root
