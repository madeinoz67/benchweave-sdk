"""The MCP surface: one ``bws_v1_*`` tool per implemented catalogue operation.

The namespace is the PRD's Q4 recommendation (own prefix, interface-0.1.0
shapes where semantics match) so an agent cannot assume gateway guarantees
from familiar ``stg_v1_*`` names. Schemas are handed over from the catalogue
explicitly — never inferred from the Python signature: fastmcp 4.0.3's
inference cannot reproduce authored schemas (the gateway's Task-1 spike
verdict, pydantic never emitting an empty ``required``), so registration
follows the gateway's mandated construction — ``mcp.tool(fn, name=...,
description=...)`` then a pin pass that fetches each Tool and assigns
``parameters``/``output_schema`` from the catalogue verbatim, self-checking
that the pin took. The same pin is what gate F reads back.

Authoring tools (SW-35/NFR-S8) exist only when the host starts with
``--authoring``: without the flag they are absent from the tool list, not
refused on call — pinned by test.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

from fastmcp import FastMCP
from fastmcp.tools import ToolResult

from . import catalogue
from .errors import SeamError
from .seam import StandaloneSeam

_NAME_PREFIX = "bws_v1"


def tool_name(operation: str) -> str:
    """The served tool name for one catalogue operation."""
    return f"{_NAME_PREFIX}_{operation}"


def _tool_handlers(seam: StandaloneSeam) -> dict[str, Callable[..., Any]]:
    """One named async function per implemented operation.

    fastmcp 4.0.3 refuses ``**kwargs``-only functions as tools, so each
    operation gets a real signature whose parameters are exactly its
    catalogue input-schema keys; the schemas themselves are still pinned
    from the catalogue by :func:`_pin_all` (inference is never the wire
    authority). A catalogue row implemented without a handler here fails
    construction loudly — the closed set cannot drift silently.
    """

    async def host_info() -> Any:
        return await _dispatch(seam, "host_info", {})

    async def device_discover() -> Any:
        return await _dispatch(seam, "device_discover", {})

    async def device_connect(device_id: str) -> Any:
        return await _dispatch(seam, "device_connect", {"device_id": device_id})

    async def device_disconnect(device_id: str) -> Any:
        return await _dispatch(seam, "device_disconnect", {"device_id": device_id})

    async def device_get(device_id: str) -> Any:
        return await _dispatch(seam, "device_get", {"device_id": device_id})

    async def parameter_read(device_id: str, parameter: str) -> Any:
        return await _dispatch(
            seam, "parameter_read", {"device_id": device_id, "parameter": parameter}
        )

    async def parameter_stage(
        device_id: str, parameter: str, value: float | str | bool
    ) -> Any:
        return await _dispatch(
            seam,
            "parameter_stage",
            {"device_id": device_id, "parameter": parameter, "value": value},
        )

    async def parameter_apply(device_id: str) -> Any:
        return await _dispatch(seam, "parameter_apply", {"device_id": device_id})

    async def preset_list() -> Any:
        return await _dispatch(seam, "preset_list", {})

    async def preset_apply(device_id: str, preset_id: str) -> Any:
        return await _dispatch(
            seam, "preset_apply", {"device_id": device_id, "preset_id": preset_id}
        )

    async def events_get(after_id: int) -> Any:
        return await _dispatch(seam, "events_get", {"after_id": after_id})

    async def capture_start(
        device_id: str,
        count: int | None = None,
        duration_s: float | None = None,
        format: str = "raw_binary",
        sample_interval_s: float | None = None,
        unit: str | None = None,
        max_bytes: int | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
        notes: str | None = None,
    ) -> Any:
        arguments: dict[str, Any] = {
            "device_id": device_id,
            "format": format,
        }
        if count is not None:
            arguments["count"] = count
        if duration_s is not None:
            arguments["duration_s"] = duration_s
        if sample_interval_s is not None:
            arguments["sample_interval_s"] = sample_interval_s
        if unit is not None:
            arguments["unit"] = unit
        if max_bytes is not None:
            arguments["max_bytes"] = max_bytes
        if project is not None:
            arguments["project"] = project
        if tags is not None:
            arguments["tags"] = tags
        if notes is not None:
            arguments["notes"] = notes
        return await _dispatch(seam, "capture_start", arguments)

    async def capture_stop(capture_id: str) -> Any:
        return await _dispatch(seam, "capture_stop", {"capture_id": capture_id})

    async def capture_list() -> Any:
        return await _dispatch(seam, "capture_list", {})

    async def capture_get(capture_id: str) -> Any:
        return await _dispatch(seam, "capture_get", {"capture_id": capture_id})

    async def capture_series(capture_id: str, max_points: int = 2000) -> Any:
        return await _dispatch(
            seam,
            "capture_series",
            {"capture_id": capture_id, "max_points": max_points},
        )

    async def capture_annotate(
        capture_id: str, notes: str | None = None, tags: list[str] | None = None
    ) -> Any:
        arguments: dict[str, Any] = {"capture_id": capture_id}
        if notes is not None:
            arguments["notes"] = notes
        if tags is not None:
            arguments["tags"] = tags
        return await _dispatch(seam, "capture_annotate", arguments)

    async def capture_analysis(
        capture_id: str, markers: list[dict[str, Any]]
    ) -> Any:
        return await _dispatch(
            seam,
            "capture_analysis",
            {"capture_id": capture_id, "markers": markers},
        )

    async def capture_pin(capture_id: str) -> Any:
        return await _dispatch(seam, "capture_pin", {"capture_id": capture_id})

    async def capture_unpin(capture_id: str) -> Any:
        return await _dispatch(seam, "capture_unpin", {"capture_id": capture_id})

    async def capture_delete(capture_id: str) -> Any:
        return await _dispatch(seam, "capture_delete", {"capture_id": capture_id})

    async def artifact_read(capture_id: str, offset: int, length: int) -> Any:
        return await _dispatch(
            seam,
            "artifact_read",
            {"capture_id": capture_id, "offset": offset, "length": length},
        )

    async def report_export(
        capture_ids: list[str],
        lo: float | None = None,
        hi: float | None = None,
        markers: list[dict[str, Any]] | None = None,
        assertions: list[dict[str, Any]] | None = None,
        settle_pct: float | None = None,
        power: dict[str, Any] | None = None,
    ) -> Any:
        arguments: dict[str, Any] = {"capture_ids": capture_ids}
        if lo is not None:
            arguments["lo"] = lo
        if hi is not None:
            arguments["hi"] = hi
        if markers is not None:
            arguments["markers"] = markers
        if assertions is not None:
            arguments["assertions"] = assertions
        if settle_pct is not None:
            arguments["settle_pct"] = settle_pct
        if power is not None:
            arguments["power"] = power
        return await _dispatch(seam, "report_export", arguments)

    handlers: dict[str, Callable[..., Any]] = {
        "host_info": host_info,
        "device_discover": device_discover,
        "device_connect": device_connect,
        "device_disconnect": device_disconnect,
        "device_get": device_get,
        "parameter_read": parameter_read,
        "parameter_stage": parameter_stage,
        "parameter_apply": parameter_apply,
        "preset_list": preset_list,
        "preset_apply": preset_apply,
        "events_get": events_get,
        "capture_start": capture_start,
        "capture_stop": capture_stop,
        "capture_list": capture_list,
        "capture_get": capture_get,
        "capture_series": capture_series,
        "capture_annotate": capture_annotate,
        "capture_analysis": capture_analysis,
        "capture_pin": capture_pin,
        "capture_unpin": capture_unpin,
        "capture_delete": capture_delete,
        "artifact_read": artifact_read,
        "report_export": report_export,
    }
    missing = set(catalogue.served_operations()) - set(handlers)
    extra = set(handlers) - set(catalogue.served_operations())
    if missing or extra:
        raise RuntimeError(
            f"standalone_tool_handlers_drift: missing={sorted(missing)} extra={sorted(extra)}"
        )
    return handlers


def _register_operation_tool(
    mcp: FastMCP, handler: Callable[..., Any], row: catalogue.OperationSpec
) -> None:
    name = tool_name(row.name)
    handler.__name__ = name
    handler.__doc__ = row.description
    mcp.tool(handler, name=name, description=row.description)


async def _dispatch(seam: StandaloneSeam, operation: str, arguments: dict[str, Any]) -> Any:
    """Run one operation; failures surface as error ToolResults, not crashes.

    Success returns the result data directly: the pinned ``output_schema``
    IS the operation's result schema, so any envelope wrapper here would
    fail the served schema.
    """
    from uuid import uuid4

    try:
        return await seam.call(
            operation,
            arguments,
            correlation_id=f"mcp-{uuid4().hex[:12]}",
            surface="mcp",
        )
    except SeamError as exc:
        return ToolResult(structured_content=exc.body(), is_error=True)


_PIN_EXECUTOR: ThreadPoolExecutor | None = None


def _run(coro_factory: Callable[[], Any]) -> Any:
    """Run a coroutine to completion even when a loop already runs here.

    Construction-time helpers (the pin pass, tool-name readback) are sync
    APIs; inside a running loop they hop to a worker thread's own loop.
    """
    global _PIN_EXECUTOR
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())
    if _PIN_EXECUTOR is None:
        _PIN_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bws-pin")
    return _PIN_EXECUTOR.submit(asyncio.run, coro_factory()).result()


def _pin_all(mcp: FastMCP) -> None:
    """Pin each registered tool's schemas from the catalogue (Task-1 shape).

    The pass needs a fresh event loop for ``get_tool``; when construction
    itself happens inside a running loop (async test or app builder), the
    pin runs on a single worker thread's own loop instead. The self-check
    raises so a pin that silently failed can never serve (it survives
    ``python -O``).
    """

    async def _pin() -> None:
        for row in catalogue.CATALOGUE:
            if not row.implemented:
                continue
            name = tool_name(row.name)
            tool = await mcp.get_tool(name)
            if tool is None:
                raise RuntimeError(f"{name} not registered")
            tool.parameters = dict(row.input_schema)
            pinned_output = {**dict(row.result_schema), "type": "object"}
            tool.output_schema = pinned_output
            if tool.parameters != row.input_schema or tool.output_schema != pinned_output:
                raise RuntimeError(f"{name}: schema pin did not take")

    _run(_pin)


def build_mcp(seam: StandaloneSeam, *, authoring: bool = False) -> FastMCP:
    """Build the MCP server over the seam; authoring tools only on request."""
    mcp = FastMCP(
        # Issue #309 slice A, fold F1: serverInfo.name is wire-visible —
        # the distribution the host rides, not the dead sibling's name
        # (the A-R dash-token grep pins the tree; test_mcp pins the object).
        "benchweave-sdk-server",
        instructions=(
            "Standalone BenchWeave host. No gateway: no leases, policy, "
            "approvals, procedures or run records (host_info states the same "
            "absent guarantees)."
        ),
    )
    handlers = _tool_handlers(seam)
    for row in catalogue.CATALOGUE:
        if row.implemented:
            _register_operation_tool(mcp, handlers[row.name], row)
    if authoring:
        from .authoring import register_authoring_tools

        register_authoring_tools(mcp, seam=seam)
    _pin_all(mcp)
    return mcp


def registered_tool_names(mcp: FastMCP) -> list[str]:
    """The served tool names, sorted (the gate-F readback helper)."""

    async def _names() -> list[str]:
        tools = await mcp.list_tools()
        return sorted(str(tool.name) for tool in tools)

    return cast("list[str]", _run(_names))


def operation_tool_schema(mcp: FastMCP, name: str) -> catalogue.OperationSpec | None:
    """Read one tool's pinned schemas back as a catalogue-shaped object."""

    async def _read() -> catalogue.OperationSpec | None:
        tool = await mcp.get_tool(name)
        if tool is None:
            return None
        return catalogue.OperationSpec(
            name=name.removeprefix(f"{_NAME_PREFIX}_"),
            implemented=True,
            description=tool.description or "",
            input_schema=dict(tool.parameters or {}),
            result_schema=dict(tool.output_schema or {}),
        )

    return cast("catalogue.OperationSpec | None", _run(_read))
