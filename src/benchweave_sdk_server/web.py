"""The app factory: one ASGI app with REST, HTML and the mounted MCP server.

Mirrors the gateway's ``interfaces/app.py`` composition shape-for-shape with
the store, worker, write-gate and recovery sweep removed: the REST router is
included FIRST, FastMCP's ``http_app(path="/mcp")`` is mounted at ``/`` (so
``/mcp`` lands and ``/v1`` already won its routes), and the host lifespan
enters the mounted app's lifespan — FastMCP's http_app lifespan MUST run on
the host or initialize 500s. ``build_app`` takes an explicit
:class:`~benchweave_sdk_server.security.GuardPolicy` so the acceptance RED
arms can omit exactly one guard; the ``serve`` CLI always passes a complete
one.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from . import catalogue
from .assets import (
    RENDERER_ASSETS,
    renderer_assets_root,
    ui_assets_root,
    verify_renderer_assets,
    verify_ui_assets,
)
from .errors import ERROR_HTTP_STATUS, SeamError
from .mcp import build_mcp
from .presentation import (
    SUPPORTED_PANELS,
    HostPresentation,
    compose_severity,
    mode_banner_html,
    reading_tile_html,
    refusal_severity,
)
from .scenarios import SCENARIOS, ScenarioSelection
from .seam import StandaloneSeam
from .security import GuardPolicy, install_guards

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))

_MEDIA_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


def _envelope(result: dict[str, Any]) -> JSONResponse:
    return JSONResponse(result)


def _failure(exc: SeamError) -> JSONResponse:
    return JSONResponse(exc.body(), status_code=ERROR_HTTP_STATUS[exc.code])


def build_app(
    seam: StandaloneSeam,
    *,
    policy: GuardPolicy,
    authoring: bool = False,
    scenario: ScenarioSelection | None = None,
) -> FastAPI:
    """Compose the one app; the seam is the only thing routes talk to.

    Construction verifies the vendored asset inventory first (SW-05's
    posture, NFR-P3): tampered or missing bytes refuse STARTUP — never a
    half-serving app whose shell answers 200 while its assets 500.
    ``scenario`` (scenario mode only) arms the device page's scenario
    select — a host-side route mutating the selection, never a catalogue
    operation (D-B1).
    """
    verify_ui_assets(ui_assets_root())
    # The renderer's tokens/themes/globals are verified by the INSTALLED
    # package's own verifier — one verifier per byte set (§4.6).
    verify_renderer_assets()
    # The presentation model is the SEAM's (built once at seam
    # construction, SW-41): this host's declared feature/panel sets drove
    # its validation, and the unavailable-page disclosures ride it.
    presentation = seam.presentation
    mcp_server = build_mcp(seam, authoring=authoring)
    mcp_app = mcp_server.http_app(path="/mcp")

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        # FastMCP's http_app lifespan must run on the host app (the gateway
        # composition precedent): initialize 500s without it. On shutdown the
        # adapter's quiet path runs (NFR-O1) — close is idempotent-tolerant.
        async with mcp_app.lifespan(app):
            try:
                yield
            finally:
                await seam.session.close()

    app = FastAPI(title="BenchWeave SDK server", lifespan=_lifespan)
    app.state.seam = seam
    app.state.policy = policy

    _add_rest_routes(app, seam)
    _add_html_routes(app, seam, policy, scenario=scenario, presentation=presentation)
    _add_asset_routes(app)
    # REST routes are included BEFORE the "/" mount: a mount at "/" swallows
    # every route included after it, so /v1 must land first (app.py:1040-1048).
    app.mount("/", mcp_app)
    install_guards(app, policy)
    return app


def _add_rest_routes(app: FastAPI, seam: StandaloneSeam) -> None:
    """One JSON route per implemented catalogue operation (SW-20)."""

    def handler(operation: str) -> Any:
        async def _route(request: Request) -> Response:
            correlation = str(
                request.headers.get("x-correlation-id") or f"rest-{uuid4().hex[:12]}"
            )
            try:
                body = await request.json()
            except ValueError:
                body = None
            if not isinstance(body, dict):
                return JSONResponse(
                    {
                        "correlation_id": correlation,
                        "error": {
                            "code": "invalid_request",
                            "message": "request body must be a JSON object",
                        },
                    },
                    status_code=400,
                )
            try:
                data = await seam.call(operation, body, correlation_id=correlation)
            except SeamError as exc:
                return _failure(exc)
            return _envelope({"correlation_id": correlation, "data": data})

        return _route

    for row in catalogue.CATALOGUE:
        # Deferred operations are routed too — the seam's ``unavailable``
        # refusal must be an explicit answer, never a silent 404 (SW-10's
        # closed-set honesty on the REST surface).
        app.add_api_route(
            f"/v1/{row.name}",
            handler(row.name),
            methods=["POST"],
            name=f"rest_{row.name}",
        )


def _add_html_routes(
    app: FastAPI,
    seam: StandaloneSeam,
    policy: GuardPolicy,
    *,
    scenario: ScenarioSelection | None = None,
    presentation: HostPresentation,
) -> None:
    """Server-rendered pages plus the HTMX poll partials (SW-20/SW-27)."""

    simulated = seam.transport_kind == "mock"
    mode_banner = Markup(mode_banner_html(simulated=simulated))

    def shared(**extra: Any) -> dict[str, Any]:
        context: dict[str, Any] = {
            "mode_banner": mode_banner,
            "absent": catalogue.ABSENT_GUARANTEES,
            "plugin": seam.session.plugin,
            "csrf_token": policy.csrf_token,
        }
        context.update(extra)
        return context

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> Response:
        devices = (await seam.call("device_discover"))["devices"]
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="index.html",
            context=shared(
                devices=devices,
                connected=seam.session.connected,
                pages=presentation.pages,
                has_presentation=presentation.available,
            ),
        )

    async def _gather_readings(
        device_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Read every readable parameter, or stop at the first refusal.

        Read-only (NFR-O3: no write happens on a page load or poll); a
        refused seam call surfaces as the page's refused state — the honest
        negative — never as a silent blank.
        """
        plugin = seam.session.plugin
        readings: list[dict[str, Any]] = []
        for parameter in plugin.readable_parameters:
            name = str(parameter.get("name", ""))
            try:
                data = await seam.call(
                    "parameter_read", {"device_id": device_id, "parameter": name}
                )
                readings.append(
                    {
                        "name": name,
                        "value": data.get("value"),
                        "unit": data.get("unit") or parameter.get("unit"),
                        "quality": data.get("quality", ""),
                    }
                )
            except SeamError as exc:
                return readings, {
                    "code": exc.code,
                    "message": exc.message,
                    "adapter": exc.details.get("adapter"),
                }
        return readings, None

    async def _render_device(
        request: Request,
        device_id: str,
        action_error: dict[str, Any] | None = None,
    ) -> Response:
        plugin = seam.session.plugin
        readings, error = (
            await _gather_readings(device_id)
            if seam.session.connected and not presentation.available
            else ([], None)
        )
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="device.html",
            context=shared(
                device_id=device_id,
                parameters=plugin.readable_parameters,
                connected=seam.session.connected,
                readings=readings,
                readings_error=error,
                action_error=action_error,
                load_diagnostic=plugin.load_diagnostic,
                scenarios=SCENARIOS if scenario is not None else None,
                scenario_current=scenario.current if scenario is not None else None,
                pages=presentation.pages,
                has_presentation=presentation.available,
            ),
        )

    @app.get("/devices/{device_id}", response_class=HTMLResponse)
    async def device_page(request: Request, device_id: str) -> Response:
        if device_id != seam.session.device_id:
            return HTMLResponse("not found", status_code=404)
        return await _render_device(request, device_id)

    @app.get("/devices/{device_id}/readings", response_class=HTMLResponse)
    async def readings_partial(request: Request, device_id: str) -> Response:
        """The I1 polled partial (the no-presentation degraded path): every
        readable parameter, or the refused state."""
        if device_id != seam.session.device_id:
            return HTMLResponse("not found", status_code=404)
        readings, error = await _gather_readings(device_id)
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="readings.html",
            context=shared(
                device_id=device_id,
                readings=readings,
                readings_error=error,
                connected=seam.session.connected,
            ),
        )

    # --- the manifest pages (I2a §3.2) --------------------------------

    async def _page_reading_state(
        device_id: str, page: Any
    ) -> tuple[list[str], list[Any], dict[str, Any] | None]:
        """Gather one page's reading tiles (read-only, NFR-O3).

        Stops at the first refused read — the refused state renders as the
        page's refused notice, never a silent blank (the I1 partial's
        honest-negative policy carried onto pages). Non-observation
        bindings render the no-data disclosure: the degradation
        ``generate_baselines`` already discloses for non-observation
        targets — their declared plots still project, the renderer owes
        the no-data line.
        """
        plugin = seam.session.plugin
        parameters = {
            str(row.get("name")): row for row in plugin.descriptor.get("parameters", [])
        }
        tiles: list[str] = []
        severities: list[Any] = []
        no_data: list[Any] = []
        for binding in page.bindings:
            if binding.kind != "observation" or binding.parameter_id is None:
                no_data.append(binding)
                continue
            parameter = parameters.get(binding.parameter_id, {})
            try:
                data = await seam.call(
                    "parameter_read",
                    {"device_id": device_id, "parameter": binding.parameter_id},
                )
            except SeamError as exc:
                adapter = exc.details.get("adapter")
                refusal = {
                    "code": exc.code,
                    "message": exc.message,
                    "adapter": adapter,
                }
                return tiles, severities, refusal
            html, severity = reading_tile_html(data, parameter, label=binding.target_id)
            tiles.append(html)
            severities.append(severity)
        return tiles, severities, None

    def _page_context(
        page: Any,
        severity: Any,
        tiles: list[str],
        refusal: Any,
        no_data: list[Any],
    ) -> dict[str, Any]:
        panel_refusal = (
            {"panel_id": page.panel_id}
            if page.panel_id is not None and page.panel_id not in SUPPORTED_PANELS
            else None
        )
        return {
            "page": page,
            "severity": severity,
            "tiles": [Markup(tile) for tile in tiles],
            "refusal": refusal,
            "no_data": no_data,
            "panel_refusal": panel_refusal,
        }

    def _page_plots(page_id: str) -> str:
        """The page's declared plots, composed through the package's plot
        machinery over the session's observation ring (§3.3)."""
        from .plots import plot_host_html

        parts = [
            plot_host_html(view, seam.observation_ring)
            for view in presentation.plot_views
            if view.page_id == page_id
        ]
        return Markup("".join(parts))

    @app.get("/pages/{page_id}", response_class=HTMLResponse)
    async def page_route(request: Request, page_id: str) -> Response:
        page = presentation.page(page_id)
        if page is None:
            return HTMLResponse("not found", status_code=404)
        severity = "neutral"
        tiles: list[str] = []
        refusal = None
        no_data: list[Any] = []
        if page.panel_id is None:
            if page.kind == "readings":
                # The page always probes its bindings: a not-connected
                # device answers not_ready and the page renders the refused
                # state (the disconnected baseline's own severity — the
                # honest negative, never a silent blank).
                tiles, severities, refusal = await _page_reading_state(
                    seam.session.device_id, page
                )
                if refusal is not None:
                    severities.append(
                        refusal_severity(
                            refusal["code"], refusal.get("adapter")
                        )
                    )
                severity = compose_severity(severities)
            else:
                no_data = [binding for binding in page.bindings if binding.kind != "observation"]
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="page.html",
            context=shared(
                **_page_context(page, severity, tiles, refusal, no_data),
                plots=_page_plots(page.id),
            ),
        )

    @app.get("/pages/{page_id}/readings", response_class=HTMLResponse)
    async def page_partial(request: Request, page_id: str) -> Response:
        """The polled partial: the severity header, the tiles, the refused
        state (I1's poll mechanism — SW-26's degenerate coalescing-by-poll,
        disclosed as D-I2a until the event bus lands at I2c)."""
        page = presentation.page(page_id)
        if page is None:
            return HTMLResponse("not found", status_code=404)
        severity = "neutral"
        tiles: list[str] = []
        refusal = None
        if page.panel_id is None and page.kind == "readings":
            tiles, severities, refusal = await _page_reading_state(
                seam.session.device_id, page
            )
            if refusal is not None:
                severities.append(refusal_severity(refusal["code"], refusal.get("adapter")))
            severity = compose_severity(severities)
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="page-readings.html",
            context=shared(
                **_page_context(page, severity, tiles, refusal, []),
                plots=_page_plots(page.id),
            ),
        )

    def _redirect(device_id: str) -> RedirectResponse:
        return RedirectResponse(url=f"/devices/{device_id}", status_code=303)

    @app.post("/devices/{device_id}/connect")
    async def connect_device(request: Request, device_id: str) -> Response:
        if device_id != seam.session.device_id:
            return HTMLResponse("not found", status_code=404)
        try:
            await seam.call("device_connect", {"device_id": device_id})
        except SeamError as exc:
            # The M1 fold: a refused connect RENDERS its refusal — the
            # operator never gets the silent prompt back instead.
            return await _render_device(
                request, device_id, action_error={"code": exc.code, "message": exc.message}
            )
        return _redirect(device_id)

    @app.post("/devices/{device_id}/disconnect")
    async def disconnect_device(device_id: str) -> Response:
        if device_id != seam.session.device_id:
            return HTMLResponse("not found", status_code=404)
        with contextlib.suppress(SeamError):
            await seam.call("device_disconnect", {"device_id": device_id})
        return _redirect(device_id)

    if scenario is not None:

        @app.post("/devices/{device_id}/scenario")
        async def select_scenario(request: Request, device_id: str) -> Response:
            """Switch the scenario selection — host state, not a catalogue op.

            The connect-button idiom (HTML POST + CSRF): the mutation arms
            the mock factory's NEXT-connection script, so the swap takes
            effect on reconnect — a live connection keeps the transport it
            opened with (the M1 fold's per-connection services, honestly).
            """
            if device_id != seam.session.device_id:
                return HTMLResponse("not found", status_code=404)
            form = await request.form()
            try:
                scenario.select(str(form.get("scenario", "")))
            except ValueError as exc:
                return await _render_device(
                    request,
                    device_id,
                    action_error={"code": "invalid_request", "message": str(exc)},
                )
            return _redirect(device_id)


def _add_asset_routes(app: FastAPI) -> None:
    """Serve only inventory-verified vendored assets (NFR-P3/P5 posture)."""

    @app.get("/assets/{asset_path:path}")
    async def asset(asset_path: str) -> Response:
        # Same traversal refusals as the preview server's asset route: a
        # backslash is a separator on Windows and a colon is a drive or ADS.
        candidate = asset_path
        if (
            not candidate
            or candidate.startswith("/")
            or ".." in candidate.split("/")
            or "\\" in candidate
            or ":" in candidate
        ):
            return Response(status_code=404)
        # The renderer's assets serve from the installed ui-html package
        # (verified at construction); everything else serves from this
        # host's own verified vendored tree.
        root = renderer_assets_root() if candidate in RENDERER_ASSETS else ui_assets_root()
        target = root / candidate
        try:
            raw = target.read_bytes()
        except OSError:
            return Response(status_code=404)
        media = _MEDIA_TYPES.get(target.suffix, "application/octet-stream")
        return Response(
            content=raw,
            media_type=media,
            headers={"Cache-Control": "no-cache"},
        )
