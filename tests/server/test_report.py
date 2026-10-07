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
import re
import struct
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk_server.analysis import (
    ANALYSIS_DEFINITION,
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
    entries: list[ReportEntry] = []
    for capture_id in capture_ids:
        source = load_series_set(root, [capture_id])[0]
        stats, _ = scan_series(source, lo=lo, hi=hi)
        points = [
            (t, value)
            for t, value in series_samples(source)
            if (lo is None or t >= lo) and (hi is None or t <= hi)
        ]
        entries.append(ReportEntry(source=source, stats=stats, points=points))
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
    write_capture(tmp_path, "fx-huge", values=(1.0,) * 1000)
    from benchweave_sdk_server import report as report_module

    monkeypatch.setattr(report_module, "REPORT_PLOT_SAMPLE_CEILING", 10)
    with pytest.raises(ValueError, match="standalone_report_window_too_large"):
        _render(tmp_path, ["fx-huge"])


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
