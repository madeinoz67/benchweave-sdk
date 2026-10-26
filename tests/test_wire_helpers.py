# author: Stephen Eaton
"""Issue #566 rows 8-10: the scaffold's wire-discipline helpers.

The helpers ship INSIDE every scaffolded plugin package
(``src/<package>/wire.py``, rendered from the copier template) because the
generated plugin runtime has no dependency on this SDK (invariants SRF-1).
These tests render the scaffold and import the rendered module directly, so
the contract is proven on the bytes a plugin actually receives — the same
posture as the R-2 fixture parity arms.

Row 8 generalizes the plugin's inline ``_advance_counter`` (commit a6fd5da,
branch feat/562-wire-truth): one opaque counter across reads and writes, a
gap refused with the evidence attached. The generalization drops every
device assumption — no 3-byte ACK, no frame shape, only the counter value
the caller supplies — and adds the wrap modulus the inline version lacked
(a byte counter that rolls 0xFF->0x00 was a false gap there).

Row 9 generalizes the inline paced poll (commit cacb563): the helper IS the
loop, so the declared interval cannot go unread — the unwired-constant
defect that caused systematic false timeouts on hardware is unrepresentable
in a loop built on it.

Row 10 generalizes the DONE-pin gate (commit 30e9dd7): the completion
signal refusal exists as a named exception the adapter maps to a device
failure, never ok.
"""

from __future__ import annotations

import asyncio
import importlib.util
import math
from pathlib import Path
from types import ModuleType

import pytest

from benchweave_sdk.scaffold import create_project


def _rendered_wire(tmp_path: Path) -> ModuleType:
    """Import ``wire.py`` from a freshly rendered scaffold project."""
    project = tmp_path / "example_plugin"
    create_project(project, "example_plugin")
    path = project / "src" / "example_plugin" / "wire.py"
    spec = importlib.util.spec_from_file_location("rendered_wire", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- row 8: the sequencing integrity tracker ---------------------------------


def test_counter_continuity_passes(tmp_path: Path) -> None:
    wire = _rendered_wire(tmp_path)
    tracker = wire.CommandCounter()
    asyncio.run(tracker.advance(0x10))
    asyncio.run(tracker.advance(0x11))


def test_counter_first_observation_establishes_the_baseline(tmp_path: Path) -> None:
    """The first exchange sets the baseline: a resync/reconnect sequence can
    begin at any counter value without a false gap."""
    wire = _rendered_wire(tmp_path)
    tracker = wire.CommandCounter()
    asyncio.run(tracker.advance(0xE7))


def test_counter_gap_refusal_names_expected_observed_and_exchange(
    tmp_path: Path,
) -> None:
    wire = _rendered_wire(tmp_path)
    tracker = wire.CommandCounter()
    asyncio.run(tracker.advance(0x10))
    with pytest.raises(wire.CounterGapError) as caught:
        asyncio.run(tracker.advance(0x13))
    message = str(caught.value)
    assert "expected 0x11" in message
    assert "observed 0x13" in message
    assert "exchange 1" in message


def test_counter_gap_is_a_value_error(tmp_path: Path) -> None:
    """The adapter's existing ``except (ValueError, ...)`` maps the gap to
    PROTOCOL_ERROR without new plumbing — the inline version's mapping."""
    wire = _rendered_wire(tmp_path)
    assert issubclass(wire.CounterGapError, ValueError)


def test_counter_byte_wrap_passes_with_modulus(tmp_path: Path) -> None:
    """The inline plugin version's latent defect, fixed generally: a counter
    BYTE rolls 0xFF->0x00, which without a modulus was a false gap."""
    wire = _rendered_wire(tmp_path)
    tracker = wire.CommandCounter(modulus=256)
    asyncio.run(tracker.advance(0xFE))
    asyncio.run(tracker.advance(0xFF))
    asyncio.run(tracker.advance(0x00))
    asyncio.run(tracker.advance(0x01))


def test_counter_byte_wrap_without_modulus_refuses(tmp_path: Path) -> None:
    """Without a declared modulus the tracker is device-agnostic and strict:
    0xFF->0x00 IS a gap unless the caller said the counter wraps."""
    wire = _rendered_wire(tmp_path)
    tracker = wire.CommandCounter()
    asyncio.run(tracker.advance(0xFF))
    with pytest.raises(wire.CounterGapError):
        asyncio.run(tracker.advance(0x00))


def test_counter_gap_records_evidence_before_the_refusal(tmp_path: Path) -> None:
    """Row 8's 'with the evidence attached': the record hook receives one
    evidence dict (expected, observed, exchange) and is awaited BEFORE the
    refusal raises — the inline version's record-then-raise order."""
    wire = _rendered_wire(tmp_path)
    tracker = wire.CommandCounter()
    recorded: list[dict] = []

    async def record(entry: dict) -> None:
        recorded.append(entry)

    asyncio.run(tracker.advance(0x40))
    with pytest.raises(wire.CounterGapError):
        asyncio.run(tracker.advance(0x42))
    assert recorded == []  # no hook was wired on that first tracker
    tracker2 = wire.CommandCounter()
    asyncio.run(tracker2.advance(0x40, record=record))
    with pytest.raises(wire.CounterGapError):
        asyncio.run(tracker2.advance(0x44, record=record))
    assert recorded == [
        {
            "kind": "command_counter_gap",
            "exchange": 1,
            "expected": 0x41,
            "observed": 0x44,
        }
    ]


def test_evidence_kinds_are_a_closed_set(tmp_path: Path) -> None:
    """Row 15: the scaffold's evidence-kind names are exported constants,
    not inlined strings. A misspelled name fails at import (a NameError in
    referencing code, an AttributeError through getattr) rather than
    becoming a wrong string only a reviewer can catch."""
    wire = _rendered_wire(tmp_path)
    assert wire.EVIDENCE_COMMAND_COUNTER_GAP == "command_counter_gap"
    with pytest.raises(NameError):
        exec("EVIDENCE_COMMAND_COUNTER_GPA", vars(wire))  # misspelled


def test_counter_gap_evidence_carries_the_constant(tmp_path: Path) -> None:
    """The helper emits its kind through the constant — identity, not a
    duplicated literal — so renaming the constant moves the wire value."""
    wire = _rendered_wire(tmp_path)
    tracker = wire.CommandCounter()
    recorded: list[dict] = []

    async def record(entry: dict) -> None:
        recorded.append(entry)

    asyncio.run(tracker.advance(0x40, record=record))
    with pytest.raises(wire.CounterGapError):
        asyncio.run(tracker.advance(0x42, record=record))
    assert recorded[0]["kind"] is wire.EVIDENCE_COMMAND_COUNTER_GAP


def test_counter_refuses_non_int_and_out_of_range_counters(tmp_path: Path) -> None:
    wire = _rendered_wire(tmp_path)
    tracker = wire.CommandCounter(modulus=256)
    with pytest.raises(TypeError):
        asyncio.run(tracker.advance("5"))
    with pytest.raises(ValueError):
        asyncio.run(tracker.advance(256))


def test_counter_refuses_bad_modulus(tmp_path: Path) -> None:
    wire = _rendered_wire(tmp_path)
    with pytest.raises(ValueError):
        wire.CommandCounter(modulus=1)


# --- row 9: the paced poll -----------------------------------------------------


class FakeClock:
    """A monotonic clock the waits advance — real transfers cost time."""

    def __init__(self) -> None:
        self.now = 100.0

    def monotonic(self) -> float:
        return self.now


def _pacer(wire: ModuleType, clock: FakeClock, *, deadline: float = 200.0):
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        clock.now += seconds

    def poll(
        attempts: int,
        interval_s: float,
        *,
        results: list[object],
        cancelled=None,
    ):
        served = list(results)

        async def read():
            return served.pop(0)

        return wire.paced_poll(
            attempts,
            interval_s,
            read=read,
            ready=lambda outcome: bool(outcome),
            monotonic=clock.monotonic,
            deadline=deadline,
            cancelled=cancelled,
            sleep=sleep,
        )

    return poll, waits


def test_paced_poll_waits_the_declared_interval_between_attempts(
    tmp_path: Path,
) -> None:
    """Two not-ready attempts then ready: exactly two waits of the declared
    interval — the device cadence IS the budget (row 9)."""
    wire = _rendered_wire(tmp_path)
    clock = FakeClock()
    poll, waits = _pacer(wire, clock)
    outcome = asyncio.run(poll(3, 0.1, results=[None, None, "ready"]))
    assert outcome == "ready"
    assert waits == [0.1, 0.1]
    assert math.isclose(clock.now, 100.2)


def test_paced_poll_reads_before_any_wait(tmp_path: Path) -> None:
    wire = _rendered_wire(tmp_path)
    clock = FakeClock()
    poll, waits = _pacer(wire, clock)
    outcome = asyncio.run(poll(3, 0.1, results=["ready"]))
    assert outcome == "ready"
    assert waits == []


def test_paced_poll_deadline_expiry_raises_timeout(tmp_path: Path) -> None:
    wire = _rendered_wire(tmp_path)
    clock = FakeClock()
    poll, waits = _pacer(wire, clock, deadline=100.15)
    with pytest.raises(TimeoutError):
        asyncio.run(poll(5, 0.1, results=[None, None, None, None, None]))
    assert waits == [0.1, 0.1]


def test_paced_poll_exhaustion_names_the_attempts(tmp_path: Path) -> None:
    """Attempt-bounded as well as deadline-bounded: a host whose clock never
    advances must still terminate (the plugin's mock-clock constraint)."""
    wire = _rendered_wire(tmp_path)
    clock = FakeClock()
    poll, waits = _pacer(wire, clock, deadline=math.inf)
    with pytest.raises(TimeoutError, match="4 attempt"):
        asyncio.run(poll(4, 0.1, results=[None, None, None, None]))
    assert waits == [0.1, 0.1, 0.1]


def test_paced_poll_cancellation_raises_timeout(tmp_path: Path) -> None:
    wire = _rendered_wire(tmp_path)
    clock = FakeClock()
    poll, _ = _pacer(wire, clock)

    def cancelled() -> bool:
        return clock.now > 100.0

    with pytest.raises(TimeoutError):
        asyncio.run(poll(5, 0.1, results=[None] * 5, cancelled=cancelled))


def test_paced_poll_refuses_bad_shape(tmp_path: Path) -> None:
    wire = _rendered_wire(tmp_path)
    clock = FakeClock()
    poll, _ = _pacer(wire, clock)
    with pytest.raises(ValueError):
        asyncio.run(poll(0, 0.1, results=[]))
    with pytest.raises(ValueError):
        asyncio.run(poll(3, 0, results=[None] * 3))


# --- row 10: completion pins gate success --------------------------------------


def test_completion_passes_when_the_signal_is_asserted(tmp_path: Path) -> None:
    wire = _rendered_wire(tmp_path)
    assert wire.require_completion(True, signal="FPGA DONE pin") is None


def test_completion_refusal_names_the_signal_and_exchange(tmp_path: Path) -> None:
    wire = _rendered_wire(tmp_path)
    with pytest.raises(wire.CompletionUnassertedError) as caught:
        wire.require_completion(False, signal="FPGA DONE pin", exchange=7)
    message = str(caught.value)
    assert "FPGA DONE pin" in message
    assert "exchange 7" in message


def test_completion_refusal_is_a_runtime_error(tmp_path: Path) -> None:
    """Not a ValueError: a silent completion is a device-verdict failure the
    adapter maps to its own failure code (the plugin used DEVICE_REJECTED
    with an uncertain outcome), distinct from a malformed response."""
    wire = _rendered_wire(tmp_path)
    assert issubclass(wire.CompletionUnassertedError, RuntimeError)
