"""I4a AR-4/AR-6: the self-contained HTML report renderer.

AR-4 runs over three input sets (single capture, a 2-capture different-unit
set, a windowed export): self-containment, printed digests, the
host-computed/definition/denominator labelling, clock-free
reproducibility, and escaping. AR-6 pins genericity: the renderer and the
loader carry no adapter/plugin coupling (import census + name census) and
render the same shape over one-series and two-series inputs.

``write_capture`` mirrors the writer's on-disk shape (the same fixture
discipline as test_library/test_analysis; invented ``fx-*`` names).
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import struct
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk_server.analysis import (
    ANALYSIS_DEFINITION,
    AssertionResult,
    load_series_set,
    scan_series,
    series_samples,
)
from benchweave_sdk_server.report import REPORT_PLOT_COLUMNS, ReportEntry, build_report

STYLES = "/*inlined-tokens*/:root{--bw-test:1}"
PIN_VERSION = "0.2.1-test"
SDK_VERSION = "9.9.9-test"


def write_capture(
    root: Path,
    capture_id: str,
    *,
    values: tuple[float, ...],
    interval: float = 0.001,
    unit: str = "V",
    metadata: dict[str, Any] | None = None,
) -> Path:
    payload = b"".join(struct.pack("<d", value) for value in values)
    event = root / capture_id
    event.mkdir(parents=True)
    (event / f"{capture_id}.f64").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    manifest = {
        "capture_id": capture_id,
        "format": "waveform_f64le",
        "artifact_id": "art-" + digest,
        "byte_length": len(payload),
        "sha256": digest,
        "started_at": f"2026-10-07T10:30:00+00:00-{capture_id}",
        "sample_count": len(values),
        "sample_interval_s": interval,
        "unit": unit,
        "x-standalone-state": "finalised",
        "x-standalone-manifest-version": 1,
    }
    (event / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    meta: dict[str, Any] = {
        "capture_id": capture_id,
        "device": {"id": "fx-device", "firmware": "1.2.7"},
        "plugin": {"package": "fx-plugin", "version": "0.3.1",
                   "descriptor_sha256": "f" * 64},
        "surface": "rest",
        "operator": "fx-op",
        "tags": [],
        "notes": "",
    }
    meta.update(metadata or {})
    (event / "metadata.json").write_text(json.dumps(meta, sort_keys=True))
    return event


def _entries(
    root: Path, capture_ids: list[str], *, lo: float | None = None, hi: float | None = None
) -> list[ReportEntry]:
    from benchweave_sdk_server.analysis import (
        SETTLE_PCT_DEFAULT,
        decimated_extent,
        edge_analysis,
    )

    entries: list[ReportEntry] = []
    for capture_id in capture_ids:
        source = load_series_set(root, [capture_id])[0]
        stats, _ = scan_series(source, lo=lo, hi=hi)
        points = [
            (t, value)
            for t, value in series_samples(source)
            if (lo is None or t >= lo) and (hi is None or t <= hi)
        ]
        entries.append(
            ReportEntry(
                source=source,
                stats=stats,
                points=points,
                edge=edge_analysis(
                    iter(points), lo=lo, hi=hi, settle_pct=SETTLE_PCT_DEFAULT
                ),
                context_points=decimated_extent(source, REPORT_PLOT_COLUMNS),
            )
        )
    return entries


def _render(root: Path, capture_ids: list[str], **window: float | None) -> str:
    lo, hi = window.get("lo"), window.get("hi")
    return build_report(
        _entries(root, capture_ids, lo=lo, hi=hi),
        lo=lo,
        hi=hi,
        styles=STYLES,
        pin_version=PIN_VERSION,
        sdk_version=SDK_VERSION,
    )


# --- the three AR-4 input sets ----------------------------------------------------


@pytest.fixture(scope="module")
def single_set(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("report-single")
    values = tuple(float(index % 23) for index in range(2000))
    write_capture(root, "fx-single", values=values)
    return root


@pytest.fixture(scope="module")
def double_set(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("report-double")
    write_capture(root, "fx-volt", values=tuple(1.0 + 0.5 * (i % 7) for i in range(1500)), unit="V")
    write_capture(root, "fx-amp", values=tuple(0.1 * (i % 11) for i in range(1500)), unit="A")
    return root


@pytest.fixture(scope="module")
def windowed_set(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("report-window")
    write_capture(root, "fx-win", values=tuple(float(i % 31) for i in range(3000)), interval=0.01)
    return root


SINGLE = ("fx-single",)
DOUBLE = ("fx-volt", "fx-amp")
WINDOWED = ("fx-win",)


def test_ar4a_no_external_references_in_any_document(
    single_set: Path, double_set: Path, windowed_set: Path
) -> None:
    documents = [
        _render(single_set, list(SINGLE)),
        _render(double_set, list(DOUBLE)),
        _render(windowed_set, list(WINDOWED), lo=2.0, hi=20.0),
    ]
    for index, document in enumerate(documents):
        lowered = document.lower()
        assert "src=" not in lowered, f"document {index} references an external source"
        assert "href=" not in lowered, f"document {index} links out"
        assert "url(" not in lowered, f"document {index} pulls a url()"
        assert "@import" not in lowered, f"document {index} imports a stylesheet"


def test_ar4b_printed_digests_equal_manifest_and_recomputed_primary(
    single_set: Path, double_set: Path
) -> None:
    for root, capture_ids in ((single_set, SINGLE), (double_set, DOUBLE)):
        document = _render(root, list(capture_ids))
        for capture_id in capture_ids:
            manifest = json.loads(
                (root / capture_id / "manifest.json").read_text(encoding="utf-8")
            )
            payload = (root / capture_id / f"{capture_id}.f64").read_bytes()
            recomputed = hashlib.sha256(payload).hexdigest()
            assert manifest["sha256"] == recomputed
            assert re.search(r"[0-9a-f]{64}", document)
            assert manifest["sha256"] in document, (
                f"{capture_id}: the manifest digest must be printed"
            )


def test_ar4b_hand_edited_manifest_digest_refuses_at_load(
    tmp_path: Path,
) -> None:
    """A manifest digest edited on disk after publication never renders:
    the loader's recomputed-digest check refuses before any report exists
    (the seam maps ``standalone_report_primary_mismatch``)."""
    write_capture(tmp_path, "fx-edited", values=(1.0, 2.0, 3.0))
    event = tmp_path / "fx-edited"
    manifest = json.loads((event / "manifest.json").read_text(encoding="utf-8"))
    manifest["sha256"] = "e" * 64
    (event / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    with pytest.raises(ValueError, match="standalone_report_primary_mismatch"):
        _render(tmp_path, ["fx-edited"])


def test_ar4c_every_stats_block_carries_label_definition_and_denominators(
    single_set: Path, double_set: Path, windowed_set: Path
) -> None:
    cases = [
        (single_set, SINGLE, None, None),
        (double_set, DOUBLE, None, None),
        (windowed_set, WINDOWED, 2.0, 20.0),
    ]
    for root, capture_ids, lo, hi in cases:
        document = _render(root, list(capture_ids), lo=lo, hi=hi)
        for capture_id in capture_ids:
            source = load_series_set(root, [capture_id])[0]
            stats, _ = scan_series(source, lo=lo, hi=hi)
            block = _stats_block(document, capture_id)
            assert block is not None, f"{capture_id}: no stats block in document"
            assert "host-computed" in block
            assert ANALYSIS_DEFINITION in block
            assert f"count {stats.count}" in block
            assert f"null_count {stats.null_count}" in block
            assert f"window [{_fmt(lo)}, {_fmt(hi)}]" in block


def test_ar4d_identical_inputs_render_byte_identical(
    single_set: Path, double_set: Path, windowed_set: Path
) -> None:
    for root, capture_ids, window in (
        (single_set, SINGLE, {}),
        (double_set, DOUBLE, {}),
        (windowed_set, WINDOWED, {"lo": 2.0, "hi": 20.0}),
    ):
        first = _render(root, list(capture_ids), **window)  # type: ignore[arg-type]
        second = _render(root, list(capture_ids), **window)  # type: ignore[arg-type]
        assert first == second, f"{capture_ids}: re-render of identical inputs differs"


def test_ar4e_metadata_escapes(
    tmp_path: Path,
) -> None:
    hostile = "<script>alert('x')</script>"
    write_capture(
        tmp_path,
        "fx-hostile",
        values=(1.0, 2.0),
        unit="V<script>",
        metadata={
            "operator": hostile,
            "notes": hostile + " {{7*7}}",
            "project": "{{secret}}",
            "device": {"id": hostile, "firmware": hostile},
            "plugin": {
                "package": "fx-{{plugin}}",
                "version": hostile,
                "descriptor_sha256": "a" * 64,
            },
        },
    )
    document = _render(tmp_path, ["fx-hostile"])
    assert "<script>" not in document
    assert "&lt;script&gt;" in document
    # No template engine interpolates here: braces are inert literal text.
    assert "{{7*7}}" in document
    assert "{{secret}}" in document
    assert "V<script>" not in document


def test_mode_line_names_standalone_and_simulated(tmp_path: Path) -> None:
    write_capture(tmp_path, "fx-plain", values=(1.0,))
    plain = _render(tmp_path, ["fx-plain"])
    assert "STANDALONE" in plain and "no gateway" in plain
    assert "SIMULATED" not in plain
    write_capture(
        tmp_path, "fx-mocked", values=(1.0,), metadata={"transport": "mock"}
    )
    marked = _render(tmp_path, ["fx-mocked"])
    assert "SIMULATED" in marked
    # Any one mock-transport source marks the whole report.
    mixed = _render(tmp_path, ["fx-plain", "fx-mocked"])
    assert "SIMULATED" in mixed


def test_sources_section_prints_plugin_identity_and_pin(
    single_set: Path,
) -> None:
    document = _render(single_set, list(SINGLE))
    assert "fx-plugin" in document and "0.3.1" in document
    assert "f" * 64 in document, "the descriptor digest must be printed"
    assert PIN_VERSION in document, "the ui-html pin version must be printed"
    assert SDK_VERSION in document


# --- the SVG structural arms (SRF-1: structural, not pixel parity) ----------------


def test_svg_carries_axes_legend_description_and_window(
    double_set: Path,
) -> None:
    document = _render(double_set, list(DOUBLE))
    assert 'role="img"' in document
    assert "<desc>" in document, "a textual description must accompany the plot"
    assert "t (s)" in document, "the x axis names its unit"
    assert "V" in document and "A" in document, "each y axis names its unit"
    # A visible legend distinguishing series by line form AND colour.
    assert "stroke-dasharray" in document, "line form must distinguish series"
    assert "fx-volt" in document and "fx-amp" in document
    # The stated time basis.
    assert "seconds from" in document and "own start" in document
    assert f"{REPORT_PLOT_COLUMNS}" in document, "the decimation budget is stated"


def test_windowed_render_shades_the_region(windowed_set: Path) -> None:
    document = _render(windowed_set, list(WINDOWED), lo=2.0, hi=20.0)
    assert 'data-bw-window="2…20' in document or "data-bw-window" in document
    assert "bw-report-window" in document


def test_more_than_two_distinct_units_refuse(tmp_path: Path) -> None:
    write_capture(tmp_path, "fx-u1", values=(1.0,), unit="V")
    write_capture(tmp_path, "fx-u2", values=(1.0,), unit="A")
    write_capture(tmp_path, "fx-u3", values=(1.0,), unit="W")
    with pytest.raises(ValueError, match="standalone_report_units_unsupported"):
        _render(tmp_path, ["fx-u1", "fx-u2", "fx-u3"])


def test_plot_points_ceiling_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The presentation ceiling binds the ZOOM path (the windowed points
    a zoom chart decimates). I4b.1's context/zoom split moved the check
    onto that path — a full-extent render draws no windowed chart (the
    context chart streams), and the export's own windowed_points limit
    still refuses an oversized window before any render."""
    write_capture(tmp_path, "fx-huge", values=(1.0,) * 1000)
    from benchweave_sdk_server import report as report_module

    monkeypatch.setattr(report_module, "REPORT_PLOT_SAMPLE_CEILING", 10)
    with pytest.raises(ValueError, match="standalone_report_window_too_large"):
        _render(tmp_path, ["fx-huge"], lo=0.0, hi=0.5)


# --- fold wave 1: plot scales and null rendering (rows 1 and 6) --------------------


def test_same_unit_series_share_a_union_scale(tmp_path: Path) -> None:
    """Row 1: the per-unit y scale is the UNION of that unit's series
    extents — a same-unit series with a different extent must not vanish
    outside the viewBox (the last-writer-wins defect). Every path
    coordinate lands inside the plot box."""
    write_capture(tmp_path, "fx-wide", values=tuple(float(i) for i in range(1000)))
    write_capture(tmp_path, "fx-narrow", values=(0.0, 0.5, 1.0))
    document = _render(tmp_path, ["fx-wide", "fx-narrow"])
    paths = re.findall(r'<path d="([^"]+)"', document)
    assert len(paths) == 2
    for path in paths:
        coordinates = re.findall(r"([0-9.]+),(-?[0-9.]+)", path)
        assert coordinates, "a drawn series must have path coordinates"
        for _, y_text in coordinates:
            y = float(y_text)
            assert 20 <= y <= 370, f"path y {y} outside the plot box"


def test_all_null_window_renders_no_nan_literals(tmp_path: Path) -> None:
    """Row 6: an all-NaN window (every sample null) renders an honest
    absence — no ``nan`` coordinate literals in the SVG (an invalid path
    silently undrawn), the document still renders, and the stats block
    carries the null denominator."""
    write_capture(tmp_path, "fx-allnull", values=(math.nan,) * 64)
    document = _render(tmp_path, ["fx-allnull"])
    assert not re.search(r",[+-]?nan\b", document, re.IGNORECASE), (
        "NaN coordinate literals must not reach the SVG"
    )
    assert 'role="img"' in document
    assert "null_count 64" in document
    assert "count 0" in document


# --- AR-6: genericity --------------------------------------------------------------


def test_ar6_same_code_over_single_and_double_sets(
    single_set: Path, double_set: Path
) -> None:
    single = _render(single_set, list(SINGLE))
    double = _render(double_set, list(DOUBLE))
    for document in (single, double):
        assert 'role="img"' in document
        assert ANALYSIS_DEFINITION in document
        assert "host-computed" in document


def test_ar6_module_census_no_adapter_or_plugin_coupling() -> None:
    """Both modules: imports confined to the stdlib + markupsafe + the
    package's own analysis/plots modules; no adapter or plugin name token
    anywhere in the module text."""
    import benchweave_sdk_server.analysis as analysis_module
    import benchweave_sdk_server.report as report_module

    allowed_roots = {
        "__future__",
        "ast",
        "collections",
        "dataclasses",
        "hashlib",
        "json",
        "math",
        "markupsafe",
        "pathlib",
        "re",
        "struct",
        "typing",
    }
    for module in (analysis_module, report_module):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        outside = imported - allowed_roots
        assert not outside, f"{module.__name__} imports {outside}"
        text = Path(module.__file__).read_text(encoding="utf-8").lower()
        for token in ("example_plugin", "ref-adapter", "adc", "example_device"):
            assert token not in text, f"{module.__name__} names {token}"


# --- helpers -----------------------------------------------------------------------


def _stats_block(document: str, capture_id: str) -> str | None:
    match = re.search(
        rf'<table class="bw-stats"[^>]*data-bw-capture="{re.escape(capture_id)}".*?</table>',
        document,
        re.DOTALL,
    )
    return match.group(0) if match is not None else None


def _fmt(value: float | None) -> str:
    from benchweave_sdk_server.report import format_number

    return format_number(value)


# --- fold wave 2 (lane B): non-finite statistics rendering (row B-F8) ---------------


def test_non_finite_statistics_are_never_rendered_as_absence(
    tmp_path: Path,
) -> None:
    """B-F8 partial: a window whose data is present but whose statistics
    compute to non-finite values (mean of +inf/-inf samples is NaN) must
    render as non-finite, NEVER as the honest-absence dash — the dash is
    reserved for count=0. The computation itself stays IEEE-conformant
    (the lane's disclosed non-change)."""
    write_capture(
        tmp_path, "fx-infmix", values=(1.0, float("inf"), float("-inf"), 4.0)
    )
    document = _render(tmp_path, ["fx-infmix"])
    block = _stats_block(document, "fx-infmix")
    assert block is not None
    assert "count 4" in block, "the samples ARE present"
    assert "n/a (non-finite)" in block, (
        "a computed non-finite statistic must say so, not borrow the "
        "absence mark"
    )
    assert not re.search(r",[+-]?nan\b", document, re.IGNORECASE), (
        "inf-extent series must not produce NaN path coordinates either"
    )


# --- I4b.1 AR-9: the context/zoom pair, marker glyphs, edge/assert blocks -----------


def _render_full(
    root: Path,
    capture_ids: list[str],
    *,
    markers: dict | None = None,
    assertions: tuple = (),
    **window: float | None,
) -> str:
    lo, hi = window.get("lo"), window.get("hi")
    return build_report(
        _entries(root, capture_ids, lo=lo, hi=hi),
        lo=lo,
        hi=hi,
        styles=STYLES,
        pin_version=PIN_VERSION,
        sdk_version=SDK_VERSION,
        markers=markers,
        assertions=assertions,
    )


def _chart_of(document: str, kind: str) -> str:
    match = re.search(
        rf'<svg[^>]*data-bw-chart="{kind}".*?</svg>', document, re.DOTALL
    )
    return match.group(0) if match is not None else ""


@pytest.fixture(scope="module")
def marked_set(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("report-marked")
    values = tuple(float(index % 23) for index in range(2000))
    write_capture(root, "fx-marked", values=values)
    return root


def test_ar9a_markers_render_as_glyphs_and_escaped_notes(
    marked_set: Path,
) -> None:
    """In-window markers draw as labelled glyphs on both charts; a
    hostile note renders escaped with inert braces (AR-4e extended); an
    out-of-window marker stays in the notes list and never reaches the
    zoom chart it cannot (the context chart spans the extent, so it CAN
    reach it there)."""
    hostile = "<script>alert('x')</script> {{7*7}}"
    markers = {
        "fx-marked": [
            {"label": "A", "t": 0.5, "note": "load applied"},
            {"label": "B", "t": 1.905, "note": hostile},
        ]
    }
    document = _render_full(marked_set, ["fx-marked"], markers=markers, lo=0.2, hi=1.0)
    context, zoom = _chart_of(document, "context"), _chart_of(document, "zoom")
    assert context and zoom
    # The window is shaded ON the context chart (the zoom chart IS the
    # window — shading it would shade the whole canvas).
    assert 'class="bw-window-shade"' in context
    assert 'class="bw-window-shade"' not in zoom
    assert 'data-bw-marker="A"' in context and 'data-bw-marker="A"' in zoom
    # B is inside the capture's extent (context) but OUTSIDE the window
    # (zoom): the zoom chart cannot reach it.
    assert 'data-bw-marker="B"' in context
    assert 'data-bw-marker="B"' not in zoom
    # The notes list carries every row, escaped, braces inert.
    assert "&lt;script&gt;" in document
    assert "<script>" not in document
    assert "{{7*7}}" in document
    assert "load applied" in document


def test_ar9b_edge_and_assertion_blocks_carry_labels_and_denominators(
    marked_set: Path,
) -> None:
    assertions = (
        AssertionResult(
            definition="benchweave-assert/1",
            capture_id="fx-marked",
            verdict="pass",
            min=0.0,
            max=22.0,
            actual_min=0.0,
            actual_max=22.0,
            reasons=(),
            lo=0.2,
            hi=1.0,
            count=800,
            null_count=0,
            uncertainty="unknown",
        ),
    )
    document = _render_full(
        marked_set, ["fx-marked"], assertions=assertions, lo=0.2, hi=1.0
    )
    edge_block = re.search(
        r'<table class="bw-edge".*?</table>', document, re.DOTALL
    )
    assert edge_block is not None
    edge_text = edge_block.group(0)
    assert "benchweave-edge/1" in edge_text
    assert "host-computed" in edge_text
    assert re.search(r"\bn \d+", edge_text)
    assert "head_n" in edge_text and "tail_n" in edge_text and "settle_pct" in edge_text
    assert re.search(r"window \[", edge_text)
    assert_block = re.search(
        r'<table class="bw-assertions".*?</table>', document, re.DOTALL
    )
    assert assert_block is not None
    assert "benchweave-assert/1" in assert_block.group(0)
    assert "host-computed" in assert_block.group(0)
    assert ">pass<" in assert_block.group(0)


def test_ar9c_zoom_renders_iff_the_window_is_a_proper_subset(
    marked_set: Path,
) -> None:
    """A full-extent export renders ONE chart (the context chart) and no
    zoom section; a proper-subset window renders the pair."""
    full = _render_full(marked_set, ["fx-marked"])
    assert full.count("<svg") == 1, "a full-extent export renders one chart"
    assert "bw-report-zoom" not in full
    assert 'data-bw-chart="context"' in full
    windowed = _render_full(marked_set, ["fx-marked"], lo=0.2, hi=1.0)
    assert windowed.count("<svg") == 2
    assert "bw-report-zoom" in windowed
    assert "Zoom 0.2 → 1" in windowed
    # A window that covers the whole extent (0 to t_max) is NOT a proper
    # subset: one chart, exactly as the full-extent export.
    t_max = 1999 * 0.001
    covering = _render_full(marked_set, ["fx-marked"], lo=0.0, hi=t_max)
    assert covering.count("<svg") == 1


def test_ar9d_both_charts_are_structurally_complete(marked_set: Path) -> None:
    document = _render_full(marked_set, ["fx-marked"], lo=0.2, hi=1.0)
    for kind in ("context", "zoom"):
        chart = _chart_of(document, kind)
        assert chart, kind
        assert 'role="img"' in chart
        assert "<desc>" in chart
        assert "t (s)" in chart
        assert 'class="bw-axis-label"' in chart
        assert "stroke-dasharray" in chart or "bw-legend-label" in chart
    assert "seconds from" in document and "own start" in document
    assert f"{REPORT_PLOT_COLUMNS}" in document


def test_ar9f_identical_inputs_with_markers_and_assertions_render_identical(
    marked_set: Path,
) -> None:
    markers = {"fx-marked": [{"label": "A", "t": 0.5, "note": "same"}]}
    assertions = (
        AssertionResult(
            definition="benchweave-assert/1",
            capture_id="fx-marked",
            verdict="fail",
            min=0.0,
            max=1.0,
            actual_min=0.0,
            actual_max=22.0,
            reasons=("above_max",),
            lo=None,
            hi=None,
            count=2000,
            null_count=0,
            uncertainty="unknown",
        ),
    )
    first = _render_full(
        marked_set, ["fx-marked"], markers=markers, assertions=assertions
    )
    second = _render_full(
        marked_set, ["fx-marked"], markers=markers, assertions=assertions
    )
    assert first == second
