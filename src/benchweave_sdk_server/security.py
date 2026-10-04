"""The guard set: individually omittable middleware objects (NFR-S1–S6).

Each guard is its own class and its own ``enable_*`` flag so an acceptance
RED arm can construct an app minus exactly one guard and prove that guard —
not something incidental — is the mechanism that stops its attack. The
``serve`` CLI always builds the complete set (a separate test pins that).

What the guards do NOT catch (the honest residual):

- ``BodyCapGuard`` pre-checks the ``Content-Length`` header, matching the
  SDK preview server's posture; a chunked body sent without that header is
  not pre-refused here (the routes still parse it through the framework).
- ``McpGuard`` judges the ``Origin`` header only when a client sends one —
  non-browser MCP clients do not; browsers cannot omit it on cross-origin
  POSTs, which is the attack class the guard exists for.
- The stdio MCP entry and in-process MCP clients never traverse these HTTP
  guards (NFR-S4: no socket, no listener).
"""

from __future__ import annotations

import ipaddress
import secrets
from dataclasses import dataclass, replace

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

#: The request-body cap (NFR-S6), owned here since 0.7.0: moved verbatim
#: from ``benchweave_sdk.preview_server`` when the frozen renderer bundle was
#: deleted (issue #308); the guard module is the surviving owner of the
#: listener/body rules the standalone host enforces.
MAX_REQUEST_BYTES = 64 * 1024


def validate_listener(host: str, allow_network: bool) -> None:
    """Reject wildcard listeners and require acknowledgement outside loopback.

    Moved verbatim from ``benchweave_sdk.preview_server`` at 0.7.0 (issue
    #308): what NFR-S1 called verbatim reuse is ownership — ``serve`` and the
    ``preview-ui`` shim both route their ``--host``/``--allow-network`` rules
    through here. The ``preview_`` refusal prefixes are recorded lineage.
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError(f"preview_invalid_listener: {host}") from exc
    if address.is_unspecified:
        raise ValueError(f"preview_unsafe_listener: wildcard address {host} is prohibited")
    if not address.is_loopback and not allow_network:
        raise ValueError(
            f"preview_network_acknowledgement_required: {host} requires --allow-network"
        )


CSP_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'"
)

_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


def new_token() -> str:
    """A per-launch URL-safe secret (bearer and CSRF tokens)."""
    return secrets.token_urlsafe(32)


@dataclass(frozen=True, slots=True)
class GuardPolicy:
    """Which guards are armed, and the material they check against.

    ``complete()`` builds the full set; ``replace(policy, enable_x=False)``
    builds the minus-one RED arms.
    """

    bound_host: str
    bound_port: int
    bearer_token: str
    csrf_token: str
    enable_trusted_host: bool = True
    enable_csrf: bool = True
    enable_bearer: bool = True
    enable_mcp_guard: bool = True
    enable_body_cap: bool = True
    enable_csp: bool = True

    @classmethod
    def complete(
        cls, bound_host: str, bound_port: int, bearer_token: str, csrf_token: str
    ) -> GuardPolicy:
        return cls(
            bound_host=bound_host,
            bound_port=bound_port,
            bearer_token=bearer_token,
            csrf_token=csrf_token,
        )

    def minus(self, flag: str) -> GuardPolicy:
        """The same policy with exactly one guard disarmed (test harness)."""
        # ``replace`` cannot express a dynamically-keyed kwarg; the flag set
        # is the frozen field list above and the value is always bool.
        return replace(self, **{flag: False})  # type: ignore[arg-type]


def _guard_error(name: str, status: int = 403) -> JSONResponse:
    return JSONResponse({"error": name}, status_code=status)


class TrustedHostGuard(BaseHTTPMiddleware):
    """Refuse DNS-rebinding: the Host header must name this listener.

    Ports ``preview_server``'s ``_handler._host_is_trusted`` logic (bracketed
    IPv6, port match, ``localhost`` implies loopback-bound) onto the ASGI
    stack; it covers HTML, ``/v1`` and ``/mcp`` alike.
    """

    def __init__(self, app: object, bound_host: str, bound_port: int) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._bound_host = bound_host
        self._bound_port = bound_port

    def _trusted(self, header: str) -> bool:
        try:
            bound_loopback = ipaddress.ip_address(self._bound_host).is_loopback
        except ValueError:
            bound_loopback = False
        if header.startswith("["):
            closing = header.find("]")
            if closing < 0:
                return False
            name = header[1:closing]
            port = header[closing + 1 :].lstrip(":")
        else:
            name, separator, port = header.partition(":")
            if not separator:
                return False
        if not port.isdigit() or int(port) != int(self._bound_port):
            return False
        if name.lower() == "localhost":
            return bound_loopback
        try:
            return ipaddress.ip_address(name).is_loopback and bound_loopback
        except ValueError:
            return name == self._bound_host

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not self._trusted(request.headers.get("host", "")):
            return _guard_error("standalone_invalid_host")
        return await call_next(request)


class BodyCapGuard(BaseHTTPMiddleware):
    """Refuse oversized request bodies before they are read (413)."""

    def __init__(self, app: object, limit: int = MAX_REQUEST_BYTES) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._limit = limit

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        length = request.headers.get("content-length")
        if (
            request.method in _STATE_CHANGING
            and length is not None
            and (not length.isdigit() or int(length) > self._limit)
        ):
            return JSONResponse(
                {
                    "error": {
                        "code": "payload_too_large",
                        "message": f"body exceeds {self._limit} bytes",
                    }
                },
                status_code=413,
            )
        return await call_next(request)


class CsrfGuard(BaseHTTPMiddleware):
    """State-changing HTML routes must carry the page-delivered CSRF token.

    Applies to state-changing requests outside ``/v1`` and ``/mcp`` (those
    carry their own credentials); the token rides HTMX ``hx-headers`` and is
    rendered into every page (NFR-S3).
    """

    def __init__(self, app: object, csrf_token: str) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._token = csrf_token

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        html_mutation = (
            request.method in _STATE_CHANGING
            and not path.startswith("/v1")
            and not path.startswith("/mcp")
        )
        if html_mutation and request.headers.get("x-csrf-token") != self._token:
            return _guard_error("standalone_csrf_required")
        return await call_next(request)


class BearerGuard(BaseHTTPMiddleware):
    """REST mutations require the per-launch bearer token (NFR-S3)."""

    def __init__(self, app: object, bearer_token: str) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._token = bearer_token

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method in _STATE_CHANGING and request.url.path.startswith("/v1"):
            header = request.headers.get("authorization", "")
            if header != f"Bearer {self._token}":
                return _guard_error("standalone_bearer_required")
        return await call_next(request)


def _origin_is_loopback(origin: str) -> bool:
    from urllib.parse import urlsplit

    parts = urlsplit(origin)
    if parts.scheme != "http" or parts.hostname is None:
        return False
    try:
        return ipaddress.ip_address(parts.hostname).is_loopback
    except ValueError:
        return parts.hostname == "localhost"


class McpGuard(BaseHTTPMiddleware):
    """MCP over HTTP: loopback origins only, plus the per-launch token.

    Fail-closed ahead of the FastMCP app (the CON-6 shape at one layer):
    a rejected request never reaches a tool. The token requirement matches
    the REST bearer; the Origin check allows only loopback origins when a
    client sends one (NFR-S4). The stdio entry never traverses this guard.
    """

    def __init__(self, app: object, bearer_token: str) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._token = bearer_token

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not request.url.path.startswith("/mcp"):
            return await call_next(request)
        origin = request.headers.get("origin")
        if origin is not None and not _origin_is_loopback(origin):
            return _guard_error("standalone_origin_not_allowed")
        header = request.headers.get("authorization", "")
        if header != f"Bearer {self._token}":
            return _guard_error("standalone_mcp_token_required")
        return await call_next(request)


class SecurityHeadersGuard(BaseHTTPMiddleware):
    """CSP on HTML responses; no CORS header is ever set (NFR-S5)."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            response.headers["Content-Security-Policy"] = CSP_POLICY
        return response


def install_guards(app: object, policy: GuardPolicy) -> None:
    """Add the armed guards to ``app`` in the fail-closed order.

    Starlette applies middleware last-added-first, so the ordering below runs
    ``TrustedHostGuard`` outermost (rebinding refused before anything else),
    then the body cap, then the route-class credentials, with the response
    headers innermost.
    """
    from fastapi import FastAPI

    assert isinstance(app, FastAPI)
    if policy.enable_csp:
        app.add_middleware(SecurityHeadersGuard)
    if policy.enable_mcp_guard:
        app.add_middleware(McpGuard, bearer_token=policy.bearer_token)
    if policy.enable_bearer:
        app.add_middleware(BearerGuard, bearer_token=policy.bearer_token)
    if policy.enable_csrf:
        app.add_middleware(CsrfGuard, csrf_token=policy.csrf_token)
    if policy.enable_body_cap:
        app.add_middleware(BodyCapGuard)
    if policy.enable_trusted_host:
        app.add_middleware(
            TrustedHostGuard, bound_host=policy.bound_host, bound_port=policy.bound_port
        )
