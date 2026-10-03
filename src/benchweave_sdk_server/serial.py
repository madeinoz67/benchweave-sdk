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

import asyncio
import contextlib
import json
import math
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from benchweave_sdk.capture import StandaloneCaptureWriter

from .session import LoadedPlugin, PluginSession

_TERMINATORS = {"lf": b"\n", "crlf": b"\r\n"}

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


class SerialCaptureServices:
    """All eight CaptureServices members over one serial link.

    Productises the guide's ``SerialStandaloneHost`` (whose docstring and
    cells this class mirrors): the transport side validates the GENERIC
    OTDP section 8.1 stream transactions exactly as the guide does — strict
    field sets, only ``lf``/``crlf`` terminators on serial, ``eom`` refused,
    ``exact_bytes`` precedence, the quiet-line ``{"data": b""}`` after the
    quiet window, and unfinished receives staying buffered across
    deadlines — through the link's reader-thread ring. The three capture
    members delegate to a PER-CAPTURE :class:`StandaloneCaptureWriter`
    (one capture in flight per writer instance; a finalised or aborted
    capture retires its writer, so a long-lived host captures repeatedly)
    with block-buffered appends: buffered bytes flush to the writer at
    64 KiB, at finalise, and abort discards them, so a streaming adapter's
    per-frame appends cannot explode the writer's one-file-per-chunk
    staging; the manifest digest is computed by the writer over flushed
    bytes only. ``record_evidence`` appends JSON lines, the host's own
    ``at``/``operation_id`` fields winning over a caller's (the guide's
    shape, unchanged). Real clocks throughout.
    """

    _BLOCK = 64 * 1024

    def __init__(
        self,
        link: SerialLink,
        *,
        max_frame_bytes: int,
        capture_root: Any = None,
        evidence_path: Any = None,
    ) -> None:
        if (
            not isinstance(max_frame_bytes, int)
            or isinstance(max_frame_bytes, bool)
            or max_frame_bytes < 1
        ):
            raise ValueError(
                "standalone_serial_frame: max_frame_bytes must be a positive integer"
            )
        self._link = link
        self._max_frame_bytes = max_frame_bytes
        self._ceiling = min(link.transfer_ceiling, max_frame_bytes)
        self._capture_root = capture_root
        self._evidence_path = evidence_path
        self._writers: dict[str, StandaloneCaptureWriter] = {}
        self._buffers: dict[str, bytearray] = {}
        self.evidence: list[dict[str, Any]] = []

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
        """The receive bounds with the A02 clamp: the per-receive ceiling is
        ``min(transfer_ceiling, descriptor max_frame_bytes)`` — the plugin's
        own declared bound governs."""
        max_bytes = t["max_bytes"]
        termination = t["termination"]
        exact = t["exact_bytes"]
        if (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or not 1 <= max_bytes <= self._ceiling
        ):
            raise ValueError(f"max_bytes must be 1..{self._ceiling}")
        if termination not in _TERMINATORS:  # serial has no "eom"
            raise ValueError("termination must be 'lf' or 'crlf' on a serial port")
        if exact is not None and (
            not isinstance(exact, int)
            or isinstance(exact, bool)
            or not 0 <= exact <= max_bytes
        ):
            raise ValueError("exact_bytes must be None or 0..max_bytes")
        return max_bytes, _TERMINATORS[termination], exact or 0

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
        """Close the link; tolerant of repeated calls (Adapter.close rule)."""
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

    # capture: per-capture writers with block-buffered appends

    def _writer_for(self, capture_id: str) -> StandaloneCaptureWriter:
        writer = self._writers.get(capture_id)
        if writer is None:
            writer = StandaloneCaptureWriter(root=self._capture_root)
            self._writers[capture_id] = writer
        return writer

    async def artifact_append(self, capture_id: str, data: bytes, context: Any) -> None:
        """Buffer the append; flush to the per-capture writer at 64 KiB."""
        buffer = self._buffers.get(capture_id)
        if buffer is None:
            buffer = self._buffers[capture_id] = bytearray()
        buffer += bytes(data)
        while len(buffer) >= self._BLOCK:
            block = bytes(buffer[: self._BLOCK])
            del buffer[: self._BLOCK]
            await self._writer_for(capture_id).artifact_append(capture_id, block, context)

    async def artifact_finalise(
        self, capture_id: str, metadata: dict[str, Any], context: Any
    ) -> dict[str, Any]:
        """Flush the buffered tail, then publish through the per-capture
        writer; the digest is computed by the writer over flushed bytes."""
        writer = self._writers.pop(capture_id, None)
        if writer is None:
            writer = StandaloneCaptureWriter(root=self._capture_root)
        buffer = self._buffers.pop(capture_id, None) or bytearray()
        if buffer:
            await writer.artifact_append(capture_id, bytes(buffer), context)
        return await writer.artifact_finalise(capture_id, metadata, context)

    async def artifact_abort(self, capture_id: str) -> None:
        """Discard the buffer and the in-flight capture; publish nothing.
        Unknown ids are a no-op (the writer protocol's abort rule)."""
        self._buffers.pop(capture_id, None)
        writer = self._writers.pop(capture_id, None)
        if writer is not None:
            await writer.artifact_abort(capture_id)


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
        baudrate=int(settings.get("baud", 115200)),
        bytesize=data,
        parity=parity,
        stopbits=stop,
        rtscts=bool(settings.get("rtscts", False)),
        timeout=0.05,
        write_timeout=1.0,
    )


def serial_plugin_session(
    plugin: LoadedPlugin, device_path: str, *, open_port: Any = None
) -> PluginSession:
    """A ``PluginSession`` over a serial port: the services factory mints a
    FRESH link + services per connection (the M1 fold's per-connection
    precedent — a reconnect starts a new conversation over a new link, and
    a faulted link never serves a second conversation). ``open_port`` stays
    injectable so tests never need a real port."""
    settings = _serial_settings(plugin)
    max_frame = int(settings.get("max_frame_bytes", 0)) or 4096
    opener = open_port or open_serial_port

    def factory() -> SerialCaptureServices:
        transport = opener(device_path, settings)
        return SerialCaptureServices(SerialLink(transport), max_frame_bytes=max_frame)

    return PluginSession(plugin, factory)


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
            link, max_frame_bytes=int(_serial_settings(plugin).get("max_frame_bytes", 0)) or 4096
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
