import asyncio
import base64
import json
from importlib.resources import files
from pathlib import Path
import pytest
from benchweave_sdk.validation import validate_descriptor, verify_provider_pin
from benchweave_sdk_server.ftdi import ScriptedFtdiDriver, ftdi_plugin_session
from benchweave_sdk_server.session import load_plugin_project
from example_plugin.adapter import create_plugin
from example_plugin import protocol as proto


def _corpus():
    """This plugin's OWN vectors.json exchanges — the one document both
    rehearsals consume (the driver double below and the mock test in this
    suite), so the corpus and the rehearsals cannot drift."""
    document = json.loads(files("example_plugin").joinpath("vectors.json").read_text())
    return document["exchanges"]


def _script():
    """The bring-up conversation as a double script (the #564 row shape),
    read from the plugin's own vectors corpus — one document, two
    rehearsals. The recorded-evidence story is the replay journal a bench
    session records with --record; this script is a rehearsal smoke, not
    evidence (it claims nothing)."""
    return _corpus()


def test_descriptor_pin_and_contract():
    descriptor = json.loads(files("example_plugin").joinpath("descriptor.json").read_text())
    validate_descriptor(descriptor)
    pinned = verify_provider_pin(
        descriptor, Path(str(files("example_plugin").joinpath("descriptor.json")))
    )
    assert pinned is not None
    assert pinned["feature_id"].startswith("otdp.transport.ftdi-control/")


def test_bring_up_rehearses_on_the_mock():
    """The transaction-boundary rehearsal (issue #570): the provider plugin
    connects under the DEFAULT mock transport — no hardware, no journal —
    the three authored polls serve the reads, the consumption trace equals
    the corpus whole-dict in order, and the script completes."""
    import asyncio as _asyncio

    from benchweave_sdk_server.session import load_plugin_project, mock_plugin_session

    project = Path(__file__).resolve().parents[1]
    plugin = load_plugin_project(project)
    corpus = _corpus()
    session = mock_plugin_session(plugin)

    async def run():
        await session.connect()
        for _ in range(3):
            read = await session.execute("read", {"parameter": "line_status"})
            assert read["status"] == "ok"
            assert read["data"]["value"] == 0x5A
        host = session.services
        expected = []
        for row in corpus:
            t = dict(row["transaction"])
            if "data" in t:
                t["data"] = bytes.fromhex(t["data"])
            expected.append(t)
        assert [dict(x) for x in host.transfers] == expected
        host.assert_complete()

    _asyncio.run(run())


def test_vectors_evidence_claims_carry_recorded_bytes():
    """The anti-circularity invariant (issue #566): a vectors.json that
    claims hardware evidence must carry at least one hand-recorded
    exchange. The scaffold ships synthetic evidence, which claims
    nothing."""
    from benchweave_sdk.vectors import validate_vectors_evidence

    document = json.loads(files("example_plugin").joinpath("vectors.json").read_text())
    validate_vectors_evidence(document, source=Path("vectors.json"))


def test_bring_up_rehearses_on_the_shipped_double(tmp_path):
    async def run():
        project = Path(__file__).resolve().parents[1]
        plugin = load_plugin_project(project)
        driver = ScriptedFtdiDriver(_script())
        session = ftdi_plugin_session(
            plugin, "ftdi://::0x0403:0x6001/1", driver_factory=lambda url: driver,
            capture_root=tmp_path / "caps",
        )
        await session.connect()
        read = await session.execute("read", {"parameter": "line_status"})
        assert read["status"] == "ok"
        assert read["data"]["value"] == 0x5A
        await session.close()
    asyncio.run(run())


def test_no_transmit_before_dispatch(tmp_path):
    async def run():
        project = Path(__file__).resolve().parents[1]
        plugin = load_plugin_project(project)
        driver = ScriptedFtdiDriver(_script())
        session = ftdi_plugin_session(
            plugin, "ftdi://::0x0403:0x6001/1", driver_factory=lambda url: driver,
            capture_root=tmp_path / "caps",
        )
        await session.connect()
        calls_before = list(driver.calls)
        handle = create_plugin()
        from benchweave_sdk.testing import MockContext
        context = MockContext("op", deadline_monotonic=1.0)
        await handle.open({}, type("Dead", (), {
            "monotonic": lambda self: 0.0,
            "transfer": lambda self, t, c: (_ for _ in ()).throw(AssertionError("transmitted")),
            "close_transport": lambda self, c: None,
        })(), context)
        request = {"operation_id": "op", "verb": "read",
                   "arguments": {"parameter": "line_status"}}
        context.cancel()
        result = await handle.execute(request, context)
        assert result["status"] == "error"
        assert result["error"]["dispatch_state"] == "not_dispatched"
        assert driver.calls == calls_before
        await session.close()
    asyncio.run(run())


def test_uncertain_response_after_dispatch(tmp_path):
    async def run():
        project = Path(__file__).resolve().parents[1]
        plugin = load_plugin_project(project)
        rows = _script()
        # Doctor the FIRST status exchange — the row the read consumes
        # after connect's eight bring-up rows.
        next(row for row in rows if row["transaction"].get("kind") == "stream_exchange")[
            "response"
        ] = {"data": "c200"}  # a partial reply: the exchange times out
        driver = ScriptedFtdiDriver(rows)
        session = ftdi_plugin_session(
            plugin, "ftdi://::0x0403:0x6001/1", driver_factory=lambda url: driver,
            capture_root=tmp_path / "caps",
        )
        await session.connect()
        read = await session.execute("read", {"parameter": "line_status"})
        assert read["status"] == "unknown"
        assert read["error"]["dispatch_state"] == "unknown"
        await session.close()
    asyncio.run(run())


def test_wire_counter_refuses_a_gap():
    """The wire helpers (issue #566): one counter sequences reads and
    writes; a gap is a refusal naming the expected and observed counter
    and the exchange index."""
    from example_plugin.wire import (
        CommandCounter, CounterGapError, EVIDENCE_COMMAND_COUNTER_GAP)
    tracker = CommandCounter(modulus=256)
    recorded = []

    async def record(entry):
        recorded.append(entry)

    async def run():
        await tracker.advance(0x10)
        await tracker.advance(0x11)

    asyncio.run(run())

    async def gap():
        await tracker.advance(0x14, record=record)

    with pytest.raises(CounterGapError,
                       match=r"exchange 2.*expected 0x12.*observed 0x14"):
        asyncio.run(gap())
    assert recorded[0]["kind"] is EVIDENCE_COMMAND_COUNTER_GAP
