"""Reusable checks, not full OTDP certification or hardware qualification."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from typing import Any

from .interfaces import Adapter, OperationContext
from .testing import MockContext, MockHost
from .validation import validate_descriptor, validate_request, validate_result


def _check_timeout(timeout: float) -> None:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Conformance timeout must be finite and positive")


async def check_operation(
    adapter: Adapter,
    request: dict[str, Any],
    context: OperationContext,
    *,
    timeout: float = 1.0,
) -> dict[str, Any]:
    """Check one response, with a wall-clock limit for cooperative async code."""
    _check_timeout(timeout)
    validate_request(request)
    if request["operation_id"] != context.operation_id:
        raise ValueError("Request/context correlation mismatch")
    async with asyncio.timeout(timeout):
        result = await adapter.execute(request, context)
    validate_result(result, request)
    return result


async def check_lifecycle(
    factory: Callable[[], Adapter], descriptor: dict[str, Any], *, timeout: float = 1.0
) -> None:
    """Check quiet lifecycle and bounded cleanup; import I/O needs separate tests.

    Each await has a wall-clock timeout. Run untrusted code in an isolated process:
    blocking Python or code swallowing cancellation cannot be stopped by asyncio.
    """
    _check_timeout(timeout)
    validate_descriptor(descriptor)
    host = MockHost([])
    context = MockContext("lifecycle", deadline_monotonic=timeout)
    adapter = factory()
    try:
        async with asyncio.timeout(timeout):
            await adapter.open(descriptor, host, context)
        assert not host.transfers, "Open performed a device transaction"
        async with asyncio.timeout(timeout):
            assert await adapter.next_event("quiet", context) is None
    finally:
        async with asyncio.timeout(timeout):
            await adapter.close(context)
    async with asyncio.timeout(timeout):
        await adapter.close(context)
    host.assert_complete()
    assert not host.transfers, "Lifecycle performed a device transaction"
