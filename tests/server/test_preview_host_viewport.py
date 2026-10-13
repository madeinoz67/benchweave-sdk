"""Issue #449 slice 3 — viewport partials (zoom/scroll) over the lanes figure.

The design record's §3.3: zoom and scroll are VIEWPORT state over composed
columns — an htmx partial endpoint (``/pages/{page_id}/lanes/{view}`` with
``from``/``to`` window parameters) that recomposes the SAME declaration
against the windowed column budget and swaps the figure.
The trigger marker and cursors are data the composer already models
(presentation-only: positions are host-supplied); no plot vocabulary
changes (deferral D4 stands).

The units decision, pinned by ``test_units_are_sample_indices``: ``from``/
``to`` are ABSOLUTE SAMPLE INDICES into the capture, clamped into
``[0, acquired)``. Sample index is the composer's native grid
(``reduce_lane`` partitions sample indices; ``LaneSegment.first/last`` are
sample indices) and is rate-INDEPENDENT — the composer's seconds form
(``round(t * (rate or 0.0))``) degenerates without a rate, so sample index
is the only unit addressable both with and without a declared rate.

The pre-committed acceptance rule (design §7): a viewport request windowing
to the second half of a capture yields a figure whose ``data-bw-acquisition``
reports the windowed counts, and the un-windowed figure is unchanged — plus
a poll-isolation arm (a readings poll swap does not change the lanes
region's DOM identity).

READING NOTE (binding): fixture captures are slice 2 — the AR's "capture"
here is a TEST-SUPPLIED data-bearing ``LanesDeclaration`` injected through
the host's ``plots.lanes_source`` seam (states over the LaneState alphabet
0/1/x/z, sample count, rate, trigger, cursors — the composer's own model).
Slice 2 later replaces the seam's BODY with fixtures; the mechanism proven
here does not change.
"""

from __future__ import annotations

import html
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk_server import plots

# --- the test-supplied data-bearing capture ---------------------------------------


CAPTURE_SAMPLES = 1000
#: Absolute sample index of the d0 low→high transition (windowing inputs are
#: absolute sample indices; the transition lets one window prove BOTH states).
D0_EDGE = 300
#: 1000 Hz: one second of capture, so seconds-derived annotations (trigger,
#: cursors, decoder events) map to memorable sample indices.
RATE_HZ = 1000.0
#: The acceptance rule's window: the capture's second half.
SECOND_HALF = (500, 1000)


def _source_factory(rate: float | None):
    """The seam override: the host's declaration-only projection injected
    with the data-bearing capture. The slice-3 reading, per the brief: no
    fixture captures exist yet, so the TEST supplies the declaration the
    composer consumes.

    Same lane structure the host projects from the lanes fixture (4 channel
    lanes, a hex bus group over d0/d1, a radix-default group over d2/d3, a
    UART decoder lane), carrying states over the full LaneState alphabet
    (0, 1, x, z), a trigger, two cursors and two decoder events — one inside
    the acceptance window, one fully outside it. ``rate=None`` builds the
    rate-less twin the units pin needs.
    """
    from benchweave_ui_html.lanes import Cursor, DecoderEvent

    original = plots.lanes_source  # the production seam, bound pre-patch

    def _source(view: Any):
        declaration, member = original(view)
        channel_states: dict[str, tuple[str, ...]] = {
            "d0": tuple("0" * D0_EDGE + "1" * (CAPTURE_SAMPLES - D0_EDGE)),
            "d1": ("1",) * CAPTURE_SAMPLES,
            "d2": ("x",) * CAPTURE_SAMPLES,
            "d3": ("z",) * CAPTURE_SAMPLES,
        }
        lanes = []
        for spec in declaration.lanes:
            if spec.kind == "channel":
                lanes.append(replace(spec, states=channel_states[spec.label]))
            elif spec.kind == "decoder":
                lanes.append(
                    replace(
                        spec,
                        events=(
                            DecoderEvent(0.55, 0.70, "6E"),  # inside the AR window
                            DecoderEvent(0.10, 0.20, "OUT"),  # fully before it
                        ),
                    )
                )
            else:
                lanes.append(spec)  # bus groups: states ride member_states
        bearing = replace(
            declaration,
            lanes=tuple(lanes),
            acquired=CAPTURE_SAMPLES,
            sample_rate_hz=rate,
            trigger_s=0.5,  # sample 500: the AR window's first sample
            cursors=(Cursor(0.2), Cursor(0.6)),  # samples 200 / 600
        )
        return bearing, {name: channel_states[name] for name in member}

    return _source


# --- fixtures -----------------------------------------------------------------------

# The seam patch is PROCESS-GLOBAL for as long as it sits on
# ``plots.lanes_source`` — a module-scoped patch would leak into every other
# client's requests (observed: the un-patched host served the injected
# capture and the empty-capture refusal test flaked on fixture order). So the
# data-bearing clients are FUNCTION-scoped: the patch lives exactly as long
# as the test. The plugin PROJECTS stay module-scoped (disk build is the slow
# part; the app rebuild per test is not).


@pytest.fixture(scope="module")
def capture_project(
    tmp_path_factory: pytest.TempPathFactory, lanes_project_builder
) -> Path:
    project = tmp_path_factory.mktemp("viewport_capture") / "capture_plugin"
    return lanes_project_builder(project)


@pytest.fixture(scope="module")
def rateless_project(
    tmp_path_factory: pytest.TempPathFactory, lanes_project_builder
) -> Path:
    project = tmp_path_factory.mktemp("viewport_rateless") / "rateless_plugin"
    return lanes_project_builder(project)


@pytest.fixture
def capture_client(capture_project: Path, app_client_factory) -> TestClient:
    """The data-bearing host (rate 1000 Hz): the acceptance rule's client."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(plots, "lanes_source", _source_factory(RATE_HZ))
        yield app_client_factory(capture_project)


@pytest.fixture
def rateless_client(rateless_project: Path, app_client_factory) -> TestClient:
    """The rate-less twin (``sample_rate_hz=None``): the units pin's client."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(plots, "lanes_source", _source_factory(None))
        yield app_client_factory(rateless_project)


@pytest.fixture(scope="module")
def plain_client(
    tmp_path_factory: pytest.TempPathFactory,
    lanes_project_builder,
    app_client_factory,
) -> TestClient:
    """The un-patched host: the declaration-only source (production shape)."""
    project = tmp_path_factory.mktemp("viewport_plain") / "plain_plugin"
    lanes_project_builder(project)
    return app_client_factory(project)


# --- the served-surface probes ------------------------------------------------------


LANES_VIEW_URL = "/pages/capture/lanes/logic"
ACQUIRED_ATTR = re.compile(r'data-bw-acquired="(\d+)"')
PLOTTED_ATTR = re.compile(r'data-bw-plotted="(\d+)"')
TRIGGER_ATTR = re.compile(r'data-bw-trigger-sample="(-?\d+)"')
CURSOR_ATTR = re.compile(r'data-bw-cursor-sample="(-?\d+)"')
SPAN_ATTRS = re.compile(r'data-bw-span-start="([^"]+)" data-bw-span-end="([^"]+)"')
AXIS_LABEL_ATTR = re.compile(r'data-bw-axis-label="([^"]*)"')
LANES_FIGURE = re.compile(r'<figure class="bw-lanes".*?</figure>', re.DOTALL)
LANES_REGION = re.compile(
    r'<section class="bw-lanes-region".*?</section>\s*(?=<div id="page-readings")',
    re.DOTALL,
)


def _acquired(body: str) -> int:
    match = ACQUIRED_ATTR.search(body)
    assert match is not None, f"no data-bw-acquired in: {body[:200]}"
    return int(match.group(1))


def _plotted(body: str) -> int:
    match = PLOTTED_ATTR.search(body)
    assert match is not None, f"no data-bw-plotted in: {body[:200]}"
    return int(match.group(1))


# --- the acceptance rule -----------------------------------------------------------


class TestAcceptanceRule:
    def test_windowing_to_the_second_half_reports_windowed_counts(
        self, capture_client: TestClient
    ) -> None:
        response = capture_client.get(
            f"{LANES_VIEW_URL}?from={SECOND_HALF[0]}&to={SECOND_HALF[1]}"
        )
        assert response.status_code == 200, response.text[:200]
        assert _acquired(response.text) == 500, (
            "the windowed figure reports the WINDOW's sample count"
        )
        assert _plotted(response.text) == 500, (
            "the windowed figure plots the window's columns"
        )

    def test_the_unwindowed_figure_is_unchanged(
        self, capture_client: TestClient, plain_client: TestClient
    ) -> None:
        """The un-windowed endpoint figure is byte-identical to the page's
        own lanes figure — viewport machinery changes nothing about the
        default render. (During this test the data-bearing seam override is
        active process-wide, so the page figure is the data-bearing one —
        the pin proves ENDPOINT ≡ PAGE for the same source, while the
        production-shape byte parity stays pinned by AR-1 in the fidelity
        suite.)"""
        from_endpoint = LANES_FIGURE.search(capture_client.get(LANES_VIEW_URL).text)
        from_page = LANES_FIGURE.search(plain_client.get("/pages/capture").text)
        assert from_endpoint is not None and from_page is not None
        assert from_endpoint.group(0) == from_page.group(0), (
            "the un-windowed figure must be the page's own unchanged figure"
        )
        assert _acquired(from_endpoint.group(0)) == CAPTURE_SAMPLES
        assert _plotted(from_endpoint.group(0)) == min(600, CAPTURE_SAMPLES)


# --- the pinned units and window semantics -----------------------------------------


class TestWindowSemantics:
    def test_units_are_sample_indices(
        self, capture_client: TestClient, rateless_client: TestClient
    ) -> None:
        """``from``/``to`` are sample indices and NOTHING in the windowing
        path converts them through the rate: the rate-less twin (same
        states, ``sample_rate_hz=None``) windows to IDENTICAL segment
        geometry and acquisition counts."""
        with_rate = capture_client.get(f"{LANES_VIEW_URL}?from=200&to=400").text
        without_rate = rateless_client.get(
            f"{LANES_VIEW_URL}?from=200&to=400"
        ).text

        def _segments(body: str) -> list[tuple[str, str, str, str]]:
            return [
                (lane, first, last, state)
                for lane, first, last, state in re.findall(
                    r'data-bw-lane="(\d+)" data-bw-first="(\d+)" '
                    r'data-bw-last="(\d+)" data-bw-state="([^"]*)"',
                    body,
                )
            ]

        assert _acquired(with_rate) == 200 == _acquired(without_rate)
        assert _plotted(with_rate) == 200 == _plotted(without_rate)
        assert _segments(with_rate) == _segments(without_rate), (
            "the window path must be rate-independent (sample-index units)"
        )
        # The window's content is the absolute slice [200, 400) — d0 (lane 0)
        # STRADDLES its transition at 300 here (200 ≤ 300 < 400), so the
        # window-relative render shows 100 low columns, the edge at 300, then
        # 100 high columns; a column's first/last are SLICE indices
        # (exclusive last), so sample i shows as first=i, last=i+1.
        lane_zero = [seg for seg in _segments(with_rate) if seg[0] == "0"]
        assert len(lane_zero) == 200, "one column per sample at the budget"
        assert lane_zero[0] == ("0", "0", "1", "0")
        assert lane_zero[100] == ("0", "100", "101", "1"), (
            "the absolute edge at 300 lands at window-relative 300"
        )
        assert {seg[3] for seg in lane_zero} == {"0", "1"}, (
            "the [200, 400) slice straddles d0's edge: both states render"
        )

    def test_negative_from_clamps_to_zero(self, capture_client: TestClient) -> None:
        response = capture_client.get(f"{LANES_VIEW_URL}?from=-50&to=500")
        assert response.status_code == 200
        assert _acquired(response.text) == 500
        assert "samples 0–499" in response.text, (
            "the axis label must disclose the CLAMPED window"
        )

    def test_to_beyond_the_capture_clamps_to_acquired(
        self, capture_client: TestClient
    ) -> None:
        response = capture_client.get(f"{LANES_VIEW_URL}?from=500&to=2000")
        assert response.status_code == 200
        assert _acquired(response.text) == 500
        assert "samples 500–999" in response.text

    def test_full_capture_window_equals_the_capture_span(
        self, capture_client: TestClient
    ) -> None:
        """Clamping both ends inward/outward to [0, acquired) windows the
        whole capture — segments stay absolute-slice-equivalent (the d0 edge
        at 300 renders) and the axis discloses the full span."""
        response = capture_client.get(f"{LANES_VIEW_URL}?from=-100&to=2000")
        assert response.status_code == 200
        assert _acquired(response.text) == CAPTURE_SAMPLES
        assert 'data-bw-state="0"' in response.text, "the low half renders"
        assert 'data-bw-state="1"' in response.text, "the high half renders"
        assert "samples 0–999" in response.text

    @pytest.mark.parametrize("window", [("600", "500"), ("500", "500"), ("700", "700")])
    def test_an_empty_or_inverted_window_refuses(
        self, capture_client: TestClient, window: tuple[str, str]
    ) -> None:
        """``from >= to`` (inverted or zero-width) refuses — an empty figure
        would launder an empty window as a rendered capture."""
        response = capture_client.get(
            f"{LANES_VIEW_URL}?from={window[0]}&to={window[1]}"
        )
        assert response.status_code == 400
        assert response.text.startswith("viewport_window_refused:"), response.text

    def test_a_window_over_an_empty_capture_refuses(
        self, plain_client: TestClient
    ) -> None:
        """The declaration-only source has ``acquired=0`` — every window
        clamps to an empty span and refuses (there is no capture to show;
        an empty windowed figure would fake one)."""
        response = plain_client.get(f"{LANES_VIEW_URL}?from=0&to=100")
        assert response.status_code == 400
        assert response.text.startswith("viewport_window_refused:")

    def test_half_a_window_is_a_client_error(self, plain_client: TestClient) -> None:
        for query in ("?from=500", "?to=500", "?from=abc&to=500", "?from=1.5&to=5"):
            response = plain_client.get(f"{LANES_VIEW_URL}{query}")
            assert response.status_code == 400, query
            assert response.text.startswith("viewport_window_refused:"), query

    def test_unknown_page_or_view_refuses(self, plain_client: TestClient) -> None:
        assert plain_client.get("/pages/nope/lanes/logic").status_code == 404
        assert plain_client.get("/pages/capture/lanes/nope").status_code == 404
        assert plain_client.get("/pages/readings/lanes/logic").status_code == 404, (
            "a page without lanes plots has no lanes view to window"
        )


# --- recomposition fidelity ---------------------------------------------------------


class TestRecomposition:
    def test_segments_are_window_relative_slices(
        self, capture_client: TestClient
    ) -> None:
        """The windowed figure draws the absolute slice [first, last): d0's
        transition at 300 renders inside [0, 500) and is GONE from
        [500, 1000); positions are window-relative."""
        first_half = capture_client.get(f"{LANES_VIEW_URL}?from=0&to=500").text
        second_half = capture_client.get(
            f"{LANES_VIEW_URL}?from=500&to=1000"
        ).text
        # [0, 500): 300 low samples, then 200 high — the edge renders. The
        # package draws one column per sample at or below the budget, and a
        # column's first/last are SLICE indices (exclusive last): sample i
        # shows as first=i, last=i+1.
        assert 'data-bw-first="0" data-bw-last="1" data-bw-state="0"' in first_half
        assert 'data-bw-first="299" data-bw-last="300" data-bw-state="0"' in first_half
        assert 'data-bw-first="300" data-bw-last="301" data-bw-state="1"' in first_half
        assert 'data-bw-first="499" data-bw-last="500" data-bw-state="1"' in first_half
        # [500, 1000): all high, window-relative from zero.
        assert 'data-bw-first="0" data-bw-last="1" data-bw-state="1"' in second_half
        assert 'data-bw-first="499" data-bw-last="500" data-bw-state="1"' in second_half
        assert 'data-bw-state="0"' not in second_half, (
            "the low half must not leak into the second-half window"
        )

    def test_bus_cells_recompose_from_windowed_members(
        self, capture_client: TestClient
    ) -> None:
        """Bus groups read their members through ``member_states`` — the
        windowed figure's bus cells reflect the WINDOWED member states (d0
        high + d1 high over the second half ⇒ 0x3, not the full capture's
        0x1 cells)."""
        second_half = capture_client.get(f"{LANES_VIEW_URL}?from=500&to=1000").text
        assert 'data-bw-bus-value="3"' in second_half, (
            "the windowed bus cells come from the windowed member states"
        )
        assert 'data-bw-bus-value="2"' not in second_half, (
            "d0 is high across the whole window: no low-stretch cells survive"
        )
        full = capture_client.get(LANES_VIEW_URL).text
        assert 'data-bw-bus-value="2"' in full, (
            "the un-windowed figure keeps the full capture's low-stretch "
            "cells (d0 low + d1 high ⇒ 0x2)"
        )

    def test_trigger_and_cursors_pass_through_rebased(
        self, capture_client: TestClient
    ) -> None:
        """Scope item 4, pinned: the composer's trigger/cursor model
        survives windowing — in-window markers rebase window-relative
        (sample − first), out-of-window markers drop (a marker drawn off the
        shown range would lie about its position), and the Δt readout
        survives on two surviving cursors."""
        full = capture_client.get(LANES_VIEW_URL).text
        assert TRIGGER_ATTR.search(full).group(1) == "500"
        assert sorted(CURSOR_ATTR.findall(full)) == ["200", "600"]
        assert "Δt" in full

        windowed = capture_client.get(
            f"{LANES_VIEW_URL}?from=500&to=1000"
        ).text
        assert TRIGGER_ATTR.search(windowed).group(1) == "0", (
            "the trigger at the window's first sample rebases to 0"
        )
        assert CURSOR_ATTR.findall(windowed) == ["100"], (
            "the in-window cursor rebases (600 − 500); the one at 200 drops"
        )
        assert "Δt" not in windowed, "a single survivor has no Δt pair"

    def test_trigger_and_cursors_drop_without_a_rate(
        self, rateless_client: TestClient
    ) -> None:
        """Positions are seconds; without a rate the composer's seconds→
        samples mapping degenerates (``round(t * 0.0)``), so a windowed
        recomposition cannot honestly rebase them — they drop rather than
        pin to the window start."""
        windowed = rateless_client.get(f"{LANES_VIEW_URL}?from=500&to=1000").text
        assert TRIGGER_ATTR.search(windowed) is None
        assert CURSOR_ATTR.search(windowed) is None

    def test_decoder_events_shift_window_relative(
        self, capture_client: TestClient
    ) -> None:
        """Decoder events are absolute-time annotations: windowing SHIFTS
        them by the window offset (never quantized) — the in-window event
        [0.55, 0.70) over [500, 1000) renders [0.05, 0.20); the pre-window
        event drops; the composer's own clip then bounds the extent."""
        full = capture_client.get(LANES_VIEW_URL).text
        spans = SPAN_ATTRS.findall(full)
        assert ("0.55", "0.7") in spans or ("0.55", "0.70") in spans, spans

        windowed = capture_client.get(
            f"{LANES_VIEW_URL}?from=500&to=1000"
        ).text
        spans = SPAN_ATTRS.findall(windowed)
        assert spans == [("0.05", "0.2")], (
            f"the in-window event shifts by the window offset; got {spans}"
        )

    def test_the_window_is_disclosed_on_the_axis(
        self, capture_client: TestClient
    ) -> None:
        """A windowed figure's axis label carries the absolute sample span —
        window-relative positions without the offset disclosure would
        launder absolute positions into local ones."""
        windowed = capture_client.get(
            f"{LANES_VIEW_URL}?from=500&to=1000"
        ).text
        match = AXIS_LABEL_ATTR.search(windowed)
        assert match is not None
        assert match.group(1).endswith("samples 500–999"), match.group(1)
        full = AXIS_LABEL_ATTR.search(capture_client.get(LANES_VIEW_URL).text)
        assert full is not None
        assert "samples 500–999" not in full.group(1), (
            "the un-windowed figure discloses no window (it shows everything)"
        )


# --- the htmx controls and the poll-isolation arm -----------------------------------


class TestControlsAndPollIsolation:
    def test_the_page_carries_viewport_blocks_with_controls(
        self, capture_client: TestClient, plain_client: TestClient
    ) -> None:
        """The lanes region renders per-view viewport blocks: a stable host
        for the figure plus a server-driven control toolbar (htmx GET swaps
        replacing the whole block — §C.3's partial pattern). The plain
        (declaration-only) host has nothing navigable (acquired=0) and
        renders no toolbar."""
        body = capture_client.get("/pages/capture").text
        assert 'data-bw-lanes-view="logic"' in body
        assert "data-bw-lanes-host" in body
        toolbar = re.search(
            r'<div class="bw-lanes-controls"[^>]*>.*?</div>', body, re.DOTALL
        )
        assert toolbar is not None, "the viewport toolbar renders"
        for attr in ('hx-target="closest .bw-lanes-viewport"', 'hx-swap="outerHTML"'):
            assert attr in toolbar.group(0), attr
        assert f'hx-get="{LANES_VIEW_URL}"' in toolbar.group(0), (
            "the Full control targets the lanes partial endpoint"
        )

    def test_an_empty_capture_renders_no_toolbar(self, plain_client: TestClient) -> None:
        """Nothing navigable over a capture with zero acquired samples: the
        toolbar is omitted entirely (a lone Full button would invite a
        request that refuses). PLAIN HOST ONLY — running this against the
        patched client would measure the injection, not the mechanism."""
        plain = plain_client.get("/pages/capture").text
        assert "bw-lanes-controls" not in plain, (
            "nothing navigable over an empty capture: no toolbar renders"
        )
        assert "bw-lanes-viewport" in plain, (
            "the viewport host block itself still renders"
        )

    def test_every_rendered_control_serves_a_windowed_figure(
        self, capture_client: TestClient
    ) -> None:
        """Control URLs are server-computed and server-clamped — walking
        them must land on figures whose window stays inside the capture."""
        body = capture_client.get("/pages/capture").text
        urls = re.findall(r'hx-get="(/pages/capture/lanes/logic[^"]*)"', body)
        assert urls, "the toolbar carries navigable URLs"
        for raw_url in urls:
            # The template HTML-escapes the query separator (&amp;) — the
            # browser decodes the entity before GETing; the test mirrors it.
            url = html.unescape(raw_url)
            response = capture_client.get(url)
            assert response.status_code == 200, (url, response.text[:120])
            window = _acquired(response.text)
            assert 0 < window <= CAPTURE_SAMPLES, (url, window)

    def test_poll_swap_does_not_touch_the_lanes_region(
        self, capture_client: TestClient, plain_client: TestClient
    ) -> None:
        """THE POLL-ISOLATION ARM. The lanes region (viewport blocks, host,
        toolbar) sits OUTSIDE the readings poll region: the poll's partial
        must carry none of it, and the region itself must carry no poll
        trigger. Discriminating construction: a regression that moves the
        figure back inside the poll region re-renders the viewport block in
        the poll partial — this test fails on it."""
        body = capture_client.get("/pages/capture").text
        region = LANES_REGION.search(body)
        assert region is not None, "the lanes region renders ahead of the poll"
        assert 'hx-trigger="every' not in region.group(0), (
            "the lanes region must carry no poll trigger"
        )

        poll = plain_client.get("/pages/capture/readings").text
        assert "bw-lanes-region" not in poll
        assert "bw-lanes-viewport" not in poll, (
            "the poll swap must not re-render the viewport block"
        )
        assert "bw-lanes-controls" not in poll
        assert LANES_FIGURE.search(poll) is None, (
            "the poll swap must not re-render the lanes figure"
        )
