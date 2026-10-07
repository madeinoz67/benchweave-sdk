#!/usr/bin/env python3
# author: Stephen Eaton
"""The shadow-mode claim-conformance lane.

Design record: ``.claude/deep-review/2026-10-07-claim-lane-shadow-design.md``.
The lane's law, from the trace-vs-excerpt experiment: doc claims are judged
against EXECUTED BEHAVIORAL TRACES, never code excerpts.

This module carries the manifest (``CLAIMS`` — doc sentences quoted verbatim,
each bound to a probe cell), the dead-band classifier (the ambiguity control
made structural), and the judge client (stdlib urllib against the System One
API, injectable so every downstream test runs offline).

SHADOW LAW: the runner (``__main__``) exits 0 for ANY verdict distribution.
Nonzero exit is reserved for hard setup errors — a malformed manifest or
probe failures. A non_conforming verdict is data for a human, never a gate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
KEY_ENV = "TYPESAFE_API_KEY"
#: The probes write trace artifacts under this directory when it is wired
#: (the runner wires it; plain suite runs leave it unset).
ARTIFACT_ROOT_ENV = "CLAIM_LANE_ARTIFACT_ROOT"
REQUEST_TIMEOUT_S = 60
MAX_ATTEMPTS = 5

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR_NAME = ".claim-lane"
TRACES_DIR_NAME = "traces"

VERDICT_CONFORMING = "conforming"
VERDICT_NON_CONFORMING = "non_conforming"
VERDICT_INSUFFICIENT = "insufficient_evidence"

CONFORMING_THRESHOLD = 0.70
NON_CONFORMING_THRESHOLD = 0.30

#: The judge answers one question per (claim, trace) pair.
JudgeClient = Callable[[dict[str, Any], dict[str, dict[str, Any]]], dict[str, Any]]
#: One HTTP attempt: (status, parsed body or None). Injectable for tests.
Post = Callable[[str, bytes, str, float], tuple[int, Any]]


class ClaimLaneError(Exception):
    """A hard setup error: malformed manifest, missing probe, dead client."""


def _sleep(seconds: float) -> None:
    """Indirection so tests pin backoff timing without waiting (patch me)."""
    time.sleep(seconds)


# --- the dead band --------------------------------------------------------


def classify(noul: float) -> str:
    """Map a judge score to a verdict through the dead band.

    ``>= 0.70`` conforming, ``<= 0.30`` non_conforming, between them
    insufficient evidence. The middle band exists because the experiment's
    ambiguity control produced one 0.57 mid-band result: a trace that does
    not settle its claim must report as unsettled, never as a confident
    verdict on either side. A NaN lands in the dead band by the same
    conservative default.
    """
    if noul >= CONFORMING_THRESHOLD:
        return VERDICT_CONFORMING
    if noul <= NON_CONFORMING_THRESHOLD:
        return VERDICT_NON_CONFORMING
    return VERDICT_INSUFFICIENT


# --- the manifest ---------------------------------------------------------


@dataclass(frozen=True)
class ClaimRow:
    """One manifest row: a doc sentence and the probe that executes it."""

    id: str
    claim: str
    probe: str


#: The seed corpus. ``claim`` sentences are quoted VERBATIM from the
#: repository's README.md and user_guide/plugin-sdk.qmd at the design date;
#: every ``probe`` names a cell in tests/test_claim_probes.py that exercises
#: the sentence's behavior over the existing test doubles.
CLAIMS: list[ClaimRow] = [
    ClaimRow(
        id="scan-hint-filter",
        claim=(
            "Discovery opens candidate ports and asks each for its identity, "
            "filtered by the descriptor's declared USB hint "
            "(`x-standalone-usb-vid`/`x-standalone-usb-pid` extension keys "
            "under `transport.settings`) where declared."
        ),
        probe="tests/test_claim_probes.py::test_claim_scan_hint_filter",
    ),
    ClaimRow(
        id="scan-unparseable-hint",
        claim="An unparseable declared hint refuses the scan and names the value.",
        probe="tests/test_claim_probes.py::test_claim_scan_unparseable_hint",
    ),
    ClaimRow(
        id="capture-abort-id-reuse",
        claim=(
            "The abort removes the event directory, so you can reuse the "
            "capture id in the same process."
        ),
        probe="tests/test_claim_probes.py::test_claim_capture_abort_id_reuse",
    ),
    ClaimRow(
        id="capture-crash-reserved",
        claim="A capture left behind by a crash keeps its id reserved.",
        probe="tests/test_claim_probes.py::test_claim_capture_crash_reserved",
    ),
    ClaimRow(
        id="capture-reservation-crossing",
        claim=("The writer checks the reservation at each append: an append that would "
            "carry the staged total past the reservation is refused, naming both numbers."),
        probe="tests/test_claim_probes.py::test_claim_capture_reservation_crossing",
    ),
    ClaimRow(
        id="negotiated-bauds-validation",
        claim=(
            "The host checks the declaration when the session builds. "
            "A malformed value stops the build with a clear error."
        ),
        probe="tests/test_claim_probes.py::test_claim_negotiated_bauds_validation",
    ),
    ClaimRow(
        id="negotiated-switch-undeclared",
        claim="Without the declaration, every switch refuses.",
        probe="tests/test_claim_probes.py::test_claim_negotiated_switch_undeclared",
    ),
    ClaimRow(
        id="capture-empty-refused",
        claim="The writer refuses a capture that appended nothing.",
        probe="tests/test_claim_probes.py::test_claim_capture_empty_refused",
    ),
    ClaimRow(
        id="capture-waveform-length",
        claim=(
            "It also refuses a `waveform_f64le` capture whose byte length is "
            "not `sample_count` × 8, as the gateway refuses that too."
        ),
        probe="tests/test_claim_probes.py::test_claim_capture_waveform_length",
    ),
    ClaimRow(
        id="capture-env-dir-empty",
        claim=(
            "The writer also refuses a `BENCHWEAVE_CAPTURE_DIR` that is set "
            "but empty or whitespace-only."
        ),
        probe="tests/test_claim_probes.py::test_claim_capture_env_dir_empty",
    ),
]


def validate_manifest(rows: list[ClaimRow], *, probes_root: Path | None = None) -> None:
    """Refuse a manifest that is not judgeable: duplicate ids, empty fields,
    or a probe whose file or cell does not exist. Raises ClaimLaneError."""
    if not rows:
        raise ClaimLaneError("empty manifest: no claims to judge")
    seen: set[str] = set()
    for row in rows:
        if not row.id.strip():
            raise ClaimLaneError(f"empty id on row with claim {row.claim[:40]!r}")
        if row.id in seen:
            raise ClaimLaneError(f"duplicate claim id: {row.id}")
        seen.add(row.id)
        if not row.claim.strip():
            raise ClaimLaneError(f"empty claim: {row.id}")
        if "::" not in row.probe:
            raise ClaimLaneError(f"probe is not a pytest node id: {row.id}: {row.probe}")
    if probes_root is None:
        return
    for row in rows:
        file_part, _, cell = row.probe.partition("::")
        probe_file = probes_root / file_part
        if not probe_file.is_file():
            raise ClaimLaneError(f"probe file missing: {row.id}: {probe_file}")
        if f"def {cell}(" not in probe_file.read_text(encoding="utf-8"):
            raise ClaimLaneError(f"probe cell missing: {row.id}: {row.probe}")


# --- the trace artifact ---------------------------------------------------

#: Judgment language that must never appear inside an observation. Verdict
#: vocabulary hands the judge the answer; the experiment's clean separation
#: (false 0.02-0.04 vs true 0.74-0.98) came from NEUTRAL traces. Behavior
#: vocabulary ("refused", "failed", "returned") is deliberately absent from
#: this list: the probes observe refusal paths, and those words describe
#: what happened, not whether it matches the claim.
_VERDICT_VOCABULARY = (
    "conform",
    "verdict",
    "as documented",
    "as claimed",
    "matches the claim",
    "match the claim",
    "consistent with the claim",
    "contradicts the claim",
    "complies",
    "documented behavior",
)


def validate_trace(
    artifact: dict[str, Any], *, expected_id: str | None = None
) -> list[str]:
    """Validate one trace artifact and return its observations.

    An artifact is ``{"claim_id": str, "observations": [str, ...]}`` with at
    least one non-blank observation, each free of verdict vocabulary.
    Raises ClaimLaneError on any violation — a bad trace fails the probe,
    never the judge.
    """
    claim_id = artifact.get("claim_id")
    if not isinstance(claim_id, str) or not claim_id.strip():
        raise ClaimLaneError(f"trace artifact has no claim_id: {artifact!r}")
    if expected_id is not None and claim_id != expected_id:
        raise ClaimLaneError(f"trace claim_id mismatch: {claim_id} != {expected_id}")
    observations = artifact.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ClaimLaneError(f"trace for {claim_id} has no observations")
    for index, observation in enumerate(observations):
        if not isinstance(observation, str):
            raise ClaimLaneError(f"trace for {claim_id}: observation {index} is not a string")
        if not observation.strip():
            raise ClaimLaneError(f"trace for {claim_id}: observation {index} is blank")
        lowered = observation.lower()
        for word in _VERDICT_VOCABULARY:
            if word in lowered:
                raise ClaimLaneError(
                    f"trace for {claim_id}: observation {index} carries verdict "
                    f"vocabulary ({word!r})"
                )
    return [str(item) for item in observations]


# --- the judge client -----------------------------------------------------


def _urllib_post(url: str, body: bytes, key: str, timeout_s: float) -> tuple[int, Any]:
    """One real HTTP attempt. Returns (status, parsed JSON or None). The key
    exists only inside this request's Authorization header — never in a
    return value, log line, or artifact."""
    request = urllib.request.Request(  # noqa: S310 - the fixed https endpoint
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        # 422 bodies name the offending field — the diagnosis the live
        # contract check needs, so it must travel with the status.
        try:
            detail = error.read().decode("utf-8", "replace")
        except OSError:  # pragma: no cover - body already consumed
            detail = ""
        return error.code, (json.loads(detail) if detail else None)
    except (urllib.error.URLError, OSError) as error:
        raise ClaimLaneError(f"systemone unreachable: {error}") from error


def systemone_client(
    api_key: str,
    *,
    model: str = DEFAULT_MODEL,
    url: str = SYSTEMONE_URL,
    timeout_s: float = REQUEST_TIMEOUT_S,
    max_attempts: int = MAX_ATTEMPTS,
    post: Post | None = None,
) -> JudgeClient:
    """Build the judge client: one POST per call, 429/529 exponential
    backoff (1 s, 2 s, 4 s, ...), hard failure otherwise."""
    do_post: Post = post if post is not None else _urllib_post

    def client(
        state: dict[str, Any], questions: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        body = json.dumps(
            {"model": model, "state": state, "questions": questions}
        ).encode("utf-8")
        delay = 1.0
        for attempt in range(1, max_attempts + 1):
            status, payload = do_post(url, body, api_key, timeout_s)
            if status == 200 and isinstance(payload, dict):
                return payload
            if status not in (429, 529):
                raise ClaimLaneError(
                    f"systemone request failed: HTTP {status} {payload!r}"
                )
            if attempt == max_attempts:
                break
            _sleep(delay)
            delay *= 2
        raise ClaimLaneError(
            f"systemone still rate-limited after {max_attempts} attempts "
            f"(last status {status})"
        )

    return client


def default_client() -> JudgeClient | None:
    """The client from the environment, or None when the key is absent —
    the runner's skip path keys off this."""
    key = os.environ.get(KEY_ENV)
    if not key:
        return None
    return systemone_client(key)


def ask(
    state: dict[str, Any],
    questions: dict[str, dict[str, Any]],
    *,
    client: JudgeClient | None = None,
) -> dict[str, Any]:
    """Pose questions against state through the (injected or default)
    client. No client and no key is a hard setup error."""
    active = client if client is not None else default_client()
    if active is None:
        raise ClaimLaneError(f"no judge client: {KEY_ENV} is not set")
    return active(state, questions)


# --- the runner ------------------------------------------------------------

#: The experiment's conformance question: judgment rests on the executed
#: trace alone, with explicit true/false criteria and an explicit
#: low-confidence out for unsettled traces (the dead band's input side).
CONFORMANCE_INSTRUCTIONS = (
    "Given `observed_behavior`, does the system behave as the sentence in "
    "`claim` states? Answer true only if the observed behavior demonstrates "
    "the sentence. Answer false if the observed behavior contradicts the "
    "sentence. If the observations do not settle the question, answer "
    "without confidence. Rest the answer only on observed_behavior."
)

#: The question's typed shape on the wire (the API contract): a noul with
#: explicit true/false descriptions. The live 422 that shaped this constant
#: is the lesson: an injectable client proves nothing about the wire form
#: unless a test pins it.
CONFORMANCE_CRITERIA = {
    "true": "the observed behavior matches the claim's assertion",
    "false": "the observed behavior differs from the claim's assertion",
}


def conformance_question(claim_id: str) -> dict[str, Any]:
    """The wire-shaped question for one claim, keyed for the questions map."""
    return {
        "type": "noul",
        "instructions": CONFORMANCE_INSTRUCTIONS,
        "criteria": CONFORMANCE_CRITERIA,
    }


def _noul_of(answer: Any) -> float:
    value = answer.get("noul") if isinstance(answer, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ClaimLaneError(f"judge answer carries no numeric noul: {answer!r}")
    return float(value)


def _run_probes(artifact_root: Path, probes_root: Path) -> int:
    """Run the claim_probe cells as a subprocess with the artifact root
    wired. The probes' own exit code decides: red cells are probe failures."""
    env = dict(os.environ)
    env[ARTIFACT_ROOT_ENV] = str(artifact_root)
    completed = subprocess.run(  # noqa: S603 - the repo's own test suite
        [sys.executable, "-m", "pytest", "-m", "claim_probe", "tests"],
        cwd=probes_root,
        env=env,
        check=False,
    )
    return completed.returncode


def collect_traces(
    rows: list[ClaimRow], artifact_root: Path
) -> dict[str, list[str]]:
    """Read and validate every row's trace artifact. A missing artifact or a
    schema violation is a hard setup error — nothing is judged on evidence
    that is not there."""
    traces: dict[str, list[str]] = {}
    for row in rows:
        path = artifact_root / f"{row.id}.json"
        if not path.is_file():
            raise ClaimLaneError(f"probe produced no trace artifact: {row.id}")
        artifact = json.loads(path.read_text(encoding="utf-8"))
        traces[row.id] = validate_trace(artifact, expected_id=row.id)
    return traces


def judge_rows(
    rows: list[ClaimRow], traces: dict[str, list[str]], client: JudgeClient
) -> list[dict[str, Any]]:
    """Judge every (claim, trace) pair through the client and classify."""
    judged: list[dict[str, Any]] = []
    for row in rows:
        state = {
            "claim": row.claim,
            "observed_behavior": "\n".join(traces[row.id]),
        }
        response = client(state, {row.id: conformance_question(row.id)})
        answers = response.get("answers")
        if not isinstance(answers, dict) or not isinstance(
            answers.get(row.id), dict
        ):
            raise ClaimLaneError(f"judge returned no answer for {row.id}")
        noul = _noul_of(answers[row.id])
        usage = response.get("usage")
        tokens = usage.get("total_tokens", 0) if isinstance(usage, dict) else 0
        judged.append(
            {
                "claim_id": row.id,
                "claim": row.claim,
                "verdict": classify(noul),
                "noul": noul,
                "model": response.get("model", DEFAULT_MODEL),
                "tokens": tokens,
            }
        )
    return judged


def write_report(
    report_dir: Path,
    rows_out: list[dict[str, Any]],
    *,
    skipped: bool = False,
    skip_reason: str = "",
) -> Path:
    """Write .claim-lane/report.json and return its path."""
    report_dir.mkdir(parents=True, exist_ok=True)
    totals = {
        "claims": len(rows_out),
        "conforming": sum(1 for row in rows_out if row["verdict"] == VERDICT_CONFORMING),
        "non_conforming": sum(
            1 for row in rows_out if row["verdict"] == VERDICT_NON_CONFORMING
        ),
        "insufficient_evidence": sum(
            1 for row in rows_out if row["verdict"] == VERDICT_INSUFFICIENT
        ),
    }
    document = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        "model": DEFAULT_MODEL,
        "skipped": skipped,
        "skip_reason": skip_reason,
        "rows": rows_out,
        "totals": totals,
    }
    path = report_dir / "report.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def _print_summary(rows_out: list[dict[str, Any]], skipped: bool) -> None:
    for row in rows_out:
        score = f"{row['noul']:.2f}" if row["noul"] is not None else "  - "
        print(f"claim-lane: {row['verdict']:<22} {score}  {row['claim_id']}")
    if skipped:
        print("claim-lane: judging skipped (no API key); probes ran, report written")
        return
    totals_rows = [row for row in rows_out]
    conforming = sum(1 for row in totals_rows if row["verdict"] == VERDICT_CONFORMING)
    non_conforming = sum(
        1 for row in totals_rows if row["verdict"] == VERDICT_NON_CONFORMING
    )
    insufficient = sum(
        1 for row in totals_rows if row["verdict"] == VERDICT_INSUFFICIENT
    )
    print(
        f"claim-lane: {len(rows_out)} claims — {conforming} conforming, "
        f"{non_conforming} non_conforming, {insufficient} insufficient_evidence "
        "(shadow: verdicts never fail the run)"
    )


def run(
    *,
    rows: list[ClaimRow] | None = None,
    probes_root: Path | None = None,
    report_dir: Path | None = None,
    artifact_root: Path | None = None,
    client: JudgeClient | None = None,
    probe_results: dict[str, Any] | None = None,
) -> int:
    """The shadow run: validate, probe, judge, classify, report.

    Exit codes: 0 for ANY verdict distribution (the shadow law) and for the
    missing-key skip; 2 for hard setup errors only — a malformed manifest, a
    probe failure, a missing or leaky trace, or a dead judge client.

    ``client`` and ``probe_results`` are the test seams: an injected client
    replaces the network, and injected probe results replace the subprocess
    (``{"__returncode__": 1}`` simulates a probe failure).
    """
    manifest = rows if rows is not None else CLAIMS
    root = probes_root if probes_root is not None else REPO_ROOT
    out_dir = report_dir if report_dir is not None else root / REPORT_DIR_NAME
    try:
        validate_manifest(manifest, probes_root=root)
    except ClaimLaneError as error:
        print(f"claim-lane: malformed manifest: {error}", file=sys.stderr)
        return 2

    traces_dir = artifact_root if artifact_root is not None else out_dir / TRACES_DIR_NAME
    traces_dir.mkdir(parents=True, exist_ok=True)

    if probe_results is None:
        if (code := _run_probes(traces_dir, root)) != 0:
            print(
                f"claim-lane: probe cells failed (pytest exit {code}) — "
                "no report without evidence",
                file=sys.stderr,
            )
            return 2
    elif probe_results.get("__returncode__", 0) != 0:
        print("claim-lane: probe cells failed — no report without evidence", file=sys.stderr)
        return 2
    else:
        try:
            for claim_id, observations in probe_results.items():
                artifact = {"claim_id": claim_id, "observations": observations}
                validate_trace(artifact, expected_id=claim_id)
                (traces_dir / f"{claim_id}.json").write_text(
                    json.dumps(artifact, indent=2), encoding="utf-8"
                )
        except ClaimLaneError as error:
            print(f"claim-lane: trace collection failed: {error}", file=sys.stderr)
            return 2

    try:
        traces = collect_traces(manifest, traces_dir)
    except ClaimLaneError as error:
        print(f"claim-lane: trace collection failed: {error}", file=sys.stderr)
        return 2

    active = client if client is not None else default_client()
    if active is None:
        rows_out = [
            {
                "claim_id": row.id,
                "claim": row.claim,
                "verdict": "skipped",
                "noul": None,
                "model": DEFAULT_MODEL,
                "tokens": 0,
            }
            for row in manifest
        ]
        write_report(out_dir, rows_out, skipped=True, skip_reason=f"{KEY_ENV} is not set")
        _print_summary(rows_out, skipped=True)
        return 0

    try:
        rows_out = judge_rows(manifest, traces, active)
    except ClaimLaneError as error:
        print(f"claim-lane: judging failed: {error}", file=sys.stderr)
        return 2
    write_report(out_dir, rows_out)
    _print_summary(rows_out, skipped=False)
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
