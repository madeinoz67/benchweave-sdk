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

:class:`ByteStreamMockHost` (issue #394) is the demand-driven sibling for
binary §8.1 SEND/RECEIVE plugins: the same recycle/clock posture with frame
semantics and the serial backend's exact RECEIVE outcomes, one
``_stream_receive_bounds`` definition shared with it.
"""

from __future__ import annotations

import time
from collections import deque
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from benchweave_sdk.interfaces import OperationContext
from benchweave_sdk.testing import ConformanceError, MockHost

from .serial import _FIELDS, WriterBackedCaptureServices, _stream_receive_bounds
from .session import FrameRow


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


class ByteStreamMockHost(WriterBackedCaptureServices, MockHost):
    """A demand-driven frame-script host for binary §8.1 SEND/RECEIVE
    plugins (issue #394).

    ``LoopingMockHost``'s sibling: the same real-clock overrides, the same
    establishment/tail-recycle semantics (``cycles``/``establishment``/
    ``_plays``), the same inherited ``close_transport``, evidence recording
    and honest-exhaustion posture — with ``transfer`` replaced by frame
    semantics and the capture members served by the SAME
    ``WriterBackedCaptureServices`` base the serial backend uses (one
    capture lifecycle, two hosts).

    The script is ordered :class:`FrameRow`\\s under a minimal-period
    cycle plan (see :func:`benchweave_sdk_server.session._cycle_plan`): the
    captured rows play once, then the shortest repeating unit restores —
    ROTATED to the phase the capture ended on — when the next command
    arrives. Response-only rows (``request is None`` — device-initiated
    frames) release their bytes to the inbound stream in ROW ORDER, ONCE
    per cycle: a receive never re-arms the tail, so a drain returns the
    burst and then the quiet line (a receive against a pending request row
    is a quiet line, exactly as on real hardware). A ``stream_send`` must
    match the head request-bearing row's frame exactly — a genuine adapter/script disagreement is a
    ``ConformanceError`` carrying the row key and both frames hex-rendered
    (the exact-match discipline at frame granularity; the one-line format
    is API, STD-4). ``stream_receive`` serves the inbound stream with the
    serial backend's exact OUTCOMES (not timings — the quiet line answers
    immediately, not after the 100 ms window; a receive that cannot
    complete raises the backend's ``TimeoutError`` with the partial bytes
    retained): positive ``exact_bytes`` pops exactly N when buffered,
    otherwise the terminator is searched within the first ``max_bytes``
    (found: returned including the terminator; ``max_bytes`` filled without
    one: those bytes are DISCARDED and ``ValueError`` raised — an
    incomplete frame is never returned as complete). Bounds validate
    through the shared ``_stream_receive_bounds``; field sets through the
    shared ``_FIELDS`` — one definition for backend and mock, refused
    identically on both.

    Parameters
    ----------
    rows
        The scripted :class:`FrameRow`\\s, in demand order (establishment
        first).
    cycles, establishment
        :class:`LoopingMockHost`'s exact recycle parameters.
    max_frame_bytes
        The descriptor's own frame bound — the receive ceiling (A02: the
        plugin's declared bound is the bound).
    capture_root, capture_max_bytes
        The capture configuration threaded through
        :class:`WriterBackedCaptureServices`.
    """

    def __init__(
        self,
        rows: list[FrameRow],
        *,
        cycles: int | None = None,
        establishment: int = 1,
        cycle: list[FrameRow] | None = None,
        cycle_rotate: int = 0,
        max_frame_bytes: int = 128,
        capture_root: Any = None,
        capture_max_bytes: int | None = None,
    ) -> None:
        WriterBackedCaptureServices.__init__(
            self, capture_root=capture_root, capture_max_bytes=capture_max_bytes
        )
        MockHost.__init__(self, [])
        if cycles is not None and cycles < 1:
            raise ValueError("standalone_transport_cycles: cycles must be >= 1 or None")
        if establishment < 0 or establishment > len(rows):
            raise ValueError(
                "standalone_transport_establishment: must index into the script"
            )
        if (
            not isinstance(max_frame_bytes, int)
            or isinstance(max_frame_bytes, bool)
            or max_frame_bytes < 1
        ):
            raise ValueError(
                "standalone_transport_frame: max_frame_bytes must be a positive integer"
            )
        original = list(rows)
        if cycle is not None:
            if cycle_rotate < 0 or cycle_rotate >= max(len(cycle), 1):
                raise ValueError(
                    "standalone_transport_cycle_rotate: must index into the cycle unit"
                )
            self._cycle = deque(cycle)
            self._rotate = cycle_rotate
        else:
            # No explicit unit: LoopingMockHost's own derivation — the tail
            # after the establishment head (the single-row rule included).
            if len(original) > establishment:
                self._cycle = deque(original[establishment:])
            else:
                self._cycle = deque(original)
            self._rotate = 0
        self._rows = deque(original)
        self._cycles = cycles
        self._plays = 1
        # Release-once arming (the fold's F3/F7 rule): the captured rows
        # are the first availability; a restore re-arms only when a
        # REQUEST-BEARING row is consumed, so an unsolicited burst releases
        # once per cycle and a drain quiets — never re-releasing per
        # receive (the measured hot spin).
        self._armed = True
        self._ceiling = max_frame_bytes
        self._inbound = bytearray()

    @property
    def plays(self) -> int:
        """How many times the poll cycle has been made available so far."""
        return self._plays

    @property
    def pending(self) -> int:
        """The number of scripted rows not yet consumed."""
        return len(self._rows)

    def assert_complete(self) -> None:
        """Fail unless the whole script was consumed AND the inbound stream
        drained (lane 1 F4 + critic F5: the inherited check read the
        exchange deque — always empty here — so ``conformance.py``'s
        lifecycle check certified exhaustion over an un-exhausted script)."""
        if self._rows:
            raise ConformanceError(
                f"{len(self._rows)} scripted rows were not consumed"
            )
        if self._inbound:
            raise ConformanceError(
                f"{len(self._inbound)} inbound bytes remain buffered"
            )

    def monotonic(self) -> float:
        """The real monotonic clock — deadlines must expire on live time."""
        return time.monotonic()

    def utc_now(self) -> str:
        """The real UTC now, in the SDK stamp's ISO-8601 ``Z`` shape."""
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _check(self, context: OperationContext) -> None:
        # Judge cancellation and expiry on the same real clock the deadlines
        # are minted on (LoopingMockHost's override, verbatim).
        if context.is_cancelled() or time.monotonic() >= context.deadline_monotonic:
            raise TimeoutError("Operation cancelled or expired")

    def _may_recycle(self) -> bool:
        return self._cycles is None or self._plays < self._cycles

    def _advance(self) -> None:
        """Release leading response-only rows to the inbound stream, in row
        order. Never recycles: response-only bytes release ONCE per cycle
        (a receive cannot re-arm the tail — the recycle happens in the send
        path, on request-bearing consumption, so a drain quiets after the
        burst exactly as a recorded backend burst does)."""
        while self._rows and self._rows[0].request is None:
            self._inbound += self._rows.popleft().response

    def _recycle_if_armed(self) -> None:
        """Restore the cycle unit — ROTATED to the captured phase — but
        only when a request-bearing row was consumed since the last
        restore (the arming rule) and the cycle budget allows it."""
        if self._rows or not self._armed or not self._may_recycle():
            return
        unit = list(self._cycle)
        self._rows = deque(unit[self._rotate :] + unit[: self._rotate])
        self._plays += 1
        self._armed = False

    def _pop(self, count: int) -> bytes:
        out = bytes(self._inbound[:count])
        del self._inbound[:count]
        return out

    def _send_frame(self, data: Any) -> None:
        """Match one command frame against the head request-bearing row."""
        if not isinstance(data, bytes):
            raise ValueError("data must be bytes")
        self._advance()
        self._recycle_if_armed()
        self._advance()
        if not self._rows:
            raise ConformanceError("Unexpected transfer: no scripted exchange remains")
        row = self._rows[0]
        if row.request is None:
            # Unreachable after _advance released every leading
            # response-only row; the guard keeps the invariant local.
            raise ConformanceError("Unexpected transfer: no scripted exchange remains")
        if data != row.request:
            raise ConformanceError(
                f"frame mismatch at row {row.name}: "
                f"expected {row.request.hex()}, got {data.hex()}"
            )
        self._rows.popleft()
        self._inbound += row.response
        self._armed = True

    def _serve_receive(
        self, max_bytes: int, terminator: bytes, exact: int
    ) -> bytes:
        """The inbound stream under the backend's exact receive outcomes:
        exact precedence, terminator search within ``max_bytes``, the
        discard+ValueError on an overlong unterminated run, the quiet-line
        ``b""`` on an empty stream, and the retained-partial TimeoutError
        (raised immediately — the outcome the backend reaches at the
        deadline; nothing can arrive during this call)."""
        if exact:
            if len(self._inbound) >= exact:
                return self._pop(exact)
        else:
            end = self._inbound[:max_bytes].find(terminator)
            if end >= 0:
                return self._pop(end + len(terminator))
            if len(self._inbound) >= max_bytes:
                del self._inbound[:max_bytes]
                raise ValueError(f"no terminator within {max_bytes} bytes")
        if not self._inbound:
            return b""
        raise TimeoutError("receive deadline expired; a partial frame stays buffered")

    def _complete_from_inbound(
        self, bounds: tuple[int, bytes, int]
    ) -> bytes | None:
        """One COMPLETE frame off the inbound stream, or None when nothing
        complete is buffered (the closed-path rule — no discards, no quiet
        line, the offending run stays buffered)."""
        max_bytes, terminator, exact = bounds
        if exact:
            if len(self._inbound) >= exact:
                return self._pop(exact)
            return None
        end = self._inbound[:max_bytes].find(terminator)
        if end >= 0:
            return self._pop(end + len(terminator))
        return None

    def _receive(self, bounds: tuple[int, bytes, int]) -> bytes:
        """Serve one receive from the inbound stream under pre-validated
        bounds (the ladder validated them before any state change)."""
        self._advance()
        return self._serve_receive(*bounds)

    async def transfer(
        self, transaction: dict[str, Any], context: OperationContext
    ) -> dict[str, Any]:
        kind = transaction.get("kind")
        if kind not in _FIELDS or set(transaction) != _FIELDS[kind]:
            raise ValueError(
                f"not a section 8.1 stream transaction: {sorted(transaction)}"
            )
        # The backend's own ladder (critic F2, lane 1 F9 — refuse before ANY
        # state change): grammar, then the receive bounds, then the payload
        # type, then liveness, the closed transport, the dispatch marker —
        # and only then is a row consumed, a byte buffered or a transfer
        # recorded. A refused transaction leaves the conversation untouched,
        # so the corrected retry hits the row it should.
        bounds: tuple[int, bytes, int] = (0, b"", 0)
        if kind != "stream_send":
            bounds = _stream_receive_bounds(transaction, self._ceiling)
        if kind != "stream_receive" and not isinstance(transaction["data"], bytes):
            raise ValueError("data must be bytes")
        self._check(context)
        if self.closed:
            # Closed-path parity with SerialLink.take (critic F3 = lane 1
            # F8): evidence already received is real — a buffered COMPLETE
            # frame still delivers; a partial can never complete on a dead
            # reader, so it refuses instead of burning the deadline. Writes
            # refuse outright (the link's own closed-write posture).
            if kind != "stream_receive":
                raise ConnectionError("Transport closed")
            frame = self._complete_from_inbound(bounds)
            if frame is None:
                raise ConnectionError(
                    "Transport closed with a partial frame buffered"
                )
            self.transfers.append(deepcopy(transaction))
            return {"data": frame}
        if kind != "stream_receive" and not getattr(context, "dispatched", False):
            raise ConformanceError("Transmission needs a dispatch marker")
        if kind == "stream_receive":
            data = self._receive(bounds)
            self.transfers.append(deepcopy(transaction))
            return {"data": data}
        self._send_frame(transaction["data"])
        self.transfers.append(deepcopy(transaction))
        if kind == "stream_send":
            return {}
        return {"data": self._receive(bounds)}
