# author: Stephen Eaton
"""Link reconfiguration cells for the serial backend (issue #407).

The negotiated serial transport (design record "issue #407: the negotiated
serial transport", §7 proof set): the R-cells pin the services-level
``reconfigure_link`` capability — the fresh-link mint (a line reset starts a
new conversation over a NEW link; the old ring dies with the old link), the
grammar/liveness/guard order, the busy guard on a mid-receive link, the
descriptor-declared allowed set, the bounded one-attempt posture, the typed
failure posture, the closed link-event shape, and the module law that boot
settings never change under a switch.

Cell bodies are plain functions raising :class:`AssertionError` on
violation, so the mutant controls share the exact bodies: each control runs
a cell against the backend with one protection removed on disk (cp backup,
edit, run, restore — the conformance suite's own doctrine, one level up) and
requires that failure. If a mutant passes the whole cell set, the CELL SET
is falsified — test the cell set, not the mutant.

All cells assert observed state; no cell asserts a wall-clock difference.
The harness never opens a real port: the opener is injectable and returns
in-process doubles (the conformance fixture-1 shape).
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest

from benchweave_sdk_server.serial import (
    LinkReconfigurator,
    SerialCaptureServices,
    SerialLink,
    negotiable_bauds,
)
from benchweave_sdk_server.session import HostOperationContext

#: Generous-but-bounded waits: cells stay fast and scheduler-noise-free.
_DEADLINE_S = 5.0

_BOOT = {"baud": 115200, "parity": "none", "rtscts": False}
_DECLARED = {**_BOOT, "x-negotiated-bauds": [3_000_000]}
_TARGET = 3_000_000


class _SwitchPort:
    """pyserial's surface over an in-process buffer; one port per OPEN.

    A reopen mints a NEW port object — the real reopen's shape (a new
    pyserial port over the same device path), which is what makes the
    fresh-link swap observable: the old link's transport dies with its
    link.
    """

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = dict(settings)
        self.inbound = bytearray()
        self.written: list[bytes] = []
        self._lock = threading.Lock()
        self._data = threading.Event()
        self._open = True

    def deliver(self, data: bytes) -> bytes:
        """Far end -> host bytes."""
        with self._lock:
            self.inbound += data
            self._data.set()
        return b""

    def write(self, data: bytes) -> int | None:
        with self._link_lock():
            if not self._open:
                raise OSError("port closed")
            self.written.append(bytes(data))
        self._data.set()
        return len(data)

    def read(self, size: int = 1) -> bytes:
        while True:
            out = b""
            with self._link_lock():
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
        with self._link_lock():
            _ = self._open
            self._open = False
        self._data.set()

    def _link_lock(self) -> threading.Lock:
        """The port's own lock (named for the report's readability)."""
        return self._lock


class _Opener:
    """A counting opener: one fresh :class:`_SwitchPort` per open, every
    (device, settings) recorded and every built port kept — the fake of
    record for the swap."""

    def __init__(self) -> None:
        self.opens: list[tuple[str, dict[str, Any]]] = []
        self.built: list[_SwitchPort] = []

    def __call__(self, device: str, settings: dict[str, Any]) -> _SwitchPort:
        self.opens.append((device, dict(settings)))
        port = _SwitchPort(settings)
        self.built.append(port)
        return port


def _broken_opener(opener: _Opener) -> Callable[[str, dict[str, Any]], _SwitchPort]:
    """An opener that records the open, then fails like a vanished device."""

    def _broken(device: str, settings: dict[str, Any]) -> _SwitchPort:
        opener.opens.append((device, dict(settings)))
        raise OSError("device vanished")

    return _broken


def _services(
    opener: _Opener,
    *,
    settings: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> SerialCaptureServices:
    """The services under test: a fresh link over the opener's first open,
    with a reconfigurator (the session factory's own construction)."""
    declared = _DECLARED if settings is None else settings
    link = SerialLink(opener("/dev/fake0", declared))
    reconfigurator = LinkReconfigurator(
        opener=opener,
        device_path="/dev/fake0",
        boot_settings=dict(declared),
        allowed_bauds=negotiable_bauds(declared),
        on_link_event=(events.append if events is not None else None),
    )
    return SerialCaptureServices(
        link,
        max_frame_bytes=4096,
        reconfigurator=reconfigurator,
    )


def _ctx() -> HostOperationContext:
    return HostOperationContext(f"cell-{uuid.uuid4().hex[:8]}", timeout_ms=5000)


def _current_port(services: SerialCaptureServices) -> _SwitchPort:
    """The transport behind the services' current link (test visibility)."""
    transport = services.link._transport  # noqa: SLF001 - test seam
    assert isinstance(transport, _SwitchPort)
    return transport


def test_r1_reconfigure_mints_a_fresh_link_and_returns_the_applied_settings() -> None:
    """R1 (apply): the applied settings come back (the read-back is the
    caller's proof), a NEW link serves the new conversation, the OLD link's
    reader is dead, the opener saw the boot open then the reopen at
    ``{**boot, "baud": N}``, and the new ring starts empty. The fresh link
    serves a real §8.1 receive — the swap is not a facade."""
    opener = _Opener()
    services = _services(opener)
    old_link = services.link

    applied = asyncio.run(services.reconfigure_link({"baud": _TARGET}, _ctx()))

    # boot settings never change: the reopen settings are literally
    # {**boot_settings, "baud": N} — the full declared boot dict (the
    # x- key included, exactly what the opener received at boot), only
    # the baud replaced.
    assert applied == {**_DECLARED, "baud": _TARGET}
    assert applied["baud"] == _TARGET
    assert applied["parity"] == "none" and applied["rtscts"] is False
    assert services.link is not old_link, "a line reset starts a new link"
    assert not old_link.reader_alive(), "the old reader joined through close()"
    assert services.link.reader_alive()
    assert old_link.ring_length() == 0
    assert services.link.ring_length() == 0
    assert [s for _, s in opener.opens] == [_DECLARED, {**_DECLARED, "baud": _TARGET}]

    _current_port(services).deliver(b"OK\n")
    got = asyncio.run(
        services.transfer(
            {"kind": "stream_receive", "max_bytes": 64, "termination": "lf",
             "exact_bytes": None},
            _ctx(),
        )
    )
    assert got == {"data": b"OK\n"}


def test_r2_a_parked_receive_refuses_the_reconfigure_and_then_completes() -> None:
    """R2 (mid-receive): a receive parked in a worker makes the switch
    refuse with the typed busy prefix; the parked receive still completes
    correctly afterwards — the refusal protects the conversation, it does
    not abort it."""
    opener = _Opener()
    services = _services(opener)
    done = threading.Event()
    result: list[bytes] = []

    def _parked_receive() -> None:
        try:
            result.append(
                services.link.take(
                    max_bytes=64,
                    terminator=b"\n",
                    exact=0,
                    deadline=time.monotonic() + _DEADLINE_S,
                )
            )
        finally:
            done.set()

    worker = threading.Thread(target=_parked_receive, daemon=True)
    worker.start()
    # The counter is the guard's own fact source: when it reads 1, the
    # parked take has entered — deterministic drain, no sleeps.
    limit = time.monotonic() + _DEADLINE_S
    while services.link.receive_depth < 1:
        assert time.monotonic() < limit, "the parked receive never entered"
        time.sleep(0.001)

    with pytest.raises(ValueError, match="standalone_serial_reconfigure_busy"):
        asyncio.run(services.reconfigure_link({"baud": _TARGET}, _ctx()))

    _current_port(services).deliver(b"ACK\n")
    assert done.wait(_DEADLINE_S), "the parked receive never completed"
    worker.join(_DEADLINE_S)
    assert result == [b"ACK\n"], "the parked receive must complete, not die"


def test_r3_a_baud_outside_the_declared_set_refuses_naming_the_set() -> None:
    """R3 (guard rail): a baud outside the declared set refuses with the
    typed prefix and the refusal names the allowed set; the
    no-declaration case fails closed — the allowed set is {boot} and every
    switch refuses."""
    opener = _Opener()
    services = _services(opener)
    with pytest.raises(ValueError) as excinfo:
        asyncio.run(services.reconfigure_link({"baud": 9600}, _ctx()))
    message = str(excinfo.value)
    assert "standalone_serial_baud_not_negotiable" in message
    assert "9600" in message
    assert "115200" in message and "3000000" in message, (
        "the refusal names the allowed set"
    )
    assert len(opener.opens) == 1, "a guard refusal performs no I/O"

    plain = _services(_Opener(), settings=_BOOT)
    with pytest.raises(ValueError, match="standalone_serial_baud_not_negotiable"):
        asyncio.run(plain.reconfigure_link({"baud": _TARGET}, _ctx()))
    assert plain.link_state() == {
        "baud": 115200,
        "boot_baud": 115200,
        "negotiable": False,
    }


def test_r4_the_field_set_is_closed_and_baud_must_be_an_int() -> None:
    """R4 (grammar): extra fields refuse, an empty request refuses, and a
    bool or string baud (a bool is an int to Python) refuses — boot
    settings (parity, stop bits, rtscts) can never ride a switch request."""
    opener = _Opener()
    services = _services(opener)
    for bad in (
        {"baud": _TARGET, "parity": "even"},
        {},
        {"baud": True},
        {"baud": "3000000"},
    ):
        with pytest.raises(ValueError, match="standalone_serial_reconfigure_fields"):
            asyncio.run(services.reconfigure_link(bad, _ctx()))
    assert len(opener.opens) == 1, "a grammar refusal performs no I/O"


def test_r5_an_expired_or_cancelled_context_refuses_before_any_io() -> None:
    """R5 (bounded): a cancelled or expired context refuses before any
    I/O — the opener count never moves (the C06/C07 posture)."""
    opener = _Opener()
    services = _services(opener)
    expired = _ctx()
    expired.deadline_monotonic = time.monotonic() - 1.0
    with pytest.raises(TimeoutError):
        asyncio.run(services.reconfigure_link({"baud": _TARGET}, expired))
    cancelled = _ctx()
    cancelled.cancel()
    with pytest.raises(TimeoutError):
        asyncio.run(services.reconfigure_link({"baud": _TARGET}, cancelled))
    assert len(opener.opens) == 1, "liveness refuses before the reopen"


def test_r6_a_failed_reconfigure_leaves_no_link_and_never_retries() -> None:
    """R6 (failure posture): an opener error raises ConnectionError, the
    services then have no serving link (the closed old one is never
    rebound — a faulted link never serves a second conversation),
    close_transport stays safe, and the host never retried on its own: a
    second reconfigure is the CALLER's explicit fallback move, and it
    restores a serving link."""
    opener = _Opener()
    services = _services(opener)
    old_link = services.link
    services._reconfigurator = LinkReconfigurator(
        opener=_broken_opener(opener),
        device_path="/dev/fake0",
        boot_settings=dict(_DECLARED),
        allowed_bauds=negotiable_bauds(_DECLARED),
        on_link_event=None,
    )
    with pytest.raises(ConnectionError):
        asyncio.run(services.reconfigure_link({"baud": _TARGET}, _ctx()))
    assert len(opener.opens) == 2, "one attempt, no host retry"
    assert services.link is old_link, "the closed old link never rebinds"
    assert not old_link.reader_alive()
    with pytest.raises(ConnectionError):
        asyncio.run(
            services.transfer(
                {"kind": "stream_receive", "max_bytes": 8, "termination": "lf",
                 "exact_bytes": None},
                _ctx(),
            )
        )
    asyncio.run(services.close_transport(_ctx()))  # safe on the no-link posture

    services._reconfigurator = LinkReconfigurator(
        opener=opener,
        device_path="/dev/fake0",
        boot_settings=dict(_DECLARED),
        allowed_bauds=negotiable_bauds(_DECLARED),
        on_link_event=None,
    )
    applied = asyncio.run(services.reconfigure_link({"baud": 115200}, _ctx()))
    assert applied == {**_DECLARED, "baud": 115200}
    assert services.link.reader_alive(), "the explicit fallback restores a link"


def test_r7_link_events_carry_the_closed_shape_and_vocabulary() -> None:
    """R7 (events): applied, refused and failed rows ride the callback with
    the closed data shape (``event``/``from_baud``/``to_baud``/
    ``operation_id``, optional ``reason``) and the closed ``event``
    vocabulary — the bus carries the LINK state machine only."""
    opener = _Opener()
    events: list[dict[str, Any]] = []
    services = _services(opener, events=events)

    with pytest.raises(ValueError):
        asyncio.run(services.reconfigure_link({"baud": 9600}, _ctx()))  # refused
    applied = asyncio.run(services.reconfigure_link({"baud": _TARGET}, _ctx()))
    assert applied == {**_DECLARED, "baud": _TARGET}

    services._reconfigurator = LinkReconfigurator(
        opener=_broken_opener(opener),
        device_path="/dev/fake0",
        boot_settings=dict(_DECLARED),
        allowed_bauds=negotiable_bauds(_DECLARED),
        on_link_event=events.append,
    )
    with pytest.raises(ConnectionError):
        asyncio.run(services.reconfigure_link({"baud": 115200}, _ctx()))  # failed

    assert [row["event"] for row in events] == [
        "reconfigure_refused",
        "reconfigured",
        "reconfigure_failed",
    ]
    vocabulary = {"reconfigured", "reconfigure_refused", "reconfigure_failed"}
    for row in events:
        assert row["event"] in vocabulary
        assert set(row) <= {"event", "from_baud", "to_baud", "reason", "operation_id"}
        assert {"event", "from_baud", "to_baud", "operation_id"} <= set(row)
        assert isinstance(row["from_baud"], int)
        assert not isinstance(row["from_baud"], bool)
        assert isinstance(row["to_baud"], int)
        assert not isinstance(row["to_baud"], bool)
        assert row["operation_id"]
    refused, applied_row, failed = events
    assert refused["from_baud"] == 115200 and refused["to_baud"] == 9600
    assert applied_row["from_baud"] == 115200 and applied_row["to_baud"] == _TARGET
    assert failed["from_baud"] == _TARGET and failed["to_baud"] == 115200


def test_r7b_a_busy_refusal_publishes_the_refused_row_with_reason() -> None:
    """R7 (refused with reason): the busy refusal's row names the reason —
    a watcher sees why the switch did not happen."""
    opener = _Opener()
    events: list[dict[str, Any]] = []
    services = _services(opener, events=events)
    result: list[bytes] = []
    done = threading.Event()

    def _parked_receive() -> None:
        try:
            result.append(
                services.link.take(
                    max_bytes=64, terminator=b"\n", exact=0,
                    deadline=time.monotonic() + _DEADLINE_S,
                )
            )
        finally:
            done.set()

    worker = threading.Thread(target=_parked_receive, daemon=True)
    worker.start()
    limit = time.monotonic() + _DEADLINE_S
    while services.link.receive_depth < 1:
        assert time.monotonic() < limit
        time.sleep(0.001)
    with pytest.raises(ValueError, match="standalone_serial_reconfigure_busy"):
        asyncio.run(services.reconfigure_link({"baud": _TARGET}, _ctx()))
    _current_port(services).deliver(b"ACK\n")
    assert done.wait(_DEADLINE_S)
    worker.join(_DEADLINE_S)

    rows = [row for row in events if row["event"] == "reconfigure_refused"]
    assert len(rows) == 1
    assert rows[0]["reason"] == "a receive is in flight"


def test_negotiable_bauds_validation_is_loud_and_fail_closed() -> None:
    """The derivation itself (FOLD-F posture): a malformed declaration
    refuses loudly naming the key; an absent declaration yields the
    fail-closed {boot}-only set."""
    with pytest.raises(ValueError, match="standalone_serial_negotiated_bauds"):
        negotiable_bauds({**_BOOT, "x-negotiated-bauds": []})
    with pytest.raises(ValueError, match="standalone_serial_negotiated_bauds"):
        negotiable_bauds({**_BOOT, "x-negotiated-bauds": [0]})
    with pytest.raises(ValueError, match="standalone_serial_negotiated_bauds"):
        negotiable_bauds({**_BOOT, "x-negotiated-bauds": [True]})
    with pytest.raises(ValueError, match="standalone_serial_negotiated_bauds"):
        negotiable_bauds({**_BOOT, "x-negotiated-bauds": ["3000000"]})
    with pytest.raises(ValueError, match="standalone_serial_negotiated_bauds"):
        negotiable_bauds({**_BOOT, "x-negotiated-bauds": "nope"})
    assert negotiable_bauds(_BOOT) == frozenset({115200})
    assert negotiable_bauds(_DECLARED) == frozenset({115200, 3_000_000})
