# author: Stephen Eaton
"""Issue #394, host-level cells: the byte-stream host's own discipline.

Family B1 (a response-only row served as an unsolicited frame under
``send_receive``) and family C (a genuine SEND mismatch is a
``ConformanceError`` carrying the row key and the hex diff — the exact
one-line format is API, STD-4/R2, pinned verbatim here) plus the host's
recycle/exhaustion/marker/field-set cells and the cycle-start derivation
the selector rides. The SW-61 parity battery lives in
``test_mock_bytestream_parity.py``.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from benchweave_sdk.testing import ConformanceError
from benchweave_sdk_server.session import (
    FrameRow,
    HostOperationContext,
    frame_script,
    load_plugin_project,
    mock_transport_factory,
)
from benchweave_sdk_server.transport import ByteStreamMockHost

FIXTURE_ROWS = [
    FrameRow("identify", b"*IDN?\n", b"DEV,frames,1,1.0.0\n"),
    FrameRow("read", b"AVG?\n", b"2.5\n"),
    FrameRow("write", b"SA\x00\x00@@\n", b"OK\n"),
    FrameRow("readback", b"AVG?\n", b"3.0\n"),
    FrameRow("poll", b"AVG?\n", b"2.5\n"),
    FrameRow("status", None, b"STAT\x00\n"),
]


def _context(timeout_ms: int = 1000) -> HostOperationContext:
    return HostOperationContext("op", timeout_ms=timeout_ms)


async def _send(host: ByteStreamMockHost, data: bytes) -> None:
    context = _context()
    await context.mark_dispatch_started()
    await host.transfer({"kind": "stream_send", "data": data}, context)


async def _receive(host: ByteStreamMockHost, **overrides):
    transaction = {
        "kind": "stream_receive",
        "max_bytes": 128,
        "termination": "lf",
        "exact_bytes": None,
    }
    transaction.update(overrides)
    return await host.transfer(transaction, _context())


def _host(rows=None, **kwargs) -> ByteStreamMockHost:
    return ByteStreamMockHost(rows if rows is not None else list(FIXTURE_ROWS), **kwargs)


# --- family B1: response-only rows served under send_receive -----------------


def test_b1_response_only_row_is_served_as_an_unsolicited_frame() -> None:
    """A response-only row's bytes are released to the inbound stream in row
    order: a receive with no preceding send gets the frame — the quiet line
    answers only once nothing is offered."""

    async def flow() -> None:
        host = _host(
            [FrameRow("boot", None, b"READY\n"), FrameRow("identify", b"*IDN?\n", b"x\n")]
        )
        reply = await _receive(host)
        assert reply == {"data": b"READY\n"}
        # Nothing more is offered: the quiet line, not an error.
        assert await _receive(host) == {"data": b""}

    asyncio.run(flow())


def test_b1_response_only_rows_release_in_row_order_before_a_request_row() -> None:
    async def flow() -> None:
        host = _host(
            [
                FrameRow("boot", None, b"ONE\n"),
                FrameRow("beacon", None, b"TWO\n"),
                FrameRow("poll", b"AVG?\n", b"2.5\n"),
            ]
        )
        assert await _receive(host) == {"data": b"ONE\n"}
        assert await _receive(host) == {"data": b"TWO\n"}
        assert await _receive(host) == {"data": b""}
        await _send(host, b"AVG?\n")
        assert await _receive(host) == {"data": b"2.5\n"}

    asyncio.run(flow())


# --- family C: the genuine SEND mismatch (1 cell + the R2 format pin) --------


def test_c_send_mismatch_carries_the_row_key_and_hex_diff() -> None:
    """The exact-match discipline at frame granularity: the ConformanceError
    names the row and renders both frames hex — the exact one-line format is
    API (R2/STD-4) and changes only as an API change."""

    async def flow() -> None:
        host = _host()
        with pytest.raises(ConformanceError) as caught:
            await _send(host, b"WRONG\x00\n")
        assert str(caught.value) == (
            "frame mismatch at row identify: expected 2a49444e3f0a, got 57524f4e47000a"
        )

    asyncio.run(flow())


# --- the host's own discipline -----------------------------------------------


def test_send_consumes_its_row_and_buffers_the_response() -> None:
    async def flow() -> None:
        host = _host()
        await _send(host, b"*IDN?\n")
        assert await _receive(host) == {"data": b"DEV,frames,1,1.0.0\n"}
        assert await _receive(host) == {"data": b""}

    asyncio.run(flow())


def test_exhausted_send_fails_honestly() -> None:
    """cycles=1: after the single play, a send refuses with the inherited
    honest-exhaustion posture (never a partial or silent pass)."""

    async def flow() -> None:
        host = _host([FrameRow("poll", b"AVG?\n", b"2.5\n")], cycles=1)
        await _send(host, b"AVG?\n")
        with pytest.raises(ConformanceError, match="no scripted exchange remains"):
            await _send(host, b"AVG?\n")

    asyncio.run(flow())


def test_receive_on_a_pending_request_row_is_a_quiet_line() -> None:
    """A receive-before-send against a request-bearing head answers the
    quiet line immediately — the outcome of the backend's quiet window,
    deterministically (§1.5: no wall-clock duration is asserted)."""

    async def flow() -> None:
        host = _host()
        assert await _receive(host) == {"data": b""}

    asyncio.run(flow())


def test_dispatch_marker_is_enforced_for_sends_and_exempt_for_receives() -> None:
    async def flow() -> None:
        host = _host()
        with pytest.raises(ConformanceError, match="dispatch marker"):
            await host.transfer(
                {"kind": "stream_send", "data": b"*IDN?\n"}, _context()
            )
        assert await host.transfer(
            {
                "kind": "stream_receive",
                "max_bytes": 8,
                "termination": "lf",
                "exact_bytes": None,
            },
            _context(),
        ) == {"data": b""}

    asyncio.run(flow())


def test_field_sets_are_strict_and_shared_with_the_backend() -> None:
    """Unspecified or missing fields refuse the shared ValueError — one
    ``_FIELDS`` definition for backend and mock (the SW-61 spirit, made
    structural)."""

    async def flow() -> None:
        host = _host()
        with pytest.raises(ValueError, match="not a section 8.1 stream transaction"):
            await host.transfer(
                {"kind": "stream_send", "data": b"x", "extra": 1}, _context()
            )
        with pytest.raises(ValueError, match="not a section 8.1 stream transaction"):
            await host.transfer({"kind": "i2c_transfer"}, _context())

    asyncio.run(flow())


def test_overlong_unterminated_receive_discards_and_refuses() -> None:
    async def flow() -> None:
        host = _host([FrameRow("poll", b"AVG?\n", b"12345678\n")])
        await _send(host, b"AVG?\n")
        with pytest.raises(ValueError, match="no terminator within 4"):
            await _receive(host, max_bytes=4)
        # The offending run was discarded; the next receive resynchronises
        # on the following bytes.
        assert await _receive(host, max_bytes=128) == {"data": b"5678\n"}

    asyncio.run(flow())


def test_partial_frame_at_the_deadline_times_out_and_retains() -> None:
    async def flow() -> None:
        host = _host(
            [FrameRow("poll", b"AVG?\n", b"2.5"), FrameRow("fin", b"FIN\n", b"\n")]
        )
        await _send(host, b"AVG?\n")
        with pytest.raises(TimeoutError):
            await _receive(host)
        # The partial stays buffered: the next row's terminator completes it.
        await _send(host, b"FIN\n")
        assert await _receive(host) == {"data": b"2.5\n"}

    asyncio.run(flow())


def test_assert_complete_grows_teeth() -> None:
    """Lane 1 F4 + critic F5: the inherited assert_complete is vacuously
    green over the byte-stream host (it reads the exchange deque, which is
    always empty) — conformance.py:65 consumes it, so a run could certify
    exhaustion over an un-exhausted script. It must fail on pending rows
    AND on buffered inbound bytes."""

    async def flow() -> None:
        unexhausted = _host()  # the full FIXTURE_ROWS script, nothing served
        with pytest.raises(ConformanceError, match="scripted rows were not consumed"):
            unexhausted.assert_complete()

        buffered = _host([FrameRow("poll", b"AVG?\n", b"partial-no-terminator")])
        await _send(buffered, b"AVG?\n")  # response buffered, never received
        with pytest.raises(ConformanceError, match="bytes remain buffered"):
            buffered.assert_complete()

        clean = _host([FrameRow("poll", b"AVG?\n", b"2.5\n")])
        await _send(clean, b"AVG?\n")
        await _receive(clean)  # row consumed AND inbound drained
        clean.assert_complete()

    asyncio.run(flow())


def test_cycle_plan_pinned_on_the_core_shapes() -> None:
    """The minimal-period plan (controller ruling 1): [i,A,B,A,B] -> head
    [i], unit [A,B]; the odd capture continues at the captured phase; no
    period evidence -> LoopingMockHost's head-of-one fallback. The full
    derivation battery lives in test_mock_bytestream_cycle.py."""
    from benchweave_sdk_server.session import _cycle_plan

    pair = [
        FrameRow("i", b"I?\n", b"x\n"),
        FrameRow("a0", b"A?\n", b"y\n"),
        FrameRow("b0", b"B?\n", b"z\n"),
        FrameRow("a1", b"A?\n", b"y\n"),
        FrameRow("b1", b"B?\n", b"z\n"),
    ]
    establishment, unit, rotate = _cycle_plan(pair)
    assert (establishment, rotate) == (1, 0)
    assert [row.request for row in unit] == [b"A?\n", b"B?\n"]
    one_shot = [FrameRow("identify", b"A\n", b"x\n"), FrameRow("read", b"B?\n", b"y\n")]
    assert _cycle_plan(one_shot)[0] == 1


def test_the_selector_builds_the_byte_stream_host_for_the_fixture() -> None:
    from benchweave_sdk_server.transport import LoopingMockHost

    plugin = load_plugin_project(
        Path(__file__).resolve().parent.parent / "fixtures" / "binary_frames_plugin"
    )
    factory = mock_transport_factory(plugin)
    host = factory()
    assert isinstance(host, ByteStreamMockHost)
    assert not isinstance(host, LoopingMockHost)
    assert host.pending == 9
    assert host.plays == 1
    # The default dialect keeps today's host: the scaffold's starter.
    from benchweave_sdk.scaffold import create_project

    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "starter"
        create_project(project, "example_plugin")
        starter = load_plugin_project(project)
        assert isinstance(mock_transport_factory(starter)(), LoopingMockHost)


def test_frame_script_decodes_the_fixture_rows() -> None:
    plugin = load_plugin_project(
        Path(__file__).resolve().parent.parent / "fixtures" / "binary_frames_plugin"
    )
    rows = frame_script(plugin)
    assert [row.name for row in rows] == [
        "identify", "read", "write", "readback", "capture",
        "poll", "status", "poll", "status",
    ]
    assert rows[0].request == b"*IDN?\n"
    assert rows[0].response == b"BenchWeave Labs,frames-demo,SIM-BF1,1.0.0\n"
    assert rows[-1].request is None
    assert rows[-1].response == b"STAT\x00\n"
    assert len(rows[4].response) == 1024
    assert rows[6].response == rows[8].response  # two captured poll cycles
