"""The self-contained HTML report (issue #286, I4a; SW-53).

One document per export: the inlined renderer tokens (``tokens.css`` +
``themes.css`` — the exact pinned bytes ``assets.py`` serves, so the report
carries the host's styling with no external dependency), a server-side SVG
of the plot (no script can run in a report document — uPlot is canvas/JS,
so the report re-renders the SAME closed plot semantics SW-25 defines:
labelled axes with units, a legend distinguishing series by line form as
well as colour, a stated time basis, a textual description, and
min/max-per-column decimation through :func:`.plots.decimate_minmax` —
lazily imported, the same discipline ``_op_capture_series`` keeps).

Every processed-value block carries the ``host-computed`` label, the
definition id and its denominators (``count``, ``null_count``, the window)
— PRD §10's interim rule and G4's claim discipline: a report number never
means whatever the reader assumes.

The rendered bytes are CLOCK-FREE: ``generated_at`` lives in the export
sidecar, never in this document, so re-exporting identical inputs is
byte-identical and the report is re-derivable from its sources plus its
parameters. Every interpolated string is HTML-escaped; there is no
template engine, so content braces are inert literal text by construction.

The module is generic by construction (AR-6): no adapter or plugin names,
no imports beyond the stdlib, markupsafe and the package's own
analysis/plots modules.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from markupsafe import escape

from .analysis import (
    ANALYSIS_DEFINITION,
    ASSERT_DEFINITION,
    EDGE_DEFINITION,
    AssertionResult,
    EdgeTiming,
    RegionStats,
    SeriesSource,
)

#: The SVG canvas (the fork's own report geometry): wide enough for a
#: readable dual-axis plot inside a printed page.
_SVG_WIDTH = 900
_SVG_HEIGHT = 420
_PLOT_LEFT = 70
_PLOT_RIGHT = 830
_PLOT_TOP = 20
_PLOT_BOTTOM = 370

#: Decimation columns for the report plot: ``plots.PLOT_COLUMNS`` is the
#: live plot's budget; the report reuses the same number so both renderings
#: of the same window draw the same columns.
REPORT_PLOT_COLUMNS = 600

#: Presentation bound on the windowed samples materialised for the plot
#: path (a memory bound, not a commissioned envelope — A02 posture). The
#: statistics never materialise anything; only the SVG path does.
REPORT_PLOT_SAMPLE_CEILING = 2_000_000

#: Line forms distinguishing series in the legend and the paths (SW-25:
#: the legend distinguishes by line form as well as colour).
_LINE_FORMS = ("", "6 4", "2 4")

#: Series stroke colours (the design tokens' own fallback values).
_COLOUR_FALLBACKS = ("#4682b4", "#b47846", "#7ab46a")


class ReportRefusal(ValueError):
    """A report-shape refusal carrying its ``standalone_report_*`` prefix."""


@dataclass(frozen=True)
class ReportEntry:
    """One series' report inputs: its loaded source, its window
    statistics, the windowed (not yet decimated) plot points, its edge
    timing (I4b.1 AR-2 over the same windowed samples) and its
    full-extent context points (the streaming reducer's already-reduced
    output — never re-decimated here)."""

    source: SeriesSource
    stats: RegionStats
    points: list[tuple[float, float]]
    edge: EdgeTiming
    context_points: list[tuple[float, float]]


def format_number(value: float | None) -> str:
    """One deterministic, locale-free rendering for every number in the
    document. ``—`` is the HONEST ABSENCE (no data in the window) and is
    reserved for it; a COMPUTED non-finite value (B-F8: a mean over
    +inf/-inf samples is NaN) renders as ``n/a (non-finite)`` — data was
    present, the IEEE-conformant statistic just has no finite value, and
    borrowing the absence mark for that would say otherwise. ``inf``
    itself is a value and renders as such."""
    if value is None:
        return "—"
    if math.isnan(value):
        return "n/a (non-finite)"
    return format(value, ".12g")


def _text(value: Any) -> str:
    """Every interpolated string in the document goes through here."""
    return str(escape(str(value)))


def build_report(
    entries: Sequence[ReportEntry],
    *,
    lo: float | None,
    hi: float | None,
    styles: str,
    pin_version: str,
    sdk_version: str,
    markers: Mapping[str, Sequence[dict[str, Any]]] | None = None,
    assertions: Sequence[AssertionResult] = (),
) -> str:
    """Render the one self-contained HTML document (pure: no I/O, no
    clock; the caller owns asset bytes and versions).

    I4b.1's context/zoom pair (AR-9): the context chart covers every
    source's whole extent (the streaming reducer's output) with the
    analysis window shaded and the in-extent markers drawn; the windowed
    chart is the labelled zoom section and renders ONLY when the window
    is a proper subset of the sources' extent — a full-extent export
    renders one chart, never two identical charts.

    Refuses (``standalone_report_*``) when the set carries more than two
    distinct units (the SVG has a left and a right axis and no third) or
    when a window's plot points exceed the presentation ceiling.
    """
    if not entries:
        raise ReportRefusal("standalone_report_sources_empty: nothing to report")
    units: list[str] = []
    for entry in entries:
        if entry.source.unit not in units:
            units.append(entry.source.unit)
    if len(units) > 2:
        raise ReportRefusal(
            "standalone_report_units_unsupported: the report renders at most "
            f"two distinct units ({', '.join(units)}); split the export"
        )
    simulated = any(
        entry.source.metadata.get("transport") == "mock" for entry in entries
    )
    marker_rows = dict(markers or {})
    title_ids = ", ".join(entry.source.capture_id for entry in entries)
    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append(f"<title>BenchWeave analysis report — {_text(title_ids)}</title>")
    parts.append(f"<style>\n{styles}\n</style>")
    parts.append(_REPORT_STYLE)
    parts.append("</head>")
    parts.append("<body>")
    parts.append('<main class="bw-report">')
    parts.append("<h1>Analysis report</h1>")
    mode = "STANDALONE — no gateway"
    if simulated:
        mode += " · SIMULATED (a source capture records mock transport)"
    parts.append(f'<p class="bw-report-mode">{_text(mode)}</p>')
    parts.append(
        f"<p>Statistics definition <code>{ANALYSIS_DEFINITION}</code>; edge "
        f"timing <code>{EDGE_DEFINITION}</code>; assertions "
        f"<code>{ASSERT_DEFINITION}</code>. "
        "Processed values are host-computed (uncertainty: unknown); every "
        "block states its denominators.</p>"
    )
    # The union extent end drives the proper-subset gate: a window that
    # covers [0, t_max] (or is absent entirely) renders the context chart
    # alone. A-F2: t_max comes from the SOURCE GRID ((sample_count - 1) x
    # sample_interval_s) — the decimated context points can end a column
    # short of the true end (their last pair orders by x), and a window
    # trimming only that tail gap is a proper subset.
    t_max = max(
        (entry.source.sample_count - 1) * entry.source.sample_interval_s
        for entry in entries
    )
    proper_subset = (lo is not None and lo > 0.0) or (
        hi is not None and hi < t_max
    )
    parts.append('<section class="bw-report-context">')
    parts.append("<h2>Context (full extent)</h2>")
    parts.append(
        _render_chart(
            _chart_series(entries, lambda entry: entry.context_points),
            units=units,
            x_max=t_max if t_max > 0 else 1.0,
            shade=(lo, hi),
            markers=marker_rows,
            chart_kind="context",
        )
    )
    parts.append(
        "<p>Time basis: seconds from each capture's own start "
        "(sample index × sample_interval_s). The context chart spans every "
        f"source's full extent, decimated to {REPORT_PLOT_COLUMNS} min/max "
        "columns by the streaming reducer (edge-preserving); the analysis "
        "window is shaded and in-extent markers are drawn.</p>"
    )
    parts.append("</section>")
    if proper_subset:
        zoom_series = _windowed_series_checked(entries)
        # B-F1: the zoom chart's x domain IS the window — [lo, hi] mapped
        # across the plot box (a [0, hi] domain squeezed the window into
        # the right edge and wasted the axis).
        zoom_lo = lo if lo is not None else 0.0
        zoom_hi = hi if hi is not None else t_max
        parts.append('<section class="bw-report-zoom">')
        parts.append(
            "<h2>Zoom "
            f"{format_number(zoom_lo)} → "
            f"{format_number(zoom_hi)}</h2>"
        )
        parts.append(
            _render_chart(
                zoom_series,
                units=units,
                x_lo=zoom_lo,
                x_max=zoom_hi if zoom_hi > zoom_lo else zoom_lo + 1.0,
                shade=None,
                markers=marker_rows,
                chart_kind="zoom",
                marker_span=(zoom_lo, zoom_hi),
            )
        )
        parts.append(
            "<p>The zoom section covers the inclusive analysis window "
            f"[{format_number(lo)}, {format_number(hi)}] — the context "
            "chart's shaded region at full resolution over that span.</p>"
        )
        parts.append("</section>")
    if lo is not None or hi is not None:
        parts.append(
            '<p class="bw-report-window">Window '
            f"[{format_number(lo)}, {format_number(hi)}] (inclusive).</p>"
        )
    parts.append('<section class="bw-report-stats">')
    parts.append("<h2>Window statistics</h2>")
    for entry in entries:
        parts.append(_stats_table(entry))
    parts.append("</section>")
    parts.append('<section class="bw-report-edge">')
    parts.append("<h2>Edge timing</h2>")
    for entry in entries:
        parts.append(_edge_table(entry))
    parts.append("</section>")
    if assertions:
        parts.append('<section class="bw-report-assertions">')
        parts.append("<h2>Assertions</h2>")
        parts.append(_assertions_table(assertions))
        parts.append("</section>")
    if any(marker_rows.get(entry.source.capture_id) for entry in entries):
        parts.append('<section class="bw-report-markers">')
        parts.append("<h2>Markers</h2>")
        parts.append(_markers_table(entries, marker_rows))
        parts.append("</section>")
    parts.append('<section class="bw-report-sources">')
    parts.append("<h2>Sources</h2>")
    for entry in entries:
        parts.append(_source_block(entry))
    parts.append("</section>")
    parts.append(
        '<footer class="bw-report-footer">benchweave-sdk '
        f"{_text(sdk_version)} · renderer pin benchweave-ui-html "
        f"{_text(pin_version)} · this document is re-derivable from its "
        "sources and parameters (no generated_at is embedded; the export "
        "sidecar records it).</footer>"
    )
    parts.append("</main>")
    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts) + "\n"


def _chart_series(
    entries: Sequence[ReportEntry], points_of: Any
) -> list[dict[str, Any]]:
    """The chart's series list: one row per entry carrying its (already
    chosen) points, line form and colour."""
    return [
        {
            "capture_id": entry.source.capture_id,
            "unit": entry.source.unit,
            "points": list(points_of(entry)),
            "form": _LINE_FORMS[index % len(_LINE_FORMS)],
            "colour": _COLOUR_FALLBACKS[index % len(_COLOUR_FALLBACKS)],
        }
        for index, entry in enumerate(entries)
    ]


def _windowed_series_checked(
    entries: Sequence[ReportEntry],
) -> list[dict[str, Any]]:
    """The zoom chart's series: the windowed raw points decimated to the
    report budget, refusing above the presentation ceiling."""
    from .plots import decimate_minmax

    series: list[dict[str, Any]] = []
    for entry in entries:
        if len(entry.points) > REPORT_PLOT_SAMPLE_CEILING:
            raise ReportRefusal(
                "standalone_report_window_too_large: "
                f"{entry.source.capture_id} window holds {len(entry.points)} "
                f"samples for plotting; the report plot ceiling is "
                f"{REPORT_PLOT_SAMPLE_CEILING} (narrow the window)"
            )
    series = _chart_series(
        entries, lambda entry: decimate_minmax(entry.points, columns=REPORT_PLOT_COLUMNS)
    )
    return series


def _stats_table(entry: ReportEntry) -> str:
    """One series' statistics block: the values, their definition, and the
    denominators on the block itself (AR-4c — the label travels with the
    numbers, not with the page)."""
    stats = entry.stats
    unit = _text(entry.source.unit)
    caption = (
        f"{_text(entry.source.capture_id)} ({unit}) — host-computed · "
        f"definition {ANALYSIS_DEFINITION} · count {stats.count} · "
        f"null_count {stats.null_count} · "
        f"window [{format_number(stats.lo)}, {format_number(stats.hi)}]"
    )
    rows = (
        ("count", f"{stats.count}"),
        ("null_count", f"{stats.null_count}"),
        ("min", format_number(stats.min)),
        ("mean", format_number(stats.mean)),
        ("max", format_number(stats.max)),
        ("rms", format_number(stats.rms)),
        ("peak-to-peak", format_number(stats.pp)),
    )
    body = "".join(
        f"<tr><th>{name}</th><td>{value}</td></tr>" for name, value in rows
    )
    return (
        f'<table class="bw-stats" data-bw-capture="{_text(entry.source.capture_id)}">\n'
        f"<caption>{caption}</caption>\n<tbody>\n{body}\n</tbody>\n</table>"
    )


def _source_block(entry: ReportEntry) -> str:
    """One source capture's provenance: the manifest digest printed in
    full (SW-53), the plugin identity, the annotation fields."""
    source = entry.source
    manifest = source.manifest
    metadata = source.metadata
    device = metadata.get("device") or {}
    plugin = metadata.get("plugin") or {}
    rows = (
        ("capture", _text(source.capture_id)),
        ("unit", _text(source.unit)),
        ("sample_count", _text(manifest.get("sample_count"))),
        ("sample_interval_s", format_number(source.sample_interval_s)),
        ("byte_length", _text(manifest.get("byte_length"))),
        ("started_at", _text(manifest.get("started_at"))),
        ("manifest sha256", _text(source.manifest_sha256)),
        ("device", _text(device.get("id"))),
        ("firmware", _text(device.get("firmware"))),
        ("plugin", _text(plugin.get("package"))),
        ("plugin version", _text(plugin.get("version"))),
        ("descriptor sha256", _text(plugin.get("descriptor_sha256"))),
        ("operator", _text(metadata.get("operator"))),
        ("project", _text(metadata.get("project"))),
        ("notes", _text(metadata.get("notes"))),
    )
    body = "".join(
        f"<tr><th>{name}</th><td>{value}</td></tr>" for name, value in rows
    )
    return (
        f'<table class="bw-source" data-bw-capture="{_text(source.capture_id)}">\n'
        f"<caption>{_text(source.capture_id)}</caption>\n<tbody>\n{body}\n"
        "</tbody>\n</table>"
    )


def _render_chart(
    series: list[dict[str, Any]],
    *,
    units: list[str],
    x_max: float,
    shade: tuple[float | None, float | None] | None,
    markers: Mapping[str, Sequence[dict[str, Any]]],
    chart_kind: str,
    marker_span: tuple[float, float] | None = None,
    x_lo: float = 0.0,
) -> str:
    """One server-side chart: paths, per-unit axes, the optional window
    shading and marker glyphs, and the legend. Structural — labelled and
    described, never pixel-compared (SRF-1). The x domain is
    ``[x_lo, x_max]`` (B-F1: the zoom chart maps its WINDOW across the
    box, never [0, hi]). ``marker_span`` bounds which markers a chart
    draws (the context chart draws its in-extent markers; the zoom chart
    draws the in-window ones — a marker a chart cannot reach never
    renders on it)."""
    plot_width = _PLOT_RIGHT - _PLOT_LEFT
    plot_height = _PLOT_BOTTOM - _PLOT_TOP
    x_span = x_max - x_lo if x_max > x_lo else 1.0

    def x_of(t: float) -> float:
        return _PLOT_LEFT + ((t - x_lo) / x_span) * plot_width

    # Per-unit y scales over the UNION of that unit's series extents (fold
    # row 1: last-writer-wins let a same-unit series with a different
    # extent escape the viewBox — every series of a unit scales against
    # one shared axis). Null (NaN) samples are not observations of a
    # numeric axis and never enter the extent (fold row 6: an all-null
    # series must not produce a NaN scale).
    extents: dict[str, tuple[float, float]] = {}
    for series_ in series:
        values = [
            value
            for _, value in series_["points"]
            if math.isfinite(value)
        ]
        if not values:
            continue
        low, high = min(values), max(values)
        if series_["unit"] in extents:
            previous_low, previous_high = extents[series_["unit"]]
            low = min(low, previous_low)
            high = max(high, previous_high)
        extents[series_["unit"]] = (low, high)
    scales: dict[str, tuple[float, float]] = {}
    for unit, (low, high) in extents.items():
        if low == high:
            low, high = low - 1.0, high + 1.0
        margin = (high - low) * 0.05
        scales[unit] = (low - margin, high + margin)

    def y_of(unit: str, value: float) -> float:
        low, high = scales.get(unit, (0.0, 1.0))
        return _PLOT_BOTTOM - ((value - low) / (high - low)) * plot_height

    parts: list[str] = []
    aria = (
        f"Analysis {chart_kind} plot: "
        + ", ".join(f"{s['capture_id']} in {s['unit']}" for s in series)
    )
    if shade is not None and (shade[0] is not None or shade[1] is not None):
        aria += f"; window [{format_number(shade[0])}, {format_number(shade[1])}]"
    parts.append(
        f'<svg viewBox="0 0 {_SVG_WIDTH} {_SVG_HEIGHT}" role="img" '
        f'aria-label="{_text(aria)}" class="bw-report-svg" '
        f'data-bw-chart="{_text(chart_kind)}">'
    )
    parts.append(f"<title>{_text(aria)}</title>")
    parts.append(
        f"<desc>Server-rendered min/max-per-column {chart_kind} chart of "
        "the series; axis labels name their units and the legend "
        "distinguishes series by line form and colour.</desc>"
    )
    parts.append(
        f'<rect x="{_PLOT_LEFT}" y="{_PLOT_TOP}" width="{plot_width}" '
        f'height="{plot_height}" fill="none" stroke="#888888"/>'
    )
    if shade is not None:
        shade_lo, shade_hi = shade
        if shade_lo is not None or shade_hi is not None:
            shade_left = x_of(shade_lo if shade_lo is not None else 0.0)
            shade_right = x_of(shade_hi if shade_hi is not None else x_max)
            parts.append(
                f'<rect class="bw-window-shade" data-bw-window='
                f'"{format_number(shade_lo)}…{format_number(shade_hi)}" '
                f'x="{shade_left:.2f}" y="{_PLOT_TOP}" '
                f'width="{max(0.0, shade_right - shade_left):.2f}" '
                f'height="{plot_height}" fill="#4682b4" opacity="0.08"/>'
            )
    for series_ in series:
        # Non-finite samples are gaps, never coordinates (fold row 6: a
        # NaN coordinate would render an invalid, silently-undrawn path;
        # B-F8: an inf sample is undrawable on a finite axis too — the
        # statistics still count it, the plot skips it).
        coordinates = [
            (t, value)
            for t, value in series_["points"]
            if math.isfinite(value)
        ]
        if not coordinates:
            continue
        path = " ".join(
            f"{'M' if index == 0 else 'L'}{x_of(t):.2f},"
            f"{y_of(series_['unit'], value):.2f}"
            for index, (t, value) in enumerate(coordinates)
        )
        dash = (
            f' stroke-dasharray="{series_["form"]}"' if series_["form"] else ""
        )
        parts.append(
            f'<path d="{path}" fill="none" stroke="{series_["colour"]}" '
            f'stroke-width="1.5"{dash} data-bw-capture='
            f'"{_text(series_["capture_id"])}"/>'
        )
    # Marker glyphs: a labelled vertical line per in-span marker row of
    # the chart's captures (AR-9a — out-of-span markers stay in the
    # notes list, never on a chart they cannot reach).
    for series_ in series:
        for marker in markers.get(series_["capture_id"], ()):
            t = float(marker.get("t", 0.0))
            if marker_span is not None and not (
                marker_span[0] <= t <= marker_span[1]
            ):
                continue
            x = x_of(t)
            parts.append(
                f'<line class="bw-marker" data-bw-marker='
                f'"{_text(marker.get("label", ""))}" data-bw-capture='
                f'"{_text(series_["capture_id"])}" x1="{x:.2f}" '
                f'y1="{_PLOT_TOP}" x2="{x:.2f}" y2="{_PLOT_BOTTOM}" '
                f'stroke="#8b3a3a" stroke-dasharray="3 3"/>'
            )
            parts.append(
                f'<text x="{x + 3:.2f}" y="{_PLOT_TOP + 12:.2f}" '
                f'class="bw-marker-label">'
                f"{_text(marker.get('label', ''))}</text>"
            )
    # The x axis: label + five ticks spanning the x domain.
    for step in range(6):
        t = x_lo + x_span * step / 5
        parts.append(
            f'<line x1="{x_of(t):.2f}" y1="{_PLOT_BOTTOM}" '
            f'x2="{x_of(t):.2f}" y2="{_PLOT_BOTTOM + 4}" stroke="#888888"/>'
        )
        parts.append(
            f'<text x="{x_of(t):.2f}" y="{_PLOT_BOTTOM + 18}" '
            f'text-anchor="middle" class="bw-axis-tick">{format_number(t)}</text>'
        )
    parts.append(
        f'<text x="{(_PLOT_LEFT + _PLOT_RIGHT) / 2:.0f}" y="{_SVG_HEIGHT - 5}" '
        f'text-anchor="middle" class="bw-axis-label">t (s)</text>'
    )
    # One labelled y axis per unit: the first on the left, the second on
    # the right.
    for position, unit in enumerate(units):
        low, high = scales.get(unit, (0.0, 1.0))
        anchor_x = _PLOT_LEFT - 55 if position == 0 else _PLOT_RIGHT + 55
        line_x = _PLOT_LEFT if position == 0 else _PLOT_RIGHT
        parts.append(
            f'<line x1="{line_x}" y1="{_PLOT_TOP}" x2="{line_x}" '
            f'y2="{_PLOT_BOTTOM}" stroke="#888888"/>'
        )
        for step in range(5):
            value = low + (high - low) * step / 4
            parts.append(
                f'<text x="{anchor_x}" y="{y_of(unit, value) + 4:.2f}" '
                f'text-anchor="middle" class="bw-axis-tick">'
                f"{format_number(value)}</text>"
            )
        parts.append(
            f'<text x="{anchor_x}" y="{_PLOT_TOP - 6}" text-anchor="middle" '
            f'class="bw-axis-label">{_text(unit)}</text>'
        )
    # The legend: line form AND colour per series.
    legend_y = _SVG_HEIGHT - 24
    legend_x = _PLOT_LEFT
    for series_ in series:
        dash = (
            f' stroke-dasharray="{series_["form"]}"' if series_["form"] else ""
        )
        parts.append(
            f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x + 28}" '
            f'y2="{legend_y}" stroke="{series_["colour"]}" '
            f'stroke-width="2"{dash}/>'
        )
        parts.append(
            f'<text x="{legend_x + 34}" y="{legend_y + 4}" '
            f'class="bw-legend-label">{_text(series_["capture_id"])} '
            f"({_text(series_['unit'])})</text>"
        )
        legend_x += 34 + 14 * (len(series_["capture_id"]) + len(series_["unit"]) + 3)
    parts.append("</svg>")
    return "\n".join(parts)


def _edge_table(entry: ReportEntry) -> str:
    """One series' edge-timing block: the values, their definition, and
    the denominators on the block (SRF-4 — the label travels with the
    numbers)."""
    edge = entry.edge
    caption = (
        f"{_text(entry.source.capture_id)} — host-computed · "
        f"definition {EDGE_DEFINITION} · n {edge.n} · head_n {edge.head_n} · "
        f"tail_n {edge.tail_n} · settle_pct {format_number(edge.settle_pct)} · "
        f"window [{format_number(edge.lo)}, {format_number(edge.hi)}]"
    )
    rising = "—" if edge.rising is None else ("rising" if edge.rising else "falling")
    rows = (
        ("detected", "yes" if edge.detected else "no"),
        ("direction", rising),
        ("baseline", format_number(edge.baseline)),
        ("final", format_number(edge.final)),
        ("step", format_number(edge.step)),
        ("t10 (s)", format_number(edge.t10)),
        ("t90 (s)", format_number(edge.t90)),
        ("rise_time (s)", format_number(edge.rise_time)),
        ("settle_time (s)", format_number(edge.settle_time)),
    )
    body = "".join(
        f"<tr><th>{name}</th><td>{value}</td></tr>" for name, value in rows
    )
    return (
        f'<table class="bw-edge" data-bw-capture="{_text(entry.source.capture_id)}">\n'
        f"<caption>{caption}</caption>\n<tbody>\n{body}\n</tbody>\n</table>"
    )


def _assertions_table(assertions: Sequence[AssertionResult]) -> str:
    """The assertions block: one row per verdict with its bounds, the
    measured actuals, the machine-readable reasons and the window
    denominators the verdict was computed over (SRF-4)."""
    caption = (
        f"host-computed · definition {ASSERT_DEFINITION} · "
        f"{len(assertions)} assertion(s)"
    )
    body = "".join(
        "<tr>"
        f"<td>{_text(row.capture_id)}</td>"
        f"<td>{_text(row.verdict)}</td>"
        f"<td>{format_number(row.min)}</td>"
        f"<td>{format_number(row.max)}</td>"
        f"<td>{format_number(row.actual_min)}</td>"
        f"<td>{format_number(row.actual_max)}</td>"
        f"<td>{_text(', '.join(row.reasons))}</td>"
        f"<td>{row.count}</td>"
        f"<td>{row.null_count}</td>"
        f"<td>[{format_number(row.lo)}, {format_number(row.hi)}]</td>"
        "</tr>\n"
        for row in assertions
    )
    head = (
        "<tr>"
        "<th>capture</th><th>verdict</th><th>min</th><th>max</th>"
        "<th>actual min</th><th>actual max</th><th>reasons</th>"
        "<th>count</th><th>null_count</th><th>window</th>"
        "</tr>\n"
    )
    return (
        '<table class="bw-assertions">\n'
        f"<caption>{caption}</caption>\n"
        f"<thead>\n{head}</thead>\n<tbody>\n{body}</tbody>\n</table>"
    )


def _markers_table(
    entries: Sequence[ReportEntry], markers: Mapping[str, Sequence[dict[str, Any]]]
) -> str:
    """The markers block: EVERY stored row for the report's captures —
    out-of-window markers appear here even though no chart they cannot
    reach draws them (AR-9a). Notes are operator free text and render
    escaped (AR-4e extended to notes)."""
    body = ""
    for entry in entries:
        for marker in markers.get(entry.source.capture_id, ()):
            t = float(marker.get("t", 0.0))
            inside = "yes" if (
                (entry.edge.lo is None or t >= entry.edge.lo)
                and (entry.edge.hi is None or t <= entry.edge.hi)
            ) else "no"
            body += (
                "<tr>"
                f"<td>{_text(marker.get('label', ''))}</td>"
                f"<td>{_text(entry.source.capture_id)}</td>"
                f"<td>{format_number(t)}</td>"
                f"<td>{_text(marker.get('note', ''))}</td>"
                f"<td>{inside}</td>"
                "</tr>\n"
            )
    head = (
        "<tr><th>label</th><th>capture</th><th>t (s)</th>"
        "<th>note</th><th>in window</th></tr>\n"
    )
    return (
        '<table class="bw-markers">\n'
        f"<thead>\n{head}</thead>\n<tbody>\n{body}</tbody>\n</table>"
    )


#: The report's own structural styling — appended after the inlined tokens
#: so token classes apply and the report layout needs no external sheet.
_REPORT_STYLE = """<style>
.bw-report { max-width: 60rem; margin: 0 auto; padding: 1rem; }
.bw-report table { border-collapse: collapse; margin: 0.75rem 0; }
.bw-report caption { text-align: left; font-weight: 600; padding: 0.25rem 0; }
.bw-report th, .bw-report td { border: 1px solid #888888; padding: 0.2rem 0.5rem;
  text-align: left; }
.bw-report svg { width: 100%; height: auto; }
.bw-axis-tick { font-size: 11px; fill: currentColor; }
.bw-axis-label { font-size: 12px; fill: currentColor; }
.bw-legend-label { font-size: 12px; fill: currentColor; }
</style>"""
