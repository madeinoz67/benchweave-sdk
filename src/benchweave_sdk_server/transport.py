"""The I1 transport: a recycling scripted host with real clocks.

The SDK's :class:`benchweave_sdk.testing.MockHost` is finite-script with a
manual clock — exactly right for tests, wrong for a live server that polls
every few seconds: the second poll would exhaust the script and the manual
clock would never expire a deadline. :class:`LoopingMockHost` subclasses it
and changes exactly those two things:

- the poll cycle is restored from a pristine copy whenever the deque empties
  (``cycles=None`` loops forever; ``cycles=k`` plays the cycle ``k`` times
  total, the exact-finite control the acceptance RED arms use);
- the clock reads and the deadline/cancellation judgement run on the real
  monotonic clock, so inherited expiry arithmetic stays honest on live
  deadlines.

Everything else — exact-dict matching, dispatch-marker enforcement,
``ConformanceError`` on mismatch, evidence recording — is inherited
unchanged from the tested SDK class. The SDK file itself is untouched.
"""

from __future__ import annotations

import time
from collections import deque
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from benchweave_sdk.interfaces import OperationContext
from benchweave_sdk.testing import MockHost


class LoopingMockHost(MockHost):
    """A :class:`MockHost` that recycles its poll cycle and tells real time.

    The first scripted exchange is the once-per-construction establishment
    exchange (identify); the remaining tail is the poll cycle a live server
    repeats indefinitely. When the deque empties, the TAIL is restored —
    restoring the whole script would desync a read-only poller (after
    identify + one read, the recycled head would be the establishment
    exchange again and the next read would mismatch). A single-exchange
    script has no distinct establishment: the exchange is the cycle.

    Parameters
    ----------
    exchanges
        The scripted ``(expected_transaction, response)`` pairs, as
        :class:`MockHost` takes them, in demand order (establishment
        first).
    cycles
        How many times the poll cycle may play in total. ``None`` loops
        forever (the serving posture); ``1`` plays it once and lets the
        next poll fail honestly — the RED control that proves the recycle
        mechanism is what sustains reads.

    See Also
    --------
    MockHost : the SDK double this extends; everything not overridden here
        is inherited unchanged.
    """

    def __init__(
        self,
        exchanges: list[tuple[dict[str, Any], dict[str, Any] | Exception]],
        *,
        cycles: int | None = None,
        establishment: int = 1,
    ) -> None:
        super().__init__(exchanges)
        if cycles is not None and cycles < 1:
            raise ValueError("standalone_transport_cycles: cycles must be >= 1 or None")
        if establishment < 0 or establishment > len(exchanges):
            raise ValueError(
                "standalone_transport_establishment: must index into the script"
            )
        original = list(self._script)
        # The poll cycle is the script AFTER its establishment head — the
        # default 1 is the identify-first conversation mock_exchanges
        # scripts; 0 serves a script with no establishment exchange at all
        # (scenario mode for a plugin that does not declare identify). A
        # script no longer than its own establishment head has no distinct
        # cycle: the whole script is the cycle (the single-exchange rule).
        if len(original) > establishment:
            self._cycle = deque(original[establishment:])
        else:
            self._cycle = deque(original)
        self._cycles = cycles
        self._plays = 1

    @property
    def plays(self) -> int:
        """How many times the poll cycle has been made available so far."""
        return self._plays

    def monotonic(self) -> float:
        """The real monotonic clock — deadlines must expire on live time."""
        return time.monotonic()

    def utc_now(self) -> str:
        """The real UTC now, in the SDK stamp's ISO-8601 ``Z`` shape."""
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _check(self, context: OperationContext) -> None:
        # Judge cancellation and expiry on the same real clock the deadlines
        # are minted on (HostOperationContext uses time.monotonic()); the
        # inherited judgement against the manual _time would never fire.
        if context.is_cancelled() or time.monotonic() >= context.deadline_monotonic:
            raise TimeoutError("Operation cancelled or expired")

    async def transfer(
        self, transaction: dict[str, Any], context: OperationContext
    ) -> dict[str, Any]:
        if not self._script and (self._cycles is None or self._plays < self._cycles):
            self._script = deepcopy(self._cycle)
            self._plays += 1
        return await super().transfer(transaction, context)
