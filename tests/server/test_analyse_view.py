"""I4a §1.4: the Analyse view and the report download route.

The view composes existing surfaces: the picker over the landed I3c
``capture_list`` rows (published waveform captures), the plot through the
shared wrapper's markup + the vendored hydrator, statistics through
``analysis`` (definition ``benchweave-analysis/1``, denominators stated),
the export through the ``report_export`` catalogue row (CSRF-guarded POST
per NFR-S3 — the middleware's job), and the download from the capture
root under a report-specific, script-free CSP (``script-src 'none'``;
the style axis is deliberately looser — ``style-src 'unsafe-inline'`` —
because a self-contained document has no external sheet).
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.web import build_app

TEST_HOST = "127.0.0.1"
TEST_PORT = 8477


def write_capture(
    root: Path,
    capture_id: str,
    *,
    values: tuple[float, ...],
    unit: str = "V",
    interval: float = 0.001,
) -> Path:
    payload = b"".join(struct.pack("<d", value) for value in values)
    event = root / capture_id
    event.mkdir(parents=True)
    (event / f"{capture_id}.f64").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (event / "manifest.json").write_text(
        json.dumps(
            {
                "capture_id": capture_id,
                "format": "waveform_f64le",
                "artifact_id": "art-" + digest,
                "byte_length": len(payload),
                "sha256": digest,
                "started_at": f"2026-10-07T12:00:00+00:00-{capture_id}",
                "sample_count": len(values),
                "sample_interval_s": interval,
                "unit": unit,
                "x-standalone-state": "finalised",
                "x-standalone-manifest-version": 1,
            },
            sort_keys=True,
        )
    )
    (event / "metadata.json").write_text(
        json.dumps(
            {
                "capture_id": capture_id,
                "device": {"id": "fx-device", "firmware": "1.0.0"},
                "plugin": {"package": "fx-plugin", "version": "0.1.0",
                           "descriptor_sha256": "c" * 64},
                "surface": "ui",
                "operator": "fx-op",
                "tags": [],
                "notes": "",
            },
            sort_keys=True,
        )
    )
    return event


@pytest.fixture()
def capture_root(tmp_path: Path) -> Path:
    return tmp_path / "captures"


@pytest.fixture()
def client(plugin, capture_root: Path) -> TestClient:
    from benchweave_sdk_server.session import mock_plugin_session

    seam = StandaloneSeam(
        mock_plugin_session(plugin),
        transport_kind="mock",
        capture_root=capture_root,
    )
    app = build_app(
        seam,
        policy=GuardPolicy.complete(
            bound_host=TEST_HOST,
            bound_port=TEST_PORT,
            bearer_token=new_token(),
            csrf_token=new_token(),
            operator_action_token=new_token(),
        ),
    )
    entered = TestClient(app, base_url=f"http://{TEST_HOST}:{TEST_PORT}")
    with entered:
        yield entered


def csrf_of(client: TestClient) -> str:
    page = client.get("/analyse").text
    match = re.search(r'"X-CSRF-Token":\s*"([^"]+)"', page)
    assert match is not None, "the page must render the CSRF token"
    return match.group(1)


def test_picker_lists_published_waveform_captures(
    client: TestClient, capture_root: Path
) -> None:
    write_capture(capture_root, "fx-pick-a", values=(1.0, 2.0))
    write_capture(capture_root, "fx-pick-b", values=(3.0,))
    page = client.get("/analyse").text
    assert "fx-pick-a" in page and "fx-pick-b" in page
    assert 'name="capture"' in page
    assert 'name="lo"' in page and 'name="hi"' in page


def test_get_with_selection_renders_stats_inline(
    client: TestClient, capture_root: Path
) -> None:
    write_capture(capture_root, "fx-inline", values=(1.0, 2.0, 3.0))
    page = client.get("/analyse", params={"capture": "fx-inline"}).text
    assert "fx-inline" in page
    assert "host-computed" in page
    assert "benchweave-analysis/1" in page
    assert "count 3" in page


def test_stats_partial_answers_htmx_post(
    client: TestClient, capture_root: Path
) -> None:
    write_capture(capture_root, "fx-partial", values=(2.0, 4.0))
    token = csrf_of(client)
    response = client.post(
        "/analyse/stats",
        data={"capture": "fx-partial", "lo": "", "hi": ""},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    assert "host-computed" in response.text
    assert "count 2" in response.text


def test_stats_post_without_csrf_refuses(client: TestClient) -> None:
    response = client.post("/analyse/stats", data={"capture": "fx-any"})
    assert response.status_code == 403
    assert response.json()["error"] == "standalone_csrf_required"


def test_export_redirects_to_the_download(
    client: TestClient, capture_root: Path
) -> None:
    write_capture(capture_root, "fx-export", values=(1.0, 5.0, 1.0))
    token = csrf_of(client)
    response = client.post(
        "/analyse/export",
        data={"capture": "fx-export", "lo": "", "hi": ""},
        headers={"X-CSRF-Token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert re.fullmatch(r"/reports/rep-[0-9a-f]{16}", location)
    downloaded = client.get(location)
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("text/html")
    # The report-specific CSP: no script can run in a report document.
    csp = downloaded.headers["content-security-policy"]
    assert "script-src 'none'" in csp
    assert "style-src 'unsafe-inline'" in csp
    assert "fx-export" in downloaded.text
    # The default host CSP still governs ordinary pages (the guard was
    # tightened for reports, not weakened for everything).
    index = client.get("/")
    assert "script-src 'self'" in index.headers["content-security-policy"]


def test_download_refuses_malformed_and_unknown_ids(client: TestClient) -> None:
    for bad in (
        "/reports/../library.sqlite3",
        "/reports/not-a-report-id",
        "/reports/rep-zzzzzzzzzzzzzzzz",
    ):
        response = client.get(bad, follow_redirects=False)
        assert response.status_code == 404, bad


def test_export_refusal_renders_the_refusal(
    client: TestClient, capture_root: Path
) -> None:
    """The render-the-refusal idiom: a refused export answers with the
    code and message on the page, never a silent redirect."""
    write_capture(capture_root, "fx-there", values=(1.0,))
    token = csrf_of(client)
    page = client.post(
        "/analyse/export",
        data={"capture": ["fx-there", "fx-not-there"], "lo": "", "hi": ""},
        headers={"X-CSRF-Token": token},
    )
    assert page.status_code == 404
    assert "fx-not-there" in page.text


def test_analyse_js_is_served_under_the_inventory(client: TestClient) -> None:
    response = client.get("/assets/analyse.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    script = response.text
    # The brush is page-scoped and talks only to the wrapper's own
    # conventions plus the vendored uPlot's real hook/scale surface
    # (B-F1): no plugin knowledge, no fetch targets beyond the host.
    assert "_bwPlot" in script
    assert "setScale" in script


# --- fold wave 1: view admission, escaping, and the CSP pin (rows 2, 3, 8) ---------


def test_the_view_refuses_ids_outside_the_capture_root(
    client: TestClient, capture_root: Path
) -> None:
    """Row 2a: the Analyse view runs its ids through the SAME admission
    as the export — a traversal-shaped id that names a manifest outside
    the capture root refuses, never analyses it (the lane's repro:
    GET /analyse?capture=../x answered 200 with stats while the export
    of the same id refused)."""
    write_capture(capture_root.parent, "evil", values=(1.0, 2.0))
    page = client.get("/analyse", params={"capture": "../evil"}).text
    assert 'class="bw-stats"' not in page, "no stats table may render"
    assert "no published capture" in page


def test_unindexed_in_root_dir_refuses_in_view_and_export(
    client: TestClient, capture_root: Path
) -> None:
    """Row 2b: a capture directory written to disk AFTER the library
    constructed its index analyses in neither surface — the view and the
    export share one admission gate."""
    write_capture(capture_root, "fx-before", values=(1.0,))
    client.get("/analyse")  # constructs the library over the current root
    write_capture(capture_root, "fx-after", values=(2.0,))  # unindexed
    page = client.get("/analyse", params={"capture": "fx-after"}).text
    assert 'class="bw-stats"' not in page, "no stats table may render"
    assert "no published capture" in page
    token = csrf_of(client)
    export = client.post(
        "/analyse/export",
        data={"capture": "fx-after", "lo": "", "hi": ""},
        headers={"X-CSRF-Token": token},
    )
    assert export.status_code == 404
    assert "no published capture: fx-after" in export.text


def test_the_figure_escapes_a_double_quoted_capture_id_at_render() -> None:
    """Row 3 (direct render, wave 3's portability shape): the full
    double-quote attribute-breakout payload is proven at the RENDER SEAM
    — ``_figure_entry`` driven directly with the hostile id string, no
    on-disk directory (double quotes are illegal in Windows path
    components, so a fixture directory carrying them dies with WinError
    123 before any assertion; the CI windows lane redded there)."""
    from benchweave_sdk_server.analysis import region_stats
    from benchweave_sdk_server.web import _figure_entry

    hostile = 'fx-break" onmouseover="alert(1)'
    stats = region_stats([(0.0, 1.0), (0.001, 2.0)], lo=None, hi=None)
    figure = _figure_entry(
        {
            "capture_id": hostile,
            "unit": "V",
            "stats": stats,
            "points": [(0.0, 1.0), (0.001, 2.0)],
            "sha256": "a" * 64,
        }
    )["figure"]
    assert 'onmouseover="alert(1)' not in figure
    assert "&#34;" in figure or "&quot;" in figure


def test_the_figure_escapes_a_hostile_but_windows_legal_id_end_to_end(
    client: TestClient, capture_root: Path
) -> None:
    """Row 3's end-to-end arm, portable: single quotes are the one
    attribute-payload class legal in a Windows path component, so the
    on-disk fixture carries them — the full view path (picker, figure,
    stats tables) must render the hostile-but-legal name defanged."""
    hostile = "fx-break' onmouseover='alert(1)"
    write_capture(capture_root, hostile, values=(1.0, 2.0))
    page = client.get("/analyse", params={"capture": hostile}).text
    # The raw name survives ONLY inside the inert application/json data
    # block (plain JSON content — the parser ends the element at
    # </script, never at a quote); the attribute slots must carry the
    # escaped form.
    assert 'data-bw-plot-slug="analyse-fx-break\' ' not in page
    assert "&#39;" in page
    assert 'class="bw-stats"' in page


def test_figure_json_block_never_carries_a_raw_script_closer(
    client: TestClient, capture_root: Path
) -> None:
    """Row 3's element-breakout class, disposition: STRUCTURALLY
    UNREACHABLE, asserted as such. A ``</script>`` closer always contains
    a slash, and a slash can never appear in a capture id that maps to a
    real event directory (the id IS one path segment) — and a form-carried
    id with a slash refuses at load before any render. The arm pins the
    refusal so the unreachability is enforced, not assumed."""
    hostile = "fx-</script>-x"
    page = client.get("/analyse", params={"capture": hostile}).text
    assert 'class="bw-stats"' not in page, "no stats table may render"
    assert "no published capture" in page


def test_guard_preserves_a_route_set_csp_verbatim(plugin, capture_root: Path) -> None:
    """Row 8's pin (the reworded claim): the guard preserves a route-set
    CSP VERBATIM and does not police its directives — a route setting a
    looser CSP than the default survives (disclosed residual: every route
    is this repository's own code; directive policing is review's job,
    not the guard's — and the report route's stricter policy is pinned in
    test_export_redirects_to_the_download). This test pins the actual
    mechanism the report route relies on, replacing the refuted
    'may tighten, never loosen' claim."""
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    from benchweave_sdk_server.security import GuardPolicy, install_guards

    app = FastAPI()

    @app.get("/route-csp", response_class=HTMLResponse)
    async def route_csp() -> HTMLResponse:
        response = HTMLResponse("<html></html>")
        response.headers["Content-Security-Policy"] = (
            "default-src *; script-src *; style-src *"
        )
        return response

    install_guards(
        app,
        GuardPolicy.complete(
            bound_host=TEST_HOST,
            bound_port=TEST_PORT,
            bearer_token="t",
            csrf_token="t",
        ),
    )
    with TestClient(app, base_url=f"http://{TEST_HOST}:{TEST_PORT}") as c:
        preserved = c.get("/route-csp")
        assert preserved.headers["content-security-policy"] == (
            "default-src *; script-src *; style-src *"
        )


# --- fold wave 2 (lane B): hostile units, non-finite windows, the live brush --------


def test_hostile_unit_renders_escaped_in_the_figure(
    client: TestClient, capture_root: Path
) -> None:
    """B-F2: the figure block is built inside Markup(...) (autoescape
    bypass) — every interpolated slot must escape by hand. A hostile unit
    that would break out of data-bw-axes and inject markup renders
    escaped, exactly as the report renderer already treats it."""
    hostile = 'V" onload="alert(1)" data-evil="1"><script>alert(2)</script>'
    write_capture(capture_root, "fx-evilunit", values=(1.0, 2.0), unit=hostile)
    page = client.get("/analyse", params={"capture": "fx-evilunit"}).text
    assert 'onload="alert(1)' not in page
    assert "<script>alert(2)" not in page
    assert "&#34;" in page or "&quot;" in page


def test_non_finite_window_refuses_on_the_web_surface(
    client: TestClient, capture_root: Path
) -> None:
    """B-F4 (web arm): NaN/Infinity window bounds — parseable as floats
    from the form text — refuse at admission, never reach the pin loop or
    the sidecar."""
    write_capture(capture_root, "fx-finite", values=(1.0, 2.0))
    token = csrf_of(client)
    for bad in ("nan", "inf", "-inf"):
        response = client.post(
            "/analyse/export",
            data={"capture": "fx-finite", "lo": bad, "hi": ""},
            headers={"X-CSRF-Token": token},
        )
        assert response.status_code == 400, bad
        assert "standalone_report_window_invalid" in response.text
        assert "finite" in response.text


def test_the_brush_talks_to_the_real_vendored_uplot_api() -> None:
    """B-F1 (static arm): every uPlot API token the brush uses exists in
    the VENDORED bytes — the dead-code defect was analyse.js reading
    ``plot.sel``, a property these bytes never expose."""
    from benchweave_sdk_server.assets import ui_assets_root

    script = (ui_assets_root() / "analyse.js").read_text(encoding="utf-8")
    vendored = (ui_assets_root() / "uplot.min.js").read_text(encoding="utf-8")
    for token in ("hooks", "scales", "setScale"):
        assert token in script, f"the brush must use the {token} API"
        assert token in vendored, f"the vendored bytes do not expose {token}"
    import re as _re

    assert not _re.search(r"plot\.sel\b", script), (
        "plot.sel does not exist in the vendored bytes (B-F1's dead token)"
    )


def test_the_brush_handles_the_real_event_sequence(tmp_path: Path) -> None:
    """B-F1 (handler arm): analyse.js driven under node against a shim
    exposing the VENDORED API surface — mousedown arms, the drag-completion
    setScale hook fires with the zoomed x extent, the window inputs fill
    and the form submits. A resize-driven setScale while disarmed must NOT
    submit. Skipped visibly where node is absent (the static arm still
    holds the surface check)."""
    import shutil
    import subprocess

    from benchweave_sdk_server.assets import ui_assets_root

    if shutil.which("node") is None:
        pytest.skip("node is not available to drive the brush handler")
    harness = tmp_path / "harness.mjs"
    harness.write_text(NODE_HARNESS)
    script = ui_assets_root() / "analyse.js"
    result = subprocess.run(
        ["node", str(harness), str(script)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["lo"] == "2.5" and payload["hi"] == "7.5"
    assert payload["submitted"] is True
    assert payload["resize_submits"] is False


NODE_HARNESS = """
import { readFileSync } from "node:fs";

const script = readFileSync(process.argv[2], "utf8");
const listeners = {};
const form = {
  elements: { lo: { value: "" }, hi: { value: "" } },
  submitted: 0,
  requestSubmit() { this.submitted += 1; },
};
const canvas = {
  addEventListener(type, cb) { (listeners[type] = listeners[type] || []).push(cb); },
};
const plot = {
  hooks: {},
  scales: { x: { min: 0, max: 9.99 } },
};
const host = {
  _bwPlot: plot,
  dataset: {},
  querySelector(selector) { return selector === ".bw-plot__canvas" ? canvas : null; },
};
globalThis.document = {
  readyState: "complete",
  addEventListener() {},
  getElementById(id) { return id === "analyse-form" ? form : null; },
  querySelectorAll() { return [host]; },
  body: { addEventListener() {} },
};

eval(script);

function fire(type) { (listeners[type] || []).forEach((cb) => cb()); }
function fireSetScale(min, max) {
  plot.scales.x = { min, max };
  (plot.hooks.setScale || []).forEach((cb) => cb("x"));
}

// A resize while disarmed must not submit (init/resize also fire setScale).
fireSetScale(1.0, 2.0);
const resizeSubmits = form.submitted;

// The real drag sequence: mousedown (arm) -> drag end: uPlot's own mouseup
// zooms and fires setScale synchronously -> the event bubbles to the
// container mouseup afterwards.
fire("mousedown");
fireSetScale(2.5, 7.5);
fire("mouseup");

console.log(
  JSON.stringify({
    lo: form.elements.lo.value,
    hi: form.elements.hi.value,
    submitted: form.submitted > resizeSubmits,
    resize_submits: resizeSubmits > 0,
  })
);
"""


# --- I4b.1 AR-8: the marker editor and click-to-place ------------------------------


def test_marker_editor_renders_for_a_single_capture_selection(
    client: TestClient, capture_root: Path
) -> None:
    write_capture(capture_root, "fx-mark-one", values=(1.0, 2.0, 3.0))
    write_capture(capture_root, "fx-mark-two", values=(4.0,))
    single = client.get("/analyse", params={"capture": "fx-mark-one"}).text
    assert 'id="marker-fieldset"' in single
    assert 'name="marker_label"' in single
    assert 'formaction="/analyse/markers"' in single
    # The editor is per-capture: a multi-capture selection renders the
    # hint, not the fieldset (the I4b.1 single-series cut).
    both = client.get(
        "/analyse", params={"capture": ["fx-mark-one", "fx-mark-two"]}
    ).text
    assert 'id="marker-fieldset"' not in both
    assert "one capture at a time" in both


def test_marker_save_round_trips_through_the_page_route(
    client: TestClient, capture_root: Path
) -> None:
    write_capture(capture_root, "fx-mark-save", values=(1.0, 2.0, 3.0))
    token = csrf_of(client)
    response = client.post(
        "/analyse/markers",
        data={
            "capture": "fx-mark-save",
            "lo": "",
            "hi": "",
            "marker_label": ["A", "B"],
            "marker_t": ["0.0", "0.001"],
            "marker_note": ["first", "second"],
        },
        headers={"X-CSRF-Token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/analyse?capture=fx-mark-save"
    import json as _json

    overlay = _json.loads(
        (capture_root / "fx-mark-save" / "analysis.json").read_text()
    )
    assert overlay["format"] == "standalone-analysis/1"
    assert overlay["markers"] == [
        {"label": "A", "t": 0.0, "note": "first"},
        {"label": "B", "t": 0.001, "note": "second"},
    ]
    # The re-rendered view prefills the editor from the stored overlay.
    page = client.get("/analyse", params={"capture": "fx-mark-save"}).text
    assert 'value="A"' in page and 'value="first"' in page


def test_marker_save_refusal_renders_the_refusal(
    client: TestClient, capture_root: Path
) -> None:
    write_capture(capture_root, "fx-mark-bad", values=(1.0, 2.0, 3.0))
    token = csrf_of(client)
    page = client.post(
        "/analyse/markers",
        data={
            "capture": "fx-mark-bad",
            "marker_label": ["AA"],
            "marker_t": ["0.0"],
            "marker_note": [""],
        },
        headers={"X-CSRF-Token": token},
    )
    assert page.status_code == 400
    assert "standalone_report_marker_invalid" in page.text


def test_marker_rows_ride_the_stats_post_as_form_state(
    client: TestClient, capture_root: Path
) -> None:
    """The htmx stats POST carries the editor's unsaved rows: the swapped
    partial echoes them into the export form's hidden fields, so unsaved
    markers flow into the export (the design's form-state rule)."""
    write_capture(capture_root, "fx-mark-state", values=(1.0, 2.0))
    token = csrf_of(client)
    partial = client.post(
        "/analyse/stats",
        data={
            "capture": "fx-mark-state",
            "lo": "",
            "hi": "",
            "marker_label": ["A"],
            "marker_t": ["0.0"],
            "marker_note": ["unsaved"],
        },
        headers={"X-CSRF-Token": token},
    )
    assert partial.status_code == 200
    assert 'name="marker_capture" value="fx-mark-state"' in partial.text
    assert 'name="marker_label" value="A"' in partial.text
    assert 'name="marker_note" value="unsaved"' in partial.text


def test_click_to_place_talks_to_the_real_vendored_uplot_api() -> None:
    """The placement arm's static half (B-F1's discipline): every uPlot
    API token the click-to-place uses exists in the VENDORED bytes, and
    the numeric fields remain the complete no-script path."""
    from benchweave_sdk_server.assets import ui_assets_root

    script = (ui_assets_root() / "analyse.js").read_text(encoding="utf-8")
    vendored = (ui_assets_root() / "uplot.min.js").read_text(encoding="utf-8")
    for token in ("posToVal", "setScale"):
        assert token in script, f"the placement must use the {token} API"
        assert token in vendored, f"the vendored bytes do not expose {token}"
    assert "bw-marker-t" in script


# --- the refute fold (I4b.1): A-F5, B-reflected, B-303, B-F2, B-F3 -----------------


def test_a_f5_unparseable_marker_rows_refuse_on_export_too(
    client: TestClient, capture_root: Path
) -> None:
    """A-F5: the export route silently DROPPED unparseable marker rows
    while the save route 400ed the same input — the operator's unsaved
    edits vanished from the report while stored overlay markers rendered.
    Both routes now refuse with the same diagnostic family."""
    write_capture(capture_root, "fx-drop-row", values=(1.0, 2.0))
    token = csrf_of(client)
    response = client.post(
        "/analyse/export",
        data={
            "capture": "fx-drop-row",
            "lo": "",
            "hi": "",
            "marker_capture": "fx-drop-row",
            "marker_label": ["A"],
            "marker_t": ["not-a-number"],
            "marker_note": ["x"],
        },
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 400
    assert "marker t must be a number" in response.text


def test_b_reflected_marker_refusal_pages_escape_their_operands(
    client: TestClient, capture_root: Path
) -> None:
    """B-reflected: the marker refusal pages interpolated label/row text
    raw into the 400 body. Every interpolated operand now escapes (the
    analyse view's established discipline) — CSP/CSRF contained it, the
    page must not reflect it."""
    write_capture(capture_root, "fx-reflect", values=(1.0, 2.0))
    token = csrf_of(client)
    hostile = "<img src=x onerror=alert(1)>"
    page = client.post(
        "/analyse/markers",
        data={
            "capture": "fx-reflect",
            "marker_label": [hostile],
            "marker_t": ["0.0"],
            "marker_note": [""],
        },
        headers={"X-CSRF-Token": token},
    )
    assert page.status_code == 400
    assert "<img" not in page.text
    assert "&lt;img" in page.text


def test_b_303_save_redirect_url_encodes_its_params(
    client: TestClient, capture_root: Path
) -> None:
    """B-303: an unencoded & in lo_text injected query parameters into
    the post-save Location. The redirect's params are URL-encoded."""
    write_capture(capture_root, "fx-redirect", values=(1.0, 2.0, 3.0))
    token = csrf_of(client)
    response = client.post(
        "/analyse/markers",
        data={
            "capture": "fx-redirect",
            "lo": "0&evil=1",
            "hi": "",
            "marker_label": ["A"],
            "marker_t": ["0.0"],
            "marker_note": [""],
        },
        headers={"X-CSRF-Token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert "&evil=1" not in location, f"the & must not be a separator: {location}"
    assert "%26" in location, f"the & must be percent-encoded: {location}"


def test_b_f2_and_b_f3_the_driven_placement_sequence(tmp_path: Path) -> None:
    """B-F2 + B-F3 driven (the brush harness's discipline): a click on
    the axis gutter (event.offsetX is target-relative, and the .u-axis
    div poisons the over-div convention posToVal expects) fills NOTHING;
    a click inside the over-div places the selected row's t; and the
    export form's hidden fields then carry the placed marker — the
    visible editor and the export form are never independent copies."""
    import shutil
    import subprocess

    from benchweave_sdk_server.assets import ui_assets_root

    if shutil.which("node") is None:
        pytest.skip("node is not available to drive the placement handler")
    harness = tmp_path / "placement.mjs"
    harness.write_text(PLACEMENT_HARNESS)
    script = ui_assets_root() / "analyse.js"
    result = subprocess.run(
        ["node", str(harness), str(script)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["axis_click_filled"] == "", (
        "a click on the axis gutter must never place a marker"
    )
    assert payload["placed"] == "3.75", payload
    assert payload["export_carries"] == "3.75", (
        "the export form must mirror the placed marker at submit time"
    )


PLACEMENT_HARNESS = """
import { readFileSync } from "node:fs";

const script = readFileSync(process.argv[2], "utf8");

const tInput = { value: "" };
const labelInput = { value: "A" };
const noteInput = { value: "" };
const row = {
  isConnected: true,
  querySelector(selector) {
    if (selector === ".bw-marker-t") return tInput;
    if (selector === "input[name='marker_label']") return labelInput;
    return noteInput;
  },
};
const fieldset = {
  querySelectorAll(selector) {
    return selector === ".bw-marker-row" ? [row] : [];
  },
  getAttribute(name) {
    return name === "data-bw-marker-capture" ? "fx-cap" : null;
  },
};

const exportForm = {
  id: "export-form",
  hidden: [
    { name: "marker_capture", value: "fx-cap" },
    { name: "marker_label", value: "" },
    { name: "marker_t", value: "" },
    { name: "marker_note", value: "" },
  ],
  addEventListener() {},
  querySelectorAll(selector) {
    const names = [];
    if (selector.indexOf("marker_label") >= 0) names.push("marker_label");
    if (selector.indexOf("marker_t") >= 0) names.push("marker_t");
    if (selector.indexOf("marker_note") >= 0) names.push("marker_note");
    if (selector.indexOf("marker_capture") >= 0) names.push("marker_capture");
    return this.hidden.filter((node) => names.indexOf(node.name) >= 0);
  },
  appendChild(node) {
    node.parentNode = this;
    this.hidden.push(node);
    return node;
  },
  removeChild(node) {
    this.hidden = this.hidden.filter((entry) => entry !== node);
    return node;
  },
};
exportForm.hidden.forEach((node) => { node.parentNode = exportForm; });

const form = {
  id: "analyse-form",
  elements: { lo: { value: "" }, hi: { value: "" } },
  requestSubmit() {},
  submit() {},
  querySelectorAll(selector) {
    return selector === ".bw-marker-row" ? [row] : [];
  },
};

const over = { closest: (selector) => (selector === ".u-over" ? over : null) };
const canvasEl = {
  _l: {},
  closest: (selector) => (selector === ".u-over" ? over : null),
  addEventListener(type, cb) {
    (this._l[type] = this._l[type] || []).push(cb);
  },
  querySelector(selector) {
    return selector === ".u-over" ? over : null;
  },
};
const axisTick = { closest: () => null }; /* inside .u-axis, NOT .u-over */
const plot = {
  hooks: {},
  scales: { x: { min: 0, max: 9.99 } },
  posToVal(left) {
    return (left / 400) * 5; /* a stable fake pixel -> value map */
  },
};
const host = {
  _bwPlot: plot,
  dataset: {},
  querySelector(selector) {
    return selector === ".bw-plot__canvas" ? canvasEl : null;
  },
};

const documentListeners = {};
globalThis.document = {
  readyState: "complete",
  addEventListener(type, cb) {
    (documentListeners[type] = documentListeners[type] || []).push(cb);
  },
  getElementById(id) {
    if (id === "analyse-form") return form;
    if (id === "marker-fieldset") return fieldset;
    if (id === "export-form") return exportForm;
    return null;
  },
  querySelectorAll() {
    return [host];
  },
  createElement() {
    return { type: "", name: "", value: "" };
  },
  body: { addEventListener() {} },
};

eval(script);

function fire(type, event) {
  (canvasEl._l[type] || []).forEach((cb) => cb(event));
}
function fireDocument(type, event) {
  (documentListeners[type] || []).forEach((cb) => cb(event));
}

// Focus the marker row so the placement knows its target.
fireDocument("focusin", { target: { closest: () => row } });

// A click on the AXIS GUTTER must fill nothing (B-F2).
fire("mousedown", { offsetX: 50, target: axisTick });
fire("click", { offsetX: 50, target: axisTick });
const axisClickFilled = tInput.value;

// A click inside the over-div places the selected row's t (300px -> 3.75).
fire("mousedown", { offsetX: 300, target: canvasEl });
fire("click", { offsetX: 300, target: canvasEl });
const placed = tInput.value;

// The export form mirrors the placed marker at submit time (B-F3).
fireDocument("submit", { target: exportForm });
const exportCarries = exportForm.hidden
  .filter((node) => node.name === "marker_t")
  .map((node) => node.value)
  .join(",");

console.log(
  JSON.stringify({ axis_click_filled: axisClickFilled, placed, export_carries: exportCarries })
);
"""


# --- I4b.2: the Analyse view's power mode surface (the record §1.4/§1.6) ------------


def _write_power_pair(root: Path) -> None:
    write_capture(
        root, "fx-view-v", values=(2.0,) * 360, interval=0.01, unit="V"
    )
    write_capture(
        root, "fx-view-i", values=(3.0,) * 360, interval=0.01, unit="A"
    )


def test_analyse_page_offers_the_power_mode_fields(
    client: TestClient, capture_root: Path
) -> None:
    _write_power_pair(capture_root)
    page = client.get("/analyse").text
    assert 'name="power_mode"' in page
    for mode in ("battery", "dc-dc", "sleep", "load-step"):
        assert f'>{mode}<' in page
    assert 'name="capacity_ah"' in page and 'name="threshold"' in page


def test_stats_partial_renders_the_power_block(
    client: TestClient, capture_root: Path
) -> None:
    _write_power_pair(capture_root)
    token = csrf_of(client)
    response = client.post(
        "/analyse/stats",
        data={
            "capture": ["fx-view-v", "fx-view-i"],
            "power_mode": "battery",
            "capacity_ah": "12",
        },
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    assert "benchweave-power/1" in response.text
    assert "host-computed" in response.text
    assert "runtime (h)" in response.text and ">4<" in response.text
    # The export form carries the power fields through the swap.
    assert 'name="power_mode" value="battery"' in response.text


def test_sleep_not_evaluated_renders_on_the_view(
    client: TestClient, capture_root: Path
) -> None:
    _write_power_pair(capture_root)
    token = csrf_of(client)
    response = client.post(
        "/analyse/stats",
        data={"capture": ["fx-view-v", "fx-view-i"], "power_mode": "sleep"},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    assert "not_evaluated" in response.text and "no threshold" in response.text


def test_unparseable_power_number_renders_the_refusal(
    client: TestClient, capture_root: Path
) -> None:
    """An unparseable power number follows the WINDOW idiom on the stats
    partial (the refused notice renders in the page) and the marker
    idiom on the export route (a 400 page, never a silent drop)."""
    _write_power_pair(capture_root)
    token = csrf_of(client)
    # The full page renders the refused notice (the swapped partial keeps
    # its I4a shape: "No results — the selection refused").
    response = client.get(
        "/analyse",
        params=[
            ("capture", "fx-view-v"),
            ("capture", "fx-view-i"),
            ("power_mode", "battery"),
            ("capacity_ah", "twelve"),
        ],
    )
    assert response.status_code == 200
    assert "Refused" in response.text
    assert "standalone_report_power_param" in response.text
    export = client.post(
        "/analyse/export",
        data={
            "capture": ["fx-view-v", "fx-view-i"],
            "power_mode": "battery",
            "capacity_ah": "twelve",
        },
        headers={"X-CSRF-Token": token},
    )
    assert export.status_code == 400
    assert "standalone_report_power_param" in export.text


def test_export_carries_the_power_params(
    client: TestClient, capture_root: Path
) -> None:
    """The export POST forwards the view's power fields; the rendered
    report carries the power section (the two surfaces share the one
    computation)."""
    _write_power_pair(capture_root)
    token = csrf_of(client)
    response = client.post(
        "/analyse/export",
        data={
            "capture": ["fx-view-v", "fx-view-i"],
            "power_mode": "load-step",
        },
        headers={"X-CSRF-Token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    report = client.get(response.headers["Location"])
    assert "benchweave-power/1" in report.text
    assert "R (Ω)" in report.text
