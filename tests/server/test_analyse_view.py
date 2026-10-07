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
    root: Path, capture_id: str, *, values: tuple[float, ...], unit: str = "V"
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
                "sample_interval_s": 0.001,
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


def test_the_figure_markup_escapes_the_capture_id(
    client: TestClient, capture_root: Path
) -> None:
    """Row 3: the figure's attribute slots escape the capture id exactly
    like the title two lines up — an event directory whose name carries
    attribute-breakout bytes (hand-mangled on disk; the writer's own ids
    are allowlisted) renders defanged."""
    hostile = 'fx-break" onmouseover="alert(1)'
    write_capture(capture_root, hostile, values=(1.0, 2.0))
    page = client.get("/analyse", params={"capture": hostile}).text
    assert 'onmouseover="alert(1)' not in page
    assert "&#34;" in page or "&quot;" in page


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
