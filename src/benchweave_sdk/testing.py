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
    """A deterministic ``OperationContext`` with caller-controlled state.

    Time never advances on its own: the deadline is judged against the
    paired :class:`MockHost`'s manually advanced clock, and cancellation
    happens only when the test calls :meth:`cancel`.

    Parameters
    ----------
    operation_id
        Identity carried by the operation's request and result envelopes.
    deadline_monotonic
        Deadline in seconds on the paired host's monotonic clock; must be
        finite.
    dataset_id
        Optional dataset correlation id, or ``None`` when the operation is
        not part of a dataset.

    Raises
    ------
    ValueError
        If ``operation_id`` is empty or ``deadline_monotonic`` is not finite.

    See Also
    --------
    MockHost : the scripted transport this context pairs with.
    """

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
        """Report whether :meth:`cancel` has been called."""
        return self._cancelled

    def cancel(self) -> None:
        """Cancel the operation; subsequent transfers must fail, not transmit."""
        self._cancelled = True

    async def mark_dispatch_started(self) -> None:
        """Record the dispatch marker; ``dispatched`` becomes ``True``.

        Adapters call this immediately before their first transmit. The
        paired :class:`MockHost` refuses transmitting transfers made without
        it, which is how the mock enforces honest ``dispatch_state``
        reporting.
        """
        self.dispatched = True


class MockHost:
    """A scripted ``HostServices`` double: exact bytes, a manual clock, no I/O.

    The script is an ordered list of ``(expected_transaction, response)``
    pairs. Each ``transfer`` must match the next expected transaction
    exactly (compared as whole dicts, bytes included) and receives its
    scripted response — or raises it, when the response is an exception
    instance. Consumed exchanges are recorded on ``transfers`` and evidence
    entries on ``evidence``, both deep-copied so later mutation cannot
    falsify assertions.

    Parameters
    ----------
    exchanges
        The scripted ``(expected_transaction, response)`` pairs, consumed
        in order. An exception response is raised instead of returned.
    start
        Initial reading of the monotonic clock in seconds; advance it
        explicitly with :meth:`advance`.

    Raises
    ------
    ValueError
        If ``start`` is negative or not finite.

    See Also
    --------
    MockContext : the deterministic per-operation context.
    benchweave_sdk.conformance.check_operation : validates envelopes around this mock.
    """

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
        """The number of scripted exchanges not yet consumed."""
        return len(self._script)

    def monotonic(self) -> float:
        """Return the mock monotonic clock; moves only via :meth:`advance`."""
        return self._time

    def utc_now(self) -> str:
        """Return a deterministic ISO-8601 UTC stamp derived from the clock."""
        return (
            (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=self._time))
            .isoformat()
            .replace("+00:00", "Z")
        )

    def advance(self, seconds: float) -> None:
        """Advance the monotonic clock by ``seconds``.

        Parameters
        ----------
        seconds
            Nonnegative, finite seconds to add; the resulting clock value
            must stay finite.

        Raises
        ------
        ValueError
            If ``seconds`` is negative, not finite, or would overflow.
        """
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
        """Consume the next scripted exchange for an exactly matching transaction.

        Parameters
        ----------
        transaction
            The exchange the adapter requests; must equal the next scripted
            transaction exactly. Kinds other than ``stream_receive`` /
            ``can_receive`` additionally require a prior
            ``mark_dispatch_started``.
        context
            The operation context; cancelled or expired operations fail
            before any script is consumed.

        Returns
        -------
        dict
            A deep copy of the scripted response.

        Raises
        ------
        TimeoutError
            If the context is cancelled or past its deadline.
        ConnectionError
            If the transport has been closed — or the scripted response is
            itself an exception, which is raised as-is.
        ConformanceError
            If the transfer is unscripted, mismatched, or transmitted
            without a dispatch marker.
        """
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
        """Mark the transport closed; later transfers raise ``ConnectionError``.

        Deliberately performs no deadline or cancellation check: closing the
        transport is cleanup, and cleanup after an expired or cancelled
        operation is correct adapter behaviour (``Adapter.close`` must
        tolerate repeated calls), not a late transmission.
        """
        self.closed = True

    async def record_evidence(self, entry: dict[str, Any], context: OperationContext) -> None:
        """Append a deep copy of ``entry`` to ``evidence``; live contexts only."""
        self._check(context)
        self.evidence.append(deepcopy(entry))

    def assert_complete(self) -> None:
        """Fail (``ConformanceError``) unless every scripted exchange was consumed."""
        if self._script:
            raise ConformanceError(f"{len(self._script)} scripted exchanges were not consumed")
