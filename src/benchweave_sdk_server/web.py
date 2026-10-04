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

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from . import catalogue
from . import presentation as presentation_module
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
    staged_control_html,
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
    # construction, SW-41, and REBUILT on reload): this host's declared
    # feature/panel sets drove its validation, and the unavailable-page
    # disclosures ride it. Routes read it per request through the seam.
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
                # The host's own resources: the capture library's root lock
                # (NFR-O1's close-down shape; I3c extends this to settle an
                # in-flight capture first).
                seam.close()

    app = FastAPI(title="BenchWeave SDK server", lifespan=_lifespan)
    app.state.seam = seam
    app.state.policy = policy

    _add_rest_routes(app, seam)
    _add_html_routes(app, seam, policy, scenario=scenario)
    _add_events_route(app, seam)
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
                data = await seam.call(
                    operation, body, correlation_id=correlation, surface="rest"
                )
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
) -> None:
    """Server-rendered pages plus the HTMX poll partials (SW-20/SW-27)."""

    simulated = seam.transport_kind == "mock"
    mode_banner = Markup(mode_banner_html(simulated=simulated))

    def pres() -> HostPresentation:
        """The CURRENT presentation model, read per request: a reload
        rebuilds it on the seam, and a closure captured at build time
        would keep rendering the previous version's pages forever."""
        return seam.presentation

    def shared(**extra: Any) -> dict[str, Any]:
        context: dict[str, Any] = {
            "mode_banner": mode_banner,
            "absent": catalogue.ABSENT_GUARANTEES,
            "plugin": seam.session.plugin,
            "csrf_token": policy.csrf_token,
            "reload_state": seam.reload_state,
            "pending_reload": seam.pending_reload,
        }
        context.update(extra)
        return context

    async def _ui_call(
        operation: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """The page routes' dispatches carry the UI surface (SW-34): the
        originating surface is host knowledge supplied by the dispatch
        layer — REST passes ``surface="rest"`` on its routes, and the
        browser's mutations pass ``"ui"`` here, so what the tag feeds
        (the SW-54 capture sidecar reads it) records the true origin,
        never null."""
        return await seam.call(operation, arguments, surface="ui")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> Response:
        if seam.transport_kind == "serial":
            # NFR-O3: a page load never transmits — GET serves the LAST
            # discovery result (host state, initially empty with a scan
            # prompt); scanning is the explicit POST below.
            devices = seam.discovery_cache or []
            scan_error = None
        else:
            devices = (await seam.call("device_discover"))["devices"]
            scan_error = None
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="index.html",
            context=shared(
                devices=devices,
                connected=seam.session.connected,
                pages=pres().pages,
                has_presentation=pres().available,
                scan_available=seam.transport_kind == "serial",
                scan_error=scan_error,
            ),
        )

    @app.post("/discover")
    async def discover_route(request: Request) -> Response:
        """The explicit scan (NFR-O3's arm): the ONLY page route that calls
        device_discover on the serial transport. A refused scan renders its
        refusal — never a silent no-op."""
        if seam.transport_kind != "serial":
            return RedirectResponse(url="/", status_code=303)
        try:
            await seam.call("device_discover")
        except SeamError as exc:
            devices = seam.discovery_cache or []
            return _TEMPLATES.TemplateResponse(
                request=request,
                name="index.html",
                context=shared(
                    devices=devices,
                    connected=seam.session.connected,
                    pages=pres().pages,
                    has_presentation=pres().available,
                    scan_available=True,
                    scan_error={"code": exc.code, "message": exc.message},
                ),
            )
        except (RuntimeError, ValueError, OSError) as exc:
            # The scan's failure classes that raise before any SeamError
            # exists (FOLD-E) render the same typed scan-refused row; the
            # seam maps them for REST and MCP too, so this arm is the
            # route's own defense, not the only reader.
            devices = seam.discovery_cache or []
            return _TEMPLATES.TemplateResponse(
                request=request,
                name="index.html",
                context=shared(
                    devices=devices,
                    connected=seam.session.connected,
                    pages=pres().pages,
                    has_presentation=pres().available,
                    scan_available=True,
                    scan_error={"code": "not_ready", "message": str(exc)},
                ),
            )
        return RedirectResponse(url="/", status_code=303)

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
        *,
        action_label: str | None = None,
    ) -> Response:
        plugin = seam.session.plugin
        readings, error = (
            await _gather_readings(device_id)
            if seam.session.connected and not pres().available
            else ([], None)
        )
        try:
            presets = (await seam.call("preset_list"))["presets"]
        except SeamError:
            presets = None
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
                action_label=action_label,
                load_diagnostic=plugin.load_diagnostic,
                scenarios=SCENARIOS if scenario is not None else None,
                scenario_current=scenario.current if scenario is not None else None,
                pages=pres().pages,
                has_presentation=pres().available,
                presets=presets,
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
    ) -> tuple[list[str], list[Any], list[Any], dict[str, Any] | None, dict[str, Any]]:
        """Gather one page's reading tiles (read-only, NFR-O3).

        Stops at the first refused read — the refused state renders as the
        page's refused notice, never a silent blank (the I1 partial's
        honest-negative policy carried onto pages). Non-observation
        bindings render the no-data disclosure: the degradation
        ``generate_baselines`` already discloses for non-observation
        targets — their declared plots still project, the renderer owes
        the no-data line. The fifth element is the raw read data per
        parameter name — the staging inputs' device-value defaults.
        """
        plugin = seam.session.plugin
        parameters = {
            str(row.get("name")): row for row in plugin.descriptor.get("parameters", [])
        }
        tiles: list[str] = []
        severities: list[Any] = []
        no_data: list[Any] = []
        reads: dict[str, Any] = {}
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
                return tiles, severities, no_data, refusal, reads
            if (
                presentation_module.STAGED_ECHO_TILES
                and binding.parameter_id in seam.staged
            ):
                # The I2-S RED control's render (never the default): an
                # optimistic host laundering the staged value into the tile.
                data = {**data, "value": seam.staged[binding.parameter_id]}
            reads[binding.parameter_id] = data
            html, severity = reading_tile_html(data, parameter, label=binding.target_id)
            tiles.append(html)
            severities.append(severity)
        return tiles, severities, no_data, None, reads

    def _page_controls(page: Any, reads: dict[str, Any]) -> list[dict[str, Any]]:
        """The staging inputs for one page's WRITABLE numeric parameters
        (I2b §4.1): bounds from the descriptor's own range, the staged
        value shown only in the input (§E.3). Host state, no I/O."""
        plugin = seam.session.plugin
        controls: list[dict[str, Any]] = []
        for binding in page.bindings:
            if binding.kind != "observation" or binding.parameter_id is None:
                continue
            parameter = next(
                (
                    row
                    for row in plugin.descriptor.get("parameters", [])
                    if str(row.get("name", "")) == binding.parameter_id
                ),
                None,
            )
            if (
                parameter is None
                or str(parameter.get("access", "")) != "rw"
                or str(parameter.get("type", "")) not in ("float", "int")
            ):
                continue
            controls.append(
                {
                    "name": binding.parameter_id,
                    "input": Markup(
                        staged_control_html(
                            parameter,
                            staged=seam.staged.get(binding.parameter_id),
                            device_value=(reads.get(binding.parameter_id) or {}).get(
                                "value"
                            ),
                        )
                    ),
                }
            )
        return controls

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
            for view in pres().plot_views
            if view.page_id == page_id
        ]
        return Markup("".join(parts))

    @app.get("/pages/{page_id}", response_class=HTMLResponse)
    async def page_route(request: Request, page_id: str) -> Response:
        page = pres().page(page_id)
        if page is None:
            return HTMLResponse("not found", status_code=404)
        severity = "neutral"
        tiles: list[str] = []
        refusal = None
        no_data: list[Any] = []
        reads: dict[str, Any] = {}
        connected = seam.session.connected
        if page.panel_id is None:
            if page.kind == "readings":
                has_observations = any(
                    binding.kind == "observation" and binding.parameter_id is not None
                    for binding in page.bindings
                )
                if connected:
                    # Connected: the page probes its bindings; a refused
                    # read renders the refused state (the request-rejected
                    # baseline's own shape — never a silent blank).
                    tiles, severities, no_data, refusal, reads = (
                        await _page_reading_state(seam.session.device_id, page)
                    )
                    if refusal is not None:
                        severities.append(
                            refusal_severity(refusal["code"], refusal.get("adapter"))
                        )
                    severity = compose_severity(severities)
                else:
                    # Not connected: nothing was refused — the connect
                    # prompt renders ONLY for pages that declare
                    # observations to read (fold R-b); pages without them
                    # render their disclosures alone, never the prompt.
                    no_data = [
                        binding
                        for binding in page.bindings
                        if binding.kind != "observation"
                        or binding.parameter_id is None
                    ]
                    show_prompt = has_observations
                    return _TEMPLATES.TemplateResponse(
                        request=request,
                        name="page.html",
                        context=shared(
                            **_page_context(page, severity, tiles, refusal, no_data),
                            show_prompt=show_prompt,
                            plots=_page_plots(page.id),
                            controls=_page_controls(page, reads),
                            action_error=None,
                        ),
                    )
            else:
                no_data = [binding for binding in page.bindings if binding.kind != "observation"]
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="page.html",
            context=shared(
                **_page_context(page, severity, tiles, refusal, no_data),
                show_prompt=False,
                plots=_page_plots(page.id),
                controls=_page_controls(page, reads),
                action_error=None,
            ),
        )

    @app.get("/pages/{page_id}/readings", response_class=HTMLResponse)
    async def page_partial(request: Request, page_id: str) -> Response:
        """The polled partial: the severity badge, the tiles, the refused
        state, the no-data disclosures and the plots — everything the swap
        region owns (I1's poll mechanism — SW-26's degenerate
        coalescing-by-poll, disclosed as D-I2a until the event bus lands at
        I2c). The no-data lines SURVIVE the swap (fold R-b: a disclosure
        that vanishes on poll is a laundered disclosure)."""
        page = pres().page(page_id)
        if page is None:
            return HTMLResponse("not found", status_code=404)
        severity = "neutral"
        tiles: list[str] = []
        refusal = None
        no_data: list[Any] = []
        show_prompt = False
        if page.panel_id is None and page.kind == "readings":
            if seam.session.connected:
                tiles, severities, no_data, refusal, _reads = (
                    await _page_reading_state(seam.session.device_id, page)
                )
                if refusal is not None:
                    severities.append(refusal_severity(refusal["code"], refusal.get("adapter")))
                severity = compose_severity(severities)
            else:
                no_data = [
                    binding
                    for binding in page.bindings
                    if binding.kind != "observation" or binding.parameter_id is None
                ]
                show_prompt = any(
                    binding.kind == "observation" and binding.parameter_id is not None
                    for binding in page.bindings
                )
        elif page.panel_id is None:
            no_data = [binding for binding in page.bindings if binding.kind != "observation"]
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="page-readings.html",
            context=shared(
                **_page_context(page, severity, tiles, refusal, no_data),
                show_prompt=show_prompt,
                plots=_page_plots(page.id),
            ),
        )

    def _redirect() -> RedirectResponse:
        """The device page redirect. The target derives from the SEAM's
        own device id — the validated server-side object — never the
        request's echoed path parameter (#98's untrusted-redirection
        class: every caller has already validated equality, and the rule
        has nothing left to see)."""
        return RedirectResponse(
            url=f"/devices/{seam.session.device_id}", status_code=303
        )

    @app.post("/devices/{device_id}/connect")
    async def connect_device(request: Request, device_id: str) -> Response:
        if device_id != seam.session.device_id:
            return HTMLResponse("not found", status_code=404)
        try:
            await _ui_call("device_connect", {"device_id": device_id})
        except SeamError as exc:
            # The M1 fold: a refused connect RENDERS its refusal — the
            # operator never gets the silent prompt back instead.
            return await _render_device(
                request, device_id, action_error={"code": exc.code, "message": exc.message}
            )
        return _redirect()

    @app.post("/devices/{device_id}/disconnect")
    async def disconnect_device(device_id: str) -> Response:
        if device_id != seam.session.device_id:
            return HTMLResponse("not found", status_code=404)
        with contextlib.suppress(SeamError):
            await _ui_call("device_disconnect", {"device_id": device_id})
        return _redirect()

    def _page_action_error(exc: SeamError) -> dict[str, Any]:
        return {
            "code": exc.code,
            "message": exc.message,
            "adapter": exc.details.get("adapter"),
        }

    async def _render_page(
        request: Request,
        page: Any,
        action_error: dict[str, Any] | None,
        *,
        action_label: str | None = None,
    ) -> Response:
        """Re-render one page with an action outcome (the refused apply
        renders its refusal — SW-12's pass-through, never a silent drop)."""
        severity = "neutral"
        tiles: list[str] = []
        refusal = None
        no_data: list[Any] = []
        reads: dict[str, Any] = {}
        if page.panel_id is None and page.kind == "readings" and seam.session.connected:
            tiles, severities, no_data, refusal, reads = await _page_reading_state(
                seam.session.device_id, page
            )
            if refusal is not None:
                severities.append(refusal_severity(refusal["code"], refusal.get("adapter")))
            severity = compose_severity(severities)
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="page.html",
            context=shared(
                **_page_context(page, severity, tiles, refusal, no_data),
                show_prompt=False,
                plots=_page_plots(page.id),
                controls=_page_controls(page, reads),
                action_error=action_error,
                action_label=action_label,
            ),
        )

    def _parse_form_value(raw: str, parameter: dict[str, Any]) -> Any:
        """Parse one form field against the parameter's declared type."""
        kind = str(parameter.get("type", ""))
        if kind == "bool":
            if raw in ("true", "false"):
                return raw == "true"
            raise ValueError(f"not a boolean: {raw}")
        if kind in ("float", "int"):
            value = float(raw) if kind == "float" else int(raw)
            if kind == "float" and value.is_integer() and "." not in raw and "e" not in raw.lower():
                return value
            return value
        return raw

    @app.post("/pages/{page_id}/stage")
    async def stage_page(request: Request, page_id: str) -> Response:
        """Stage the page's inputs (host state, no device I/O): the first
        of the two deliberate actions — Stage, then Apply."""
        page = pres().page(page_id)
        if page is None:
            return HTMLResponse("not found", status_code=404)
        form = await request.form()
        plugin = seam.session.plugin
        for control in _page_controls(page, {}):
            name = str(control["name"])
            raw = form.get(name)
            if raw is None or str(raw) == "":
                continue
            parameter = next(
                row
                for row in plugin.descriptor.get("parameters", [])
                if str(row.get("name", "")) == name
            )
            try:
                value = _parse_form_value(str(raw), parameter)
            except ValueError as exc:
                return await _render_page(
                    request,
                    page,
                    {
                        "code": "invalid_request",
                        "message": f"invalid staged input for {name}: {exc}",
                    },
                    action_label="Stage refused",
                )
            try:
                await _ui_call(
                    "parameter_stage",
                    {
                        "device_id": seam.session.device_id,
                        "parameter": name,
                        "value": value,
                    },
                )
            except SeamError as exc:
                return await _render_page(
                    request,
                    page,
                    _page_action_error(exc),
                    action_label="Stage refused",
                )
        return RedirectResponse(url=f"/pages/{page.id}", status_code=303)

    @app.post("/pages/{page_id}/apply")
    async def apply_page(request: Request, page_id: str) -> Response:
        """Apply every staged value (write, then read-back — SW-23)."""
        page = pres().page(page_id)
        if page is None:
            return HTMLResponse("not found", status_code=404)
        try:
            await _ui_call("parameter_apply", {"device_id": seam.session.device_id})
        except SeamError as exc:
            return await _render_page(request, page, _page_action_error(exc))
        return RedirectResponse(url=f"/pages/{page.id}", status_code=303)

    @app.post("/devices/{device_id}/preset-apply")
    async def apply_preset(request: Request, device_id: str) -> Response:
        """Apply one preset through the same write/read-back path; the
        firmware gate runs before any write."""
        if device_id != seam.session.device_id:
            return HTMLResponse("not found", status_code=404)
        form = await request.form()
        preset_id = str(form.get("preset_id", ""))
        try:
            await _ui_call(
                "preset_apply",
                {"device_id": device_id, "preset_id": preset_id},
            )
        except SeamError as exc:
            return await _render_device(
                request,
                device_id,
                action_error=_page_action_error(exc),
                action_label="Preset apply refused",
            )
        return _redirect()

    @app.post("/reload/confirm")
    async def confirm_reload_route(request: Request) -> Response:
        """The operator's Q11 confirmation (CSRF POST): proceeds a reload
        that pended because it changes adapter code while a device is
        connected. With nothing pending it answers 409 — a confirm for a
        reload nobody asked for is refused, never a silent no-op."""
        if seam.pending_reload is None:
            return HTMLResponse(
                "no reload is waiting for confirmation", status_code=409
            )
        try:
            await seam.confirm_reload(source="ui")
        except SeamError as exc:
            return HTMLResponse(
                f"{exc.code}: {exc.message}",
                status_code=ERROR_HTTP_STATUS[exc.code],
            )
        return _redirect()

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
            return _redirect()


#: The event kinds whose SSE payload is a human advisory rather than the
#: JSON row (htmx's sse-swap renders the data into the page — the two
#: reload advisories say what happened in words; everything else swaps
#: nowhere and stays the compact JSON a script can read).
_ADVISORY_TEXT: dict[str, str] = {
    "plugin_reloaded": (
        "Plugin reloaded — refresh pages to see the new version."
    ),
    "reload_confirmation_required": (
        "A reload is waiting for operator confirmation — confirm it on this page."
    ),
}


def _sse_data(row: dict[str, Any]) -> str:
    advisory = _ADVISORY_TEXT.get(str(row.get("kind")))
    if advisory is not None:
        return advisory
    return json.dumps(
        {"id": row["id"], "kind": row["kind"], "data": row["data"]},
        separators=(",", ":"),
    )


def _add_events_route(app: FastAPI, seam: StandaloneSeam) -> None:
    """The SSE stream over the SAME sequence ``events_get`` serves (I2c
    §4.2): the browser, REST watchers and MCP see one order. Reconnecting
    clients resume from ``Last-Event-ID`` (the htmx SSE extension sends
    it) or the ``after_id`` query parameter."""

    @app.get("/events")
    async def events(request: Request) -> Response:
        header = request.headers.get("last-event-id")
        raw = request.query_params.get("after_id", header or "")
        try:
            cursor = max(0, int(raw)) if raw else 0
        except ValueError:
            return PlainTextResponse("invalid event cursor", status_code=400)

        async def stream() -> AsyncIterator[str]:
            # The comment frame flips the response to streaming immediately;
            # the backlog follows, then the poll loop carries new rows.
            # Disconnect detection is CANCELLATION, not is_disconnected():
            # reading the receive channel inside a streaming body under
            # BaseHTTPMiddleware (every guard here is one) consumes body
            # messages and deadlocks the stream — the server cancels the
            # response task on disconnect, which ends this generator.
            yield ": connected\n\n"
            last = cursor
            while True:
                rows = seam.events.after(last)
                for row in rows:
                    yield f"id: {row['id']}\nevent: {row['kind']}\ndata: {_sse_data(row)}\n\n"
                    last = row["id"]
                if not rows:
                    await asyncio.sleep(0.2)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )


def _add_asset_routes(app: FastAPI) -> None:
    """Serve only inventory-verified vendored assets (NFR-P3/P5 posture)."""

    @app.get("/assets/{asset_path:path}")
    async def asset(asset_path: str) -> Response:
        # Same traversal refusals as the preview server's asset route: a
        # backslash is a separator on Windows and a colon is a drive or ADS.
        # These refusals are the guard CodeQL's py/path-injection alert
        # asks about (ROW-4): the request can only name a relative,
        # "/"-separated, non-parent path, so root / candidate stays inside
        # one of the two package-local roots (pinned by the traversal arm).
        # Not caught: a symlink swapped into the tree at runtime — that
        # takes filesystem write access to the package, which the request
        # does not have; the startup inventory verifies the tree's bytes.
        candidate = asset_path  # codeql[py/path-injection] guarded: traversal refusals pin the path
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
