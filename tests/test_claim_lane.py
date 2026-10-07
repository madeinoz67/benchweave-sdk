"""Claim lane unit cells: the dead band, the manifest, the judge seam.

AR-1 (the four dead-band edge cells), AR-2 (manifest validation), and the
client-injection seam of the design record
``.claude/deep-review/2026-10-07-claim-lane-shadow-design.md``. The
runner-with-fake-client cells (AR-4..AR-7) live in
``tests/test_claim_lane_runner.py``; the probe cells (AR-3/AR-8) live in
``tests/test_claim_probes.py`` and its schema cells.
"""

from __future__ import annotations

import dataclasses
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
    spec = importlib.util.spec_from_file_location("claim_lane_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # 3.14's dataclasses resolve the class's module through sys.modules —
    # an unregistered spec-loaded module crashes the decorator.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def lane() -> ModuleType:
    return _load_lane()


# --- AR-1: the dead band -------------------------------------------------


@pytest.mark.parametrize(
    ("noul", "expected"),
    [
        (1.00, "conforming"),
        (0.70, "conforming"),
        (0.69, "insufficient_evidence"),
        (0.50, "insufficient_evidence"),
        (0.31, "insufficient_evidence"),
        (0.30, "non_conforming"),
        (0.00, "non_conforming"),
    ],
)
def test_ar1_dead_band_cells(lane: ModuleType, noul: float, expected: str) -> None:
    assert lane.classify(noul) == expected


def test_ar1_the_four_edges_are_exactly_pinned(lane: ModuleType) -> None:
    """The design record's four boundary values, one cell, no loop — a moved
    threshold must redden THIS line, not a table row."""
    assert lane.classify(0.70) == "conforming"
    assert lane.classify(0.69) == "insufficient_evidence"
    assert lane.classify(0.31) == "insufficient_evidence"
    assert lane.classify(0.30) == "non_conforming"


def test_ar1_a_nan_refuses_rather_than_scoring(lane: ModuleType) -> None:
    """Ride (b), the ruled resolution: a NaN is malformed judge output, not
    an unsettled trace — insufficient_evidence is for traces that do not
    settle a claim; parking a broken answer there would launder an
    infrastructure failure into a soft verdict row."""
    with pytest.raises(lane.ClaimLaneError, match="outside"):
        lane.classify(float("nan"))


@pytest.mark.parametrize("bad", [-1.0, -0.01, 1.01, 1.5, float("inf")])
def test_ar1_an_out_of_domain_score_refuses(lane: ModuleType, bad: float) -> None:
    """Ride (b): -1 used to buy non_conforming and 1.5 conforming — an
    out-of-domain score is a judge-contract violation and refuses, never
    mints a verdict edge (the dead-band clamp was tried and ruled the
    weaker call)."""
    with pytest.raises(lane.ClaimLaneError, match=r"outside \[0, 1\]"):
        lane.classify(bad)


# --- AR-2: the manifest --------------------------------------------------


def test_ar2_the_seed_manifest_is_well_formed(lane: ModuleType) -> None:
    rows = lane.CLAIMS
    assert len(rows) >= 8, "the seed corpus carries at least eight claims"
    ids = [row.id for row in rows]
    assert len(set(ids)) == len(ids)
    for row in rows:
        assert row.claim.strip(), f"claim {row.id!r} is empty"
        assert row.probe.startswith("tests/test_claim_probes.py::"), (
            f"claim {row.id!r} names a probe outside the probe file"
        )


def _variant(lane: ModuleType, **overrides: Any) -> Any:
    return dataclasses.replace(lane.CLAIMS[0], **overrides)


def test_ar2_a_duplicate_id_refuses(lane: ModuleType) -> None:
    rows = lane.CLAIMS[:2] + [lane.CLAIMS[0]]
    with pytest.raises(lane.ClaimLaneError, match="duplicate claim id"):
        lane.validate_manifest(rows)


def test_ar2_an_empty_claim_refuses(lane: ModuleType) -> None:
    with pytest.raises(lane.ClaimLaneError, match="empty claim"):
        lane.validate_manifest([_variant(lane, claim="   ")])


def test_ar2_an_empty_id_refuses(lane: ModuleType) -> None:
    with pytest.raises(lane.ClaimLaneError, match="empty id"):
        lane.validate_manifest([_variant(lane, id="")])


def _probe_file(tmp_path: Path, names: list[str]) -> Path:
    root = tmp_path / "proj"
    probes = root / "tests"
    probes.mkdir(parents=True)
    body = "\n\n".join(f"def {name}() -> None:\n    pass\n" for name in names)
    (probes / "test_claim_probes.py").write_text(body, encoding="utf-8")
    return root


def test_ar2_a_probe_whose_file_is_missing_refuses(
    lane: ModuleType, tmp_path: Path
) -> None:
    with pytest.raises(lane.ClaimLaneError, match="probe file missing"):
        lane.validate_manifest([lane.CLAIMS[0]], probes_root=tmp_path)


def test_ar2_a_probe_cell_missing_from_the_file_refuses(
    lane: ModuleType, tmp_path: Path
) -> None:
    root = _probe_file(tmp_path, ["test_claim_other_cell"])
    with pytest.raises(lane.ClaimLaneError, match="probe cell missing"):
        lane.validate_manifest([lane.CLAIMS[0]], probes_root=root)


def test_ar2_a_present_probe_cell_passes(lane: ModuleType, tmp_path: Path) -> None:
    cell = lane.CLAIMS[0].probe.split("::")[1]
    root = _probe_file(tmp_path, [cell])
    lane.validate_manifest([lane.CLAIMS[0]], probes_root=root)


# --- the judge-client injection seam ---------------------------------------


def _fake_client(noul: float) -> tuple[list[Any], Any]:
    calls: list[Any] = []

    def client(state: Any, questions: Any) -> Any:
        calls.append({"state": state, "questions": questions})
        return {
            # The wire contract: answers arrive as a map keyed by the
            # question ids the request sent (mirrors the live API).
            "answers": {qid: {"type": "noul", "noul": noul} for qid in questions},
            "usage": {"total_tokens": 7},
        }

    return calls, client


def test_the_client_seam_is_injectable(lane: ModuleType) -> None:
    calls, client = _fake_client(0.9)
    state = {"claim": "c", "observed_behavior": ["an observation"]}
    questions = {"q1": lane.conformance_question("q1")}
    result = lane.ask(state, questions, client=client)
    assert result["answers"]["q1"]["noul"] == 0.9
    assert len(calls) == 1
    assert calls[0]["state"] is state


def test_the_conformance_question_is_wire_shaped(lane: ModuleType) -> None:
    """The live-contract pin (the 422 lesson): the question carries the
    noul type and explicit true/false criteria — an injectable client
    proves nothing about the wire form unless this shape is pinned."""
    question = lane.conformance_question("scan-hint-filter")
    assert question["type"] == "noul"
    assert isinstance(question["instructions"], str) and question["instructions"]
    assert set(question["criteria"]) == {"true", "false"}
    assert all(isinstance(v, str) and v for v in question["criteria"].values())


def test_ask_without_a_client_or_a_key_is_a_hard_error(
    lane: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(lane.KEY_ENV, raising=False)
    with pytest.raises(lane.ClaimLaneError, match="TYPESAFE_API_KEY"):
        lane.ask({}, {})


def test_default_client_is_none_without_the_key(
    lane: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(lane.KEY_ENV, raising=False)
    assert lane.default_client() is None


def test_default_client_is_callable_with_the_key(
    lane: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(lane.KEY_ENV, "test-key-material")
    client = lane.default_client()
    assert client is not None and callable(client)


def test_the_real_client_carries_auth_timeout_and_backoff(
    lane: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The urllib client's contract, offline: the Authorization header and
    the 60 s timeout ride every attempt, 429/529 back off exponentially, and
    a 200 returns the parsed payload."""
    posts: list[dict[str, Any]] = []
    statuses = [429, 529, 200]
    sleeps: list[float] = []

    def post(url: str, body: bytes, key: str, timeout_s: float) -> tuple[int, Any]:
        posts.append({"url": url, "key": key, "timeout_s": timeout_s, "body": body})
        return statuses[len(posts) - 1], {
            "answers": {"q": {"type": "noul", "noul": 0.5}}
        }

    monkeypatch.setattr(lane, "_sleep", sleeps.append)
    client = lane.systemone_client("test-key-material", post=post)
    result = client({"claim": "c"}, {"q": lane.conformance_question("q")})

    assert result["answers"]["q"]["noul"] == 0.5
    # The wire contract pinned at the byte level: the POSTed body carries
    # the questions as a MAP with the noul type present (the live-422 fix).
    sent = json.loads(posts[0]["body"])
    assert isinstance(sent["questions"], dict)
    assert sent["questions"]["q"]["type"] == "noul"
    assert len(posts) == 3, "429 and 529 each retried once"
    for call in posts:
        assert call["url"] == lane.SYSTEMONE_URL
        assert call["key"] == "test-key-material"
        assert call["timeout_s"] == 60
    assert sleeps == [1.0, 2.0], "exponential backoff"


def test_the_real_client_hard_fails_on_a_server_error(
    lane: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lane, "_sleep", lambda _s: None)

    def post(_url: str, _body: bytes, _key: str, _t: float) -> tuple[int, Any]:
        return 500, None

    client = lane.systemone_client("test-key-material", post=post)
    with pytest.raises(lane.ClaimLaneError, match="HTTP 500"):
        client({}, [])


def test_the_real_client_hard_fails_when_retries_exhaust(
    lane: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lane, "_sleep", lambda _s: None)

    def post(_url: str, _body: bytes, _key: str, _t: float) -> tuple[int, Any]:
        return 429, None

    client = lane.systemone_client("test-key-material", post=post)
    with pytest.raises(lane.ClaimLaneError, match="429"):
        client({}, [])


# --- AR-3: the trace artifact ---------------------------------------------


def test_ar3_a_well_formed_trace_validates(lane: ModuleType) -> None:
    artifact = {
        "claim_id": "capture-crash-reserved",
        "observations": [
            "An abandoned capture left its event directory under the capture root.",
            "A fresh writer's append with that capture id was refused with a collision message.",
        ],
    }
    observations = lane.validate_trace(artifact, expected_id="capture-crash-reserved")
    assert len(observations) == 2


def test_ar3_a_missing_claim_id_refuses(lane: ModuleType) -> None:
    with pytest.raises(lane.ClaimLaneError, match="claim_id"):
        lane.validate_trace({"observations": ["an observation"]})


def test_ar3_a_mismatched_claim_id_refuses(lane: ModuleType) -> None:
    with pytest.raises(lane.ClaimLaneError, match="mismatch"):
        lane.validate_trace(
            {"claim_id": "a", "observations": ["an observation"]}, expected_id="b"
        )


def test_ar3_an_empty_observation_set_refuses(lane: ModuleType) -> None:
    with pytest.raises(lane.ClaimLaneError, match="no observations"):
        lane.validate_trace({"claim_id": "a", "observations": []})


def test_ar3_a_non_string_observation_refuses(lane: ModuleType) -> None:
    with pytest.raises(lane.ClaimLaneError, match="not a string"):
        lane.validate_trace(
            {"claim_id": "a", "observations": ["The scan opened two ports.", 7]}
        )


def test_ar3_a_blank_observation_refuses(lane: ModuleType) -> None:
    with pytest.raises(lane.ClaimLaneError, match="blank"):
        lane.validate_trace({"claim_id": "a", "observations": ["   "]})


@pytest.mark.parametrize(
    "bad",
    [
        "The behavior conforms to the documented sentence.",
        "This matches the claim exactly.",
        "The system is non_conforming here.",
        "The observation contradicts the claim.",
        "This is consistent with the claim.",
        "Verified: the code complies.",
        "The verdict is conforming.",
        "This is as documented.",
    ],
)
def test_ar3_verdict_vocabulary_is_rejected(lane: ModuleType, bad: str) -> None:
    """The deliberately-bad observation sets: judgment language inside a
    trace hands the judge the answer — the schema refuses it (AR-3)."""
    with pytest.raises(lane.ClaimLaneError, match="verdict vocabulary"):
        lane.validate_trace({"claim_id": "a", "observations": [bad]})


def test_ar3_behavior_vocabulary_stays_neutral(lane: ModuleType) -> None:
    """Refusal and failure words describe BEHAVIOR, not the claim — they
    must survive the neutrality gate (the probes observe refusal paths)."""
    observations = [
        "The writer refused the append with a ValueError.",
        "The finalise call failed before any publication.",
        "The scan returned two devices.",
    ]
    assert lane.validate_trace({"claim_id": "a", "observations": observations}) == (
        observations
    )


# --- fold 1, F3: the structural gate (the blocklist is not enough) ----------

#: The refuter's paraphrase classes (13) plus three new ones. The vocabulary
#: blocklist alone admitted all of these; each must now refuse on STRUCTURE:
#: no causal, concessive or evaluative clause, and a past-tense event core.
_STRUCTURAL_BYPASSES = [
    # the five named in the fold brief
    "The scan behaved as the README specifies.",
    "Das Verhalten ist konform.",
    "行为符合声明。",
    "The writer c0nforms to the documented limit.",
    "The observed behavior did not differ from the claim.",
    # eight more across the same classes
    "The refusal count matched the documented number, so the sentence holds.",
    "Everything worked exactly as expected.",
    "The system therefore satisfies the sentence.",
    "Because the reservation holds, the claim is intact.",
    "The behavior is correct in every observed case.",
    "This is in line with what the guide promises.",
    "The trace proves that the sentence is true.",
    "The scan will open all candidate ports.",
    # three new for this fold
    "It works.",
    "The writer c0nf0rms t0 the limit.",
    "The refused append was refused because its 100 bytes would carry the "
    "staged total to 1100 bytes, past the 1024-byte reservation; the "
    "accepted append had stayed within it.",
]


@pytest.mark.parametrize("bad", _STRUCTURAL_BYPASSES)
def test_f3_structural_bypasses_are_refused(lane: ModuleType, bad: str) -> None:
    """Every observation must be a past-tense event sentence: the blocklist
    is accidental-leak protection, this structure check is the gate."""
    with pytest.raises(lane.ClaimLaneError):
        lane.validate_trace({"claim_id": "a", "observations": [bad]})


def test_f3_a_present_tense_observation_refuses(lane: ModuleType) -> None:
    with pytest.raises(lane.ClaimLaneError, match="past-tense"):
        lane.validate_trace(
            {"claim_id": "a", "observations": ["The scan opens four ports."]}
        )


def test_f3_a_fragment_without_a_verb_refuses(lane: ModuleType) -> None:
    with pytest.raises(lane.ClaimLaneError, match="past-tense"):
        lane.validate_trace({"claim_id": "a", "observations": ["Four open ports."]})


def test_f3_cold_numbers_stay_admissible(lane: ModuleType) -> None:
    """The ROW-4 shape: cold-numbers past-tense observations with no causal
    clause must pass the structural gate."""
    observations = [
        "The 100-byte second append arrived with 1000 bytes already staged "
        "against the 1024-byte reservation.",
        "The refusal message reported the reservation of 1024 bytes and "
        "the 1000 bytes already staged.",
    ]
    assert lane.validate_trace({"claim_id": "a", "observations": observations}) == (
        observations
    )
