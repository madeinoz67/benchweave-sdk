"""The conformance harness must fail loudly, including under ``python -O``."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from benchweave_sdk.testing import ConformanceError, MockContext, MockHost


def _context(deadline: float = 10.0) -> MockContext:
    return MockContext("op-1", deadline_monotonic=deadline)


def test_conformance_error_is_an_assertion_error() -> None:
    # pytest.raises(AssertionError) suites keep working across the change.
    assert issubclass(ConformanceError, AssertionError)


def test_unscripted_transfer_raises_typed_error() -> None:
    host = MockHost([])
    context = _context()

    async def scenario() -> dict[str, Any]:
        await context.mark_dispatch_started()
        return await host.transfer({"kind": "stream_exchange", "data": b"?"}, context)

    with pytest.raises(ConformanceError, match="no scripted exchange"):
        asyncio.run(scenario())


def test_transfer_without_dispatch_marker_raises_typed_error() -> None:
    host = MockHost([({"kind": "stream_exchange", "data": b"?"}, {"data": b"!"})])
    context = _context()

    async def scenario() -> dict[str, Any]:
        return await host.transfer({"kind": "stream_exchange", "data": b"?"}, context)

    with pytest.raises(ConformanceError, match="dispatch marker"):
        asyncio.run(scenario())


def test_mismatched_transfer_raises_typed_error() -> None:
    host = MockHost([({"kind": "stream_exchange", "data": b"expected"}, {"data": b"!"})])
    context = _context()

    async def scenario() -> dict[str, Any]:
        await context.mark_dispatch_started()
        return await host.transfer({"kind": "stream_exchange", "data": b"other"}, context)

    with pytest.raises(ConformanceError, match="Expected"):
        asyncio.run(scenario())


def test_assert_complete_raises_typed_error() -> None:
    host = MockHost([({"kind": "stream_exchange", "data": b"?"}, {"data": b"!"})])
    with pytest.raises(ConformanceError, match="not consumed"):
        host.assert_complete()


def test_close_transport_allowed_after_deadline() -> None:
    host = MockHost([])
    context = _context(deadline=1.0)
    host.advance(5.0)

    async def scenario() -> None:
        await host.close_transport(context)

    asyncio.run(scenario())
    assert host.closed


def test_expired_transfer_still_raises_timeout() -> None:
    host = MockHost([])
    context = _context(deadline=1.0)
    host.advance(5.0)

    async def scenario() -> dict[str, Any]:
        return await host.transfer({"kind": "stream_exchange", "data": b"?"}, context)

    with pytest.raises(TimeoutError):
        asyncio.run(scenario())
