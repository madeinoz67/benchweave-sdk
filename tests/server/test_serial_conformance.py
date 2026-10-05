# author: Stephen Eaton
"""SW-61 conformance cells for the serial backend (issue #393).

The 12-cell transaction-grammar set (design record "issue #393: ADC
single-channel high-rate sampling", §4.5 + §10 A1): the eight transport
behaviours the contributor fork's 26-cell adapter suite pins, re-expressed
host-side against the SW-60 backend, plus exact-byte echo, ring-overflow
gap visibility, ceiling refusal by name, and deadline-before-dispatch.

Fixtures (design §4.5):
1. in-process — a scripted far end injected as the backend's ``Transport``
   (the fork's proven shape; every platform).
2. pty — ``os.openpty()`` + real pyserial on the slave, a scripted far end
   driving the master; exercises the far end over the real pyserial/termios
   read path (posix-only; skips cleanly where ``os.openpty`` is absent).

Eleven cells run over BOTH fixtures; cell C02 (short-write transport
error) runs in-process only — a pty's kernel cannot make a small
pyserial write report a short count, so the defect class is not
exercisable through the pty fixture (disclosed; the landed
``test_a_short_write_is_a_connection_error`` pins the same posture
in-process).

Cell bodies are plain functions raising :class:`AssertionError` on
violation, so the mutant controls share the exact bodies: each control
runs a discriminating cell against a subclass that removes one protection
(the design's three planted mutants), and requires that failure. If a
mutant passes the whole cell set, the CELL SET is falsified — not the
mutant. Each mutant subclass freezes a copy of the one method it maims;
if the real method changes shape materially, re-derive the mutant at
review (the cells stay live either way).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import select
import threading
import time
from typing import Any

import pytest

from benchweave_sdk_server.serial import SerialCaptureServices, SerialLink
from benchweave_sdk_server.session import HostOperationContext

#: Generous-but-bounded waits: cells stay fast and scheduler-noise-free.
_DEADLINE_S = 5.0
_QUIET_S = 0.05
_READ_CHUNK = 4096
#: The services layer's terminator set (the backend's own posture: serial
#: has no ``eom``). Local spelling, so the mutants reference only what this
#: module defines.
_TERMINATORS = {"lf": b"\n", "crlf": b"\r\n"}


# ---------------------------------------------------------------------------
# fixture 1: the in-process scripted far end (pyserial's surface, scripted)


class _ScriptedPort:
    """pyserial's surface with a scripted far end, in-process.

    ``deliver`` queues far-end -> host bytes; ``written`` records what the
    host wrote (the far end's view); ``short_write`` makes ``write`` report
    the configured count. ``read`` returns immediately when the buffer
    holds bytes and waits briefly on an empty one (pyserial's posture), so
    a reader thread never hot-spins.
    """

    def __init__(self) -> None:
        self.inbound = bytearray()
        self.written: list[bytes] = []
        self._lock = threading.Lock()
        self._data = threading.Event()
        self.short_write: int | None = None
        self.auto_echo = False
        self._open = True

    # far end -> host
    def deliver(self, data: bytes) -> None:
        with self._lock:
            self.inbound += data
            self._data.set()

    # host -> far end
    def write(self, data: bytes) -> int | None:
        with self._lock:
            if not self._open:
                raise OSError("port closed")
            self.written.append(bytes(data))
            if self.auto_echo:
                self.inbound += data
        self._data.set()
        if self.short_write is not None:
            return min(self.short_write, len(data))
        return len(data)

    def read(self, size: int = 1) -> bytes:
        while True:
            out = b""
            with self._lock:
                if self.inbound:
                    out = bytes(self.inbound[:size])
                    del self.inbound[:size]
            if out:
                return out
            if self._data.wait(0.01):
                self._data.clear()
                continue
            return b""

    def close(self) -> None:
        with self._lock:
            self._open = False
        self._data.set()


class _ScriptedFarEnd:
    """The cells' handle on the in-process far end."""

    def __init__(self, port: _ScriptedPort) -> None:
        self._port = port

    def deliver(self, device_to_host: bytes) -> None:
        self._port.deliver(device_to_host)

    def deliver_later(self, data: bytes, delay_s: float) -> None:
        timer = threading.Timer(delay_s, self._port.deliver, args=(data,))
        timer.daemon = True
        timer.start()

    def written_count(self) -> int:
        return sum(len(chunk) for chunk in self._port.written)


# ---------------------------------------------------------------------------
# fixture 2: the pty pair + real pyserial (posix-only)


class _PtyFarEnd:
    """A scripted far end over the pty master fd; the host opens the slave
    with real pyserial.

    A drain thread reads the master (what the host writes) so the far end
    can echo and count; ``deliver`` writes far-end -> host bytes onto the
    master. One far end per cell.
    """

    def __init__(self, master_fd: int) -> None:
        self._fd = master_fd
        self.echo = False
        self._seen = bytearray()
        self._seen_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def _drain(self) -> None:
        while not self._stop.is_set():
            try:
                readable, _, _ = select.select([self._fd], [], [], 0.02)
                if not readable:
                    continue
                data = os.read(self._fd, 4096)
            except OSError:
                break
            if not data:
                break
            with self._seen_lock:
                self._seen += data
            if self.echo:
                self.deliver(bytes(data))

    def deliver(self, data: bytes) -> None:
        os.write(self._fd, data)

    def deliver_later(self, data: bytes, delay_s: float) -> None:
        timer = threading.Timer(delay_s, self.deliver, args=(data,))
        timer.daemon = True
        timer.start()

    def written_count(self) -> int:
        with self._seen_lock:
            return len(self._seen)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        with contextlib.suppress(OSError):
            os.close(self._fd)


# ---------------------------------------------------------------------------
# the shared backend over either fixture


class _Backend:
    """One link + services over a fixture; the cells' single handle."""

    def __init__(
        self,
        kind: str,
        far: Any,
        host_port: Any,
        *,
        quiet_s: float = _QUIET_S,
        **link_config: Any,
    ) -> None:
        self.kind = kind
        self.far = far
        self.port = host_port
        self.link = SerialLink(host_port, quiet_s=quiet_s, **link_config)
        self.services = SerialCaptureServices(
            self.link, max_frame_bytes=256, capture_root=None, evidence_path=None
        )

    def deliver(self, data: bytes) -> None:
        self.far.deliver(data)

    def deliver_later(self, data: bytes, delay_s: float) -> None:
        self.far.deliver_later(data, delay_s)

    def written_count(self) -> int:
        return self.far.written_count()

    def set_echo(self, enabled: bool = True) -> None:
        """The far end echoes what the host writes (the C01 echo cell)."""
        if self.kind == "in_process":
            self.port.auto_echo = enabled
        else:
            self.far.echo = enabled

    def close(self) -> None:
        self.link.close()
        close = getattr(self.far, "close", None)
        if close is not None:
            close()


def _build_in_process() -> _Backend:
    port = _ScriptedPort()
    return _Backend("in_process", _ScriptedFarEnd(port), port)


def _build_pty(link_config: dict[str, Any] | None = None) -> tuple[Any, int]:
    """A pty-backed backend plus the slave fd (the caller closes it)."""
    if not hasattr(os, "openpty"):
        pytest.skip("posix pty unavailable")
    master_fd, slave_fd = os.openpty()
    # Raw mode: the default line discipline (ICANON/ECHO) would hold
    # newline-less input in the line buffer and echo writes back — neither
    # resembles a data radio. Raw delivers bytes as they come.
    try:
        import termios
        import tty

        tty.setraw(master_fd)
    except (ImportError, OSError, termios.error):  # pragma: no cover
        os.close(master_fd)
        os.close(slave_fd)
        pytest.skip("pty raw mode unavailable")
    try:
        import serial  # pyserial, [server] extra

        host_port = serial.Serial(
            os.ttyname(slave_fd), baudrate=115200, timeout=0.05, write_timeout=1.0
        )
    except ImportError:  # pragma: no cover — the extra is installed in CI
        os.close(master_fd)
        os.close(slave_fd)
        pytest.skip("pyserial unavailable")
    return _Backend("pty", _PtyFarEnd(master_fd), host_port, **(link_config or {})), slave_fd


@pytest.fixture(params=["in_process", "pty"])
def backend(request: Any) -> Any:
    box, slave_fd = (
        (_build_in_process(), None)
        if request.param == "in_process"
        else _build_pty()
    )
    try:
        yield box
    finally:
        box.close()
        if slave_fd is not None:
            os.close(slave_fd)


# ---------------------------------------------------------------------------
# cell bodies — every failure is an AssertionError


def _tx(services: SerialCaptureServices, ctx: Any, data: bytes) -> None:
    asyncio.run(services.transfer({"kind": "stream_send", "data": data}, ctx))


def _rx(
    services: SerialCaptureServices,
    ctx: Any,
    *,
    max_bytes: int = 64,
    termination: str = "lf",
    exact_bytes: int | None = None,
) -> bytes:
    result = asyncio.run(
        services.transfer(
            {
                "kind": "stream_receive",
                "max_bytes": max_bytes,
                "termination": termination,
                "exact_bytes": exact_bytes,
            },
            ctx,
        )
    )
    return result["data"]  # type: ignore[no-any-return]


def _xchg(
    services: SerialCaptureServices, ctx: Any, data: bytes, **rx: Any
) -> bytes:
    result = asyncio.run(
        services.transfer(
            {
                "kind": "stream_exchange",
                "data": data,
                "max_bytes": rx.get("max_bytes", 64),
                "termination": rx.get("termination", "lf"),
                "exact_bytes": rx.get("exact_bytes"),
            },
            ctx,
        )
    )
    return result["data"]  # type: ignore[no-any-return]


def _ctx(timeout_s: float = _DEADLINE_S) -> Any:
    ctx = HostOperationContext(f"op-{time.monotonic_ns()}", timeout_ms=int(timeout_s * 1000))
    return ctx


def _ctx_marked(timeout_s: float = _DEADLINE_S) -> Any:
    """A live context carrying the dispatch marker (transmits need one)."""
    ctx = _ctx(timeout_s)
    asyncio.run(ctx.mark_dispatch_started())
    return ctx


def _expired(timeout_s: float = 0.02) -> Any:
    """A context whose deadline has already passed."""
    ctx = _ctx(timeout_s)
    time.sleep(timeout_s + 0.05)
    return ctx


# C01 exact-byte echo: the far end echoes; an exact receive takes it.
# The echo receive retries the quiet answer (pty round-trip latency can
# outlast the quiet window; the property is that the echo completes).
def _cell_c01(backend: Any) -> None:
    backend.set_echo(True)
    _tx(backend.services, _ctx_marked(), b"PING\n")
    got = b""
    for _ in range(10):
        got = _rx(backend.services, _ctx_marked(), exact_bytes=5)
        if got:
            break
    assert got == b"PING\n", f"exact echo mismatch: {got!r}"


# C02 exact-byte contract break: a short write count is a transport error.
def _cell_c02(backend: _Backend) -> None:
    backend.port.short_write = 1
    ctx = _ctx_marked()
    refused = None
    try:
        _tx(backend.services, ctx, b"HELLO")
    except ConnectionError as exc:
        refused = str(exc)
    assert refused is not None, "a short write must refuse as a transport error"
    backend.port.short_write = None
    # The landed posture: operation-level refusal; the link stays alive.
    quiet = _rx(backend.services, _ctx_marked())
    assert quiet == b"", "the link must survive a short-write refusal"


# C03 a frame the line pauses inside is kept until complete.
def _cell_c03(backend: _Backend) -> None:
    ctx = _ctx_marked(timeout_s=0.3)
    backend.deliver(b"he")
    interrupted = None
    try:
        _rx(backend.services, ctx, max_bytes=8)
    except TimeoutError:
        interrupted = True
    assert interrupted is not None, "an incomplete frame must not answer as complete"
    backend.deliver(b"llo\n")
    got = _rx(backend.services, _ctx_marked(), max_bytes=8)
    assert got == b"hello\n", f"the buffered partial must complete: {got!r}"


# C04 a reply after a quiet read still completes (the fork cell's
# script-order shape: the quiet read answers, THEN the reply, THEN the
# completing receive — no wall-clock race with the quiet window).
def _cell_c04(backend: _Backend) -> None:
    quiet = _rx(backend.services, _ctx_marked())
    assert quiet == b"", "nothing queued: the quiet answer"
    backend.deliver(b"late\n")
    got = _rx(backend.services, _ctx_marked())
    assert got == b"late\n", f"a reply after quiet must complete: {got!r}"


# C05 no reply by the deadline: the quiet answer, after the quiet window.
def _cell_c05(services: Any) -> None:
    started = time.monotonic()
    got = _rx(services, _ctx_marked())
    elapsed = time.monotonic() - started
    assert got == b"", "an empty line answers quiet"
    assert elapsed >= 0.5 * _QUIET_S, (
        f"the quiet answer must wait the quiet window (mutant M2's instant "
        f"answer fails here); elapsed={elapsed:.3f}s"
    )
    assert elapsed < _DEADLINE_S, "the quiet answer must not wait out the deadline"


# C06 an expired context never transmits.
def _cell_c06(backend: _Backend) -> None:
    ctx = _expired()
    refused = None
    try:
        _tx(backend.services, ctx, b"NEVER")
    except TimeoutError:
        refused = True
    assert refused is not None, "an expired context must refuse the transmit"
    assert backend.written_count() == 0, "nothing may reach the wire"


# C07 a cancelled context never transmits.
def _cell_c07(backend: _Backend) -> None:
    ctx = _ctx_marked()
    ctx.cancel()
    refused = None
    try:
        _tx(backend.services, ctx, b"NEVER")
    except TimeoutError:
        refused = True
    assert refused is not None, "a cancelled context must refuse the transmit"
    assert backend.written_count() == 0, "nothing may reach the wire"


# C08 an overlong line is refused and the next receive resynchronises.
# A quiet answer before the delivery lands (pty latency) just retries.
def _cell_c08(backend: _Backend) -> None:
    ctx = _ctx_marked()
    backend.deliver(b"aaaaaaaa" + b"OK\n")
    refusals = 0
    got = b""
    for _ in range(8):
        try:
            got = _rx(backend.services, ctx, max_bytes=4)
        except ValueError:
            refusals += 1
            continue
        if got == b"OK\n":
            break
    assert got == b"OK\n", f"the receive after the discards must resync: {got!r}"
    assert refusals >= 1, "at least one ceiling refusal must precede the resync"


# C09 interleaved data inside a reply is buffered for the next receive.
# A quiet answer before the delivery lands (pty latency) just retries: the
# property under test is the ordering (first frame first, straggler kept).
def _cell_c09(backend: _Backend) -> None:
    ctx = _ctx_marked()
    backend.deliver(b"DATA\nACK\n")
    first = b""
    for _ in range(8):
        first = _rx(backend.services, ctx, max_bytes=16)
        if first:
            break
    second = b""
    for _ in range(8):
        second = _rx(backend.services, _ctx_marked(), max_bytes=16)
        if second:
            break
    assert first == b"DATA\n", f"the first terminated frame first: {first!r}"
    assert second == b"ACK\n", f"the straggler must stay buffered: {second!r}"


# C10 the ceiling refuses by name: max_bytes above the A02 clamp.
def _cell_c10(services: Any) -> None:
    refused = None
    try:
        _rx(services, _ctx_marked(), max_bytes=4096)
    except ValueError as exc:
        refused = str(exc)
    assert refused is not None, "max_bytes above the ceiling must refuse"
    assert "1..256" in refused, f"the refusal must name the ceiling: {refused!r}"


# C11 ring-overflow gap visibility: drops counted, tail kept, ring bounded.
def _cell_c11(link: SerialLink, deliver: Any) -> None:
    deliver(b"0123456789ABCDEFGHIJ")
    deadline = time.monotonic() + 5
    while link.ring_length() < 16 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert link.ring_length() == 16, "the ring is bounded at its capacity"
    assert link.dropped_bytes == 4, (
        f"the overflow drop must be counted (oldest first): "
        f"{link.dropped_bytes}"
    )
    tail = asyncio.run(
        _exact_take(link)
    )
    assert tail == b"456789ABCDEFGHIJ", (
        f"the newest tail must survive (mutant M1 keeps the stale head): "
        f"{tail!r}"
    )


async def _exact_take(link: SerialLink) -> bytes:
    return await asyncio.to_thread(
        link.take,
        max_bytes=16,
        terminator=b"\n",
        exact=16,
        deadline=time.monotonic() + _DEADLINE_S,
    )


# C12 deadline-before-dispatch: an expired context refuses an exchange
# before anything reaches the wire.
def _cell_c12(backend: _Backend) -> None:
    ctx = _expired()
    refused = None
    try:
        _xchg(backend.services, ctx, b"NEVER\n", max_bytes=16)
    except TimeoutError:
        refused = True
    assert refused is not None, "an expired context must refuse the exchange"
    assert backend.written_count() == 0, "the exchange path must not write first"


# ---------------------------------------------------------------------------
# the 12 cells over the fixtures


def test_c01_exact_byte_echo(backend: Any) -> None:
    _cell_c01(backend)


def test_c02_short_write_is_a_transport_error_in_process_only(backend: Any) -> None:
    if backend.kind == "pty":
        pytest.skip("C02: a pty's kernel cannot short-write a small buffer")
    _cell_c02(backend)


def test_c03_frame_paused_inside_is_kept_until_complete(backend: Any) -> None:
    _cell_c03(backend)


def test_c04_reply_after_a_quiet_read_still_completes(backend: Any) -> None:
    _cell_c04(backend)


def test_c05_no_reply_by_deadline_is_the_quiet_answer(backend: Any) -> None:
    _cell_c05(backend.services)


def test_c06_expired_context_never_transmits(backend: Any) -> None:
    _cell_c06(backend)


def test_c07_cancelled_context_never_transmits(backend: Any) -> None:
    _cell_c07(backend)


def test_c08_overlong_line_refused_then_resyncs(backend: Any) -> None:
    _cell_c08(backend)


def test_c09_interleaved_data_inside_a_reply_is_buffered(backend: Any) -> None:
    _cell_c09(backend)


def test_c10_ceiling_refuses_by_name(backend: Any) -> None:
    _cell_c10(backend.services)


def test_c11_ring_overflow_gap_visibility() -> None:
    # In-process: a 20-byte burst into a 16-byte ring.
    port = _ScriptedPort()
    link = SerialLink(port, ring_capacity=16, quiet_s=_QUIET_S)
    try:
        _cell_c11(link, port.deliver)
    finally:
        link.close()
    # pty (posix): the same cell over the real pyserial read path — one
    # reader per port, so the small ring is the BACKEND's link.
    if hasattr(os, "openpty"):
        box, slave_fd = _build_pty({"ring_capacity": 16, "quiet_s": _QUIET_S})
        try:
            _cell_c11(box.link, box.far.deliver)
        finally:
            box.close()
            os.close(slave_fd)


def test_c12_deadline_before_dispatch(backend: Any) -> None:
    _cell_c12(backend)


# ---------------------------------------------------------------------------
# the three planted mutants (design §10 A1): each must fail >= 1 cell


class _MutantLinkDropsNewest(SerialLink):
    """M1: overflow drops the NEWEST bytes (keeps the stale head).

    A frozen copy of ``SerialLink._drain`` with the drop direction flipped;
    the real one must never look like this.
    """

    def _drain(self) -> None:
        try:
            while not self._closing:
                chunk = self._transport.read(_READ_CHUNK)
                if not chunk:
                    continue
                with self._cond:
                    self._ring += chunk
                    overflow = len(self._ring) - self._ring_capacity
                    if overflow > 0:
                        del self._ring[self._ring_capacity :]
                        self._dropped_bytes += overflow
                    self._cond.notify_all()
        except BaseException as exc:  # noqa: BLE001 — the real handler's shape
            with self._cond:
                self._fault = exc
                self._cond.notify_all()


class _MutantLinkQuietRemoved(SerialLink):
    """M2: the quiet-line wait is gone — an empty ring answers b"" at once."""

    def take(
        self,
        *,
        max_bytes: int,
        terminator: bytes,
        exact: int,
        deadline: float,
    ) -> bytes:
        while True:
            with self._cond:
                if self._fault is not None:
                    raise ConnectionError(f"serial transport faulted: {self._fault}")
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
            if empty:
                return b""  # THE MUTANT: no quiet window at all
            if time.monotonic() >= deadline:
                raise TimeoutError("receive deadline expired")
            time.sleep(0.005)


# ---------------------------------------------------------------------------


class _MutantServicesCeilingUnchecked(SerialCaptureServices):
    """M3: the per-receive ceiling is not enforced (any positive max_bytes)."""

    def _receive_bounds(self, t: dict[str, Any]) -> tuple[int, bytes, int]:
        max_bytes = t["max_bytes"]
        termination = t["termination"]
        exact = t["exact_bytes"]
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
            raise ValueError(f"max_bytes must be 1..{self._ceiling}")
        if termination not in _TERMINATORS:
            raise ValueError("termination must be 'lf' or 'crlf' on a serial port")
        if exact is not None and (
            not isinstance(exact, int)
            or isinstance(exact, bool)
            or not 0 <= exact <= max_bytes
        ):
            raise ValueError("exact_bytes must be None or 0..max_bytes")
        return max_bytes, _TERMINATORS[termination], exact or 0


def test_mutant_m1_ring_drops_newest_fails_c11() -> None:
    port = _ScriptedPort()
    link = _MutantLinkDropsNewest(port, ring_capacity=16, quiet_s=_QUIET_S)
    try:
        with pytest.raises(AssertionError, match="newest tail must survive"):
            _cell_c11(link, port.deliver)
    finally:
        link.close()


def test_mutant_m2_quiet_wait_removed_fails_c05() -> None:
    port = _ScriptedPort()
    link = _MutantLinkQuietRemoved(port, quiet_s=_QUIET_S)
    services = SerialCaptureServices(link, max_frame_bytes=256)
    try:
        with pytest.raises(AssertionError, match="must wait the quiet window"):
            _cell_c05(services)
    finally:
        link.close()


def test_mutant_m3_ceiling_unchecked_fails_c10() -> None:
    port = _ScriptedPort()
    services = _MutantServicesCeilingUnchecked(
        SerialLink(port, quiet_s=_QUIET_S), max_frame_bytes=256
    )
    with pytest.raises(AssertionError, match="max_bytes above the ceiling must refuse"):
        _cell_c10(services)
    link = services.link
    link.close()
