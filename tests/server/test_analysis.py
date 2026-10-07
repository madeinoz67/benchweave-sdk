"""I4a AR-1: the analysis dataset loader and window statistics.

The definition under test is ``benchweave-analysis/1``: an inclusive
``[lo, hi]`` window, nulls (NaN samples) counted and excluded, every
statistic's denominator the non-null in-window count. Tolerance per the
design record: exact for count/min/max/pp; at most 4 ulp for mean/rms —
and if more than one fixture ever needs loosening past that, the
computation order is wrong (a KILL, never a tolerance fix).

The fixtures are synthetic with invented ``fx-*`` names (the record's
fixture rule); every closed form is computed in-test from the same known
sample values, so a wrong implementation cannot pass by accident.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk_server.analysis import (
    ANALYSIS_DEFINITION,
    RegionStats,
    load_series_set,
    region_stats,
    scan_series,
    series_samples,
    windowed_points,
)

_INTERVAL = 0.001


def write_capture(
    root: Path,
    capture_id: str,
    *,
    values: tuple[float, ...],
    interval: float = _INTERVAL,
    unit: str = "V",
    fmt: str = "waveform_f64le",
    declared_count: int | None = None,
    metadata: dict[str, Any] | None = None,
    primary_bytes: bytes | None = None,
    manifest_extra: dict[str, Any] | None = None,
) -> Path:
    """Publish one event directory exactly as the writer + host do.

    ``primary_bytes`` overrides the payload on disk (the tampered-primary
    arm); ``declared_count`` overrides the manifest's sample_count (the
    length-mismatch arm).
    """
    payload = b"".join(struct.pack("<d", value) for value in values)
    on_disk = payload if primary_bytes is None else primary_bytes
    event = root / capture_id
    event.mkdir(parents=True)
    (event / f"{capture_id}.f64").write_bytes(on_disk)
    digest = hashlib.sha256(payload).hexdigest()
    manifest: dict[str, Any] = {
        "capture_id": capture_id,
        "format": fmt,
        "artifact_id": "art-" + digest,
        "byte_length": len(payload),
        "sha256": digest,
        "started_at": f"2026-10-07T09:00:00+00:00-{capture_id}",
    }
    if fmt == "waveform_f64le":
        manifest["sample_count"] = len(values) if declared_count is None else declared_count
        manifest["sample_interval_s"] = interval
        manifest["unit"] = unit
    if manifest_extra:
        manifest.update(manifest_extra)
    (event / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    meta: dict[str, Any] = {
        "capture_id": capture_id,
        "device": {"id": "fx-device", "firmware": "1.2.7"},
        "plugin": {"package": "fx-plugin", "version": "0.3.1"},
        "surface": "rest",
        "operator": "fx-op",
        "tags": [],
        "notes": "",
    }
    meta.update(metadata or {})
    (event / "metadata.json").write_text(json.dumps(meta, sort_keys=True))
    return event


def _ulp(actual: float, expected: float, ulps: float = 4.0) -> bool:
    """``actual`` within ``ulps`` binary64 units of the last place of
    ``expected`` (the record's mean/rms tolerance; exact for 0)."""
    if expected == 0.0:
        return actual == 0.0
    return math.isclose(actual, expected, rel_tol=ulps * 2.2e-16)


# --- the AR-1 fixture family ------------------------------------------------------


def test_fx_const_zero(tmp_path: Path) -> None:
    write_capture(tmp_path, "fx-const-zero", values=(0.0,) * 1000)
    (stats, _) = _scan(tmp_path, "fx-const-zero")
    assert (stats.count, stats.null_count) == (1000, 0)
    assert stats.min == 0.0 and stats.max == 0.0 and stats.pp == 0.0
    assert stats.mean == 0.0 and stats.rms == 0.0


def test_fx_const_neg(tmp_path: Path) -> None:
    write_capture(tmp_path, "fx-const-neg", values=(-3.5,) * 1000)
    (stats, _) = _scan(tmp_path, "fx-const-neg")
    assert stats.count == 1000
    assert stats.mean == -3.5
    assert _ulp(stats.rms, 3.5)
    assert stats.pp == 0.0


def test_fx_twolevel(tmp_path: Path) -> None:
    write_capture(tmp_path, "fx-twolevel", values=(0.0,) * 500 + (2.0,) * 500)
    (stats, _) = _scan(tmp_path, "fx-twolevel")
    assert stats.mean == 1.0
    assert _ulp(stats.rms, math.sqrt(2.0))
    assert stats.pp == 2.0


def test_fx_ramp(tmp_path: Path) -> None:
    values = tuple(float(index) for index in range(1000))
    write_capture(tmp_path, "fx-ramp", values=values)
    (stats, _) = _scan(tmp_path, "fx-ramp")
    assert (stats.min, stats.max, stats.pp) == (0.0, 999.0, 999.0)
    assert stats.mean == 499.5
    assert stats.rms is not None and _ulp(
        stats.rms, math.sqrt(sum(value * value for value in values) / 1000)
    )


def test_fx_alt(tmp_path: Path) -> None:
    values = tuple(float(index % 2) for index in range(10_000))
    write_capture(tmp_path, "fx-alt", values=values)
    (stats, _) = _scan(tmp_path, "fx-alt")
    assert stats.count == 10_000
    assert stats.mean == 0.5
    # The design record's AR-1 line says "rms=0.5" for this fixture — an
    # arithmetic slip in the record, disclosed: rms of alternating 0/1 is
    # sqrt(0.5) (~0.7071), and rms >= |mean| (0.5) with pp=1 makes 0.5
    # impossible. The closed form the implementation must meet is sqrt(0.5).
    assert _ulp(stats.rms, math.sqrt(0.5))
    assert stats.pp == 1.0


def test_fx_nulls(tmp_path: Path) -> None:
    """100 NaN samples at known positions: counted as nulls, excluded from
    every statistic, and the remaining 900 compared against the closed form
    over exactly those samples."""
    null_positions = set(range(7, 1000, 10))
    assert len(null_positions) == 100
    values = tuple(
        math.nan if index in null_positions else float(index % 17) - 8.0
        for index in range(1000)
    )
    write_capture(tmp_path, "fx-nulls", values=values)
    (stats, _) = _scan(tmp_path, "fx-nulls")
    kept = [value for index, value in enumerate(values) if index not in null_positions]
    assert (stats.count, stats.null_count) == (900, 100)
    assert stats.min == min(kept) and stats.max == max(kept)
    assert stats.pp == max(kept) - min(kept)
    assert stats.mean is not None and _ulp(stats.mean, sum(kept) / 900)
    assert stats.rms is not None and _ulp(
        stats.rms, math.sqrt(sum(value * value for value in kept) / 900)
    )


def test_fx_window_inclusive_bounds(tmp_path: Path) -> None:
    """The window is inclusive: samples AT lo and AT hi are inside."""
    values = (10.0, 9.0, 8.0, 7.0, 6.0, 5.0)
    write_capture(tmp_path, "fx-window", values=values, interval=1.0)
    source = load_series_set(tmp_path, ["fx-window"])[0]
    stats = region_stats(series_samples(source), lo=2.0, hi=4.0)
    assert stats.count == 3
    assert stats.mean == 7.0
    assert (stats.min, stats.max) == (6.0, 8.0)
    assert stats.lo == 2.0 and stats.hi == 4.0


def test_fx_spike(tmp_path: Path) -> None:
    values = tuple(10.0 if index == 5000 else 0.0 for index in range(10_000))
    write_capture(tmp_path, "fx-spike", values=values)
    (stats, _) = _scan(tmp_path, "fx-spike")
    assert stats.count == 10_000
    assert stats.mean is not None and _ulp(stats.mean, 0.001)
    assert stats.max == 10.0 and stats.min == 0.0


def test_empty_window_statistics_are_absent_never_zero(tmp_path: Path) -> None:
    write_capture(tmp_path, "fx-window-empty", values=(1.0, 2.0, 3.0), interval=1.0)
    source = load_series_set(tmp_path, ["fx-window-empty"])[0]
    stats = region_stats(series_samples(source), lo=100.0, hi=200.0)
    assert stats.count == 0
    assert stats.mean is None and stats.rms is None
    assert stats.min is None and stats.max is None and stats.pp is None


def test_stats_carry_the_definition_and_uncertainty(tmp_path: Path) -> None:
    write_capture(tmp_path, "fx-labelled", values=(1.0, 2.0))
    (stats, _) = _scan(tmp_path, "fx-labelled")
    assert stats.definition == ANALYSIS_DEFINITION == "benchweave-analysis/1"
    assert stats.uncertainty == "unknown"


def test_loader_labels_each_series_with_unit_and_metadata(tmp_path: Path) -> None:
    write_capture(
        tmp_path, "fx-labelled", values=(1.0,), unit="A",
        metadata={"operator": "fx-op", "notes": "rail current"},
    )
    source = load_series_set(tmp_path, ["fx-labelled"])[0]
    assert source.unit == "A"
    assert source.sample_interval_s == _INTERVAL
    assert source.sample_count == 1
    assert source.metadata["operator"] == "fx-op"
    assert source.manifest["sha256"] == source.manifest_sha256


def test_multi_capture_set_loads_in_request_order(tmp_path: Path) -> None:
    write_capture(tmp_path, "fx-set-a", values=(1.0,), unit="V")
    write_capture(tmp_path, "fx-set-b", values=(2.0,), unit="A")
    sources = load_series_set(tmp_path, ["fx-set-b", "fx-set-a"])
    assert [source.capture_id for source in sources] == ["fx-set-b", "fx-set-a"]
    assert [source.unit for source in sources] == ["A", "V"]


def test_scan_series_digest_matches_manifest_and_recomputed_bytes(tmp_path: Path) -> None:
    values = tuple(float(index % 5) for index in range(5000))
    write_capture(tmp_path, "fx-digest", values=values)
    source = load_series_set(tmp_path, ["fx-digest"])[0]
    (stats, digest) = scan_series(source)
    payload = b"".join(struct.pack("<d", value) for value in values)
    assert digest == source.manifest_sha256
    assert digest == hashlib.sha256(payload).hexdigest()
    assert stats.count == 5000


def test_chunked_reader_is_exact_across_chunk_boundaries(tmp_path: Path) -> None:
    """The loader never materialises the series: it reads in chunks. A
    series straddling several chunk boundaries yields exactly the same
    statistics as the closed form over the whole value list."""
    values = tuple(float((index * 37) % 101) - 50.0 for index in range(8192 * 2 + 5))
    write_capture(tmp_path, "fx-chunky", values=values)
    (stats, _) = _scan(tmp_path, "fx-chunky")
    assert stats.count == len(values)
    assert stats.mean is not None and _ulp(
        stats.mean, sum(values) / len(values)
    )
    assert stats.rms is not None and _ulp(
        stats.rms, math.sqrt(sum(v * v for v in values) / len(values))
    )


def _scan(root: Path, capture_id: str) -> tuple[RegionStats, str]:
    source = load_series_set(root, [capture_id])[0]
    return scan_series(source)


# --- the refusal family (NFR-Q4: one arm per refusal path) ------------------------


def test_unknown_capture_refuses(tmp_path: Path) -> None:
    write_capture(tmp_path, "fx-known", values=(1.0,))
    with pytest.raises(ValueError, match="standalone_report_capture_unknown: fx-missing"):
        load_series_set(tmp_path, ["fx-missing"])


def test_unparseable_manifest_refuses(tmp_path: Path) -> None:
    event = write_capture(tmp_path, "fx-mangled", values=(1.0,))
    (event / "manifest.json").write_text("{not json")
    with pytest.raises(ValueError, match="standalone_report_manifest_unreadable"):
        load_series_set(tmp_path, ["fx-mangled"])


def test_non_waveform_format_refuses(tmp_path: Path) -> None:
    write_capture(tmp_path, "fx-raw", values=(1.0,), fmt="raw_binary")
    with pytest.raises(ValueError, match="standalone_report_format_unsupported"):
        load_series_set(tmp_path, ["fx-raw"])


def test_primary_length_mismatch_refuses(tmp_path: Path) -> None:
    write_capture(
        tmp_path, "fx-short", values=(1.0, 2.0, 3.0), declared_count=3,
        primary_bytes=b"\x00" * 8,
    )
    with pytest.raises(ValueError, match="standalone_report_primary_length"):
        load_series_set(tmp_path, ["fx-short"])


def test_missing_primary_refuses(tmp_path: Path) -> None:
    event = write_capture(tmp_path, "fx-noprimary", values=(1.0,))
    (event / "fx-noprimary.f64").unlink()
    with pytest.raises(ValueError, match="standalone_report_primary_missing"):
        load_series_set(tmp_path, ["fx-noprimary"])


def test_tampered_primary_refuses_at_scan(tmp_path: Path) -> None:
    """The manifest digest is recomputed over the real bytes during the
    scan pass: bytes that changed after publication must not silently
    enter a report (AR-4b's recomputed-digest rule, enforced at source)."""
    values = (1.0, 2.0, 3.0, 4.0)
    event = write_capture(tmp_path, "fx-tampered", values=values)
    (event / "fx-tampered.f64").write_bytes(
        b"".join(struct.pack("<d", v) for v in (1.0, 2.0, 3.0, 5.0))
    )
    source = load_series_set(tmp_path, ["fx-tampered"])[0]
    with pytest.raises(ValueError, match="standalone_report_primary_mismatch"):
        scan_series(source)


def test_incomplete_waveform_manifest_refuses(tmp_path: Path) -> None:
    event = write_capture(tmp_path, "fx-nounit", values=(1.0,))
    manifest = json.loads((event / "manifest.json").read_text())
    del manifest["unit"]
    (event / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    with pytest.raises(ValueError, match="standalone_report_manifest_incomplete"):
        load_series_set(tmp_path, ["fx-nounit"])


def test_missing_metadata_reads_as_empty_not_a_refusal(tmp_path: Path) -> None:
    """metadata.json is the annotation authority, not a load precondition
    (the library's honest-defaults rule): its absence loads with empty
    metadata rather than refusing."""
    event = write_capture(tmp_path, "fx-nometa", values=(1.0,))
    (event / "metadata.json").unlink()
    source = load_series_set(tmp_path, ["fx-nometa"])[0]
    assert source.metadata == {}


# --- fold wave 1: the bounded, verified windowing pass (rows 4 and 5) --------------


def test_windowed_points_verifies_the_digest_on_its_own_pass(tmp_path: Path) -> None:
    """Row 5: the plot points come from a SECOND read of the primary —
    that pass must verify the digest itself. A primary mutated between
    the statistics pass and the points pass refuses here instead of
    feeding unverified bytes to the plot."""
    values = (1.0, 2.0, 3.0, 4.0)
    event = write_capture(tmp_path, "fx-two-pass", values=values)
    source = load_series_set(tmp_path, ["fx-two-pass"])[0]
    stats, digest = scan_series(source)
    assert digest == source.manifest_sha256
    assert stats.count == 4
    (event / "fx-two-pass.f64").write_bytes(
        b"".join(struct.pack("<d", value) for value in (1.0, 2.0, 3.0, 9.0))
    )
    with pytest.raises(ValueError, match="standalone_report_primary_mismatch"):
        windowed_points(source, lo=None, hi=None, limit=100)


def test_windowed_points_enforces_the_limit_incrementally(tmp_path: Path) -> None:
    """Row 4: the ceiling binds MEMORY, not just the response — the
    window list refuses the moment it would exceed the limit, never after
    materialising the whole window."""
    write_capture(tmp_path, "fx-limit", values=tuple(float(i) for i in range(1000)))
    source = load_series_set(tmp_path, ["fx-limit"])[0]
    with pytest.raises(ValueError, match="standalone_report_window_too_large"):
        windowed_points(source, lo=None, hi=None, limit=100)
    # At or below the limit the pass is exact and window-filtering holds.
    bounded = windowed_points(source, lo=1.0, hi=3.0, limit=1000)
    assert bounded == [
        (t, value) for t, value in series_samples(source) if 1.0 <= t <= 3.0
    ]
    assert windowed_points(source, lo=None, hi=None, limit=1000) == list(
        series_samples(source)
    )


def test_windowed_points_refuses_a_primary_truncated_between_passes(
    tmp_path: Path,
) -> None:
    """B-F5's truncation variant (converged with fold row 5): the second
    pass verifies its OWN read — a primary truncated (not just mutated)
    after the statistics pass refuses instead of drawing a partial
    series."""
    values = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
    event = write_capture(tmp_path, "fx-trunc", values=values)
    source = load_series_set(tmp_path, ["fx-trunc"])[0]
    stats, _ = scan_series(source)
    assert stats.count == 6
    (event / "fx-trunc.f64").write_bytes(
        b"".join(struct.pack("<d", v) for v in values[:2])
    )
    with pytest.raises(ValueError, match="standalone_report_primary_mismatch"):
        windowed_points(source, lo=None, hi=None, limit=100)
