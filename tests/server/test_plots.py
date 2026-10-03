"""The plot wrapper (I2a §3.3, SW-25/UR-07, ruled by #310): host-side.

The host composes each declared plot through the package's own plot
machinery (``compose_plot`` over the projected ``PlotView``), decimates the
session's bounded observation ring min/max-per-column HOST-SIDE (#310's
ruling), and emits the columns in a CSP-safe JSON block keyed to the
rendered figure. The acquisition disclosure derives from the decimation
output — never caller-supplied (G1b fold M1's rule). uPlot vendors
HOST-SIDE under the host's own inventory; digital lanes render the skeleton
with the no-data disclosure (live lane data is I3's — D-I2b).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk_server.plots import (
    PLOT_COLUMNS,
    ObservationRing,
    compose_page_plot,
    decimate_minmax,
)
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.session import PluginSession, mock_exchanges
from benchweave_sdk_server.transport import LoopingMockHost
from benchweave_sdk_server.web import build_app

DEV = "example_device"
UI_ASSETS = Path(__file__).resolve().parents[2] / "src" / "benchweave_sdk_server" / "ui_assets"


def _policy() -> GuardPolicy:
    return GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )


@pytest.fixture()
def app_client(plugin):
    seam = StandaloneSeam(
        PluginSession(plugin, lambda: LoopingMockHost(mock_exchanges(plugin))),
        transport_kind="mock",
    )
    policy = _policy()
    client = TestClient(build_app(seam, policy=policy), base_url="http://127.0.0.1:8477")
    with client:
        yield client, seam, policy


# --- the bounded observation ring ----------------------------------------------


def test_the_ring_records_host_observed_samples_and_caps() -> None:
    ring = ObservationRing(cap=4)
    for index in range(10):
        ring.record("voltage", 100.0 * index, 1.0)
    samples = ring.snapshot("voltage")
    assert len(samples) == 4, "the ring is bounded (the cap drops the oldest)"
    assert samples[0][0] == 600.0, "the newest samples survive"


def test_the_ring_records_only_finite_numeric_values() -> None:
    """A bool/string read never feeds a numeric plot; ``None`` (loading)
    is not an observation."""
    ring = ObservationRing(cap=8)
    ring.record("voltage", 1.0, None)
    ring.record("voltage", 2.0, True)
    ring.record("voltage", 3.0, "3.3")
    ring.record("voltage", 4.0, 3.3)
    assert ring.snapshot("voltage") == [(4.0, 3.3)]


def test_the_ring_feeds_from_every_parameter_read(app_client) -> None:
    client, seam, policy = app_client
    client.post(f"/devices/{DEV}/connect", headers={"x-csrf-token": _csrf(client)})
    for _ in range(3):
        client.post(
            "/v1/parameter_read",
            json={"device_id": DEV, "parameter": "voltage"},
            headers={"authorization": f"Bearer {policy.bearer_token}"},
        )
    ring = seam.observation_ring
    samples = ring.snapshot("voltage")
    assert len(samples) == 3, samples
    assert all(value == 3.3 for _, value in samples)


def _csrf(client: TestClient) -> str:
    body = client.get(f"/devices/{DEV}").text
    marker = 'hx-headers=\'{"X-CSRF-Token": "'
    return body.split(marker, 1)[1].split('"', 1)[0]


# --- host-side min/max decimation (#310's ruling) -------------------------------


def _ramp(count: int) -> list[tuple[float, float]]:
    return [(float(index), float(index)) for index in range(count)]


def test_decimation_keeps_the_min_and_max_of_every_column() -> None:
    """100 samples → 2 columns keeps 4 points: each column's min and max,
    in x order — the extremes survive (a dropped spike is the defect class
    min/max decimation exists to prevent)."""
    points = _ramp(100)
    points[37] = (37.0, -50.0)  # an interior minimum
    points[71] = (71.0, 500.0)  # an interior maximum
    reduced = decimate_minmax(points, columns=2)
    assert len(reduced) == 4
    values = [value for _, value in reduced]
    assert -50.0 in values and 500.0 in values
    assert [x for x, _ in reduced] == sorted(x for x, _ in reduced)


def test_decimation_is_identity_below_the_column_budget() -> None:
    points = _ramp(3)
    assert decimate_minmax(points, columns=PLOT_COLUMNS) == points


def test_decimation_output_count_bounds_the_payload() -> None:
    points = _ramp(5000)
    reduced = decimate_minmax(points, columns=PLOT_COLUMNS)
    assert len(reduced) <= 2 * PLOT_COLUMNS


# --- the composed plot over the projected view ---------------------------------


def test_the_page_renders_the_declared_plot_through_the_package_partial(
    app_client,
) -> None:
    """The scaffold declares one time-series plot: the page carries the
    package's ``render_plot`` figure (role=img, the legend rows, the
    acquisition disclosure) composed from the projected ``PlotView``."""
    client, _, policy = app_client
    client.post(f"/devices/{DEV}/connect", headers={"x-csrf-token": _csrf(client)})
    client.post(
        "/v1/parameter_read",
        json={"device_id": DEV, "parameter": "voltage"},
        headers={"authorization": f"Bearer {policy.bearer_token}"},
    )
    body = client.get("/pages/readings").text
    assert 'class="bw-plot"' in body
    assert 'role="img"' in body
    assert 'data-bw-channel-id="value"' in body
    # The acquisition disclosure derives from the decimation output: one
    # acquired sample plots one point, so §E.2.5's row does not render yet.
    assert "Acquired" not in body


def test_the_acquisition_disclosure_derives_from_the_decimation() -> None:
    """Many reads, one plot: the disclosure names the ring's own acquired
    count and the decimated drawn count — never a caller-supplied scalar."""
    from benchweave_ui_html.plot import TraceSpec, compose_plot

    points = _ramp(300)
    reduced = decimate_minmax(points, columns=2)
    composed = compose_plot(
        title="Supply rail",
        description="test",
        traces=(TraceSpec("value", "V", samples=tuple(v for _, v in reduced), acquired=300),),
        hints={},
    )
    assert composed.acquisition
    (row,) = composed.acquisition
    assert row.acquired == 300
    assert row.drawn == len(reduced)
    assert f"Acquired {row.acquired} samples · plotted {row.drawn}" in row.text


def test_the_json_block_is_csp_safe_and_keys_to_the_figure(app_client) -> None:
    """The columns ride in a ``application/json`` block (data, never
    executed) keyed to the plot's own wrapper — the hydrator's join key."""
    client, _, policy = app_client
    client.post(f"/devices/{DEV}/connect", headers={"x-csrf-token": _csrf(client)})
    for _ in range(5):
        client.post(
            "/v1/parameter_read",
            json={"device_id": DEV, "parameter": "voltage"},
            headers={"authorization": f"Bearer {policy.bearer_token}"},
        )
    body = client.get("/pages/readings").text
    assert 'type="application/json"' in body
    assert "data-bw-plot-host" in body
    block = body.split("data-bw-plot-data>", 1)[1].split("</script>", 1)[0]
    payload = json.loads(block)
    assert payload["channels"][0]["id"] == "value"
    # Five REST reads plus the page's own gather read feed the ring.
    assert len(payload["channels"][0]["x"]) == 6
    assert payload["x_unit"] == "s"


def test_digital_lanes_render_the_skeleton_with_the_no_data_disclosure() -> None:
    """A declared digital-lanes plot renders its skeleton figure and the
    no-data disclosure — live lane data is I3's (D-I2b), and the page says
    so rather than drawing an empty capture.

    Pinned at the composition seam: a VALIDATED digital-lanes declaration
    requires a dataset target with string/vector lane variables (the
    presentation validator refuses an observation-targeted lanes plot),
    and the scaffold's generator never emits one — the first validated
    lanes manifest rides I3's capture work, where dataset targets exist.
    The render arm itself is what this pin holds."""
    from benchweave_sdk.preview_models import PlotAxis, PlotChannel, PlotView
    from benchweave_sdk_server.plots import compose_page_plot

    view = PlotView(
        page_id="readings",
        kind="digital_lanes",
        binding_id="capture",
        title="Lane view",
        x=PlotAxis(label="time", unit="s"),
        channels=(PlotChannel(variable_id="sda", label="sda", unit=None),),
        lane_groups=(),
        decoder_lanes=(),
    )
    render = compose_page_plot(view, ObservationRing())
    assert "data-bw-lanes" in render.html
    assert "No lane data" in render.html


# --- the vendored uPlot + the hydrator (host-side, per #310) --------------------


def test_uplot_vendors_host_side_with_provenance_and_no_versioned_name() -> None:
    """The single-file build (measured 49.9 KiB by #310), its stylesheet,
    the licence and the upstream provenance line the host's own inventory;
    the FILENAME carries no version (obligation 20/22's literal-free tree)."""
    inventory = json.loads((UI_ASSETS / "inventory.json").read_text())
    listed = {row["path"] for row in inventory["assets"]}
    for name in ("uplot.min.js", "uplot.css", "uplot-LICENCE", "bw-plot.js"):
        assert name in listed, name
    sources = (UI_ASSETS / "uplot-SOURCES.md").read_text()
    assert "uPlot" in sources
    assert "MIT" in sources


def test_the_assets_route_serves_the_vendored_bytes(client: TestClient) -> None:
    for name in ("uplot.min.js", "uplot.css", "bw-plot.js"):
        served = client.get(f"/assets/{name}")
        assert served.status_code == 200, name
        assert served.content == (UI_ASSETS / name).read_bytes(), name


def test_the_base_template_loads_the_plot_assets(client: TestClient) -> None:
    body = client.get("/").text
    assert 'href="/assets/uplot.css"' in body
    assert 'src="/assets/uplot.min.js"' in body
    assert 'src="/assets/bw-plot.js"' in body


# --- helpers --------------------------------------------------------------------


# --- the visibility default (fold 1: an omitted hint is not a hide request) ----


def _scaffold_plot_view(starter_project):
    from benchweave_sdk_server.presentation import load_host_presentation
    from benchweave_sdk_server.session import load_plugin_project

    plugin = load_plugin_project(starter_project)
    views = load_host_presentation(plugin).plot_views
    assert views, "the scaffold projects one example plot"
    return views[0]


def test_a_color_role_only_hint_renders_the_channel_visible(starter_project) -> None:
    """The scaffold's own manifest hint carries ``color_role: muted`` and NO
    ``visible`` key: the omitted flag must default VISIBLE. Passing None
    through ``ChannelHint(visible=...)`` computes ``hidden = not None`` and
    hides every scaffold channel — the legend row renders "hidden by
    presentation preference", the acquisition disclosure never fires (hidden
    traces draw nothing), and the axis filter empties ``data-bw-axes``."""
    view = _scaffold_plot_view(starter_project)
    ring = ObservationRing()
    for index in range(5000):
        ring.record("voltage", 10.0 * index, 3.3)
    render = compose_page_plot(view, ring)
    assert "data-hidden" not in render.html, "the channel renders hidden"
    assert "hidden by presentation preference" not in render.html
    assert "Acquired" in render.html, "a visible decimated trace discloses"
    assert 'data-bw-axes="V"' in render.html, "the y-axis unit survives"


def test_an_explicit_hide_hint_still_hides(starter_project) -> None:
    """The fix's honest boundary: a manifest hint that SAYS visible=false
    keeps hiding the channel (the omission default never overrides an
    explicit request)."""
    from dataclasses import replace as _replace

    view = _scaffold_plot_view(starter_project)
    channel = view.channels[0]
    hidden_view = _replace(
        view,
        channels=(
            _replace(channel, color_role=None, visible=False),
        ),
    )
    render = compose_page_plot(hidden_view, ObservationRing())
    assert "data-hidden" in render.html


# --- the lanes skeleton escapes the manifest title (fold 2) ---------------------


def test_the_lanes_skeleton_escapes_the_manifest_title() -> None:
    """A hostile page title must not land as a real attribute on the
    hand-built skeleton (#363's lesson class: manifest data never bypasses
    the escaped renderer)."""
    from benchweave_sdk.preview_models import PlotAxis, PlotChannel, PlotView

    view = PlotView(
        page_id="readings",
        kind="digital_lanes",
        binding_id="capture",
        title='Lane view" onmouseover="alert(1)',
        x=PlotAxis(label="time", unit="s"),
        channels=(PlotChannel(variable_id="sda", label="sda", unit=None),),
        lane_groups=(),
        decoder_lanes=(),
    )
    render = compose_page_plot(view, ObservationRing())
    assert 'onmouseover="alert' not in render.html
    assert render.html.count('onmouseover="') == 0, "no unescaped attribute slot remains"
    # The title still renders, escaped, in the attribute slots.
    assert "Lane view" in render.html
    assert "&#34;" in render.html or "&quot;" in render.html


# --- decimation duplicate points and retention honesty (fold 3) -----------------


def test_the_column_band_retains_every_point_without_duplicates() -> None:
    """n in (columns, 2*columns]: single-point columns must emit ONE point,
    not their min and max twice. The duplicate form claimed drawn > acquired
    (1200 points for 601 samples) - inflating the wire payload and making
    the package's drawn>=acquired rule skip the disclosure even where
    points were dropped."""
    points = [(float(index), float(index % 7)) for index in range(PLOT_COLUMNS + 1)]
    reduced = decimate_minmax(points, columns=PLOT_COLUMNS)
    assert len(reduced) == PLOT_COLUMNS + 1, "every point retained, once"
    assert len({x for x, _ in reduced}) == len(reduced), "no duplicate columns"


def test_a_full_ring_discloses_its_retention_window(starter_project) -> None:
    """When the ring is at its cap the disclosure's 'Acquired {n}' names the
    RETAINED count, not everything ever acquired: the figure carries the
    retention window beside the disclosure (the honest channel)."""
    view = _scaffold_plot_view(starter_project)
    ring = ObservationRing(cap=2000)
    for index in range(5000):
        ring.record("voltage", 10.0 * index, float(index % 5))
    render = compose_page_plot(view, ring)
    assert "Acquired" in render.html
    assert "retains the most recent 2000 samples" in render.html
    shallow = ObservationRing(cap=4096)
    for index in range(10):
        shallow.record("voltage", 10.0 * index, 1.0)
    quiet = compose_page_plot(view, shallow)
    assert "retains" not in quiet.html


# --- the composed description admits unplotted channels (fold R-g) --------------


def test_the_description_does_not_overstate_plotted_channels(starter_project) -> None:
    """Row R-g: a plot view declaring TWO channels, of which the host can
    plot only the value channel, must not claim both plot. The full
    multi-channel data story stays I3's; the description stops
    overstating."""
    from dataclasses import replace as _replace


    view = _scaffold_plot_view(starter_project)
    second = _replace(view.channels[0], variable_id="aux")
    wide = _replace(view, channels=(view.channels[0], second))
    render = compose_page_plot(wide, ObservationRing())
    assert "2 channel(s) from host-observed reads" not in render.html
    assert "1 plotted channel" in render.html
    assert "1 declared channel(s) have no host data path" in render.html


def test_a_single_channel_description_claims_only_that_channel(starter_project) -> None:
    view = _scaffold_plot_view(starter_project)
    render = compose_page_plot(view, ObservationRing())
    assert "1 plotted channel" in render.html
    assert "no host data path" not in render.html


def test_the_lanes_skeleton_names_its_declared_lane_count() -> None:
    """Row R-g's lanes arm: the skeleton's no-data line names how many
    lane channels are declared (an honest count of structure, not of
    data)."""
    from benchweave_sdk.preview_models import PlotAxis, PlotChannel, PlotView

    view = PlotView(
        page_id="readings",
        kind="digital_lanes",
        binding_id="capture",
        title="Lane view",
        x=PlotAxis(label="time", unit="s"),
        channels=(
            PlotChannel(variable_id="sda", label="sda", unit=None),
            PlotChannel(variable_id="scl", label="scl", unit=None),
        ),
        lane_groups=(),
        decoder_lanes=(),
    )
    render = compose_page_plot(view, ObservationRing())
    assert "2 declared lane channel(s)" in render.html
