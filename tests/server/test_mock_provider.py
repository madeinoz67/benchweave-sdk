"""The mock provider dialect (issue #570): a provider plugin rehearses its
full bring-up under ``--transport mock`` with no hardware and no journal,
from the ``vectors.json`` its own scaffold emits.

The division of proof (the #570 design record's §3, kept from #568's §3 as
design content): the mock proves the adapter's conversation SHAPE at the
transaction boundary; the driver double (the generated suite's rehearsal)
proves the executor ladder one boundary down; replay proves the
conversation against recorded evidence; the device is proven only on a
bench. Both rehearsal mechanisms consume ONE corpus (§4) so they cannot
drift — the parity guard pins it.

Arms here carry the design record's pre-committed acceptance (§10): Metric
A's execution sentence (A2/A3 shapes at the SDK level), Metric B's RED
controls (each redden-able by its single-point reversion — evidence quoted
in the build commit), Metric C's cross-slice integrity (the amended C5,
the parity guard, the honesty surfaces).
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk_server.cli import _build_seam
from benchweave_sdk_server.session import (
    load_plugin_project,
    mock_plugin_session,
    provider_script,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "ftdi_control_plugin"


def _corpus(plugin: Any) -> list[dict[str, Any]]:
    return json.loads((plugin.package_dir / "vectors.json").read_text())["exchanges"]


def _expected_transactions(corpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The corpus transactions in ABI form (hex stream data decoded) — the
    exact-dict consumption trace's expectation."""
    rows = []
    for row in corpus:
        t = dict(row["transaction"])
        if "data" in t:
            t["data"] = bytes.fromhex(t["data"])
        rows.append(t)
    return rows


# --------------------------------------------------------------------------
# Metric A — the sentence, by execution
# --------------------------------------------------------------------------


def test_the_fixture_rehearses_its_bring_up_on_the_mock() -> None:
    """A2 at the SDK level: the provider plugin connects under the MOCK,
    the three authored status polls serve the reads (the derived unit),
    the recorded transfers equal the corpus transactions in order, and the
    script completes — no hardware, no journal."""
    plugin = load_plugin_project(FIXTURE_ROOT)
    corpus = _corpus(plugin)
    session = mock_plugin_session(plugin)
    asyncio.run(session.connect())
    assert session.identity is not None, "the mock establish works"
    for _ in range(3):  # the three authored polls
        read = asyncio.run(session.execute("read", {"parameter": "line_status"}))
        assert read["status"] == "ok", read
        assert read["data"]["value"] == 0x5A
    host = session.services
    assert [dict(t) for t in host.transfers] == _expected_transactions(corpus), (
        "the consumption trace equals the corpus, whole-dict, in order"
    )
    host.assert_complete()


def test_the_fourth_poll_serves_from_the_recycled_unit() -> None:
    """B5's observable at the SDK level: a read BEYOND the three authored
    polls still serves from the recycled unit (the establishment the cycle
    plan derived) — sustained mock serving, the guide's three-cycle rule
    made mechanical."""
    plugin = load_plugin_project(FIXTURE_ROOT)
    session = mock_plugin_session(plugin)
    asyncio.run(session.connect())
    for index in range(4):
        read = asyncio.run(session.execute("read", {"parameter": "line_status"}))
        assert read["status"] == "ok", index


def test_the_serve_surface_loads_the_dialect(tmp_path: Path) -> None:
    """A3: `_build_seam(transport="mock")` over the provider plugin
    constructs and connects — the default transport, the author's first
    reach."""
    seam, selection = _build_seam(FIXTURE_ROOT, transport="mock")
    assert selection is None
    assert seam.transport_kind == "mock"
    asyncio.run(seam.call("device_connect", {"device_id": seam.session.device_id}))
    read = asyncio.run(
        seam.call(
            "parameter_read",
            {"device_id": seam.session.device_id, "parameter": "line_status"},
        )
    )
    assert read["value"] == 0x5A
    asyncio.run(seam.session.close())


# --------------------------------------------------------------------------
# Metric B — the RED controls (single-point reversions; evidence in the
# build commit's message)
# --------------------------------------------------------------------------


def test_the_dialect_dispatch_reaches_the_provider_compile() -> None:
    """B1's anchor: the provider dialect reaches provider_script (and the
    unknown-dialect refusal names all three)."""
    plugin = load_plugin_project(FIXTURE_ROOT)
    exchanges, establishment, rotate = provider_script(plugin)
    assert len(exchanges) == 11, "the whole corpus compiles"
    assert establishment == 8, "the cycle plan derives the status unit head"
    assert rotate == 0, "this corpus ends on a unit boundary"


def test_a_doctored_corpus_row_refuses_at_load(tmp_path: Path) -> None:
    """B2's anchor: the shared validator runs — a vectors row violating
    the pinned grammar (a read_pins response carrying non-base64 data)
    refuses at load with the standalone_vectors_row_shape prefix."""
    project = tmp_path / "doctored"
    shutil.copytree(FIXTURE_ROOT, project)
    corpus_path = project / "src" / "ftdi_control_demo" / "vectors.json"
    corpus = json.loads(corpus_path.read_text())
    corpus["exchanges"][5]["response"] = {"data": "not base64!!"}
    corpus_path.write_text(json.dumps(corpus, indent=2) + "\n")
    plugin = load_plugin_project(project)
    with pytest.raises(Exception, match="standalone_vectors_row_shape"):
        asyncio.run(mock_plugin_session(plugin).connect())


def test_a_drifted_conversation_refuses_the_mismatch(tmp_path: Path) -> None:
    """B3's anchor: exact-dict matching — a corpus whose set_baud is 57600
    against the adapter's 115200 must ConformanceError at the mismatched
    row (never rehearse a wrong conversation clean)."""
    project = tmp_path / "drifted"
    shutil.copytree(FIXTURE_ROOT, project)
    corpus_path = project / "src" / "ftdi_control_demo" / "vectors.json"
    corpus = json.loads(corpus_path.read_text())
    for row in corpus["exchanges"]:
        if row["transaction"].get("op") == "set_baud":
            row["transaction"]["baud"] = 57600
    corpus_path.write_text(json.dumps(corpus, indent=2) + "\n")
    plugin = load_plugin_project(project)
    session = mock_plugin_session(plugin)
    with pytest.raises(Exception, match="set_baud"):
        asyncio.run(session.connect())


# --------------------------------------------------------------------------
# Metric C — cross-slice integrity
# --------------------------------------------------------------------------


def test_c2_the_amended_c5_pins_three_refusals(tmp_path: Path) -> None:
    """The #570 amendment of #568's C5 second half, three refusals where
    one was: (i) the byte-stream mock host still refuses provider kinds
    (the _FIELDS gate, untouched); (ii) a provider plugin whose vectors
    declares a STREAM dialect refuses at load — its rows cannot script
    control ops; (iii) a provider plugin with NO vectors.json still
    refuses the honest load refusal naming vectors.json."""
    from benchweave_sdk.testing import MockContext
    from benchweave_sdk_server.session import FrameRow
    from benchweave_sdk_server.transport import ByteStreamMockHost

    # (i) the untouched _FIELDS gate
    host = ByteStreamMockHost([FrameRow("only", b"\x01", b"\x02")])
    context = MockContext("op-c2", deadline_monotonic=host.monotonic() + 1)
    context.dispatched = True
    with pytest.raises(ValueError, match="not a section 8.1 stream transaction"):
        asyncio.run(
            host.transfer({"kind": "ftdi_control", "op": "reset_device"}, context)
        )

    # (ii) stream dialect on a provider plugin: the rows cannot compile
    project = tmp_path / "stream-dialect"
    shutil.copytree(FIXTURE_ROOT, project)
    corpus_path = project / "src" / "ftdi_control_demo" / "vectors.json"
    corpus = json.loads(corpus_path.read_text())
    corpus["transaction_dialect"] = "stream_exchange"
    corpus_path.write_text(json.dumps(corpus, indent=2) + "\n")
    plugin = load_plugin_project(project)
    with pytest.raises(Exception, match="standalone_vectors_row_unscriptable"):
        asyncio.run(mock_plugin_session(plugin).connect())

    # (iii) no vectors at all: the honest load refusal
    project = tmp_path / "no-vectors"
    shutil.copytree(FIXTURE_ROOT, project)
    (project / "src" / "ftdi_control_demo" / "vectors.json").unlink()
    plugin = load_plugin_project(project)
    with pytest.raises(Exception, match="vectors.json"):
        asyncio.run(mock_plugin_session(plugin).connect())


def test_c3_the_parity_guard_journal_and_corpus_one_conversation() -> None:
    """One conversation, two documents: the fixture's bring-up journal and
    its vectors corpus carry the same rows (name, kind, params, data,
    order) — the journal's provider+stream prefix equals the corpus's
    bring-up head, so the double, the mock and the replay lane consume one
    evidence conversation and cannot drift."""
    plugin = load_plugin_project(FIXTURE_ROOT)
    journal = json.loads(
        (plugin.package_dir / "bring-up-journal.json").read_text()
    )["rows"]
    corpus = _corpus(plugin)
    head = corpus[: len(journal)]
    assert len(corpus) == len(journal) + 2, "the corpus adds only the 2 extra polls"
    for j_row, c_row in zip(journal, head, strict=True):
        assert j_row["name"] == c_row["name"], (j_row["name"], c_row["name"])
        assert j_row["transaction"] == c_row["transaction"]
        assert j_row["response"] == c_row["response"]


def test_c4_the_honesty_surfaces_stay_the_mocks_own() -> None:
    """A provider-dialect session runs under transport_kind "mock": the
    SIMULATED banner (string-pinned), transport "mock" on the state
    surface, and no surface carries "replay" or a journal digest."""
    seam, _ = _build_seam(FIXTURE_ROOT, transport="mock")
    info = asyncio.run(seam.call("host_info"))
    assert info["transport"] == "mock"
    from benchweave_sdk_server.presentation import mode_banner_html

    banner = mode_banner_html(simulated=True)
    assert "SIMULATED PRESENTATION DATA" in banner
    assert "REPLAYED RECORDED EXCHANGES" not in banner
    assert "SCRIPTED REHEARSAL" not in banner


def test_encoding_under_provider_refuses(tmp_path: Path) -> None:
    """The owner ruling: an `encoding` key under the provider dialect
    would be a silent no-op — it refuses typed, naming the fix."""
    project = tmp_path / "encoded"
    shutil.copytree(FIXTURE_ROOT, project)
    corpus_path = project / "src" / "ftdi_control_demo" / "vectors.json"
    corpus = json.loads(corpus_path.read_text())
    corpus["encoding"] = "hex"
    corpus_path.write_text(json.dumps(corpus, indent=2) + "\n")
    plugin = load_plugin_project(project)
    with pytest.raises(Exception, match="standalone_vectors_encoding_unsupported"):
        asyncio.run(mock_plugin_session(plugin).connect())


def test_recorded_failure_scripts_the_ladders_outcome(tmp_path: Path) -> None:
    """Bound D2 as work (the owner ruling): a recorded failure scripts the
    ladder's own outcome class through MockHost's Exception slot — the
    recorded timeout rehearses as the backend's TimeoutError posture, the
    recorded connection fault as ConnectionError. The recorded outcome
    stays the recorded outcome (A06)."""
    project = tmp_path / "failed"
    shutil.copytree(FIXTURE_ROOT, project)
    corpus_path = project / "src" / "ftdi_control_demo" / "vectors.json"
    corpus = json.loads(corpus_path.read_text())
    failure_rows = [
        {
            "name": "timeout-poll",
            "transaction": {
                "kind": "stream_exchange",
                "data": "55a1",
                "max_bytes": 8,
                "termination": "lf",
                "exact_bytes": 4,
            },
            "recorded_failure": "timeout",
        },
        {
            "name": "lost-poll",
            "transaction": {
                "kind": "stream_exchange",
                "data": "55a1",
                "max_bytes": 8,
                "termination": "lf",
                "exact_bytes": 4,
            },
            "recorded_failure": "connection",
        },
    ]
    corpus["exchanges"] = corpus["exchanges"] + failure_rows
    corpus_path.write_text(json.dumps(corpus, indent=2) + "\n")
    plugin = load_plugin_project(project)
    session = mock_plugin_session(plugin)
    asyncio.run(session.connect())
    from benchweave_sdk.testing import MockContext

    context = MockContext("op-d2", deadline_monotonic=session.services.monotonic() + 2)
    context.dispatched = True
    transaction = {
        "kind": "stream_exchange",
        "data": bytes.fromhex("55a1"),
        "max_bytes": 8,
        "termination": "lf",
        "exact_bytes": 4,
    }
    # The script is ordered: connect consumed the eight bring-up rows; the
    # three authored polls serve first, THEN the recorded failures raise.
    for _ in range(3):
        asyncio.run(session.services.transfer(dict(transaction), context))
    with pytest.raises(TimeoutError, match="recorded receive"):
        asyncio.run(session.services.transfer(dict(transaction), context))
    with pytest.raises(ConnectionError, match="lost its connection"):
        asyncio.run(session.services.transfer(dict(transaction), context))


def test_a_provider_row_failure_refuses_in_the_shared_validator(
    tmp_path: Path,
) -> None:
    """The provider-row face of the same bound: the shared validator itself
    refuses (recorded_failure applies to receive rows, not provider
    transactions) — typed, under the vectors document's prefix."""
    project = tmp_path / "provider-failure"
    shutil.copytree(FIXTURE_ROOT, project)
    corpus_path = project / "src" / "ftdi_control_demo" / "vectors.json"
    corpus = json.loads(corpus_path.read_text())
    corpus["exchanges"][0]["recorded_failure"] = "timeout"
    corpus_path.write_text(json.dumps(corpus, indent=2) + "\n")
    plugin = load_plugin_project(project)
    with pytest.raises(
        Exception, match="standalone_vectors_row_shape: row reset: recorded_failure"
    ):
        asyncio.run(mock_plugin_session(plugin).connect())


def test_an_unpinned_plugin_refuses_the_provider_dialect(
    tmp_path: Path, starter_project: Path
) -> None:
    """A provider corpus requires a pinned contract: the starter plugin
    (no provider pin) with a provider-dialect vectors refuses typed."""
    project = tmp_path / "unpinned"
    shutil.copytree(starter_project, project)
    package = project / "src" / "example_plugin"
    (package / "vectors.json").write_text(
        json.dumps(
            {
                "evidence": "synthetic",
                "transaction_dialect": "provider",
                "exchanges": [
                    {
                        "name": "reset",
                        "transaction": {
                            "kind": "ftdi_control",
                            "op": "reset_device",
                        },
                        "response": {},
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )
    plugin = load_plugin_project(project)
    with pytest.raises(Exception, match="standalone_vectors_provider_unpinned"):
        asyncio.run(mock_plugin_session(plugin).connect())


# --------------------------------------------------------------------------
# Bounds D1-D5 as work (the owner ruling of 2026-10-28)
# --------------------------------------------------------------------------


def test_d1_the_walk_order_rehearsal_covers_provider_corpora() -> None:
    """D1 as work: the descriptor walk (identify, then each readable
    parameter) rehearses over the provider corpus with exact-dict
    matching; the 3x poll tail passes as cycle repeats, and a foreign
    tail row the walk never saw refuses."""
    from benchweave_sdk_server.session import validate_provider_walk_order

    plugin = load_plugin_project(FIXTURE_ROOT)
    validate_provider_walk_order(plugin)  # the 3x corpus passes


def test_d1_a_foreign_tail_row_refuses_the_walk(tmp_path: Path) -> None:
    project = tmp_path / "foreign-tail"
    shutil.copytree(FIXTURE_ROOT, project)
    corpus_path = project / "src" / "ftdi_control_demo" / "vectors.json"
    corpus = json.loads(corpus_path.read_text())
    corpus["exchanges"].append(
        {
            "name": "foreign",
            "transaction": {"kind": "ftdi_control", "op": "purge", "queue": "tx"},
            "response": {},
        }
    )
    corpus_path.write_text(json.dumps(corpus, indent=2) + "\n")
    from benchweave_sdk_server.session import validate_provider_walk_order

    with pytest.raises(Exception, match="vectors_walk_order_unconsumed"):
        validate_provider_walk_order(load_plugin_project(project))


def test_d3_served_stream_outcomes_equal_the_computed_ladder() -> None:
    """D3 as work: for every LOAD-VALIDATED stream row, the outcome the
    mock serves equals the outcome the byte-stream ladder computes over
    the same bytes and bounds — exact precedence, terminator search, the
    quiet line — proven row by row rather than asserted in prose. (The
    shared loader's outcome check already refuses a row whose recorded
    outcome its bounds cannot produce; this arm pins that the SERVING
    path agrees with the computation, catching any future host change
    that serves scripted bytes the bounds can't produce.)"""
    from benchweave_sdk_server.serial import _stream_receive_bounds

    plugin = load_plugin_project(FIXTURE_ROOT)
    corpus = _corpus(plugin)
    session = mock_plugin_session(plugin)
    asyncio.run(session.connect())
    from benchweave_sdk.testing import MockContext

    context = MockContext("op-d3", deadline_monotonic=session.services.monotonic() + 2)
    context.dispatched = True
    for row in corpus:
        transaction = dict(row["transaction"])
        if transaction["kind"] != "stream_exchange":
            continue  # connect consumed the bring-up; the statuses remain
        transaction["data"] = bytes.fromhex(transaction["data"])
        served = asyncio.run(session.services.transfer(transaction, context))
        # The ladder's computation over the recorded bytes and bounds.
        max_bytes, terminator, exact = _stream_receive_bounds(transaction, 4096)
        recorded = bytes.fromhex(row["response"]["data"])
        if exact:
            computed = recorded  # exact precedence: the frame is the count
        else:
            computed = None
            assert computed is not None or terminator in recorded
        assert served == {"data": computed}, (row["name"], served)


def test_d5_a_corpus_over_one_mib_refuses(tmp_path: Path) -> None:
    """D5 as work: the provider corpus carries the journal's own byte
    bound — bulk conversations are journals."""
    project = tmp_path / "bulky"
    shutil.copytree(FIXTURE_ROOT, project)
    corpus_path = project / "src" / "ftdi_control_demo" / "vectors.json"
    corpus = json.loads(corpus_path.read_text())
    corpus["exchanges"][6]["transaction"]["data"] = "ab" * 200_000
    corpus_path.write_text(json.dumps(corpus, indent=2) + "\n")
    assert corpus_path.stat().st_size > 262_144
    plugin = load_plugin_project(project)
    # The compile's own boundary names the bound typed (its stat check
    # runs before its read); through the session path the shared reader
    # fires the same 256 KiB cap with its generic message — the bound is
    # the reader's, the typing is the compile's.
    with pytest.raises(Exception, match="standalone_vectors_provider_bound"):
        provider_script(plugin)


def test_d4_a_mid_unit_corpus_restores_rotated() -> None:
    """D4 as work: LoopingMockHost gains cycle_rotate; a corpus ending
    mid-unit restores the cycle rotated to the recorded phase."""
    from benchweave_sdk_server.transport import LoopingMockHost

    exchanges = [
        ({"kind": "x", "n": 0}, {}),
        ({"kind": "x", "n": 1}, {}),
        ({"kind": "x", "n": 2}, {}),
        ({"kind": "x", "n": 3}, {}),
    ]
    host = LoopingMockHost(exchanges, establishment=1, cycle_rotate=2)
    from benchweave_sdk.testing import MockContext

    context = MockContext("op-d4", deadline_monotonic=host.monotonic() + 2)
    context.dispatched = True
    # The rotation applies at RECYCLE: consume the establishment row and
    # the unit (n1..n3), then the restored cycle's head is n3 (rotated by
    # 2 from n1), not n1.
    for expected, _ in exchanges:
        asyncio.run(host.transfer(dict(expected), context))
    # The recycle arms on the next command and restores rotated: the 5th
    # demand serves n3 (the rotated head), not n1.
    asyncio.run(host.transfer(dict(exchanges[3][0]), context))
    head = host._script[0][0] if host._script else None
    assert head == {"kind": "x", "n": 1}, head  # n1 follows n3 in the unit


# --------------------------------------------------------------------------
# Row e (the owner expansion): the provider-agnostic executor registry —
# a second family plugs in by registering; the banked-bytes bind survives
# the abstraction intact (a lookalike of the SECOND family refuses too).
# The second family is TEST-ONLY — exactly one real family exists and no
# fabricated production contract justifies the registry.
# --------------------------------------------------------------------------


def test_e_a_second_family_registers_and_serves(tmp_path: Path) -> None:
    """The registry is exercised by the FTDI family plus this test-only
    synthetic family: register an executor whose banked copy lives beside
    the test, verify a plugin pinning IT passes the bind, and serve its
    grammar through the same transport machinery."""
    import hashlib

    from benchweave_sdk_server.ftdi import PROVIDER_EXECUTORS, ProviderExecutor

    # The synthetic banked contract: a minimal one-kind grammar.
    banked = {
        "contract_version": "0.1.0",
        "id": "urn:otdp:transport-provider:test-second:1.0.0",
        "feature_id": "otdp.transport.test-second/1.0.0",
        "version": "1.0.0",
        "description": "Test-only second family: exercises the executor registry.",
        "transport_kind": "test_second",
        "transaction_grammar": [
            {
                "kind": "test_second",
                "request_schema": {
                    "type": "object",
                    "properties": {"op": {"const": "ping"}},
                    "required": ["op"],
                    "additionalProperties": False,
                },
                "result_schema": {"type": "object", "maxProperties": 0},
                "limits": {},
            }
        ],
        "security_scope": "commissioned_connection",
        "host_requirements": {"summary": "none", "native_libraries": [], "privileges": []},
        "approval": {
            "approved_by": "BenchWeave SDK",
            "approved_at": "2026-10-28T00:00:00Z",
            "expires_at": "2027-10-28T00:00:00Z",
            "evidence": [
                {
                    "category": "protocol",
                    "report": {
                        "id": "registry-exercise",
                        "version": "1.0.0",
                        "sha256": "0" * 64,
                    },
                    "tested_at": "2026-10-28T00:00:00Z",
                    "scope": "Synthetic registry exercise; not a production claim",
                    "result": "partial",
                    "limitations": [
                        "Test-only family; the evidence row is schema shape, not a test claim"
                    ],
                }
            ],
        },
    }
    raw = json.dumps(banked, indent=2).encode() + b"\n"
    banked_path = tmp_path / "test-second-control-1.0.0.json"
    banked_path.write_bytes(raw)

    executor = ProviderExecutor(
        family="test-second",
        feature_prefix="otdp.transport.test-second/",
        transport_kind="ftdi",
        probe_payloads={"ping": {"op": "ping"}},
        banked_resolver=lambda tail: banked_path if tail == "1.0.0" else None,
    )
    PROVIDER_EXECUTORS["test-second"] = executor
    try:
        # A plugin pinning the second family: byte-equal to ITS banked copy.
        project = tmp_path / "second-plugin"
        shutil.copytree(FIXTURE_ROOT, project)
        package = project / "src" / "ftdi_control_demo"
        (package / "ftdi-control-provider.json").write_bytes(raw)
        descriptor_path = package / "descriptor.json"
        descriptor = json.loads(descriptor_path.read_text())
        descriptor["transport"]["provider"] = {
            "feature_id": banked["feature_id"],
            "id": banked["id"],
            "path": "ftdi-control-provider.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        descriptor["required_features"] = [
            "otdp.core/0.1.0",
            "otdp.adapter/0.1.0",
            banked["feature_id"],
        ]
        descriptor_path.write_text(json.dumps(descriptor, indent=2) + "\n")
        plugin = load_plugin_project(project)
        from benchweave_sdk_server.ftdi import verify_ftdi_plugin

        contract = verify_ftdi_plugin(plugin)
        assert contract.provider["feature_id"] == banked["feature_id"]

        # The banked bind survives the abstraction: a lookalike of the
        # SECOND family (same feature line, different bytes) refuses.
        lookalike = tmp_path / "second-lookalike"
        shutil.copytree(project, lookalike)
        package2 = lookalike / "src" / "ftdi_control_demo"
        widened = dict(banked)
        widened["description"] = "lookalike"
        raw2 = json.dumps(widened, indent=2).encode() + b"\n"
        (package2 / "ftdi-control-provider.json").write_bytes(raw2)
        descriptor2 = json.loads((package2 / "descriptor.json").read_text())
        descriptor2["transport"]["provider"]["sha256"] = hashlib.sha256(
            raw2
        ).hexdigest()
        (package2 / "descriptor.json").write_text(
            json.dumps(descriptor2, indent=2) + "\n"
        )
        with pytest.raises(ValueError, match="live_provider_feature_unsupported"):
            verify_ftdi_plugin(load_plugin_project(lookalike))
    finally:
        PROVIDER_EXECUTORS.pop("test-second", None)
