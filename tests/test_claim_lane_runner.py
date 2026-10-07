# author: Stephen Eaton
"""Claim lane runner cells: the report, the shadow law, the skip path.

AR-4 (fake-client rows + report shape), AR-5 (missing key => skip, exit 0),
AR-6 (a non_conforming verdict never fails the run), AR-7 (the key never
appears in any artifact), and the hard-error posture (malformed manifest,
probe failure). All offline: the client is injected and the probe outcome
is injected, so no subprocess and no network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "claim_lane.py"


def _load_lane() -> ModuleType:
    spec = importlib.util.spec_from_file_location("claim_lane_runner_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def lane() -> ModuleType:
    return _load_lane()


_CONFORMING_TRACE = {
    "scan-hint-filter": [
        "The scan opened four candidate ports and sent one identify frame to each.",
        "The scan returned two devices carrying the descriptor's identity fields.",
    ],
}
#: The RED control: a trace that CONTRADICTS the claim (the trace is still
#: schema-valid and neutral — it is simply false evidence for the sentence).
_CONTRADICTING_TRACE = {
    "scan-hint-filter": [
        "The scan opened no candidate ports and transmitted nothing.",
        "The scan returned no devices.",
    ],
}
_DEAD_BAND_TRACE = {
    "scan-hint-filter": [
        "The scan ran and returned an unspecified number of devices.",
    ],
}


def _client_returning(noul: float) -> Any:
    def client(state: Any, questions: Any) -> Any:
        return {
            "answers": [{"id": q["id"], "noul": noul} for q in questions],
            "usage": {"total_tokens": 42},
            "model": "jev-test",
        }

    return client


def _run(lane: ModuleType, tmp_path: Path, *, client: Any, traces: Any) -> int:
    return lane.run(
        rows=lane.CLAIMS[:1],
        report_dir=tmp_path / "report",
        probe_results=traces,
        client=client,
    )


def _report(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / "report" / "report.json").read_text(encoding="utf-8"))


# --- AR-4: rows and report shape ------------------------------------------


def test_ar4_a_conforming_noul_yields_a_conforming_row(lane: ModuleType, tmp_path: Path) -> None:
    code = _run(lane, tmp_path, client=_client_returning(0.92), traces=_CONFORMING_TRACE)
    assert code == 0
    report = _report(tmp_path)
    (row,) = report["rows"]
    assert row["claim_id"] == "scan-hint-filter"
    assert row["verdict"] == "conforming"
    assert row["noul"] == pytest.approx(0.92)
    assert row["claim"] == lane.CLAIMS[0].claim
    assert row["model"] == "jev-test"
    assert row["tokens"] == 42
    assert report["totals"] == {
        "claims": 1,
        "conforming": 1,
        "non_conforming": 0,
        "insufficient_evidence": 0,
    }


def test_ar4_row_fields_are_exactly_the_pinned_set(lane: ModuleType, tmp_path: Path) -> None:
    _run(lane, tmp_path, client=_client_returning(0.9), traces=_CONFORMING_TRACE)
    (row,) = _report(tmp_path)["rows"]
    assert set(row) == {"claim_id", "claim", "verdict", "noul", "model", "tokens"}


def test_ar4_an_insufficient_noul_lands_in_the_dead_band(
    lane: ModuleType, tmp_path: Path
) -> None:
    _run(lane, tmp_path, client=_client_returning(0.5), traces=_DEAD_BAND_TRACE)
    (row,) = _report(tmp_path)["rows"]
    assert row["verdict"] == "insufficient_evidence"
    assert _report(tmp_path)["totals"]["insufficient_evidence"] == 1


# --- AR-6 + the offline RED control ----------------------------------------


def test_ar6_a_contradicting_trace_reports_non_conforming_and_exits_zero(
    lane: ModuleType, tmp_path: Path
) -> None:
    """The offline RED control: deliberately false evidence for the claim
    scores low, lands non_conforming in the report, and the run still exits
    0 — the shadow law pinned (AR-6)."""
    code = _run(
        lane, tmp_path, client=_client_returning(0.03), traces=_CONTRADICTING_TRACE
    )
    assert code == 0, "a non_conforming verdict never fails the run"
    report = _report(tmp_path)
    (row,) = report["rows"]
    assert row["verdict"] == "non_conforming"
    assert report["totals"]["non_conforming"] == 1


def test_ar6_an_all_non_conforming_report_still_exits_zero(
    lane: ModuleType, tmp_path: Path
) -> None:
    traces = {
        row.id: ["The behavior observed did not exercise this sentence."]
        for row in lane.CLAIMS
    }
    code = lane.run(
        rows=lane.CLAIMS,
        report_dir=tmp_path / "report",
        probe_results=traces,
        client=_client_returning(0.02),
    )
    assert code == 0
    report = _report(tmp_path)
    assert report["totals"]["non_conforming"] == len(lane.CLAIMS)
    assert report["totals"]["conforming"] == 0


# --- AR-5: the missing-key skip path ---------------------------------------


def test_ar5_a_missing_key_writes_a_skip_report_and_exits_zero(
    lane: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(lane.KEY_ENV, raising=False)
    code = lane.run(
        rows=lane.CLAIMS[:1],
        report_dir=tmp_path / "report",
        probe_results=_CONFORMING_TRACE,
        client=None,
    )
    assert code == 0
    report = _report(tmp_path)
    assert report["skipped"] is True
    assert lane.KEY_ENV in report["skip_reason"]
    (row,) = report["rows"]
    assert row["verdict"] == "skipped"


def test_ar5_a_real_key_takes_the_judging_path(
    lane: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(lane.KEY_ENV, "runner-test-key")
    code = _run(lane, tmp_path, client=_client_returning(0.8), traces=_CONFORMING_TRACE)
    assert code == 0
    assert _report(tmp_path)["skipped"] is False


# --- hard setup errors ------------------------------------------------------


def test_a_malformed_manifest_exits_nonzero(lane: ModuleType, tmp_path: Path) -> None:
    rows = lane.CLAIMS[:1] + [lane.CLAIMS[0]]
    code = lane.run(
        rows=rows,
        report_dir=tmp_path / "report",
        probe_results={},
        client=_client_returning(0.9),
    )
    assert code == 2
    assert not (tmp_path / "report" / "report.json").exists()


def test_a_probe_failure_exits_nonzero(lane: ModuleType, tmp_path: Path) -> None:
    code = lane.run(
        rows=lane.CLAIMS[:1],
        report_dir=tmp_path / "report",
        probe_results={"__returncode__": 1},
        client=_client_returning(0.9),
    )
    assert code == 2


def test_a_missing_artifact_for_a_row_exits_nonzero(
    lane: ModuleType, tmp_path: Path
) -> None:
    code = lane.run(
        rows=lane.CLAIMS[:2],
        report_dir=tmp_path / "report",
        probe_results={lane.CLAIMS[0].id: ["One observation was recorded."]},
        client=_client_returning(0.9),
    )
    assert code == 2


def test_a_verdict_vocabulary_trace_exits_nonzero_before_judging(
    lane: ModuleType, tmp_path: Path
) -> None:
    """A leaky trace never reaches the judge — the collector refuses it."""
    called: list[Any] = []

    def client(state: Any, questions: Any) -> Any:
        called.append(state)
        return {"answers": [{"id": "x", "noul": 1.0}]}

    code = lane.run(
        rows=lane.CLAIMS[:1],
        report_dir=tmp_path / "report",
        probe_results={"scan-hint-filter": ["The behavior conforms to the sentence."]},
        client=client,
    )
    assert code == 2
    assert not called, "the judge never saw the leaky trace"


# --- AR-7: the key never appears in any artifact ---------------------------


def test_ar7_the_key_never_appears_in_any_artifact(
    lane: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real client path with the real key value, offline: _urllib_post is
    pinned to a canned 200, so the key flows exactly as far as the request —
    then every produced byte is grepped for it."""
    sentinel = "sk-secret-claimlane-ar7"
    monkeypatch.setenv(lane.KEY_ENV, sentinel)

    def post(_url: str, _body: bytes, _key: str, _t: float) -> tuple[int, Any]:
        return 200, {
            "answers": [{"id": "scan-hint-filter", "noul": 0.88}],
            "usage": {"total_tokens": 5},
        }

    monkeypatch.setattr(lane, "_urllib_post", post)
    report_dir = tmp_path / "report"
    artifact_root = tmp_path / "artifacts"
    code = lane.run(
        rows=lane.CLAIMS[:1],
        report_dir=report_dir,
        artifact_root=artifact_root,
        probe_results=_CONFORMING_TRACE,
        client=None,
    )
    assert code == 0
    produced = list(report_dir.rglob("*")) + list(artifact_root.rglob("*"))
    files = [path for path in produced if path.is_file()]
    assert files, "the run produced report and artifact files"
    for path in files:
        assert sentinel not in path.read_text(encoding="utf-8"), f"key leaked into {path}"
    (row,) = _report(tmp_path)["rows"]
    assert row["verdict"] == "conforming"
