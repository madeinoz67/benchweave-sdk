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
    RegionStats,
    edge_analysis,
    evaluate_assertions,
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
