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
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
KEY_ENV = "TYPESAFE_API_KEY"
REQUEST_TIMEOUT_S = 60
MAX_ATTEMPTS = 5

VERDICT_CONFORMING = "conforming"
VERDICT_NON_CONFORMING = "non_conforming"
VERDICT_INSUFFICIENT = "insufficient_evidence"

CONFORMING_THRESHOLD = 0.70
NON_CONFORMING_THRESHOLD = 0.30

#: The judge answers one question per (claim, trace) pair.
JudgeClient = Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]]
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
        claim="The writer refuses an append that crosses the reservation at each append.",
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
        return error.code, None


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

    def client(state: dict[str, Any], questions: list[dict[str, Any]]) -> dict[str, Any]:
        body = json.dumps(
            {"model": model, "state": state, "questions": questions}
        ).encode("utf-8")
        delay = 1.0
        for attempt in range(1, max_attempts + 1):
            status, payload = do_post(url, body, api_key, timeout_s)
            if status == 200 and isinstance(payload, dict):
                return payload
            if status not in (429, 529):
                raise ClaimLaneError(f"systemone request failed: HTTP {status}")
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
    questions: list[dict[str, Any]],
    *,
    client: JudgeClient | None = None,
) -> dict[str, Any]:
    """Pose questions against state through the (injected or default)
    client. No client and no key is a hard setup error."""
    active = client if client is not None else default_client()
    if active is None:
        raise ClaimLaneError(f"no judge client: {KEY_ENV} is not set")
    return active(state, questions)
