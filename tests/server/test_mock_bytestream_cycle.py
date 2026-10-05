# author: Stephen Eaton
"""Issue #394 fold: the minimal-period cycle model (controller ruling 1) and
the release-once rule (lane 1 F3 + critic F7).

The LAST-repeat heuristic is structurally broken: any row after the last
repeated request is by construction novel, so the derived cycle can never
contain a repeating multi-request cycle — an alternating-channel device
(``[ID, CH0, CH1] x3``, the reporter's own class) fails on the second sweep
with a mismatch that blames a correct adapter. The replacement: the cycle
unit is the shortest suffix-unit that, repeated from the establishment
boundary, regenerates the captured tail exactly, with at least two full
units of evidence; no derivable period (a truncated capture) falls back to
``LoopingMockHost``'s own rule — establishment of one, the whole tail the
cycle. A mid-unit capture end continues at the captured phase (the rotated
restore). Response-only rows release ONCE per cycle: the drain quiets
after the burst instead of re-releasing it forever.
"""

from __future__ import annotations

import asyncio

import pytest

from benchweave_sdk.testing import ConformanceError
from benchweave_sdk_server.session import FrameRow, HostOperationContext
from benchweave_sdk_server.transport import ByteStreamMockHost


def _context(timeout_ms: int = 1000) -> HostOperationContext:
    return HostOperationContext("cycle", timeout_ms=timeout_ms)


async def _send(host: ByteStreamMockHost, data: bytes) -> bytes:
    context = _context()
    await context.mark_dispatch_started()
    await host.transfer({"kind": "stream_send", "data": data}, context)
    reply = await host.transfer(
        {
            "kind": "stream_receive",
            "max_bytes": 128,
            "termination": "lf",
            "exact_bytes": None,
        },
        _context(),
    )
    return reply["data"]


async def _send_only(host: ByteStreamMockHost, data: bytes) -> None:
    """One command frame, no ack receive — for silent-ack commands whose
    response burst shares the stream (the drain collects it)."""
    context = _context()
    await context.mark_dispatch_started()
    await host.transfer({"kind": "stream_send", "data": data}, context)


async def _drain(host: ByteStreamMockHost, bound: int = 64) -> list[bytes]:
    """Drain until the quiet line, BOUNDED: a drain that never quiets (the
    hot spin the fold targets) fails the bound instead of hanging."""
    frames: list[bytes] = []
    for _ in range(bound):
        reply = await host.transfer(
            {
                "kind": "stream_receive",
                "max_bytes": 128,
                "termination": "lf",
                "exact_bytes": None,
            },
            _context(),
        )
        if reply["data"] == b"":
            return frames
        frames.append(reply["data"])
    raise AssertionError(f"the drain did not quiet within {bound} frames: {frames}")


def _row(name: str, request: bytes | None, response: bytes) -> FrameRow:
    return FrameRow(name=name, request=request, response=response)


def _served_host(rows: list[FrameRow]) -> ByteStreamMockHost:
    """The host built the way ``mock_transport_factory`` builds it — through
    the session module's CURRENT cycle plan (the pre-fold stand-in is the
    LAST-repeat heuristic, so the probes exercise the wiring that serves
    real plugins, not a hand-picked establishment)."""
    from benchweave_sdk_server import session as session_module

    plan = getattr(session_module, "_cycle_plan", None)
    if plan is not None:
        establishment, cycle, rotate = plan(rows)
        return ByteStreamMockHost(
            rows,
            establishment=establishment,
            cycle=cycle,
            cycle_rotate=rotate,
            max_frame_bytes=128,
        )
    return ByteStreamMockHost(
        rows,
        establishment=session_module._cycle_start(rows),
        max_frame_bytes=128,
    )


def _sweep(rows: list[FrameRow], commands: list[bytes], expect: list[bytes]) -> None:
    """Drive ``commands`` in order, asserting each response — the sweep that
    must serve past the captured evidence."""

    async def flow() -> None:
        host = _served_host(rows)
        for command, wanted in zip(commands, expect, strict=True):
            assert await _send(host, command) == wanted, command

    asyncio.run(flow())


# --- the alternating-channel device class (the critic's probe) ---------------


def test_alternating_channels_serve_past_two_full_sweeps() -> None:
    """[ID, CH0, CH1] x3 — the reporter's own device class. The cycle unit
    is [CH0, CH1]; eight alternating commands (past the captured two full
    channel sweeps) all answer."""
    rows = [_row("id", b"ID?\n", b"DEV\n")]
    for sweep in range(3):
        rows.append(_row(f"ch0-{sweep}", b"CH0?\n", b"C0\n"))
        rows.append(_row(f"ch1-{sweep}", b"CH1?\n", b"C1\n"))
    commands = [b"ID?\n"] + [b"CH0?\n", b"CH1?\n"] * 8
    expect = [b"DEV\n"] + [b"C0\n", b"C1\n"] * 8
    _sweep(rows, commands, expect)


def test_p1_repeating_pair_serves_past_the_capture() -> None:
    """Lane 1's P1: [i, A?, B?, A?, B?] — the pair repeats indefinitely."""
    rows = [
        _row("i", b"I?\n", b"ok\n"),
        _row("a0", b"A?\n", b"ra\n"),
        _row("b0", b"B?\n", b"rb\n"),
        _row("a1", b"A?\n", b"ra\n"),
        _row("b1", b"B?\n", b"rb\n"),
    ]
    commands = [b"I?\n"] + [b"A?\n", b"B?\n"] * 6
    expect = [b"ok\n"] + [b"ra\n", b"rb\n"] * 6
    _sweep(rows, commands, expect)


def test_odd_capture_continues_at_the_captured_phase() -> None:
    """[i, A, B, A, B, A] — two and a half captured units. The continuation
    must resume at the phase the capture ended on: after the captured A,
    the next scripted request is B (not A)."""
    rows = [
        _row("i", b"I?\n", b"ok\n"),
        _row("a0", b"A?\n", b"ra\n"),
        _row("b0", b"B?\n", b"rb\n"),
        _row("a1", b"A?\n", b"ra\n"),
        _row("b1", b"B?\n", b"rb\n"),
        _row("a2", b"A?\n", b"ra\n"),
    ]
    commands = [b"I?\n", b"A?\n", b"B?\n", b"A?\n", b"B?\n", b"A?\n", b"B?\n", b"A?\n"]
    expect = [b"ok\n", b"ra\n", b"rb\n", b"ra\n", b"rb\n", b"ra\n", b"rb\n", b"ra\n"]
    _sweep(rows, commands, expect)


def test_truncated_capture_falls_back_to_head_of_one() -> None:
    """[i, A, B, A] — one and a half units is not period evidence: the plan
    falls back to LoopingMockHost's own rule (establishment of one, the
    whole tail the cycle, replayed in captured order)."""
    from benchweave_sdk_server.session import _cycle_plan

    rows = [
        _row("i", b"I?\n", b"ok\n"),
        _row("a0", b"A?\n", b"ra\n"),
        _row("b0", b"B?\n", b"rb\n"),
        _row("a1", b"A?\n", b"ra\n"),
    ]
    establishment, cycle, rotate = _cycle_plan(rows)
    assert establishment == 1
    assert [row.name for row in cycle] == ["a0", "b0", "a1"]
    assert rotate == 0
    # The captured order serves once; the second sweep replays the SAME
    # captured order (the honest fallback — the guide says capture two full
    # poll cycles for a repeating model).
    _sweep(rows, [b"I?\n", b"A?\n", b"B?\n", b"A?\n", b"A?\n", b"B?\n", b"A?\n"],
           [b"ok\n", b"ra\n", b"rb\n", b"ra\n", b"ra\n", b"rb\n", b"ra\n"])


def test_multi_command_soak_repeats_the_pair_exactly() -> None:
    """R1's sibling over a TWO-command cycle (beside the single-command
    soak): 32 alternating commands, every response exact."""
    rows = []
    for index in range(8):
        rows.append(_row(f"a{index}", b"A?\n", b"ra\n"))
        rows.append(_row(f"b{index}", b"B?\n", b"rb\n"))
    _sweep(rows, [b"A?\n", b"B?\n"] * 32, [b"ra\n", b"rb\n"] * 32)


# --- release-once (lane 1 F3 + critic F7) ------------------------------------


def test_p4_drain_returns_the_burst_once_then_quiets() -> None:
    """[cmd, s1, s2]: the command's ack is silent, the device streams two
    status frames. The drain returns S1, S2 and then the quiet line — the
    burst releases ONCE, not re-released per receive (the measured hot
    spin)."""
    rows = [
        _row("cmd", b"GO\n", b""),
        _row("s1", None, b"S1\n"),
        _row("s2", None, b"S2\n"),
    ]

    async def flow() -> None:
        host = _served_host(rows)
        await _send_only(host, b"GO\n")
        assert await _drain(host) == [b"S1\n", b"S2\n"]
        assert await _drain(host) == [], "a second drain must stay quiet"

    asyncio.run(flow())


def test_release_once_keeps_the_command_cycle_serviceable() -> None:
    """The release-once rule must not strand the conversation: a captured
    [cmd, s1] x2 script serves command, burst, quiet, command, burst,
    quiet — the recycle re-arms on the request-bearing row, not the
    receive."""

    async def flow() -> None:
        rows = [
            _row("cmd0", b"GO\n", b""),
            _row("s10", None, b"S1\n"),
            _row("cmd1", b"GO\n", b""),
            _row("s11", None, b"S1\n"),
        ]
        host = _served_host(rows)
        for _ in range(3):
            await _send_only(host, b"GO\n")
            assert await _drain(host) == [b"S1\n"]
            assert await _drain(host) == []

    asyncio.run(flow())


def test_exhaustion_still_fails_honestly_under_the_plan() -> None:
    """cycles bounds stay meaningful: one play, then the honest exhaustion
    posture on the next command."""

    async def flow() -> None:
        rows = [
            _row("a0", b"A?\n", b"ra\n"),
            _row("b0", b"B?\n", b"rb\n"),
            _row("a1", b"A?\n", b"ra\n"),
            _row("b1", b"B?\n", b"rb\n"),
        ]
        host = ByteStreamMockHost(
            rows, cycles=1, establishment=0, cycle=list(rows), max_frame_bytes=128
        )
        await _send(host, b"A?\n")
        await _send(host, b"B?\n")
        await _send(host, b"A?\n")
        await _send(host, b"B?\n")
        with pytest.raises(ConformanceError, match="no scripted exchange remains"):
            await _send(host, b"A?\n")

    asyncio.run(flow())


# --- the plan derivation, pinned ---------------------------------------------


def test_cycle_plan_derivations() -> None:
    from benchweave_sdk_server.session import _cycle_plan

    def named(*rows: tuple[str, bytes | None, bytes]) -> list[FrameRow]:
        return [_row(name, request, response) for name, request, response in rows]

    # [i, A, B, A, B] -> establishment [i], unit [A, B], phase 0
    plan = _cycle_plan(named(("i", b"I?\n", b"o\n"), ("a", b"A?\n", b"x\n"),
                             ("b", b"B?\n", b"y\n"), ("a", b"A?\n", b"x\n"),
                             ("b", b"B?\n", b"y\n")))
    assert (plan[0], [r.name for r in plan[1]], plan[2]) == (1, ["a", "b"], 0)
    # [i, A, B, A, B, A] -> unit [A, B], phase 1 (the continuation opens on B)
    plan = _cycle_plan(named(("i", b"I?\n", b"o\n"), ("a", b"A?\n", b"x\n"),
                             ("b", b"B?\n", b"y\n"), ("a", b"A?\n", b"x\n"),
                             ("b", b"B?\n", b"y\n"), ("a", b"A?\n", b"x\n")))
    assert (plan[0], [r.name for r in plan[1]], plan[2]) == (1, ["a", "b"], 1)
    # [ID, CH0, CH1] x3 -> establishment [ID], unit [CH0, CH1]
    rows = named(("id", b"ID?\n", b"d\n"))
    rows += [named(("c0", b"C0?\n", b"0\n"), ("c1", b"C1?\n", b"1\n"))[i % 2]
             for i in range(6)]
    plan = _cycle_plan(rows)
    assert (plan[0], [r.name for r in plan[1]], plan[2]) == (1, ["c0", "c1"], 0)
    # no period evidence -> the LoopingMockHost fallback (head of one)
    plan = _cycle_plan(named(("i", b"I?\n", b"o\n"), ("a", b"A?\n", b"x\n")))
    assert (plan[0], [r.name for r in plan[1]], plan[2]) == (1, ["a"], 0)
    # a response-only unit is not a poll cycle: it never qualifies
    plan = _cycle_plan(named(("s0", None, b"S\n"), ("s1", None, b"S\n"),
                             ("s2", None, b"S\n"), ("s3", None, b"S\n")))
    assert plan[0] == 1, "an all-response-only script takes the fallback"
