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

from . import catalogue
from .assets import ui_assets_root, verify_ui_assets
from .errors import ERROR_HTTP_STATUS, SeamError
from .mcp import build_mcp
from .seam import StandaloneSeam
from .security import GuardPolicy, install_guards

#: The persistent banner every page carries (SW-27) — distinct from the
#: preview server's SIMULATED PRESENTATION DATA labelling.
BANNER = "STANDALONE — no gateway"

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))

_MEDIA_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


def _envelope(result: dict[str, Any]) -> JSONResponse:
    return JSONResponse(result)


def _failure(exc: SeamError) -> JSONResponse:
    return JSONResponse(exc.body(), status_code=ERROR_HTTP_STATUS[exc.code])


def build_app(seam: StandaloneSeam, *, policy: GuardPolicy, authoring: bool = False) -> FastAPI:
    """Compose the one app; the seam is the only thing routes talk to.

    Construction verifies the vendored asset inventory first (SW-05's
    posture, NFR-P3): tampered or missing bytes refuse STARTUP — never a
    half-serving app whose shell answers 200 while its assets 500.
    """
    verify_ui_assets(ui_assets_root())
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
    _add_html_routes(app, seam, policy)
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


def _add_html_routes(app: FastAPI, seam: StandaloneSeam, policy: GuardPolicy) -> None:
    """Server-rendered pages plus the HTMX readings partial (SW-20/SW-27)."""

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> Response:
        devices = (await seam.call("device_discover"))["devices"]
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "banner": BANNER,
                "absent": catalogue.ABSENT_GUARANTEES,
                "plugin": seam.session.plugin,
                "devices": devices,
                "connected": seam.session.connected,
                "csrf_token": policy.csrf_token,
            },
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
                return readings, {"code": exc.code, "message": exc.message}
        return readings, None

    async def _render_device(
        request: Request,
        device_id: str,
        action_error: dict[str, Any] | None = None,
    ) -> Response:
        plugin = seam.session.plugin
        readings, error = (
            await _gather_readings(device_id) if seam.session.connected else ([], None)
        )
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="device.html",
            context={
                "banner": BANNER,
                "absent": catalogue.ABSENT_GUARANTEES,
                "plugin": plugin,
                "device_id": device_id,
                "parameters": plugin.readable_parameters,
                "connected": seam.session.connected,
                "readings": readings,
                "readings_error": error,
                "action_error": action_error,
                "csrf_token": policy.csrf_token,
            },
        )

    @app.get("/devices/{device_id}", response_class=HTMLResponse)
    async def device_page(request: Request, device_id: str) -> Response:
        if device_id != seam.session.device_id:
            return HTMLResponse("not found", status_code=404)
        return await _render_device(request, device_id)

    @app.get("/devices/{device_id}/readings", response_class=HTMLResponse)
    async def readings_partial(request: Request, device_id: str) -> Response:
        """The polled partial: every readable parameter, or the refused state."""
        if device_id != seam.session.device_id:
            return HTMLResponse("not found", status_code=404)
        readings, error = await _gather_readings(device_id)
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="readings.html",
            context={
                "banner": BANNER,
                "absent": catalogue.ABSENT_GUARANTEES,
                "plugin": seam.session.plugin,
                "device_id": device_id,
                "readings": readings,
                "readings_error": error,
                "connected": seam.session.connected,
                "csrf_token": policy.csrf_token,
            },
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
        root = ui_assets_root()
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
