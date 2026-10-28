"""The live FTDI provider transport (issue #568): the third standalone
transport, pinned end to end.

The parity rule (the design record's §3): only the driver is doubled. The
scripted double's expected op sequence, its pin answers and its data-pipe
replies are all DERIVED from the committed bring-up journal — the same
evidence document the replay transport validates — so the rehearsal path
and the recorded conversation cannot drift: if the journal's recorded
conversation and the double's rehearsal ever disagree, the parity test
reddens.

The arms carry the design record's pre-committed acceptance (§8):

- **Metric A** — the bring-up over the double: every envelope ``ok`` and
  the double's recorded op-call sequence equals the journal's provider
  rows exactly (op, params, order). Zero ``ConformanceError``.
- **Metric B** — six single-point RED controls (B1 is the pre-change
  posture on the pre-existing transports; B2-B6 each have a permanent pin
  here whose mutation run reddens it).
- **Metric C** — seven honesty arms: the seam surfaces, the live banner,
  the sidecar, the CLI guards, the untouched mock refusal, the unpinned
  reconnect, the faulted-driver posture.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import time
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.testing import ConformanceError, MockContext
from benchweave_sdk_server.cli import _build_seam
from benchweave_sdk_server.ftdi import (
    FtdiCaptureServices,
    FtdiStreamAdapter,
    ftdi_plugin_session,
    open_ftdi,
    verify_ftdi_plugin,
)
from benchweave_sdk_server.replay import load_replay_journal
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.serial import SerialCaptureServices, SerialLink
from benchweave_sdk_server.session import load_plugin_project
from benchweave_sdk_server.transport import ByteStreamMockHost

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "ftdi_control_plugin"
HID_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "replay_hid_plugin"
JOURNAL_PATH = FIXTURE_ROOT / "bring-up-journal.json"

#: The device URL every arm selects (pyftdi's selector spelling). The
#: double ignores it; the absent-device arm (B6) lets the real pyftdi
#: mapping refuse it — this bench has no FTDI device attached.
_URL = "ftdi://::0x0403:0x6001/1"


class ScriptedFtdiDriver:
    """The scripted ``FtdiDriver`` double: records every control-op call
    (op, params), answers ``read_pins`` from a script, releases data-pipe
    replies as each write lands (a device answers writes), and bounds its
    parameters the way the real driver's firmware would — a mask of 999
    never reaches it (the grammar refuses first), but the double's contract
    still refuses it (the serial suite's fake-Transport posture, one level
    up). ``fault_writes`` turns every later ``write_data`` into the
    mid-conversation unplug fault (C7)."""

    def __init__(
        self, *, pins: list[int] | None = None, pipe: list[bytes] | None = None
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.writes: list[bytes] = []
        self.write_calls = 0
        self.closes = 0
        self.fault_writes = False
        self._pins = list(pins or [])
        self._pipe = list(pipe or [])
        self._inbound = bytearray()

    def _record(self, op: str, params: dict[str, Any]) -> None:
        self.calls.append((op, dict(params)))

    def reset_device(self) -> None:
        self._record("reset_device", {})

    def set_timeouts(self, read_ms: int, write_ms: int) -> None:
        if read_ms < 0 or write_ms < 0:
            raise ValueError("timeouts are nonnegative")
        self._record("set_timeouts", {"read_ms": read_ms, "write_ms": write_ms})

    def set_latency(self, ms: int) -> None:
        if not 0 <= ms <= 255:
            raise ValueError("latency timer is one byte")
        self._record("set_latency", {"ms": ms})

    def set_baud(self, baud: int) -> None:
        if baud < 1:
            raise ValueError("baud rate is positive")
        self._record("set_baud", {"baud": baud})

    def purge(self, queue: str) -> None:
        if queue not in ("tx", "rx"):
            raise ValueError("queue is 'tx' or 'rx'")
        self._record("purge", {"queue": queue})

    def set_bitmode(self, mask: int, mode: int) -> None:
        if not 0 <= mask <= 255 or not 0 <= mode <= 255:
            raise ValueError("mask and mode are one byte each")
        self._record("set_bitmode", {"mask": mask, "mode": mode})

    def read_pins(self) -> int:
        self._record("read_pins", {})
        if not self._pins:
            raise AssertionError("the pin script is exhausted")
        return self._pins.pop(0)

    def write_data(self, data: bytes) -> int:
        self.write_calls += 1
        if self.fault_writes:
            raise OSError("device unplugged")
        self.writes.append(bytes(data))
        if self._pipe:
            self._inbound += self._pipe.pop(0)
        return len(data)

    def read_data(self, size: int) -> bytes:
        out = bytes(self._inbound[:size])
        del self._inbound[:size]
        return out

    def close(self) -> None:
        self.closes += 1


def _double_from_journal(journal: Any) -> ScriptedFtdiDriver:
    """The parity rule's center: the double's script IS the journal — pin
    answers from the provider rows' recorded results, data-pipe replies
    from the stream rows' recorded responses."""
    pins = [
        row.result["data"][0]
        for row in journal.rows
        if row.result is not None and "data" in row.result
    ]
    pipe = [
        row.response
        for row in journal.rows
        if row.command and row.kind in ("stream_send", "stream_exchange") and row.response
    ]
    return ScriptedFtdiDriver(pins=pins, pipe=pipe)


def _provider_rows(journal: Any) -> list[tuple[str, dict[str, Any]]]:
    """The journal's provider rows as the expected op-call sequence (op,
    params, order — the parity assertion's right-hand side)."""
    return [
        (
            row.expected["op"],
            {
                key: value
                for key, value in row.expected.items()
                if key not in ("kind", "op")
            },
        )
        for row in journal.rows
        if row.expected is not None
    ]


@pytest.fixture(scope="module")
def plugin():
    return load_plugin_project(FIXTURE_ROOT)


@pytest.fixture(scope="module")
def journal(plugin):
    return load_replay_journal(JOURNAL_PATH, plugin)


def _services(
    plugin: Any,
    driver: ScriptedFtdiDriver,
    *,
    max_frame_bytes: int = 4096,
) -> FtdiCaptureServices:
    """A directly-constructed services object over the double (the unit
    arms' hand — the same construction the session factory performs)."""
    grammar, provider = verify_ftdi_plugin(plugin)
    link = SerialLink(FtdiStreamAdapter(driver))
    return FtdiCaptureServices(
        link,
        driver,
        grammar,
        provider=provider,
        max_frame_bytes=max_frame_bytes,
    )


def _context(services: Any, name: str = "op-x") -> MockContext:
    context = MockContext(name, deadline_monotonic=services.monotonic() + 2)
    context.dispatched = True
    return context


# --------------------------------------------------------------------------
# B1 — the pre-change posture, pinned (the design's RED statement, made
# permanent): the pre-existing standalone transports refuse provider kinds
# --------------------------------------------------------------------------


class _FakeSerialTransport:
    """The serial suite's minimal Transport (write/read/close)."""

    def __init__(self) -> None:
        self._inbound = bytearray()

    def write(self, data: bytes) -> int | None:
        return len(data)

    def read(self, size: int = 1) -> bytes:
        out = bytes(self._inbound[:size])
        del self._inbound[:size]
        return out

    def close(self) -> None: ...


def test_b1_the_serial_backend_refuses_provider_kinds(plugin) -> None:
    """The serial backend's own grammar gate refuses the fixture's provider
    transaction by construction — the refusal this transport exists to
    lift, WITHOUT changing it anywhere else (serial.py's ValueError)."""
    services = SerialCaptureServices(
        SerialLink(_FakeSerialTransport()), max_frame_bytes=4096
    )
    context = _context(services, "op-b1-serial")
    with pytest.raises(ValueError, match="not a section 8.1 stream transaction"):
        asyncio.run(
            services.transfer(
                {"kind": "ftdi_control", "op": "reset_device"}, context
            )
        )
    services.link.close()


def test_b1_the_byte_stream_mock_refuses_provider_kinds() -> None:
    """The same refusal through the SHARED imported _FIELDS (transport.py)
    — the mock's honesty posture this design deliberately does not touch
    (C5's other half)."""
    from benchweave_sdk_server.session import FrameRow

    host = ByteStreamMockHost([FrameRow("only", b"\x01", b"\x02")])
    context = MockContext("op-b1-mock", deadline_monotonic=host.monotonic() + 1)
    context.dispatched = True
    with pytest.raises(ValueError, match="not a section 8.1 stream transaction"):
        asyncio.run(
            host.transfer({"kind": "ftdi_control", "op": "reset_device"}, context)
        )


# --------------------------------------------------------------------------
# Metric A — the bring-up over the double (the parity arm)
# --------------------------------------------------------------------------


def test_metric_a_bring_up_over_the_double(tmp_path: Path, plugin, journal) -> None:
    """The recorded bring-up conversation runs through ``ftdi_plugin_session``
    over the scripted double: connect (the identify verb speaks the init
    chain, the bitstream chunk and the DONE gate), one read (the status
    exchange), every envelope ok, and the double's recorded op-call
    sequence equals the journal's provider rows exactly — the parity
    assertion. Zero ConformanceError (any would fail the run)."""
    provider_rows = _provider_rows(journal)
    # A's denominator, stamped in the journal file this derives from: the
    # provider-row count (7 — the init chain's six ops plus the DONE gate).
    assert len(provider_rows) == 7
    driver = _double_from_journal(journal)
    session = ftdi_plugin_session(
        plugin, _URL, driver_factory=lambda url: driver, capture_root=tmp_path / "caps"
    )
    asyncio.run(session.connect())
    assert session.identity is not None, "connect establishes identity"
    assert session.identity["manufacturer"] == "OTDP Reference"
    read = asyncio.run(session.execute("read", {"parameter": "line_status"}))
    assert read["status"] == "ok", read
    assert read["data"]["value"] == 0x5A  # the recorded reading byte
    assert driver.calls == provider_rows, (
        "the rehearsal and the recording disagree — the parity rule reddens"
    )
    assert [op for op, _ in driver.calls] == [
        "reset_device",
        "purge",
        "set_latency",
        "set_baud",
        "set_bitmode",
        "read_pins",
        "read_pins",
    ], "the journal's provider order is the bring-up order"
    # The stream side rode the inherited SerialLink over the adapter: the
    # bitstream chunk and the status request both reached the data pipe.
    assert driver.writes == [
        bytes.fromhex("deadbeefcafebabe"),
        bytes.fromhex("55a1"),
    ]
    asyncio.run(session.close())


# --------------------------------------------------------------------------
# Metric B — the RED controls (permanent pins; the mutation runs reddens
# each named test — evidence in the lane report)
# --------------------------------------------------------------------------


def test_metric_b2_every_table_op_dispatches(plugin) -> None:
    """B2's named test: every op in the dispatch table dispatches onto the
    driver when its transaction conforms — reverting a table entry (the
    mutation) reddens here at that op's refusal, never a silent skip."""
    driver = ScriptedFtdiDriver(pins=[0x00])
    services = _services(plugin, driver)
    context = _context(services, "op-b2")
    samples: dict[str, dict[str, Any]] = {
        "reset_device": {},
        "set_timeouts": {"read_ms": 50, "write_ms": 500},
        "set_latency": {"ms": 16},
        "set_baud": {"baud": 115200},
        "purge": {"queue": "rx"},
        "set_bitmode": {"mask": 0x0F, "mode": 0x40},
        "read_pins": {},
    }
    for op, params in samples.items():
        result = asyncio.run(
            services.transfer({"kind": "ftdi_control", "op": op, **params}, context)
        )
        if op == "read_pins":
            assert result == {"data": b"\x00"}
        else:
            assert result == {}
    assert [op for op, _ in driver.calls] == list(samples)
    services.link.close()


def test_metric_b3_busy_guard_refuses_control_under_parked_receive(
    plugin,
) -> None:
    """B3's named test: a control op under a parked receive refuses
    ``live_provider_line_busy:`` BEFORE dispatch — the double never sees
    the op. With the guard reverted (the mutation) the control op runs and
    this test reddens. The park is observed through the link's own
    receive-depth counter (the deterministic hook; a partial frame keeps
    the receive parked until its deadline)."""
    driver = ScriptedFtdiDriver(
        pins=[0x00, 0x80],
        # A PARTIAL status reply (2 of the 4 exact bytes): the receive
        # parks with a partial frame and stays parked until its deadline.
        pipe=[b"\xc2\x00"],
    )
    session = ftdi_plugin_session(
        plugin, _URL, driver_factory=lambda url: driver
    )

    async def scenario() -> dict[str, Any]:
        await session.connect()
        link = session.services.link
        task = asyncio.create_task(
            session.execute("read", {"parameter": "line_status"})
        )
        deadline = time.monotonic() + 2.0
        while link.receive_depth == 0 and time.monotonic() < deadline:
            await asyncio.sleep(0.001)
        assert link.receive_depth == 1, "the receive parked (partial frame)"
        context = _context(session.services, "op-b3")
        with pytest.raises(ValueError, match="live_provider_line_busy:"):
            await session.services.transfer(
                {"kind": "ftdi_control", "op": "set_baud", "baud": 9600}, context
            )
        await session.close()  # unwinds the parked receive through the closed path
        return await task

    envelope = asyncio.run(scenario())
    # The parked receive unwound through the closing link: a DISPATCHED
    # exchange whose transport faulted answers the honest uncertain posture
    # ("unknown" — the transmit happened, the outcome is ambiguous), never
    # a clean ok (the replay fixture's own envelope discipline).
    assert envelope["status"] == "unknown"
    assert envelope["error"]["code"] == "TRANSPORT_ERROR"
    # The refused control op never reached the driver — the INIT chain's
    # own set_baud (115200) did; the refused one (9600) must not.
    assert ("set_baud", {"baud": 9600}) not in driver.calls, (
        "the refused control op never reached the driver"
    )


def test_metric_b4_result_grammar_refuses_a_two_byte_answer(plugin) -> None:
    """B4's named test: a driver answering two bytes' worth for read_pins
    refuses ``live_provider_result_grammar:`` — the live device is
    untrusted against its own pinned contract. With the validation
    reverted (the mutation) the refusal disappears and this test reddens."""
    driver = ScriptedFtdiDriver(pins=[0x4403])  # two bytes' worth, not one
    services = _services(plugin, driver)
    context = _context(services, "op-b4")
    with pytest.raises(ValueError, match="live_provider_result_grammar:"):
        asyncio.run(
            services.transfer({"kind": "ftdi_control", "op": "read_pins"}, context)
        )
    services.link.close()


def test_metric_b5_wrong_feature_refuses(capsys: pytest.CaptureFixture[str]) -> None:
    """B5's named test: the reference-hid fixture (an admitted contract,
    wrong feature family) on ``--transport ftdi`` refuses
    ``live_provider_feature_unsupported:`` at serve construction rather
    than serving foreign semantics. With the feature gate reverted (the
    mutation) the build proceeds and this test reddens."""
    hid = load_plugin_project(HID_FIXTURE_ROOT)
    with pytest.raises(ValueError, match="live_provider_feature_unsupported:"):
        verify_ftdi_plugin(hid)
    # The CLI branch's fail-fast carries the same refusal to exit 2.
    with pytest.raises(SystemExit) as exc:
        _build_seam(HID_FIXTURE_ROOT, transport="ftdi", device=_URL)
    assert exc.value.code == 2
    assert "live_provider_feature_unsupported:" in capsys.readouterr().err


def test_metric_b6_absent_device_refuses(plugin) -> None:
    """B6's named test: REAL pyftdi, no device attached (this bench has
    none) — the connect refuses ``live_provider_device_unavailable:``
    naming the exception class, one attempt, no scan, no retry. With the
    availability refusal deleted and a fabricated ok returned (the
    mutation) this test reddens."""
    session = ftdi_plugin_session(plugin, _URL)  # driver_factory=None: the real open
    with pytest.raises(RuntimeError, match="live_provider_device_unavailable:"):
        asyncio.run(session.connect())


# --------------------------------------------------------------------------
# Metric C — the honesty arms (7/7)
# --------------------------------------------------------------------------


def _wired_seam(
    project: Path,
    driver: ScriptedFtdiDriver,
    tmp_path: Path,
) -> StandaloneSeam:
    seam, selection = _build_seam(
        project,
        transport="ftdi",
        device=_URL,
        driver_factory=lambda url: driver,
        capture_root=tmp_path / "caps",
    )
    assert selection is None
    return seam


def test_metric_c1_seam_surfaces_report_ftdi_transport(
    tmp_path: Path, plugin, journal
) -> None:
    """C1: the seam's state surfaces report ``transport: "ftdi"`` — the
    seam property, ``host_info`` (REST and MCP's state surface) and the
    connected ``device_get`` identity block. (The binding-row surface is
    serial-only by construction; the capture-row surface is C3's sidecar
    arm.)"""
    driver = _double_from_journal(journal)
    seam = _wired_seam(FIXTURE_ROOT, driver, tmp_path)
    assert seam.transport_kind == "ftdi"
    info = asyncio.run(seam.call("host_info"))
    assert info["transport"] == "ftdi"
    asyncio.run(seam.call("device_connect", {"device_id": seam.session.device_id}))
    device = asyncio.run(
        seam.call("device_get", {"device_id": seam.session.device_id})
    )
    assert device["model"] == "ftdi-control-demo"
    asyncio.run(seam.session.close())


def test_metric_c2_banner_is_the_live_shape(
    tmp_path: Path, journal
) -> None:
    """C2: the mode banner over the ftdi seam renders the LIVE shape —
    the three standalone truths, no ``simulated`` row, no replay row —
    string-pinned against the presentation literals, through the real
    page-rendering path (web.py classifies by exclusion: ftdi is neither
    mock nor replay)."""
    from fastapi.testclient import TestClient

    from benchweave_sdk_server.presentation import REPLAY_MODE_WORDING
    from benchweave_sdk_server.security import GuardPolicy, new_token
    from benchweave_sdk_server.web import build_app

    driver = _double_from_journal(journal)
    seam = _wired_seam(FIXTURE_ROOT, driver, tmp_path)
    policy = GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )
    with TestClient(
        build_app(seam, policy=policy), base_url="http://127.0.0.1:8477"
    ) as client:
        # The fixture plugin carries no presentation documents, so its page
        # set is the shell surfaces (index + device page) — the banner rides
        # the shell.
        for page in ("/", f"/devices/{seam.session.device_id}"):
            body = client.get(page).text
            for wording in (
                "NO GATEWAY · LOCAL PRESENTATION ONLY",
                "NO CONTROLLER LEASE · ACTIONS CANNOT BE AUTHORISED",
                "NO POLICY ENGINE · POLICY CHECKS UNAVAILABLE",
            ):
                assert wording in body, (page, wording)
            assert "SIMULATED PRESENTATION DATA" not in body, page
            assert REPLAY_MODE_WORDING not in body, page
            assert 'data-bw-mode="simulated"' not in body, page


def test_metric_c3_sidecar_names_transport_and_contract_digest(
    tmp_path: Path, plugin
) -> None:
    """C3: the capture sidecar carries ``config.transport = "ftdi"`` and
    the pinned contract's digest — written by the REAL writer path
    (configure_capture → first append), read back from disk: file bytes,
    not in-memory state."""
    grammar, provider = verify_ftdi_plugin(plugin)
    driver = ScriptedFtdiDriver()
    link = SerialLink(FtdiStreamAdapter(driver))
    services = FtdiCaptureServices(
        link,
        driver,
        grammar,
        provider=provider,
        max_frame_bytes=4096,
        capture_root=tmp_path / "caps",
    )

    async def run() -> None:
        services.configure_capture(
            "cap-ftdi", metadata={"surface": "test"}, max_bytes=1024
        )
        await services.artifact_append("cap-ftdi", b"\x01\x02\x03\x04", None)
        await services.artifact_finalise(
            "cap-ftdi",
            {
                "format": "raw_binary",
                "sample_count": 4,
                "sample_interval_s": 0.001,
                "started_at": services.utc_now(),
                "unit": "V",
            },
            None,
        )

    asyncio.run(run())
    link.close()
    sidecars = sorted((tmp_path / "caps").rglob("metadata.json"))
    assert len(sidecars) == 1
    sidecar = json.loads(sidecars[0].read_text())
    config = sidecar["config"]
    assert config["transport"] == "ftdi"
    pinned = json.loads(
        (FIXTURE_ROOT / "src" / "ftdi_control_demo" / "ftdi-control-provider.json").read_text()
    )
    import hashlib

    assert config["provider"]["feature_id"] == pinned["feature_id"]
    assert config["provider"]["sha256"] == hashlib.sha256(
        (FIXTURE_ROOT / "src" / "ftdi_control_demo" / "ftdi-control-provider.json").read_bytes()
    ).hexdigest()
    assert config["max_bytes"] == 1024  # the effective reservation survives


def test_metric_c4_cli_guards(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """C4: ``--transport ftdi`` without ``--device`` refuses typed exit 2;
    ``--replay`` and ``--bindings`` refuse on ftdi through the EXISTING
    guards (one flag one meaning); ``--device`` on a non-live transport
    refuses through the amended live-only guard row."""
    with pytest.raises(SystemExit) as exc:
        _build_seam(FIXTURE_ROOT, transport="ftdi")
    assert exc.value.code == 2
    assert "standalone_transport_ftdi_device_required:" in capsys.readouterr().err

    journal_copy = tmp_path / "journal.json"
    journal_copy.write_text(JOURNAL_PATH.read_text())
    with pytest.raises(SystemExit) as exc:
        _build_seam(FIXTURE_ROOT, transport="ftdi", replay=journal_copy)
    assert exc.value.code == 2
    assert "standalone_transport_replay_flag:" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        _build_seam(
            FIXTURE_ROOT,
            transport="ftdi",
            device=_URL,
            bindings=tmp_path / "device-bindings.json",
        )
    assert exc.value.code == 2
    assert "standalone_transport_bindings_serial_only:" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        _build_seam(FIXTURE_ROOT, device=_URL)  # the default transport is mock
    assert exc.value.code == 2
    assert "standalone_transport_device_live_only:" in capsys.readouterr().err


def test_metric_c5_the_mock_still_refuses_provider_kinds_from_the_ftdi_side() -> None:
    """C5: the plain mock still refuses provider kinds — the honest posture
    (a builder-derived vectors script cannot script control ops), pinned
    from THIS suite with the fixture's OWN builder transaction. The mock
    session for a provider plugin refuses one step earlier still: it has no
    vectors.json to script (a provider plugin's conversation is control
    ops, which the mock cannot rehearse by design)."""
    import sys

    from benchweave_sdk_server.session import FrameRow, mock_plugin_session

    sys.path.insert(0, str(FIXTURE_ROOT / "src"))
    import ftdi_control_demo.protocol as proto

    plugin = load_plugin_project(FIXTURE_ROOT)
    host = ByteStreamMockHost([FrameRow("only", b"\x01", b"\x02")])
    context = MockContext("op-c5", deadline_monotonic=host.monotonic() + 1)
    context.dispatched = True
    with pytest.raises(ValueError, match="not a section 8.1 stream transaction"):
        asyncio.run(host.transfer(proto.reset_device(), context))
    session = mock_plugin_session(plugin)
    with pytest.raises(Exception) as raised:
        asyncio.run(session.connect())
    assert "vectors.json" in str(raised.value), (
        "a provider plugin has no mock script — the honest load refusal"
    )


def test_metric_c6_unpinned_reconnect_refuses(plugin) -> None:
    """C6: an unpinning of the plugin descriptor (the provider object
    removed) on a live session's reconnect refuses
    ``live_provider_plugin_unpinned:`` — the reload-and-reconnect
    re-verify over the CURRENT plugin (replay's reconnect posture)."""
    driver = ScriptedFtdiDriver(pins=[0x00, 0x80])
    session = ftdi_plugin_session(
        plugin, _URL, driver_factory=lambda url: driver
    )
    asyncio.run(session.connect())
    unpinned = dataclasses.replace(
        plugin,
        descriptor={
            **plugin.descriptor,
            "transport": {
                key: value
                for key, value in plugin.descriptor["transport"].items()
                if key != "provider"
            },
        },
    )
    asyncio.run(session.reload_plugin(unpinned))
    with pytest.raises(RuntimeError) as raised:
        asyncio.run(session.connect())
    assert "live_provider_plugin_unpinned:" in str(raised.value)


def test_metric_c7_midconversation_fault_maps_not_ready_no_retry(
    tmp_path: Path, journal
) -> None:
    """C7: a mid-conversation driver fault maps to ConnectionError → the
    seam's ``not_ready`` (the TRANSPORT_ERROR envelope mapping), and the
    double records exactly one call at the faulting op — one bounded
    attempt, never a host retry (A06)."""
    driver = _double_from_journal(journal)
    seam = _wired_seam(FIXTURE_ROOT, driver, tmp_path)
    asyncio.run(seam.call("device_connect", {"device_id": seam.session.device_id}))
    writes_after_connect = driver.write_calls
    driver.fault_writes = True  # the device is unplugged mid-conversation
    from benchweave_sdk_server.errors import SeamError

    with pytest.raises(SeamError) as raised:
        asyncio.run(
            seam.call(
                "parameter_read",
                {"device_id": seam.session.device_id, "parameter": "line_status"},
            )
        )
    assert raised.value.code == "not_ready"
    assert driver.write_calls == writes_after_connect + 1, (
        "the faulting write ran exactly once — no host retry"
    )
    asyncio.run(seam.session.close())


# --------------------------------------------------------------------------
# The refusal family's remaining members (grammar-first, backend missing)
# --------------------------------------------------------------------------


def test_transaction_grammar_refuses_out_of_envelope_params(plugin) -> None:
    """Grammar-first: an out-of-envelope control transaction refuses
    ``live_provider_transaction_grammar:`` before any state change — a
    mask of 999 never reaches the driver."""
    driver = ScriptedFtdiDriver()
    services = _services(plugin, driver)
    context = _context(services, "op-grammar")
    with pytest.raises(ValueError, match="live_provider_transaction_grammar:"):
        asyncio.run(
            services.transfer(
                {"kind": "ftdi_control", "op": "set_bitmode", "mask": 999, "mode": 1},
                context,
            )
        )
    assert driver.calls == [], "the refused transaction never reached the driver"
    services.link.close()


def test_backend_missing_refuses_with_the_install_hint(
    plugin, monkeypatch
) -> None:
    """A missing pyftdi refuses ``live_provider_backend_missing:`` with the
    ``[server]``-extra install hint — the open_serial_port precedent, at
    serve construction and at open."""
    import sys

    monkeypatch.setitem(sys.modules, "pyftdi.ftdi", None)
    with pytest.raises(RuntimeError, match="live_provider_backend_missing:"):
        verify_ftdi_plugin(plugin)
    with pytest.raises(RuntimeError, match="live_provider_backend_missing:"):
        open_ftdi(_URL)


def test_the_journal_is_a_valid_replay_document(plugin, journal) -> None:
    """The one-evidence-document property, cross-checked: the bring-up
    journal loads through the REPLAY transport's own validator against the
    same pin — 9 rows, 7 of them provider rows (Metric A's denominator),
    the recorded read_pins replies decoding to the DONE-gated pin bytes."""
    assert journal.row_count == 9
    provider_rows = [row for row in journal.rows if row.expected is not None]
    assert len(provider_rows) == 7
    pin_replies = [
        row.result["data"]
        for row in journal.rows
        if row.result is not None and "data" in row.result
    ]
    assert pin_replies == [b"\x00", b"\x80"]
    # The pin bytes are what the pinned contract's result schema declares:
    # one byte, padded base64 (the pattern that closes the three-byte door).
    assert base64.b64encode(pin_replies[1]).decode("ascii") == "gA=="


def test_conformance_error_still_importable() -> None:
    """A no-op arm keeping the module's ConformanceError import honest (the
    dispatch-marker refusal it names is exercised through every envelope
    above; the marker discipline itself is the parent's, pinned there)."""
    assert issubclass(ConformanceError, Exception)
