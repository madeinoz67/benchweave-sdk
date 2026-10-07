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
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The definition id printed on every report and carried by every stats
#: object: the numbers mean exactly this computation, nothing else.
ANALYSIS_DEFINITION = "benchweave-analysis/1"

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
