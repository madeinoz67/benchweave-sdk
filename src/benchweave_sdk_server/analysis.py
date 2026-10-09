"""The analysis dataset and its window statistics (issue #286, I4a).

The one structural decision of the I4 design record: an analysis request
names 1..n published captures, and this module extracts ONE numeric series
per capture — the minimal bridge from the landed single-stream capture
format to a multi-series view (capture-set composition, no on-disk format
change; a future multi-variable capture format slots in behind the same
loader interface).

Everything here is pure with respect to host state: reads only the
published capture root, imports no plugin code, reads no clock (a report
re-exported from the same sources re-derives the same numbers). The
statistics follow definition ``benchweave-analysis/1``:

- the window is inclusive ``[lo, hi]`` (the fork's ``t < lo || t > hi``
  skip rule);
- a sample is NULL iff it is NaN — binary64's own "no value" — and nulls
  are counted and excluded, never coerced (the fork's null-to-zero power
  coercion is a killed behaviour, not a precedent);
- every statistic's denominator is the non-null in-window count, and the
  denominators travel WITH the values (``count``, ``null_count``, the
  window) so a reader can never mistake the population a number came
  from (G4);
- host-computed values carry ``uncertainty: "unknown"`` — a propagated
  bound would presume operand-error independence nothing here can
  evidence (A02), so no analysis value ever carries a fabricated
  accuracy.

The loader never materialises a whole series: primaries are read in fixed
chunks (a ``struct.unpack_from`` loop) and statistics accumulate in one
pass. It never reads the DECIMATED series — ``capture_series``'s
decimation is a presentation reduction, and statistics over decimated
points would be wrong by construction.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The definition id printed on every report and carried by every stats
#: object: the numbers mean exactly this computation, nothing else.
ANALYSIS_DEFINITION = "benchweave-analysis/1"

#: The edge-timing definition (I4b.1 AR-2): rise/settle numbers mean
#: exactly the fork-compatible step computation pinned in the I4b design
#: record §1.1 — nothing else.
EDGE_DEFINITION = "benchweave-edge/1"

#: The assertion definition (I4b.1 AR-7): a verdict means exactly this
#: min/max evaluation over the entry's window statistics.
ASSERT_DEFINITION = "benchweave-assert/1"

#: The per-event analysis overlay's format id (I4b.1 AR-8): the file
#: holds operator annotation only (markers now, additive keys later);
#: absent or unparseable reads as no overlay, never a load precondition.
ANALYSIS_OVERLAY_FORMAT = "standalone-analysis/1"

#: A marker label is one uppercase A-Z character (the fork's own regex
#: shape) — 26 rows bound the overlay.
MARKER_LABEL_RE = re.compile(r"^[A-Z]$")

#: The settle band's display default (the fork's own fallback): an
#: operator-editable statistical band parameter printed on every block,
#: explicitly NOT a commissioned envelope (A02: nothing protective keys
#: on it).
SETTLE_PCT_DEFAULT = 2.0

#: Samples read per chunk (64 KiB): the loader's memory bound. A
#: presentation constant, not a commissioned envelope (A02 posture).
_CHUNK_SAMPLES = 8192


class AnalysisRefusal(ValueError):
    """A refusal carrying its ``standalone_report_*`` message prefix.

    The loader is pure and raises ``ValueError`` subclasses only; the seam
    maps each prefix onto its interface-0.1.0 code (STD-4's posture).
    """


@dataclass(frozen=True)
class SeriesSource:
    """One loaded capture: its published series identity, read-only.

    The samples themselves are NOT held — :func:`series_samples` streams
    them from the primary in chunks.
    """

    capture_id: str
    unit: str
    sample_interval_s: float
    sample_count: int
    manifest_sha256: str
    manifest: dict[str, Any]
    metadata: dict[str, Any]
    primary: Path


@dataclass(frozen=True)
class RegionStats:
    """Window statistics per :data:`ANALYSIS_DEFINITION`.

    ``min``/``max``/``pp``/``mean``/``rms`` are ``None`` exactly when the
    window holds no non-null sample — an honest absence, never a silent
    zero.
    """

    definition: str
    lo: float | None
    hi: float | None
    count: int
    null_count: int
    min: float | None
    max: float | None
    pp: float | None
    mean: float | None
    rms: float | None
    uncertainty: str


@dataclass(frozen=True)
class EdgeTiming:
    """Edge timing for one window per :data:`EDGE_DEFINITION` (I4b.1).

    The region is the window's NON-NULL samples in acquisition order (the
    fork's ``regionPoints`` semantics — nulls drop out before the count).
    ``detected`` is ``False`` for a region of fewer than 3 samples or a
    flat step (the guard); the timing fields are then ``None`` — an
    honest negative, never a zero rise. ``rise_time`` is ``None`` when
    either crossing is absent; ``settle_time`` is ``0.0`` when nothing in
    scope left the band, ``None`` when the region's last sample is still
    outside it ("not settled within the region"). Every row carries its
    denominators (``n``, ``head_n``, ``tail_n``, ``settle_pct``, the
    window).
    """

    definition: str
    lo: float | None
    hi: float | None
    n: int
    head_n: int
    tail_n: int
    settle_pct: float
    detected: bool
    rising: bool | None
    baseline: float | None
    final: float | None
    step: float | None
    t10: float | None
    t90: float | None
    rise_time: float | None
    settle_time: float | None
    uncertainty: str


@dataclass(frozen=True)
class AssertionResult:
    """One min/max assertion's verdict per :data:`ASSERT_DEFINITION`
    (I4b.1 AR-7).

    ``not_evaluated`` is the honest verdict for an empty window (count 0
    — the target series contributed no samples): never ``pass``. A failed
    row names its machine-readable ``reasons`` (``below_min``,
    ``above_max``); verdicts carry the window denominators they were
    computed over.
    """

    definition: str
    capture_id: str
    verdict: str
    min: float | None
    max: float | None
    actual_min: float | None
    actual_max: float | None
    reasons: tuple[str, ...]
    lo: float | None
    hi: float | None
    count: int
    null_count: int
    uncertainty: str


def _read_metadata(event: Path) -> dict[str, Any]:
    """The event's ``metadata.json`` as a dict, ``{}`` when absent or
    unparseable (the library's honest-defaults rule: the annotation
    authority is not a load precondition)."""
    try:
        payload = json.loads((event / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_series_set(root: Path, capture_ids: list[str] | tuple[str, ...]) -> list[SeriesSource]:
    """Load 1..n published captures as analysis series sources.

    Refuses (``standalone_report_*`` prefix, mapped by the seam) for an
    unknown id, an unparseable manifest, a non-waveform format, a primary
    whose length contradicts the manifest's sample_count, and a waveform
    manifest missing its corpus-mandated fields.
    """
    sources: list[SeriesSource] = []
    for capture_id in capture_ids:
        sources.append(_load_one(Path(root), capture_id))
    return sources


def _load_one(root: Path, capture_id: str) -> SeriesSource:
    event = root / capture_id
    manifest_path = event / "manifest.json"
    if not capture_id or not manifest_path.is_file():
        raise AnalysisRefusal(f"standalone_report_capture_unknown: {capture_id}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise AnalysisRefusal(
            f"standalone_report_manifest_unreadable: {capture_id} ({exc})"
        ) from exc
    if not isinstance(manifest, dict):
        raise AnalysisRefusal(
            f"standalone_report_manifest_unreadable: {capture_id} (not an object)"
        )
    fmt = manifest.get("format")
    if fmt != "waveform_f64le":
        raise AnalysisRefusal(
            "standalone_report_format_unsupported: "
            f"{capture_id} ({fmt or 'unknown'}); analysis serves waveform_f64le "
            "primaries"
        )
    count = manifest.get("sample_count")
    interval = manifest.get("sample_interval_s")
    unit = manifest.get("unit")
    if (
        type(count) is not int
        or count < 1
        or isinstance(interval, bool)
        or not isinstance(interval, (int, float))
        or not interval > 0
        or not math.isfinite(interval)
        or not isinstance(unit, str)
        or not unit
    ):
        raise AnalysisRefusal(
            f"standalone_report_manifest_incomplete: {capture_id} (a waveform "
            "manifest requires sample_count >= 1, a positive finite "
            "sample_interval_s and a non-empty unit)"
        )
    primary = event / f"{capture_id}.f64"
    if not primary.is_file():
        raise AnalysisRefusal(f"standalone_report_primary_missing: {capture_id}")
    actual_length = primary.stat().st_size
    if actual_length != count * 8:
        raise AnalysisRefusal(
            f"standalone_report_primary_length: {capture_id} declares "
            f"sample_count {count} ({count * 8} bytes) but the primary holds "
            f"{actual_length} bytes"
        )
    return SeriesSource(
        capture_id=capture_id,
        unit=str(unit),
        sample_interval_s=float(interval),
        sample_count=count,
        manifest_sha256=str(manifest.get("sha256", "")),
        manifest=manifest,
        metadata=_read_metadata(event),
        primary=primary,
    )


def series_samples(source: SeriesSource) -> Iterator[tuple[float, float]]:
    """The source's ``(t, value)`` samples in acquisition order, read in
    chunks — never the decimated series, never a materialised list."""
    interval = source.sample_interval_s
    with source.primary.open("rb") as stream:
        index = 0
        while True:
            chunk = stream.read(_CHUNK_SAMPLES * 8)
            if not chunk:
                return
            for value in struct.unpack_from(f"<{len(chunk) // 8}d", chunk):
                yield index * interval, value
                index += 1


def region_stats(
    samples: Iterator[tuple[float, float]], *, lo: float | None, hi: float | None
) -> RegionStats:
    """One pass over ``samples``: the definition-1 statistics for the
    inclusive window ``[lo, hi]`` (``None`` bounds are unbounded ends)."""
    count = 0
    null_count = 0
    total = 0.0
    total_sq = 0.0
    low: float | None = None
    high: float | None = None
    for t, value in samples:
        if lo is not None and t < lo:
            continue
        if hi is not None and t > hi:
            continue
        if math.isnan(value):
            null_count += 1
            continue
        count += 1
        total += value
        total_sq += value * value
        if low is None or value < low:
            low = value
        if high is None or value > high:
            high = value
    mean = total / count if count else None
    rms = math.sqrt(total_sq / count) if count else None
    return RegionStats(
        definition=ANALYSIS_DEFINITION,
        lo=lo,
        hi=hi,
        count=count,
        null_count=null_count,
        min=low,
        max=high,
        pp=(high - low) if low is not None and high is not None else None,
        mean=mean,
        rms=rms,
        uncertainty="unknown",
    )


def scan_series(
    source: SeriesSource, *, lo: float | None = None, hi: float | None = None
) -> tuple[RegionStats, str]:
    """One chunked pass over the primary: the window statistics AND the
    recomputed sha256 together (the digest check is AR-4b's rule enforced
    at source — bytes that changed after publication refuse before any
    report renders them)."""
    hasher = hashlib.sha256()

    def hashed() -> Iterator[tuple[float, float]]:
        interval = source.sample_interval_s
        with source.primary.open("rb") as stream:
            index = 0
            while True:
                chunk = stream.read(_CHUNK_SAMPLES * 8)
                if not chunk:
                    return
                hasher.update(chunk)
                for value in struct.unpack_from(f"<{len(chunk) // 8}d", chunk):
                    yield index * interval, value
                    index += 1

    stats = region_stats(hashed(), lo=lo, hi=hi)
    digest = hasher.hexdigest()
    if digest != source.manifest_sha256:
        raise AnalysisRefusal(
            f"standalone_report_primary_mismatch: {source.capture_id} primary "
            f"digest {digest} does not match its manifest "
            f"{source.manifest_sha256}; the capture changed after publication"
        )
    return stats, digest


def windowed_points(
    source: SeriesSource,
    *,
    lo: float | None,
    hi: float | None,
    limit: int,
) -> list[tuple[float, float]]:
    """The windowed plot points in ONE verified, bounded pass (fold wave 1,
    rows 4 and 5).

    Verified: the chunks are hashed as they are read and the recomputed
    digest must still match the manifest — this is the SECOND read of the
    primary (the statistics pass was the first), and a primary mutated
    between the passes refuses here rather than feeding unverified bytes
    to the plot. Bounded: the window list refuses the moment it would
    exceed ``limit`` — the ceiling binds the ALLOCATION, never just the
    response after a full materialisation."""
    if limit < 1:
        raise ValueError("the windowed-point limit must be positive")
    hasher = hashlib.sha256()
    points: list[tuple[float, float]] = []
    interval = source.sample_interval_s
    with source.primary.open("rb") as stream:
        index = 0
        while True:
            chunk = stream.read(_CHUNK_SAMPLES * 8)
            if not chunk:
                break
            hasher.update(chunk)
            for value in struct.unpack_from(f"<{len(chunk) // 8}d", chunk):
                t = index * interval
                index += 1
                if lo is not None and t < lo:
                    continue
                if hi is not None and t > hi:
                    continue
                points.append((t, value))
                if len(points) > limit:
                    raise AnalysisRefusal(
                        "standalone_report_window_too_large: "
                        f"{source.capture_id} window exceeds the {limit}-sample "
                        "plot ceiling (narrow the window)"
                    )
    digest = hasher.hexdigest()
    if digest != source.manifest_sha256:
        raise AnalysisRefusal(
            f"standalone_report_primary_mismatch: {source.capture_id} primary "
            f"digest {digest} does not match its manifest "
            f"{source.manifest_sha256}; the capture changed after publication"
        )
    return points


def _cross_time(
    region: list[tuple[float, float]], level: float, rising: bool
) -> float | None:
    """The first interpolated crossing of ``level`` in the step direction
    (linear between bracketing samples; a level the region never crosses
    yields ``None``). A bracketing segment with no span (both samples at
    the level) crosses at the segment's first sample."""
    for (ta, va), (tb, vb) in zip(region, region[1:], strict=False):
        if rising:
            if va <= level <= vb:
                span = vb - va
                if span == 0:
                    return ta
                return ta + (level - va) * (tb - ta) / span
        elif va >= level >= vb:
            span = va - vb
            if span == 0:
                return ta
            return ta + (va - level) * (tb - ta) / span
    return None


def edge_analysis(
    samples: Iterator[tuple[float, float]],
    *,
    lo: float | None,
    hi: float | None,
    settle_pct: float,
) -> EdgeTiming:
    """Edge timing over one window per :data:`EDGE_DEFINITION` (I4b.1 AR-2).

    Pure and single-pass over ``samples``: the region is the window's
    non-null samples in acquisition order, the baseline/final are the
    means of the first/last ``max(1, floor(n * 0.15))`` region samples,
    and the flat guard ``|step| < 0.005 * max(|baseline|, |final|, 1e-12)``
    (a NaN step fails the comparison and stays non-flat only through
    non-finite means — see the fx-step-nocross arm) yields an honest
    ``detected: False``. The caller bounds the sample count it passes
    (the report's plot ceiling already bounds the windowed stream).

    ``settle_pct`` is the band percentage around ``final``; the scan runs
    from ``t10`` (or the region start when the crossing is absent) and
    ``settle_time`` measures from that same origin.
    """
    region = [
        (t, value)
        for t, value in samples
        if (lo is None or t >= lo)
        and (hi is None or t <= hi)
        and not math.isnan(value)
    ]
    n = len(region)
    head_n = max(1, math.floor(n * 0.15)) if n else 0
    tail_n = max(1, math.floor(n * 0.15)) if n else 0

    def row(
        *,
        detected: bool,
        rising: bool | None = None,
        baseline: float | None = None,
        final: float | None = None,
        step: float | None = None,
        t10: float | None = None,
        t90: float | None = None,
        rise_time: float | None = None,
        settle_time: float | None = None,
    ) -> EdgeTiming:
        return EdgeTiming(
            definition=EDGE_DEFINITION,
            lo=lo,
            hi=hi,
            n=n,
            head_n=head_n,
            tail_n=tail_n,
            settle_pct=settle_pct,
            detected=detected,
            rising=rising,
            baseline=baseline,
            final=final,
            step=step,
            t10=t10,
            t90=t90,
            rise_time=rise_time,
            settle_time=settle_time,
            uncertainty="unknown",
        )

    if n < 3:
        return row(detected=False)
    baseline = sum(value for _, value in region[:head_n]) / head_n
    final = sum(value for _, value in region[n - tail_n :]) / tail_n
    step = final - baseline
    if abs(step) < 0.005 * max(abs(baseline), abs(final), 1e-12):
        # The flat guard, exactly as pinned. A NON-FINITE step compares
        # False against its own reference (inf < inf is False, NaN < x is
        # False) and so does NOT take this branch: the row stays a
        # transition carrying the non-finite means and null crossings
        # rather than laundering them into "no edge" (the fx-step-nocross
        # arm pins that outcome).
        return row(detected=False, baseline=baseline, final=final, step=step)
    rising = step > 0
    t10 = _cross_time(region, baseline + 0.10 * step, rising)
    t90 = _cross_time(region, baseline + 0.90 * step, rising)
    rise_time = t90 - t10 if t10 is not None and t90 is not None else None
    band = settle_pct / 100.0 * abs(step)
    low_band, high_band = final - band, final + band
    scope = 0
    if t10 is not None:
        # The region is t-ascending: the scope starts at the first sample
        # at or after the interpolated t10.
        while scope < n and region[scope][0] < t10:
            scope += 1
    t0 = t10 if t10 is not None else region[0][0]
    last_outside: int | None = None
    for index in range(scope, n):
        value = region[index][1]
        if value < low_band or value > high_band:
            last_outside = index
    if last_outside is None:
        settle_time: float | None = 0.0
    elif last_outside == n - 1:
        settle_time = None  # not settled within the region
    else:
        settle_time = region[last_outside + 1][0] - t0
    return row(
        detected=True,
        rising=rising,
        baseline=baseline,
        final=final,
        step=step,
        t10=t10,
        t90=t90,
        rise_time=rise_time,
        settle_time=settle_time,
    )


def evaluate_assertions(
    spec: list[dict[str, Any]], entries: dict[str, RegionStats]
) -> list[AssertionResult]:
    """Evaluate min/max assertion rows against the request's own window
    statistics (I4b.1 AR-7).

    Each spec row is ``{capture_id, min?, max?}`` with at least one
    bound. The target must be one of the request's source captures — the
    miss is refused (``standalone_report_assert_target``) rather than
    rendered ``found: false`` forever; bounds must be finite and at least
    one present (``standalone_report_assert_bound``, the B-F4 family
    refused at admission like the window). The verdict reads the entry's
    window ``RegionStats``: ``pass`` iff every present bound holds,
    ``fail`` with machine-readable reasons otherwise, and
    ``not_evaluated`` when the window counted no samples — never
    ``pass``.
    """
    results: list[AssertionResult] = []
    for row in spec:
        capture_id = str(row.get("capture_id", ""))
        if capture_id not in entries:
            raise AnalysisRefusal(
                f"standalone_report_assert_target: {capture_id} is not among "
                f"the request's captures ({', '.join(entries)})"
            )
        minimum = row.get("min")
        maximum = row.get("max")
        if minimum is None and maximum is None:
            raise AnalysisRefusal(
                f"standalone_report_assert_bound: {capture_id} carries "
                "neither min nor max; at least one bound is required"
            )
        for name, bound in (("min", minimum), ("max", maximum)):
            if bound is not None and not math.isfinite(float(bound)):
                raise AnalysisRefusal(
                    f"standalone_report_assert_bound: {capture_id} {name} "
                    f"{bound} is not finite; bounds must be finite numbers"
                )
        stats = entries[capture_id]
        reasons: list[str] = []
        if stats.count > 0:
            if minimum is not None and (stats.min is None or stats.min < minimum):
                reasons.append("below_min")
            if maximum is not None and (stats.max is None or stats.max > maximum):
                reasons.append("above_max")
        results.append(
            AssertionResult(
                definition=ASSERT_DEFINITION,
                capture_id=capture_id,
                verdict="not_evaluated" if stats.count == 0 else (
                    "fail" if reasons else "pass"
                ),
                min=minimum,
                max=maximum,
                actual_min=stats.min if stats.count else None,
                actual_max=stats.max if stats.count else None,
                reasons=tuple(reasons),
                lo=stats.lo,
                hi=stats.hi,
                count=stats.count,
                null_count=stats.null_count,
                uncertainty="unknown",
            )
        )
    return results


def read_markers(event: Path) -> list[dict[str, Any]]:
    """The event's stored marker rows, ``[]`` when absent or unparseable
    (the library's honest-defaults rule: the overlay is operator
    annotation, never a load precondition). Only well-formed rows
    survive — anything else in the file reads as no overlay rather than
    half an overlay."""
    try:
        payload = json.loads((event / "analysis.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    rows = payload.get("markers")
    if not isinstance(rows, list):
        return []
    kept: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label, t = row.get("label"), row.get("t")
        note = row.get("note", "")
        if (
            isinstance(label, str)
            and MARKER_LABEL_RE.fullmatch(label) is not None
            and isinstance(t, (int, float))
            and not isinstance(t, bool)
            and math.isfinite(float(t))
            and isinstance(note, str)
        ):
            kept.append({"label": label, "t": float(t), "note": note})
    return sorted(kept, key=lambda row: row["label"])


def resolve_markers(
    manifest: dict[str, Any], rows: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Validate and normalise incoming marker rows against the capture's
    own time base: labels are single uppercase A-Z (one row per label,
    the LAST duplicate wins — the fork's ``placeMarker`` semantics), ``t``
    is finite and lies inside ``[0, (sample_count - 1) *
    sample_interval_s]`` (a marker that names no point the capture can
    display refuses), and the stored rows are sorted by label so
    re-export is stable. ``note`` is free text (no invented cap) and
    escapes at render, never here."""
    count = manifest.get("sample_count")
    interval = manifest.get("sample_interval_s")
    if (
        type(count) is not int
        or count < 1
        or isinstance(interval, bool)
        or not isinstance(interval, (int, float))
        or not interval > 0
        or not math.isfinite(float(interval))
    ):
        raise AnalysisRefusal(
            "standalone_report_marker_invalid: the capture's manifest "
            "declares no usable sample grid (sample_count/sample_interval_s)"
        )
    span = (count - 1) * float(interval)
    resolved: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise AnalysisRefusal(
                "standalone_report_marker_invalid: a marker row is not an "
                "object ({label, t, note})"
            )
        label = row.get("label")
        if not isinstance(label, str) or MARKER_LABEL_RE.fullmatch(label) is None:
            raise AnalysisRefusal(
                f"standalone_report_marker_invalid: label {label!r} is not a "
                "single uppercase character A-Z"
            )
        t = row.get("t")
        if (
            isinstance(t, bool)
            or not isinstance(t, (int, float))
            or not math.isfinite(float(t))
        ):
            raise AnalysisRefusal(
                f"standalone_report_marker_invalid: marker {label} carries a "
                f"non-finite t ({t!r})"
            )
        if not 0.0 <= float(t) <= span:
            raise AnalysisRefusal(
                f"standalone_report_marker_invalid: marker {label} names t "
                f"{float(t)} outside the capture's displayable time base "
                f"[0, {span}] ((sample_count - 1) x sample_interval_s)"
            )
        note = row.get("note", "")
        if not isinstance(note, str):
            raise AnalysisRefusal(
                f"standalone_report_marker_invalid: marker {label} carries a "
                "non-string note"
            )
        resolved[label] = {"label": label, "t": float(t), "note": note}
    return [resolved[label] for label in sorted(resolved)]
