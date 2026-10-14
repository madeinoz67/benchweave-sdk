"""Issue #449 slice 3 fold wave — post-refute rows F1-F12 (RED-first).

Companion to ``test_preview_host_viewport.py``: this module carries the
refute lanes' rows as executable RED arms, each proven failing at the fold
base (770be60) before its fix lands. Rows F9/F11/F12 are docstring/comment
honesty rows verified by diff, not by cells.
"""

from __future__ import annotations

import html
import re
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk_server import plots

# --- the fold-wave data-bearing source ----------------------------------------------


RATE_HZ = 1000.0
CAPTURE_SAMPLES = 1000

D0_EDGE = 300
FOLD_VIEW_URL = "/pages/capture/lanes/logic"
TRIGGER_ATTR = re.compile(r'data-bw-trigger-sample="(-?\d+)"')
CURSOR_ATTR = re.compile(r'data-bw-cursor-sample="(-?\d+)"')
SPAN_ATTRS = re.compile(r'data-bw-span-start="([^"]+)" data-bw-span-end="([^"]+)"')
LANES_FIGURE = re.compile(r'<figure class="bw-lanes".*?</figure>', re.DOTALL)


def _fold_source_factory(
    rate: float | None = RATE_HZ,
    *,
    trigger_s: float | None = 0.5,
    cursor_positions: tuple[float, ...] = (0.2, 0.6),
    events: tuple[tuple[float, float, str], ...] = (
        (0.55, 0.70, "6E"),
        (0.10, 0.20, "OUT"),
    ),
    acquired: int = CAPTURE_SAMPLES,
    states_length: int | None = None,
):
    """The seam override with fold-row overrides (boundary events, high-rate
    tables, invariant breaches). Same lane structure as the slice's fixture:
    4 channel lanes over the full LaneState alphabet, bus groups, a decoder."""
    from benchweave_ui_html.lanes import Cursor, DecoderEvent

    original = plots.lanes_source  # the production seam, bound pre-patch
    length = CAPTURE_SAMPLES if states_length is None else states_length

    def _source(view: Any):
        declaration, member = original(view)
        channel_states: dict[str, tuple[str, ...]] = {
            "d0": tuple("0" * D0_EDGE + "1" * (max(length, D0_EDGE) - D0_EDGE)),
            "d1": ("1",) * length,
            "d2": ("x",) * length,
            "d3": ("z",) * length,
        }
        lanes = []
        for spec in declaration.lanes:
            if spec.kind == "channel":
                lanes.append(replace(spec, states=channel_states[spec.label]))
            elif spec.kind == "decoder":
                lanes.append(
                    replace(
                        spec,
                        events=tuple(
                            DecoderEvent(start, end, payload)
                            for start, end, payload in events
                        ),
                    )
                )
            else:
                lanes.append(spec)  # bus groups: states ride member_states
        bearing = replace(
            declaration,
            lanes=tuple(lanes),
            acquired=acquired,
            sample_rate_hz=rate,
            trigger_s=trigger_s,
            cursors=tuple(
                Cursor(position_s=position) for position in cursor_positions
            ),
        )
        return bearing, {name: channel_states[name] for name in member}

    return _source


@contextmanager
def _bearing(
    app_client_factory, project: Path, **overrides: Any
):
    """An ad-hoc data-bearing client; the patch lives exactly as long as the
    context (the process-global patch lesson from the slice build)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            plots,
            "lanes_source",
            _fold_source_factory(overrides.pop("rate", RATE_HZ), **overrides),
        )
        yield app_client_factory(project)


# --- project mutators ----------------------------------------------------------------


def _repin(
    project: Path,
    *,
    descriptor_digest: str,
    catalogue_raw: bytes | None,
    manifest_raw: bytes | None,
) -> None:
    """Re-pin the envelope digests after a post-scaffold mutation."""
    import hashlib
    import json

    package = project / "src" / "example_plugin"
    if catalogue_raw is not None:
        (package / "binding-catalogue.json").write_bytes(catalogue_raw)
    if manifest_raw is not None:
        (package / "ui" / "manifest.json").write_bytes(manifest_raw)
    envelope_path = package / "presentation.json"
    envelope = json.loads(envelope_path.read_text())
    envelope["descriptor_sha256"] = descriptor_digest
    if manifest_raw is not None:
        envelope["manifest"]["sha256"] = hashlib.sha256(manifest_raw).hexdigest()
    envelope_path.write_text(json.dumps(envelope, indent=2) + "\n")


def _readings_plus_lanes_project(tmp_path: Path, builder) -> Path:
    """The row's literal repro fixture: the scaffold starter with its
    ``voltage`` parameter made writable (access/range/hazard/write_policy)
    and the digests re-pinned. The readings page carries the scaffold's own
    time_series plot — the figure the refusal re-render must keep."""
    import hashlib
    import json

    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "f1_plugin"
    create_project(project, "example_plugin")
    create_ui_resources(project, "example_plugin")
    package = project / "src" / "example_plugin"
    descriptor_path = package / "descriptor.json"
    descriptor = json.loads(descriptor_path.read_text())
    parameter = next(
        row for row in descriptor["parameters"] if row["name"] == "voltage"
    )
    parameter["access"] = "rw"
    parameter["range"] = [-10, 10]
    parameter["hazard_class"] = "low"
    parameter["write_policy"] = {
        "effect": "setting",
        "completion": "acknowledged",
        "retry": "never",
    }
    raw = (json.dumps(descriptor, indent=2) + "\n").encode()
    descriptor_path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()

    catalogue_path = package / "binding-catalogue.json"
    catalogue = json.loads(catalogue_path.read_text())
    catalogue["descriptor_sha256"] = digest
    (package / "binding-catalogue.json").write_bytes(
        (json.dumps(catalogue, indent=2) + "\n").encode()
    )

    manifest_path = package / "ui" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["descriptor_sha256"] = digest
    _repin(
        project,
        descriptor_digest=digest,
        catalogue_raw=None,
        manifest_raw=(json.dumps(manifest, indent=2) + "\n").encode(),
    )
    return project


def _slash_target_project(tmp_path: Path, builder) -> Path:
    """The lanes fixture with a schema-legal slash-bearing target id: the
    F10 surface (unquoted ids 404 every toolbar URL)."""
    import json

    project = tmp_path / "f10_plugin"
    builder(project)
    package = project / "src" / "example_plugin"

    catalogue_path = package / "binding-catalogue.json"
    catalogue = json.loads(catalogue_path.read_text())
    catalogue["targets"][0]["id"] = "logic/x"
    _repin(
        project,
        descriptor_digest=catalogue["descriptor_sha256"],
        catalogue_raw=(json.dumps(catalogue, indent=2) + "\n").encode(),
        manifest_raw=None,
    )
    manifest_path = package / "ui" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["bindings"][0]["target_id"] = "logic/x"
    _repin(
        project,
        descriptor_digest=manifest["descriptor_sha256"],
        catalogue_raw=None,
        manifest_raw=(json.dumps(manifest, indent=2) + "\n").encode(),
    )
    return project


def _csrf_via_page(client: TestClient) -> str:
    """The page-delivered CSRF token (rendered into every form)."""
    body = client.get("/devices/example_device").text
    marker = 'hx-headers=\'{"X-CSRF-Token": "'
    return body.split(marker, 1)[1].split('"', 1)[0]


def _viewport_project(tmp_path: Path, builder) -> Path:
    """A plain lanes plugin at a per-call path."""
    project = tmp_path / "fold_plugin"
    builder(project)
    return project


# --- F1: the refusal re-render keeps the figure, never tuple garbage -----------------


def test_f1_stage_refusal_keeps_the_figure_and_never_renders_tuple_garbage(
    tmp_path: Path, lanes_project_builder, app_client_factory
) -> None:
    """F1: ``_render_page`` passed the (scalar, lanes) TUPLE to the template
    and omitted ``lanes`` — a stage/apply refusal rendered escaped tuple-repr
    garbage in the poll region and the plot figure vanished (pre-existing at
    base a3e867e; live at the fold base). Fix: unpack like page_route does.
    The row's repro is the scaffold starter: voltage made writable, a
    non-numeric stage refused, the readings page's own plot figure intact."""
    project = _readings_plus_lanes_project(tmp_path, lanes_project_builder)
    client = app_client_factory(project)
    token = _csrf_via_page(client)
    client.post("/devices/example_device/connect", headers={"x-csrf-token": token})
    response = client.post(
        "/pages/readings/stage",
        data={"voltage": "not-a-number"},
        headers={"x-csrf-token": token},
    )
    assert response.status_code == 200, response.text[:200]
    assert "Stage refused" in response.text, "the refusal renders"
    assert '<figure class="bw-plot"' in response.text, (
        "the page's plot figure survives the refusal re-render"
    )
    assert "Markup(" not in response.text, (
        "no escaped tuple-repr garbage in the served page"
    )


# --- F2: the htmx error channel -------------------------------------------------------


def _free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def fold_browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        yield playwright.chromium.launch()


@pytest.mark.browser
def test_f2_a_refused_viewport_swap_is_announced_not_silent(
    tmp_path_factory: pytest.TempPathFactory,
    lanes_project_builder,
    fold_browser,
) -> None:
    """F2: a stale server-minted window URL 400s and htmx's default response
    handling swaps NOTHING — the button silently no-ops. The host-side
    ``htmx:responseError`` listener renders the refusal into the viewport
    region: the operator sees the refusal, never a dead button. Real server,
    real browser, real 400."""
    import threading
    import time

    import uvicorn

    from benchweave_sdk_server.cli import _build_seam
    from benchweave_sdk_server.security import GuardPolicy, new_token
    from benchweave_sdk_server.web import build_app

    project = tmp_path_factory.mktemp("f2") / "f2_plugin"
    lanes_project_builder(project)
    port = _free_port()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(plots, "lanes_source", _fold_source_factory(RATE_HZ))
        seam, selection = _build_seam(project)
        app = build_app(
            seam,
            policy=GuardPolicy.complete(
                bound_host="127.0.0.1",
                bound_port=port,
                bearer_token=new_token(),
                csrf_token=new_token(),
            ),
            scenario=selection,
        )
        config = uvicorn.Config(
            app, host="127.0.0.1", port=port, log_config=None, lifespan="on"
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        while not server.started:
            time.sleep(0.02)
        page = None
        try:
            page = fold_browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/pages/capture")
            page.evaluate(
                """() => {
                    const button = document.querySelector('.bw-lanes-control');
                    button.setAttribute(
                        'hx-get',
                        '/pages/capture/lanes/logic?from=800&to=300'
                    );
                    window.htmx.process(button);
                }"""
            )
            page.click(".bw-lanes-control")
            notice = page.locator(".bw-lanes-viewport-error")
            notice.wait_for(state="visible", timeout=5000)
            assert "refused" in (notice.text_content() or "").lower()
        finally:
            if page is not None:
                page.close()
            server.should_exit = True
            thread.join(timeout=10)


# --- F3: the served window as structured data -----------------------------------------


def test_f3_the_served_window_is_structured_data(
    tmp_path: Path, lanes_project_builder, app_client_factory
) -> None:
    """F3: the served window rides a structured attribute plus a rewrite
    marker when served differs from requested — assertions parse attributes,
    never prose."""
    with _bearing(
        app_client_factory,
        _viewport_project(tmp_path, lanes_project_builder),
    ) as client:
        windowed = client.get(f"{FOLD_VIEW_URL}?from=-500&to=500").text
        full = client.get(FOLD_VIEW_URL).text
    assert 'data-bw-window="0,499"' in windowed, (
        "the SERVED window (inclusive ends) is machine-readable"
    )
    assert "data-bw-window-clamped" in windowed, (
        "a clamped window announces the rewrite"
    )
    assert 'data-bw-window="0,999"' in full, (
        "the un-windowed figure carries the full span"
    )
    assert "data-bw-window-clamped" not in full, (
        "an unrequested window announces no rewrite"
    )


# --- F4: boundary events render, never drop to awaiting --------------------------------


def test_f4_window_start_boundary_events_render_not_await(
    tmp_path: Path, lanes_project_builder, app_client_factory
) -> None:
    """F4: the drop gate must judge the composer's own (rounded) values with
    the composer's own overlap semantics — a zero-width event AT the window
    start and a sub-sample overlap crossing it render (the composer's
    min-mark / clip), never drop to awaiting."""
    events = ((0.5, 0.5, "ZW"), (0.4999995, 0.5000005, "EDGE"))
    with _bearing(
        app_client_factory,
        _viewport_project(tmp_path, lanes_project_builder),
        rate=RATE_HZ,
        events=events,
    ) as client:
        body = client.get(f"{FOLD_VIEW_URL}?from=500&to=1000").text
    spans = SPAN_ATTRS.findall(body)
    assert len(spans) == 2, f"both boundary events render; got {spans}"
    assert "ZW" in body, "the zero-width point at the window start min-marks"
    assert "EDGE" in body, "the sub-sample overlap renders clipped"


# --- F5: sample-domain rebase, exact at any rate -----------------------------------------


@pytest.mark.parametrize("rate", [1e8, 2e9, 1e10])
def test_f5_markers_rebase_exactly_at_high_rates(
    tmp_path: Path, lanes_project_builder, app_client_factory, rate: float
) -> None:
    """F5: rebasing happens in the SAMPLE domain — the composer's
    seconds→samples round-trip recovers exact integers at any rate; no
    seconds-domain rounding quantizes sub-nanosecond positions away."""
    trigger = (500 + 1) / rate
    cursors = ((500 + 2) / rate, (500 + 5) / rate)
    with _bearing(
        app_client_factory,
        _viewport_project(tmp_path, lanes_project_builder),
        rate=rate,
        trigger_s=trigger,
        cursor_positions=cursors,
    ) as client:
        body = client.get(f"{FOLD_VIEW_URL}?from=500&to=1000").text
    assert TRIGGER_ATTR.search(body).group(1) == "1", body[-600:]
    assert sorted(CURSOR_ATTR.findall(body)) == ["2", "5"], body[-600:]


# --- F6: no-rate markers drop in BOTH views ------------------------------------------------


def test_f6_a_rateless_declaration_carries_no_position_markers(
    tmp_path: Path, lanes_project_builder, app_client_factory
) -> None:
    """F6: without a rate the composer launders every seconds position to
    sample 0 — the host omits trigger/cursors from the declaration, so BOTH
    views agree on no markers (no laundering, no disagreement)."""
    with _bearing(
        app_client_factory,
        _viewport_project(tmp_path, lanes_project_builder),
        rate=None,
    ) as client:
        full = client.get(FOLD_VIEW_URL).text
        windowed = client.get(f"{FOLD_VIEW_URL}?from=500&to=1000").text
    assert TRIGGER_ATTR.search(full) is None, (
        "the full view must not launder the trigger to sample 0"
    )
    assert CURSOR_ATTR.search(full) is None
    assert TRIGGER_ATTR.search(windowed) is None
    assert CURSOR_ATTR.search(windowed) is None


# --- F7: non-positive rates refuse typed, never a 500 ---------------------------------------


def test_f7_a_non_positive_rate_refuses_typed_not_500(
    tmp_path: Path, lanes_project_builder, app_client_factory
) -> None:
    """F7: rate 0.0 drove the composer to ZeroDivisionError (a 500). The
    host refuses it typed, loud, before any compose."""
    with _bearing(
        app_client_factory,
        _viewport_project(tmp_path, lanes_project_builder),
        rate=0.0,
    ) as client:
        response = client.get(f"{FOLD_VIEW_URL}?from=0&to=500")
    assert response.status_code == 400
    assert response.text.startswith("viewport_rate_refused:"), response.text


# --- F8: the states-length invariant refuses, never launders ---------------------------------


def test_f8_states_shorter_than_acquired_refuse(
    tmp_path: Path, lanes_project_builder, app_client_factory
) -> None:
    """F8: a declaration claiming 1000 acquired samples with 700 states
    would silently re-grid — the windower refuses the invariant breach, never
    launders it."""
    with _bearing(
        app_client_factory,
        _viewport_project(tmp_path, lanes_project_builder),
        acquired=1000,
        states_length=700,
    ) as client:
        response = client.get(f"{FOLD_VIEW_URL}?from=0&to=500")
    assert response.status_code == 400
    assert response.text.startswith("viewport_invariant_refused:"), response.text


# --- F10: slash-bearing view ids reach the route -----------------------------------------------


def test_f10_a_slash_bearing_view_id_resolves_from_the_toolbar(
    tmp_path: Path, lanes_project_builder, app_client_factory
) -> None:
    """F10: schema-legal ids may contain ``/`` — the single-segment route
    never matches an unquoted id, so every toolbar URL 404s. Ids enter URLs
    percent-encoded (``safe=''``), and the route decodes back."""
    project = _slash_target_project(tmp_path, lanes_project_builder)

    # Unit arm: the controls builder percent-encodes the id.
    controls = plots.lanes_viewport_controls("capture", "logic/x", 500, 1000, 1000)
    assert any("%2F" in control["url"] for control in controls), controls

    # Route arm: with a data-bearing source (a toolbar renders), the
    # quoted toolbar URL resolves end to end.
    with _bearing(app_client_factory, project) as client:
        body = client.get("/pages/capture").text
        urls = re.findall(r'hx-get="(/pages/capture/lanes/[^"]*)"', body)
        assert urls, "the toolbar carries navigable URLs for the slash view"
        for raw_url in urls:
            response = client.get(html.unescape(raw_url))
            assert response.status_code == 200, (raw_url, response.text[:120])
        direct = client.get("/pages/capture/lanes/logic%2Fx?from=0&to=100")
        assert direct.status_code == 200, direct.text[:120]
