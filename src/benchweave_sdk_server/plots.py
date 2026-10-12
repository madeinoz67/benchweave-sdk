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

Digital lanes compose through the package's lanes module the same way
(:func:`benchweave_ui_html.lanes.compose_lanes` + ``partials.render_lanes``
over a ``LanesDeclaration`` projected from the view): lane rows, bus cells,
decoder spans and the acquisition furniture are the package's bytes. Preview
acquires no capture data (that is the preview fixtures train's work), so the
declaration is declaration-only: ``acquired=0``, no states, no events — the
package's own "Acquired 0 samples · plotted 0" line is the one shown.

No plugin-supplied plot options enter anywhere: the wrapper is closed.
The manifest's channel hints are the only plugin input, and each branch
resolves exactly what it renders: the scalar branch flows hints through
the package's own hint resolution (colour role, visibility per channel);
the lanes branch honors exactly one key — an explicit ``visible: false``
maps to ``LaneSpec.hidden`` and the package renders the hidden lane
(issue #449 fold F1). Every other hint key has no lanes rendering, and
``lane_group.default_collapsed`` and decoder ``settings`` stay unwired —
the refute slate's row-call, recorded here, not an oversight.
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from benchweave_ui_html.lanes import LanesDeclaration, LaneSpec, compose_lanes
from benchweave_ui_html.plot import ChannelHint, TraceSpec, compose_plot

from benchweave_sdk.preview_models import PlotView

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

    def clear(self) -> None:
        """Drop every sample. A reload resets the ring: the previous
        plugin version's observations are not the new version's data, and
        plotting them would launder one version's samples into another's
        axes."""
        self._samples.clear()

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
        # Ties resolve to the FIRST minimum and the LAST maximum, so a
        # multi-point column of equal values keeps its x-extent instead of
        # collapsing onto its first point.
        low = min(column, key=lambda point: point[1])
        high = max(reversed(column), key=lambda point: point[1])
        if low == high:
            # A single-point column emits ONE point (fold 3): emitting its
            # min and max twice inflated the drawn count past the acquired
            # count - a duplicated wire payload and a disclosure the
            # package's drawn>=acquired rule then skipped.
            reduced.append(low)
            return
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


def compose_page_plot(view: PlotView, ring: ObservationRing) -> PlotRender:
    """Compose one ``PlotView`` into the rendered figure and its payload.

    The figure is the package's own ``render_plot(compose_plot(...))``
    output; the payload is the decimated columns per channel, keyed to the
    figure's wrapper. Digital lanes delegate to the package's lanes module
    (no payload: the figure is semantic HTML, no canvas to hydrate).
    """
    from benchweave_ui_html.partials import render_plot

    if view.kind == "digital_lanes":
        return PlotRender(html=plot_lanes_html(view), json="")
    hints = {
        channel.variable_id: ChannelHint(
            color_role=channel.color_role,
            # An OMITTED manifest visibility key is not a hide request: the
            # projected ``PlotChannel.visible`` is None for hints that only
            # carry a colour role, and ``ChannelHint(visible=None)`` computes
            # ``hidden = not None`` — hiding every hinted channel (fold 1:
            # the unmodified scaffold rendered its one channel "hidden by
            # presentation preference"). Default the omission to VISIBLE;
            # an explicit ``visible: false`` keeps hiding.
            visible=True if channel.visible is None else channel.visible,
        )
        for channel in view.channels
        if channel.color_role is not None or channel.visible is not None
    }
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
            "1 plotted channel from host-observed reads"
            + (
                f"; {len(view.channels) - 1} declared channel(s) have no "
                "host data path yet (capture data is I3's)"
                if len(view.channels) > 1
                else ""
            )
        ),
        traces=traces,
        hints=hints,
    )
    payload = {"channels": channels_payload, "x_unit": view.x.unit or X_UNIT}
    html = render_plot(composed)
    if len(samples) >= ring.cap:
        # The package's disclosure row says "Acquired {n}" - but at the cap
        # n is the RETAINED count, not everything ever acquired (the ring
        # dropped the oldest to get here). The retention window is
        # disclosed beside the figure (fold 3: the wording must not claim
        # more than the window).
        html += (
            '\n<p class="bw-plot-retention" role="status">The host retains '
            f"the most recent {ring.cap} samples of this parameter.</p>"
        )
    return PlotRender(html=html, json=json.dumps(payload))


def build_lanes_declaration(view: PlotView) -> LanesDeclaration:
    """The projected view → the package's declaration (issue #449 slice 1).

    Lane specs in declared order: channel lanes from ``view.channels`` —
    an explicit ``visible: false`` channel hint hides its lane (the
    package renders ``data-hidden``; an omitted hint is not a hide
    request) — group lanes from ``view.lane_groups`` (members and radix),
    decoder lanes from ``view.decoder_lanes`` (first declared source
    channel). Preview acquires no capture data, so the declaration is
    declaration-only: ``acquired=0``, no states, no events. The lane
    index is the declared position (the package's lane identity — never
    renumbered).
    """
    lanes: list[LaneSpec] = []
    index = 0
    for channel in view.channels:
        # The hint's visibility rides the spec (fold F1): an explicit
        # ``visible: false`` hides the lane — the package renders
        # ``data-hidden`` plus its hidden marker — and an OMITTED hint is
        # not a hide request (the scalar branch's own default, fold 1).
        lanes.append(
            LaneSpec(
                index=index,
                kind="channel",
                label=channel.label,
                hidden=channel.visible is False,
            )
        )
        index += 1
    for group in view.lane_groups:
        members = tuple(str(member) for member in group["member_ids"])
        lanes.append(
            LaneSpec(
                index=index,
                kind="group",
                label=str(group.get("label") or group["id"]),
                members=members,
                bit_width=len(members),
                radix=group.get("radix", "hex"),
            )
        )
        index += 1
    for decoder in view.decoder_lanes:
        lanes.append(
            LaneSpec(
                index=index,
                kind="decoder",
                label=str(decoder.get("label") or decoder["id"]),
                source_channel=str(decoder["source_channel_ids"][0]),
            )
        )
        index += 1
    return LanesDeclaration(
        title=view.title,
        description=(
            f"{view.title}: the declared capture structure; "
            "no capture data is acquired in preview."
        ),
        lanes=tuple(lanes),
        acquired=0,
        columns=PLOT_COLUMNS,
        axis_label=view.x.label,
        axis_unit="s",
    )


def plot_lanes_html(view: PlotView) -> str:
    """The package's lanes figure for one declared digital-lanes view.

    Composition runs through :func:`benchweave_ui_html.lanes.compose_lanes`
    and the package's ``render_lanes`` partial — the host authors no lane
    markup. The declaration-only render's bus-cell walk needs every
    declared member present in ``member_states`` (the package raises on a
    missing member even when the sequence is empty), so each member binds
    an EMPTY sequence: no samples, no cells — the package's empty path.
    """
    from benchweave_ui_html.partials import render_lanes

    declaration = build_lanes_declaration(view)
    member_states = {
        str(member): ()
        for group in view.lane_groups
        for member in group["member_ids"]
    }
    return render_lanes(compose_lanes(declaration, member_states))


def plot_host_html(view: PlotView, ring: ObservationRing) -> str:
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
