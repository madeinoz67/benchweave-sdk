"""The browser/axe lane (I2a §3.5, NFR-Q1, gate I2-A).

Every page template × both themes, served from the REAL app factory over
the mock transport (a uvicorn thread on an ephemeral port — the guards,
the CSP and the vendored assets are all in play), checked with axe-core at
WCAG 2.2 A/AA. Themes are FORCED via ``data-theme`` on the document
element — not left to ``prefers-color-scheme``.

The RED control runs in the same lane: a doctored template (a label-less
input) MUST produce an axe violation — a clean run against the doctored
page means the measurement is broken, not the page set (the G1d
planted-violation precedent). The plot hydration is asserted
post-hydrate (risk 4's falsifier: payload pins alone cannot carry a draw
claim), and the Canvas-2D lane hydrator draws synthetic columns — live
lane data is I3's (D-I2b).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.responses import HTMLResponse
from playwright.sync_api import Browser, Page, sync_playwright

pytestmark = pytest.mark.browser

#: axe's WCAG 2.2 AA rule set: levels A + AA of 2.0 and 2.2 (2.1's A/AA
#: are a subset of 2.2's at the tag level axe exposes).
WCAG_22_AA_TAGS = ["wcag2a", "wcag2aa", "wcag22a", "wcag22aa"]

DEV = "example_device"
#: The page templates: index, device page, the manifest readings page.
PAGES = ("/", f"/devices/{DEV}", "/pages/readings")
THEMES = ("light", "dark")


def _scaffold(destination: Path) -> Path:
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    create_project(destination, "example_plugin")
    create_ui_resources(destination, "example_plugin")
    return destination


def _make_app(project: Path, port: int):
    """The real factory, guards and all — the trusted-host guard must know
    the port the listener actually binds (the browser sends it in Host)."""
    from benchweave_sdk_server.cli import _build_seam
    from benchweave_sdk_server.security import GuardPolicy, new_token
    from benchweave_sdk_server.web import build_app

    seam, _ = _build_seam(project, scenario="normal")
    return build_app(
        seam,
        policy=GuardPolicy.complete(
            bound_host="127.0.0.1",
            bound_port=port,
            bearer_token=new_token(),
            csrf_token=new_token(),
        ),
    )


def _free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class _Server:
    """A uvicorn thread on an ephemeral loopback port; the app factory
    receives the port BEFORE the server starts."""

    def __init__(self, project: Path) -> None:
        import uvicorn

        self.port = _free_port()
        self.config = uvicorn.Config(
            _make_app(project, self.port),
            host="127.0.0.1",
            port=self.port,
            log_config=None,
            lifespan="on",
        )
        self.server = uvicorn.Server(self.config)

    def __enter__(self) -> str:
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        while not self.server.started:
            import time

            time.sleep(0.02)
        return f"http://127.0.0.1:{self.port}"

    def __exit__(self, *args: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


@pytest.fixture(scope="module")
def server_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    with _Server(_scaffold(tmp_path_factory.mktemp("browser") / "starter")) as url:
        yield url


@pytest.fixture(scope="module")
def doctored_url() -> Iterator[str]:
    """The RED control's app: a doctored template — a form input with no
    associated label (axe's ``label`` rule fires). The control proves the
    MEASUREMENT has teeth in this browser setup; it serves from its own
    tiny app because the real factory mounts \"/\" last and would swallow
    a route added after construction."""
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/doctored", response_class=HTMLResponse)
    async def doctored() -> HTMLResponse:
        return HTMLResponse(
            "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<title>Doctored control</title></head><body>"
            "<main><form><input type=\"text\" name=\"unlabelled\"></form></main>"
            "</body></html>"
        )

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None)
    )

    class _Started:
        def __enter__(self) -> str:
            self.thread = threading.Thread(target=server.run, daemon=True)
            self.thread.start()
            while not server.started:
                import time

                time.sleep(0.02)
            return f"http://127.0.0.1:{port}"

        def __exit__(self, *args: object) -> None:
            server.should_exit = True
            self.thread.join(timeout=10)

    with _Started() as url:
        yield url


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch()
        yield chromium
        chromium.close()


@pytest.fixture()
def page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    yield context.new_page()
    context.close()


def _connect(server_url: str, page: Page) -> None:
    """Connect deterministically: the page-delivered CSRF token drives the
    POST through Playwright's request context (the same request the htmx
    form sends), then the caller navigates fresh."""
    import re

    body = page.request.get(server_url + f"/devices/{DEV}").text()
    match = re.search(r'X-CSRF-Token": "([^"]+)"', body)
    assert match, "the device page delivers the CSRF token"
    response = page.request.post(
        server_url + f"/devices/{DEV}/connect",
        headers={"x-csrf-token": match.group(1)},
    )
    assert response.status in (200, 303), response.status


def _axe(page: Page):
    from axe_playwright_python.sync_playwright import Axe  # type: ignore[import-untyped]

    return Axe().run(
        page,
        options={
            "runOnly": {"type": "tag", "values": WCAG_22_AA_TAGS},
            "resultTypes": ["violations"],
        },
    )


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("path", PAGES)
def test_every_page_template_is_axe_clean_in_both_themes(
    page: Page, server_url: str, theme: str, path: str
) -> None:
    page.goto(server_url + path)
    page.evaluate("theme => { document.documentElement.dataset.theme = theme; }", theme)
    results = _axe(page)
    assert results.violations_count == 0, results.generate_snapshot()


def test_the_two_theme_arms_really_differ(page: Page, server_url: str) -> None:
    """Fold R-e's machine check: forcing data-theme must actually switch
    the computed tokens — if both arms computed the same --bw-canvas the
    'both themes' claim would be one theme checked twice (theme collapse).
    """
    page.goto(server_url + "/")
    canvases = {}
    for theme in THEMES:
        page.evaluate("theme => { document.documentElement.dataset.theme = theme; }", theme)
        canvases[theme] = page.evaluate(
            "() => getComputedStyle(document.documentElement)"
            ".getPropertyValue('--bw-canvas').trim()"
        )
    assert canvases["light"] and canvases["dark"], canvases
    assert canvases["light"] != canvases["dark"], canvases


def test_the_readings_page_is_axe_clean_connected(
    page: Page, server_url: str
) -> None:
    """The connected render — tiles with live severities — is the state
    the operator actually reads; axe checks it in both themes."""
    _connect(server_url, page)
    page.goto(server_url + "/pages/readings")
    page.wait_for_selector(".bw-reading")
    for theme in THEMES:
        page.evaluate("theme => { document.documentElement.dataset.theme = theme; }", theme)
        results = _axe(page)
        assert results.violations_count == 0, results.generate_snapshot()


def test_the_doctored_template_control_must_red(page: Page, doctored_url: str) -> None:
    """RED control: the label-less input MUST produce an axe violation —
    proving the lane has teeth in THIS http-served setup. A clean run
    here means the measurement is broken (a KILL, per gate I2-A)."""
    page.goto(doctored_url + "/doctored")
    results = _axe(page)
    assert results.violations_count > 0, "the doctored control must red"
    rules = {violation["id"] for violation in results.response["violations"]}
    assert "label" in rules, rules


# --- the plot hydration (risk 4's falsifier) -----------------------------------


def test_the_plot_hydrates_and_the_canvas_draws(page: Page, server_url: str) -> None:
    """Post-hydrate canvas state, not payload pins: after connecting and
    letting the page's own gather read land, the uPlot instance mounts
    into the hydrate-target canvas with a non-trivial size."""
    _connect(server_url, page)
    page.goto(server_url + "/pages/readings")
    host = page.wait_for_selector('[data-bw-plot-host][data-bw-hydrated="true"]', timeout=15000)
    assert host is not None
    mounted = page.evaluate(
        """() => {
            const host = document.querySelector('[data-bw-plot-host]');
            const plot = host && host._bwPlot;
            if (!plot) return null;
            return { width: plot.width, height: plot.height, series: plot.series.length };
        }"""
    )
    assert mounted, "the uPlot instance mounted on the wrapper"
    assert mounted["width"] > 0 and mounted["height"] > 0
    assert mounted["series"] == 2  # the x axis series + one channel


def test_the_lane_hydrator_draws_synthetic_columns(page: Page, server_url: str) -> None:
    """The Canvas-2D lane hydrator ships and is exercised on synthetic
    columns (D-I2b: live lane data is I3's)."""
    page.goto(server_url + "/")
    drawn = page.evaluate(
        """() => {
            const canvas = document.createElement('canvas');
            canvas.style.width = '600px';
            document.body.appendChild(canvas);
            window.bwHydrateLanes(canvas, [
                { state: '1', transitions: 0, glitch: false },
                { state: '0', transitions: 1, glitch: false,
                  edge: { from: '0', to: '1' } },
                { state: '1', transitions: 2, glitch: true },
            ]);
            const marked = canvas.getAttribute('data-bw-lanes-drawn');
            canvas.remove();
            return marked;
        }"""
    )
    assert drawn == "3", "the hydrator drew the three synthetic columns"
