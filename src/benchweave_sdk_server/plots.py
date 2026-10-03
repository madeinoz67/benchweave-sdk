"""The plot wrapper (I2a §3.3): host-side composition and decimation.

Every declared plot composes through the package's own exported plot
machinery (:func:`benchweave_ui_html.plot.compose_plot` over the projected
``PlotView``) — the host writes no second copy of the slot/axis/hint
vocabulary. The samples are the session's bounded observation ring
(host-observed values, nothing fabricated), decimated min/max-per-column
HOST-SIDE per #310's ruling; the acquisition disclosure therefore derives
from the decimation output, never caller-supplied (G1b fold M1's rule).
The decimated columns ride in a ``application/json`` block keyed to the
figure — data, CSP-safe — and the vendored uPlot hydrator draws them.

No plugin-supplied plot options enter anywhere: the wrapper is closed
(the manifest's channel hints are the only plugin input, and they flow
through the package's own hint resolution).
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from benchweave_ui_html.plot import ChannelHint, TraceSpec, compose_plot

#: Per-parameter sample cap — a presentation bound (the ring is host state
#: for the live page, not a capture store; retained observations belong to
#: the gateway). Deliberately not a commissioned envelope (A02 posture:
#: this bounds memory, not safety).
RING_CAP = 4096

#: The decimation column budget: the host decimates to a bounded column
#: count before the payload leaves the server (#310's ruling — host-side
#: min/max decimation regardless of renderer). The client draws the
#: columns at its own resolution.
PLOT_COLUMNS = 600

#: The x axis is the acquisition clock (the receipt-time variable the
#: scaffold's own example plot declares, in seconds).
X_UNIT = "s"


@dataclass(frozen=True)
class ObservationRing:
    """A bounded per-parameter ring of ``(monotonic_ms, value)`` samples.

    Host-observed values only — every entry comes from a successful
    ``parameter_read``. Only finite numeric values feed a numeric plot;
    absent (``None``), boolean and string values are not observations of
    a numeric axis and are not recorded.
    """

    cap: int = RING_CAP
    _samples: dict[str, deque[tuple[float, float]]] = field(
        init=False, default_factory=dict, repr=False
    )

    def __post_init__(self) -> None:
        if self.cap <= 0:
            raise ValueError("the observation ring cap must be positive")

    def record(self, parameter: str, monotonic_ms: float, value: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        if not math.isfinite(float(value)) or not math.isfinite(monotonic_ms):
            return
        ring = self._samples.setdefault(parameter, deque(maxlen=self.cap))
        ring.append((float(monotonic_ms), float(value)))

    def snapshot(self, parameter: str) -> list[tuple[float, float]]:
        """The parameter's samples in acquisition order (oldest first)."""
        return list(self._samples.get(parameter, ()))


def decimate_minmax(
    points: list[tuple[float, float]], *, columns: int
) -> list[tuple[float, float]]:
    """Min/max per column, x-ordered: every drawn column carries its own
    minimum and maximum, so an interior spike survives any reduction
    (#310's ruling — the edge-preserving shape for time series).

    At or below the column budget this is the identity (no reduction, no
    disclosure owed). The output count is bounded by ``2 * columns``.
    """
    if columns < 1:
        raise ValueError("the decimation column budget must be positive")
    if len(points) <= columns:
        return list(points)
    first_x = points[0][0]
    last_x = points[-1][0]
    if last_x <= first_x:
        return [min(points, key=lambda point: point[1]), max(points, key=lambda p: p[1])]
    width = (last_x - first_x) / columns
    reduced: list[tuple[float, float]] = []
    column: list[tuple[float, float]] = []
    current = 0

    def flush() -> None:
        if not column:
            return
        low = min(column, key=lambda point: point[1])
        high = max(column, key=lambda point: point[1])
        pair = [low, high] if low[0] <= high[0] else [high, low]
        reduced.extend(pair)

    for point in points:
        index = min(columns - 1, int((point[0] - first_x) / width))
        if index != current:
            flush()
            column = []
            current = index
        column.append(point)
    flush()
    return reduced


@dataclass(frozen=True)
class PlotRender:
    """One composed plot's server-side output."""

    html: str
    json: str


def compose_page_plot(view: Any, ring: ObservationRing) -> PlotRender:
    """Compose one ``PlotView`` into the rendered figure and its payload.

    The figure is the package's own ``render_plot(compose_plot(...))``
    output; the payload is the decimated columns per channel, keyed to the
    figure's wrapper. Digital lanes render the skeleton with the no-data
    disclosure — live lane data is I3's (D-I2b) and the wrapper says so
    rather than drawing an empty capture.
    """
    from benchweave_ui_html.partials import render_plot

    hints = {
        channel.variable_id: ChannelHint(
            color_role=channel.color_role, visible=channel.visible
        )
        for channel in view.channels
        if channel.color_role is not None or channel.visible is not None
    }
    if view.kind == "digital_lanes":
        skeleton = (
            f'<figure class="bw-plot" role="img" aria-label="{view.title}" data-bw-lanes '
            f'data-bw-plot-title="{view.title}">\n'
            f'  <div class="bw-plot__canvas" data-bw-axes="{view.x.unit or X_UNIT}" '
            f'data-bw-plot-title="{view.title}"></div>\n'
            '  <p class="bw-plot__no-data" role="status">No lane data — captures begin at I3; '
            "this figure renders the declared lane structure only.</p>\n"
            "</figure>"
        )
        payload: dict[str, Any] = {"channels": [], "x_unit": view.x.unit or X_UNIT}
        return PlotRender(html=skeleton, json=json.dumps(payload))

    samples = ring.snapshot(view.binding_id)
    reduced = decimate_minmax(samples, columns=PLOT_COLUMNS)
    if samples:
        origin = samples[0][0]
        x_values = [(x - origin) / 1000.0 for x, _ in reduced]
        y_values = [value for _, value in reduced]
    else:
        x_values, y_values = [], []
    channels_payload = [
        {"id": view.channels[0].variable_id if view.channels else "value",
         "x": x_values, "y": y_values}
    ]
    traces = tuple(
        TraceSpec(
            channel_id=channel.variable_id,
            unit=str(channel.unit or ""),
            samples=tuple(y_values) if index == 0 else (),
            acquired=len(samples) if index == 0 else None,
        )
        for index, channel in enumerate(view.channels)
    )
    composed = compose_plot(
        title=view.title,
        description=(
            f"{view.title}: {view.kind} over {view.binding_id}; "
            f"{len(view.channels)} channel(s) from host-observed reads."
        ),
        traces=traces,
        hints=hints,
    )
    payload = {"channels": channels_payload, "x_unit": view.x.unit or X_UNIT}
    return PlotRender(html=render_plot(composed), json=json.dumps(payload))


def plot_host_html(view: Any, ring: ObservationRing) -> str:
    """The wrapper the hydrator keys on: the figure plus its JSON block."""
    render = compose_page_plot(view, ring)
    slug = "".join(
        character if character.isalnum() else "-" for character in view.title.lower()
    )
    return (
        f'<div class="bw-plot-host" data-bw-plot-host data-bw-plot-slug="{slug}">\n'
        f"{render.html}\n"
        f'<script type="application/json" data-bw-plot-data>{render.json}</script>\n'
        "</div>"
    )
