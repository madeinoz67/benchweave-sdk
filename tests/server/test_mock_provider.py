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
    exchanges, establishment = provider_script(plugin)
    assert len(exchanges) == 11, "the whole corpus compiles"
    assert establishment == 8, "the cycle plan derives the status unit head"


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


def test_recorded_failure_under_provider_refuses(tmp_path: Path) -> None:
    """Bound D2: failure rows are not scriptable under the dialect — the
    refusal names the bound; the driver double's fault flags cover fault
    rehearsal meanwhile."""
    project = tmp_path / "failed"
    shutil.copytree(FIXTURE_ROOT, project)
    corpus_path = project / "src" / "ftdi_control_demo" / "vectors.json"
    corpus = json.loads(corpus_path.read_text())
    # A stream_receive row with a recorded failure and NO response: the
    # shared validator accepts this row for journals (failure rows carry
    # no response), so the refusal that fires is the DIALECT's own bound.
    corpus["exchanges"].append(
        {
            "name": "quiet-drain",
            "transaction": {
                "kind": "stream_receive",
                "max_bytes": 8,
                "termination": "lf",
                "exact_bytes": None,
            },
            "recorded_failure": "timeout",
        }
    )
    corpus_path.write_text(json.dumps(corpus, indent=2) + "\n")
    plugin = load_plugin_project(project)
    with pytest.raises(Exception, match="recorded_failure rows are not scriptable"):
        asyncio.run(mock_plugin_session(plugin).connect())


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
