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
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from markupsafe import escape

from .analysis import ANALYSIS_DEFINITION, RegionStats, SeriesSource

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
    """One series' report inputs: its loaded source, its window statistics
    and the windowed (not yet decimated) plot points."""

    source: SeriesSource
    stats: RegionStats
    points: list[tuple[float, float]]


def format_number(value: float | None) -> str:
    """One deterministic, locale-free rendering for every number in the
    document (``—`` for the honest absence, never a bare ``None``)."""
    if value is None:
        return "—"
    if math.isnan(value):
        return "—"
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
) -> str:
    """Render the one self-contained HTML document (pure: no I/O, no
    clock; the caller owns asset bytes and versions).

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
        f"<p>Statistics definition <code>{ANALYSIS_DEFINITION}</code>. "
        "Processed values are host-computed (uncertainty: unknown); every "
        "block states its denominators.</p>"
    )
    parts.append('<section class="bw-report-plot">')
    parts.append("<h2>Plot</h2>")
    parts.append(_svg_plot(entries, lo=lo, hi=hi, units=units))
    parts.append(
        "<p>Time basis: seconds from each capture's own start "
        "(sample index × sample_interval_s). Plot decimated to at most "
        f"{REPORT_PLOT_COLUMNS} min/max columns (edge-preserving); "
        "statistics are computed over every raw sample in the window.</p>"
    )
    if lo is not None or hi is not None:
        parts.append(
            '<p class="bw-report-window">Window '
            f"[{format_number(lo)}, {format_number(hi)}] (inclusive).</p>"
        )
    parts.append("</section>")
    parts.append('<section class="bw-report-stats">')
    parts.append("<h2>Window statistics</h2>")
    for entry in entries:
        parts.append(_stats_table(entry))
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


def _svg_plot(
    entries: Sequence[ReportEntry],
    *,
    lo: float | None,
    hi: float | None,
    units: list[str],
) -> str:
    """The server-side plot: decimated paths, per-unit axes, the window
    shading, and the legend. Structural — labelled and described, never
    pixel-compared (SRF-1)."""
    from .plots import decimate_minmax

    series: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if len(entry.points) > REPORT_PLOT_SAMPLE_CEILING:
            raise ReportRefusal(
                "standalone_report_window_too_large: "
                f"{entry.source.capture_id} window holds {len(entry.points)} "
                f"samples for plotting; the report plot ceiling is "
                f"{REPORT_PLOT_SAMPLE_CEILING} (narrow the window)"
            )
        reduced = decimate_minmax(entry.points, columns=REPORT_PLOT_COLUMNS)
        # Line form and colour distinguish SERIES (the legend's rule); the
        # unit only selects which y axis a path scales against.
        series.append(
            {
                "capture_id": entry.source.capture_id,
                "unit": entry.source.unit,
                "points": reduced,
                "form": _LINE_FORMS[index % len(_LINE_FORMS)],
                "colour": _COLOUR_FALLBACKS[index % len(_COLOUR_FALLBACKS)],
            }
        )
    x_max = max(
        (series_["points"][-1][0] for series_ in series if series_["points"]),
        default=1.0,
    )
    x_max = x_max if x_max > 0 else 1.0
    plot_width = _PLOT_RIGHT - _PLOT_LEFT
    plot_height = _PLOT_BOTTOM - _PLOT_TOP

    def x_of(t: float) -> float:
        return _PLOT_LEFT + (t / x_max) * plot_width

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
            if not math.isnan(value)
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
        "Analysis plot: "
        + ", ".join(f"{s['capture_id']} in {s['unit']}" for s in series)
        + (
            f"; window [{format_number(lo)}, {format_number(hi)}]"
            if lo is not None or hi is not None
            else ""
        )
    )
    parts.append(
        f'<svg viewBox="0 0 {_SVG_WIDTH} {_SVG_HEIGHT}" role="img" '
        f'aria-label="{_text(aria)}" class="bw-report-svg">'
    )
    parts.append(f"<title>{_text(aria)}</title>")
    parts.append(
        "<desc>Server-rendered min/max-per-column plot of the windowed "
        "series; axis labels name their units and the legend distinguishes "
        "series by line form and colour.</desc>"
    )
    parts.append(
        f'<rect x="{_PLOT_LEFT}" y="{_PLOT_TOP}" width="{plot_width}" '
        f'height="{plot_height}" fill="none" stroke="#888888"/>'
    )
    if lo is not None or hi is not None:
        shade_left = x_of(lo if lo is not None else 0.0)
        shade_right = x_of(hi if hi is not None else x_max)
        parts.append(
            f'<rect class="bw-window-shade" data-bw-window='
            f'"{format_number(lo)}…{format_number(hi)}" x="{shade_left:.2f}" '
            f'y="{_PLOT_TOP}" width="{max(0.0, shade_right - shade_left):.2f}" '
            f'height="{plot_height}" fill="#4682b4" opacity="0.08"/>'
        )
    for series_ in series:
        # Null samples are gaps, never coordinates (fold row 6: a NaN
        # coordinate would render an invalid, silently-undrawn path).
        coordinates = [
            (t, value)
            for t, value in series_["points"]
            if not math.isnan(value)
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
    # The x axis: label + five ticks.
    for step in range(6):
        t = x_max * step / 5
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
