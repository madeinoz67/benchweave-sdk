"""SerialLink: the reader-thread link over a serial transport.

The fork's reader-thread link, generalised: constructor configuration with
the 3 Mbps-class defaults (#393: 512 KiB ring — at the 3 Mbps byte rate of
300 kB/s that is >= 1.7 s of buffering, >= 2.6 s at the legacy 200 kB/s —
a 64 KiB transfer ceiling, a 100 ms quiet line), oldest-byte drop on
overflow, complete receives only, faults that wake every waiter, and a
close that joins the reader. Every test runs over an in-process loopback
transport — no pyserial, no real port (AR-1's test posture; the Transport
protocol stays injectable).
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from benchweave_sdk_server.serial import SerialLink


class LoopbackPort:
    """pyserial's surface: ``read`` returns what is buffered, blocking up to
    its own short timeout; ``write`` may append a scripted reply."""

    def __init__(
        self,
        inbound: bytes = b"",
        replies: dict[bytes, bytes] | None = None,
        read_timeout: float = 0.05,
    ) -> None:
        self.inbound = bytearray(inbound)
        self.replies = dict(replies or {})
        self.written: list[bytes] = []
        self.reads = 0
        self.closes = 0
        self.read_timeout = read_timeout
        self._data = threading.Event()
        self._fail_read: Exception | None = None

    def write(self, data: bytes) -> int | None:
        self.written.append(bytes(data))
        reply = self.replies.get(bytes(data))
        if reply is not None:
            self.inbound += reply
            self._data.set()
        return len(data)

    def read(self, size: int = 1) -> bytes:
        self.reads += 1
        if self._fail_read is not None:
            error, self._fail_read = self._fail_read, None
            raise error
        while not self.inbound:
            if not self._data.wait(self.read_timeout):
                return b""
            self._data.clear()
        out = bytes(self.inbound[:size])
        del self.inbound[:size]
        return out

    def close(self) -> None:
        self.closes += 1
        self._data.set()


def _link(port: LoopbackPort, **config: Any) -> SerialLink:
    return SerialLink(port, **config)


def _take(link: SerialLink, **overrides: Any) -> bytes:
    """A receive with the shared default deadline (2 s), overridable."""
    overrides.setdefault("max_bytes", 64)
    overrides.setdefault("terminator", b"\n")
    overrides.setdefault("exact", 0)
    overrides.setdefault("deadline", time.monotonic() + 2)
    return link.take(**overrides)


def test_constructor_configures_the_fork_constants_and_refuses_bad_values() -> None:
    port = LoopbackPort()
    link = _link(port)
    # 512 KiB (issue #393): >= 1.7 s at the 3 Mbps byte rate (300 kB/s),
    # >= 2.6 s at the legacy 200 kB/s — the negotiation-critical pre-switch
    # rate keeps more than a second of headroom.
    assert link.ring_capacity == 512 * 1024
    assert link.transfer_ceiling == 64 * 1024
    assert link.quiet_s == 0.1
    with pytest.raises(ValueError, match="standalone_serial_link_ring_capacity"):
        _link(port, ring_capacity=0)
    with pytest.raises(ValueError, match="standalone_serial_link_transfer_ceiling"):
        _link(port, transfer_ceiling=0)
    with pytest.raises(ValueError, match="standalone_serial_link_quiet_s"):
        _link(port, quiet_s=-0.5)


def test_take_returns_only_a_complete_terminated_frame() -> None:
    port = LoopbackPort(b"3.3\n0.1\n")
    link = _link(port)
    assert _take(link) == b"3.3\n"
    assert _take(link) == b"0.1\n"
    link.close()
    assert port.closes == 1


def test_exact_receive_takes_exactly_that_many_bytes() -> None:
    port = LoopbackPort(b"\xf0\xa1\x03\x02AB\n")
    link = _link(port)
    assert _take(link, exact=4) == b"\xf0\xa1\x03\x02"
    assert _take(link, exact=2) == b"AB"
    assert _take(link) == b"\n"
    link.close()


def test_a_quiet_line_answers_empty_before_the_deadline() -> None:
    link = _link(LoopbackPort(), quiet_s=0.05)
    started = time.monotonic()
    assert _take(link, deadline=time.monotonic() + 5) == b""
    assert time.monotonic() - started < 2.0, "a quiet line must not wait out the deadline"


def test_a_partial_frame_stays_buffered_across_a_deadline() -> None:
    port = LoopbackPort(b"3.3")
    link = _link(port)
    with pytest.raises(TimeoutError):
        _take(link, deadline=time.monotonic() + 0.05)
    port.inbound += b"\r\n"
    out = _take(link, terminator=b"\r\n")
    assert out == b"3.3\r\n", "the partial frame must survive the expired receive"
    link.close()


def test_a_line_longer_than_max_bytes_is_refused_and_discarded() -> None:
    port = LoopbackPort(b"123456\nOK\n")
    link = _link(port)
    with pytest.raises(ValueError, match="no terminator within 4"):
        _take(link, max_bytes=4)
    assert _take(link, max_bytes=8) == b"56\n"
    link.close()


def test_a_partial_frame_polls_boundedly_after_the_quiet_window_expires() -> None:
    """A partial frame buffered after the quiet window expired must not
    hot-spin: the wait budget never goes non-positive (the pre-fold code
    computed ``min(quiet_until, deadline) - now``, went negative once
    quiet_until passed with a partial buffered, and ``Condition.wait(<= 0)``
    returns immediately — a measured 0.88–0.97 core). The bound is generous
    (cpu < 0.25 × wall) so the arm measures the spin class, not scheduler
    noise."""
    port = LoopbackPort(b"3.3")  # a partial that never completes
    link = _link(port, quiet_s=0.02)
    started_wall = time.monotonic()
    started_cpu = time.process_time()
    with pytest.raises(TimeoutError):
        _take(link, deadline=time.monotonic() + 1.0)
    wall = time.monotonic() - started_wall
    cpu = time.process_time() - started_cpu
    link.close()
    assert cpu < wall * 0.25, f"hot spin suspected: cpu={cpu:.3f}s wall={wall:.3f}s"


def test_a_transport_error_faults_the_link_and_wakes_every_waiter() -> None:
    port = LoopbackPort()
    port._fail_read = OSError("device gone")
    link = _link(port, quiet_s=0.02)
    with pytest.raises(ConnectionError, match="faulted"):
        link.take(max_bytes=64, terminator=b"\n", exact=0, deadline=time.monotonic() + 5)
    # A faulted link stays faulted — no receive recovers it (NFR-O2 posture).
    with pytest.raises(ConnectionError, match="faulted"):
        link.take(max_bytes=64, terminator=b"\n", exact=0, deadline=time.monotonic() + 5)
    with pytest.raises(ConnectionError, match="faulted"):
        link.write(b"x")
    link.close()


def test_concurrent_waiters_all_wake_on_a_fault() -> None:
    port = LoopbackPort()
    port._fail_read = OSError("device gone")
    link = _link(port, quiet_s=5.0)  # without the fault these would wait out quiet_s
    errors: list[BaseException] = []

    def waiter() -> None:
        try:
            link.take(max_bytes=64, terminator=b"\n", exact=0, deadline=time.monotonic() + 5)
        except BaseException as exc:  # noqa: BLE001 - the test collects it
            errors.append(exc)

    threads = [threading.Thread(target=waiter) for _ in range(3)]
    for thread in threads:
        thread.start()
    time.sleep(0.05)
    assert link.ring_length() == 0
    deadline = time.monotonic() + 5
    while link.ring_length() == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    for thread in threads:
        thread.join(timeout=5)
    assert all(thread.is_alive() is False for thread in threads)
    assert len(errors) == 3 and all(isinstance(exc, ConnectionError) for exc in errors)
    link.close()


def test_overflow_drops_the_oldest_bytes_and_keeps_the_newest_tail() -> None:
    port = LoopbackPort()
    link = _link(port, ring_capacity=16)
    port.inbound += b"0123456789ABCDEFGHIJ"  # 20 bytes into a 16-byte ring
    deadline = time.monotonic() + 5
    while link.ring_length() < 16 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert link.ring_length() == 16
    assert _take(link, max_bytes=16, exact=16, deadline=deadline) == b"456789ABCDEFGHIJ"
    link.close()


def test_overflow_counts_the_dropped_bytes() -> None:
    """The cumulative dropped-bytes counter (FOLD-G): overflow silently
    discarded the oldest bytes with no telemetry — the counter makes the
    loss diagnosable after the fact. Diagnostics only: surfaced nowhere
    yet, by design."""
    port = LoopbackPort()
    link = _link(port, ring_capacity=8)
    port.inbound += b"012345678901234"  # 15 bytes into an 8-byte ring
    deadline = time.monotonic() + 5
    while link.ring_length() < 8 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert link.dropped_bytes == 7
    link.close()


def test_close_joins_the_reader_and_closes_the_transport_once() -> None:
    port = LoopbackPort()
    link = _link(port)
    link.close()
    link.close()
    assert port.closes == 1
    assert not link.reader_alive()
    with pytest.raises(ConnectionError, match="closed"):
        link.take(max_bytes=8, terminator=b"\n", exact=0, deadline=time.monotonic() + 1)
    with pytest.raises(ConnectionError, match="closed"):
        link.write(b"x")


@pytest.mark.timing
def test_a_closed_link_drains_complete_frames_and_refuses_a_partial_fast() -> None:
    """Closed-link semantics (FOLD-H), stated exactly by the docstring:
    drain-then-refuse — buffered COMPLETE frames still deliver (evidence
    already received is real); a partial can never complete, the reader is
    dead, so it refuses promptly instead of burning the deadline."""
    port = LoopbackPort(b"ok\n3.3")  # one complete frame, one partial
    link = _link(port, quiet_s=0.02)
    deadline = time.monotonic() + 5
    while link.ring_length() < 7 and time.monotonic() < deadline:
        time.sleep(0.005)
    link.close()
    assert _take(link, max_bytes=8) == b"ok\n", "a complete frame drains after close"
    started = time.monotonic()
    with pytest.raises(ConnectionError, match="closed"):
        _take(link, max_bytes=8, deadline=time.monotonic() + 2)
    assert time.monotonic() - started < 0.5, "a partial on a dead reader must refuse fast"


def test_a_write_reaches_the_transport_and_reports_the_count() -> None:
    port = LoopbackPort(replies={b"ID?\n": b"ok\n"})
    link = _link(port)
    assert link.write(b"ID?\n") == 4
    assert _take(link, max_bytes=8) == b"ok\n"
    link.close()
