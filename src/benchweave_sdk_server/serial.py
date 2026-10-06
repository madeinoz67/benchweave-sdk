"""The I3a serial provider backend: link, capture services, session, discovery.

Productises the user guide's ``SerialStandaloneHost`` example
(``user_guide/plugin-sdk.qmd``, section "A standalone runtime around the
writer"; that example stays the copy-into-your-project form and is pinned
by ``tests/test_guide_serial_host.py``), adding the fork's reader-thread
link, re-sized for the 3 Mbps class by #393: a 512 KiB reader ring
(>= 1.7 s at the 3 Mbps byte rate of 300 kB/s, >= 2.6 s at the legacy
200 kB/s), a 64 KiB transfer ceiling, a 100 ms quiet line. The transport
speaks the GENERIC OTDP section 8.1 stream kinds exactly as the guide's
example does; no custom serial provider grammar exists on this backend,
and no standards bytes move.

The reconfigure law (issue #407): a baud change is a LINE RESET — a line
reset starts a new conversation over a NEW link (the M1 fold's law, one
level down); the old ring dies with the old link, so "drain" is the old
link closing. ``reconfigure_link`` is one bounded attempt, never a host
retry (A06); the busy guard refuses while a receive is parked on the
link; the allowed switch set is descriptor-declared (``x-negotiated-
bauds``, A02 — the author's declaration, not a host constant) and fails
closed to {boot}-only when the declaration is absent. Boot settings
never change under a switch: the reopen settings are literally
``{**boot_settings, "baud": N}`` and the closed field set admits no
other key. A closed session has no link to reconfigure: a switch past
``close_transport`` refuses typed (``standalone_serial_reconfigure_closed``),
and a close landing DURING a swap is honored in the post-opener window
-- the produced transport closes and the failed row publishes, never a
reconfigured-after-close.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from benchweave_sdk.capture import StandaloneCaptureWriter
from benchweave_sdk.testing import ConformanceError

from .session import (
    TRANSFER_CEILING,
    LoadedPlugin,
    PluginSession,
    transport_ceiling,
)

_TERMINATORS = {"lf": b"\n", "crlf": b"\r\n"}

_LOGGER = logging.getLogger(__name__)

#: The section 8.1 stream transaction field sets, exactly as the guide's
#: example validates them (and as the mock's scripted cells exercise them):
#: strict field sets, unspecified fields refused.
_RECEIVE = {"max_bytes", "termination", "exact_bytes"}
_FIELDS = {
    "stream_send": {"kind", "data"},
    "stream_receive": {"kind"} | _RECEIVE,
    "stream_exchange": {"kind", "data"} | _RECEIVE,
}

_READ_CHUNK = 4096
_JOIN_TIMEOUT_S = 5.0

#: The reconfigure request's closed field set (issue #407): a switch
#: names a baud, nothing else — parity/stop bits/data bits/rtscts are
#: boot-carried, and a request naming any of them refuses by this rule,
#: never silently applied.
_RECONFIGURE_FIELDS = {"baud"}

#: The boot baud default, shared with :func:`open_serial_port` (one
#: definition — the opener's own default is the derivation's).
_BOOT_BAUD_DEFAULT = 115200

#: The poll quantum a receive waits on once the quiet window has expired
#: with a partial frame buffered (FOLD-C): the quiet-line answer no longer
#: applies, and a non-positive wait budget would hot-spin — wait this
#: quantum per loop until the deadline instead.
_IDLE_POLL_S = 0.005


def _stream_receive_bounds(t: dict[str, Any], ceiling: int) -> tuple[int, bytes, int]:
    """The section 8.1 receive bounds against one ceiling, the shared
    definition the serial backend and the byte-stream mock both validate
    through (issue #394: outcome parity is pinned, not hoped — one
    definition cannot drift). The A02 clamp: the ceiling itself is
    ``min(transfer_ceiling, descriptor max_frame_bytes)`` — the plugin's
    own declared bound governs."""
    max_bytes = t["max_bytes"]
    termination = t["termination"]
    exact = t["exact_bytes"]
    if (
        not isinstance(max_bytes, int)
        or isinstance(max_bytes, bool)
        or not 1 <= max_bytes <= ceiling
    ):
        raise ValueError(f"max_bytes must be 1..{ceiling}")
    if termination not in _TERMINATORS:  # serial has no "eom"
        raise ValueError("termination must be 'lf' or 'crlf' on a serial port")
    if exact is not None and (
        not isinstance(exact, int)
        or isinstance(exact, bool)
        or not 0 <= exact <= max_bytes
    ):
        raise ValueError("exact_bytes must be None or 0..max_bytes")
    return max_bytes, _TERMINATORS[termination], exact or 0


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
        Constructor configuration with the 3 Mbps-class defaults (#393:
        512 KiB, 64 KiB, 100 ms). The 512 KiB ring is >= 1.7 s of buffering
        at the 3 Mbps byte rate (300 kB/s: 3,000,000 baud 8N1 carries
        10 bit-times per byte) and >= 2.6 s at the legacy 2 Mbps byte
        rate (200 kB/s), so a stalled consumer keeps more than
        a full negotiation window of the wire while the parser catches up.
        The services clamp the per-receive ceiling with the descriptor's
        ``max_frame_bytes`` — the plugin's own declared bound governs
        (A02 posture).
    """

    def __init__(
        self,
        transport: Transport,
        *,
        # 512 KiB (issue #393): >= 1.7 s of buffering at the 3 Mbps byte
        # rate (300 kB/s: 3_000_000 baud 8N1 carries 10 bit-times per
        # byte), >= 2.6 s at the legacy 2 Mbps byte rate (200 kB/s). The
        # fork's 256 KiB value gave 0.87 s at 3 Mbps — under one
        # negotiation window.
        ring_capacity: int = 512 * 1024,
        transfer_ceiling: int = TRANSFER_CEILING,
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
        self._dropped_bytes = 0
        self._receive_depth = 0
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

    @property
    def dropped_bytes(self) -> int:
        """The cumulative bytes dropped on ring overflow (the oldest bytes
        go first). Diagnostics only — surfaced nowhere yet, by design; a
        future status surface reads it from here."""
        return self._dropped_bytes

    @property
    def receive_depth(self) -> int:
        """The receives currently parked on this link (issue #407).

        The reconfigure busy guard's fact source: a receive that has
        STARTED -- the worker's first instruction has run -- is visible
        here. The visibility claim is bounded at worker-start, not at
        dispatch: a transfer and a reconfigure dispatched in the same
        event-loop tick can pass under the guard (it reads 0 before the
        worker increments), and the parked receive then unwinds through
        the closing link with typed outcomes -- no corruption, but the
        window is real and disclosed rather than claimed away."""
        return self._receive_depth

    @property
    def is_closed(self) -> bool:
        """Whether :meth:`close` has run on this link (the state block's
        link-down fact — a closed link serves nothing, so nothing may
        report a live-looking baud about it)."""
        return self._closed

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
        # The receive-depth counter (issue #407): a parked or running
        # receive is structurally visible — the reconfigure busy guard's
        # fact source. Incremented under the ring's own condition so the
        # guard reads it consistently; decremented in a finally so every
        # exit path (return, raise) unwinds it.
        with self._cond:
            self._receive_depth += 1
        try:
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
                    if self._closed:
                        # Closed-link drain-then-refuse: buffered COMPLETE
                        # frames still deliver (evidence already received is
                        # real — the completeness checks above return them);
                        # a partial can never complete, the reader is dead,
                        # so it refuses now instead of burning the deadline.
                        raise ConnectionError(
                            "serial link is closed with a partial frame buffered"
                        )
                now = time.monotonic()
                if empty and now >= quiet_until:
                    return b""
                if now >= deadline:
                    raise TimeoutError(
                        "receive deadline expired; a partial frame stays buffered"
                    )
                budget = min(quiet_until, deadline) - now
                if budget <= 0:
                    # The quiet window has expired with a partial frame
                    # buffered: the quiet-line answer no longer applies, and a
                    # non-positive wait budget would return immediately — poll
                    # on a small bounded quantum until the deadline.
                    budget = _IDLE_POLL_S
                with self._cond:
                    self._cond.wait(budget + 0.001)
        finally:
            with self._cond:
                self._receive_depth -= 1

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
                        self._dropped_bytes += overflow
                    self._cond.notify_all()
        except BaseException as exc:
            with self._cond:
                self._fault = exc
                self._cond.notify_all()

    def close(self) -> None:
        """Stop the reader, join it, then close the transport; tolerant of
        repeated calls. A closed link's writes refuse; its receives DRAIN
        THEN REFUSE: buffered complete frames still deliver (evidence
        already received is real), while a partial can never complete —
        the reader is dead — so it refuses promptly."""
        with self._cond:
            if self._closed:
                return
            self._closed = True
            self._closing = True
            self._cond.notify_all()
        self._thread.join(timeout=_JOIN_TIMEOUT_S)
        if self._thread.is_alive():
            # The reader is still draining an in-flight port read past the
            # join bound: report it — a silent still-live reader after
            # close looks closed while it still holds the port handle.
            # (The thread is daemon, so the process can still exit; the
            # link stays closed and the transport close runs regardless.)
            _LOGGER.warning(
                "standalone_serial_close: reader still alive after the "
                "%0.0fs join; the transport close still runs",
                _JOIN_TIMEOUT_S,
            )
        with contextlib.suppress(OSError):
            self._transport.close()


class WriterBackedCaptureServices:
    """The five capture members over per-capture :class:`StandaloneCaptureWriter`
    instances with block-buffered appends.

    Issue #394: extracted verbatim from :class:`SerialCaptureServices` so the
    byte-stream mock host serves the SAME capture lifecycle the serial
    backend does — one definition, two hosts. One capture in flight per
    writer instance; a finalised or aborted capture retires its writer, so a
    long-lived host captures repeatedly. Buffered bytes flush to the writer
    at 64 KiB, at finalise, and abort discards them, so a streaming
    adapter's per-frame appends cannot explode the writer's one-file-per-chunk
    staging; the manifest digest is computed by the writer over flushed bytes
    only.
    """

    _BLOCK = 64 * 1024

    def __init__(
        self,
        *,
        capture_root: Any = None,
        capture_max_bytes: int | None = None,
    ) -> None:
        self._capture_max_bytes = capture_max_bytes
        self._capture_root = capture_root
        self._writers: dict[str, StandaloneCaptureWriter] = {}
        self._buffers: dict[str, bytearray] = {}
        self._flushed: dict[str, int] = {}
        # The host lifecycle's per-capture configuration (I3b): the SW-54
        # metadata sidecar written beside the primary at the writer's FIRST
        # append, and the per-capture reservation — min(requested, the
        # configured ceiling); the writer stays the authority.
        self._reservations: dict[str, int] = {}
        self._capture_meta: dict[str, dict[str, Any]] = {}
        self._meta_written: set[str] = set()

    # capture: per-capture writers with block-buffered appends

    def configure_capture(
        self,
        capture_id: str,
        *,
        metadata: dict[str, Any],
        max_bytes: int | None = None,
    ) -> None:
        """Arm one capture's host-side configuration (the lifecycle's
        call): the SW-54 metadata sidecar written beside the primary at the
        writer's FIRST append, and the per-capture reservation —
        ``min(requested, the configured ceiling)`` when both exist; the
        writer stays the reservation's enforcement authority either way.
        The sidecar's ``config`` records the EFFECTIVE reservation (both
        clamps applied), never the raw requested argument — the durable
        evidence names what the writer enforces (B-F3).
        """
        reservation = max_bytes
        if max_bytes is not None and self._capture_max_bytes is not None:
            reservation = min(max_bytes, self._capture_max_bytes)
        if reservation is not None:
            self._reservations[capture_id] = int(reservation)
        effective = self._reservations.get(capture_id, self._capture_max_bytes)
        if effective is not None:
            config = metadata.get("config")
            if isinstance(config, dict):
                metadata = dict(
                    metadata, config={**config, "max_bytes": int(effective)}
                )
        self._capture_meta[capture_id] = dict(metadata)
        self._meta_written.discard(capture_id)

    def capture_progress(self, capture_id: str) -> int:
        """The capture's staged progress: flushed + buffered bytes — the
        host's progress rows never fabricate a count the writer did not
        see. Zero for an unknown id."""
        return self._flushed.get(capture_id, 0) + len(
            self._buffers.get(capture_id, b"")
        )

    def _reservation(self, capture_id: str) -> int | None:
        """The effective reservation for one capture: the per-capture value
        (min(requested, the configured ceiling), set by configure_capture),
        falling back to the configured ceiling."""
        return self._reservations.get(capture_id, self._capture_max_bytes)

    def _flush_threshold(self, capture_id: str) -> int:
        """The flush threshold for one capture: the block size or the
        reservation, whichever is tighter — a small reservation must reach
        the writer promptly (the constructor rule, per capture now)."""
        reservation = self._reservation(capture_id)
        if reservation is not None:
            return min(self._BLOCK, reservation)
        return self._BLOCK

    def _writer_kwargs(self, capture_id: str) -> dict[str, Any]:
        """The writer constructor arguments for one capture: the root plus
        the per-capture reservation when one exists (the composer's
        configuration, A02)."""
        kwargs: dict[str, Any] = {"root": self._capture_root}
        reservation = self._reservations.get(capture_id)
        if reservation is not None:
            kwargs["max_bytes"] = reservation
        elif self._capture_max_bytes is not None:
            kwargs["max_bytes"] = self._capture_max_bytes
        return kwargs

    def _writer_for(self, capture_id: str) -> StandaloneCaptureWriter:
        writer = self._writers.get(capture_id)
        if writer is None:
            writer = StandaloneCaptureWriter(**self._writer_kwargs(capture_id))
            self._writers[capture_id] = writer
        return writer

    async def _writer_append(
        self, capture_id: str, block: bytes, context: Any
    ) -> None:
        """One writer append plus the SW-54 sidecar: the writer owns
        directory creation, so ``metadata.json`` is written into the event
        directory immediately after the FIRST accepted append — a
        sub-block capture's first append is the finalise tail-flush, so
        the sidecar lands there too (the design record's rule)."""
        writer = self._writer_for(capture_id)
        await writer.artifact_append(capture_id, block, context)
        if capture_id in self._meta_written:
            return
        self._meta_written.add(capture_id)
        metadata = self._capture_meta.get(capture_id)
        event = writer.event_path
        if metadata is None or event is None:
            return
        payload = json.dumps(metadata, sort_keys=True).encode("utf-8")
        temp = event / "metadata.json.tmp"
        temp.write_bytes(payload)
        os.replace(temp, event / "metadata.json")

    async def artifact_append(self, capture_id: str, data: bytes, context: Any) -> None:
        """Buffer the append; flush to the per-capture writer at the block
        size or the reservation, whichever is tighter.

        The buffer-path refusal is CONSERVATIVE, not the reservation's
        authority: an un-staged span larger than the whole reservation is
        refused before buffering, while fitting spans are buffered and the
        WRITER enforces the reservation per flush and at finalise — its
        refusal is cleanable (the capture stays abortable, FOLD-B)."""
        buffer = self._buffers.get(capture_id)
        if buffer is None:
            buffer = self._buffers[capture_id] = bytearray()
        reservation = self._reservation(capture_id)
        if reservation is not None and len(buffer) + len(data) > reservation:
            raise ValueError(
                f"append of {len(data)} bytes exceeds the declared "
                f"max_bytes reservation ({reservation} bytes, "
                f"{self._flushed.get(capture_id, 0)} flushed + "
                f"{len(buffer)} buffered)"
            )
        buffer += bytes(data)
        threshold = self._flush_threshold(capture_id)
        while len(buffer) >= threshold:
            block = bytes(buffer[:threshold])
            # Accept-then-account: the writer may refuse the flush (its
            # staged count plus this block would cross the reservation) —
            # the block stays buffered and is counted only on acceptance,
            # so every refusal names true counts and loses no bytes.
            await self._writer_append(capture_id, block, context)
            del buffer[:threshold]
            self._flushed[capture_id] = self._flushed.get(capture_id, 0) + len(block)

    async def artifact_finalise(
        self, capture_id: str, metadata: dict[str, Any], context: Any
    ) -> dict[str, Any]:
        """Flush the buffered tail, then publish through the per-capture
        writer; the digest is computed by the writer over flushed bytes.

        Nothing detaches before the writer accepts: the writer (a fresh
        one included) is attached FIRST, so a refused tail flush or a
        refused finalise leaves the capture abortable — the pre-fold code
        popped writer and buffer up front and a refusal stranded the event
        directory (abort a no-op, the id un-reusable). The buffer retires
        once the writer accepts the tail, so a metadata-fix retry cannot
        double-flush it; the per-capture state retires only on success."""
        writer = self._writers.get(capture_id)
        if writer is None:
            writer = StandaloneCaptureWriter(**self._writer_kwargs(capture_id))
            self._writers[capture_id] = writer
        buffer = self._buffers.get(capture_id)
        if buffer:
            await self._writer_append(capture_id, bytes(buffer), context)
            # The tail was accepted: the services copy retires so a
            # metadata-fix retry cannot double-flush it.
            self._buffers.pop(capture_id, None)
        manifest = await writer.artifact_finalise(capture_id, metadata, context)
        self._writers.pop(capture_id, None)
        self._flushed.pop(capture_id, None)
        self._reservations.pop(capture_id, None)
        self._capture_meta.pop(capture_id, None)
        self._meta_written.discard(capture_id)
        return manifest

    async def artifact_abort(self, capture_id: str) -> None:
        """Discard the buffer and the in-flight capture; publish nothing.
        Unknown ids are a no-op (the writer protocol's abort rule).

        An un-finalised capture's event directory is REMOVED: the writer's
        own abort deliberately leaves it (a published capture stands), and
        a leftover empty directory would wedge the capture_id against
        reuse (the writer's collision check refuses while the name
        exists). The publication marker (``manifest.json``) decides what
        is removed — the writer no-ops on a finalised capture, so the
        removal can only touch an un-published event."""
        self._buffers.pop(capture_id, None)
        self._flushed.pop(capture_id, None)
        self._reservations.pop(capture_id, None)
        self._capture_meta.pop(capture_id, None)
        self._meta_written.discard(capture_id)
        writer = self._writers.pop(capture_id, None)
        if writer is not None:
            event = writer.event_path
            await writer.artifact_abort(capture_id)
            if event is not None and not (event / "manifest.json").exists():
                shutil.rmtree(event, ignore_errors=True)


class SerialCaptureServices(WriterBackedCaptureServices):
    """All eight CaptureServices members over one serial link.

    Productises the guide's ``SerialStandaloneHost`` (whose docstring and
    cells this class mirrors): the transport side validates the GENERIC
    OTDP section 8.1 stream transactions exactly as the guide does — strict
    field sets, only ``lf``/``crlf`` terminators on serial, ``eom`` refused,
    ``exact_bytes`` precedence, the quiet-line ``{"data": b""}`` after the
    quiet window, and unfinished receives staying buffered across
    deadlines — through the link's reader-thread ring. The five capture
    members are inherited from :class:`WriterBackedCaptureServices`.
    ``record_evidence`` appends JSON lines, the host's own
    ``at``/``operation_id`` fields winning over a caller's (the guide's
    shape, unchanged). Real clocks throughout.
    """

    def __init__(
        self,
        link: SerialLink,
        *,
        max_frame_bytes: int,
        capture_root: Any = None,
        evidence_path: Any = None,
        capture_max_bytes: int | None = None,
        reconfigurator: LinkReconfigurator | None = None,
    ) -> None:
        if (
            not isinstance(max_frame_bytes, int)
            or isinstance(max_frame_bytes, bool)
            or max_frame_bytes < 1
        ):
            raise ValueError(
                "standalone_serial_frame: max_frame_bytes must be a positive integer"
            )
        super().__init__(
            capture_root=capture_root, capture_max_bytes=capture_max_bytes
        )
        self._link = link
        self._max_frame_bytes = max_frame_bytes
        self._ceiling = min(link.transfer_ceiling, max_frame_bytes)
        self._evidence_path = evidence_path
        self.evidence: list[dict[str, Any]] = []
        # The link-control capability (issue #407): configuration, present-
        # but-degrading-loudly when absent — the conformance cells' direct
        # construction carries no reconfigurator and the member refuses
        # with the typed not-configured prefix, never a silent no-op. The
        # link-settings bookkeeping rides the same source: without a
        # reconfigurator there is no declared boot state to report, so
        # ``link_state`` answers None (the schema's null arm).
        self._reconfigurator = reconfigurator
        self._boot_settings: dict[str, Any] | None = (
            dict(reconfigurator.boot_settings) if reconfigurator is not None else None
        )
        self._link_settings: dict[str, Any] | None = (
            dict(reconfigurator.boot_settings) if reconfigurator is not None else None
        )
        # Serializes reconfigure_link across guard re-check + close +
        # open + rebind (the refute wave's interleaving class): two
        # concurrent switches queue; the loser's swap closes the winner's
        # link through the normal old.close() path.
        self._reconfigure_lock = asyncio.Lock()
        # The session's own close fact (wave-3): close_transport sets it,
        # and the swap re-checks it inside its critical section and again
        # in the post-opener window -- a close racing a swap must never
        # let the swap rebind a live link onto a closed session.
        self._transport_closed = False

    @property
    def link(self) -> SerialLink:
        """The underlying link (the host's own close path uses it)."""
        return self._link

    # clocks
    def monotonic(self) -> float:
        """The real monotonic clock — deadlines must expire on live time."""
        return time.monotonic()

    def utc_now(self) -> str:
        """The real UTC now, in the SDK stamp's ISO-8601 ``Z`` shape."""
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    # transport (OTDP section 8.1 stream transactions)
    def _live(self, context: Any) -> None:
        if context.is_cancelled() or self.monotonic() >= context.deadline_monotonic:
            raise TimeoutError("operation cancelled or expired")

    def _receive_bounds(self, t: dict[str, Any]) -> tuple[int, bytes, int]:
        """The receive bounds against this link's clamped ceiling (the
        shared ``_stream_receive_bounds`` definition — see its docstring)."""
        return _stream_receive_bounds(t, self._ceiling)

    async def transfer(self, transaction: dict[str, Any], context: Any) -> dict[str, Any]:
        """One bounded exchange over the link, the guide's §8.1 discipline:
        grammar first (refused before any I/O), then the context liveness,
        then the write (short counts refuse), then the receive through the
        link's ring with the context's remaining deadline."""
        kind = transaction.get("kind")
        if kind not in _FIELDS or set(transaction) != _FIELDS[kind]:
            raise ValueError(
                f"not a section 8.1 stream transaction: {sorted(transaction)}"
            )
        max_bytes, terminator, exact = 0, b"", 0
        if kind != "stream_send":
            max_bytes, terminator, exact = self._receive_bounds(transaction)
        if kind != "stream_receive" and not isinstance(transaction["data"], bytes):
            raise ValueError("data must be bytes")
        self._live(context)
        if kind != "stream_receive" and not getattr(context, "dispatched", False):
            # The mock's discipline on the real backend (A06): a transmit
            # happens only under a dispatch marker — honest dispatch_state
            # reporting is a conformance requirement, not a mock luxury.
            # The tolerance is getattr, matching the mock's own read of
            # minimal contexts (a context without the attribute refuses,
            # the same as one whose marker was never set).
            raise ConformanceError("Transmission needs a dispatch marker")
        if kind != "stream_receive":
            data = transaction["data"]
            try:
                sent = await asyncio.to_thread(self._link.write, data)
            except OSError as error:
                raise ConnectionError(f"serial write failed: {error}") from error
            if sent is not None and sent != len(data):
                raise ConnectionError(f"serial write reported {sent} of {len(data)} bytes")
            if kind == "stream_send":
                return {}
        received = await asyncio.to_thread(
            self._link.take,
            max_bytes=max_bytes,
            terminator=terminator,
            exact=exact,
            deadline=context.deadline_monotonic,
        )
        return {"data": received}

    async def close_transport(self, context: Any) -> None:
        """Close the link; tolerant of repeated calls (Adapter.close rule).

        Marks the session closed FIRST: a swap in flight re-checks this
        fact in its post-opener window and refuses to rebind a live link
        onto a closed session (wave-3 R1)."""
        self._transport_closed = True
        self._link.close()

    async def record_evidence(self, entry: dict[str, Any], context: Any) -> None:
        """Append one evidence entry as a JSON line; the host's own ``at``
        and ``operation_id`` fields win over a caller's (the guide's shape,
        unchanged)."""
        record = {**entry, "at": self.utc_now(), "operation_id": context.operation_id}
        self.evidence.append(record)
        if self._evidence_path is not None:
            with self._evidence_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")

    # link control (OTDP §8.1 negotiation support, issue #407)

    def _publish_link_event(
        self,
        event: str,
        from_baud: int,
        to_baud: int,
        context: Any,
        *,
        reason: str | None = None,
    ) -> None:
        """One row of the closed link-event family. ``reason`` is
        optional (the applied row carries none); refused rows publish
        only where both endpoints are known ints — grammar and
        not-configured refusals change nothing about the link state
        machine, and the bus carries the link state machine only."""
        publisher = (
            self._reconfigurator.on_link_event if self._reconfigurator else None
        )
        if publisher is None:
            return
        row: dict[str, Any] = {
            "event": event,
            "from_baud": int(from_baud),
            "to_baud": int(to_baud),
            "operation_id": str(context.operation_id),
        }
        if reason is not None:
            row["reason"] = reason
        publisher(row)

    def link_state(self) -> dict[str, Any] | None:
        """The live link block for ``host_info``/``device_get`` (issue
        #407): current baud, the descriptor's boot baud, and whether any
        switch is negotiable. ``None`` without a reconfigurator — no
        declared boot state to report — and ``None`` whenever the current
        link is closed (a failed swap leaves no serving link; a
        live-looking baud with nothing serving it would be a lie — A06)."""
        if self._reconfigurator is None or self._link_settings is None:
            return None
        if self._link.is_closed:
            return None
        return {
            "baud": _boot_baud(self._link_settings),
            "boot_baud": _boot_baud(self._boot_settings or {}),
            "negotiable": len(self._reconfigurator.allowed_bauds) > 1,
        }

    async def reconfigure_link(
        self, settings: dict[str, Any], context: Any
    ) -> dict[str, Any]:
        """One bounded line-settings switch (the ``LinkControlServices``
        capability member, issue #407).

        The house discipline order (``transfer``'s): grammar first, then
        liveness, then guards, then I/O — the guards re-checked under the
        session's reconfigure lock, which is held across the close, the
        opener and the rebind (one swap at a time; concurrent switches
        serialize). The swap is the fresh-link mint: the old link closes
        (joins its reader — buffered residue dies with it), the deadline
        is re-checked, then the opener runs once at
        ``{**boot_settings, "baud": N}`` — and the deadline is re-checked
        AFTER the opener too (a reopen that outlived its context closes
        the port it opened and answers ``TimeoutError``, never success).
        One attempt, never a host retry (A06): an opener error — or a
        cancellation, which publishes the failed row too — leaves the
        services with NO link (the faulted posture) and raises
        ``ConnectionError``; the caller's explicit fallback reconfigure
        (for the boot baud) is the caller's move, not a host retry.
        """
        # grammar: the closed field set; boot settings never change.
        baud = settings.get("baud") if isinstance(settings, dict) else None
        if (
            not isinstance(settings, dict)
            or set(settings) != _RECONFIGURE_FIELDS
            or not isinstance(baud, int)
            or isinstance(baud, bool)
        ):
            shape = (
                sorted(settings) if isinstance(settings, dict) else type(settings).__name__
            )
            raise ValueError(
                "standalone_serial_reconfigure_fields: a switch request carries "
                f'exactly {{"baud": <int>}}, got {shape}'
            )
        # liveness: refuse before any I/O (the C06/C07 posture).
        self._live(context)
        # guards: capability, allowed set, busy link.
        if self._reconfigurator is None:
            raise ValueError(
                "standalone_serial_reconfigure_not_configured: this serial "
                "session carries no link reconfigurator"
            )
        # One swap at a time: the lock is held across the guard re-checks,
        # the close, the opener and the rebind, so two concurrent switches
        # serialize — the loser closes the winner's link through the normal
        # ``old.close()`` path and no transport is ever orphaned, and a
        # failure answer then genuinely means no serving link (the guards
        # read the CURRENT link; without the lock a queued twin could
        # close a fresh link it never minted).
        async with self._reconfigure_lock:
            # Re-check liveness inside the lock: a caller queued behind a
            # swap whose deadline expired while waiting refuses before
            # any I/O (the C06/C07 posture).
            self._live(context)
            # from_baud is the CURRENT link's baud, read under the lock
            # (wave-3 R4): a twin queued behind a switch must publish the
            # true transition, never a stale pre-switch baud.
            from_baud = _boot_baud(self._link_settings or {})
            # A closed session has no link to reconfigure (wave-3 R3): a
            # stale services reference must not mint a live link past a
            # close.
            if self._transport_closed:
                raise ConnectionError(
                    "standalone_serial_reconfigure_closed: the transport "
                    "is closed; there is no link to reconfigure"
                )
            if baud not in self._reconfigurator.allowed_bauds:
                self._publish_link_event(
                    "reconfigure_refused",
                    from_baud,
                    baud,
                    context,
                    reason=f"baud {baud} is not in the negotiable set "
                    f"{sorted(self._reconfigurator.allowed_bauds)}",
                )
                raise ValueError(
                    "standalone_serial_baud_not_negotiable: "
                    f"{baud} is not in the negotiable set "
                    f"{sorted(self._reconfigurator.allowed_bauds)}"
                )
            if self._link.receive_depth > 0:
                self._publish_link_event(
                    "reconfigure_refused",
                    from_baud,
                    baud,
                    context,
                    reason="a receive is in flight",
                )
                raise ValueError(
                    "standalone_serial_reconfigure_busy: a receive is in flight"
                )
            # the swap (one attempt — A06): copy the live link's
            # configuration, close the old link (joins the reader; the
            # ring dies with it), re-check the deadline, then reopen at
            # the new baud.
            old = self._link
            ring_capacity = old.ring_capacity
            quiet_s = old.quiet_s
            transfer_ceiling = old.transfer_ceiling
            old.close()
            if context.is_cancelled() or self.monotonic() >= context.deadline_monotonic:
                self._publish_link_event(
                    "reconfigure_failed",
                    from_baud,
                    baud,
                    context,
                    reason="the context expired during the close",
                )
                raise TimeoutError(
                    "reconfigure deadline expired; the old link is closed "
                    "(the honest ambiguous posture — no serving link)"
                )
            next_settings = {**self._reconfigurator.boot_settings, "baud": baud}
            reconfigurator = self._reconfigurator
            opened: list[Any] = []

            def _open() -> Any:
                item = reconfigurator.opener(
                    reconfigurator.device_path, next_settings
                )
                opened.append(item)
                return item

            try:
                transport = await asyncio.to_thread(_open)
            except BaseException as exc:
                # The faulted posture: no rebind, no serving link, no
                # retry — the caller owns any fallback move. Cancellation
                # is a BaseException: the failed row publishes and any
                # transport the opener managed to produce closes before
                # the exception propagates. (A cancel landing while the
                # thread is STILL inside a blocked opener cannot reach the
                # produced transport — the disclosed residual; the host's
                # own timeout enforcement sits at the same boundary.)
                for item in opened:
                    with contextlib.suppress(Exception):
                        item.close()
                self._publish_link_event(
                    "reconfigure_failed",
                    from_baud,
                    baud,
                    context,
                    reason=f"{type(exc).__name__}: {exc}",
                )
                if isinstance(exc, Exception):
                    raise ConnectionError(f"serial reopen failed: {exc}") from exc
                raise
            # A close that landed while the host sat inside the reopen:
            # the produced transport closes, the failed row publishes
            # (never a reconfigured row after a close), and the member
            # answers typed -- the swap must not rebind a live link onto
            # a closed session (wave-3 R1).
            if self._transport_closed:
                with contextlib.suppress(Exception):
                    transport.close()
                self._publish_link_event(
                    "reconfigure_failed",
                    from_baud,
                    baud,
                    context,
                    reason="the session closed during the reopen",
                )
                raise ConnectionError(
                    "standalone_serial_reconfigure_closed: the transport "
                    "closed during the reopen; the opened port is closed "
                    "(no serving link)"
                )
            # The deadline is re-checked AFTER the opener too: a reopen
            # that outlived its context answers TimeoutError, never
            # success — and the transport it opened closes (a port opened
            # past its deadline must not silently become the session's
            # link).
            if context.is_cancelled() or self.monotonic() >= context.deadline_monotonic:
                with contextlib.suppress(Exception):
                    transport.close()
                self._publish_link_event(
                    "reconfigure_failed",
                    from_baud,
                    baud,
                    context,
                    reason="the context expired during the reopen",
                )
                raise TimeoutError(
                    "reconfigure deadline expired during the reopen; the "
                    "opened port is closed (no serving link — the honest "
                    "ambiguous posture)"
                )
            self._link = SerialLink(
                transport,
                ring_capacity=ring_capacity,
                transfer_ceiling=transfer_ceiling,
                quiet_s=quiet_s,
            )
            self._link_settings = dict(next_settings)
            self._publish_link_event("reconfigured", from_baud, baud, context)
            return dict(next_settings)

def _serial_settings(plugin: Any) -> dict[str, Any]:
    """The descriptor's transport settings (the serial knobs the opener uses)."""
    settings = plugin.descriptor.get("transport", {}).get("settings", {})
    return settings if isinstance(settings, dict) else {}


def open_serial_port(device: str, settings: dict[str, Any]) -> Any:
    """Open a real serial port through pyserial with the descriptor's own
    declared settings (A02: the plugin's declared bound is the bound). A
    missing pyserial refuses with the prefixed install hint, never a bare
    ImportError."""
    try:
        import serial  # type: ignore[import-untyped]  # pyserial, [server] extra
    except ImportError as exc:
        raise RuntimeError(
            "standalone_serial_pyserial_missing: install 'benchweave-sdk[server]' "
            "for serial transport support"
        ) from exc
    parity = {
        "none": serial.PARITY_NONE,
        "even": serial.PARITY_EVEN,
        "odd": serial.PARITY_ODD,
    }.get(str(settings.get("parity", "none")), serial.PARITY_NONE)
    stop = {1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}.get(
        int(settings.get("stop_bits", 1)), serial.STOPBITS_ONE
    )
    data = {7: serial.SEVENBITS, 8: serial.EIGHTBITS}.get(
        int(settings.get("data_bits", 8)), serial.EIGHTBITS
    )
    return serial.Serial(
        device,
        baudrate=int(settings.get("baud", _BOOT_BAUD_DEFAULT)),
        bytesize=data,
        parity=parity,
        stopbits=stop,
        rtscts=bool(settings.get("rtscts", False)),
        timeout=0.05,
        write_timeout=1.0,
    )


def _boot_baud(settings: dict[str, Any]) -> int:
    """The descriptor's boot baud (the opener's own default is the
    derivation's — one definition), validated like the declared list: a
    positive non-bool int, refusing typed otherwise (a bool baud would
    admit the set ``{1}`` silently)."""
    baud = settings.get("baud", _BOOT_BAUD_DEFAULT)
    if not isinstance(baud, int) or isinstance(baud, bool) or baud <= 0:
        raise ValueError(
            "standalone_serial_boot_baud: declared boot baud "
            f"{baud!r} must be a positive integer"
        )
    return int(baud)


def negotiable_bauds(settings: dict[str, Any]) -> frozenset[int]:
    """The allowed switch set: ``{boot baud} ∪ settings["x-negotiated-bauds"]``.

    The ``x-`` key rides ``transport.settings`` (the schema-legal lane;
    the ``usb_identity_filter`` posture). Validation is structural only —
    a non-empty list of positive non-bool ints — and fails LOUD with the
    prefixed error (the FOLD-F posture: an unparseable declared value
    must not become a silently-empty capability). No range table, no
    speed-plausibility check: which bauds a bench may use is the
    descriptor author's declaration, not a host constant (A02). A
    MISSING key is not an error: the allowed set is ``{boot baud}`` and
    every switch refuses (fail-closed opt-in).
    """
    if not isinstance(settings, dict):
        raise ValueError(
            "standalone_serial_negotiated_bauds: transport settings must be "
            f"a mapping, got {type(settings).__name__}"
        )
    declared = settings.get("x-negotiated-bauds")
    if declared is None:
        return frozenset({_boot_baud(settings)})
    if (
        not isinstance(declared, list)
        or not declared
        or any(
            not isinstance(baud, int) or isinstance(baud, bool) or baud <= 0
            for baud in declared
        )
    ):
        raise ValueError(
            "standalone_serial_negotiated_bauds: declared x-negotiated-bauds "
            f"{declared!r} must be a non-empty list of positive integers"
        )
    return frozenset({_boot_baud(settings)} | set(declared))


@dataclass(frozen=True)
class LinkReconfigurator:
    """The factory's knowledge, made reusable for the reopen (issue #407).

    ``serial_plugin_session`` holds every input the reopen needs — the
    opener, the device path, the boot settings, the declared allowed set
    — so it mints one of these per services object; ``reconfigure_link``
    reuses it. ``on_link_event`` is the host layer's callback (the seam's
    publisher, read at MINT time — the late-bound shape): applied,
    refused and failed rows ride it; ``None`` publishes nothing.
    """

    opener: Callable[[str, dict[str, Any]], Any]
    device_path: str
    boot_settings: dict[str, Any]
    allowed_bauds: frozenset[int]
    on_link_event: Callable[[dict[str, Any]], None] | None = None


def serial_plugin_session(
    plugin: LoadedPlugin,
    device_path: str,
    *,
    open_port: Any = None,
    capture_root: Any = None,
    capture_max_bytes: int | None = None,
) -> PluginSession:
    """A ``PluginSession`` over a serial port: the services factory mints a
    FRESH link + services per connection (the M1 fold's per-connection
    precedent — a reconnect starts a new conversation over a new link, and
    a faulted link never serves a second conversation). ``open_port`` stays
    injectable so tests never need a real port. ``capture_root`` and
    ``capture_max_bytes`` are the host's capture configuration — the root
    the per-capture writers publish under and the configured reservation
    ceiling (I3b's lifecycle wiring).

    The link-control capability (issue #407): the declared allowed set is
    derived HERE, loud and failing at session build (the FOLD-F posture);
    each mint builds the reconfigurator — reading the session's
    ``link_event_publisher`` at MINT time (the late-bound shape, the
    ``cli.py`` factory docstring) — so a reconnect serves the CURRENT
    publisher, not a stale one."""
    settings = _serial_settings(plugin)
    max_frame = transport_ceiling(settings)
    opener = open_port or open_serial_port
    allowed = negotiable_bauds(settings)  # loud at session build
    # The mint ALWAYS carries the baud (the defaulted read — a descriptor
    # whose settings omit it is legal and worked at base): every derived
    # read of the boot/linked settings goes through the same defaulted
    # getter, never a bare index.
    boot_settings = {**settings, "baud": _boot_baud(settings)}

    def factory() -> SerialCaptureServices:
        transport = opener(device_path, boot_settings)
        reconfigurator = LinkReconfigurator(
            opener=opener,
            device_path=device_path,
            boot_settings=dict(boot_settings),
            allowed_bauds=allowed,
            on_link_event=session.link_event_publisher,
        )
        return SerialCaptureServices(
            SerialLink(transport),
            max_frame_bytes=max_frame,
            capture_root=capture_root,
            capture_max_bytes=capture_max_bytes,
            reconfigurator=reconfigurator,
        )

    session: PluginSession = PluginSession(plugin, factory)
    return session


@dataclass(frozen=True)
class SerialPortHooks:
    """The two port hooks discovery needs, injectable so tests never open a
    real port (the Transport protocol's posture, one level up)."""

    enumerate_ports: Callable[[], list[Any]]
    open_port: Callable[[str, dict[str, Any]], Any]


def _pyserial_enumerate() -> list[Any]:
    try:
        from serial.tools import list_ports  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "standalone_serial_pyserial_missing: install 'benchweave-sdk[server]' "
            "for serial transport support"
        ) from exc
    return list(list_ports.comports())


def _default_hooks() -> SerialPortHooks:
    return SerialPortHooks(enumerate_ports=_pyserial_enumerate, open_port=open_serial_port)


def usb_identity_filter(plugin: LoadedPlugin) -> dict[str, Any] | None:
    """The descriptor's declared USB identity hint — ``x-`` extension keys
    under ``transport.settings`` (the only schema-legal lane; the descriptor
    schema grants no addresses). ``None`` when nothing is declared."""
    settings = _serial_settings(plugin)
    vid = settings.get("x-standalone-usb-vid")
    pid = settings.get("x-standalone-usb-pid")
    if vid is None and pid is None:
        return None
    return {"vid": vid, "pid": pid}


def _identity_int(value: Any) -> int | None:
    """A USB id as int: ints pass through, strings parse as base-16 with an
    optional 0x prefix; anything else (bool included) never matches."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip().lower().removeprefix("0x")
        try:
            return int(text, 16)
        except ValueError:
            return None
    return None


def _port_matches(port: Any, hint: dict[str, Any]) -> bool:
    """The candidate carries every USB id the descriptor declares. A
    candidate whose port object lacks an id (``vid``/``pid`` None) never
    matches a declared id — VID alone is distrusted, the fork's posture."""
    for key in ("vid", "pid"):
        declared = hint.get(key)
        if declared is None:
            continue
        want = _identity_int(declared)
        if want is None:
            return False
        actual = _identity_int(getattr(port, key, None))
        if actual is None or actual != want:
            return False
    return True


def _port_name(port: Any) -> str:
    return str(getattr(port, "device", None) or port)


def _identify_timeout_ms(plugin: LoadedPlugin) -> int:
    """The descriptor's identify bound; unbounded identify falls back to the
    strictest declared timeout (the session's lifecycle rule — derived, not
    invented)."""
    policies = plugin.descriptor.get("operations", {})
    row = policies.get("identify", {})
    if isinstance(row, dict):
        declared = int(row.get("timeout_ms", 0))
        if declared > 0:
            return declared
    timeouts = [
        int(item.get("timeout_ms", 0))
        for item in policies.values()
        if isinstance(item, dict)
    ]
    return max(timeouts) if timeouts else 1000


async def _confirm_by_identify(
    plugin: LoadedPlugin,
    port: Any,
    hooks: SerialPortHooks,
    timeout_ms: int,
) -> dict[str, Any] | None:
    """Open one candidate and run the adapter's identify over a fresh link:
    the ONLY transmission discovery performs. The answered identity must
    match the descriptor's declared manufacturer and model; a silent,
    erroring or foreign port is omitted (an unconfirmed port is not a
    device)."""
    from .session import HostOperationContext

    transport = None
    link: SerialLink | None = None
    adapter: Any = None
    try:
        transport = hooks.open_port(_port_name(port), _serial_settings(plugin))
        link = SerialLink(transport)
        services = SerialCaptureServices(
            link, max_frame_bytes=transport_ceiling(_serial_settings(plugin))
        )
        adapter = plugin.adapter_factory() if plugin.adapter_factory else None
        if adapter is None:
            return None
        context = HostOperationContext(
            f"discover-{uuid.uuid4().hex[:8]}", timeout_ms=timeout_ms
        )
        await adapter.open(plugin.descriptor, services, context)
        envelope = await adapter.execute(
            {
                "operation_id": context.operation_id,
                "verb": "identify",
                "arguments": {},
            },
            context,
        )
        if envelope.get("status") != "ok":
            return None
        data = envelope.get("data")
        if not isinstance(data, dict):
            return None
        declared = plugin.descriptor.get("identity", {})
        if (
            data.get("manufacturer") != declared.get("manufacturer")
            or data.get("model") != declared.get("model")
        ):
            return None
        return data
    except ConformanceError as error:
        # Omitted, but not silently: an adapter that transmits without a
        # dispatch marker fails its own conformance (FOLD-D's check) and
        # the developer deserves to know why the device did not appear
        # — the silent-empty class FOLD-F fixed for hints. Foreign,
        # silent and erroring candidates stay unreported by design
        # (AR-4: an unconfirmed port is not a device).
        _LOGGER.warning(
            "serial discovery: %s omitted — %s", _port_name(port), error
        )
        return None
    except Exception:
        # A silent, erroring or foreign candidate is omitted, not reported:
        # an unconfirmed port is not a device (AR-4's posture).
        return None
    finally:
        if adapter is not None:
            with contextlib.suppress(Exception):
                close_context = HostOperationContext(
                    f"discover-close-{uuid.uuid4().hex[:8]}", timeout_ms=timeout_ms
                )
                await adapter.close(close_context)
        if link is not None:
            with contextlib.suppress(Exception):
                link.close()


def _device_row(plugin: LoadedPlugin, identity: dict[str, Any]) -> dict[str, Any]:
    """One _DEVICE_SUMMARY row, schema-verbatim."""
    transport = plugin.descriptor.get("transport", {})
    return {
        "id": plugin.device_id,
        "manufacturer": str(identity.get("manufacturer", "")),
        "model": str(identity.get("model", "")),
        "transport": str(transport.get("type", "")),
        "connection_key": str(transport.get("connection_key", "")),
    }


async def discover_serial_devices(
    plugin: LoadedPlugin,
    *,
    hooks: SerialPortHooks | None = None,
    connected_device: str | None = None,
    connected_identity: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Enumerate candidate ports, filter by the descriptor's declared USB
    identity WHERE DECLARED, confirm each survivor by its identify answer,
    and return the confirmed devices as _DEVICE_SUMMARY rows. The ONLY
    transmissions are the identify exchanges; the connected session's port
    is served from the session's established identity without re-probing."""
    effective = hooks or _default_hooks()
    hint = usb_identity_filter(plugin)
    if hint is not None:
        # An unparseable declared hint would mismatch every port silently
        # (an empty discovery with zero diagnostics): refuse loudly naming
        # the value — fail-closed as before, but visible (FOLD-F).
        for key, value in hint.items():
            if value is not None and _identity_int(value) is None:
                raise ValueError(
                    f"standalone_serial_usb_hint: declared x-standalone-usb-{key} "
                    f"{value!r} does not parse as a USB id"
                )
    timeout_ms = _identify_timeout_ms(plugin)
    rows: list[dict[str, Any]] = []
    for port in effective.enumerate_ports():
        name = _port_name(port)
        if connected_device is not None and name == connected_device:
            rows.append(_device_row(plugin, connected_identity or {}))
            continue
        if hint is not None and not _port_matches(port, hint):
            continue
        answered = await _confirm_by_identify(plugin, port, effective, timeout_ms)
        if answered is None:
            continue
        rows.append(_device_row(plugin, answered))
    return rows
