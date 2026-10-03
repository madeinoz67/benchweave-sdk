"""The operations seam: the only mutation path, shared by REST, HTML and MCP.

A13's one-contract rule applied to standalone: every surface is an adapter
over :meth:`StandaloneSeam.call`; no route, tool or template touches the
adapter directly. The seam owns the closed refusal model —

- an operation name outside the catalogue is ``invalid_request`` (the client
  asked for something the contract does not contain);
- a declared but unimplemented operation is ``unavailable`` with a
  ``reason: increment_deferral`` detail (never silently absent);
- arguments are validated against the catalogue's input schema
  (``invalid_request`` with the validator's findings);
- adapter-reported failures surface with their envelope preserved verbatim in
  ``details`` (``status``, ``error.code``, ``dispatch_state``) so permission,
  transport and device rejection stay distinct outcomes end to end (SW-12,
  REG-2's ambiguity-preservation as the pass-through rule);
- exceptions escaping the adapter map honestly: a ``ConformanceError`` is the
  scripted transport refusing an exchange (exhausted or mismatched —
  ``unavailable``); ``TimeoutError``/``ConnectionError`` are ``not_ready``
  (NFR-O2: transport loss and expiry are not-ready outcomes); anything else
  is ``internal_error``.
"""

from __future__ import annotations

import asyncio
import uuid
from importlib import metadata
from typing import Any, cast

from benchweave_sdk.testing import ConformanceError

from . import catalogue
from .errors import SeamError
from .session import PluginSession

#: Adapter envelope error codes → interface codes (SW-12 distinctness kept:
#: the adapter's own code and dispatch_state ride in ``details`` verbatim).
_ADAPTER_CODE_MAP: dict[str, str] = {
    "INVALID_ARGUMENT": "invalid_request",
    "UNSUPPORTED": "invalid_request",
    "TIMEOUT": "not_ready",
    "TRANSPORT_ERROR": "not_ready",
    "PROTOCOL_ERROR": "unavailable",
    "INTERNAL_ERROR": "internal_error",
}


def sdk_version() -> str:
    """The SDK version this host runs on, derived — never a literal."""
    try:
        return metadata.version("benchweave-sdk")
    except metadata.PackageNotFoundError:  # pragma: no cover - dev-checkout edge
        return "unknown"


class StandaloneSeam:
    """One seam over one adapter session; the surfaces are its adapters."""

    def __init__(self, session: PluginSession, *, transport_kind: str) -> None:
        self._session = session
        self._transport_kind = transport_kind

    @property
    def session(self) -> PluginSession:
        return self._session

    @property
    def transport_kind(self) -> str:
        return self._transport_kind

    def _correlation(self, supplied: str | None) -> str:
        return supplied or f"bws-{uuid.uuid4().hex[:12]}"

    def _fail(
        self, code: str, message: str, correlation_id: str, **details: Any
    ) -> SeamError:
        return SeamError(code, message, correlation_id=correlation_id, details=details)

    async def call(
        self,
        operation: str,
        arguments: dict[str, Any] | None = None,
        *,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute one catalogue operation; return its data or raise ``SeamError``."""
        correlation = self._correlation(correlation_id)
        row = catalogue.spec(operation)
        if row is None:
            raise self._fail(
                "invalid_request",
                f"unknown operation: {operation}",
                correlation,
                closed_catalogue=catalogue.deferred_operations() + catalogue.served_operations(),
            )
        if not row.implemented:
            raise self._fail(
                "unavailable",
                f"operation not implemented in this increment: {operation}",
                correlation,
                reason="increment_deferral",
            )
        self._validate(row.name, arguments or {}, correlation)
        handler = getattr(self, f"_op_{row.name}")
        result = await handler(arguments or {}, correlation)
        return cast(dict[str, Any], result)

    def _validate(self, name: str, arguments: dict[str, Any], correlation: str) -> None:
        from jsonschema import Draft202012Validator

        row = catalogue.spec(name)
        assert row is not None and row.implemented
        validator = Draft202012Validator(row.input_schema)
        findings = sorted(validator.iter_errors(arguments), key=lambda e: list(e.absolute_path))
        if findings:
            raise self._fail(
                "invalid_request",
                "arguments failed schema validation",
                correlation,
                findings=[
                    {"path": list(error.absolute_path), "message": error.message}
                    for error in findings
                ],
            )

    # --- handlers ----------------------------------------------------------

    async def _op_host_info(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        plugin = self._session.plugin
        return {
            "mode": "standalone",
            "absent_guarantees": list(catalogue.ABSENT_GUARANTEES),
            "served_operations": list(catalogue.served_operations()),
            "deferred_operations": list(catalogue.deferred_operations()),
            "plugin": {
                "package": plugin.package,
                "version": plugin.plugin_version,
                "descriptor_sha256": plugin.descriptor_sha256,
            },
            "transport": self._transport_kind,
            "sdk_version": sdk_version(),
        }

    async def _op_device_discover(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        descriptor = self._session.plugin.descriptor
        identity = descriptor.get("identity", {})
        transport = descriptor.get("transport", {})
        return {
            "devices": [
                {
                    "id": self._session.device_id,
                    "manufacturer": str(identity.get("manufacturer", "")),
                    "model": str(identity.get("model", "")),
                    "transport": str(transport.get("type", "")),
                    "connection_key": str(transport.get("connection_key", "")),
                }
            ]
        }

    async def _op_device_connect(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        if arguments["device_id"] != self._session.device_id:
            raise self._fail(
                "not_found", f"no such device: {arguments['device_id']}", correlation
            )
        if self._session.connected:
            raise self._fail(
                "conflict",
                f"device already connected: {arguments['device_id']}",
                correlation,
            )
        try:
            await self._session.connect()
        except ConformanceError as exc:
            raise self._fail(
                "unavailable", f"transport refused the exchange: {exc}", correlation
            ) from exc
        except (TimeoutError, ConnectionError) as exc:
            raise self._fail(
                "not_ready", f"device not ready: {exc}", correlation
            ) from exc
        except RuntimeError as exc:
            raise self._fail("not_ready", str(exc), correlation) from exc
        return {"device_id": self._session.device_id, "connected": True}

    async def _op_device_disconnect(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        if arguments["device_id"] != self._session.device_id:
            raise self._fail(
                "not_found", f"no such device: {arguments['device_id']}", correlation
            )
        await self._session.close()
        return {"device_id": self._session.device_id, "connected": False}

    async def _op_device_get(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        if arguments["device_id"] != self._session.device_id:
            raise self._fail(
                "not_found", f"no such device: {arguments['device_id']}", correlation
            )
        if not self._session.connected:
            raise self._fail(
                "not_ready", "device is not connected", correlation
            )
        if self._session.identity is None:
            raise self._fail(
                "not_ready", "device identity not established", correlation
            )
        return dict(self._session.identity)

    async def _op_parameter_read(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        if arguments["device_id"] != self._session.device_id:
            raise self._fail(
                "not_found", f"no such device: {arguments['device_id']}", correlation
            )
        if not self._session.connected:
            raise self._fail("not_ready", "device is not connected", correlation)
        name = arguments["parameter"]
        known = {
            row.get("name"): row
            for row in self._session.plugin.readable_parameters
        }
        if name not in known:
            raise self._fail(
                "not_found",
                f"no such readable parameter: {name}",
                correlation,
            )
        return await self._execute("read", {"parameter": name}, correlation)

    # --- adapter envelope handling -----------------------------------------

    async def _execute(
        self, verb: str, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        """Run one adapter envelope and map its outcome honestly."""
        try:
            envelope = await self._session.execute(verb, arguments)
        except ConformanceError as exc:
            raise self._fail(
                "unavailable",
                f"transport refused the exchange: {exc}",
                correlation,
            ) from exc
        except (TimeoutError, ConnectionError) as exc:
            raise self._fail(
                "not_ready", f"device not ready: {exc}", correlation
            ) from exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the honest internal bucket
            raise SeamError(
                "internal_error",
                f"unexpected adapter failure: {exc}",
                correlation_id=correlation,
            ) from exc

        status = envelope.get("status")
        if status == "ok":
            data = envelope.get("data")
            if not isinstance(data, dict):
                raise SeamError(
                    "internal_error",
                    "adapter returned no data object",
                    correlation_id=correlation,
                )
            return data
        error = envelope.get("error") or {}
        adapter_code = str(error.get("code", ""))
        code = _ADAPTER_CODE_MAP.get(adapter_code, "internal_error")
        raise self._fail(
            code,
            str(error.get("message", "adapter reported failure")),
            correlation,
            adapter={
                "status": status,
                "code": adapter_code,
                "dispatch_state": error.get("dispatch_state"),
            },
        )
