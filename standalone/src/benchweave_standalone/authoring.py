"""Authoring tools: the SDK's functions, not its CLI text (SW-35/NFR-S8).

``plugin_new`` composes ``scaffold.create_project`` with
``presentation.create_ui_resources`` exactly as the SDK's ``new --with-ui``
does; ``plugin_check`` runs ``validation.validate_descriptor``;
``ui_check`` runs the ``presentation.check_ui`` path with the plugin's real
document paths. Results carry the SDK's own diagnostic surface (validator
findings with their codes and paths, scaffold refusal messages) — nothing is
re-worded. The tools are registered only when the host starts with
``--authoring``; without it they are absent from the tool list (test-pinned).
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

from benchweave_sdk.scaffold import create_project
from benchweave_sdk.validation import YankedPinWarning, validate_descriptor
from fastmcp import FastMCP
from fastmcp.tools import ToolResult


def _error(message: str, **details: Any) -> ToolResult:
    return ToolResult(
        structured_content={"error": {"code": "invalid_request", "message": message,
                                       **({"details": details} if details else {})}},
        is_error=True,
    )


def _plugin_new(destination: str, package: str, with_ui: bool) -> dict[str, Any]:
    """Scaffold a project; return the created file inventory."""
    from benchweave_sdk.presentation import create_ui_resources

    target = Path(destination).expanduser().resolve()
    create_project(target, package)
    if with_ui:
        create_ui_resources(target, package)
    files = sorted(
        str(path.relative_to(target)) for path in target.rglob("*") if path.is_file()
    )
    return {"created": str(target), "package": package, "files": files}


def _plugin_check(descriptor_path: str) -> dict[str, Any]:
    """Validate one descriptor with the SDK checker; report its surface."""
    from benchweave_sdk.presentation import read_file

    path = Path(descriptor_path).expanduser().resolve()
    try:
        raw = read_file(path)
        document = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"valid": False, "path": str(path), "error": str(exc)}
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        try:
            validate_descriptor(document)
        except (ValueError, KeyError, TypeError) as exc:
            return {"valid": False, "path": str(path), "error": str(exc)}
    yanked = [str(row.message) for row in captured if issubclass(row.category, YankedPinWarning)]
    return {"valid": True, "path": str(path), "warnings": yanked}


def _ui_check(project_root: str) -> dict[str, Any]:
    """Run ``check_ui`` over a project's real presentation documents."""
    from benchweave_sdk.presentation import check_ui

    root = Path(project_root).expanduser().resolve()
    src = root / "src"
    candidates = sorted(p.parent for p in src.glob("*/presentation.json"))
    if len(candidates) != 1:
        return {
            "valid": False,
            "error": f"standalone_plugin_project: expected exactly one "
            f"src/*/presentation.json under {root}, found {len(candidates)}",
        }
    package_dir = candidates[0]
    try:
        report = check_ui(
            package_dir / "presentation.json",
            package_dir / "descriptor.json",
            package_dir,
            package_dir / "binding-catalogue.json",
            firmware=None,
            features=frozenset(),
            panels=frozenset(),
        )
    except (ValueError, OSError) as exc:
        return {"valid": False, "error": str(exc)}
    return {
        "valid": bool(getattr(report, "valid", False)),
        "findings": [
            {
                "code": getattr(finding, "code", ""),
                "path": getattr(finding, "path", ""),
                "message": getattr(finding, "message", ""),
            }
            for finding in getattr(report, "findings", [])
        ],
        "unavailable_pages": list(getattr(report, "unavailable_pages", []) or []),
    }


def register_authoring_tools(mcp: FastMCP) -> None:
    """Register the three authoring tools (authoring mode only)."""

    async def plugin_new(destination: str, package: str = "example_plugin",
                         with_ui: bool = True) -> Any:
        try:
            return _plugin_new(destination, package, with_ui)
        except (ValueError, OSError) as exc:
            return _error(str(exc))

    async def plugin_check(descriptor_path: str) -> Any:
        return _plugin_check(descriptor_path)

    async def ui_check(project_root: str) -> Any:
        return _ui_check(project_root)

    plugin_new.__doc__ = (
        "Scaffold a synthetic SDK plugin project (create_project, plus UI "
        "resources with --with-ui); returns the created file inventory."
    )
    plugin_check.__doc__ = (
        "Run the SDK descriptor checker (S01/S02/S04) on one descriptor.json."
    )
    ui_check.__doc__ = (
        "Run the SDK presentation checker over a plugin project's real "
        "presentation documents."
    )
    mcp.tool(plugin_new, name="plugin_new", description=plugin_new.__doc__ or "")
    mcp.tool(plugin_check, name="plugin_check", description=plugin_check.__doc__ or "")
    mcp.tool(ui_check, name="ui_check", description=ui_check.__doc__ or "")
