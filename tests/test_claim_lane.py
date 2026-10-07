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


def test_ar1_a_nan_scores_insufficient_not_a_verdict(lane: ModuleType) -> None:
    """A judge that returns NaN lands in the dead band — never a confident
    verdict on either side (the shadow posture's conservative default)."""
    assert lane.classify(float("nan")) == "insufficient_evidence"


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
            "answers": [{"id": q["id"], "noul": noul} for q in questions],
            "usage": {"total_tokens": 7},
        }

    return calls, client


def test_the_client_seam_is_injectable(lane: ModuleType) -> None:
    calls, client = _fake_client(0.9)
    state = {"claim": "c", "observed_behavior": ["an observation"]}
    questions = [{"id": "q1", "instructions": "judge"}]
    result = lane.ask(state, questions, client=client)
    assert result["answers"][0]["noul"] == 0.9
    assert len(calls) == 1
    assert calls[0]["state"] is state


def test_ask_without_a_client_or_a_key_is_a_hard_error(
    lane: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(lane.KEY_ENV, raising=False)
    with pytest.raises(lane.ClaimLaneError, match="TYPESAFE_API_KEY"):
        lane.ask({}, [])


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
        posts.append({"url": url, "key": key, "timeout_s": timeout_s})
        return statuses[len(posts) - 1], {"answers": [{"id": "q", "noul": 0.5}]}

    monkeypatch.setattr(lane, "_sleep", sleeps.append)
    client = lane.systemone_client("test-key-material", post=post)
    result = client({"claim": "c"}, [{"id": "q", "instructions": "i"}])

    assert result["answers"][0]["noul"] == 0.5
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
