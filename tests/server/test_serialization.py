"""The seam's op-vs-reload serialization (the refute lanes' FOLD-A class):
no await point inside a device-mutating sequence may admit a reload or a
staging write that breaks the sequence's meaning.

Two deterministic repros, both with a slow-write adapter (the lanes'
wrapper shape — 40ms of write latency makes the interleaving land inside
the window every run, not by luck):

- stage-vs-apply: a stage landing between the in-flight apply's last
  write and its staging-map clear must SURVIVE — today the clear() eats
  it and the value vanishes without ever reaching the device;
- preset-vs-reload: a reload landing inside a preset apply's
  write→read-back span must WAIT — today the write goes to the old
  adapter and the read-back to the new one (a cross-adapter chimera
  reported SUCCESS, SW-23's read-back rule broken), with the old
  adapter's data landing in the post-swap ring.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from benchweave_sdk.testing import ConformanceError
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.session import PluginSession, load_plugin_project
from benchweave_sdk_server.transport import LoopingMockHost

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "setpoint_plugin"
DEV = {"device_id": "setpoint_dev"}
PARAM = "current_limit"
WRITE_DELAY_S = 0.04


class SlowWriteAdapter:
    """Wraps the fixture adapter: every ``write`` verb sleeps, and every
    envelope is recorded as ``(instance identity, verb)`` — the chimera
    observable is a write and its read-back served by DIFFERENT
    instances."""

    def __init__(self, inner: Any, tag: int, served: list[tuple[int, str]]) -> None:
        self._inner = inner
        self._tag = tag
        self._served = served

    async def open(self, descriptor: Any, services: Any, context: Any) -> None:
        await self._inner.open(descriptor, services, context)

    async def execute(self, request: Any, context: Any) -> Any:
        verb = str(request.get("verb"))
        self._served.append((self._tag, verb))
        if verb == "write":
            await asyncio.sleep(WRITE_DELAY_S)
        return await self._inner.execute(request, context)

    async def next_event(self, subscription_id: Any, context: Any) -> Any:
        return await self._inner.next_event(subscription_id, context)

    async def close(self, context: Any) -> None:
        await self._inner.close(context)


class WriteThroughHost(LoopingMockHost):
    """The setpoint fixture's write-through scripted device (the same
    shape test_control's SetpointHost pins, on the real-clock looping
    base so the adapter's deadline arithmetic works): identity, read and
    write frames; a write changes what the next read serves, so apply's
    read-back can only ever come from the device."""

    def __init__(self) -> None:
        super().__init__([], establishment=0)
        self.limit = 2.0

    async def transfer(self, transaction: Any, context: Any) -> dict[str, Any]:
        data = bytes(transaction.get("data", b""))
        if data == b"ID?\n":
            return {"data": b"BenchWeave Labs,setpoint-demo,SIM-SP1,1.0.0\n"}
        if data == b"LIM?\n":
            return {"data": f"{self.limit:g}\n".encode("ascii")}
        if data.startswith(b"LIM ") and data.endswith(b"\n"):
            self.limit = float(data[4:-1].decode("ascii"))
            return {"data": b"OK\n"}
        raise ConformanceError(f"unscripted exchange: {data!r}")


def _slow_seam(
    project: Path, *, unattended: bool = False
) -> tuple[StandaloneSeam, list[tuple[int, str]]]:
    from dataclasses import replace

    plugin = load_plugin_project(project)
    served: list[tuple[int, str]] = []
    counter = [0]
    original = plugin.adapter_factory

    def factory() -> Any:
        counter[0] += 1
        return SlowWriteAdapter(original(), counter[0], served)

    instrumented = replace(plugin, adapter_factory=factory)
    session = PluginSession(instrumented, WriteThroughHost)
    return (
        StandaloneSeam(session, transport_kind="mock", unattended=unattended),
        served,
    )


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "setpoint"
    shutil.copytree(FIXTURE, project)
    return project


async def _connect(seam: StandaloneSeam) -> None:
    await seam.call("device_connect", DEV)


# --- A(i): stage-vs-apply --------------------------------------------------------


def test_a_stage_landing_mid_apply_survives(tmp_path) -> None:
    async def scenario() -> None:
        seam, _served = _slow_seam(_project(tmp_path))
        await _connect(seam)
        await seam.call(
            "parameter_stage", {**DEV, "parameter": PARAM, "value": 1.0}
        )
        applying = asyncio.create_task(
            seam.call("parameter_apply", {"device_id": DEV["device_id"]})
        )
        # Land inside the apply's write window (the slow adapter holds it
        # open for WRITE_DELAY_S; a tenth of that is comfortably inside).
        await asyncio.sleep(WRITE_DELAY_S / 4)
        staged_mid_flight = await seam.call(
            "parameter_stage", {**DEV, "parameter": PARAM, "value": 2.0}
        )
        applied = await applying
        assert staged_mid_flight["staged"] == [PARAM]
        assert applied["applied"], "the apply itself must succeed"
        # The mid-flight stage MUST survive: it arrived after the apply's
        # own batch was fixed, so the apply has no business clearing it.
        assert seam.staged == {PARAM: 2.0}, (
            "a stage that landed mid-apply vanished — the apply's "
            "staging-map clear ate a value the device never saw"
        )

    asyncio.run(scenario())


# --- A(ii): preset-vs-reload -----------------------------------------------------


def test_a_reload_waits_for_an_in_flight_preset_apply(tmp_path) -> None:
    async def scenario() -> None:
        project = _project(tmp_path)
        seam, served = _slow_seam(project, unattended=True)
        await _connect(seam)
        # An ADAPTER-code change stands ready (unattended: no confirmation
        # gate; adapter bytes leave the descriptor pin untouched, so the
        # preset apply's own drift check still passes).
        adapter = project / "src" / "setpoint_demo" / "adapter.py"
        adapter.write_text(adapter.read_text() + "\n# edit\n")
        applying = asyncio.create_task(
            seam.call("preset_apply", {**DEV, "preset_id": "steady"})
        )
        await asyncio.sleep(WRITE_DELAY_S / 4)
        reloading = asyncio.create_task(seam.reload_plugin(source="test"))
        applied = await applying
        reloaded = await reloading
        assert applied["applied"], "the preset apply must complete"
        assert reloaded["status"] == "reloaded"
        # The write and its read-back were served by ONE adapter
        # generation — a cross-adapter pair is the chimera.
        writes = [tag for tag, verb in served if verb == "write"]
        reads_after = [
            tag
            for tag, verb in served[
                served.index((writes[-1], "write")) + 1 :
            ]
            if verb == "read"
        ]
        assert reads_after, "the read-back must be observable"
        assert all(tag == writes[-1] for tag in reads_after), (
            "write and read-back crossed adapter generations — the "
            "reload swapped the adapter inside the apply's span"
        )
        # And the bus agrees on the order: the apply COMPLETED before the
        # reload swapped anything.
        kinds = [
            row["kind"]
            for row in (await seam.call("events_get", {"after_id": 0}))["events"]
        ]
        assert kinds.index("preset_apply") < kinds.index("plugin_reloaded")

    asyncio.run(scenario())


def test_a_the_repro_class_is_real_pre_fix(tmp_path) -> None:
    """The lanes demanded the repros be deterministic, not lucky: the
    slow-write window is 40ms and the interleaving lands a quarter in —
    assert the window itself opens (the write is still in flight when
    the second operation starts), so the arm can never pass by timing
    accident."""
    async def scenario() -> None:
        seam, served = _slow_seam(_project(tmp_path))
        await _connect(seam)
        await seam.call("parameter_stage", {**DEV, "parameter": PARAM, "value": 1.0})
        applying = asyncio.create_task(
            seam.call("parameter_apply", {"device_id": DEV["device_id"]})
        )
        await asyncio.sleep(WRITE_DELAY_S / 4)
        # The write is still mid-flight: no read-back has been served yet.
        assert not [verb for _tag, verb in served if verb == "read"]
        await applying

    asyncio.run(scenario())
