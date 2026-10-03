"""The I3a serial provider backend: link, capture services, session, discovery.

Productises the user guide's ``SerialStandaloneHost`` example
(``user_guide/plugin-sdk.qmd``, section "A standalone runtime around the
writer"; that example stays the copy-into-your-project form and is pinned
by ``tests/test_guide_serial_host.py``), adding the fork's reader-thread
link for the 2 Mbaud class. The fork's constants became constructor
configuration with the fork's values as defaults: a 256 KiB reader ring, a
64 KiB transfer ceiling, a 100 ms quiet line. The transport speaks the
GENERIC OTDP section 8.1 stream kinds exactly as the guide's example does;
no custom serial provider grammar exists on this backend, and no standards
bytes move.
"""

from __future__ import annotations

import contextlib
import math
import threading
import time
from typing import Protocol

_TERMINATORS = {"lf": b"\n", "crlf": b"\r\n"}

_READ_CHUNK = 4096
_JOIN_TIMEOUT_S = 5.0


class Transport(Protocol):
    """pyserial's surface, injectable so tests never need a real port.

    ``write`` returns the sent count or ``None`` (pyserial's own
    ``rs485.RS485`` and ``cp2110://`` ports report no count and are
    trusted); ``read`` returns what is buffered, returning early on the
    port's own short timeout; ``close`` is idempotent-tolerant.
    """

    def write(self, data: bytes) -> int | None: ...

    def read(self, size: int = 1) -> bytes: ...

    def close(self) -> None: ...


class SerialLink:
    """One reader-thread link over a serial transport.

    A dedicated reader thread drains the transport into a bounded ring
    (a ``bytearray`` guarded by one :class:`threading.Condition`); overflow
    drops the OLDEST bytes; :meth:`take` returns only complete receives: a
    terminated frame, an exact count, or the quiet-line ``b""`` answered
    when no byte at all arrives within the quiet window. Transport errors
    fault the link and wake every waiter; a faulted link stays faulted
    (NFR-O2 posture — reconnect required), and close joins the reader.

    Parameters
    ----------
    transport
        Anything with pyserial's ``write``/``read``/``close`` surface
        (:class:`Transport`).
    ring_capacity, transfer_ceiling, quiet_s
        Constructor configuration with the fork's values as defaults
        (256 KiB, 64 KiB, 100 ms). The services clamp the per-receive
        ceiling with the descriptor's ``max_frame_bytes`` — the plugin's
        own declared bound governs (A02 posture).
    """

    def __init__(
        self,
        transport: Transport,
        *,
        ring_capacity: int = 256 * 1024,
        transfer_ceiling: int = 64 * 1024,
        quiet_s: float = 0.1,
    ) -> None:
        if (
            not isinstance(ring_capacity, int)
            or isinstance(ring_capacity, bool)
            or ring_capacity <= 0
        ):
            raise ValueError(
                "standalone_serial_link_ring_capacity: must be a positive integer"
            )
        if (
            not isinstance(transfer_ceiling, int)
            or isinstance(transfer_ceiling, bool)
            or transfer_ceiling <= 0
        ):
            raise ValueError(
                "standalone_serial_link_transfer_ceiling: must be a positive integer"
            )
        if not (
            isinstance(quiet_s, (int, float))
            and not isinstance(quiet_s, bool)
            and quiet_s >= 0
            and math.isfinite(quiet_s)
        ):
            raise ValueError(
                "standalone_serial_link_quiet_s: must be a finite nonnegative number of seconds"
            )
        self._transport = transport
        self._ring_capacity = ring_capacity
        self._transfer_ceiling = transfer_ceiling
        self._quiet_s = float(quiet_s)
        self._ring = bytearray()
        self._cond = threading.Condition()
        self._fault: BaseException | None = None
        self._closing = False
        self._closed = False
        self._thread = threading.Thread(
            target=self._drain, name="benchweave-serial-reader", daemon=True
        )
        self._thread.start()

    @property
    def ring_capacity(self) -> int:
        """The bounded ring's capacity in bytes (overflow drops the oldest)."""
        return self._ring_capacity

    @property
    def transfer_ceiling(self) -> int:
        """The link's per-receive ceiling before the descriptor clamp."""
        return self._transfer_ceiling

    @property
    def quiet_s(self) -> float:
        """The quiet-window length in seconds."""
        return self._quiet_s

    def ring_length(self) -> int:
        """The ring's current length (test and soak instrumentation)."""
        with self._cond:
            return len(self._ring)

    def reader_alive(self) -> bool:
        """Whether the reader thread is running."""
        return self._thread.is_alive()

    def write(self, data: bytes) -> int | None:
        """Transmit through the transport; a faulted or closed link refuses.
        pyserial reports a short count without raising when a pending write
        is cancelled or under write_timeout=0 — part of a frame on the wire
        must not pass as sent: the caller (the services layer) checks the
        returned count."""
        if self._closed or self._closing:
            raise ConnectionError("serial link is closed")
        if self._fault is not None:
            raise ConnectionError(
                f"serial transport faulted: {self._fault}"
            ) from self._fault
        return self._transport.write(data)

    def take(
        self,
        *,
        max_bytes: int,
        terminator: bytes,
        exact: int,
        deadline: float,
    ) -> bytes:
        """One complete receive off the ring.

        Returns a terminated frame, an exact count, or the quiet-line
        ``b""`` (no byte at all within the quiet window). Raises
        ``ValueError`` (an overlong unterminated line — the offending run
        is discarded so the next receive can resynchronise),
        ``TimeoutError`` (deadline expired; any partial frame stays
        buffered for the next receive), ``ConnectionError`` (faulted or
        closed link).
        """
        quiet_until = time.monotonic() + self._quiet_s
        while True:
            with self._cond:
                if self._fault is not None:
                    raise ConnectionError(
                        f"serial transport faulted: {self._fault}"
                    ) from self._fault
                if self._closed and not self._ring:
                    raise ConnectionError("serial link is closed")
                if exact:
                    if len(self._ring) >= exact:
                        return self._pop(exact)
                else:
                    end = self._ring[:max_bytes].find(terminator)
                    if end >= 0:
                        return self._pop(end + len(terminator))
                    if len(self._ring) >= max_bytes:
                        del self._ring[:max_bytes]
                        raise ValueError(f"no terminator within {max_bytes} bytes")
                empty = not self._ring
            now = time.monotonic()
            if empty and now >= quiet_until:
                return b""
            if now >= deadline:
                raise TimeoutError(
                    "receive deadline expired; a partial frame stays buffered"
                )
            budget = min(quiet_until, deadline) - now
            with self._cond:
                self._cond.wait(budget + 0.001)

    def _pop(self, count: int) -> bytes:
        out = bytes(self._ring[:count])
        del self._ring[:count]
        return out

    def _drain(self) -> None:
        """The reader thread: drain the transport into the bounded ring.
        Transport errors fault the link and wake every waiter; a close
        ends the loop after the in-flight read returns."""
        try:
            while not self._closing:
                chunk = self._transport.read(_READ_CHUNK)
                if not chunk:
                    continue
                with self._cond:
                    self._ring += chunk
                    overflow = len(self._ring) - self._ring_capacity
                    if overflow > 0:
                        del self._ring[:overflow]
                    self._cond.notify_all()
        except BaseException as exc:
            with self._cond:
                self._fault = exc
                self._cond.notify_all()

    def close(self) -> None:
        """Stop the reader, join it, then close the transport; tolerant of
        repeated calls. A closed link's receives and writes refuse."""
        with self._cond:
            if self._closed:
                return
            self._closed = True
            self._closing = True
            self._cond.notify_all()
        self._thread.join(timeout=_JOIN_TIMEOUT_S)
        with contextlib.suppress(OSError):
            self._transport.close()
