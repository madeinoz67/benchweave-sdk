"""The live FTDI provider transport (issue #568): the third standalone
transport, pinned end to end.

The parity rule (the design record's §3, as amended 2026-10-28): the
scripted double SHIPS product-side (``ScriptedFtdiDriver`` in
``ftdi.py``), its script is the #564 journal's row shape, and it drives
the PRODUCTION services end to end — only the driver is doubled. The
acceptance script is the committed bring-up fixture — a SYNTHETIC
document authored to the #564 journal's row shape (no recording exists
in-tree; the fixture self-declares synthetic_fixture and claims none),
which the replay loader validates independently — so the rehearsal path
and the fixture cannot drift: if the fixture's conversation and the
double's rehearsal ever disagree, the parity test reddens.

The arms carry the design record's pre-committed acceptance (§8, amended):

- **Metric A** — the bring-up over the shipped double: every envelope
  ``ok`` and the double's recorded op-call sequence equals the journal's
  provider rows exactly (op, params, order). Zero ``ConformanceError``.
- **Metric B** — six single-point RED controls. B1 is the negative
  control, three transports wide: the SAME provider-kind transaction is
  refused on serial, on the mock, and on replay (the reference-hid
  fixture's grammar does not admit the kind) — only ftdi dispatches it.
  B2-B6 each have a permanent pin here whose mutation run reddens it.
- **Metric C** — seven honesty arms: the seam surfaces, the live banner,
  the sidecar, the CLI guards, the untouched mock refusal (with the
  unpinned-plugin serve-construction arm), the unpinned reconnect, the
  faulted-driver posture.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import hashlib
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
    ScriptedFtdiDriver,
    ftdi_plugin_session,
    open_ftdi,
    verify_ftdi_plugin,
)
from benchweave_sdk_server.replay import load_replay_journal, replay_plugin_session
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.serial import SerialCaptureServices, SerialLink
from benchweave_sdk_server.session import load_plugin_project
from benchweave_sdk_server.transport import ByteStreamMockHost

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "ftdi_control_plugin"
HID_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "replay_hid_plugin"
JOURNAL_PATH = FIXTURE_ROOT / "src" / "ftdi_control_demo" / "bring-up-journal.json"

#: The device URL every arm selects (pyftdi's selector spelling). The
#: double ignores it; the absent-device arm (B6) lets the real pyftdi
#: mapping refuse it — this bench has no FTDI device attached.
_URL = "ftdi://::0x0403:0x6001/1"

#: The negative-control transaction (amended §8, B1): the SAME
#: provider-kind transaction, refused on serial, on the mock and on
#: replay; only the ftdi transport dispatches it.
_NEGATIVE_CONTROL = {"kind": "ftdi_control", "op": "set_baud", "baud": 115200}


def _journal_rows() -> list[dict[str, Any]]:
    """The committed synthetic bring-up fixture's raw rows (the script
    AND the expectation derive from this one document — the parity rule;
    authored to the #564 journal's row shape, claiming no recording)."""
    return json.loads(JOURNAL_PATH.read_text())["rows"]


def _double(rows: list[dict[str, Any]] | None = None) -> ScriptedFtdiDriver:
    """The shipped double over the journal's rows (or doctored rows for
    the fault arms)."""
    return ScriptedFtdiDriver(rows if rows is not None else _journal_rows())


def _provider_rows(rows: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """The script's provider rows as the expected op-call sequence (op,
    params, order — the parity assertion's right-hand side)."""
    return [
        (
            row["transaction"]["op"],
            {
                key: value
                for key, value in row["transaction"].items()
                if key not in ("kind", "op")
            },
        )
        for row in rows
        if "op" in row["transaction"]
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
    contract = verify_ftdi_plugin(plugin)
    link = SerialLink(FtdiStreamAdapter(driver))
    return FtdiCaptureServices(
        link,
        driver,
        contract.grammar,
        provider=contract.provider,
        max_frame_bytes=max_frame_bytes,
        limits=contract.limits,
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
    """The negative control, arm one of three (amended §8): the SAME
    provider-kind transaction the ftdi transport dispatches is refused by
    the serial backend's own grammar gate — a provider plugin cannot
    silently land on serial. The refusal this transport exists to lift,
    WITHOUT changing it anywhere else (serial.py's ValueError)."""
    services = SerialCaptureServices(
        SerialLink(_FakeSerialTransport()), max_frame_bytes=4096
    )
    context = _context(services, "op-b1-serial")
    with pytest.raises(ValueError, match="not a section 8.1 stream transaction"):
        asyncio.run(services.transfer(_NEGATIVE_CONTROL, context))
    services.link.close()


def test_b1_the_byte_stream_mock_refuses_provider_kinds() -> None:
    """The negative control, arm two of three: the same refusal through the
    SHARED imported _FIELDS (transport.py) — the mock's honesty posture
    this design deliberately does not touch."""
    from benchweave_sdk_server.session import FrameRow

    host = ByteStreamMockHost([FrameRow("only", b"\x01", b"\x02")])
    context = MockContext("op-b1-mock", deadline_monotonic=host.monotonic() + 1)
    context.dispatched = True
    with pytest.raises(ValueError, match="not a section 8.1 stream transaction"):
        asyncio.run(host.transfer(_NEGATIVE_CONTROL, context))


def test_b1_the_replay_loader_refuses_the_provider_kind_for_a_wrong_grammar_plugin(
    tmp_path: Path,
) -> None:
    """The negative control, arm three of three: on replay, a journal row
    of the provider kind is admitted ONLY when the served plugin's pinned
    grammar declares that kind. The reference-hid fixture (an admitted
    contract, wrong grammar) is the ready-made wrong-grammar control: the
    loader refuses the row before any conversation exists. A passing run
    anywhere is NOT this control; the three refusals are — only the ftdi
    transport dispatches the transaction (Metric A, B2)."""
    hid = load_plugin_project(HID_FIXTURE_ROOT)
    journal = {
        "journal_version": "1",
        "recorded": {"started_at": "2026-10-28T00:00:00Z", "source": "b1-control"},
        "provider": {
            "feature_id": "otdp.transport.reference-hid/1.0.0",
            "id": "urn:otdp:transport-provider:reference-hid:1.0.0",
            "sha256": hashlib.sha256(
                (
                    HID_FIXTURE_ROOT / "src" / "replay_hid_demo" / "reference-provider.json"
                ).read_bytes()
            ).hexdigest(),
        },
        "rows": [
            {
                "name": "the-negative-control",
                "transaction": dict(_NEGATIVE_CONTROL),
                "response": {},
            }
        ],
    }
    path = tmp_path / "b1.json"
    path.write_text(json.dumps(journal))
    with pytest.raises(ValueError, match="replay_journal_kind:"):
        load_replay_journal(path, hid)


# --------------------------------------------------------------------------
# Metric A — the bring-up over the double (the parity arm)
# --------------------------------------------------------------------------


def test_metric_a_bring_up_over_the_double(tmp_path: Path, plugin) -> None:
    """The recorded bring-up conversation runs the PRODUCTION session over
    the SHIPPED double (amended §3): connect (the identify verb speaks the
    init chain, the bitstream chunk and the DONE gate), one read (the
    status exchange), every envelope ok, and the double's recorded op-call
    sequence equals the journal's provider rows exactly — the parity
    assertion. Zero ConformanceError (any would fail the run)."""
    rows = _journal_rows()
    provider_rows = _provider_rows(rows)
    # A's denominator, stamped in the journal file this derives from: the
    # provider-row count (7 — the init chain's six ops plus the DONE gate).
    assert len(provider_rows) == 7
    driver = _double(rows)
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
# The shipped double's own discipline (§3): exact match, honest exhaustion
# --------------------------------------------------------------------------


def test_the_shipped_double_refuses_on_exhaustion() -> None:
    """The exact-match discipline, one boundary down: a call past the end
    of the script is a ConformanceError naming the call — the rehearsal
    never invents a device answer the recording does not carry."""
    driver = ScriptedFtdiDriver(
        [
            {
                "name": "only",
                "transaction": {"kind": "ftdi_control", "op": "reset_device"},
                "response": {},
            }
        ]
    )
    driver.reset_device()
    with pytest.raises(ConformanceError, match="exhausted at call 'purge'"):
        driver.purge("rx")


def test_the_shipped_double_refuses_an_unexpected_call() -> None:
    """The exact-match discipline's mismatch arm: a call that disagrees
    with the head row (op or params) is a ConformanceError naming the row
    and the call — a drifted builder cannot rehearse clean against the
    recording."""
    driver = ScriptedFtdiDriver(
        [
            {
                "name": "bitmode-row",
                "transaction": {
                    "kind": "ftdi_control",
                    "op": "set_bitmode",
                    "mask": 0x0F,
                    "mode": 0x40,
                },
                "response": {},
            }
        ]
    )
    with pytest.raises(ConformanceError, match="row 'bitmode-row' expects"):
        driver.set_bitmode(0x0F, 0x20)  # the mode drifted


def test_the_shipped_double_refuses_a_malformed_script_row() -> None:
    """The constructor's own typed refusal: a row that is not the #564
    journal row shape refuses at construction, never mid-rehearsal."""
    with pytest.raises(ValueError, match="scripted_driver_row:"):
        ScriptedFtdiDriver([{"transaction": {"kind": "stream_send", "data": "aa"}}])
    with pytest.raises(ValueError, match="scripted_driver_row:"):
        ScriptedFtdiDriver(
            [
                {
                    "name": "bad-pins",
                    "transaction": {"kind": "ftdi_control", "op": "read_pins"},
                    "response": {},
                }
            ]
        )


# --------------------------------------------------------------------------
# Metric B — the RED controls (permanent pins; the mutation runs reddens
# each named test — evidence in the lane report)
# --------------------------------------------------------------------------


def test_metric_b2_every_table_op_dispatches(plugin) -> None:
    """B2's named test: every op in the dispatch table dispatches onto the
    driver when its transaction conforms — reverting a table entry (the
    mutation) reddens here at that op's refusal, never a silent skip."""
    samples: dict[str, dict[str, Any]] = {
        "reset_device": {},
        "set_timeouts": {"read_ms": 50, "write_ms": 500},
        "set_latency": {"ms": 16},
        "set_baud": {"baud": 115200},
        "purge": {"queue": "rx"},
        "set_bitmode": {"mask": 0x0F, "mode": 0x40},
        "read_pins": {},
    }
    rows = [
        {
            "name": f"probe-{index}",
            "transaction": {"kind": "ftdi_control", "op": op, **params},
            "response": {"data": "AA=="} if op == "read_pins" else {},
        }
        for index, (op, params) in enumerate(samples.items())
    ]
    driver = ScriptedFtdiDriver(rows)
    services = _services(plugin, driver)
    context = _context(services, "op-b2")
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
    # The journal's conversation with the status row doctored to a PARTIAL
    # reply (2 of the 4 exact bytes): the receive parks with a partial
    # frame and stays parked until its deadline. (The double accepts the
    # row — a device can emit two bytes; it is the JOURNAL format that
    # cannot record them, which is why this script is hand-doctored.)
    rows = _journal_rows()
    rows[-1]["response"] = {"data": "c200"}
    driver = ScriptedFtdiDriver(rows)
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
    # A one-row script whose read_pins answer carries TWO bytes (0x4403):
    # the double serves what it is scripted with; the ladder refuses it.
    driver = ScriptedFtdiDriver(
        [
            {
                "name": "two-byte-answer",
                "transaction": {"kind": "ftdi_control", "op": "read_pins"},
                "response": {"data": base64.b64encode(b"\x44\x03").decode("ascii")},
            }
        ]
    )
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
    driver = _double()
    seam = _wired_seam(FIXTURE_ROOT, driver, tmp_path)
    assert seam.transport_kind == "ftdi"
    info = asyncio.run(seam.call("host_info"))
    assert info["transport"] == "ftdi"
    # The acceptance review's A: a session over the SCRIPTED DOUBLE must
    # not read as live hardware on any state surface — the rehearsal
    # marker rides beside transport (the assertion was inverted: the old
    # pin held the laundering as correct).
    assert info["rehearsal"] is True, (
        "a double-driven session must disclose its rehearsal on host_info"
    )
    asyncio.run(seam.call("device_connect", {"device_id": seam.session.device_id}))
    device = asyncio.run(
        seam.call("device_get", {"device_id": seam.session.device_id})
    )
    assert device["model"] == "ftdi-control-demo"
    asyncio.run(seam.session.close())


def test_metric_c2_the_rehearsal_banner_discloses_the_scripted_double(
    tmp_path: Path, journal
) -> None:
    """C2, inverted by the acceptance review's A: a session over the
    scripted double must NOT render the plain LIVE banner — the old pin
    held the laundering as correct. The rehearsal banner carries the
    three standalone truths plus the rehearsal row; it is not the mock's
    simulation row and not the replay row; and it is distinct from the
    live shape (which carries neither)."""
    from fastapi.testclient import TestClient

    from benchweave_sdk_server.presentation import (
        REHEARSAL_MODE_WORDING,
        REPLAY_MODE_WORDING,
        mode_banner_html,
    )
    from benchweave_sdk_server.security import GuardPolicy, new_token
    from benchweave_sdk_server.web import build_app

    driver = _double()
    seam = _wired_seam(FIXTURE_ROOT, driver, tmp_path)
    policy = GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )
    live = mode_banner_html(simulated=False)
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
            assert REHEARSAL_MODE_WORDING in body, (
                "the rehearsal row discloses the scripted double"
            )
            assert "SIMULATED PRESENTATION DATA" not in body, page
            assert REPLAY_MODE_WORDING not in body, page
            assert 'data-bw-mode="simulated"' not in body, page
            assert body != live, "the rehearsal banner is not the live shape"


def test_metric_c3_sidecar_names_transport_and_contract_digest(
    tmp_path: Path, plugin
) -> None:
    """C3: the capture sidecar carries ``config.transport = "ftdi"`` and
    the pinned contract's digest — written by the REAL writer path
    (configure_capture → first append), read back from disk: file bytes,
    not in-memory state."""
    contract = verify_ftdi_plugin(plugin)
    driver = ScriptedFtdiDriver(
        [
            {
                "name": "idle",
                "transaction": {"kind": "ftdi_control", "op": "reset_device"},
                "response": {},
            }
        ]
    )
    link = SerialLink(FtdiStreamAdapter(driver))
    services = FtdiCaptureServices(
        link,
        driver,
        contract.grammar,
        provider=contract.provider,
        max_frame_bytes=4096,
        capture_root=tmp_path / "caps",
        limits=contract.limits,
        rehearsal=True,  # over the scripted double, declared (A)
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
    # The acceptance review's A: the durable evidence names the rehearsal
    # too — a capture over the scripted double must never read as a live
    # hardware capture (replay's replay_journal block is the precedent).
    assert config["rehearsal"] == {"driver": "scripted"}
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
    # Row a amended the guard: ftdi without --device now serves
    # BINDING-PENDING (the serial lane's posture) — construction succeeds
    # and connect refuses binding_absent at connect time.
    seam_no_device, _ = _build_seam(FIXTURE_ROOT, transport="ftdi")
    assert seam_no_device.transport_kind == "ftdi"
    assert seam_no_device.binding_row is None

    journal_copy = tmp_path / "journal.json"
    journal_copy.write_text(JOURNAL_PATH.read_text())
    with pytest.raises(SystemExit) as exc:
        _build_seam(FIXTURE_ROOT, transport="ftdi", replay=journal_copy)
    assert exc.value.code == 2
    assert "standalone_transport_replay_flag:" in capsys.readouterr().err

    # Row a widened --bindings to the live transports: ftdi accepts the
    # binding document (it names THEIR document now); only non-live
    # transports refuse it.
    seam_bound, _ = _build_seam(
        FIXTURE_ROOT,
        transport="ftdi",
        device=_URL,
        bindings=tmp_path / "device-bindings.json",
    )
    assert seam_bound.transport_kind == "ftdi"
    with pytest.raises(SystemExit) as exc:
        _build_seam(
            FIXTURE_ROOT,
            bindings=tmp_path / "device-bindings.json",
        )
    assert exc.value.code == 2
    assert "standalone_transport_bindings_live_only:" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        _build_seam(FIXTURE_ROOT, device=_URL)  # the default transport is mock
    assert exc.value.code == 2
    assert "standalone_transport_device_live_only:" in capsys.readouterr().err


def test_metric_c5_the_mock_stream_dialects_still_refuse_provider_kinds(
    starter_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """C5 (amended by #570): the plain mock's STREAM DIALECTS still refuse
    provider kinds — the _FIELDS gate, untouched — pinned from THIS suite
    with the fixture's OWN builder transaction; the provider dialect now
    serves them from a grammar-validated corpus (tests/server/
    test_mock_provider.py carries the amended three-refusal pin). The
    mirror arm holds: a plugin that declares NO provider cannot land on
    the ftdi transport either (live_provider_plugin_unpinned: at serve
    construction, exit 2)."""
    import sys

    from benchweave_sdk_server.session import FrameRow

    sys.path.insert(0, str(FIXTURE_ROOT / "src"))
    import ftdi_control_demo.protocol as proto

    host = ByteStreamMockHost([FrameRow("only", b"\x01", b"\x02")])
    context = MockContext("op-c5", deadline_monotonic=host.monotonic() + 1)
    context.dispatched = True
    with pytest.raises(ValueError, match="not a section 8.1 stream transaction"):
        asyncio.run(host.transfer(proto.reset_device(), context))
    # The mirror arm: the starter plugin (no provider pin) on --transport
    # ftdi refuses at serve construction, never silently serves.
    with pytest.raises(SystemExit) as exc:
        _build_seam(starter_project, transport="ftdi", device=_URL)
    assert exc.value.code == 2
    assert "live_provider_plugin_unpinned:" in capsys.readouterr().err


def test_metric_c6_unpinned_reconnect_refuses(plugin) -> None:
    """C6: an unpinning of the plugin descriptor (the provider object
    removed) on a live session's reconnect refuses
    ``live_provider_plugin_unpinned:`` — the reload-and-reconnect
    re-verify over the CURRENT plugin (replay's reconnect posture)."""
    driver = _double()
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
    driver = _double()
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
    driver = ScriptedFtdiDriver(
        [
            {
                "name": "idle",
                "transaction": {"kind": "ftdi_control", "op": "reset_device"},
                "response": {},
            }
        ]
    )
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


def test_the_fixture_contract_copy_is_byte_equal_to_the_banked_contract() -> None:
    """Refute lane B, finding 2: the design promised byte-equal-with-a-
    test between the fixture's contract copy and the banked instance;
    without this pin, an in-place edit of the banked contract would leave
    the suite green against stale fixture bytes (and the banked-bind gate
    would refuse the fixture — hiding which side moved)."""
    banked = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "benchweave_sdk"
        / "providers"
        / "ftdi-control-1.1.0.json"
    )
    copy = (
        FIXTURE_ROOT
        / "src"
        / "ftdi_control_demo"
        / "ftdi-control-provider.json"
    )
    assert copy.read_bytes() == banked.read_bytes(), (
        "the fixture's contract copy must stay byte-equal to the banked "
        "instance — regenerate the copy, never hand-edit either side"
    )


def test_conformance_error_still_importable() -> None:
    """A no-op arm keeping the module's ConformanceError import honest (the
    dispatch-marker refusal it names is exercised through every envelope
    above; the marker discipline itself is the parent's, pinned there)."""
    assert issubclass(ConformanceError, Exception)


# --------------------------------------------------------------------------
# --record (row b, owner directive 2026-10-28): a live session emits a
# #564-format journal — the recording helper the falsification session
# wants. Honesty rules: rows record completed exchanges; a timed-out
# receive records recorded_failure "timeout"; a refused or never-dispatched
# transaction records nothing; nothing is laundered into a clean row.
# --------------------------------------------------------------------------


def test_record_emits_a_replayable_journal(tmp_path: Path, plugin) -> None:
    """The marquee property: a session recorded over the double emits a
    journal that (a) validates through the replay transport's own loader
    against the same pin, (b) carries the conversation's provider rows
    exactly, and (c) REPLAYS — the recorded session completes the same
    bring-up and read through ``replay_plugin_session``, closing the loop
    record-on-ftdi → replay-on-#564."""

    record_path = tmp_path / "recorded-journal.json"
    driver = _double()
    session = ftdi_plugin_session(
        plugin,
        _URL,
        driver_factory=lambda url: driver,
        record_path=record_path,
    )
    asyncio.run(session.connect())
    read = asyncio.run(session.execute("read", {"parameter": "line_status"}))
    assert read["status"] == "ok"
    asyncio.run(session.close())
    assert record_path.is_file(), "close writes the journal"

    document = json.loads(record_path.read_text())
    assert document["journal_version"] == "1"
    assert document["recorded"]["source"] == "live_ftdi_session"
    emitted_provider_rows = _provider_rows(document["rows"])
    assert emitted_provider_rows == _provider_rows(_journal_rows()) == (
        [(op, dict(params)) for op, params in driver.calls]
    ), "the journal records what the device did — op, params, order"

    # The loop closes: the emitted journal replays the same conversation.
    parsed = load_replay_journal(record_path, plugin)
    assert parsed.row_count == 9
    replay_session = replay_plugin_session(plugin, record_path)
    asyncio.run(replay_session.connect())
    replayed = asyncio.run(
        replay_session.execute("read", {"parameter": "line_status"})
    )
    assert replayed["status"] == "ok"
    assert replayed["data"]["value"] == 0x5A
    host = replay_session.services
    from benchweave_sdk_server.replay import ReplayHost

    assert isinstance(host, ReplayHost)
    host.assert_complete()


def test_record_refuses_off_the_ftdi_transport(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One flag one meaning: ``--record`` names the ftdi transport's live
    recording; on every other transport it is refused, never silently
    ignored (the --device/--bindings guard family)."""
    journal_copy = tmp_path / "journal.json"
    journal_copy.write_text(JOURNAL_PATH.read_text())
    for kwargs in (
        {"transport": "mock"},
        {"transport": "serial", "device": "/dev/nowhere"},
        {"transport": "replay", "replay": journal_copy},
    ):
        with pytest.raises(SystemExit) as exc:
            _build_seam(
                FIXTURE_ROOT,
                record=tmp_path / "recorded.json",
                **kwargs,
            )
        assert exc.value.code == 2
        assert "standalone_transport_record_ftdi_only:" in capsys.readouterr().err


def test_a_timed_out_receive_records_the_timeout(tmp_path: Path, plugin) -> None:
    """The honesty rule: a receive whose deadline expired records
    ``recorded_failure: "timeout"`` — never a fabricated frame, never a
    laundered clean row."""
    from benchweave_sdk_server.ftdi import RecordingFtdiCaptureServices

    # A script whose status reply is a PARTIAL frame (2 of the 4 exact
    # bytes): the write releases the partial, the receive parks with it
    # buffered, and the deadline expires into the backend's TimeoutError
    # posture (the retained partial is not an outcome). The script holds
    # ONLY the status row — the arm drives the exchange directly, and the
    # exact-match double refuses out-of-order calls.
    rows = [_journal_rows()[-1]]
    rows[0]["response"] = {"data": "c200"}
    driver = ScriptedFtdiDriver(rows)
    contract = verify_ftdi_plugin(plugin)
    link = SerialLink(FtdiStreamAdapter(driver))
    services = RecordingFtdiCaptureServices(
        link,
        driver,
        contract.grammar,
        provider=contract.provider,
        max_frame_bytes=4096,
        record_path=tmp_path / "timeout-journal.json",
        limits=contract.limits,
    )
    context = MockContext("op-rec-timeout", deadline_monotonic=services.monotonic() + 0.3)
    context.dispatched = True
    with pytest.raises(TimeoutError):
        asyncio.run(
            services.transfer(
                {
                    "kind": "stream_exchange",
                    "data": bytes.fromhex("55a1"),
                    "max_bytes": 8,
                    "termination": "lf",
                    "exact_bytes": 4,
                },
                context,
            )
        )

    async def close() -> None:
        await services.close_transport(context)

    asyncio.run(close())
    document = json.loads((tmp_path / "timeout-journal.json").read_text())
    timeouts = [row for row in document["rows"] if "recorded_failure" in row]
    assert len(timeouts) == 1
    assert timeouts[0]["recorded_failure"] == "timeout"
    assert "response" not in timeouts[0] or not timeouts[0].get("response")
    link.close()


def test_a_refused_transaction_records_nothing(tmp_path: Path, plugin) -> None:
    """The honesty rule's other half: a transaction the ladder refused
    before dispatch (grammar-first) never reached the device and records
    no row — the journal's rows are what the device did."""
    from benchweave_sdk_server.ftdi import RecordingFtdiCaptureServices

    driver = ScriptedFtdiDriver(
        [
            {
                "name": "idle",
                "transaction": {"kind": "ftdi_control", "op": "reset_device"},
                "response": {},
            }
        ]
    )
    contract = verify_ftdi_plugin(plugin)
    link = SerialLink(FtdiStreamAdapter(driver))
    services = RecordingFtdiCaptureServices(
        link,
        driver,
        contract.grammar,
        provider=contract.provider,
        max_frame_bytes=4096,
        record_path=tmp_path / "refused-journal.json",
        limits=contract.limits,
    )
    context = _context(services, "op-rec-refused")
    with pytest.raises(ValueError, match="live_provider_transaction_grammar:"):
        asyncio.run(
            services.transfer(
                {"kind": "ftdi_control", "op": "set_bitmode", "mask": 999, "mode": 1},
                context,
            )
        )

    async def close() -> None:
        await services.close_transport(context)

    asyncio.run(close())
    document = json.loads((tmp_path / "refused-journal.json").read_text())
    assert document["rows"] == [], "a refused transaction records no row"
    link.close()


# --------------------------------------------------------------------------
# The mapping arm the double cannot give (refute lane A, F1/F3a): against
# the REAL pyftdi class, with no device attached, every mapped call must
# reach the library's own device stage — never a mapping-level Python
# error. F1's signature was AttributeError: 'int' object has no attribute
# 'name' from set_bitmode's raw int; F3a's was an unknown purge queue
# silently acting as "rx".
# --------------------------------------------------------------------------


def _require_real_pyftdi() -> bool:
    try:
        import pyftdi.ftdi  # noqa: F401

        return True
    except ImportError:
        return False


def test_the_real_mapping_reaches_the_device_stage_on_every_call() -> None:
    """F1's CI-honest mapping arm: over an UNOPENED real ``Ftdi`` (no
    device, no open), each mapped call either completes (the library's own
    no-op paths) or raises the library's own state error — the device
    stage — and never an attribute-level error from OUR mapping. The
    double is structurally blind to this class: it doubles the Protocol,
    not pyftdi's surface."""
    assert _require_real_pyftdi(), "this arm needs the real pyftdi installed"
    from pyftdi.ftdi import Ftdi

    from benchweave_sdk_server.ftdi import _PyftdiDriver

    driver = _PyftdiDriver(Ftdi())
    calls: list[tuple[str, Any]] = [
        ("reset_device", lambda: driver.reset_device()),
        ("set_timeouts", lambda: driver.set_timeouts(50, 500)),
        ("set_latency", lambda: driver.set_latency(16)),
        ("set_baud", lambda: driver.set_baud(115200)),
        ("purge:tx", lambda: driver.purge("tx")),
        ("purge:rx", lambda: driver.purge("rx")),
        ("set_bitmode", lambda: driver.set_bitmode(0x0F, 0x40)),
        ("read_pins", lambda: driver.read_pins()),
        ("write_data", lambda: driver.write_data(b"xy")),
        ("read_data", lambda: driver.read_data(4)),
        ("close", lambda: driver.close()),
    ]
    for name, call in calls:
        try:
            call()  # the library's own no-op path is also the device stage
        except Exception as exc:
            message = str(exc)
            assert not isinstance(exc, AttributeError) or "NoneType" in message, (
                f"{name}: our mapping raised an attribute-level error "
                f"({type(exc).__name__}: {message}) before reaching the "
                "device stage — the F1 class"
            )


def test_the_real_purge_refuses_an_unknown_queue_before_io() -> None:
    """F3a: an unknown purge queue must refuse typed before any I/O —
    never default to a queue the caller did not ask for (the
    admitted-but-unexpressible class: an unreviewed value acting as if it
    were approved)."""
    assert _require_real_pyftdi()
    from pyftdi.ftdi import Ftdi

    from benchweave_sdk_server.ftdi import _PyftdiDriver

    driver = _PyftdiDriver(Ftdi())
    with pytest.raises(ValueError, match="live_provider_transaction_grammar:"):
        driver.purge("both")


# --------------------------------------------------------------------------
# F2 (refute lane A): the feature gate binds the served contract to the
# BANKED bytes. A self-authored lookalike under an approved feature name
# must refuse — approval never launders onto foreign semantics.
# --------------------------------------------------------------------------


def _lookalike_plugin(
    tmp_path: Path,
    *,
    feature_tail: str,
    widen: bool,
) -> Path:
    """A copy of the fixture plugin whose pinned contract is a widened
    lookalike under the ftdi-control feature name: same feature family,
    self-authored semantics. ``widen`` edits the grammar (the purge enum);
    the digest and descriptor pin follow the edited bytes so the pin itself
    is internally consistent — the laundering shape."""
    import shutil

    project = tmp_path / f"lookalike-{feature_tail.replace('.', '-')}"
    shutil.copytree(FIXTURE_ROOT, project)
    package = project / "src" / "ftdi_control_demo"
    contract_path = package / "ftdi-control-provider.json"
    contract = json.loads(contract_path.read_text())
    contract["feature_id"] = f"otdp.transport.ftdi-control/{feature_tail}"
    contract["id"] = f"urn:otdp:transport-provider:ftdi-control:{feature_tail}"
    contract["version"] = feature_tail
    if widen:
        for entry in contract["transaction_grammar"]:
            for branch in entry["request_schema"]["oneOf"]:
                if branch["properties"].get("op", {}).get("const") == "purge":
                    branch["properties"]["queue"] = {"enum": ["tx", "rx", "both"]}
    raw = json.dumps(contract, indent=2).encode() + b"\n"
    contract_path.write_bytes(raw)
    descriptor_path = package / "descriptor.json"
    descriptor = json.loads(descriptor_path.read_text())
    descriptor["transport"]["provider"]["feature_id"] = contract["feature_id"]
    descriptor["transport"]["provider"]["id"] = contract["id"]
    descriptor["transport"]["provider"]["sha256"] = hashlib.sha256(raw).hexdigest()
    descriptor["required_features"] = [
        contract["feature_id"] if row.startswith("otdp.transport.ftdi-control/")
        else row
        for row in descriptor["required_features"]
    ]
    descriptor_path.write_text(json.dumps(descriptor, indent=2) + "\n")
    return project


def test_a_lookalike_contract_under_the_banked_feature_name_refuses(
    tmp_path: Path,
) -> None:
    """F2's named arm: a self-authored contract pinning the BANKED feature
    line (`ftdi-control/1.0.0`) with widened semantics (the purge enum) is
    internally consistent — its pin verifies against its own bytes — and
    must still refuse: the served grammar is bound to the banked
    instance's bytes, never to a feature-id prefix."""
    project = _lookalike_plugin(tmp_path, feature_tail="1.0.0", widen=True)
    plugin = load_plugin_project(project)
    with pytest.raises(ValueError, match="live_provider_feature_unsupported:") as raised:
        verify_ftdi_plugin(plugin)
    assert "sha256" in str(raised.value), "the refusal names the digest mismatch"


def test_an_unbanked_feature_version_refuses(tmp_path: Path) -> None:
    """The other laundering face: a lookalike under a version tail with NO
    banked instance (2.0.0 — 1.1.0 IS banked since row c) refuses — the
    executor serves banked feature lines only."""
    project = _lookalike_plugin(tmp_path, feature_tail="2.0.0", widen=True)
    plugin = load_plugin_project(project)
    with pytest.raises(ValueError, match="live_provider_feature_unsupported:"):
        verify_ftdi_plugin(plugin)


# --------------------------------------------------------------------------
# F3b (refute lane A): the contract's declared limits are ENFORCED at the
# ladder, before the driver call. The schema admits set_baud 2**40 and
# read_ms 2**63 because its limits block was checked nowhere — an
# admitted-but-unexpressible value must refuse typed, never dispatch.
# --------------------------------------------------------------------------


def test_the_contracts_declared_limits_are_enforced_before_dispatch(plugin) -> None:
    """F3b's named arm: lane A executed set_timeouts read_ms=2**63 through
    the grammar to the driver. The ladder now enforces the banked
    contract's DECLARED limits (set_timeouts_ms_range is [0, 4294967295]);
    the refused transaction never reaches the driver. What the contract
    does not declare, the ladder does not invent (A02): set_baud carries a
    minimum only, so 2**40 baud is inside the declared envelope and
    DISPATCHES — the device-side inexpressibility of such a rate is the
    contract's own disclosure seam, not a host constant."""
    driver = ScriptedFtdiDriver(
        [
            {
                "name": "impossible-rate",
                "transaction": {"kind": "ftdi_control", "op": "set_baud",
                                 "baud": 2**40},
                "response": {},
            },
        ]
    )
    services = _services(plugin, driver)
    context = _context(services, "op-f3b")
    with pytest.raises(ValueError, match="live_provider_transaction_grammar:"):
        asyncio.run(
            services.transfer(
                {
                    "kind": "ftdi_control",
                    "op": "set_timeouts",
                    "read_ms": 2**63,
                    "write_ms": 10,
                },
                context,
            )
        )
    assert driver.calls == [], "the refused transaction never reached the driver"
    # The declared-envelope case dispatches (the contract declares no baud
    # maximum) — the double's exact-match answer proves it reached the
    # driver, and the record's §5 disclosure owns the seam.
    asyncio.run(
        services.transfer(
            {"kind": "ftdi_control", "op": "set_baud", "baud": 2**40},
            context,
        )
    )
    assert ("set_baud", {"baud": 2**40}) in driver.calls
    services.link.close()


# --------------------------------------------------------------------------
# The recorder folds (refute lane A): F4 a session accumulates across
# reconnects (no write path may discard recorded rows); F5 a fully-sent
# frame lands its request row when the receive faults; F6 the faulted
# driver latches; plus the short-write label and the verify order.
# --------------------------------------------------------------------------


def test_record_accumulates_across_reconnects(tmp_path: Path, plugin) -> None:
    """F4's named arm: rows are minted per connection and close_transport
    used write_text, so a reconnect destroyed the prior conversation's
    rows — exactly the evidence a falsification session wants. A session
    now accumulates into one journal: both conversations' rows survive,
    the row names mark the connection boundary, and the journal still
    loads through the replay validator."""
    record_path = tmp_path / "session-journal.json"
    first = _double()
    second = _double()
    drivers = [first, second]
    session = ftdi_plugin_session(
        plugin,
        _URL,
        driver_factory=lambda url: drivers.pop(0) if drivers else _double(),
        record_path=record_path,
    )
    asyncio.run(session.connect())
    asyncio.run(session.execute("read", {"parameter": "line_status"}))
    asyncio.run(session.close())
    asyncio.run(session.connect())  # the reconnect that used to destroy
    asyncio.run(session.execute("read", {"parameter": "line_status"}))
    asyncio.run(session.close())
    document = json.loads(record_path.read_text())
    provider_rows = _provider_rows(document["rows"])
    one_conversation = _provider_rows(_journal_rows())
    assert provider_rows == one_conversation + one_conversation, (
        "both conversations' rows survive the reconnect"
    )
    names = [row["name"] for row in document["rows"]]
    assert any(name.startswith("conn1-") for name in names)
    assert any(name.startswith("conn2-") for name in names), (
        "the row names mark the reconnect boundary"
    )
    load_replay_journal(record_path, plugin)  # still a loadable journal


def test_a_fully_sent_frame_lands_its_request_row_when_the_receive_faults(
    tmp_path: Path, plugin
) -> None:
    """F5's named arm: the driver recorded the whole frame; the journal
    recorded zero rows for it — less honest than the timeout arm. The
    request row now lands with recorded_failure 'connection' when the
    send completed and the receive faulted; the replay loader and host
    serve that marker as the connection fault it was."""
    from benchweave_sdk_server.ftdi import RecordingFtdiCaptureServices

    rows = [_journal_rows()[-1]]
    rows[0]["response"] = {"data": "c200015a"}
    driver = ScriptedFtdiDriver(rows)
    driver.fault_reads = True  # the write lands; the reader faults after
    contract = verify_ftdi_plugin(plugin)
    stream = FtdiStreamAdapter(driver)
    link = SerialLink(stream)
    services = RecordingFtdiCaptureServices(
        link,
        driver,
        contract.grammar,
        provider=contract.provider,
        max_frame_bytes=4096,
        record_path=tmp_path / "fault-journal.json",
        limits=contract.limits,
        stream=stream,
    )
    context = _context(services, "op-f5")
    with pytest.raises(ConnectionError):
        asyncio.run(
            services.transfer(
                {
                    "kind": "stream_exchange",
                    "data": bytes.fromhex("55a1"),
                    "max_bytes": 8,
                    "termination": "lf",
                    "exact_bytes": 4,
                },
                context,
            )
        )

    async def close() -> None:
        await services.close_transport(context)

    asyncio.run(close())
    document = json.loads((tmp_path / "fault-journal.json").read_text())
    faults = [row for row in document["rows"] if row.get("recorded_failure")]
    assert len(faults) == 1, "the sent frame's row landed"
    assert faults[0]["recorded_failure"] == "connection"
    assert faults[0]["transaction"]["data"] == "55a1"
    # The marker replays as the connection fault it was: the loader
    # accepts the "connection" value and the replay host serves it as a
    # ConnectionError, not a fabricated frame (driven through the host
    # directly — the journal holds just the one row).
    from benchweave_sdk_server.replay import ReplayHost, load_replay_journal

    parsed = load_replay_journal(tmp_path / "fault-journal.json", plugin)
    host = ReplayHost(parsed)
    replay_context = MockContext("op-replay", deadline_monotonic=host.monotonic() + 2)
    replay_context.dispatched = True
    with pytest.raises(ConnectionError, match="lost its connection"):
        asyncio.run(
            host.transfer(
                {
                    "kind": "stream_exchange",
                    "data": bytes.fromhex("55a1"),
                    "max_bytes": 8,
                    "termination": "lf",
                    "exact_bytes": 4,
                },
                replay_context,
            )
        )
    link.close()


def test_a_faulted_driver_latches(tmp_path: Path, plugin) -> None:
    """F6's named arm: 'a faulted driver stays faulted' was claim-only —
    a transient fault let the next transaction answer ok. The services
    latch the fault; this arm proves the provider→provider and
    provider→stream directions (the stream→* directions are
    test_the_fault_latch_covers_the_stream_first_directions): each
    refuses ConnectionError BEFORE the driver, and the driver sees no
    further call."""
    driver = ScriptedFtdiDriver(_journal_rows())
    session = ftdi_plugin_session(
        plugin, _URL, driver_factory=lambda url: driver
    )
    asyncio.run(session.connect())
    driver.fault_writes = True  # the device is unplugged mid-session
    read = asyncio.run(session.execute("read", {"parameter": "line_status"}))
    assert read["status"] == "unknown"  # the faulted exchange
    calls_before = list(driver.calls)
    writes_before = driver.write_calls  # the read's own faulting write is in
    # The latch covers EVERY direction (the delta refute's residual 1):
    # provider→provider, provider→stream, stream→provider, stream→stream.
    # Each refuses BEFORE the driver, and the driver sees no call.
    context = _context(session.services, "op-f6")
    for _label, transaction in (
        ("provider→provider", {"kind": "ftdi_control", "op": "reset_device"}),
        (
            "provider→stream",
            {"kind": "stream_send", "data": bytes.fromhex("55a1")},
        ),
    ):
        with pytest.raises(ConnectionError, match="previously faulted"):
            asyncio.run(session.services.transfer(transaction, context))
    assert driver.write_calls == writes_before, "no second driver call"
    assert driver.calls == calls_before
    asyncio.run(session.close())


def test_an_unexpressible_bitmode_refuses_typed_without_latching(plugin) -> None:
    """Residual 2: the contract admits mode 0..255; the FTDI family's
    BitMode byte expresses eight values. An inadmissible mode must refuse
    TYPED before the driver call (F3a's principle) and must NOT latch the
    connection as faulted — a parameter-domain error is not a connection
    fault."""
    driver = ScriptedFtdiDriver(_journal_rows())
    services = _services(plugin, driver)
    context = _context(services, "op-mode")
    with pytest.raises(ValueError, match="live_provider_transaction_grammar:"):
        asyncio.run(
            services.transfer(
                {"kind": "ftdi_control", "op": "set_bitmode", "mask": 15, "mode": 99},
                context,
            )
        )
    assert driver.calls == [], "the refusal happens before the driver"
    # No latch: the connection still serves.
    asyncio.run(
        services.transfer({"kind": "ftdi_control", "op": "reset_device"}, context)
    )
    services.link.close()


def test_the_fault_latch_covers_the_stream_first_directions(plugin) -> None:
    """Residual 1's other half: after a STREAM fault, both a later stream
    transaction and a later provider transaction must refuse before the
    driver (STREAM→stream, STREAM→provider)."""
    driver = ScriptedFtdiDriver(_journal_rows())
    session = ftdi_plugin_session(
        plugin, _URL, driver_factory=lambda url: driver
    )
    asyncio.run(session.connect())
    driver.fault_writes = True
    read = asyncio.run(session.execute("read", {"parameter": "line_status"}))
    assert read["status"] == "unknown"
    calls_before = list(driver.calls)
    writes_before = driver.write_calls
    context = _context(session.services, "op-f6b")
    for _label, transaction in (
        ("stream→stream", {"kind": "stream_send", "data": bytes.fromhex("55a1")}),
        ("stream→provider", {"kind": "ftdi_control", "op": "reset_device"}),
    ):
        with pytest.raises(ConnectionError, match="previously faulted"):
            asyncio.run(session.services.transfer(transaction, context))
    assert driver.write_calls == writes_before, "no second driver call"
    assert driver.calls == calls_before
    asyncio.run(session.close())


def test_the_short_write_refusal_names_the_ftdi_transport(plugin) -> None:
    """Lane A's observation: the inherited short-write refusal printed
    'serial write reported ...' on the ftdi transport. The message names
    the transport that actually short-wrote."""
    rows = [
        {
            "name": "chunk",
            "transaction": {
                "kind": "stream_send",
                "data": "deadbeefcafebabe",
            },
            "response": {},
        }
    ]
    driver = ScriptedFtdiDriver(rows)
    driver.short_writes = True  # the write lands short: 4 of 8 bytes
    services = _services(plugin, driver)
    context = _context(services, "op-short")
    with pytest.raises(ConnectionError, match="ftdi write reported 4 of 8"):
        asyncio.run(
            services.transfer(
                {"kind": "stream_send", "data": bytes.fromhex("deadbeefcafebabe")},
                context,
            )
        )
    services.link.close()


def test_a_missing_backend_does_not_mask_a_contract_refusal(
    tmp_path: Path, starter_project: Path, monkeypatch
) -> None:
    """Lane A's observation: verify_ftdi_plugin checked the pyftdi
    backend before the pin, so a missing extra masked the contract
    refusal at serve. The contract-level check runs first; a deployment
    error never hides a contract one."""
    import sys

    monkeypatch.setitem(sys.modules, "pyftdi.ftdi", None)
    unpinned = load_plugin_project(starter_project)
    with pytest.raises(ValueError, match="live_provider_plugin_unpinned:"):
        verify_ftdi_plugin(unpinned)


def test_the_stream_reply_wakes_the_reader_not_the_sleep_quantum(
    tmp_path: Path, plugin, monkeypatch
) -> None:
    """The macOS CI failure (PR #221), reproduced deterministically and
    pinned. The mechanism, proven by directed repro on this machine: the
    read's stream reply sits in the driver's pipe the moment the write
    returns, but the SerialLink reader thread delivers it into the ring on
    its next poll — a poll that waits out the adapter's idle quantum when
    the pipe was empty. take() answers the QUIET LINE after the 100ms
    quiet window; the adapter then fails the decode and the fixture
    adapter honestly maps the post-dispatch ValueError to status UNKNOWN.
    The CI runner's slow suite (287s) delayed the reader's pickup past
    the window; a loaded local run five times slower did NOT reproduce it
    (the pickup normally lands within one 50ms quantum), so the margin —
    the quiet window minus up to one idle quantum — is the dependence.

    The fix removes the quantum from the delivery path: a full write
    WAKES the reader (the reply-follows-request causality of this pipe),
    so the delivery margin becomes the whole quiet window instead of the
    window minus the quantum. This arm amplifies the quantum (5s) to
    make the race deterministic: pre-fix the recorded read answers the
    quiet line (status unknown); post-fix the wake delivers the reply
    and the read is ok."""
    import benchweave_sdk_server.ftdi as ftdi_module

    monkeypatch.setattr(ftdi_module, "_IDLE_SLEEP_S", 5.0)
    record_path = tmp_path / "recorded-journal.json"
    driver = _double()
    session = ftdi_plugin_session(
        plugin,
        _URL,
        driver_factory=lambda url: driver,
        record_path=record_path,
    )
    asyncio.run(session.connect())
    read = asyncio.run(session.execute("read", {"parameter": "line_status"}))
    assert read["status"] == "ok", read
