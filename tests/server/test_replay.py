"""The replay transport (issue #564; gateway #562 work item 3): a recorded
journal served as the wire, pinned end to end.

The journals below are spelled from LITERALS in this module — the same wire
bytes the fixture plugin's builders spell in
``tests/fixtures/replay_hid_plugin/src/replay_hid_demo/protocol.py``, but
independently written here. That independence is the whole point: the
journal is evidence about the builders, so it cannot be derived from them
(the circularity the byte-stream mock's vectors.json script cannot shed).

The arms carry the design record's pre-committed acceptance (§7):

- **Metric A** — the acceptance journal (31 rows, 30 non-digest) replays to
  completion through the standalone host: every envelope ``ok``,
  ``assert_complete()`` passes, zero ``ConformanceError``.
- **Metric B** — six single-point builder mutations, each failing loudly:
  the page-bits simulation, the provider report id, the resync mask, the
  poll pulse byte, the decode inversion (the scenario's decoded-status
  assertion, not the transport), and the resync marker. A mutation that
  replays clean is a KILL, not a finding.
- **Metric C** — the five honesty arms: ``transport: "replay"`` on the seam
  surfaces, the distinct banner, the capture sidecar's journal evidence,
  the provider-triple refusal, honest exhaustion.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from benchweave_sdk.testing import ConformanceError
from benchweave_sdk_server.cli import _build_seam
from benchweave_sdk_server.replay import (
    BULK_INLINE_LIMIT,
    JOURNAL_BYTE_LIMIT,
    ReplayHost,
    load_replay_journal,
    replay_plugin_session,
)
from benchweave_sdk_server.session import load_plugin_project
from benchweave_sdk_server.transport import ByteStreamMockHost

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "replay_hid_plugin"

_PROVIDER = {
    "feature_id": "otdp.transport.reference-hid/1.0.0",
    "id": "urn:otdp:transport-provider:reference-hid:1.0.0",
    "sha256": "",  # stamped by _journal from the fixture's pinned bytes
}

_RECORDED = {
    "started_at": "2026-10-26T00:00:00Z",
    "source": "synthetic_fixture",
    "single_owner": True,
}

#: The wire literals — spelled HERE, independently of the plugin's
#: protocol.py. resync = marker e7, mask 5a; poll = sync 55, page-addressed
#: register 42 (0x02 | 0x40), pulse a5; status reply = the recorded
#: read-reply grammar c2 00 <counter> <reading>; acks = c1 00 <counter>.
_RESYNC_HEX = "e75a"
_POLL_HEX = "5542a5"
_STATUS_HEX = "c200015a"
_CONFIG_ACK_HEX = "c10001"
_CAPTURE_START_HEX = "3304"
_CAPTURE_END_HEX = "3400"
_CAPTURE_ACK_HEX = "c10004"
_IDENTIFY_PAYLOAD = b"\x90\x00"
_IDENTIFY_REPLY = b"\x10" * 32

#: The bulk configuration blob — the SAME generator the plugin spells, but
#: written out here as an independent expression (the digest row pins it).
_CONFIG_BLOB = bytes((i * 7 + 3) & 0xFF for i in range(10_000))


def _provider_sha() -> str:
    raw = (FIXTURE_ROOT / "src" / "replay_hid_demo" / "reference-provider.json").read_bytes()
    return hashlib.sha256(raw).hexdigest()


def _journal(rows: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    provider = dict(_PROVIDER, sha256=_provider_sha())
    provider.update(overrides.pop("provider_overrides", {}))
    recorded = dict(_RECORDED)
    recorded.update(overrides.pop("recorded_overrides", {}))
    return {
        "journal_version": "1",
        "recorded": recorded,
        "provider": provider,
        "rows": rows,
    }


def _write(tmp: Path, journal: dict[str, Any], name: str = "journal.json") -> Path:
    path = tmp / name
    path.write_text(json.dumps(journal, indent=2) + "\n")
    return path


def _read_rows(
    count: int, *, counter: int | None = 1, start: int = 0
) -> list[dict[str, Any]]:
    """``count`` read conversations — resync, quiet drain, poll, status.
    A ``counter`` of None leaves the counter byte INCREMENTING per read
    (the no-derivable-cycle recording: responses vary across occurrences).
    ``start`` offsets the row NAMES so a truncated journal's extra rows stay
    unique (row names are diagnostics; identity never reads them)."""
    rows: list[dict[str, Any]] = []
    for offset in range(1, count + 1):
        index = start + offset
        suffix = f"-{index}"
        status = _STATUS_HEX if counter is not None else f"c200{index:02x}5a"
        rows += [
            {"name": "resync" + suffix,
             "transaction": {"kind": "stream_send", "data": _RESYNC_HEX},
             "response": {}},
            {"name": "resync-drain" + suffix,
             "transaction": {"kind": "stream_receive", "max_bytes": 8,
                             "termination": "lf", "exact_bytes": None},
             "response": {}},
            {"name": "poll" + suffix,
             "transaction": {"kind": "stream_send", "data": _POLL_HEX},
             "response": {}},
            {"name": "status" + suffix,
             "transaction": {"kind": "stream_receive", "max_bytes": 8,
                             "termination": "lf", "exact_bytes": 4},
             "response": {"data": status}},
        ]
    return rows


def _establishment_rows() -> list[dict[str, Any]]:
    """The connect-time establishment the adapter's identify verb speaks:
    the provider handshake, then the bulk configuration load."""
    return [
        {"name": "identify-command",
         "transaction": {"kind": "hid_output_report", "report_id": 1,
                         "data": base64.b64encode(_IDENTIFY_PAYLOAD).decode()},
         "response": {}},
        {"name": "identify-reply",
         "transaction": {"kind": "hid_input_report", "report_id": 1,
                         "max_bytes": 32},
         "response": {"report_id": 1,
                      "data": base64.b64encode(_IDENTIFY_REPLY).decode()}},
        {"name": "config-send",
         "transaction": {"kind": "stream_send",
                         "data_sha256": hashlib.sha256(_CONFIG_BLOB).hexdigest(),
                         "byte_length": len(_CONFIG_BLOB)},
         "response": {}},
        {"name": "config-ack",
         "transaction": {"kind": "stream_receive", "max_bytes": 4,
                         "termination": "lf", "exact_bytes": 3},
         "response": {"data": _CONFIG_ACK_HEX}},
    ]


def _acceptance_journal() -> dict[str, Any]:
    """The acceptance recording: the provider identify handshake, the bulk
    configuration load, five read conversations, one capture. 31 rows, 30
    non-digest (the configuration send rides as a digest row)."""
    rows: list[dict[str, Any]] = list(_establishment_rows())
    rows += _read_rows(5)
    rows += [
        {"name": "capture-start",
         "transaction": {"kind": "stream_send", "data": _CAPTURE_START_HEX},
         "response": {}},
    ]
    for index in range(1, 5):
        rows.append(
            {"name": f"sample-{index}",
             "transaction": {"kind": "stream_receive", "max_bytes": 8,
                             "termination": "lf", "exact_bytes": 8},
             "response": {"data": f"{index:02x}" * 8}}
        )
    rows += [
        {"name": "capture-end",
         "transaction": {"kind": "stream_send", "data": _CAPTURE_END_HEX},
         "response": {}},
        {"name": "capture-ack",
         "transaction": {"kind": "stream_receive", "max_bytes": 4,
                         "termination": "lf", "exact_bytes": 3},
         "response": {"data": _CAPTURE_ACK_HEX}},
    ]
    return _journal(rows)


@pytest.fixture(scope="module")
def plugin():
    return load_plugin_project(FIXTURE_ROOT)


@pytest.fixture(scope="module")
def protocol_module(plugin):
    sys.path.insert(0, str(FIXTURE_ROOT / "src"))
    import replay_hid_demo.protocol as module

    return module


def _connected(tmp: Path, journal: dict[str, Any], plugin: Any) -> Any:
    """A connected session over the replay transport, plus its host."""
    path = _write(tmp, journal)
    session = replay_plugin_session(plugin, path)
    asyncio.run(session.connect())
    return session


def _read_once(session: Any) -> dict[str, Any]:
    return asyncio.run(session.execute("read", {"parameter": "bus_power"}))


# --------------------------------------------------------------------------
# The pre-fix posture, pinned (the design's RED statement, made permanent)
# --------------------------------------------------------------------------


def test_standalone_hosts_refuse_provider_kinds(plugin) -> None:
    """The two pre-existing standalone backends refuse every provider-kind
    transaction by construction — the refusal the replay transport exists
    to lift, WITHOUT changing it anywhere else (transport.py's ValueError,
    unchanged by this slice)."""
    from benchweave_sdk.testing import MockContext
    from benchweave_sdk_server.session import FrameRow

    host = ByteStreamMockHost([FrameRow("only", b"\x01", b"\x02")])
    context = MockContext("op-x", deadline_monotonic=host.monotonic() + 1)
    context.dispatched = True
    with pytest.raises(ValueError, match="not a section 8.1 stream transaction"):
        asyncio.run(
            host.transfer({"kind": "hid_output_report", "report_id": 1, "data": b"x"}, context)
        )


# --------------------------------------------------------------------------
# Metric A — the replay serves the recorded conversation
# --------------------------------------------------------------------------


def test_metric_a_acceptance_journal_replays_clean(tmp_path: Path, plugin) -> None:
    journal_doc = _acceptance_journal()
    path = _write(tmp_path, journal_doc)
    parsed = load_replay_journal(path, plugin)
    # The metric's own denominators, stamped by the loader: 31 rows, 30 of
    # them non-digest (>= 20 required), one digest-form bulk row.
    assert parsed.row_count == 31
    assert parsed.non_digest_rows == 30
    assert parsed.non_digest_rows >= 20
    session = replay_plugin_session(plugin, path)
    asyncio.run(session.connect())
    envelopes = [session.identity]
    for _ in range(5):
        envelopes.append(_read_once(session))
    capture = asyncio.run(
        session.execute("capture", {"capture_id": "cap-a", "count": 8})
    )
    envelopes.append(capture)
    assert all(row is not None for row in envelopes)
    for envelope in envelopes[1:]:
        assert envelope["status"] == "ok", envelope
    assert capture["data"]["frames"] == 4
    host = session.services
    assert isinstance(host, ReplayHost)
    host.assert_complete()
    assert host.pending == 0
    assert host.plays == 1  # no derivable cycle: the recording plays once


# --------------------------------------------------------------------------
# Metric B — the journal pins the builders (6/6 must fail loudly)
# --------------------------------------------------------------------------

#: The six single-point mutations: (label, target module attribute, value).
#: B5 is the decode inversion — it fails the decoded-status assertion, not
#: the transport, so its arm asserts the divergent VALUE instead.
_MUTATIONS = [
    ("b1_page_bits", "WIRE_PAGE_BITS", 0x20),
    ("b2_report_id", "REPORT_ID_CMD", 0x02),
    ("b3_resync_mask", "RESYNC_MASK", 0x5B),
    ("b4_pulse_byte", "PULSE_BYTE", 0x00),
    ("b6_resync_marker", "RESYNC_MARKER", 0xE8),
]


@pytest.mark.parametrize("label,attribute,value", _MUTATIONS, ids=[m[0] for m in _MUTATIONS])
def test_metric_b_wire_mutations_fail_loudly(
    tmp_path: Path, plugin, protocol_module, monkeypatch, label, attribute, value
) -> None:
    path = _write(tmp_path, _acceptance_journal())
    monkeypatch.setattr(protocol_module, attribute, value)
    session = replay_plugin_session(plugin, path)
    # B2 diverges inside identify itself (the connect-time exchange); every
    # other mutation survives identify and fails at its first read. The
    # conformance failure propagates RAW through session.connect/execute
    # (the adapter's own except-tuple does not catch AssertionError
    # subclasses), naming the offending row.
    with pytest.raises(ConformanceError, match=r"row (identify-command|resync-1|poll-1)"):
        asyncio.run(session.connect())
        _read_once(session)


def test_metric_b_decode_inversion_fails_the_decoded_assertion(
    tmp_path: Path, plugin, monkeypatch
) -> None:
    """B5: an inverted decode returns the WRONG VALUE with the transport
    clean — the scenario's decoded-status assertion is what catches it
    (the recorded reading is 0x5A; the mutation answers anything else)."""
    sys.path.insert(0, str(FIXTURE_ROOT / "src"))
    import replay_hid_demo.adapter as adapter_module

    path = _write(tmp_path, _acceptance_journal())
    session = replay_plugin_session(plugin, path)
    asyncio.run(session.connect())
    control = _read_once(session)
    assert control["data"]["value"] == 0x5A  # the unmutated control reading

    monkeypatch.setattr(
        adapter_module, "decode_status", lambda data: data[3] ^ 0xFF
    )
    mutated = _read_once(session)
    assert mutated["status"] == "ok"  # the transport served the recording…
    assert mutated["data"]["value"] != 0x5A  # …but the decoded reading lies


# --------------------------------------------------------------------------
# Metric C — the honesty arms
# --------------------------------------------------------------------------


def test_metric_c1_seam_surfaces_report_replay_transport(tmp_path: Path, plugin) -> None:
    path = _write(tmp_path, _acceptance_journal())
    seam, selection = _build_seam(
        FIXTURE_ROOT, transport="replay", replay=path, capture_root=tmp_path / "caps"
    )
    assert selection is None
    assert seam.transport_kind == "replay"
    info = asyncio.run(seam.call("host_info"))
    assert info["transport"] == "replay"
    device = seam.session.device_id
    asyncio.run(seam.call("device_connect", {"device_id": device}))
    for _ in range(5):  # the recording's reads, in recorded order
        read = asyncio.run(
            seam.call(
                "parameter_read", {"device_id": device, "parameter": "bus_power"}
            )
        )
        assert read["value"] == 0x5A
    asyncio.run(
        seam.call(
            "capture_start",
            {
                "device_id": device,
                "format": "raw_binary",
                "sample_interval_s": 0.001,
                "unit": "V",
                "count": 8,
            },
        )
    )
    # The count-bounded capture ran to publication inside the start call
    # (the replay serves instantly); the published sidecar — served back by
    # capture_get — carries BOTH transport spellings: the seam's own
    # metadata field and the host-stamped config block with the journal
    # evidence (C1 and C3's seam-level surface, one durable document).
    outcomes = seam._capture_outcomes  # noqa: SLF001 - the durable row under test
    assert outcomes, "the capture published"
    capture_id, row = next(iter(outcomes.items()))
    assert row["state"] == "published"
    assert row["byte_length"] == 32
    published = asyncio.run(seam.call("capture_get", {"capture_id": capture_id}))
    metadata = published["metadata"]
    assert metadata["transport"] == "replay"
    assert metadata["config"]["transport"] == "replay"
    assert metadata["config"]["replay_journal"]["sha256"] == load_replay_journal(
        path, plugin
    ).sha256


def test_metric_c2_banner_is_distinct_from_mock_and_live() -> None:
    from benchweave_sdk_server.presentation import (
        REHEARSAL_MODE_WORDING,
        REPLAY_MODE_WORDING,
        mode_banner_html,
    )

    replay = mode_banner_html(simulated=False, replay=True)
    mock = mode_banner_html(simulated=True)
    live = mode_banner_html(simulated=False)
    rehearsal = mode_banner_html(simulated=False, rehearsal=True)
    assert REPLAY_MODE_WORDING in replay
    assert "SIMULATED PRESENTATION DATA" not in replay
    assert "SIMULATED PRESENTATION DATA" in mock
    assert REPLAY_MODE_WORDING not in mock
    assert REPLAY_MODE_WORDING not in live
    assert "SIMULATED PRESENTATION DATA" not in live
    # The acceptance review's A: the SCRIPTED REHEARSAL row is a fourth
    # truth — four-way distinctness, and the rehearsal row lives in none
    # of the other three shapes.
    assert REHEARSAL_MODE_WORDING in rehearsal
    assert REPLAY_MODE_WORDING not in rehearsal
    assert "SIMULATED PRESENTATION DATA" not in rehearsal
    assert REHEARSAL_MODE_WORDING not in live
    assert REHEARSAL_MODE_WORDING not in mock
    assert REHEARSAL_MODE_WORDING not in replay
    shapes = (mock, replay, rehearsal, live)
    assert len(set(shapes)) == 4, "the four banner shapes are pairwise distinct"


def test_metric_c3_capture_sidecar_carries_the_journal_evidence(
    tmp_path: Path, plugin
) -> None:
    """The sidecar names the transport AND the exact recording: written by
    the REAL writer path (configure_capture → first append), read back from
    disk — file bytes, not in-memory state."""
    path = _write(tmp_path, _acceptance_journal())
    parsed = load_replay_journal(path, plugin)
    host = ReplayHost(parsed, capture_root=tmp_path / "caps")

    async def run() -> None:
        host.configure_capture(
            "cap-side", metadata={"surface": "test"}, max_bytes=1024
        )
        await host.artifact_append("cap-side", b"\x01\x02\x03\x04", None)
        # The tail flush is what reaches the writer (the buffer flushes at
        # the block size or the reservation): finalise publishes and the
        # sidecar lands with the first flushed bytes.
        await host.artifact_finalise(
            "cap-side",
            {
                "format": "raw_binary",
                "sample_count": 4,
                "sample_interval_s": 0.001,
                # The summary stamps REPLAY time, never the recording's
                # start (the honesty rule — a recorded timestamp is
                # evidence, not an observation; the refute fold's NIT).
                "started_at": host.utc_now(),
                "unit": "V",
            },
            None,
        )

    asyncio.run(run())
    sidecars = sorted((tmp_path / "caps").rglob("metadata.json"))
    assert len(sidecars) == 1
    sidecar = json.loads(sidecars[0].read_text())
    config = sidecar["config"]
    assert config["transport"] == "replay"
    assert config["replay_journal"] == {
        "sha256": parsed.sha256,
        "recorded_at": _RECORDED["started_at"],
    }
    assert config["max_bytes"] == 1024  # the effective reservation survives


def test_metric_c4_provider_mismatch_refuses(tmp_path: Path, plugin) -> None:
    journal = _acceptance_journal()
    journal["provider"]["sha256"] = "b" * 64
    path = _write(tmp_path, journal)
    with pytest.raises(ValueError, match="replay_journal_provider_mismatch:"):
        replay_plugin_session(plugin, path)


def test_metric_c5_honest_exhaustion_never_fabricates(tmp_path: Path, plugin) -> None:
    """Past the recording's end: the quiet line for an empty stream, the
    retained-partial TimeoutError for a partial, and a transmit past the
    end is a ConformanceError — never a fabricated row."""
    from benchweave_sdk.testing import MockContext

    path = _write(tmp_path, _journal(_read_rows(3, counter=None)))
    parsed = load_replay_journal(path, plugin)
    assert parsed.cycle == []  # varying responses: no derivable unit
    host = ReplayHost(parsed)
    context = MockContext("op-c5", deadline_monotonic=host.monotonic() + 5)
    context.dispatched = True
    # Drain the whole recording through the adapter-shaped conversation.
    asyncio.run(session_consume(host, plugin))
    assert host.pending == 0
    receive = {"kind": "stream_receive", "max_bytes": 8, "termination": "lf",
               "exact_bytes": None}
    assert asyncio.run(host.transfer(receive, context)) == {"data": b""}
    with pytest.raises(Exception, match="exhausted"):
        asyncio.run(
            host.transfer({"kind": "stream_send", "data": bytes.fromhex(_RESYNC_HEX)}, context)
        )

    # The retained-partial arm: a recorded unterminated partial answers the
    # backend's TimeoutError posture, not a fabricated frame.
    partial = _journal([
        {"name": "burst-send",
         "transaction": {"kind": "stream_send", "data": "11"},
         "response": {"data": "aa bb".replace(" ", "")}},
        {"name": "burst-receive",
         "transaction": {"kind": "stream_receive", "max_bytes": 8,
                         "termination": "lf", "exact_bytes": None},
         "response": {}},
    ])
    host2 = ReplayHost(load_replay_journal(_write(tmp_path, partial, "partial.json"), plugin))
    context2 = MockContext("op-c5b", deadline_monotonic=host2.monotonic() + 5)
    context2.dispatched = True
    asyncio.run(
        host2.transfer({"kind": "stream_send", "data": b"\x11"}, context2)
    )
    with pytest.raises(TimeoutError, match="partial frame stays buffered"):
        asyncio.run(host2.transfer(receive, context2))


async def session_consume(host: ReplayHost, plugin: Any) -> None:
    """Drive the no-cycle journal's whole conversation directly: the
    provider handshake (varying-counter reads need no identify here — the
    rows are only reads), then each read conversation in order."""
    context = type(
        "Ctx", (), {"operation_id": "x", "deadline_monotonic": host.monotonic() + 5,
                    "dispatched": True, "is_cancelled": lambda self: False}
    )()
    for _ in range(3):
        await host.transfer({"kind": "stream_send", "data": bytes.fromhex(_RESYNC_HEX)}, context)
        await host.transfer({"kind": "stream_receive", "max_bytes": 8,
                             "termination": "lf", "exact_bytes": None}, context)
        await host.transfer({"kind": "stream_send", "data": bytes.fromhex(_POLL_HEX)}, context)
        await host.transfer({"kind": "stream_receive", "max_bytes": 8,
                             "termination": "lf", "exact_bytes": 4}, context)


# --------------------------------------------------------------------------
# The cycle machinery (inherited semantics, honest when underivable)
# --------------------------------------------------------------------------


def test_cycle_restores_on_command_and_counts_plays(tmp_path: Path, plugin) -> None:
    """A journal whose read unit repeats with constant responses derives
    the minimal period: after the recording plays out, the next command
    restores the unit (plays increments) and the conversation continues."""
    path = _write(tmp_path, _journal(_establishment_rows() + _read_rows(3)))
    session = replay_plugin_session(plugin, path)
    asyncio.run(session.connect())
    for _ in range(3):
        _read_once(session)
    host = session.services
    assert isinstance(host, ReplayHost)
    assert host.pending == 0
    assert host.plays == 1
    _read_once(session)  # the restore sustains the read
    assert host.plays == 2
    host.assert_complete()


def test_cycle_rotation_continues_at_the_captured_phase(tmp_path: Path, plugin) -> None:
    """A recording that ended MID-READ restores rotated to that phase: the
    next poll matches immediately (the inherited rotate semantics, proven
    behaviorally through the adapter's own conversation)."""
    path = _write(tmp_path, _journal(
        _establishment_rows() + _read_rows(3) + _read_rows(1, start=3)[:2]
    ))
    parsed = load_replay_journal(path, plugin)
    assert parsed.rotate == 2  # (18 - 4) % 4: the capture ended at phase 2
    session = replay_plugin_session(plugin, path)
    asyncio.run(session.connect())
    for _ in range(4):  # the fourth read continues THROUGH the restore
        envelope = _read_once(session)
        assert envelope["status"] == "ok"
    host = session.services
    assert isinstance(host, ReplayHost)
    assert host.plays == 2


def test_cycles_one_is_the_red_control(tmp_path: Path, plugin) -> None:
    """``cycles=1`` pins the restore mechanism as the thing that sustains
    reads: with the budget spent, the same command that restored a moment
    ago now exhausts honestly."""
    from benchweave_sdk.testing import MockContext

    path = _write(tmp_path, _journal(_read_rows(3)))
    parsed = load_replay_journal(path, plugin)
    assert len(parsed.cycle) == 4
    host = ReplayHost(parsed, cycles=1)
    context = MockContext("op-c1", deadline_monotonic=host.monotonic() + 5)
    context.dispatched = True
    asyncio.run(session_consume(host, plugin))
    assert host.plays == 1
    with pytest.raises(Exception, match="exhausted"):
        asyncio.run(
            host.transfer({"kind": "stream_send", "data": bytes.fromhex(_RESYNC_HEX)}, context)
        )


def test_recorded_failure_timeout_replays_the_timeout(tmp_path: Path, plugin) -> None:
    """A recorded timeout stays a timeout: the receive answers the
    backend's TimeoutError posture naming the row — no fabricated frame, no
    clean quiet-line upgrade of the recorded ambiguity (A06)."""
    from benchweave_sdk.testing import MockContext

    journal = _journal([
        {"name": "poll-1",
         "transaction": {"kind": "stream_send", "data": _POLL_HEX},
         "response": {}},
        {"name": "early-timeout",
         "transaction": {"kind": "stream_receive", "max_bytes": 3,
                         "termination": "lf", "exact_bytes": None},
         "recorded_failure": "timeout"},
    ])
    host = ReplayHost(load_replay_journal(_write(tmp_path, journal), plugin))
    context = MockContext("op-t", deadline_monotonic=host.monotonic() + 5)
    context.dispatched = True
    asyncio.run(
        host.transfer({"kind": "stream_send", "data": bytes.fromhex(_POLL_HEX)}, context)
    )
    with pytest.raises(TimeoutError, match="early-timeout"):
        asyncio.run(
            host.transfer({"kind": "stream_receive", "max_bytes": 3,
                           "termination": "lf", "exact_bytes": None}, context)
        )


# --------------------------------------------------------------------------
# Loader refusals (typed, load-time, before any conversation)
# --------------------------------------------------------------------------


def test_journal_file_bound_names_bound_and_remedy(tmp_path: Path, plugin) -> None:
    big = dict(_acceptance_journal())
    big["recorded"] = dict(big["recorded"], operator_note="x" * (JOURNAL_BYTE_LIMIT + 1))
    path = _write(tmp_path, big)
    with pytest.raises(ValueError, match="replay_journal_bound:") as caught:
        load_replay_journal(path, plugin)
    message = str(caught.value)
    assert "1 MiB" in message
    assert "digest-form rows" in message


def test_bulk_inline_rows_refuse_with_remedy(tmp_path: Path, plugin) -> None:
    journal = _journal([
        {"name": "oversize",
         "transaction": {"kind": "stream_send",
                         "data": "ab" * BULK_INLINE_LIMIT},
         "response": {}},
    ])
    with pytest.raises(ValueError, match="replay_journal_bulk:") as caught:
        load_replay_journal(_write(tmp_path, journal), plugin)
    assert "data_sha256" in str(caught.value)


@pytest.mark.parametrize(
    "fault,expected",
    [
        ("version", "replay_journal_version:"),
        ("not_json", "replay_journal_invalid:"),
        ("no_rows", "replay_journal_rows:"),
        ("duplicate_names", "replay_journal_row_shape:"),
        ("bad_hex", "replay_journal_row_shape:"),
        ("impossible_outcome", "replay_journal_outcome:"),
        ("unknown_kind", "replay_journal_kind:"),
        ("recorded_extra", "replay_journal_recorded:"),
        ("provider_shape", "replay_journal_provider:"),
        ("unpinned_plugin", "replay_journal_plugin_unpinned:"),
    ],
)
def test_journal_faults_refuse_typed(
    tmp_path: Path, plugin, fault: str, expected: str
) -> None:
    journal = _acceptance_journal()
    if fault == "version":
        journal["journal_version"] = "2"
    elif fault == "not_json":
        path = tmp_path / "journal.json"
        path.write_text("{not json")
        with pytest.raises(ValueError, match=expected):
            load_replay_journal(path, plugin)
        return
    elif fault == "no_rows":
        journal["rows"] = []
    elif fault == "duplicate_names":
        journal["rows"][4]["name"] = journal["rows"][5]["name"]
    elif fault == "bad_hex":
        journal["rows"][4]["transaction"]["data"] = "zz"
    elif fault == "impossible_outcome":
        journal["rows"][7]["response"] = {"data": "c2"}  # exact_bytes 4, one byte
    elif fault == "unknown_kind":
        journal["rows"][4]["transaction"] = {"kind": "spi_transfer"}
    elif fault == "recorded_extra":
        journal["recorded"]["operator"] = "typo field"
    elif fault == "provider_shape":
        journal["provider"]["vendor"] = "extra"
    elif fault == "unpinned_plugin":
        other = load_plugin_project(FIXTURE_ROOT)
        del other.descriptor["transport"]["provider"]  # type: ignore[index]
        with pytest.raises(ValueError, match=expected):
            load_replay_journal(_write(tmp_path, journal), other)
        return
    with pytest.raises(ValueError, match=expected):
        load_replay_journal(_write(tmp_path, journal), plugin)


def test_recorded_single_owner_is_carried_as_evidence(tmp_path: Path, plugin) -> None:
    parsed = load_replay_journal(_write(tmp_path, _acceptance_journal()), plugin)
    assert parsed.recorded["single_owner"] is True
    journal = _acceptance_journal()
    journal["recorded"].pop("single_owner")
    parsed = load_replay_journal(_write(tmp_path, journal, "noso.json"), plugin)
    assert "single_owner" not in parsed.recorded  # absent means not stated
    journal["recorded"]["single_owner"] = "yes"
    with pytest.raises(ValueError, match="replay_journal_recorded:"):
        load_replay_journal(_write(tmp_path, journal, "badsso.json"), plugin)


def test_incoming_provider_transaction_validated_against_admitted_grammar(
    tmp_path: Path, plugin
) -> None:
    """A provider transaction the admitted grammar refuses is a typed
    refusal BEFORE any state change (transport-providers §3: the grammar,
    never the generic table)."""
    from benchweave_sdk.testing import MockContext

    host = ReplayHost(load_replay_journal(_write(tmp_path, _acceptance_journal()), plugin))
    context = MockContext("op-g", deadline_monotonic=host.monotonic() + 5)
    context.dispatched = True
    with pytest.raises(ValueError, match="replay_transaction_grammar:"):
        asyncio.run(
            host.transfer(
                {"kind": "hid_output_report", "report_id": 1, "data": b"x",
                 "extra": 1},
                context,
            )
        )


# --------------------------------------------------------------------------
# CLI wiring (one flag one meaning; fail-fast before any port binds)
# --------------------------------------------------------------------------


def test_serve_replay_without_journal_refuses(tmp_path: Path) -> None:
    from benchweave_sdk_server.cli import cli

    result = CliRunner().invoke(
        cli, ["serve", str(FIXTURE_ROOT), "--transport", "replay", "--no-open"]
    )
    assert result.exit_code == 2
    assert "standalone_transport_replay_journal:" in result.output


def test_serve_replay_flag_on_other_transports_refuses(tmp_path: Path) -> None:
    from benchweave_sdk_server.cli import cli

    result = CliRunner().invoke(
        cli,
        ["serve", str(FIXTURE_ROOT), "--transport", "mock",
         "--replay", str(_write(tmp_path, _acceptance_journal())), "--no-open"],
    )
    assert result.exit_code == 2
    assert "standalone_transport_replay_flag:" in result.output


def test_serve_replay_with_bad_journal_exits_two(tmp_path: Path) -> None:
    from benchweave_sdk_server.cli import cli

    journal = _acceptance_journal()
    journal["provider"]["sha256"] = "c" * 64
    result = CliRunner().invoke(
        cli,
        ["serve", str(FIXTURE_ROOT), "--transport", "replay",
         "--replay", str(_write(tmp_path, journal)), "--no-open"],
    )
    assert result.exit_code == 2
    assert "replay_journal_provider_mismatch:" in result.output


# --------------------------------------------------------------------------
# The refute fold (the wave over 580dab6, issue #564): five findings, RED-first
# --------------------------------------------------------------------------


def _dispatched_context(host: ReplayHost, operation_id: str = "op-fold") -> Any:
    """A live, dispatched MockContext on the host's own clock."""
    from benchweave_sdk.testing import MockContext

    context = MockContext(
        operation_id, deadline_monotonic=host.monotonic() + 5
    )
    context.dispatched = True
    return context


def test_f1_receive_path_never_restores_the_cycle(tmp_path: Path, plugin) -> None:
    """F1 (blocker): the cycle restores on a COMMAND, never on a receive —
    mock parity. After a full drain, one extra receive must leave the
    exhaustion certificate issuable; today it silently restores the unit
    and breaks assert_complete."""
    path = _write(tmp_path, _journal(_read_rows(3)))
    host = ReplayHost(load_replay_journal(path, plugin))
    context = _dispatched_context(host)
    asyncio.run(session_consume(host, plugin))
    assert (host.pending, host.plays) == (0, 1)
    receive = {"kind": "stream_receive", "max_bytes": 8,
               "termination": "lf", "exact_bytes": None}
    assert asyncio.run(host.transfer(receive, context)) == {"data": b""}
    assert (host.pending, host.plays) == (0, 1)
    host.assert_complete()


def test_f1_truncated_recording_serves_no_reply_without_its_poll(
    tmp_path: Path, plugin
) -> None:
    """F1's honesty arm: a recording cut before its status reply must answer
    the status receive with the quiet line — the NEXT cycle's recorded reply
    is a conversation the recording never showed. Two full units plus the
    truncated third is the shape that derives the cycle (the rotate lands on
    the status row), so this is the recording where the receive-path restore
    fabricated the reply."""
    rows = _establishment_rows() + _read_rows(2) + _read_rows(1, start=2)[:3]
    path = _write(tmp_path, _journal(rows))
    session = replay_plugin_session(plugin, path)
    asyncio.run(session.connect())
    for _ in range(2):  # the two complete recorded reads
        _read_once(session)
    host = session.services
    assert isinstance(host, ReplayHost)
    context = _dispatched_context(host)
    # The truncated second read: resync, drain, poll — then the status
    # receive the recording never recorded.
    asyncio.run(
        host.transfer({"kind": "stream_send", "data": bytes.fromhex(_RESYNC_HEX)}, context)
    )
    asyncio.run(
        host.transfer({"kind": "stream_receive", "max_bytes": 8,
                       "termination": "lf", "exact_bytes": None}, context)
    )
    asyncio.run(
        host.transfer({"kind": "stream_send", "data": bytes.fromhex(_POLL_HEX)}, context)
    )
    status = asyncio.run(
        host.transfer({"kind": "stream_receive", "max_bytes": 8,
                       "termination": "lf", "exact_bytes": 4}, context)
    )
    assert status == {"data": b""}  # the quiet line, not the restored reply
    assert host.plays == 1


def test_f2_replay_flag_on_serial_refuses_never_serves_live(
    tmp_path: Path,
) -> None:
    """F2 (blocker): ``--transport serial --replay <journal>`` silently
    ignored the journal and served LIVE hardware. A flag disagreement must
    refuse, never resolve toward the live device."""
    journal = _write(tmp_path, _acceptance_journal())
    with pytest.raises(SystemExit) as caught:
        _build_seam(
            FIXTURE_ROOT,
            transport="serial",
            replay=journal,
            bindings=tmp_path / "bindings.json",  # the store never writes here
        )
    assert caught.value.code == 2


def test_f2_bindings_and_device_refuse_on_replay(tmp_path: Path) -> None:
    """F2's other two dead guards: ``--bindings`` and ``--device`` were
    silently ignored on the replay transport (the replay branch returned
    before both guards)."""
    journal = _write(tmp_path, _acceptance_journal())
    with pytest.raises(SystemExit) as bindings_refusal:
        _build_seam(FIXTURE_ROOT, transport="replay", replay=journal,
                    bindings=tmp_path / "b.json")
    assert bindings_refusal.value.code == 2
    with pytest.raises(SystemExit) as device_refusal:
        _build_seam(FIXTURE_ROOT, transport="replay", replay=journal,
                    device="/dev/nope")
    assert device_refusal.value.code == 2


#: The canonical FTDI contract instance, served from the providers directory
#: — the fold builds a THROWAWAY plugin pinning it so the read_pins result
#: schema is exercised at journal load, its real enforcement surface.
_FTDI_CONTRACT = (
    Path(__file__).resolve().parents[2]
    / "src" / "benchweave_sdk" / "providers" / "ftdi-control-1.0.0.json"
)

_FTDI_DESCRIPTOR = {
    "otdp_version": "0.2.4",
    "descriptor_version": "1.0.0",
    "id": "dev.local.ftdi-fold",
    "display_name": "Fold fixture ftdi pin",
    "description": "Synthetic fold-wave fixture pinning the canonical FTDI contract copy.",
    "identity": {
        "strategy": "adapter",
        "manufacturer": "BenchWeave Labs",
        "model": "ftdi-fold",
        "firmware_policy": "listed",
        "supported_firmware": ["1.0"],
    },
    "integration": {
        "mode": "adapter",
        "adapter": {
            "entry_point": "ftdi_fold.adapter:create_plugin",
            "api_version": "1.1",
            "version": "0.1.0",
            "dependencies": [],
            "permissions": ["scoped_transport"],
        },
    },
    "transport": {
        "type": "custom",
        "connection_key": "ftdi_fold",
        "settings": {"protocol_reference": "The pinned canonical FTDI contract"},
        "provider": {
            "feature_id": "otdp.transport.ftdi-control/1.0.0",
            "id": "urn:otdp:transport-provider:ftdi-control:1.0.0",
            "path": "ftdi-control-1.0.0.json",
            "sha256": "",  # stamped from the canonical bytes below
        },
    },
    "capabilities": ["identify"],
    "operations": {
        "identify": {
            "timeout_ms": 2000,
            "side_effect": "none",
            "retry": "never",
            "cancellable": False,
            "completion": "acknowledged",
        }
    },
    "parameters": [],
    "required_features": [
        "otdp.core/0.1.0",
        "otdp.adapter/0.1.0",
        "otdp.transport.ftdi-control/1.0.0",
    ],
    "provenance": {
        "sources": [
            {
                "title": "Canonical FTDI control contract",
                "reference": "ftdi-control-1.0.0.json",
                "revision": "1.0.0",
            }
        ],
        "test_vectors": [
            {
                "id": "fold-journals",
                "path": "ftdi-control-1.0.0.json",
                "purpose": "The fold-wave journals are spelled in the suite",
            }
        ],
    },
}

_FTDI_ADAPTER = '''\
# author: Stephen Eaton
"""Minimal fold fixture adapter: one read_pins transaction, no more."""


def create_plugin():
    return Plugin()


class Plugin:
    def __init__(self):
        self.services = None
        self.closed = False

    async def open(self, descriptor, services, context):
        self.services = services

    async def execute(self, request, context):
        await context.mark_dispatch_started()
        reply = await self.services.transfer(
            {"kind": "ftdi_control", "op": "read_pins"}, context
        )
        return {"operation_id": request["operation_id"], "verb": "identify",
                "status": "ok", "data": {"pins": reply["data"].hex()}}

    async def next_event(self, subscription_id, context):
        return None

    async def close(self, context):
        if self.closed:
            return
        self.closed = True
        if self.services is not None:
            await self.services.close_transport(context)
'''


def _ftdi_project(tmp: Path) -> Path:
    """A throwaway plugin project pinning the CANONICAL contract bytes."""
    package = tmp / "src" / "ftdi_fold"
    package.mkdir(parents=True)
    contract = _FTDI_CONTRACT.read_bytes()
    (package / "ftdi-control-1.0.0.json").write_bytes(contract)
    (package / "adapter.py").write_text(_FTDI_ADAPTER)
    (package / "__init__.py").write_text("")
    import copy as _copy

    descriptor = _copy.deepcopy(_FTDI_DESCRIPTOR)
    import hashlib as _hashlib

    descriptor["transport"]["provider"]["sha256"] = _hashlib.sha256(contract).hexdigest()
    (package / "descriptor.json").write_text(json.dumps(descriptor, indent=2) + "\n")
    return tmp


def _ftdi_journal(pins_b64: str) -> dict[str, Any]:
    contract = json.loads(_FTDI_CONTRACT.read_text())
    import hashlib as _hashlib

    return _journal(
        [
            {"name": "pin-1",
             "transaction": {"kind": "ftdi_control", "op": "read_pins"},
             "response": {"data": pins_b64}},
        ],
        provider_overrides={
            "feature_id": contract["feature_id"],
            "id": contract["id"],
            "sha256": _hashlib.sha256(_FTDI_CONTRACT.read_bytes()).hexdigest(),
        },
    )


def test_f3_read_pins_result_admits_exactly_one_byte(tmp_path: Path) -> None:
    """F3: the contract SAID one byte but admitted unpadded four-character
    base64 — three bytes ("QUJD" is b"ABC"). The result schema is the
    enforcement surface at journal load: a three-byte read_pins must refuse
    there, and a one-byte read_pins must load and serve."""
    project = _ftdi_project(tmp_path)
    plugin = load_plugin_project(project)
    # RED today: this load succeeds and the three-byte pin serves.
    with pytest.raises(ValueError, match="replay_journal_row_shape:"):
        load_replay_journal(_write(tmp_path, _ftdi_journal("QUJD")), plugin)
    # The admitted direction: exactly one byte ("Wg==" is b"Z").
    host = ReplayHost(
        load_replay_journal(_write(tmp_path, _ftdi_journal("Wg=="), "one.json"), plugin)
    )
    context = _dispatched_context(host)
    reply = asyncio.run(
        host.transfer({"kind": "ftdi_control", "op": "read_pins"}, context)
    )
    assert reply == {"data": b"Z"}
    host.assert_complete()


def test_f4_directory_replay_argument_refuses_typed(tmp_path: Path) -> None:
    """F4: ``--replay <directory>`` crashed with an uncaught
    IsADirectoryError (exit 1, empty message). The surface owes a typed
    replay_journal_* refusal at exit 2."""
    from benchweave_sdk_server.cli import cli

    result = CliRunner().invoke(
        cli,
        ["serve", str(FIXTURE_ROOT), "--transport", "replay",
         "--replay", str(tmp_path), "--no-open"],
    )
    assert result.exit_code == 2
    assert "replay_journal_" in result.output


def test_nit2_stream_kinds_match_their_recorded_kind(tmp_path: Path, plugin) -> None:
    """NIT2, tightened rather than inherited: the byte-stream mock is
    kind-blind by FrameRow design (its rows carry no kind), but a replay
    row IS the recorded transaction — a stream_send must not consume a
    recorded stream_exchange row however well the bytes match."""
    journal = _journal([
        {"name": "exchange-1",
         "transaction": {"kind": "stream_exchange", "data": _RESYNC_HEX,
                         "max_bytes": 8, "termination": "lf", "exact_bytes": 4},
         "response": {"data": _STATUS_HEX}},
    ])
    host = ReplayHost(load_replay_journal(_write(tmp_path, journal), plugin))
    context = _dispatched_context(host)
    with pytest.raises(ConformanceError, match="row exchange-1"):
        asyncio.run(
            host.transfer({"kind": "stream_send",
                           "data": bytes.fromhex(_RESYNC_HEX)}, context)
        )
    # The recorded kind still matches its own transaction shape.
    reply = asyncio.run(
        host.transfer(
            {"kind": "stream_exchange", "data": bytes.fromhex(_RESYNC_HEX),
             "max_bytes": 8, "termination": "lf", "exact_bytes": 4},
            context,
        )
    )
    assert reply == {"data": bytes.fromhex(_STATUS_HEX)}
    host.assert_complete()


def test_a_row_with_a_failure_and_a_response_is_refused(tmp_path: Path, plugin) -> None:
    """The delta refute's residual 3: a row carrying BOTH a
    ``recorded_failure`` and a response used to load and silently discard
    the response (the decode is gated on ``failure is None``) while the
    loader rejects three neighbouring contradictions. Recorded evidence
    never vanishes without a diagnostic."""
    journal = _journal([
        {"name": "poll-1",
         "transaction": {"kind": "stream_send", "data": _POLL_HEX},
         "response": {}},
        {"name": "both",
         "transaction": {"kind": "stream_receive", "max_bytes": 4,
                         "termination": "lf", "exact_bytes": None},
         "recorded_failure": "timeout",
         "response": {"data": "55a10d"}},
    ])
    path = _write(tmp_path, journal)
    with pytest.raises(ValueError, match="replay_journal_row_shape:"):
        load_replay_journal(path, plugin)
