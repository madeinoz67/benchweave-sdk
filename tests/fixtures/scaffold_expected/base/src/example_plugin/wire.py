"""Wire-discipline helpers for device adapters (issue #566, rows 8 to 10).

These helpers generalise patterns proven on hardware in the wire-truth
train (issue #562): the command counter that catches a lost or duplicated
frame at birth, the paced poll whose declared interval the loop must
honour, and the completion gate that refuses ok without the device's own
done signal. They are device-agnostic on purpose — no frame shape, no ACK
length, no register map: every value is supplied by the caller, so the
helpers carry only the discipline.

Import this module relatively (``from .wire import ...``): the plugin
runtime is standard-library-only by the gateway loader's rule.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from typing import Any

#: One evidence entry the adapter's ``record`` hook receives on a gap.
RecordHook = Callable[[dict[str, Any]], Awaitable[None]]


class CounterGapError(ValueError):
    """A command-counter gap: a lost or duplicated exchange.

    Subclasses ``ValueError`` so an adapter's existing
    ``except (ValueError, KeyError, TypeError)`` mapping reports the gap as
    a protocol error without new plumbing. The refusal names the expected
    counter (wrap-aware), the observed counter, and the exchange index.
    """

    def __init__(self, *, expected: int, observed: int, exchange_index: int) -> None:
        self.expected = expected
        self.observed = observed
        self.exchange_index = exchange_index
        super().__init__(
            f"command counter gap at exchange {exchange_index}: "
            f"expected {expected:#04x}, observed {observed:#04x}"
        )


class CommandCounter:
    """Track one device command counter across reads and writes.

    Many instruments echo a counter that advances by exactly one on every
    command, whatever the frame shape. Feed every parsed counter to
    :meth:`advance`; the first observation establishes the baseline and a
    later gap is a refusal with the evidence attached.

    Parameters
    ----------
    modulus
        The counter's wrap point (``256`` for one byte), or ``None`` when
        the counter never wraps. Without a modulus a byte counter's roll
        0xFF to 0x00 reads as a gap — declare the modulus for a byte-wide
        counter.
    """

    def __init__(self, *, modulus: int | None = None) -> None:
        if modulus is not None and modulus < 2:
            raise ValueError("modulus must be at least 2; a non-wrapping counter needs none")
        self._modulus = modulus
        self._last: int | None = None
        self._exchanges = 0

    async def advance(
        self, counter: int, *, record: RecordHook | None = None
    ) -> None:
        """Observe one exchange's counter; refuse a gap.

        Parameters
        ----------
        counter
            The counter value the caller parsed from the reply — an integer
            in ``0 .. modulus - 1`` (or non-negative when the counter does
            not wrap).
        record
            Optional evidence hook (for example
            ``lambda entry: services.record_evidence(entry, context)``).
            On a gap it receives one entry
            ``{"kind": "command_counter_gap", "exchange": ...,
            "expected": ..., "observed": ...}`` and is awaited BEFORE the
            refusal raises.

        Raises
        ------
        TypeError
            If the counter is not an integer.
        ValueError
            If the counter is negative, sits outside the declared modulus,
            or breaks continuity with the previous exchange
            (:class:`CounterGapError`).
        """
        if isinstance(counter, bool) or not isinstance(counter, int):
            raise TypeError("counter must be the integer parsed from the reply")
        if counter < 0 or (self._modulus is not None and counter >= self._modulus):
            top = self._modulus - 1 if self._modulus is not None else "unbounded"
            raise ValueError(f"counter {counter} is outside 0..{top}")
        index = self._exchanges
        self._exchanges += 1
        if self._last is not None:
            expected = self._last + 1
            if self._modulus is not None:
                expected %= self._modulus
            if counter != expected:
                if record is not None:
                    await record(
                        {
                            "kind": "command_counter_gap",
                            "exchange": index,
                            "expected": expected,
                            "observed": counter,
                        }
                    )
                raise CounterGapError(
                    expected=expected, observed=counter, exchange_index=index
                )
        self._last = counter


async def paced_poll(
    attempts: int,
    interval_s: float,
    *,
    read: Callable[[], Awaitable[Any]],
    ready: Callable[[Any], bool],
    monotonic: Callable[[], float],
    deadline: float,
    cancelled: Callable[[], bool] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Any:
    """Poll ``read()`` until ``ready()`` accepts the outcome, paced at the
    device's own cadence.

    The pacer owns the loop, so the declared interval cannot go unread: a
    poll interval the loop never honours hammers a device that answers on
    its own timer and exhausts the attempt budget before the device ever
    becomes ready — the systematic false timeout this helper exists to
    make unrepresentable (issue #566 row 9). The wait happens between
    attempts only; the first read is immediate.

    The loop is attempt-bounded as well as deadline-bounded: a host whose
    clock never advances still terminates. Check the deadline and
    cancellation before entering, as the adapter's own pre-dispatch check
    does; this helper re-checks both after every wait.

    Parameters
    ----------
    attempts
        Maximum number of reads (at least 1).
    interval_s
        The declared device cadence in seconds — a finite positive number,
        the budget the loop must honour.
    read
        One poll exchange (async): sends the query, returns the reply.
    ready
        Decides the reply: truthy means the waited-for state arrived.
    monotonic
        The session's monotonic clock (``services.monotonic``).
    deadline
        ``context.deadline_monotonic``; expired after a wait refuses.
    cancelled
        Optional ``context.is_cancelled``; set after a wait refuses.
    sleep
        The wait seam (``asyncio.sleep``); tests inject a recorder.

    Returns
    -------
    The first outcome ``ready`` accepted.

    Raises
    ------
    ValueError
        If ``attempts`` is below 1 or ``interval_s`` is not a finite
        positive number of seconds.
    TimeoutError
        On cancellation or deadline expiry after a wait, or when the
        attempts are exhausted without ``ready`` accepting.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    if not math.isfinite(interval_s) or interval_s <= 0:
        raise ValueError("interval_s must be a finite positive number of seconds")
    for attempt in range(attempts):
        outcome = await read()
        if ready(outcome):
            return outcome
        if attempt + 1 < attempts:
            await sleep(interval_s)
            if cancelled is not None and cancelled():
                raise TimeoutError("Cancelled while pacing the poll")
            if monotonic() >= deadline:
                raise TimeoutError("Deadline or cancellation")
    raise TimeoutError(f"the device never became ready after {attempts} attempt(s)")


class CompletionUnassertedError(RuntimeError):
    """The device's completion signal never asserted.

    Not a ``ValueError``: a silent completion is a device verdict, not a
    malformed response — catch it in the adapter and report the failure
    your contract names (with an uncertain outcome when the device was
    already dispatched to), never ok.
    """

    def __init__(self, *, signal: str, exchange: int | None = None) -> None:
        self.signal = signal
        self.exchange = exchange
        where = f" at exchange {exchange}" if exchange is not None else ""
        super().__init__(f"the completion signal is not asserted{where}: {signal}")


def require_completion(
    asserted: Any, *, signal: str, exchange: int | None = None
) -> None:
    """Refuse unless the hardware completion signal is asserted.

    An operation whose device asserts a done/done-pin/ready signal reports
    ok only when that signal actually asserted (issue #566 row 10). Call
    this on the parsed verdict inside the adapter's failure mapping; the
    device already received the command, so the refusal's outcome is the
    adapter's to report honestly.

    Parameters
    ----------
    asserted
        The parsed signal verdict; anything falsy refuses.
    signal
        The signal's name for the refusal (for example ``"FPGA DONE pin"``).
    exchange
        Optional exchange index naming where the signal was read.

    Raises
    ------
    CompletionUnassertedError
        If ``asserted`` is falsy.
    """
    if not asserted:
        raise CompletionUnassertedError(signal=signal, exchange=exchange)
