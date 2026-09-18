"""Deterministic, hardware-free OTDP test services.

Scripted transfers assert exact bytes; no sleeps, sockets or serial ports.
These test doubles are not a production host or complete transport validator.
"""

from __future__ import annotations

import math
from collections import deque
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

from .interfaces import OperationContext


class ConformanceError(AssertionError):
    """A conformance expectation failed.

    Subclasses ``AssertionError`` so existing ``pytest.raises(AssertionError)``
    suites keep passing, while surviving ``python -O``: bare ``assert``
    statements are stripped under optimisation, and a conformance harness that
    silently passes everything there is worse than none.
    """


class MockContext:
    def __init__(
        self, operation_id: str, *, deadline_monotonic: float, dataset_id: str | None = None
    ) -> None:
        if not operation_id or not math.isfinite(deadline_monotonic):
            raise ValueError("A context needs an identity and finite deadline")
        self.operation_id = operation_id
        self.deadline_monotonic = deadline_monotonic
        self.dataset_id = dataset_id
        self.dispatched = False
        self._cancelled = False

    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    async def mark_dispatch_started(self) -> None:
        self.dispatched = True


class MockHost:
    def __init__(
        self,
        exchanges: list[tuple[dict[str, Any], dict[str, Any] | Exception]],
        *,
        start: float = 0.0,
    ) -> None:
        if not math.isfinite(start) or start < 0:
            raise ValueError("Clock start must be finite and nonnegative")
        self._time = start
        self._script = deque(deepcopy(exchanges))
        self.transfers: list[dict[str, Any]] = []
        self.evidence: list[dict[str, Any]] = []
        self.closed = False

    @property
    def pending(self) -> int:
        return len(self._script)

    def monotonic(self) -> float:
        return self._time

    def utc_now(self) -> str:
        return (
            (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=self._time))
            .isoformat()
            .replace("+00:00", "Z")
        )

    def advance(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Clock advance must be finite and nonnegative")
        if not math.isfinite(self._time + seconds):
            raise ValueError("Clock overflow")
        self._time += seconds

    def _check(self, context: OperationContext) -> None:
        if context.is_cancelled() or self._time >= context.deadline_monotonic:
            raise TimeoutError("Operation cancelled or expired")

    async def transfer(
        self, transaction: dict[str, Any], context: OperationContext
    ) -> dict[str, Any]:
        self._check(context)
        if self.closed:
            raise ConnectionError("Transport closed")
        if transaction.get("kind") not in ("stream_receive", "can_receive") and not getattr(
            context, "dispatched", False
        ):
            raise ConformanceError("Transmission needs a dispatch marker")
        if not self._script:
            raise ConformanceError("Unexpected transfer: no scripted exchange remains")
        expected, response = self._script[0]
        if transaction != expected:
            raise ConformanceError(f"Expected {expected!r}, got {transaction!r}")
        self._script.popleft()
        self.transfers.append(deepcopy(transaction))
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)

    async def close_transport(self, context: OperationContext) -> None:
        # No deadline/cancellation check: closing the transport is cleanup,
        # and cleanup after an expired or cancelled operation is correct
        # adapter behaviour (``Adapter.close`` must tolerate repeated calls),
        # not a late transmission.
        self.closed = True

    async def record_evidence(self, entry: dict[str, Any], context: OperationContext) -> None:
        self._check(context)
        self.evidence.append(deepcopy(entry))

    def assert_complete(self) -> None:
        if self._script:
            raise ConformanceError(f"{len(self._script)} scripted exchanges were not consumed")
