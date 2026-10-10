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
from collections.abc import Iterable, Iterator, Mapping, Sequence
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

#: The power definition (I4b.2 AR-3/AR-10/AR-11): a power row means
#: exactly the unit-keyed V/I pairing, per-sample product and
#: gap-visible trapezoidal integrals pinned in the I4b design record
#: §1.4 — nothing else.
POWER_DEFINITION = "benchweave-power/1"

#: The four named power modes (the record §1.4): presentations over the
#: rail rows, not separate computations — the request names ONE.
POWER_MODES = ("battery", "dc-dc", "sleep", "load-step")

#: The unit vocabulary (the fork's own ``unitKind`` sets): lowercased
#: with µ/μ folded to u. Q8's ruling keys pairing on unit/quantity and
#: NEVER on names — the fork's ``pickBy``/``guessRailPairs`` name regexes
#: are not carried.
_CURRENT_UNITS = frozenset({"a", "ma", "ua", "na"})
_VOLTAGE_UNITS = frozenset({"v", "mv", "uv", "kv"})

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
    the level) crosses at the segment's first sample; an interpolation
    that lands non-finite (an inf-to-inf bracket under a finite level)
    yields the absent crossing, never a NaN float (A-F1)."""
    for (ta, va), (tb, vb) in zip(region, region[1:], strict=False):
        if rising:
            if va <= level <= vb:
                span = vb - va
                if span == 0:
                    return ta
                crossing = ta + (level - va) * (tb - ta) / span
                return crossing if math.isfinite(crossing) else None
        elif va >= level >= vb:
            span = va - vb
            if span == 0:
                return ta
            crossing = ta + (va - level) * (tb - ta) / span
            return crossing if math.isfinite(crossing) else None
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
    if not all(math.isfinite(value) for value in (baseline, final, step)):
        # A-F1: non-finite means cannot be TIMED — the whole timing
        # family (crossings AND settle) is null. Never a NaN-float
        # crossing where the contract names null, and never settle_time
        # 0.0 ("settled instantly") over poisoned data (the fx-nf-*
        # arms). The row keeps its honest non-finite means: inf is a
        # value (B-F8) and renders as such.
        return row(detected=True, baseline=baseline, final=final, step=step)
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
            if bound is None:
                continue
            # A-F7: a bool launders to 1.0 via float(), and a numeric
            # STRING passes float() only to raise TypeError outside the
            # ValueError family later — both refuse typed here.
            if isinstance(bound, bool) or not isinstance(bound, (int, float)):
                raise AnalysisRefusal(
                    f"standalone_report_assert_bound: {capture_id} {name} "
                    f"{bound!r} is not a number; bounds must be finite numbers"
                )
            if not math.isfinite(float(bound)):
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


def read_markers(event: Path) -> list[Any]:
    """The event's stored marker rows as written, ``[]`` when the file is
    absent, unparseable, or carries no markers list (the library's
    honest-defaults rule: the overlay is operator annotation, never a
    load precondition). This read applies NO discipline — a hand-edited
    file's rows pass through verbatim (a mixed file yields its good rows
    AND its bad ones), and the EXPORT path runs every row through
    :func:`resolve_markers`'s span/label discipline so a violating row
    refuses typed exactly like the request path (A-F3; the "reads as no
    overlay" claim is for file-level damage only)."""
    try:
        payload = json.loads((event / "analysis.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    rows = payload.get("markers")
    if not isinstance(rows, list):
        return []
    return list(rows)


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


def decimated_extent(source: SeriesSource, columns: int) -> list[tuple[float, float]]:
    """The source's FULL extent reduced to per-column min/max pairs in
    one chunked, digest-verified pass (I4b.1 AR-9e) — the context chart's
    entry point, existing so a report can span captures up to the raw
    sample ceiling without materialising them (the windowed path's
    REPORT_PLOT_SAMPLE_CEILING cannot bound a full-extent path).

    Point-for-point parity with
    ``plots.decimate_minmax(list(series_samples(source)), columns)`` is
    load-bearing (the tie-breaks): the FIRST minimum and the LAST
    maximum per column, a single-point column emitting one point, the
    pair ordered by x, and the identity at or below the budget. The x
    extent derives from the manifest's own grid — ``[0, (sample_count -
    1) * sample_interval_s]`` — which is exactly what the materialised
    list's first and last times are, so the column arithmetic matches
    bit-for-bit. decimate_minmax's degenerate x-extent branch (all
    points at one x) cannot fire here: count > columns implies count >=
    2, and the loader's uniform grid is strictly increasing. Memory is
    O(columns): only the running per-column candidates are held.
    """
    if columns < 1:
        raise ValueError("the decimation column budget must be positive")
    hasher = hashlib.sha256()
    interval = source.sample_interval_s
    count = source.sample_count

    def verify() -> None:
        digest = hasher.hexdigest()
        if digest != source.manifest_sha256:
            raise AnalysisRefusal(
                f"standalone_report_primary_mismatch: {source.capture_id} "
                f"primary digest {digest} does not match its manifest "
                f"{source.manifest_sha256}; the capture changed after "
                "publication"
            )

    if count <= columns:
        # The identity branch (at or below the budget, decimate_minmax
        # returns the whole bounded list).
        points: list[tuple[float, float]] = []
        with source.primary.open("rb") as stream:
            index = 0
            while True:
                chunk = stream.read(_CHUNK_SAMPLES * 8)
                if not chunk:
                    break
                hasher.update(chunk)
                for value in struct.unpack_from(f"<{len(chunk) // 8}d", chunk):
                    points.append((index * interval, value))
                    index += 1
        verify()
        return points
    first_x = 0.0
    last_x = (count - 1) * interval
    width = (last_x - first_x) / columns
    reduced: list[tuple[float, float]] = []
    # The current column's candidates: low = FIRST minimum (strictly-less
    # replaces), high = LAST maximum (>= replaces) — decimate_minmax's
    # tie rules. ``last_point`` mirrors max(reversed(column)): a column
    # whose LAST point is NaN keeps that NaN as its maximum (nothing
    # earlier in the back-scan can compare against it).
    current_column = 0
    low: tuple[float, float] | None = None
    high: tuple[float, float] | None = None
    last_point: tuple[float, float] | None = None

    def flush() -> None:
        nonlocal low, high
        assert low is not None and high is not None
        if last_point is not None and math.isnan(last_point[1]):
            high = last_point
        if low == high:
            reduced.append(low)
        else:
            reduced.extend([low, high] if low[0] <= high[0] else [high, low])
        low = None
        high = None

    with source.primary.open("rb") as stream:
        index = 0
        while True:
            chunk = stream.read(_CHUNK_SAMPLES * 8)
            if not chunk:
                break
            hasher.update(chunk)
            for value in struct.unpack_from(f"<{len(chunk) // 8}d", chunk):
                point = (index * interval, value)
                index += 1
                column = min(columns - 1, int((point[0] - first_x) / width))
                if column != current_column:
                    flush()
                    current_column = column
                if low is None or value < low[1]:
                    low = point
                # ``high`` mirrors ``max(reversed(column))`` — the LAST
                # maximum — under a forward scan: a finite value replaces
                # on >=, and a NaN holding the slot is displaced by ANY
                # later point (in the back-scan a NaN survives only as
                # the column's final point, which the flush rule below
                # supplies separately).
                if high is None or math.isnan(high[1]) or value >= high[1]:
                    high = point
                last_point = point
    flush()
    verify()
    return reduced


def unit_kind(unit: str) -> str:
    """Classify one unit string as ``current``/``voltage``/``other``.

    The fork's own vocabulary, verbatim: lowercase, µ/μ→u, exact set
    membership — no stripping, no prefix matching (``W`` and ``Ω``
    classify ``other`` and stay unpairable). This is the ONLY thing that
    decides a series' rail role (Q8's ruling: never names).
    """
    normalized = unit.lower().replace("µ", "u").replace("μ", "u")
    if normalized in _CURRENT_UNITS:
        return "current"
    if normalized in _VOLTAGE_UNITS:
        return "voltage"
    return "other"


def product_unit(v_unit: str | None, i_unit: str) -> str:
    """The power label for one rail, derived from the rail's ACTUAL units
    (the B-F2 fold): ``W`` only when both sides are base units (V·A is W
    by definition); any scaled rail prints its unit product — ``V·mA``,
    ``mV·A`` — and the section never asserts W over a mW-scale value.
    Numeric unit SCALING is deliberately absent (a disclosed row-call:
    the labels are honest, the magnitudes stay raw)."""
    if v_unit == "V" and i_unit == "A":
        return "W"
    return f"{v_unit}·{i_unit}" if v_unit is not None else i_unit


def _fsum(terms: Sequence[float]) -> float:
    """Exact summation with the one-case fallback (the A-F1 fold):
    ``math.fsum`` raises ``ValueError`` on mixed +inf/-inf — the only
    input whose EXACT sum does not exist — and that CPython message
    used to escape to the wire as an untyped refusal. The fallback is
    the sequential IEEE sum, which yields the family's honest
    non-finite (nan for both signs of infinity, the same value the
    landed statistics' accumulator produces) — rendered as
    ``n/a (non-finite)``, never laundered to a number and never raised
    (B-F8: inf is a value; a mean over both signs of it is NaN)."""
    try:
        return math.fsum(terms)
    except ValueError:
        return sum(terms)


@dataclass(frozen=True)
class IntegralResult:
    """One trapezoidal integral with its coverage denominators (AR-10).

    ``value`` is the integral in value·seconds over the COUNTED segments
    only (the caller converts to Ah/Wh); ``integrated_span_s`` is the
    summed ``b - a`` of those segments and ``dropped_segments`` counts
    the window-intersecting segments dropped for an excluded (null)
    endpoint — a gapped integral is visibly partial, never interpolated
    across. A counted-segment count of 0 yields ``value=None``: no data
    integrated is an absence, not zero energy.
    """

    definition: str
    value: float | None
    integrated_span_s: float
    counted_segments: int
    dropped_segments: int
    uncertainty: str


def trapezoid_integral(
    points: Iterable[tuple[float, float]], lo: float | None, hi: float | None
) -> IntegralResult:
    """The fork's trapezoid with the gap rule added (the record §1.4).

    Per-segment trapezoid clipped to the inclusive window with LINEAR
    INTERPOLATION at the clipped bounds (``a = max(t0, lo)``,
    ``b = min(t1, hi)``; a segment with ``b <= a`` lies outside the
    window and is neither counted nor dropped). A segment whose either
    endpoint is null (NaN) is DROPPED — never interpolated across missing
    data. The fork's ``t1 - t0 || 1`` zero-span substitution is not
    carried: the span division is safe *is refused unless* the loader's
    own interval validation holds (a non-positive or non-finite
    ``sample_interval_s`` refuses at load, so a fed grid is strictly
    increasing), and ``t1 <= t0`` segments are skipped defensively
    rather than substituted.
    """
    areas: list[float] = []
    spans: list[float] = []
    dropped = 0
    previous: tuple[float, float] | None = None
    for sample in points:
        if previous is None:
            previous = sample
            continue
        (t0, v0), (t1, v1) = previous, sample
        previous = sample
        if t1 <= t0:
            continue
        a = t0 if lo is None else max(t0, lo)
        b = t1 if hi is None else min(t1, hi)
        if b <= a:
            continue
        if math.isnan(v0) or math.isnan(v1):
            dropped += 1
            continue
        # Linear interpolation at the clipped bounds (identity when the
        # bound lands on the segment's own endpoint).
        f_a = v0 if a == t0 else v0 + (v1 - v0) * (a - t0) / (t1 - t0)
        f_b = v1 if b == t1 else v0 + (v1 - v0) * (b - t0) / (t1 - t0)
        areas.append((f_a + f_b) / 2.0 * (b - a))
        spans.append(b - a)
    # Exact summation (the record's <=4-ulp rule): a running float sum
    # over hundreds of segments drifts past 4 ulp of the closed form on
    # the uniform grid (measured: ~40 ulp at N = 360); _fsum sums the
    # per-segment terms exactly (mixed +/-inf falls back to the honest
    # non-finite), and each per-segment span is itself exact by Sterbenz
    # (consecutive grid times differ by far less than a factor of two),
    # so the total lands within 1 ulp.
    counted = len(areas)
    return IntegralResult(
        definition=POWER_DEFINITION,
        value=_fsum(areas) if counted else None,
        integrated_span_s=_fsum(spans),
        counted_segments=counted,
        dropped_segments=dropped,
        uncertainty="unknown",
    )


@dataclass(frozen=True)
class PowerRail:
    """One V/I rail's rows per :data:`POWER_DEFINITION` (the record §1.4).

    ``count``/``null_count`` are the PAIR counters (in-window sample
    pairs with both / either side non-null); the power and paired
    statistics are honest absences on an i-only rail — ``reason`` names
    why, and only ``ah`` survives it (the record's partial-pair rule).
    ``ah`` integrates the current series ALONE; ``wh`` integrates the
    paired power series; each integral carries its own coverage
    denominators so a gapped integral is visibly partial.
    """

    definition: str
    v_id: str | None
    i_id: str
    v_unit: str | None
    i_unit: str
    lo: float | None
    hi: float | None
    count: int
    null_count: int
    mean_p: float | None
    peak_p: float | None
    mean_v: float | None
    min_v: float | None
    mean_i: float | None
    peak_i: float | None
    ah: IntegralResult
    wh: IntegralResult
    reason: str | None
    uncertainty: str


@dataclass(frozen=True)
class BatteryMode:
    """The battery presentation over rail 1 (AR-11): the rail's rows plus
    ``runtime_h = capacity_ah / mean_i`` — present only when the operator
    supplied ``capacity_ah`` AND the mean current is a finite non-zero
    value (a non-finite or zero divisor yields an absent runtime, never
    inf or a laundered 0; no default capacity ever ships)."""

    definition: str
    v_id: str | None
    i_id: str
    v_unit: str | None
    i_unit: str
    lo: float | None
    hi: float | None
    capacity_ah: float | None
    count: int
    null_count: int
    ah: float | None
    wh: float | None
    mean_i: float | None
    peak_i: float | None
    mean_v: float | None
    min_v: float | None
    mean_p: float | None
    peak_p: float | None
    runtime_h: float | None
    reason: str | None
    uncertainty: str


@dataclass(frozen=True)
class DcDcMode:
    """The dc-dc presentation over rails 1 and 2 (AR-11): rail 1 is the
    input, rail 2 the output (request order is the deterministic default;
    the operator's explicit rails reassign it). η = pout/pin × 100 only
    when both mean powers are present and ``|pin| > 1e-9`` — otherwise η
    is absent with a reason, never inf and never 0."""

    definition: str
    in_v_id: str | None
    in_i_id: str | None
    out_v_id: str | None
    out_i_id: str | None
    in_unit: str | None
    out_unit: str | None
    lo: float | None
    hi: float | None
    in_count: int
    out_count: int
    pin: float | None
    pout: float | None
    eta_pct: float | None
    reason: str | None
    uncertainty: str


@dataclass(frozen=True)
class SleepMode:
    """The sleep presentation over rail 1's current series (AR-11): a
    threshold split into above/below classes with duty %, per-class means
    and counts. A threshold ABSENT → ``not_evaluated`` with reason ``no
    threshold`` (the fork's midpoint default is not carried — the A02
    posture: a missing requirement blocks, it never defaults). An empty
    class reports its count and an ABSENT mean, never 0 A."""

    definition: str
    i_id: str
    i_unit: str
    threshold: float | None
    verdict: str
    reason: str | None
    count: int | None
    above_count: int | None
    above_mean: float | None
    below_count: int | None
    below_mean: float | None
    duty_pct: float | None
    uncertainty: str


@dataclass(frozen=True)
class LoadStepMode:
    """The load-step presentation over rail 1 (AR-11): the 15% head/tail
    means on BOTH series (each over its own non-null in-window samples,
    the edge-timing rule), ΔV, ΔI, and ``R = -ΔV/ΔI`` only when
    ``|ΔI| > 1e-9`` — otherwise absent, never inf."""

    definition: str
    v_id: str | None
    i_id: str
    v_unit: str | None
    i_unit: str
    lo: float | None
    hi: float | None
    v_n: int
    i_n: int
    v_head: float | None
    v_tail: float | None
    i_head: float | None
    i_tail: float | None
    dv: float | None
    di: float | None
    r: float | None
    uncertainty: str


@dataclass(frozen=True)
class PowerAnalysis:
    """The power family's whole result (the record §1.4): the resolved
    rails' rows, the unavailable reason when the set holds no current
    series (never 0 W — AR-3's arm), and the ONE requested mode block.
    ``resolved_rail_rows`` is the replay form the export sidecar records
    so re-export reproduces the pairing (AR-10)."""

    definition: str
    mode: str
    lo: float | None
    hi: float | None
    threshold: float | None
    capacity_ah: float | None
    rails: tuple[PowerRail, ...]
    unavailable: str | None
    battery: BatteryMode | None
    dcdc: DcDcMode | None
    sleep: SleepMode | None
    load_step: LoadStepMode | None
    uncertainty: str

    def resolved_rail_rows(self) -> list[dict[str, Any]]:
        """The rails as report_export rail rows (v omitted on an i-only
        rail — the schema's optional-v shape)."""
        rows: list[dict[str, Any]] = []
        for rail in self.rails:
            row: dict[str, Any] = {"i": rail.i_id}
            if rail.v_id is not None:
                row["v"] = rail.v_id
            rows.append(row)
        return rows


def resolve_power_rails(
    sources: Sequence[SeriesSource],
    rails: Sequence[Mapping[str, Any]] | None = None,
) -> list[tuple[SeriesSource | None, SeriesSource]]:
    """Resolve the V/I rails: explicit operator rows (re-keyed on
    ``capture_id``) or the deterministic default — the first voltage-class
    and first current-class source in REQUEST order form rail 1, the next
    of each class rail 2, and so on; unpaired CURRENTS keep an i-only
    rail (the partial-pair honesty rule), unpaired voltages form nothing.
    Every explicit row refuses typed (``standalone_report_power_rails``)
    when it names a capture outside the request set, a capture of the
    wrong class, or a capture already used by another rail.
    """
    by_id = {source.capture_id: source for source in sources}
    voltages = [s for s in sources if unit_kind(s.unit) == "voltage"]
    currents = [s for s in sources if unit_kind(s.unit) == "current"]
    resolved: list[tuple[SeriesSource | None, SeriesSource]] = []
    if rails:
        used: set[str] = set()
        for row in rails:
            i_id = str(row.get("i", ""))
            i_source = by_id.get(i_id)
            if i_source is None or unit_kind(i_source.unit) != "current":
                raise AnalysisRefusal(
                    f"standalone_report_power_rails: rail i {i_id!r} is not a "
                    "current-class capture of this request set"
                )
            v_source: SeriesSource | None = None
            v_id = row.get("v")
            if v_id is not None:
                v_source = by_id.get(str(v_id))
                if v_source is None or unit_kind(v_source.unit) != "voltage":
                    raise AnalysisRefusal(
                        f"standalone_report_power_rails: rail v {v_id!r} is not "
                        "a voltage-class capture of this request set"
                    )
            for member in ((str(v_id) if v_id is not None else None), i_id):
                if member is not None:
                    if member in used:
                        raise AnalysisRefusal(
                            f"standalone_report_power_rails: capture {member} is "
                            "named by more than one rail"
                        )
                    used.add(member)
            resolved.append((v_source, i_source))
    else:
        for v_source, i_source in zip(voltages, currents, strict=False):
            resolved.append((v_source, i_source))
    named = {i_source.capture_id for _, i_source in resolved}
    for i_source in currents:
        if i_source.capture_id not in named:
            resolved.append((None, i_source))
    return resolved


def _scaled(integral: IntegralResult, divisor: float) -> IntegralResult:
    """One integral rescaled from value·seconds to value·hours — the
    coverage denominators travel unchanged."""
    return IntegralResult(
        definition=integral.definition,
        value=integral.value / divisor if integral.value is not None else None,
        integrated_span_s=integral.integrated_span_s,
        counted_segments=integral.counted_segments,
        dropped_segments=integral.dropped_segments,
        uncertainty=integral.uncertainty,
    )


def _rail_row(
    v: SeriesSource | None,
    v_points: list[tuple[float, float]],
    i: SeriesSource,
    i_points: list[tuple[float, float]],
    *,
    lo: float | None,
    hi: float | None,
) -> PowerRail:
    """One rail's rows from its two windowed point lists (both already
    digest-verified by the caller's read; the window filter is applied
    again here so the function is correct on any superset input)."""
    if v is not None and v.sample_interval_s != i.sample_interval_s:
        raise AnalysisRefusal(
            f"standalone_report_power_pairing: {v.capture_id} and {i.capture_id} "
            f"declare sample_interval_s {v.sample_interval_s} and "
            f"{i.sample_interval_s}; a rail pairs samples on a shared "
            "uniform grid"
        )
    if v is not None and v.sample_count != i.sample_count:
        # A-F2 + B-F3 (the fold): the interval-mismatch check's unguarded
        # sibling — the same interval with DIFFERENT sample counts (one
        # instrument stopped early) used to pair silently over the zip
        # truncation, presenting overlap-only means as window rows. A
        # rail pairs whole captures or refuses.
        raise AnalysisRefusal(
            f"standalone_report_power_pairing: {v.capture_id} and {i.capture_id} "
            f"declare sample_count {v.sample_count} and {i.sample_count}; a "
            "rail pairs whole captures on a shared grid (the overlap alone "
            "would misstate the window)"
        )
    count = 0
    null_count = 0
    powers: list[float] = []
    p_peak: float | None = None
    voltages: list[float] = []
    v_low: float | None = None
    currents: list[float] = []
    i_peak: float | None = None
    power_nodes: list[tuple[float, float]] = []
    if v is not None:
        for (t, vv), (_, ii) in zip(v_points, i_points, strict=True):
            if lo is not None and t < lo:
                continue
            if hi is not None and t > hi:
                continue
            if math.isnan(vv) or math.isnan(ii):
                null_count += 1
                power_nodes.append((t, math.nan))
                continue
            count += 1
            power = vv * ii
            powers.append(power)
            if p_peak is None or power > p_peak:
                p_peak = power
            voltages.append(vv)
            if v_low is None or vv < v_low:
                v_low = vv
            currents.append(ii)
            if i_peak is None or ii > i_peak:
                i_peak = ii
            power_nodes.append((t, power))
        wh = _scaled(trapezoid_integral(power_nodes, lo, hi), 3600.0)
        reason = None
    else:
        wh = IntegralResult(
            definition=POWER_DEFINITION,
            value=None,
            integrated_span_s=0.0,
            counted_segments=0,
            dropped_segments=0,
            uncertainty="unknown",
        )
        reason = "power_unavailable: no voltage series"
    return PowerRail(
        definition=POWER_DEFINITION,
        v_id=v.capture_id if v is not None else None,
        i_id=i.capture_id,
        v_unit=v.unit if v is not None else None,
        i_unit=i.unit,
        lo=lo,
        hi=hi,
        count=count,
        null_count=null_count,
        # Exact summation for every mean (the record's <=4-ulp rule —
        # same reasoning as trapezoid_integral; _fsum's fallback keeps
        # mixed +/-inf honest instead of raising).
        mean_p=_fsum(powers) / count if count else None,
        peak_p=p_peak,
        mean_v=_fsum(voltages) / count if count else None,
        min_v=v_low,
        mean_i=_fsum(currents) / count if count else None,
        peak_i=i_peak,
        # Ah integrates the current series ALONE over its own grid — the
        # record's rule; the V side never gates it.
        ah=_scaled(trapezoid_integral(i_points, lo, hi), 3600.0),
        wh=wh,
        reason=reason,
        uncertainty="unknown",
    )


def _windowed_values(
    points: Iterable[tuple[float, float]], lo: float | None, hi: float | None
) -> list[float]:
    """The in-window non-null values in acquisition order (the region
    semantics every family shares)."""
    return [
        value
        for t, value in points
        if (lo is None or t >= lo)
        and (hi is None or t <= hi)
        and not math.isnan(value)
    ]


def _head_tail_means(values: Sequence[float]) -> tuple[int, float | None, float | None]:
    """The 15% head/tail means (``max(1, floor(n * 0.15))`` per side, the
    edge-timing rule) over one series' non-null in-window values."""
    n = len(values)
    if n == 0:
        return 0, None, None
    side = max(1, math.floor(n * 0.15))
    head = _fsum(values[:side]) / side
    tail = _fsum(values[n - side :]) / side
    return n, head, tail


def _sleep_mode(
    i_id: str,
    i_unit: str,
    i_points: list[tuple[float, float]],
    threshold: float | None,
    *,
    lo: float | None,
    hi: float | None,
) -> SleepMode:
    if threshold is None:
        # The A02 posture: a missing threshold blocks the split — the
        # fork's midpoint default is not carried (AR-11's arm).
        return SleepMode(
            definition=POWER_DEFINITION,
            i_id=i_id,
            i_unit=i_unit,
            threshold=None,
            verdict="not_evaluated",
            reason="no threshold",
            count=None,
            above_count=None,
            above_mean=None,
            below_count=None,
            below_mean=None,
            duty_pct=None,
            uncertainty="unknown",
        )
    values = _windowed_values(i_points, lo, hi)
    above = [value for value in values if value > threshold]
    below = [value for value in values if value <= threshold]
    count = len(values)
    return SleepMode(
        definition=POWER_DEFINITION,
        i_id=i_id,
        i_unit=i_unit,
        threshold=threshold,
        verdict="evaluated",
        reason=None,
        count=count,
        above_count=len(above),
        above_mean=_fsum(above) / len(above) if above else None,
        below_count=len(below),
        below_mean=_fsum(below) / len(below) if below else None,
        duty_pct=(len(above) / count * 100.0) if count else None,
        uncertainty="unknown",
    )


def power_analysis(
    series: Sequence[tuple[SeriesSource, list[tuple[float, float]]]],
    *,
    mode: str,
    rails: Sequence[Mapping[str, Any]] | None = None,
    lo: float | None,
    hi: float | None,
    threshold: float | None = None,
    capacity_ah: float | None = None,
) -> PowerAnalysis:
    """The whole power family over one capture set (the record §1.4).

    ``series`` is each loaded source with its (digest-verified) WINDOWED
    point list — the contract both real callers meet (the seam's export
    path and the view pass the request's own windowed points, so every
    pair and segment names a sample inside the window). Full point lists
    are also accepted, with one pinned coverage asymmetry (A-F3's pin
    test): the Ah integral then follows the trapezoid definition and
    CLIPS its boundary segments with interpolation, while the paired
    stream windows sample-wise — two coverages of one window, exactly as
    ``test_full_input_pinned_coverage_asymmetry`` pins.
    Scalar params refuse typed (``standalone_report_power_mode`` /
    ``standalone_report_power_param``) and rails resolve through
    :func:`resolve_power_rails`. The result carries every rail's rows,
    the ``power_unavailable`` reason when the set holds no current
    series, and the ONE requested mode block.
    """
    if mode not in POWER_MODES:
        raise AnalysisRefusal(
            f"standalone_report_power_mode: {mode!r} is not one of "
            f"{', '.join(POWER_MODES)}"
        )
    if threshold is not None and (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(float(threshold))
    ):
        raise AnalysisRefusal(
            f"standalone_report_power_param: threshold {threshold!r} is not a "
            "finite number"
        )
    if capacity_ah is not None and (
        isinstance(capacity_ah, bool)
        or not isinstance(capacity_ah, (int, float))
        or not math.isfinite(float(capacity_ah))
        or not float(capacity_ah) > 0.0
    ):
        raise AnalysisRefusal(
            f"standalone_report_power_param: capacity_ah {capacity_ah!r} is not "
            "a finite positive number"
        )
    sources = [source for source, _ in series]
    points_of = {source.capture_id: points for source, points in series}
    pairs = resolve_power_rails(sources, rails)
    if not pairs:
        # AR-3's arm: no current series means no power rows at all and
        # the reason — never a 0 W row.
        return PowerAnalysis(
            definition=POWER_DEFINITION,
            mode=mode,
            lo=lo,
            hi=hi,
            threshold=threshold,
            capacity_ah=capacity_ah,
            rails=(),
            unavailable="power_unavailable: no current series",
            battery=None,
            dcdc=None,
            sleep=None,
            load_step=None,
            uncertainty="unknown",
        )
    rail_rows = tuple(
        _rail_row(
            v,
            points_of[v.capture_id] if v is not None else [],
            i,
            points_of[i.capture_id],
            lo=lo,
            hi=hi,
        )
        for v, i in pairs
    )
    first = rail_rows[0]
    battery: BatteryMode | None = None
    dcdc: DcDcMode | None = None
    sleep: SleepMode | None = None
    load_step: LoadStepMode | None = None
    if mode == "battery":
        runtime: float | None = None
        if (
            capacity_ah is not None
            and first.mean_i is not None
            and first.mean_i != 0.0
            and math.isfinite(first.mean_i)
        ):
            candidate = float(capacity_ah) / first.mean_i
            runtime = candidate if math.isfinite(candidate) else None
        battery = BatteryMode(
            definition=POWER_DEFINITION,
            v_id=first.v_id,
            i_id=first.i_id,
            v_unit=first.v_unit,
            i_unit=first.i_unit,
            lo=lo,
            hi=hi,
            capacity_ah=float(capacity_ah) if capacity_ah is not None else None,
            count=first.count,
            null_count=first.null_count,
            ah=first.ah.value,
            wh=first.wh.value,
            mean_i=first.mean_i,
            peak_i=first.peak_i,
            mean_v=first.mean_v,
            min_v=first.min_v,
            mean_p=first.mean_p,
            peak_p=first.peak_p,
            runtime_h=runtime,
            reason=first.reason,
            uncertainty="unknown",
        )
    elif mode == "dc-dc":
        second = rail_rows[1] if len(rail_rows) > 1 else None
        pin = first.mean_p
        pout = second.mean_p if second is not None else None
        eta: float | None = None
        reason: str | None = None
        if second is None or pin is None or pout is None:
            reason = "needs two paired rails with power"
        elif abs(pin) > 1e-9:
            eta = pout / pin * 100.0
        else:
            reason = "input power at or below the 1e-9 W floor"
        dcdc = DcDcMode(
            definition=POWER_DEFINITION,
            in_v_id=first.v_id,
            in_i_id=first.i_id,
            out_v_id=second.v_id if second is not None else None,
            out_i_id=second.i_id if second is not None else None,
            in_unit=product_unit(first.v_unit, first.i_unit),
            out_unit=(
                product_unit(second.v_unit, second.i_unit)
                if second is not None
                else None
            ),
            lo=lo,
            hi=hi,
            in_count=first.count,
            out_count=second.count if second is not None else 0,
            pin=pin,
            pout=pout,
            eta_pct=eta,
            reason=reason,
            uncertainty="unknown",
        )
    elif mode == "sleep":
        sleep = _sleep_mode(
            first.i_id, first.i_unit, points_of[first.i_id], threshold,
            lo=lo, hi=hi,
        )
    else:  # "load-step" — the only remaining POWER_MODES member
        v_values = (
            _windowed_values(points_of[first.v_id], lo, hi)
            if first.v_id is not None
            else []
        )
        i_values = _windowed_values(points_of[first.i_id], lo, hi)
        v_n, v_head, v_tail = _head_tail_means(v_values)
        i_n, i_head, i_tail = _head_tail_means(i_values)
        dv = v_tail - v_head if v_tail is not None and v_head is not None else None
        di = i_tail - i_head if i_tail is not None and i_head is not None else None
        r: float | None = None
        if dv is not None and di is not None and abs(di) > 1e-9:
            r = -dv / di
        load_step = LoadStepMode(
            definition=POWER_DEFINITION,
            v_id=first.v_id,
            i_id=first.i_id,
            v_unit=first.v_unit,
            i_unit=first.i_unit,
            lo=lo,
            hi=hi,
            v_n=v_n,
            i_n=i_n,
            v_head=v_head,
            v_tail=v_tail,
            i_head=i_head,
            i_tail=i_tail,
            dv=dv,
            di=di,
            r=r,
            uncertainty="unknown",
        )
    return PowerAnalysis(
        definition=POWER_DEFINITION,
        mode=mode,
        lo=lo,
        hi=hi,
        threshold=float(threshold) if threshold is not None else None,
        capacity_ah=float(capacity_ah) if capacity_ah is not None else None,
        rails=rail_rows,
        unavailable=None,
        battery=battery,
        dcdc=dcdc,
        sleep=sleep,
        load_step=load_step,
        uncertainty="unknown",
    )
