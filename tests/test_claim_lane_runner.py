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
import io
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
            # The wire contract: answers arrive as a map keyed by the
            # question ids the request sent.
            "answers": {qid: {"type": "noul", "noul": noul} for qid in questions},
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
        "skipped": 0,
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
    assert report["totals"]["skipped"] == 1, (
        "the skipped pseudo-verdict is counted, not silently unbucketed"
    )
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
        return {"answers": {qid: {"type": "noul", "noul": 1.0} for qid in questions}}

    code = lane.run(
        rows=lane.CLAIMS[:1],
        report_dir=tmp_path / "report",
        probe_results={"scan-hint-filter": ["The behavior conforms to the sentence."]},
        client=client,
    )
    assert code == 2
    assert not called, "the judge never saw the leaky trace"


# --- fold 1, F1: a stale trace is never judged as fresh evidence ------------


def test_f1_a_prior_run_trace_is_not_laundered_into_a_skipped_probe(
    lane: ModuleType, tmp_path: Path
) -> None:
    """The two-runs shape the refuter executed: run 1 green (artifact on
    disk), run 2's probe skips (subprocess exits 0, no artifact written) —
    the prior-run trace must NOT be judged as run 2's evidence."""
    report_dir = tmp_path / "report"
    artifact_root = tmp_path / "traces"
    first = lane.run(
        rows=lane.CLAIMS[:1],
        report_dir=report_dir,
        artifact_root=artifact_root,
        probe_results=_CONFORMING_TRACE,
        client=_client_returning(0.9),
    )
    assert first == 0
    assert (artifact_root / "scan-hint-filter.json").is_file()

    second = lane.run(
        rows=lane.CLAIMS[:1],
        report_dir=report_dir,
        artifact_root=artifact_root,
        probe_results={},
        client=_client_returning(0.9),
    )
    assert second == 2, "run 2 judged run 1's stale trace as fresh evidence"


# --- fold 1, F2: crash paths never discard earned verdicts -------------------


def _http_error(lane: ModuleType, code: int, body: bytes) -> Any:
    return lane.urllib.error.HTTPError(
        "https://api.typesafe.ai/v1/systemone", code, "failure", {}, io.BytesIO(body)
    )


def test_f2_a_non_json_error_body_exits_two_with_a_partial_report(
    lane: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An HTML 502 page behind a proxy: json-loads of the body must not
    crash the run with a raw traceback — the documented exit contract
    admits only 0 and 2, and the report names the failure."""
    monkeypatch.setenv(lane.KEY_ENV, "fold-f2-key")
    monkeypatch.setattr(
        lane.urllib.request,
        "urlopen",
        lambda _request, timeout: _http_error(
            lane, 502, b"<html>Bad Gateway</html>"
        ),
    )
    code = lane.run(
        rows=lane.CLAIMS[:1],
        report_dir=tmp_path / "report",
        probe_results=_CONFORMING_TRACE,
        client=None,
    )
    assert code == 2
    report = _report(tmp_path)
    assert "502" in report["error"]
    (row,) = report["rows"]
    assert row["verdict"] == "error"
    assert "Traceback" not in capsys.readouterr().err


def test_f2_an_unusable_report_dir_exits_two_with_verdicts_preserved(
    lane: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A file squatting on the report path: verdicts already earned are
    printed (the summary is the durable record when the report cannot be)
    and the exit is 2, not a NotADirectoryError traceback."""
    squat = tmp_path / "not-a-dir"
    squat.write_text("occupied", encoding="utf-8")
    code = lane.run(
        rows=lane.CLAIMS[:1],
        report_dir=squat,
        artifact_root=tmp_path / "traces",
        probe_results=_CONFORMING_TRACE,
        client=_client_returning(0.91),
    )
    assert code == 2
    out = capsys.readouterr().out
    assert "conforming" in out and "scan-hint-filter" in out


def test_an_out_of_domain_judge_answer_is_a_named_hard_error(
    lane: ModuleType, tmp_path: Path
) -> None:
    """Ride (b), the ruled resolution at the runner level: a judge that
    answers out of domain is an infrastructure failure, not a soft verdict
    — the run exits 2 through the F2 machinery with a partial report whose
    error field names the domain violation."""
    code = lane.run(
        rows=lane.CLAIMS[:1],
        report_dir=tmp_path / "report",
        probe_results=_CONFORMING_TRACE,
        client=_client_returning(1.5),
    )
    assert code == 2
    report = _report(tmp_path)
    assert "outside [0, 1]" in report["error"]
    (row,) = report["rows"]
    assert row["verdict"] == "error"


def test_f2_an_unusable_report_dir_on_the_skip_path_exits_two(
    lane: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(lane.KEY_ENV, raising=False)
    squat = tmp_path / "not-a-dir"
    squat.write_text("occupied", encoding="utf-8")
    code = lane.run(
        rows=lane.CLAIMS[:1],
        report_dir=squat,
        probe_results=_CONFORMING_TRACE,
        client=None,
    )
    assert code == 2


def test_f2_a_corrupt_artifact_file_exits_two_not_a_traceback(
    lane: ModuleType, tmp_path: Path
) -> None:
    traces_dir = tmp_path / "traces"
    traces_dir.mkdir()
    (traces_dir / "scan-hint-filter.json").write_text("{not json", encoding="utf-8")
    code = lane.run(
        rows=lane.CLAIMS[:1],
        report_dir=tmp_path / "report",
        artifact_root=traces_dir,
        probe_results={},  # the corrupt file is pre-planted, nothing rewrites it
        client=_client_returning(0.9),
    )
    assert code == 2


# --- fold 1, F5: the key never reaches stderr through error detail ----------


def test_f5_an_echoing_error_body_never_puts_the_key_on_stderr(
    lane: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The refuter's executed leak: a 401 whose body echoes the
    Authorization header travels into ClaimLaneError text via {payload!r}
    and run() prints it. Untrusted bodies must be truncated and
    bearer-shaped material stripped before they enter any message."""
    key = "sk-echo-fold-f5-key"
    monkeypatch.setenv(lane.KEY_ENV, key)
    body = json.dumps(
        {"error": f"Authorization: Bearer {key} was rejected"}
    ).encode("utf-8")
    monkeypatch.setattr(
        lane.urllib.request,
        "urlopen",
        lambda _request, timeout: _http_error(lane, 401, body),
    )
    code = lane.run(
        rows=lane.CLAIMS[:1],
        report_dir=tmp_path / "report",
        probe_results=_CONFORMING_TRACE,
        client=None,
    )
    assert code == 2
    captured = capsys.readouterr()
    assert key not in captured.err, "the API key reached stderr through error detail"
    assert key not in captured.out


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
            "answers": {"scan-hint-filter": {"type": "noul", "noul": 0.88}},
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
