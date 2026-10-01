"""The seam's error object and its interface-0.1.0-derived status map.

The operation vocabulary is the closed interface-0.1.0 subset the PRD names
(SW-11): ``invalid_request``, ``not_found``, ``conflict``, ``not_ready``,
``payload_too_large``, ``unavailable``, ``internal_error``. There is no policy
engine, credential tier or lease lifecycle here, so ``unauthenticated``,
``forbidden``, ``policy_denied`` and the lease/gone codes are structurally
absent from :data:`ERROR_CODES` — a refusal cannot name what the host cannot
mean. The HTTP status for each code is the vendored interface catalog's own
``error_http_status`` row, mirrored here as data and pinned against the
vendored file by test (one reader, no local copy of the standard: the pin
test reads the digest-verified vendored catalog through the SDK).

Guard-layer refusals (trusted-Host, CSRF, bearer, MCP token/Origin) are HTTP
security responses, not seam operations; they use their own
``standalone_*``-prefixed error names and 403/413 statuses the same way the
SDK preview server's guards do.
"""

from __future__ import annotations

from typing import Any

#: The closed error-code vocabulary for every seam operation (SW-11). The
#: pin test asserts this set against the vendored interface catalog.
ERROR_CODES: frozenset[str] = frozenset(
    {
        "invalid_request",
        "not_found",
        "conflict",
        "not_ready",
        "payload_too_large",
        "unavailable",
        "internal_error",
    }
)

#: Each code's HTTP status, from the vendored interface catalog's
#: ``error_http_status`` rows for exactly these seven codes.
ERROR_HTTP_STATUS: dict[str, int] = {
    "invalid_request": 400,
    "not_found": 404,
    "conflict": 409,
    "not_ready": 409,
    "payload_too_large": 413,
    "unavailable": 503,
    "internal_error": 500,
}


class SeamError(Exception):
    """A refused operation: an interface-0.1.0 code, a message, a correlation.

    ``details`` carries the refusal's specifics — for adapter-reported
    failures it preserves the adapter's own envelope verbatim (``status``,
    ``error.code``, ``dispatch_state``) so permission, transport and device
    rejection stay distinct outcomes end to end (SW-12).
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        correlation_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        if code not in ERROR_CODES:
            raise ValueError(f"standalone_error_code_unknown: {code}")
        self.code = code
        self.message = message
        self.correlation_id = correlation_id
        self.details = details or {}

    def body(self) -> dict[str, Any]:
        """The wire error object: correlation id plus the error envelope."""
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            error["details"] = self.details
        if self.correlation_id:
            return {"correlation_id": self.correlation_id, "error": error}
        return {"error": error}
