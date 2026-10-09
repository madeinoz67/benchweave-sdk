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
    ASSERT_DEFINITION,
    EDGE_DEFINITION,
    POWER_DEFINITION,
    POWER_MODES,
    RegionStats,
    decimated_extent,
    edge_analysis,
    evaluate_assertions,
    load_series_set,
    power_analysis,
    region_stats,
    scan_series,
    series_samples,
    trapezoid_integral,
    unit_kind,
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


# --- I4b.1 AR-2: edge timing (definition benchweave-edge/1) ------------------------
#
# Fixtures at 1 kHz per the pre-committed rule. The closed forms are
# computed in-test from the fixture's own construction (the ramp slope and
# the head/tail plateau values), and the tolerance is the record's: within
# ONE sample interval for the timing arms.


def _step_fixture(
    *,
    baseline: float = 0.0,
    ramp_samples: int = 50,
    slope: float = 0.02,
    head: int = 400,
    before_excursion: int = 550,
    excursion: tuple[float, ...] = (),
    tail: int = 0,
) -> tuple[tuple[float, ...], int]:
    """One step fixture: ``baseline`` plateau (``head`` samples), a linear
    ramp of ``slope`` per sample, the ramp's top plateau
    (``before_excursion`` samples), then an optional scripted excursion
    and a closing top plateau (``tail``). ``head`` and the post-excursion
    plateau are each at least 150 samples (n=1000, head_n=tail_n=150), so
    the head/tail means land EXACTLY on the plateau values. The ramp is
    the continuous line v(i) = (i - head + 1) * slope, so the closed-form
    crossing of level L sits at index head - 1 + L / slope."""
    top = ramp_samples * slope
    ramp = tuple(k * slope for k in range(1, ramp_samples + 1))
    values = (
        [baseline] * head + list(ramp) + [top] * before_excursion
        + list(excursion) + [top] * tail
    )
    assert len(values) >= head + ramp_samples + before_excursion
    return tuple(values), head


def test_fx_step_rise_matches_the_closed_form(tmp_path: Path) -> None:
    """1 kHz, N=1000, head/tail means exact over the plateaus: t10/t90 are
    the interpolated crossings of 0.10/0.90 of the step, so rise_time is
    (0.90 - 0.10) / slope sample intervals — within one interval of the
    closed form (the record's tolerance; the fixture lands exact)."""
    slope = 0.02
    values, head = _step_fixture(ramp_samples=50, slope=slope)
    write_capture(tmp_path, "fx-step-rise", values=values)
    source = load_series_set(tmp_path, ["fx-step-rise"])[0]
    edge = edge_analysis(series_samples(source), lo=None, hi=None, settle_pct=2.0)
    assert edge.detected is True
    assert edge.rising is True
    assert edge.n == 1000 and edge.head_n == 150 and edge.tail_n == 150
    interval = _INTERVAL
    expected_rise = (0.90 - 0.10) / slope * interval
    assert edge.rise_time is not None
    assert abs(edge.rise_time - expected_rise) <= interval
    expected_t10 = (head - 1 + 0.10 / slope) * interval
    expected_t90 = (head - 1 + 0.90 / slope) * interval
    assert edge.t10 is not None and abs(edge.t10 - expected_t10) <= interval / 2
    assert edge.t90 is not None and abs(edge.t90 - expected_t90) <= interval / 2
    assert edge.baseline == 0.0 and edge.final == 1.0
    # The ramp below the settle band leaves it, so settle_time is a real
    # span (never None): the last out-of-band sample is the last ramp
    # sample under 0.98, and settle runs from t10 to the sample after it.
    assert edge.settle_time is not None


def test_nothing_left_the_band_settles_at_zero(tmp_path: Path) -> None:
    """The pinned edge outcome: settle_time is 0.0 exactly when nothing in
    scope ever left the band — at settle_pct 100 the band spans the whole
    step (baseline sits ON its lower edge), so no sample is outside."""
    values, _ = _step_fixture()
    write_capture(tmp_path, "fx-step-wide-band", values=values)
    source = load_series_set(tmp_path, ["fx-step-wide-band"])[0]
    edge = edge_analysis(series_samples(source), lo=None, hi=None, settle_pct=100.0)
    assert edge.detected is True
    assert edge.settle_time == 0.0


def test_fx_step_settle_matches_the_closed_form(tmp_path: Path) -> None:
    """An overshoot excursion of known extent above the 2% band:
    settle_time runs from t10 to the first sample after the LAST
    out-of-band sample — within one interval of the closed form."""
    slope = 0.02
    # head(400) + ramp(50) + top(150) + 1.05 x 20 + top(380) = 1000. The
    # tail window (last 150) sits entirely on the closing 1.0 plateau, so
    # final is exactly 1.0 and the band is [0.98, 1.02]; the 20 samples
    # at 1.05 are the last out-of-band excursion.
    values, head = _step_fixture(
        ramp_samples=50, slope=slope, before_excursion=150,
        excursion=(1.05,) * 20, tail=380,
    )
    write_capture(tmp_path, "fx-step-settle", values=values)
    source = load_series_set(tmp_path, ["fx-step-settle"])[0]
    edge = edge_analysis(series_samples(source), lo=None, hi=None, settle_pct=2.0)
    assert edge.detected is True
    assert edge.final == 1.0
    interval = _INTERVAL
    expected_t10 = (head - 1 + 0.10 / slope) * interval
    last_outside_index = head + 50 + 150 + 19
    expected_settle = (last_outside_index + 1) * interval - expected_t10
    assert edge.settle_time is not None
    assert abs(edge.settle_time - expected_settle) <= interval


def test_fx_step_fall_is_rising_false_with_equal_rise_magnitude(
    tmp_path: Path,
) -> None:
    rise_values, _ = _step_fixture(ramp_samples=50, slope=0.02)
    values = tuple(1.0 - value for value in rise_values)
    write_capture(tmp_path, "fx-step-fall", values=values)
    write_capture(tmp_path, "fx-step-up", values=rise_values)
    fall = edge_analysis(
        series_samples(load_series_set(tmp_path, ["fx-step-fall"])[0]),
        lo=None, hi=None, settle_pct=2.0,
    )
    rise = edge_analysis(
        series_samples(load_series_set(tmp_path, ["fx-step-up"])[0]),
        lo=None, hi=None, settle_pct=2.0,
    )
    assert fall.detected is True
    assert fall.rising is False
    assert rise.rising is True
    # A fall of the same shape has equal |riseTime|: for a fall the 10%
    # crossing comes FIRST in time, so t90 - t10 stays positive and the
    # magnitude matches the rise.
    assert fall.rise_time is not None and rise.rise_time is not None
    assert abs(abs(fall.rise_time) - abs(rise.rise_time)) <= _INTERVAL
    assert fall.rise_time > 0


def test_flat_series_is_not_detected(tmp_path: Path) -> None:
    write_capture(tmp_path, "fx-step-flat", values=(3.7,) * 1000)
    source = load_series_set(tmp_path, ["fx-step-flat"])[0]
    edge = edge_analysis(series_samples(source), lo=None, hi=None, settle_pct=2.0)
    assert edge.detected is False
    assert edge.rise_time is None and edge.settle_time is None


def test_two_sample_region_is_not_detected(tmp_path: Path) -> None:
    write_capture(tmp_path, "fx-step-two", values=(0.0, 1.0))
    source = load_series_set(tmp_path, ["fx-step-two"])[0]
    edge = edge_analysis(series_samples(source), lo=None, hi=None, settle_pct=2.0)
    assert edge.detected is False


def test_fx_step_nullpad_matches_the_null_free_closed_form(
    tmp_path: Path,
) -> None:
    """The region count is the NON-NULL in-window count (the fork's
    regionPoints semantics): nulls in both plateaus drop out BEFORE the
    head/tail split, so a padded rise still detects and matches the
    null-free closed form."""
    clean, head = _step_fixture(ramp_samples=50, slope=0.02)
    ramp_end = head + 50
    padded = tuple(
        math.nan if (index < head or index >= ramp_end) and index % 3 == 0 else value
        for index, value in enumerate(clean)
    )
    # Nulls only in the plateaus; the ramp (head..head+49) is null-free.
    assert all(not math.isnan(padded[index]) for index in range(head, ramp_end))
    write_capture(tmp_path, "fx-step-nullpad", values=padded)
    write_capture(tmp_path, "fx-step-clean", values=clean)
    edge = edge_analysis(
        series_samples(load_series_set(tmp_path, ["fx-step-nullpad"])[0]),
        lo=None, hi=None, settle_pct=2.0,
    )
    reference = edge_analysis(
        series_samples(load_series_set(tmp_path, ["fx-step-clean"])[0]),
        lo=None, hi=None, settle_pct=2.0,
    )
    assert edge.detected is True
    assert edge.n < 1000  # the nulls dropped out of the region count
    assert edge.n == sum(1 for value in padded if not math.isnan(value))
    assert edge.rise_time is not None and reference.rise_time is not None
    assert abs(edge.rise_time - reference.rise_time) <= _INTERVAL


def test_fx_step_nocross_reports_null_rise_time_never_zero(
    tmp_path: Path,
) -> None:
    """A region whose computed crossing levels can never be bracketed
    reports ``rise_time: None``, never 0. Construction disclosure: for
    FINITE samples a non-flat region always brackets both levels (each
    level lies strictly between the head and tail means, which lie inside
    the sample range, and the head precedes the tail in time) — the only
    data-driven absence is a non-finite-poisoned mean, which makes the
    levels NaN and every bracket comparison false. The pinned claim is
    the record's own: the absent crossing is NULL, never coerced to 0."""
    values = (float("inf"),) * 150 + (0.0,) * 850
    write_capture(tmp_path, "fx-step-nocross", values=values)
    source = load_series_set(tmp_path, ["fx-step-nocross"])[0]
    edge = edge_analysis(series_samples(source), lo=None, hi=None, settle_pct=2.0)
    assert edge.detected is True  # the flat guard cannot clear an inf step
    assert edge.t10 is None and edge.t90 is None
    assert edge.rise_time is None
    assert edge.rise_time != 0.0


def test_fx_step_settle_open_reports_null_settle_time(tmp_path: Path) -> None:
    """The region's LAST sample is still outside the band: not settled
    within the region — settle_time is None."""
    slope = 0.02
    # head(400) + ramp(50) + top(549) + one 1.05 sample = 1000. The tail
    # window holds 149 samples at 1.0 plus the final 1.05 sample, so
    # final is 1.0033.. and the 2% band tops at ~1.0204 — the region's
    # last sample (1.05) is still outside it.
    values, head = _step_fixture(
        ramp_samples=50, slope=slope, before_excursion=549, excursion=(1.05,),
    )
    assert len(values) == 1000
    write_capture(tmp_path, "fx-step-settle-open", values=values)
    source = load_series_set(tmp_path, ["fx-step-settle-open"])[0]
    edge = edge_analysis(series_samples(source), lo=None, hi=None, settle_pct=2.0)
    assert edge.detected is True
    assert edge.settle_time is None


def test_edge_rows_carry_the_definition_and_denominators(
    tmp_path: Path,
) -> None:
    values, _ = _step_fixture()
    write_capture(tmp_path, "fx-step-labelled", values=values, interval=0.001)
    source = load_series_set(tmp_path, ["fx-step-labelled"])[0]
    edge = edge_analysis(series_samples(source), lo=0.1, hi=0.9, settle_pct=2.0)
    assert edge.definition == EDGE_DEFINITION == "benchweave-edge/1"
    assert edge.uncertainty == "unknown"
    assert edge.lo == 0.1 and edge.hi == 0.9
    assert edge.settle_pct == 2.0
    assert edge.head_n >= 1 and edge.tail_n >= 1


# --- I4b.1 AR-7: min/max assertions (definition benchweave-assert/1) ---------------


def _assert_entries(root: Path, capture_id: str) -> dict[str, RegionStats]:
    (stats, _) = _scan(root, capture_id)
    return {capture_id: stats}


def test_fx_assert_pass(tmp_path: Path) -> None:
    write_capture(tmp_path, "fx-assert-pass", values=(1.0, 2.0, 3.0))
    results = evaluate_assertions(
        [{"capture_id": "fx-assert-pass", "min": 1.0, "max": 3.0}],
        _assert_entries(tmp_path, "fx-assert-pass"),
    )
    assert len(results) == 1
    row = results[0]
    assert row.verdict == "pass"
    assert row.reasons == ()
    assert row.actual_min == 1.0 and row.actual_max == 3.0


def test_fx_assert_low_and_high_name_their_reasons(tmp_path: Path) -> None:
    write_capture(tmp_path, "fx-assert-low", values=(0.5, 2.0))
    write_capture(tmp_path, "fx-assert-high", values=(1.0, 3.5))
    write_capture(tmp_path, "fx-assert-both", values=(0.5, 3.5))
    entries = {
        **_assert_entries(tmp_path, "fx-assert-low"),
        **_assert_entries(tmp_path, "fx-assert-high"),
        **_assert_entries(tmp_path, "fx-assert-both"),
    }
    low = evaluate_assertions(
        [{"capture_id": "fx-assert-low", "min": 1.0, "max": 4.0}], entries
    )[0]
    assert low.verdict == "fail"
    assert low.reasons == ("below_min",)
    high = evaluate_assertions(
        [{"capture_id": "fx-assert-high", "min": 0.0, "max": 3.0}], entries
    )[0]
    assert high.verdict == "fail"
    assert high.reasons == ("above_max",)
    both = evaluate_assertions(
        [{"capture_id": "fx-assert-both", "min": 1.0, "max": 3.0}], entries
    )[0]
    assert both.verdict == "fail"
    assert both.reasons == ("below_min", "above_max")


def test_fx_assert_single_bound_never_consults_the_absent_one(
    tmp_path: Path,
) -> None:
    """min-only / max-only: the absent bound is never consulted, so a
    value that would break it cannot flip the verdict."""
    write_capture(tmp_path, "fx-assert-min-only", values=(0.5, 2.0, 2.5))
    write_capture(tmp_path, "fx-assert-max-only", values=(0.5, 2.0, 2.5))
    entries = {
        **_assert_entries(tmp_path, "fx-assert-min-only"),
        **_assert_entries(tmp_path, "fx-assert-max-only"),
    }
    # min-only passes even though the max (2.5) would break a max bound
    # of 2.0; max-only passes even though the min (0.5) would break a min
    # bound of 1.0.
    min_only = evaluate_assertions(
        [{"capture_id": "fx-assert-min-only", "min": 0.4}], entries
    )[0]
    assert min_only.verdict == "pass"
    max_only = evaluate_assertions(
        [{"capture_id": "fx-assert-max-only", "max": 2.6}], entries
    )[0]
    assert max_only.verdict == "pass"
    failing_min = evaluate_assertions(
        [{"capture_id": "fx-assert-min-only", "min": 0.6}], entries
    )[0]
    assert failing_min.verdict == "fail"


def test_fx_assert_empty_window_is_not_evaluated_and_never_passes(
    tmp_path: Path,
) -> None:
    """The honesty crux: an empty window is ``not_evaluated`` — the pass
    count does NOT include it."""
    write_capture(tmp_path, "fx-assert-empty", values=(1.0, 2.0, 3.0), interval=1.0)
    source = load_series_set(tmp_path, ["fx-assert-empty"])[0]
    stats = region_stats(series_samples(source), lo=100.0, hi=200.0)
    assert stats.count == 0
    results = evaluate_assertions(
        [{"capture_id": "fx-assert-empty", "min": 0.0}], {"fx-assert-empty": stats}
    )
    assert results[0].verdict == "not_evaluated"
    passed = [row for row in results if row.verdict == "pass"]
    assert passed == []


def test_assertion_target_outside_the_request_set_refuses(tmp_path: Path) -> None:
    write_capture(tmp_path, "fx-assert-in", values=(1.0,))
    entries = _assert_entries(tmp_path, "fx-assert-in")
    with pytest.raises(
        ValueError, match="standalone_report_assert_target: fx-assert-out"
    ):
        evaluate_assertions(
            [{"capture_id": "fx-assert-out", "min": 0.0}], entries
        )


def test_assertion_bounds_must_be_finite_and_at_least_one(tmp_path: Path) -> None:
    write_capture(tmp_path, "fx-assert-bounds", values=(1.0,))
    entries = _assert_entries(tmp_path, "fx-assert-bounds")
    with pytest.raises(ValueError, match="standalone_report_assert_bound"):
        evaluate_assertions(
            [{"capture_id": "fx-assert-bounds", "min": float("nan")}], entries
        )
    with pytest.raises(ValueError, match="standalone_report_assert_bound"):
        evaluate_assertions(
            [{"capture_id": "fx-assert-bounds", "max": float("inf")}], entries
        )
    with pytest.raises(ValueError, match="standalone_report_assert_bound"):
        evaluate_assertions([{"capture_id": "fx-assert-bounds"}], entries)


def test_assert_rows_carry_the_definition_and_denominators(
    tmp_path: Path,
) -> None:
    write_capture(tmp_path, "fx-assert-labelled", values=(1.0, 2.0))
    row = evaluate_assertions(
        [{"capture_id": "fx-assert-labelled", "max": 5.0}],
        _assert_entries(tmp_path, "fx-assert-labelled"),
    )[0]
    assert row.definition == ASSERT_DEFINITION == "benchweave-assert/1"
    assert row.uncertainty == "unknown"
    assert row.lo is None and row.hi is None
    assert row.count == 2 and row.null_count == 0


# --- I4b.1 AR-9e: the streaming full-extent reducer's decimate parity ----------------


def test_decimated_extent_equals_decimate_minmax_point_for_point(
    tmp_path: Path,
) -> None:
    """AR-9e: the streaming reducer over the WHOLE series equals
    ``decimate_minmax(list(series_samples(source)), columns)`` — the
    tie-breaks (first min, last max, single-point column emits one point)
    are load-bearing, on the alternating fixture and the spike fixture
    (whose single high point must survive any reduction)."""
    from benchweave_sdk_server.plots import decimate_minmax

    for capture_id, values in (
        ("fx-alt", tuple(float(index % 2) for index in range(10_000))),
        ("fx-spike", tuple(10.0 if index == 5000 else 0.0 for index in range(10_000))),
    ):
        write_capture(tmp_path, capture_id, values=values)
        source = load_series_set(tmp_path, [capture_id])[0]
        for columns in (600, 7, 1):
            streaming = decimated_extent(source, columns)
            materialised = decimate_minmax(list(series_samples(source)), columns=columns)
            assert streaming == materialised, (capture_id, columns)


def test_decimated_extent_identity_below_the_budget(tmp_path: Path) -> None:
    """At or below the column budget the reduction is the identity — the
    whole (bounded) list, verified against the same digest check."""
    from benchweave_sdk_server.plots import decimate_minmax

    write_capture(tmp_path, "fx-tiny", values=(1.0, 9.0, 4.0))
    source = load_series_set(tmp_path, ["fx-tiny"])[0]
    assert decimated_extent(source, 8) == list(series_samples(source))
    assert decimated_extent(source, 8) == decimate_minmax(
        list(series_samples(source)), columns=8
    )


def test_decimated_extent_single_sample_takes_the_identity_branch(
    tmp_path: Path,
) -> None:
    """count == 1 sits at or below any positive column budget, so BOTH
    paths take the identity branch and emit the point ONCE (decimate's
    degenerate double-emission branch needs len(points) > columns with a
    degenerate x extent — unreachable for the loader's strictly
    increasing uniform grid; the reducer keeps the branch only for
    structural parity with decimate's own shape)."""
    from benchweave_sdk_server.plots import decimate_minmax

    write_capture(tmp_path, "fx-one", values=(5.5,))
    source = load_series_set(tmp_path, ["fx-one"])[0]
    expected = decimate_minmax(list(series_samples(source)), columns=600)
    assert expected == [(0.0, 5.5)]
    assert decimated_extent(source, 600) == expected


def test_decimated_extent_parity_survives_nulls(tmp_path: Path) -> None:
    """Nulls (NaN samples) ride both paths: the parity holds point-for-
    point including the columns whose first or last point is NaN — the
    reducer mirrors decimate's max-over-reversed exactly (a NaN survives
    as a column's maximum only when it is that column's FINAL point).
    The comparator is NaN-aware: tuple ``==`` is False for NaN elements,
    so a plain list compare would report a divergence that is not one."""
    from benchweave_sdk_server.plots import decimate_minmax

    def same_points(
        left: list[tuple[float, float]], right: list[tuple[float, float]]
    ) -> bool:
        return len(left) == len(right) and all(
            ta == tb and (va == vb or (math.isnan(va) and math.isnan(vb)))
            for (ta, va), (tb, vb) in zip(left, right, strict=True)
        )

    values = tuple(
        float(index % 3) if index % 97 else math.nan for index in range(3000)
    )
    write_capture(tmp_path, "fx-ext-nulls", values=values)
    source = load_series_set(tmp_path, ["fx-ext-nulls"])[0]
    for columns in (600, 13):
        assert same_points(
            decimated_extent(source, columns),
            decimate_minmax(list(series_samples(source)), columns=columns),
        ), columns


def test_decimated_extent_verifies_the_digest(tmp_path: Path) -> None:
    """The streaming pass hashes as it reads: a primary mutated after
    load refuses instead of feeding unverified bytes to the context
    chart (the windowed_points discipline)."""
    values = tuple(float(index % 5) for index in range(2000))
    event = write_capture(tmp_path, "fx-ext-tamper", values=values)
    source = load_series_set(tmp_path, ["fx-ext-tamper"])[0]
    (event / "fx-ext-tamper.f64").write_bytes(
        b"".join(struct.pack("<d", v) for v in values[:-1]) + struct.pack("<d", 9.0)
    )
    with pytest.raises(ValueError, match="standalone_report_primary_mismatch"):
        decimated_extent(source, 600)


# --- the refute fold (I4b.1): A-F1 non-finite timing, A-F7 type guard, A-15 ---------
#
# The fold's RED controls are the tests themselves against the pre-fold
# tree (each below reddens without its mechanism) plus the named
# neutralizations run during the fold.


def test_a_f1_non_finite_means_null_the_whole_timing_family(
    tmp_path: Path,
) -> None:
    """A-F1: inf/overflow means give the timing family real values where
    the contract names null (settle_time 0.0 = "settled instantly" with
    detected=yes, and NaN FLOAT crossings). The whole timing family —
    crossings AND settle — is null whenever baseline/final/step are
    non-finite. Shapes: the inf head, the inf tail, and the finite
    overflow (1e308 plateau whose head sum overflows). The mixed +/-inf
    shape has FINITE means and belongs to the crossings arm below."""
    shapes = {
        "fx-nf-head": (float("inf"),) * 150 + (0.0,) * 850,
        "fx-nf-tail": (0.0,) * 850 + (float("inf"),) * 150,
        "fx-nf-overflow": (1e308,) * 150 + (1.0,) * 850,
    }
    for capture_id, values in shapes.items():
        write_capture(tmp_path, capture_id, values=values)
        source = load_series_set(tmp_path, [capture_id])[0]
        edge = edge_analysis(series_samples(source), lo=None, hi=None, settle_pct=2.0)
        assert edge.t10 is None, capture_id
        assert edge.t90 is None, capture_id
        assert edge.rise_time is None, capture_id
        assert edge.settle_time is None, (
            f"{capture_id}: non-finite means must never claim settlement "
            f"(got {edge.settle_time})"
        )
        for field in (edge.rise_time, edge.settle_time, edge.t10, edge.t90):
            assert field is None or math.isfinite(field), capture_id


def test_a_f1_crossings_are_never_nan_floats(tmp_path: Path) -> None:
    """A-F1's second consequence: a bracket whose interpolation divides by
    a non-finite span (-inf -> +inf under a finite level) must yield the
    absent crossing (None), never a NaN float where the contract names
    null."""
    values = (
        (0.0,) * 300
        + (float("-inf"), float("inf")) * 50
        + (1.0,) * 300
    )
    write_capture(tmp_path, "fx-nf-bracket", values=values)
    source = load_series_set(tmp_path, ["fx-nf-bracket"])[0]
    edge = edge_analysis(series_samples(source), lo=None, hi=None, settle_pct=2.0)
    for field in (edge.t10, edge.t90, edge.rise_time, edge.settle_time):
        assert field is None or math.isfinite(field)


def test_fx_step_nocross_pins_settle_time_null_too(tmp_path: Path) -> None:
    """The nocross arm extended (the fold): the absent-crossing shape
    pins settle_time as NULL as well — the pre-fold code computed a
    non-finite-band settle that claimed settlement."""
    values = (float("inf"),) * 150 + (0.0,) * 850
    write_capture(tmp_path, "fx-step-nocross", values=values)
    source = load_series_set(tmp_path, ["fx-step-nocross"])[0]
    edge = edge_analysis(series_samples(source), lo=None, hi=None, settle_pct=2.0)
    assert edge.detected is True
    assert edge.t10 is None and edge.t90 is None
    assert edge.rise_time is None
    assert edge.settle_time is None
    assert edge.settle_time != 0.0


def test_settle_zero_is_reachable_at_the_default_band(tmp_path: Path) -> None:
    """Deviation-4 arm rebuilt (the fold): settle_time == 0.0 IS reachable
    at settle_pct=2 — an instantaneous step (the first in-scope sample is
    already on the final plateau) has nothing outside the band. The 0
    outcome is pinned where it actually occurs."""
    values = (0.0,) * 500 + (1.0,) * 500
    write_capture(tmp_path, "fx-step-instant", values=values)
    source = load_series_set(tmp_path, ["fx-step-instant"])[0]
    edge = edge_analysis(series_samples(source), lo=None, hi=None, settle_pct=2.0)
    assert edge.detected is True
    assert edge.rise_time is not None and edge.rise_time > 0
    assert edge.settle_time == 0.0


def test_a_f7_assertion_bounds_refuse_bools_and_strings(tmp_path: Path) -> None:
    """A-F7: a bool bound launders to 1.0 via float(); a numeric STRING
    passes the isfinite(float()) pre-check and then raises TypeError
    outside the ValueError mapping. Both refuse typed inside the
    ValueError family (unreachable through seam.call today — the schema
    fronts them — so this arm guards the pure function directly)."""
    write_capture(tmp_path, "fx-assert-types", values=(1.0,))
    entries = _assert_entries(tmp_path, "fx-assert-types")
    for bad in (True, "1.0"):
        with pytest.raises(ValueError, match="standalone_report_assert_bound"):
            evaluate_assertions(
                [{"capture_id": "fx-assert-types", "min": bad}], entries
            )


# --- I4b.2: power modes with V/I pairing (AR-3 amended, AR-10, AR-11) ---------------
#
# The definition under test is ``benchweave-power/1`` (the I4b record
# §1.4): pairing keys on unit/quantity — NEVER names (Q8's ruling; the
# fork's name-regex role guessing is not carried) — power at a sample is
# V×I only where BOTH sides are non-null (the fork's null→0 coercion is
# not carried: the fork would report ≈5.983 W on the one-null fixture),
# and every integral is gap-visible (``integrated_span_s`` +
# ``dropped_segments`` beside Ah/Wh, never interpolated across nulls).
# The AR-3 energy figure is the AMENDED one: the trapezoid spans
# (N−1) intervals over the landed uniform time base, so
# energy = 6 × (N−1) × interval / 3600 — not the naive N×interval product.


def _power_set(
    root: Path, capture_ids: tuple[str, ...] | list[str]
) -> list[tuple[Any, list[tuple[float, float]]]]:
    """The loaded (source, full points) pairs ``power_analysis`` takes —
    full-extent points; the window is the function's own job."""
    return [
        (source, windowed_points(source, lo=None, hi=None, limit=1_000_000))
        for source in load_series_set(root, list(capture_ids))
    ]


def test_unit_kind_classifies_the_fork_vocabulary() -> None:
    """The fork's own ``unitKind`` vocabulary, verbatim: lowercase with
    µ/μ folded to u; the current and voltage sets; everything else —
    notably ``W`` — is unpairable ``other`` (AR-10)."""
    for unit in ("A", "a", "mA", "µA", "μA", "uA", "nA"):
        assert unit_kind(unit) == "current", unit
    for unit in ("V", "v", "mV", "µV", "kV"):
        assert unit_kind(unit) == "voltage", unit
    for unit in ("W", "Ω", "s", "°C"):
        assert unit_kind(unit) == "other", unit


def test_power_modes_are_the_four_named_presentations() -> None:
    assert POWER_MODES == ("battery", "dc-dc", "sleep", "load-step")


# --- AR-3 (amended): pairing, honest nulls, the never-0-W arm ----------------------


def test_fx_pair_const_mean_peak_and_amended_energy(tmp_path: Path) -> None:
    """V = 2, I = 3, 100 Hz, N = 360, t = 0 … 3.59 s: mean/peak power 6 W
    and energy = 6 × (N−1) × interval / 3600 Wh (the AMENDED figure — the
    trapezoid spans 359 intervals, not 360)."""
    write_capture(
        tmp_path, "fx-pair-v", values=(2.0,) * 360, interval=0.01, unit="V"
    )
    write_capture(
        tmp_path, "fx-pair-i", values=(3.0,) * 360, interval=0.01, unit="A"
    )
    result = power_analysis(
        _power_set(tmp_path, ("fx-pair-v", "fx-pair-i")),
        mode="battery",
        lo=None,
        hi=None,
    )
    assert result.unavailable is None
    assert len(result.rails) == 1
    rail = result.rails[0]
    assert (rail.v_id, rail.i_id) == ("fx-pair-v", "fx-pair-i")
    assert (rail.count, rail.null_count) == (360, 0)
    assert rail.mean_p == 6.0 and rail.peak_p == 6.0
    assert rail.mean_v == 2.0 and rail.min_v == 2.0
    assert rail.mean_i == 3.0 and rail.peak_i == 3.0
    # The amended AR-3 figure: 6 × (N−1) × interval / 3600.
    assert rail.wh.value is not None and _ulp(
        rail.wh.value, 6.0 * (360 - 1) * 0.01 / 3600.0
    )
    assert rail.wh.counted_segments == 359
    assert rail.wh.dropped_segments == 0
    assert _ulp(rail.wh.integrated_span_s, 359 * 0.01)
    assert rail.ah.value is not None and _ulp(
        rail.ah.value, 3.0 * (360 - 1) * 0.01 / 3600.0
    )
    assert rail.definition == POWER_DEFINITION and rail.uncertainty == "unknown"
    assert rail.wh.definition == POWER_DEFINITION


def test_fx_pair_const_null_excludes_and_counts(tmp_path: Path) -> None:
    """AR-3's one-null arm + AR-10's gap arm on one fixture: the null pair
    is excluded AND counted (count 359, null_count 1), mean power stays
    6 W (the fork's coercion would report ≈5.983 W), and the energy
    integral drops the two segments touching the null —
    ``integrated_span_s`` 3.57 (357 × 0.01 s), ``dropped_segments`` 2,
    energy 6 × 3.57 / 3600 Wh. The gap is visible in the row, never
    interpolated across."""
    i_values = [3.0] * 360
    i_values[180] = math.nan
    write_capture(
        tmp_path, "fx-pair-v", values=(2.0,) * 360, interval=0.01, unit="V"
    )
    write_capture(
        tmp_path, "fx-pair-i", values=tuple(i_values), interval=0.01, unit="A"
    )
    result = power_analysis(
        _power_set(tmp_path, ("fx-pair-v", "fx-pair-i")),
        mode="battery",
        lo=None,
        hi=None,
    )
    rail = result.rails[0]
    assert (rail.count, rail.null_count) == (359, 1)
    assert rail.mean_p == 6.0 and rail.peak_p == 6.0
    assert rail.wh.dropped_segments == 2
    assert rail.wh.counted_segments == 357
    assert _ulp(rail.wh.integrated_span_s, 3.57)
    assert rail.wh.value is not None and _ulp(
        rail.wh.value, 6.0 * 357 * 0.01 / 3600.0
    )
    # Ah integrates the current series alone: the same null shape.
    assert rail.ah.dropped_segments == 2
    assert rail.ah.counted_segments == 357


def test_pairing_ignores_names_and_keys_on_units(tmp_path: Path) -> None:
    """AR-3's pairing-by-unit arm: names that bait a name-regex (a
    V-class capture named like a current, and vice versa) do not move the
    pairing — the unit classifies."""
    write_capture(
        tmp_path,
        "fx-sense-current-named",
        values=(2.0,) * 10,
        interval=0.01,
        unit="V",
    )
    write_capture(
        tmp_path,
        "fx-sense-voltage-named",
        values=(3.0,) * 10,
        interval=0.01,
        unit="A",
    )
    result = power_analysis(
        _power_set(tmp_path, ("fx-sense-current-named", "fx-sense-voltage-named")),
        mode="battery",
        lo=None,
        hi=None,
    )
    assert len(result.rails) == 1
    assert result.rails[0].v_id == "fx-sense-current-named"
    assert result.rails[0].i_id == "fx-sense-voltage-named"


def test_no_current_series_yields_no_rows_never_zero(tmp_path: Path) -> None:
    """AR-3's never-0-W arm: two V series and no A series → power rows
    ABSENT with the ``power_unavailable: no current series`` reason."""
    write_capture(tmp_path, "fx-nov-i-v1", values=(2.0,) * 10, unit="V")
    write_capture(tmp_path, "fx-nov-i-v2", values=(3.0,) * 10, unit="mV")
    result = power_analysis(
        _power_set(tmp_path, ("fx-nov-i-v1", "fx-nov-i-v2")),
        mode="battery",
        lo=None,
        hi=None,
    )
    assert result.rails == ()
    assert result.unavailable == "power_unavailable: no current series"
    assert result.battery is None


def test_fx_units_shows_the_classification(tmp_path: Path) -> None:
    """AR-10's vocabulary arm over a set: µA pairs with mV; ``W`` is
    unpairable other and forms no rail."""
    write_capture(tmp_path, "fx-units-uax", values=(1.0,) * 10, unit="µA")
    write_capture(tmp_path, "fx-units-mv", values=(2.0,) * 10, unit="mV")
    write_capture(tmp_path, "fx-units-w", values=(3.0,) * 10, unit="W")
    result = power_analysis(
        _power_set(tmp_path, ("fx-units-uax", "fx-units-mv", "fx-units-w")),
        mode="battery",
        lo=None,
        hi=None,
    )
    assert len(result.rails) == 1
    assert (result.rails[0].v_id, result.rails[0].i_id) == (
        "fx-units-mv",
        "fx-units-uax",
    )


# --- AR-10: pairing honesty and gap integrals ---------------------------------------


def test_current_only_set_yields_ah_and_the_reason(tmp_path: Path) -> None:
    """AR-10's partial-pair arm: a current series with no voltage partner
    still yields Ah, with wh null (value absent) and the
    ``power_unavailable: no voltage series`` reason beside it."""
    write_capture(
        tmp_path, "fx-ionly-i", values=(0.5,) * 100, interval=0.01, unit="A"
    )
    result = power_analysis(
        _power_set(tmp_path, ("fx-ionly-i",)),
        mode="battery",
        lo=None,
        hi=None,
    )
    assert len(result.rails) == 1
    rail = result.rails[0]
    assert rail.v_id is None
    assert rail.reason == "power_unavailable: no voltage series"
    assert rail.ah.value is not None and _ulp(
        rail.ah.value, 0.5 * 99 * 0.01 / 3600.0
    )
    assert rail.wh.value is None
    assert rail.mean_p is None and rail.peak_p is None


def test_default_pairing_follows_request_order(tmp_path: Path) -> None:
    """AR-10's ordering arm: the deterministic default pairs the FIRST
    voltage-class and FIRST current-class source in REQUEST order — ids
    whose sort order disagrees with the request order prove the rule."""
    write_capture(tmp_path, "fx-b-v", values=(2.0,) * 10, unit="V")
    write_capture(tmp_path, "fx-a-v", values=(3.0,) * 10, unit="V")
    write_capture(tmp_path, "fx-b-i", values=(0.1,) * 10, unit="A")
    write_capture(tmp_path, "fx-a-i", values=(0.2,) * 10, unit="A")
    result = power_analysis(
        _power_set(tmp_path, ("fx-b-v", "fx-a-v", "fx-b-i", "fx-a-i")),
        mode="dc-dc",
        lo=None,
        hi=None,
    )
    assert [(rail.v_id, rail.i_id) for rail in result.rails] == [
        ("fx-b-v", "fx-b-i"),
        ("fx-a-v", "fx-a-i"),
    ]


def test_leftover_currents_form_i_only_rails_in_request_order(tmp_path: Path) -> None:
    """Two currents, one voltage: the unpaired current keeps its Ah as an
    i-only rail (the partial-pair honesty rule), after the complete pair."""
    write_capture(tmp_path, "fx-mix-v", values=(2.0,) * 10, unit="V")
    write_capture(tmp_path, "fx-mix-i1", values=(0.1,) * 10, unit="A")
    write_capture(tmp_path, "fx-mix-i2", values=(0.2,) * 10, unit="A")
    result = power_analysis(
        _power_set(tmp_path, ("fx-mix-v", "fx-mix-i1", "fx-mix-i2")),
        mode="battery",
        lo=None,
        hi=None,
    )
    assert [(rail.v_id, rail.i_id) for rail in result.rails] == [
        ("fx-mix-v", "fx-mix-i1"),
        (None, "fx-mix-i2"),
    ]
    assert result.rails[1].reason == "power_unavailable: no voltage series"


def test_explicit_rails_reassign_roles(tmp_path: Path) -> None:
    """The operator's resolved rails replace the default pairing (the
    fork's railSelect re-keyed on capture_id); an explicit i-only row
    (v omitted) declares a current without its voltage."""
    write_capture(tmp_path, "fx-x-v1", values=(2.0,) * 10, unit="V")
    write_capture(tmp_path, "fx-x-v2", values=(3.0,) * 10, unit="V")
    write_capture(tmp_path, "fx-x-i1", values=(0.1,) * 10, unit="A")
    write_capture(tmp_path, "fx-x-i2", values=(0.2,) * 10, unit="A")
    result = power_analysis(
        _power_set(tmp_path, ("fx-x-v1", "fx-x-v2", "fx-x-i1", "fx-x-i2")),
        mode="dc-dc",
        rails=[{"v": "fx-x-v2", "i": "fx-x-i2"}, {"i": "fx-x-i1"}],
        lo=None,
        hi=None,
    )
    assert [(rail.v_id, rail.i_id) for rail in result.rails] == [
        ("fx-x-v2", "fx-x-i2"),
        (None, "fx-x-i1"),
    ]


def test_explicit_rails_refuse_unknown_wrongclass_and_reuse(
    tmp_path: Path,
) -> None:
    write_capture(tmp_path, "fx-val-v", values=(2.0,) * 10, unit="V")
    write_capture(tmp_path, "fx-val-i", values=(0.1,) * 10, unit="A")
    series = _power_set(tmp_path, ("fx-val-v", "fx-val-i"))
    for rails in (
        [{"v": "fx-ghost", "i": "fx-val-i"}],
        [{"v": "fx-val-i", "i": "fx-val-i"}],
        [{"v": "fx-val-v", "i": "fx-val-v"}],
        [{"v": "fx-val-v", "i": "fx-val-i"}, {"v": "fx-val-v", "i": "fx-val-i"}],
    ):
        with pytest.raises(ValueError, match="standalone_report_power_rails"):
            power_analysis(series, mode="battery", rails=rails, lo=None, hi=None)


def test_interval_mismatch_between_rail_sides_refuses(tmp_path: Path) -> None:
    """A rail pairs samples on a SHARED uniform grid: differing
    sample_interval_s between the V and the I side refuses typed (never
    an invented time alignment)."""
    write_capture(
        tmp_path, "fx-rate-v", values=(2.0,) * 100, interval=0.01, unit="V"
    )
    write_capture(
        tmp_path, "fx-rate-i", values=(3.0,) * 10, interval=0.1, unit="A"
    )
    with pytest.raises(ValueError, match="standalone_report_power_pairing"):
        power_analysis(
            _power_set(tmp_path, ("fx-rate-v", "fx-rate-i")),
            mode="battery",
            lo=None,
            hi=None,
        )


def test_zero_or_nonfinite_interval_refuses_at_load(tmp_path: Path) -> None:
    """AR-10's zero-span arm is structural (*is refused unless*): a
    non-positive or non-finite interval refuses at LOAD, so no code path
    downstream ever sees a degenerate time base — the fork's
    ``t1 - t0 || 1`` substitution cannot arise."""
    for interval in (0.0, -0.01, math.inf):
        write_capture(
            tmp_path,
            f"fx-badrate-{interval}",
            values=(1.0,) * 4,
            interval=interval,
        )
        with pytest.raises(
            ValueError, match="standalone_report_manifest_incomplete"
        ):
            load_series_set(tmp_path, [f"fx-badrate-{interval}"])


def test_power_scalar_params_refuse_typed(tmp_path: Path) -> None:
    """Mode names and the mode scalars refuse inside the family: an
    unknown mode, a non-finite/bool threshold, and a non-positive or
    non-finite capacity_ah (the A-F7/A-F8 posture at the pure layer —
    the schema fronts REST/MCP, the seam call needs the same refusal)."""
    write_capture(tmp_path, "fx-pv", values=(2.0,) * 10, unit="V")
    write_capture(tmp_path, "fx-pi", values=(0.5,) * 10, unit="A")
    series = _power_set(tmp_path, ("fx-pv", "fx-pi"))
    with pytest.raises(ValueError, match="standalone_report_power_mode"):
        power_analysis(series, mode="turbo", lo=None, hi=None)
    for threshold in (float("nan"), float("inf"), True):
        with pytest.raises(ValueError, match="standalone_report_power_param"):
            power_analysis(
                series, mode="sleep", threshold=threshold, lo=None, hi=None
            )
    for capacity in (0.0, -2.0, float("nan"), True):
        with pytest.raises(ValueError, match="standalone_report_power_param"):
            power_analysis(
                series,
                mode="battery",
                capacity_ah=capacity,
                lo=None,
                hi=None,
            )


def test_window_bounds_apply_to_pairs_and_integrals(tmp_path: Path) -> None:
    """The one window is the region for the power family too: pairs and
    integral segments clip to the inclusive [lo, hi] over the STORED
    float time base. Precision note: t is index × interval in binary64,
    so the sample "at 0.70 s" stores t = 0.7000000000000001 and a window
    ending at 0.70 EXCLUDES it (fl(71 × 0.01) = 0.71 exactly, so a
    0.71-bound includes its k = 71 sample) — the same inclusive
    comparison every landed family makes against the stored t."""
    write_capture(
        tmp_path, "fx-win-v", values=(2.0,) * 100, interval=0.01, unit="V"
    )
    write_capture(
        tmp_path, "fx-win-i", values=(3.0,) * 100, interval=0.01, unit="A"
    )
    result = power_analysis(
        _power_set(tmp_path, ("fx-win-v", "fx-win-i")),
        mode="battery",
        lo=0.5,
        hi=0.71,
    )
    rail = result.rails[0]
    assert rail.count == 22  # t = 0.50 … 0.71 inclusive on the stored grid
    assert rail.wh.counted_segments == 21
    assert _ulp(rail.wh.integrated_span_s, 0.21)
    assert rail.wh.value is not None and _ulp(
        rail.wh.value, 6.0 * 21 * 0.01 / 3600.0
    )


# --- AR-10: the trapezoid definition itself ------------------------------------------


def test_trapezoid_clips_with_interpolation_at_bounds() -> None:
    """The fork's definition verbatim: per-segment trapezoid clipped to
    the window with LINEAR INTERPOLATION at the clipped bounds. The grid
    (0.25 steps, ramp values) is binary-exact, so equality is exact."""
    points = [(0.0, 0.0), (0.25, 1.0), (0.5, 2.0), (0.75, 3.0), (1.0, 4.0)]
    clipped = trapezoid_integral(points, 0.125, 0.875)
    assert clipped.value == 1.5
    assert clipped.integrated_span_s == 0.75
    assert clipped.counted_segments == 4
    assert clipped.dropped_segments == 0
    full = trapezoid_integral(points, None, None)
    assert full.value == 2.0
    assert full.counted_segments == 4


def test_trapezoid_gap_rule_drops_and_reports() -> None:
    """A segment whose either endpoint is null is dropped, never
    interpolated across; an out-of-window null drops nothing."""
    points = [
        (0.0, 0.0),
        (0.25, math.nan),
        (0.5, 2.0),
        (0.75, 3.0),
        (1.0, 4.0),
    ]
    gapped = trapezoid_integral(points, None, None)
    assert gapped.dropped_segments == 2
    assert gapped.counted_segments == 2
    assert gapped.integrated_span_s == 0.5
    assert gapped.value == 1.5
    after = trapezoid_integral(points, 0.5, 1.0)
    assert after.dropped_segments == 0
    assert after.counted_segments == 2


def test_trapezoid_absent_value_is_none_never_zero() -> None:
    """No counted segments — all-null data or a lone sample — is an
    absent integral, never 0 (a zero integral over real zeros is a
    value; no data is not)."""
    all_null = [(float(index) * 0.25, math.nan) for index in range(4)]
    result = trapezoid_integral(all_null, None, None)
    assert result.value is None
    assert result.dropped_segments == 3
    lone = trapezoid_integral([(0.0, 1.0)], None, None)
    assert lone.value is None and lone.counted_segments == 0
    zeros = [(float(index) * 0.25, 0.0) for index in range(4)]
    real_zero = trapezoid_integral(zeros, None, None)
    assert real_zero.value == 0.0


# --- AR-11: the four mode blocks ------------------------------------------------------


def test_battery_runtime_with_denominators(tmp_path: Path) -> None:
    """capacity_ah = 2 over mean I = 0.5 A → runtime_h = 4 with its
    denominators carried; no capacity_ah → no runtime (never a default
    capacity)."""
    write_capture(
        tmp_path, "fx-bat-v", values=(3.7,) * 100, interval=0.01, unit="V"
    )
    write_capture(
        tmp_path, "fx-bat-i", values=(0.5,) * 100, interval=0.01, unit="A"
    )
    series = _power_set(tmp_path, ("fx-bat-v", "fx-bat-i"))
    result = power_analysis(
        series, mode="battery", capacity_ah=2.0, lo=None, hi=None
    )
    battery = result.battery
    assert battery is not None
    assert battery.capacity_ah == 2.0
    assert battery.mean_i == 0.5
    assert battery.runtime_h is not None and _ulp(battery.runtime_h, 4.0)
    assert battery.peak_i == 0.5 and battery.mean_v == 3.7 and battery.min_v == 3.7
    assert battery.wh is not None and _ulp(
        battery.wh, 1.85 * 99 * 0.01 / 3600.0
    )
    assert battery.definition == POWER_DEFINITION
    unresourced = power_analysis(series, mode="battery", lo=None, hi=None)
    assert unresourced.battery is not None
    assert unresourced.battery.capacity_ah is None
    assert unresourced.battery.runtime_h is None


def test_dcdc_eta_and_the_zero_pin_arm(tmp_path: Path) -> None:
    """Two rails with known powers: η = pout/pin × 100; a rail with
    |pin| ≤ 1e-9 yields η absent — never inf, never 0."""
    write_capture(
        tmp_path, "fx-dc-in-v", values=(12.0,) * 50, interval=0.01, unit="V"
    )
    write_capture(
        tmp_path, "fx-dc-in-i", values=(1.0,) * 50, interval=0.01, unit="A"
    )
    write_capture(
        tmp_path, "fx-dc-out-v", values=(5.0,) * 50, interval=0.01, unit="V"
    )
    write_capture(
        tmp_path, "fx-dc-out-i", values=(2.0,) * 50, interval=0.01, unit="A"
    )
    result = power_analysis(
        _power_set(
            tmp_path,
            ("fx-dc-in-v", "fx-dc-in-i", "fx-dc-out-v", "fx-dc-out-i"),
        ),
        mode="dc-dc",
        lo=None,
        hi=None,
    )
    dcdc = result.dcdc
    assert dcdc is not None
    assert dcdc.pin == 12.0 and dcdc.pout == 10.0
    assert dcdc.eta_pct is not None and _ulp(dcdc.eta_pct, 10.0 / 12.0 * 100.0)
    # The zero-pin arm: input power 0 W → η absent.
    write_capture(
        tmp_path, "fx-dc-zero-v", values=(0.0,) * 50, interval=0.01, unit="V"
    )
    write_capture(
        tmp_path, "fx-dc-zero-i", values=(1.0,) * 50, interval=0.01, unit="A"
    )
    zero = power_analysis(
        _power_set(
            tmp_path,
            ("fx-dc-zero-v", "fx-dc-zero-i", "fx-dc-out-v", "fx-dc-out-i"),
        ),
        mode="dc-dc",
        lo=None,
        hi=None,
    )
    assert zero.dcdc is not None
    assert zero.dcdc.pin == 0.0
    assert zero.dcdc.eta_pct is None
    assert zero.dcdc.reason is not None


def test_sleep_duty_classes_and_the_no_threshold_arm(tmp_path: Path) -> None:
    """Known threshold, known duty: duty % and class means match closed
    form; threshold ABSENT → ``not_evaluated: no threshold`` (the fork's
    midpoint default not carried); an empty class reports its count and
    an absent mean, never 0 A."""
    write_capture(
        tmp_path, "fx-slp-v", values=(3.7,) * 100, interval=0.01, unit="V"
    )
    write_capture(
        tmp_path,
        "fx-slp-i",
        values=(0.001,) * 60 + (0.100,) * 40,
        interval=0.01,
        unit="A",
    )
    series = _power_set(tmp_path, ("fx-slp-v", "fx-slp-i"))
    result = power_analysis(
        series, mode="sleep", threshold=0.01, lo=None, hi=None
    )
    sleep = result.sleep
    assert sleep is not None
    assert sleep.verdict == "evaluated"
    assert sleep.count == 100
    assert sleep.above_count == 40 and sleep.below_count == 60
    assert sleep.above_mean is not None and _ulp(sleep.above_mean, 0.1)
    assert sleep.below_mean is not None and _ulp(sleep.below_mean, 0.001)
    assert sleep.duty_pct == 40.0
    # No threshold: not_evaluated, never a midpoint default.
    bare = power_analysis(series, mode="sleep", lo=None, hi=None)
    assert bare.sleep is not None
    assert bare.sleep.verdict == "not_evaluated"
    assert bare.sleep.reason == "no threshold"
    assert bare.sleep.duty_pct is None
    # Empty class: every sample above → below_count 0, below_mean absent.
    write_capture(
        tmp_path,
        "fx-slp-all-i",
        values=(0.100,) * 100,
        interval=0.01,
        unit="A",
    )
    all_above = power_analysis(
        _power_set(tmp_path, ("fx-slp-v", "fx-slp-all-i")),
        mode="sleep",
        threshold=0.01,
        lo=None,
        hi=None,
    )
    assert all_above.sleep is not None
    assert all_above.sleep.below_count == 0
    assert all_above.sleep.below_mean is None
    assert all_above.sleep.duty_pct == 100.0


def test_loadstep_resistance_and_the_tiny_di_arm(tmp_path: Path) -> None:
    """Known ΔV/ΔI: R = −ΔV/ΔI; |ΔI| ≤ 1e-9 → R absent. Head/tail means
    are the 15% rule (max(1, floor(n × 0.15))) per series."""
    write_capture(
        tmp_path,
        "fx-ls-v",
        values=(5.0,) * 100 + (4.0,) * 100,
        interval=0.01,
        unit="V",
    )
    write_capture(
        tmp_path,
        "fx-ls-i",
        values=(0.010,) * 100 + (0.110,) * 100,
        interval=0.01,
        unit="A",
    )
    series = _power_set(tmp_path, ("fx-ls-v", "fx-ls-i"))
    result = power_analysis(series, mode="load-step", lo=None, hi=None)
    step = result.load_step
    assert step is not None
    assert step.v_n == 200 and step.i_n == 200
    assert step.v_head == 5.0 and step.v_tail == 4.0
    assert step.i_head is not None and _ulp(step.i_head, 0.01)
    assert step.i_tail is not None and _ulp(step.i_tail, 0.11)
    assert step.dv == -1.0
    assert step.di is not None and _ulp(step.di, 0.1)
    assert step.r is not None and _ulp(step.r, 10.0)
    # The tiny-ΔI arm: constant I → ΔI = 0 → R absent.
    write_capture(
        tmp_path,
        "fx-ls-flat-i",
        values=(0.050,) * 200,
        interval=0.01,
        unit="A",
    )
    flat = power_analysis(
        _power_set(tmp_path, ("fx-ls-v", "fx-ls-flat-i")),
        mode="load-step",
        lo=None,
        hi=None,
    )
    assert flat.load_step is not None
    assert flat.load_step.di == 0.0
    assert flat.load_step.dv == -1.0
    assert flat.load_step.r is None


def test_only_the_requested_mode_computes(tmp_path: Path) -> None:
    """The modes are presentations, not a batch: the requested mode's
    block is present, the other three absent."""
    write_capture(tmp_path, "fx-one-v", values=(2.0,) * 10, unit="V")
    write_capture(tmp_path, "fx-one-i", values=(0.5,) * 10, unit="A")
    result = power_analysis(
        _power_set(tmp_path, ("fx-one-v", "fx-one-i")),
        mode="load-step",
        lo=None,
        hi=None,
    )
    assert result.load_step is not None
    assert result.battery is None and result.dcdc is None and result.sleep is None
    assert result.mode == "load-step"


# --- the I4b.2 fold wave (rows A-F1/A-F2+B-F3/B-F2/A-F3) ----------------------------


def test_mixed_inf_power_renders_non_finite_never_a_crash(tmp_path: Path) -> None:
    """A-F1: mixed +inf/-inf samples must never raise out of the power
    family — CPython's ``-inf + inf in fsum`` ValueError used to escape
    through the seam as an untyped invalid_request, refusing the whole
    export while every other family renders its honest n/a (non-finite)
    marks. The exact-summation helper now falls back to the sequential
    IEEE sum for the one case fsum cannot express, so a mean over both
    signs of infinity is NaN (data present, statistic non-finite — the
    B-F8 posture) and peak stays a value."""
    write_capture(
        tmp_path,
        "fx-mix-i",
        values=(1.0, 1.0, math.inf, 1.0, -math.inf, 1.0, 1.0, 1.0),
        interval=0.01,
        unit="A",
    )
    write_capture(
        tmp_path, "fx-mix-v", values=(5.0,) * 8, interval=0.01, unit="V"
    )
    result = power_analysis(
        _power_set(tmp_path, ("fx-mix-v", "fx-mix-i")),
        mode="battery",
        lo=None,
        hi=None,
    )
    rail = result.rails[0]
    assert rail.count == 8  # inf samples are VALUES (B-F8), counted
    assert rail.mean_p is not None and math.isnan(rail.mean_p)
    assert rail.peak_p == math.inf
    assert rail.wh.value is not None and math.isnan(rail.wh.value)
    assert rail.ah.value is not None and math.isnan(rail.ah.value)
    battery = result.battery
    assert battery is not None
    assert battery.mean_i is not None and math.isnan(battery.mean_i)
    assert battery.runtime_h is None  # a non-finite divisor yields no runtime


def test_rail_length_mismatch_refuses_pairing(tmp_path: Path) -> None:
    """A-F2 + B-F3 (converged): a rail whose sides declare the SAME
    interval but DIFFERENT sample counts (one instrument stopped early)
    used to pair silently over the zip truncation — overlap-only means
    presented as window rows with null_count 0 lying, and the reverse
    orientation pairing count 100 against an Ah span from all 360. Both
    orientations refuse typed in the power_pairing family."""
    write_capture(
        tmp_path, "fx-len-v", values=(2.0,) * 360, interval=0.01, unit="V"
    )
    write_capture(
        tmp_path, "fx-len-i", values=(3.0,) * 100, interval=0.01, unit="A"
    )
    with pytest.raises(ValueError, match="standalone_report_power_pairing"):
        power_analysis(
            _power_set(tmp_path, ("fx-len-v", "fx-len-i")),
            mode="battery",
            lo=None,
            hi=None,
        )
    write_capture(
        tmp_path, "fx-len2-v", values=(2.0,) * 100, interval=0.01, unit="V"
    )
    write_capture(
        tmp_path, "fx-len2-i", values=(3.0,) * 360, interval=0.01, unit="A"
    )
    with pytest.raises(ValueError, match="standalone_report_power_pairing"):
        power_analysis(
            _power_set(tmp_path, ("fx-len2-v", "fx-len2-i")),
            mode="battery",
            lo=None,
            hi=None,
        )


def test_product_unit_labels_derive_from_the_rails() -> None:
    """B-F2: the power-unit label derives from the rail's ACTUAL units —
    W only for base V·A; any scaled rail prints its unit product, never
    asserting W over a mW-scale value (numeric scaling itself stays a
    row-call; the LABEL must be honest now)."""
    from benchweave_sdk_server.analysis import product_unit

    assert product_unit("V", "A") == "W"
    assert product_unit("mV", "A") == "mV·A"
    assert product_unit("V", "mA") == "V·mA"
    assert product_unit("mV", "µA") == "mV·µA"


def test_full_input_pinned_coverage_asymmetry(tmp_path: Path) -> None:
    """A-F3's PIN (the fold's call: pin, don't redesign): the module's
    contract names pre-windowed points (both real callers pass the
    request's windowed lists). Fed FULL point lists, the Ah integral
    follows the trapezoid definition and clips its boundary segments
    with interpolation, while the paired stream windows sample-wise —
    two coverages, one window, exactly as the docstring states."""
    write_capture(
        tmp_path, "fx-pin-v", values=(2.0,) * 100, interval=0.01, unit="V"
    )
    write_capture(
        tmp_path, "fx-pin-i", values=(3.0,) * 100, interval=0.01, unit="A"
    )
    result = power_analysis(
        _power_set(tmp_path, ("fx-pin-v", "fx-pin-i")),
        mode="battery",
        lo=0.205,
        hi=0.805,
    )
    rail = result.rails[0]
    # Ah clips: segments straddling the bounds integrate partially —
    # [0.205, 0.805] spans 0.6 s of grid.
    assert _ulp(rail.ah.integrated_span_s, 0.6)
    # Wh windows sample-wise: pairs exist only at t = 0.21 … 0.80, so
    # the counted span is the 0.59 s between them.
    assert _ulp(rail.wh.integrated_span_s, 0.59)
