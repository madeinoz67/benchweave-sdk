"""LoopingMockHost: the recycle mechanism, real clocks, honest exhaustion."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

import pytest

from benchweave_sdk.testing import ConformanceError
from benchweave_sdk_server.session import HostOperationContext
from benchweave_sdk_server.transport import LoopingMockHost

IDENTIFY = (
    {
        "kind": "stream_exchange",
        "data": b"ID?\n",
        "max_bytes": 128,
        "termination": "lf",
        "exact_bytes": None,
    },
    {"data": b"SDK Example,demo,SIM001,1.0.0\n"},
)
READ = (
    {
        "kind": "stream_exchange",
        "data": b"V?\n",
        "max_bytes": 128,
        "termination": "lf",
        "exact_bytes": None,
    },
    {"data": b"3.3\n"},
)


def _context(timeout_ms: int = 1000) -> HostOperationContext:
    return HostOperationContext("op", timeout_ms=timeout_ms)


async def _transfer(host: LoopingMockHost, transaction: dict) -> dict:
    context = _context()
    await context.mark_dispatch_started()
    return await host.transfer(dict(transaction), context)


def run(coro):
    return asyncio.run(coro)


def test_establishment_once_then_polls_forever() -> None:
    """Identify consumes the head; every later read is served from the cycle."""

    async def flow() -> None:
        host = LoopingMockHost([IDENTIFY, READ])
        await _transfer(host, IDENTIFY[0])
        for _ in range(25):
            response = await _transfer(host, READ[0])
            assert response == {"data": b"3.3\n"}

    run(flow())


def test_cycles_one_exhausts_after_the_single_play() -> None:
    async def flow() -> None:
        host = LoopingMockHost([IDENTIFY, READ], cycles=1)
        await _transfer(host, IDENTIFY[0])
        await _transfer(host, READ[0])
        with pytest.raises(ConformanceError, match="no scripted exchange remains"):
            await _transfer(host, READ[0])

    run(flow())


def test_cycles_counts_cycle_plays() -> None:
    async def flow() -> None:
        host = LoopingMockHost([IDENTIFY, READ], cycles=3)
        await _transfer(host, IDENTIFY[0])
        for _ in range(3):
            await _transfer(host, READ[0])
        with pytest.raises(ConformanceError):
            await _transfer(host, READ[0])
        assert host.plays == 3

    run(flow())


def test_exact_match_discipline_is_inherited() -> None:
    async def flow() -> None:
        host = LoopingMockHost([IDENTIFY, READ])
        wrong = dict(READ[0])
        wrong["data"] = b"X?\n"
        with pytest.raises(ConformanceError, match="Expected"):
            await _transfer(host, wrong)

    run(flow())


def test_dispatch_marker_is_still_enforced() -> None:
    async def flow() -> None:
        host = LoopingMockHost([READ])
        with pytest.raises(ConformanceError, match="dispatch marker"):
            await host.transfer(dict(READ[0]), _context())

    run(flow())


def test_real_monotonic_clock_drives_expiry() -> None:
    """A deadline in the past on the REAL clock must refuse (R3's falsifier)."""

    async def flow() -> None:
        host = LoopingMockHost([READ])
        context = HostOperationContext("op", timeout_ms=1000)
        context.deadline_monotonic = time.monotonic() - 1.0
        await context.mark_dispatch_started()
        with pytest.raises(TimeoutError):
            await host.transfer(dict(READ[0]), context)

    run(flow())


def test_cancellation_refuses_on_the_real_clock() -> None:
    async def flow() -> None:
        host = LoopingMockHost([READ])
        context = _context()
        context.cancel()
        await context.mark_dispatch_started()
        with pytest.raises(TimeoutError):
            await host.transfer(dict(READ[0]), context)

    run(flow())


def test_utc_now_is_real_iso8601_z() -> None:
    host = LoopingMockHost([READ])
    stamp = host.utc_now()
    assert stamp.endswith("Z")
    datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def test_monotonic_moves_with_wall_time() -> None:
    host = LoopingMockHost([READ])
    first = host.monotonic()
    time.sleep(0.01)
    assert host.monotonic() > first


def test_single_exchange_script_loops_that_exchange() -> None:
    async def flow() -> None:
        host = LoopingMockHost([READ])
        for _ in range(5):
            assert await _transfer(host, READ[0]) == {"data": b"3.3\n"}

    run(flow())


def test_cycles_bounds_are_validated() -> None:
    with pytest.raises(ValueError, match="standalone_transport_cycles"):
        LoopingMockHost([READ], cycles=0)
