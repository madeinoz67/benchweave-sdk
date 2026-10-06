# author: Stephen Eaton
"""Refute-lane fold cells for the #407 reconfigure capability.

One cell per refute finding (F1-F3 + the four LOWs), RED first: each
pins the corrected behavior against the branch that shipped the defect.
Sharing the R-file's doubles is deliberate — the folds run against the
same harness the R-cells use, so a fold that passes while an R-cell
fails is impossible by construction.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from test_serial_reconfigure import (
    _DECLARED,
    _TARGET,
    _SwitchPort,
)

from benchweave_sdk_server.serial import (
    LinkReconfigurator,
    SerialCaptureServices,
    SerialLink,
    negotiable_bauds,
)
from benchweave_sdk_server.session import HostOperationContext, load_plugin_project


def _baudless_plugin(project: Path) -> Any:
    """The scaffolded plugin with ``baud`` POPPED from transport.settings
    (legal — open_serial_port defaults it; it worked at base)."""
    import copy
    import dataclasses

    plugin = load_plugin_project(project)
    descriptor = copy.deepcopy(plugin.descriptor)
    descriptor["transport"]["settings"].pop("baud", None)
    return dataclasses.replace(plugin, descriptor=descriptor)


def _baudless_seam(project: Path) -> Any:
    loaded = _baudless_plugin(project)
    opens: list[dict[str, Any]] = []

    def opener(device: str, settings: dict[str, Any]) -> Any:
        opens.append(dict(settings))
        port = _SwitchPort(settings)
        port.deliver(b"SDK Example,demo,SIM001,1.0.0\n")  # the identify answer
        return port

    session = __import__(
        "benchweave_sdk_server.serial", fromlist=["serial_plugin_session"]
    ).serial_plugin_session(loaded, "/dev/fake0", open_port=opener)
    seam = __import__(
        "benchweave_sdk_server.seam", fromlist=["StandaloneSeam"]
    ).StandaloneSeam(session, transport_kind="serial")
    return seam, opens


def test_f1_a_baudless_descriptor_answers_typed_on_every_surface(
    starter_project,
) -> None:
    """F1: a descriptor whose transport.settings omits ``baud`` is legal
    (the opener defaults it) and worked at base — the derived code must
    read baud the way the writer does: defaulted, never indexed."""
    seam, opens = _baudless_seam(starter_project)

    async def scenario() -> tuple[dict[str, Any], dict[str, Any], Any]:
        await seam.session.connect()
        # the block rides from the CONNECTED session's services — the
        # KeyError class lives exactly there (services exist, the derived
        # reads indexed a missing key)
        info = await seam.call("host_info")
        device = await seam.call(
            "device_get", {"device_id": seam.session.device_id}
        )
        context = HostOperationContext("cell-f1", timeout_ms=5000)
        with pytest.raises(ValueError, match="standalone_serial_baud_not_negotiable"):
            await seam.session.services.reconfigure_link({"baud": _TARGET}, context)
        return info, device, None

    info, device, _ = asyncio.run(scenario())
    assert info["link"] == {
        "baud": 115200,
        "boot_baud": 115200,
        "negotiable": False,
    }, "host_info answers the defaulted boot state, not a KeyError"
    assert device["link"]["baud"] == 115200
    assert opens and all(
        "baud" in settings for settings in opens
    ), "every open still carries the defaulted baud"


def test_f2a_concurrent_reconfigures_never_orphan_a_transport() -> None:
    """F2 (orphan class): two concurrent reconfigures must serialize; the
    loser of the swap closes the winner's link through the normal
    ``old.close()`` path, so every opened transport eventually sees
    exactly one close — no reader thread left alive, no transport open
    forever. Pre-fix both twins pass the guards and rebind out of order:
    the first link is orphaned with its transport never closed."""
    opened_ports: list[_SwitchPort] = []

    def opener(device: str, settings: dict[str, Any]) -> _SwitchPort:
        port = _SwitchPort(settings)
        opened_ports.append(port)
        # the planted delay keeps both to_thread futures genuinely
        # pending at the twins' awaits — without it the futures resolve
        # before each twin suspends, gather runs them sequentially, the
        # lock is never contended, and a no-op-lock mutant passes the
        # whole suite (wave-3 R2)
        time.sleep(0.05)
        return port

    services = _services_from_opener(opener)

    async def scenario() -> None:
        context = HostOperationContext("cell-f2a", timeout_ms=5000)
        await asyncio.gather(
            services.reconfigure_link({"baud": _TARGET}, context),
            services.reconfigure_link({"baud": _TARGET}, context),
        )
        assert services.link.reader_alive(), "the current link serves"
        await services.close_transport(context)

    asyncio.run(scenario())
    closes = [port.closes for port in opened_ports]
    assert all(count == 1 for count in closes), (
        f"every opened transport closes exactly once (orphan class): {closes}"
    )




def test_f2b_a_connection_error_answer_means_no_serving_link() -> None:
    """F2 (consistency class): the failing twin's ConnectionError answer
    must mean what the module documents — NO serving link. Serialized,
    the loser's swap closes the winner's link before its own opener
    fails, so the answer and the link state agree. (The RED evidence for
    the pre-fix interleaving class is in the fold RED runs: the unordered
    twins both passed the guards and rebound out of order — the traced
    run showed one twin closing the other's fresh link, and the
    event-hooked cut of this cell showed a healthy link serving after a
    ConnectionError answer.)"""
    attempts: list[int] = []

    def flaky_opener(device: str, settings: dict[str, Any]) -> _SwitchPort:
        attempts.append(int(settings["baud"]))
        if len(attempts) > 2:  # boot + first twin succeed; the second raises
            raise OSError("device vanished on the second reopen")
        time.sleep(0.05)  # wave-3 R2: keep both futures pending at their awaits
        return _SwitchPort(settings)

    services = _services_from_opener(flaky_opener)

    async def scenario() -> list[BaseException]:
        context = HostOperationContext("cell-f2b", timeout_ms=10000)
        return list(
            await asyncio.gather(
                services.reconfigure_link({"baud": _TARGET}, context),
                services.reconfigure_link({"baud": _TARGET}, context),
                return_exceptions=True,
            )
        )

    outcomes = asyncio.run(scenario())
    failures = [row for row in outcomes if isinstance(row, BaseException)]
    successes = [row for row in outcomes if not isinstance(row, BaseException)]
    assert len(successes) == 1 and len(failures) == 1, (
        f"serialized twins: one success, one failure — got {outcomes}"
    )
    assert isinstance(failures[0], ConnectionError)
    with pytest.raises(ConnectionError):
        asyncio.run(
            services.transfer(
                {"kind": "stream_receive", "max_bytes": 8, "termination": "lf",
                 "exact_bytes": None},
                HostOperationContext("cell-f2b-check", timeout_ms=5000),
            )
        ), "ConnectionError means NO serving link — the healthy-link lie is gone"


def test_f3a_an_over_deadline_opener_is_a_timeout_not_a_success() -> None:
    """F3a: the deadline is re-checked AFTER the opener — a planted 0.3 s
    reopen under a 0.15 s deadline answers TimeoutError, publishes the
    failed row (never a success row), and the opened transport closes
    (no leak, closes counter asserted). Pre-fix this returned success
    with a ``reconfigured`` event and left the port open."""
    opened_ports: list[_SwitchPort] = []

    def slow_opener(device: str, settings: dict[str, Any]) -> _SwitchPort:
        port = _SwitchPort(settings)
        opened_ports.append(port)
        time.sleep(0.3)
        return port

    events: list[dict[str, Any]] = []
    services = _services_from_opener(slow_opener, events=events)
    context = HostOperationContext("cell-f3a", timeout_ms=150)
    with pytest.raises(TimeoutError):
        asyncio.run(services.reconfigure_link({"baud": _TARGET}, context))
    assert [row["event"] for row in events] == ["reconfigure_failed"], (
        "a past-deadline reopen is a failed row, never a success row"
    )
    assert opened_ports[0].closes == 1, "the opened transport closes — no leak"


def test_f3b_a_cancelled_opener_publishes_the_failed_row() -> None:
    """F3b: cancellation is a BaseException — it must not escape the
    opener's handler silently. An opener that raises CancelledError (the
    shape a cancelled operation surfaces through a port layer)
    propagates AND the ``reconfigure_failed`` row publishes."""
    events: list[dict[str, Any]] = []

    opens: list[int] = []

    def cancelling_opener(device: str, settings: dict[str, Any]) -> _SwitchPort:
        opens.append(1)
        if len(opens) > 1:  # the boot open behaves; the REOPEN cancels
            raise asyncio.CancelledError()
        return _SwitchPort(settings)

    services = _services_from_opener(cancelling_opener, events=events)
    context = HostOperationContext("cell-f3b", timeout_ms=5000)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(services.reconfigure_link({"baud": _TARGET}, context))
    assert [row["event"] for row in events] == ["reconfigure_failed"], (
        "cancellation publishes the failed row before propagating"
    )


def test_low1_link_state_after_a_failed_reconfigure_serves_null() -> None:
    """LOW1: after a failed swap the services hold NO link — the block
    serves null (A06), never a live-looking baud."""
    events: list[dict[str, Any]] = []

    opens: list[int] = []

    def failing(device: str, settings: dict[str, Any]) -> _SwitchPort:
        opens.append(1)
        if len(opens) > 1:  # the boot open behaves; the reopen fails
            raise OSError("gone")
        return _SwitchPort(settings)

    services = _services_from_opener(failing, events=events)
    before = services.link_state()
    assert before is not None, "sanity: the boot link reports"
    with pytest.raises(ConnectionError):
        asyncio.run(services.reconfigure_link({"baud": _TARGET}, _fold_ctx()))
    assert services.link_state() is None, (
        "no serving link, no live-looking block"
    )


def _services_from_opener(
    opener: Any, *, events: list[dict[str, Any]] | None = None
) -> SerialCaptureServices:
    """The R-file construction with a caller-supplied opener."""
    link = SerialLink(opener("/dev/fake0", _DECLARED))
    return SerialCaptureServices(
        link,
        max_frame_bytes=4096,
        reconfigurator=LinkReconfigurator(
            opener=opener,
            device_path="/dev/fake0",
            boot_settings=dict(_DECLARED),
            allowed_bauds=negotiable_bauds(_DECLARED),
            on_link_event=(events.append if events is not None else None),
        ),
    )


def _fold_ctx() -> HostOperationContext:
    return HostOperationContext("cell-fold", timeout_ms=5000)


def test_low2_device_get_preserves_an_adapter_reported_link_key(
    starter_project,
) -> None:
    """LOW2: the overlay must not clobber an adapter-reported
    ``identity["link"]`` — adapter keys survive (the design's F3 wording
    is false for exactly this key; the addendum notes it)."""
    seam, _opener = _baudless_seam(starter_project)

    async def scenario() -> dict[str, Any]:
        await seam.session.connect()
        seam.session.identity = {
            **(seam.session.identity or {}),
            "link": {"adapter": "reported"},
        }
        return await seam.call("device_get", {"device_id": seam.session.device_id})

    result = asyncio.run(scenario())
    assert result["link"] == {"adapter": "reported"}, (
        "an adapter-reported link key survives the overlay"
    )


def test_low3_negotiable_bauds_refuses_a_non_mapping_settings() -> None:
    """LOW3: ``negotiable_bauds(None)`` refuses typed, never an
    AttributeError."""
    with pytest.raises(ValueError, match="standalone_serial_negotiated_bauds"):
        negotiable_bauds(None)


def test_low4_a_bool_boot_baud_refuses_typed() -> None:
    """LOW4: the boot baud validates like the declared list — a bool (a
    bool is an int to Python: True would admit the set {1}) refuses
    typed."""
    with pytest.raises(ValueError, match="standalone_serial_boot_baud"):
        negotiable_bauds({"baud": True})
    with pytest.raises(ValueError, match="standalone_serial_boot_baud"):
        negotiable_bauds({"baud": 0})
    with pytest.raises(ValueError, match="standalone_serial_boot_baud"):
        negotiable_bauds({"baud": "115200"})
    with pytest.raises(ValueError, match="standalone_serial_boot_baud"):
        negotiable_bauds({"baud": -1})
    assert negotiable_bauds({}) == frozenset({115200})


class _SlowClosePort(_SwitchPort):
    """A port whose close takes a planted 0.3 s (the host sits inside
    ``old.close()`` while its deadline expires)."""

    def close(self) -> None:
        time.sleep(0.3)
        super().close()


def test_w2_the_post_close_recheck_refuses_before_any_io() -> None:
    """Wave-2 F2 (arm 2): the deadline is re-checked AFTER the close —
    a context that expires while the host sits inside a planted-slow
    ``old.close()`` answers TimeoutError with the failed row, and the
    opener NEVER runs (the refusal precedes any I/O). This is the only
    pin on the post-close recheck: wave-2's probe showed a mutant
    removing it passed the whole R-suite and N-suite green."""
    opens: list[int] = []

    def opener(device: str, settings: dict[str, Any]) -> _SlowClosePort:
        opens.append(1)
        return _SlowClosePort(settings)

    events: list[dict[str, Any]] = []
    services = _services_from_opener(opener, events=events)
    context = HostOperationContext("cell-w2-postclose", timeout_ms=150)
    with pytest.raises(TimeoutError):
        asyncio.run(services.reconfigure_link({"baud": _TARGET}, context))
    assert [row["event"] for row in events] == ["reconfigure_failed"], (
        "the expiry during the close is a failed row, never a success row"
    )
    assert "close" in events[0]["reason"]
    assert len(opens) == 1, (
        "the post-close recheck refuses BEFORE the reopen — no opener call"
    )
    assert services.link_state() is None, "no serving link (LOW1's law)"


def test_w3_close_during_a_swap_never_orphans_the_produced_transport() -> None:
    """Wave-3 R1: close_transport racing an in-flight swap must not let
    the swap rebind a live link onto a closed session — the produced
    transport closes, the failed row publishes (never a reconfigured row
    after close), and the member answers typed. Pre-fix the swap
    rebound a live link after close, published ``reconfigured``, and
    nothing ever closed the new link (session.close drops the services
    reference first -- fd + daemon reader leak forever)."""
    swap_started = threading.Event()
    release = threading.Event()

    opens: list[int] = []
    produced: list[_SwitchPort] = []

    def gated(device: str, settings: dict[str, Any]) -> _SwitchPort:
        opens.append(1)
        if len(opens) == 1:  # the boot open behaves and signals nothing
            return _SwitchPort(settings)
        port = _SwitchPort(settings)
        produced.append(port)
        swap_started.set()  # only the SWAP'S open signals
        release.wait(5.0)
        return port

    events: list[dict[str, Any]] = []
    link = SerialLink(gated("/dev/fake0", _DECLARED))
    services = SerialCaptureServices(
        link,
        max_frame_bytes=4096,
        reconfigurator=LinkReconfigurator(
            opener=gated,
            device_path="/dev/fake0",
            boot_settings=dict(_DECLARED),
            allowed_bauds=negotiable_bauds(_DECLARED),
            on_link_event=events.append,
        ),
    )
    boot_port = link._transport  # noqa: SLF001 - test seam

    async def scenario() -> None:
        context = HostOperationContext("cell-w3-r1", timeout_ms=10000)
        task = asyncio.create_task(
            services.reconfigure_link({"baud": _TARGET}, context)
        )
        limit = time.monotonic() + 5.0
        while not swap_started.is_set():
            assert time.monotonic() < limit, "the reopen never started"
            await asyncio.sleep(0.001)
        await services.close_transport(
            HostOperationContext("cell-w3-close", timeout_ms=5000)
        )
        release.set()
        with pytest.raises(
            ConnectionError, match="standalone_serial_reconfigure_closed"
        ):
            await task

    asyncio.run(scenario())
    assert [row["event"] for row in events] == ["reconfigure_failed"], (
        "a close during the swap is a failed row -- never "
        "reconfigured-after-close"
    )
    assert "closed" in events[0]["reason"]
    assert boot_port.closes == 1
    assert produced and produced[0].closes == 1, (
        "the produced transport closes -- no orphan"
    )
    assert services.link_state() is None
    with pytest.raises(ConnectionError):
        asyncio.run(
            services.transfer(
                {"kind": "stream_receive", "max_bytes": 8, "termination": "lf",
                 "exact_bytes": None},
                HostOperationContext("cell-w3-r1-check", timeout_ms=5000),
            )
        )


def test_w3_reconfigure_after_close_refuses_typed() -> None:
    """Wave-3 R3: a reconfigure on a closed session refuses typed — a
    stale services reference must not mint a live link and a live-looking
    link_state block (which bypassed LOW1's null posture). Pre-fix the
    swap SUCCEEDED past a close."""
    opens: list[int] = []

    def opener(device: str, settings: dict[str, Any]) -> _SwitchPort:
        opens.append(1)
        return _SwitchPort(settings)

    events: list[dict[str, Any]] = []
    services = _services_from_opener(opener, events=events)
    asyncio.run(services.close_transport(HostOperationContext("cell-w3-close", timeout_ms=5000)))
    with pytest.raises(
        ConnectionError, match="standalone_serial_reconfigure_closed"
    ):
        asyncio.run(services.reconfigure_link({"baud": _TARGET}, _fold_ctx()))
    assert events == [], "a refusal on a closed session publishes no applied row"
    assert services.link_state() is None


def test_w3_from_baud_reads_the_current_link_inside_the_swap() -> None:
    """Wave-3 R4: ``from_baud`` is read INSIDE the swap's critical
    section — a twin queued behind a switch publishes the TRUE
    transition (3M -> boot), never a stale boot -> boot row. Pre-fix the
    read sat before the lock: with a planted opener delay making the
    interleave reachable, the queued twin published a false
    transition."""
    attempts: list[int] = []

    def delayed_opener(device: str, settings: dict[str, Any]) -> _SwitchPort:
        attempts.append(int(settings["baud"]))
        time.sleep(0.05)  # the planted interleave: both futures in flight
        return _SwitchPort(settings)

    events: list[dict[str, Any]] = []
    services = _services_from_opener(delayed_opener, events=events)

    async def scenario() -> list[BaseException]:
        context = HostOperationContext("cell-w3-r4", timeout_ms=10000)
        return list(
            await asyncio.gather(
                services.reconfigure_link({"baud": _TARGET}, context),
                services.reconfigure_link({"baud": 115200}, context),
                return_exceptions=True,
            )
        )

    outcomes = asyncio.run(scenario())
    assert not any(isinstance(row, BaseException) for row in outcomes), (
        f"both switches apply, serialized: {outcomes}"
    )
    transitions = [
        (row["from_baud"], row["to_baud"])
        for row in events
        if row["event"] == "reconfigured"
    ]
    assert transitions == [(115200, _TARGET), (_TARGET, 115200)], (
        f"the queued twin publishes the TRUE current-baud transition: {transitions}"
    )
