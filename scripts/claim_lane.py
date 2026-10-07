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
import re
import shutil
import subprocess
import sys
import time
import unicodedata
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
    verdict on either side.

    The score domain is [0, 1]; a value outside it — including NaN —
    REFUSES (ride b, the ruled resolution: the refuter's NIT was -1
    reading as confidently non-conforming and 1.5 as conforming). A dead-
    band clamp was tried and ruled the weaker call: it would launder a
    broken judge into a soft verdict row instead of surfacing as the
    named infrastructure failure it is (the F2 partial-report path).
    """
    if not 0.0 <= noul <= 1.0:
        raise ClaimLaneError(f"noul outside [0, 1]: {noul!r}")
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

#: ACCIDENTAL-LEAK PROTECTION (fold-1 F3's honest framing): this vocabulary
#: catches direct judgment language, but a blocklist is bypassable by
#: paraphrase — the refuter admitted 13 of 13 through it, and one leading
#: sentence on a false trace bought +0.31 noul live. The load-bearing
#: refusal is the STRUCTURAL gate below (_structural_refusal): every
#: observation must be a past-tense event sentence. The judge-side
#: anchoring instruction is the demonstrated backstop (it held 0.34, not
#: 0.9, on led false evidence). Behavior vocabulary ("refused", "failed",
#: "returned") is deliberately absent here: the probes observe refusal
#: paths, and those words describe what happened, not whether it agrees
#: with the claim.
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
    # fold-1 additions: translation and leet companions of the above
    "konform",
    "符合",
    "遵从",
    "如文档",
    "一致",
)

#: Leet-fold the normalized text before the vocabulary match, so "c0nforms"
#: and "c0nf0rms" meet the same blocklist as "conforms" (digits folded to
#: their letter lookalikes; used ONLY for matching, never for storage).
_LEET_FOLD = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
)

#: A sentence that opens with one of these is a conclusion or concession,
#: not an event the probe observed.
_NON_EVENT_LEADS = frozenset((
    "because", "although", "though", "however", "therefore", "thus",
    "hence", "so", "which", "meaning", "confirming", "showing", "proving",
    "as",
))

#: Causal connectors asserting why- or therefore-readings.
_CAUSAL_MARKERS = (
    "because", "therefore", "thus", "hence", "consequently", "so that",
    "as a result", "which means", "means that", "showing that",
    "shows that", "proving that", "proves that", "confirming that",
    "confirms that",
)

#: Concessive, comparative and evaluative clauses — verdicts by paraphrase.
_EVALUATION_MARKERS = (
    "as expected", "as anticipated", "as documented", "as claimed",
    "as specified", "as required", "as the readme", "as the guide",
    "as the sentence", "as the claim", "in line with",
    "in agreement with", "consistent with the", "did not differ",
    "does not differ", "do not differ", "matches the", "match the",
    "matched the", "same as the claim", "as it should", "should have",
    "expected", "correct", "incorrect", "properly",
)

#: The closed irregular past set (the regular form is any ...ed word).
_IRREGULAR_PAST = frozenset((
    "was", "were", "ran", "led", "kept", "left", "held", "built",
    "meant", "found", "got", "took", "did", "made", "wrote", "read",
    "set", "put", "became", "began", "came", "went", "saw", "sent",
    "brought", "bought", "caught", "dealt", "felt", "fought", "grew",
    "heard", "hit", "lost", "paid", "said", "sold", "shook", "shot",
    "shut", "spent", "stood", "taught", "told", "thought", "threw",
    "understood", "wore", "won", "withdrew",
))

_PAST_TENSE_RE = re.compile(r"\b[a-z]{2,}ed\b")


def _structural_refusal(normalized: str) -> str | None:
    """The structural gate (fold-1 F3): one observation must read as a
    past-tense event sentence — it opens with an event, carries no causal
    or evaluative clause, and contains a past-tense event verb. Returns
    the refusal reason, or None when the observation passes."""
    tokens = [token for token in re.split(r"[^a-z0-9]+", normalized) if token]
    if tokens and tokens[0] in _NON_EVENT_LEADS:
        return f"opens with {tokens[0]!r}, not an event"
    for marker in _CAUSAL_MARKERS:
        if marker in normalized:
            return f"carries the causal marker {marker!r}"
    for marker in _EVALUATION_MARKERS:
        if marker in normalized:
            return f"carries the evaluation {marker!r}"
    if (
        not any(token in _IRREGULAR_PAST for token in tokens)
        and not _PAST_TENSE_RE.search(normalized)
    ):
        return "carries no past-tense event verb"
    return None


def validate_trace(
    artifact: dict[str, Any], *, expected_id: str | None = None
) -> list[str]:
    """Validate one trace artifact and return its observations.

    An artifact is ``{"claim_id": str, "observations": [str, ...]}`` with at
    least one non-blank observation. Each observation must clear the
    verdict vocabulary (NFKC+casefold+leet-fold matched — accidental-leak
    protection) AND the structural gate (a past-tense event sentence with
    no causal or evaluative clause — the load-bearing refusal). Raises
    ClaimLaneError on any violation — a bad trace fails the probe, never
    the judge.
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
        normalized = unicodedata.normalize("NFKC", observation).casefold()
        folded = normalized.translate(_LEET_FOLD)
        for variant in (normalized, folded):
            for word in _VERDICT_VOCABULARY:
                if word in variant:
                    raise ClaimLaneError(
                        f"trace for {claim_id}: observation {index} carries verdict "
                        f"vocabulary ({word!r})"
                    )
        reason = _structural_refusal(normalized)
        if reason is not None:
            raise ClaimLaneError(f"trace for {claim_id}: observation {index} {reason}")
    return [str(item) for item in observations]


# --- the judge client -----------------------------------------------------

#: Bearer-shaped and token-shaped runs redacted from any error detail
#: before it can be printed (fold-1 F5: a 401 body echoing the
#: Authorization header travelled into stderr through {payload!r}).
_REDACTION_PATTERNS = (
    re.compile(r"(?i)bearer\s+[a-z0-9\-._~+/=]+"),
    re.compile(r"(?i)authorization['\"]?\s*[:=]\s*['\"]?[a-z0-9\-._~+/=]+"),
    re.compile(r"(?i)\b(?:sk|tok|key|token)[-_][a-z0-9]{8,}\b"),
)
_DETAIL_LIMIT = 120


def _safe_detail(material: Any) -> str:
    """Untrusted response material rendered safe for error text: redact
    credential shapes, then truncate. Never let a body reach a message
    unfiltered — run() prints ClaimLaneError text to stderr."""
    if material is None:
        return "unparseable body"
    text = repr(material)
    for pattern in _REDACTION_PATTERNS:
        text = pattern.sub("[redacted]", text)
    if len(text) > _DETAIL_LIMIT:
        text = text[:_DETAIL_LIMIT] + "...[truncated]"
    return text


def _parse_json(text: str) -> Any:
    """Parse a response body defensively: any failure yields None (fold-1
    F2 — an HTML error page behind a proxy crashed the run with a raw
    JSONDecodeError instead of the documented exit contract)."""
    try:
        return json.loads(text)
    except ValueError:
        return None


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
            return response.status, _parse_json(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        # 422 bodies name the offending field — the diagnosis the live
        # contract check needs, so it must travel with the status — but
        # through _safe_detail at the raise site, never raw (F5).
        try:
            detail = error.read().decode("utf-8", "replace")
        except OSError:  # pragma: no cover - body already consumed
            detail = ""
        return error.code, (_parse_json(detail) if detail else None)
    except (urllib.error.URLError, OSError) as error:
        raise ClaimLaneError(f"systemone unreachable: {_safe_detail(error)}") from error


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
                    f"systemone request failed: HTTP {status} {_safe_detail(payload)}"
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
        artifact = _parse_json(path.read_text(encoding="utf-8"))
        if artifact is None:
            raise ClaimLaneError(f"trace artifact is not valid JSON: {path}")
        traces[row.id] = validate_trace(artifact, expected_id=row.id)
    return traces


def judge_rows(
    rows: list[ClaimRow], traces: dict[str, list[str]], client: JudgeClient
) -> tuple[list[dict[str, Any]], ClaimLaneError | None]:
    """Judge every (claim, trace) pair through the client and classify.

    Fold-1 F2's shape: a dead or malformed judge mid-run stops the pass and
    RETURNS the rows already judged plus the failure — verdicts already
    earned are never discarded by a later row's error."""
    judged: list[dict[str, Any]] = []
    for row in rows:
        state = {
            "claim": row.claim,
            "observed_behavior": "\n".join(traces[row.id]),
        }
        try:
            response = client(state, {row.id: conformance_question(row.id)})
            answers = response.get("answers")
            if not isinstance(answers, dict) or not isinstance(
                answers.get(row.id), dict
            ):
                raise ClaimLaneError(f"judge returned no answer for {row.id}")
            noul = _noul_of(answers[row.id])
            # classify rides the guard too: an out-of-domain score refuses
            # (ride b) and must surface through the F2 failure path, never
            # escape as a traceback.
            verdict = classify(noul)
        except ClaimLaneError as error:
            return judged, error
        usage = response.get("usage")
        tokens = usage.get("total_tokens", 0) if isinstance(usage, dict) else 0
        judged.append(
            {
                "claim_id": row.id,
                "claim": row.claim,
                "verdict": verdict,
                "noul": noul,
                "model": response.get("model", DEFAULT_MODEL),
                "tokens": tokens,
            }
        )
    return judged, None


def write_report(
    report_dir: Path,
    rows_out: list[dict[str, Any]],
    *,
    skipped: bool = False,
    skip_reason: str = "",
    error: str = "",
) -> Path:
    """Write .claim-lane/report.json and return its path. The ``error``
    field names a mid-run judging failure (fold-1 F2: the partial report
    is the durable record of what was earned before the failure)."""
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
        # Ride (b): the skip pseudo-verdict is counted, never silently
        # unbucketed (error/not_judged rows stay named by the top-level
        # error field — that divergence is stated, not counted).
        "skipped": sum(1 for row in rows_out if row["verdict"] == "skipped"),
    }
    document = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        "model": DEFAULT_MODEL,
        "skipped": skipped,
        "skip_reason": skip_reason,
        "error": error,
        "rows": rows_out,
        "totals": totals,
    }
    path = report_dir / "report.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def _write_report_guarded(
    report_dir: Path,
    rows_out: list[dict[str, Any]],
    *,
    skipped: bool = False,
    skip_reason: str = "",
    error: str = "",
) -> OSError | None:
    """write_report with the crash path closed (fold-1 F2): a report
    directory that cannot be written (a file squatting on the path, a read-
    only tree) returns the OSError instead of raising it — the summary on
    stdout stays the durable record of what was earned."""
    try:
        write_report(
            report_dir, rows_out, skipped=skipped, skip_reason=skip_reason, error=error
        )
    except OSError as failure:
        print(f"claim-lane: report write failed: {failure}", file=sys.stderr)
        return failure
    return None


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
    probe failure, a missing or leaky trace, an unusable trace/report
    directory, or a dead judge client. The contract admits no third value:
    every failure path on the way out is guarded, and verdicts already
    earned are preserved (printed, and written to the report when the
    report path is usable) before a failure returns (fold-1 F2).

    The traces directory is CLEARED at run start (fold-1 F1): a prior
    run's artifact can never be judged as a later run's evidence.

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
    try:
        shutil.rmtree(traces_dir, ignore_errors=True)
        traces_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(f"claim-lane: trace directory unusable: {error}", file=sys.stderr)
        return 2

    if probe_results is None:
        try:
            code = _run_probes(traces_dir, root)
        except OSError as error:
            print(f"claim-lane: probe run failed to start: {error}", file=sys.stderr)
            return 2
        if code != 0:
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
        except (ClaimLaneError, OSError) as error:
            print(f"claim-lane: trace collection failed: {error}", file=sys.stderr)
            return 2

    try:
        traces = collect_traces(manifest, traces_dir)
    except (ClaimLaneError, OSError) as error:
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
        write_failed = _write_report_guarded(
            out_dir, rows_out, skipped=True, skip_reason=f"{KEY_ENV} is not set"
        )
        _print_summary(rows_out, skipped=True)
        return 2 if write_failed else 0

    judged, failure = judge_rows(manifest, traces, active)
    rows_out = list(judged)
    error_text = ""
    if failure is not None:
        error_text = str(failure)
        print(f"claim-lane: judging failed: {error_text}", file=sys.stderr)
        for offset, remaining in enumerate(manifest[len(judged):]):
            rows_out.append(
                {
                    "claim_id": remaining.id,
                    "claim": remaining.claim,
                    "verdict": "error" if offset == 0 else "not_judged",
                    "noul": None,
                    "model": DEFAULT_MODEL,
                    "tokens": 0,
                }
            )
    write_failed = _write_report_guarded(out_dir, rows_out, error=error_text)
    _print_summary(rows_out, skipped=False)
    if write_failed is not None:
        return 2
    if failure is not None:
        return 2
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
