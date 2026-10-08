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
import hmac
import json
import math
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
from markupsafe import Markup, escape

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
    streams_closing: Any = None,
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
        # composition precedent): initialize 500s without it. On shutdown,
        # NFR-O1's close-down runs in order: the retention schedule stops
        # first (it is a writer over the library), then the in-flight
        # capture settles honestly, then the adapter's quiet path (close is
        # idempotent-tolerant), then the host's own resources.
        scheduler: asyncio.Task[None] | None = None
        if seam.retention is not None and seam.retention.rules:
            scheduler = asyncio.create_task(seam.retention_scheduler_loop())
        async with mcp_app.lifespan(app):
            try:
                yield
            finally:
                if scheduler is not None:
                    scheduler.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await scheduler
                await seam.settle_capture_for_shutdown()
                await seam.session.close()
                # The host's own resources: the capture library's root lock.
                seam.close()

    app = FastAPI(title="BenchWeave SDK server", lifespan=_lifespan)
    app.state.seam = seam
    app.state.policy = policy

    _add_rest_routes(app, seam)
    _add_html_routes(app, seam, policy, scenario=scenario)
    _add_events_route(app, seam, streams_closing=streams_closing)
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


def _figure_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """One ``analysis_view`` entry shaped for the analyse templates: the
    wrapper-shaped figure (the vendored hydrator's own markup — decimated
    columns through the landed helper, NaN gaps served as null) and the
    pre-formatted statistics rows (templates stay dumb)."""
    from .plots import PLOT_COLUMNS, decimate_minmax
    from .report import format_number

    capture_id = str(entry["capture_id"])
    unit = str(entry["unit"])
    stats = entry["stats"]
    reduced = decimate_minmax(list(entry["points"]), columns=PLOT_COLUMNS)
    x_values = [t for t, _ in reduced]
    y_values = [None if math.isnan(value) else value for _, value in reduced]
    payload = json.dumps(
        {"channels": [{"id": capture_id, "x": x_values, "y": y_values}], "x_unit": "s"}
    )
    title = str(escape(f"{capture_id} ({unit})"))
    # Fold row 3 + B-F2: EVERY attribute slot escapes what it interpolates
    # — the slug and the unit get the same treatment as the title (the
    # figure block is built inside Markup, so autoescape does not apply;
    # a hostile plugin unit cannot break out of data-bw-axes).
    slug = str(escape(f"analyse-{capture_id}"))
    axes = str(escape(f"s;{unit}"))
    figure = Markup(
        f'<div class="bw-plot-host" data-bw-plot-host '
        f'data-bw-plot-slug="{slug}">\n'
        f'<figure class="bw-plot" role="img" aria-label="{title}">\n'
        f'  <div class="bw-plot__canvas" data-bw-axes="{axes}" '
        f'data-bw-plot-title="{title}"></div>\n'
        f"</figure>\n"
        f'<script type="application/json" data-bw-plot-data>{payload}</script>\n'
        f"</div>"
    )
    return {
        "capture_id": capture_id,
        "unit": unit,
        "sha256": str(entry["sha256"]),
        "figure": figure,
        "count": stats.count,
        "null_count": stats.null_count,
        "window": f"[{format_number(stats.lo)}, {format_number(stats.hi)}]",
        "rows": [
            ("count", f"{stats.count}"),
            ("null_count", f"{stats.null_count}"),
            ("min", format_number(stats.min)),
            ("mean", format_number(stats.mean)),
            ("max", format_number(stats.max)),
            ("rms", format_number(stats.rms)),
            ("peak-to-peak", format_number(stats.pp)),
        ],
    }


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

    def _operator_valid(request: Request) -> bool:
        """Whether the request presented the per-launch operator action
        token (trust-1). Fail-closed on an unminted (empty) policy token —
        including against an empty-string header, which a naive equality
        would accept; constant-time against a minted one."""
        supplied = request.headers.get("x-operator-action-token", "")
        return bool(policy.operator_action_token) and hmac.compare_digest(
            supplied, policy.operator_action_token
        )

    def _launch_token(request: Request) -> str | None:
        """The token an ARMED page view may render into its forms' headers:
        the query parameter, but only when it IS the minted token. A page
        GET without the credential never yields it."""
        supplied = request.query_params.get("operator_action", "")
        if policy.operator_action_token and hmac.compare_digest(
            supplied, policy.operator_action_token
        ):
            return policy.operator_action_token
        return None

    def _index_url(request: Request) -> str:
        """The post-action index URL: the launch query is PRESERVED when
        the acting request carried the token, so the next action on the
        landing page (unbind after bind, re-pick after scan) stays armed."""
        if _operator_valid(request):
            return f"/?operator_action={policy.operator_action_token}"
        return "/"

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

    async def _index_response(
        request: Request,
        *,
        scan_error: dict[str, Any] | None = None,
        binding_error: dict[str, Any] | None = None,
    ) -> Response:
        """The index page's ONE rendering path: the GET view, a refused
        scan and a refused bind/unbind all render here, so a refusal is
        never a silent redirect back (the M1 fold's render-the-refusal
        idiom, carried onto the pick flow)."""
        if seam.transport_kind == "serial":
            # NFR-O3: a page load never transmits — GET serves the LAST
            # discovery result (host state, initially empty with a scan
            # prompt); scanning is the explicit POST below.
            devices = seam.discovery_cache or []
        else:
            devices = (await seam.call("device_discover"))["devices"]
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
                binding_error=binding_error,
                binding=seam.binding_row,
                # trust-1: the armed page view. A GET whose query carries
                # the per-launch operator action token renders it into the
                # bind/unbind forms' headers — a GET WITHOUT it never
                # yields the credential, so no loopback process can scrape
                # what the pages do not carry.
                operator_token=_launch_token(request),
            ),
        )

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> Response:
        return await _index_response(request)

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
            return await _index_response(
                request, scan_error={"code": exc.code, "message": exc.message}
            )
        except (RuntimeError, ValueError, OSError) as exc:
            # The scan's failure classes that raise before any SeamError
            # exists (FOLD-E) render the same typed scan-refused row; the
            # seam maps them for REST and MCP too, so this arm is the
            # route's own defense, not the only reader.
            return await _index_response(
                request, scan_error={"code": "not_ready", "message": str(exc)}
            )
        # The scan itself needs only the CSRF token (it transmits identify
        # probes to candidate ports, but the operator's explicit POST is
        # the act); its redirect keeps the LAUNCH query armed when the
        # armed page sent the request, so pick-after-scan still binds.
        return RedirectResponse(url=_index_url(request), status_code=303)

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
            # operator never gets the silent prompt back instead. The
            # binding reasons ride the error row so the device page can
            # offer the scan-and-re-pick action beside them (#385 §1.4).
            return await _render_device(
                request,
                device_id,
                action_error={
                    "code": exc.code,
                    "message": exc.message,
                    "reason": exc.details.get("reason"),
                },
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

    if seam.transport_kind == "serial":

        @app.post("/devices/{device_id}/bind")
        async def bind_endpoint(request: Request, device_id: str) -> Response:
            """The operator's endpoint pick (issue #385 §1.5): a HOST-side
            route over the seam's bind, not a catalogue operation (the
            scenario-select precedent, D-B1). The credential class is the
            per-launch OPERATOR ACTION TOKEN (trust-1), delivered
            out-of-band — the serve banner and a file under the capture
            root family — never in a page GET: the CSRF token renders into
            unauthenticated HTML, so CSRF alone would let any loopback
            process scrape it and move the physical endpoint subsequent
            writes hit. Neither a bearer-holding agent nor a tokenless
            page-scraping process can bind; the act stays with the
            operator who launched the serve. Binding transmits nothing:
            the pick records what the scan already confirmed."""
            if device_id != seam.session.device_id:
                return HTMLResponse("not found", status_code=404)
            if not _operator_valid(request):
                refusal = await _index_response(
                    request,
                    binding_error={
                        "code": "invalid_request",
                        "message": (
                            "standalone_binding_operator_token_required: "
                            "bind needs the per-launch operator action token "
                            "(the x-operator-action-token header); it is "
                            "printed at serve start and written under the "
                            "capture root — open the launch URL, or append "
                            "?operator_action=<token> to this page"
                        ),
                    },
                )
                refusal.status_code = 403
                return refusal
            form = await request.form()
            try:
                await seam.bind_device(str(form.get("port_path", "")))
            except SeamError as exc:
                return await _index_response(
                    request,
                    binding_error={"code": exc.code, "message": exc.message},
                )
            return RedirectResponse(url=_index_url(request), status_code=303)

        @app.post("/devices/{device_id}/unbind")
        async def unbind_endpoint(request: Request, device_id: str) -> Response:
            """Remove the endpoint binding — the same host-state posture,
            the same conflict-while-connected guard, and the same operator
            action token credential as bind (trust-1)."""
            if device_id != seam.session.device_id:
                return HTMLResponse("not found", status_code=404)
            if not _operator_valid(request):
                refusal = await _index_response(
                    request,
                    binding_error={
                        "code": "invalid_request",
                        "message": (
                            "standalone_binding_operator_token_required: "
                            "unbind needs the per-launch operator action token "
                            "(the x-operator-action-token header); it is "
                            "printed at serve start and written under the "
                            "capture root — open the launch URL, or append "
                            "?operator_action=<token> to this page"
                        ),
                    },
                )
                refusal.status_code = 403
                return refusal
            try:
                await seam.unbind_device()
            except SeamError as exc:
                return await _index_response(
                    request,
                    binding_error={"code": exc.code, "message": exc.message},
                )
            return RedirectResponse(url=_index_url(request), status_code=303)

    # --- the captures library page (I3c, SW-49) ------------------------------

    @app.get("/captures", response_class=HTMLResponse)
    async def captures_page(request: Request) -> Response:
        """The capture library over the landed rows: the closed metadata
        fields, each capture's NEXT retention effect (computed by the same
        evaluator the prune runs — never a second implementation), filters
        over the closed fields, and the pin/unpin/delete forms. Display and
        forms over existing rows: no new catalogue row, no new capability."""
        from datetime import UTC as _UTC
        from datetime import datetime as _datetime

        from .retention import next_effects

        rows = (await seam.call("capture_list", {}))["captures"]
        params = request.query_params
        project = params.get("project") or None
        source = params.get("source") or None
        tag = params.get("tag") or None
        query = (params.get("q") or "").strip().lower() or None
        device = params.get("device") or None
        shown = rows
        if project:
            shown = [row for row in shown if str(row.get("project") or "") == project]
        if source:
            shown = [row for row in shown if str(row.get("surface") or "") == source]
        if tag:
            shown = [row for row in shown if tag in (row.get("tags") or [])]
        if query:
            shown = [
                row
                for row in shown
                if query in str(row.get("capture_id", "")).lower()
                or query in str(row.get("notes", "")).lower()
            ]
        if device:
            # SW-49's device filter reads metadata.json per row at render:
            # the FILE is the authority, the index has no device column and
            # this slice does not widen it (disclosed). A row that NAMES NO
            # DEVICE — sidecar absent, unparseable (it reads as an empty
            # dict) or refused — stays under every filter: a row must never
            # disappear from view without positive evidence that it does
            # not match (the fold wave's row 2 — the keep-on-unreadable
            # claim, now true as coded).
            kept: list[dict[str, Any]] = []
            for row in shown:
                try:
                    fetched = await seam.call(
                        "capture_get", {"capture_id": row["capture_id"]}
                    )
                except SeamError:
                    kept.append(row)
                    continue
                metadata = fetched.get("metadata") or {}
                device_of_row = str((metadata.get("device") or {}).get("id") or "")
                if not device_of_row or device_of_row == device:
                    kept.append(row)
            shown = kept
        rules = seam.retention.rules if seam.retention is not None else ()
        armed = seam.in_flight_capture_id
        effects = next_effects(
            rules,
            rows,
            now=_datetime.now(_UTC),
            in_flight_ids={armed} if armed is not None else frozenset(),
        )
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="captures.html",
            context=shared(
                rows=shown,
                effects=effects,
                filters={
                    "project": project or "",
                    "source": source or "",
                    "tag": tag or "",
                    "q": params.get("q") or "",
                    "device": device or "",
                },
            ),
        )

    @app.get("/captures/{capture_id}/delete", response_class=HTMLResponse)
    async def capture_delete_confirm(
        request: Request, capture_id: str
    ) -> Response:
        """The delete confirmation (SW-59): names the capture id, its size
        and its project — the operator confirms against the real row, never
        a blind submit."""
        rows = (await seam.call("capture_list", {}))["captures"]
        row = next(
            (row for row in rows if str(row["capture_id"]) == capture_id), None
        )
        if row is None:
            return HTMLResponse("not found", status_code=404)
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="capture-delete.html",
            context=shared(row=row),
        )

    @app.post("/captures/{capture_id}/delete")
    async def capture_delete_route(request: Request, capture_id: str) -> Response:
        """The confirmed delete: CSRF'd POST dispatching capture_delete with
        the UI surface (the recorder names delete-ui; neither the UI nor the
        MCP tool bypasses the retention log)."""
        try:
            await _ui_call("capture_delete", {"capture_id": capture_id})
        except SeamError as exc:
            return HTMLResponse(
                f"{exc.code}: {exc.message}",
                status_code=ERROR_HTTP_STATUS[exc.code],
            )
        return RedirectResponse(url="/captures", status_code=303)

    @app.post("/captures/{capture_id}/pin")
    async def capture_pin_route(request: Request, capture_id: str) -> Response:
        # A refused pin (a stale row) redirects — the library re-renders
        # without it, the disconnect idiom.
        with contextlib.suppress(SeamError):
            await _ui_call("capture_pin", {"capture_id": capture_id})
        return RedirectResponse(url="/captures", status_code=303)

    @app.post("/captures/{capture_id}/unpin")
    async def capture_unpin_route(request: Request, capture_id: str) -> Response:
        with contextlib.suppress(SeamError):
            await _ui_call("capture_unpin", {"capture_id": capture_id})
        return RedirectResponse(url="/captures", status_code=303)

    # --- the Analyse view and the report download (I4a, SW-52/53) -----------

    #: The report document's own CSP, stronger than the host default
    #: (NFR-S5): a report is script-free by construction and inlines its
    #: styles — scripts cannot run in a report document at all.
    _REPORT_CSP = "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'"

    async def _window_of(request: Request) -> tuple[list[str], str, str]:
        """The form's selection and window text."""
        form = await request.form()
        selected = [str(value) for value in form.getlist("capture")]
        lo_text = str(form.get("lo") or "").strip()
        hi_text = str(form.get("hi") or "").strip()
        return selected, lo_text, hi_text

    def _parse_window(
        lo_text: str, hi_text: str
    ) -> tuple[float | None, float | None] | dict[str, Any]:
        try:
            lo = float(lo_text) if lo_text else None
            hi = float(hi_text) if hi_text else None
        except ValueError:
            return {
                "code": "invalid_request",
                "message": (
                    "standalone_report_window_invalid: lo/hi must be numbers "
                    f"(got lo={lo_text!r}, hi={hi_text!r})"
                ),
            }
        return _finite_window(lo, hi)

    def _finite_window(
        lo: float | None, hi: float | None
    ) -> tuple[float | None, float | None] | dict[str, Any]:
        """B-F4: non-finite bounds (``nan``/``inf`` parse as floats from
        form text and JSON literals alike) refuse at admission — the
        pre-fold path pinned sources and created the reports/ directory
        before the sidecar serializer crashed on them."""
        for name, value in (("lo", lo), ("hi", hi)):
            if value is not None and not math.isfinite(value):
                return {
                    "code": "invalid_request",
                    "message": (
                        f"standalone_report_window_invalid: {name} {value} "
                        "is not finite; window bounds must be finite numbers"
                    ),
                }
        if lo is not None and hi is not None and lo > hi:
            return {
                "code": "invalid_request",
                "message": (
                    f"standalone_report_window_invalid: lo {lo} exceeds hi {hi}"
                ),
            }
        return lo, hi

    async def _analyse_context(
        selected: list[str], lo_text: str, hi_text: str
    ) -> dict[str, Any]:
        """The analyse page's shared render context: the picker rows over
        the landed capture_list (published waveform captures only — the
        picker never offers a row the analysis would refuse), the current
        selection, and the computed entries (or the rendered refusal)."""
        rows = (await seam.call("capture_list", {}))["captures"]
        picker = [
            row
            for row in rows
            if row.get("state") == "published"
            and row.get("format") == "waveform_f64le"
        ]
        entries: list[dict[str, Any]] = []
        error: dict[str, Any] | None = None
        if selected:
            window = _parse_window(lo_text, hi_text)
            if isinstance(window, dict):
                error = window
            else:
                lo, hi = window
                try:
                    computed = seam.analysis_view(selected, lo, hi)
                    entries = [_figure_entry(entry) for entry in computed]
                except SeamError as exc:
                    error = {"code": exc.code, "message": exc.message}
        return {
            "rows": picker,
            "selected": selected,
            "entries": entries,
            "analyse_error": error,
            "lo": lo_text,
            "hi": hi_text,
        }

    @app.get("/analyse", response_class=HTMLResponse)
    async def analyse_page(request: Request) -> Response:
        """The Analyse view: the capture picker over the landed captures
        list, the numeric window (the no-script path — analyse.js adds the
        drag-brush on the plot), and the server-computed statistics under
        definition benchweave-analysis/1."""
        selected = [str(value) for value in request.query_params.getlist("capture")]
        context = await _analyse_context(
            selected,
            str(request.query_params.get("lo") or "").strip(),
            str(request.query_params.get("hi") or "").strip(),
        )
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="analyse.html",
            context=shared(**context),
        )

    @app.post("/analyse/stats", response_class=HTMLResponse)
    async def analyse_stats(request: Request) -> Response:
        """The stats partial (the htmx swap target): the same computation
        the GET renders inline — one code path, two entry points."""
        selected, lo_text, hi_text = await _window_of(request)
        context = await _analyse_context(selected, lo_text, hi_text)
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="analyse-results.html",
            context=shared(**context),
        )

    @app.post("/analyse/export")
    async def analyse_export(request: Request) -> Response:
        """Export the report over the ``report_export`` catalogue row and
        land on the download; a refused export renders its refusal (the
        delete route's idiom — never a silent redirect)."""
        selected, lo_text, hi_text = await _window_of(request)
        window = _parse_window(lo_text, hi_text)
        if isinstance(window, dict):
            return HTMLResponse(
                f"{window['code']}: {window['message']}",
                status_code=ERROR_HTTP_STATUS[str(window["code"])],
            )
        lo, hi = window
        arguments: dict[str, Any] = {"capture_ids": selected}
        if lo is not None:
            arguments["lo"] = lo
        if hi is not None:
            arguments["hi"] = hi
        try:
            result = await _ui_call("report_export", arguments)
        except SeamError as exc:
            return HTMLResponse(
                f"{exc.code}: {exc.message}",
                status_code=ERROR_HTTP_STATUS[exc.code],
            )
        return RedirectResponse(
            url=f"/reports/{result['report_id']}", status_code=303
        )

    @app.get("/reports/{report_id}", response_class=HTMLResponse)
    async def report_download(report_id: str) -> Response:
        """Serve the persisted report from the capture root. The id
        pattern (rep-<16 hex>, the seam's own check) is the whole
        traversal defense; the document carries its own stricter CSP."""
        path = seam.report_file(report_id)
        if path is None:
            return HTMLResponse("not found", status_code=404)
        response = HTMLResponse(path.read_text(encoding="utf-8"))
        response.headers["Content-Security-Policy"] = _REPORT_CSP
        return response


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


def _add_events_route(
    app: FastAPI, seam: StandaloneSeam, *, streams_closing: Any = None
) -> None:
    """The SSE stream over the SAME sequence ``events_get`` serves (I2c
    §4.2): the browser, REST watchers and MCP see one order. Reconnecting
    clients resume from ``Last-Event-ID`` (the htmx SSE extension sends
    it) or the ``after_id`` query parameter.

    ``streams_closing`` (S2, the gateway's F2 twin): the supervised
    serve's stop decision sets it and every live stream ends at its next
    poll boundary — an open events tab can never hang the drain into the
    kill rung. ``None`` (every non-supervised composition) keeps the
    stream unbounded, exactly as before."""

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
            while streams_closing is None or not streams_closing.is_set():
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
