"""Authoring tools: the SDK's functions, not its CLI text (SW-35/NFR-S8).

``plugin_new`` composes ``scaffold.create_project`` with
``presentation.create_ui_resources`` exactly as the SDK's ``new --with-ui``
does; ``plugin_check`` runs ``validation.validate_descriptor``;
``ui_check`` runs the ``presentation.check_ui`` path with the plugin's real
document paths. Results carry the SDK's own diagnostic surface (validator
findings with their codes and paths, scaffold refusal messages) — nothing is
re-worded. The tools are registered only when the host starts with
``--authoring``; without it they are absent from the tool list (test-pinned).

I2c adds the structured contract-edit set (SW-36, Q10's option 2) and the
remaining SW-35 checks. The contract-edit discipline is
validate-the-RESULT-before-write: a JSON Patch applies in memory, the
dependent digests recompute in memory, the whole result re-validates against
the vendored schema and the cross-document rules (staged to a temporary
tree so ``check_ui`` reads exactly the bytes that would land), and ONLY a
clean result writes — a failing patch writes nothing and returns the SDK's
diagnostic codes. Envelope digests never lie about unapplied bytes: every
write recomputes them. Authoring writes are confined to the loaded
project's own package (NFR-S9): portable relative paths, no traversal, no
symlinked components.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import warnings
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.tools import ToolResult

from benchweave_sdk.scaffold import create_project
from benchweave_sdk.validation import YankedPinWarning, validate_descriptor

from .jsonpatch import JSONPatchError, apply_patch


class AuthoringError(ValueError):
    """A refused authoring operation: message, code, and diagnostic details."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_request",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _error(exc: AuthoringError) -> ToolResult:
    return ToolResult(
        structured_content={
            "error": {
                "code": exc.code,
                "message": str(exc),
                **({"details": exc.details} if exc.details else {}),
            }
        },
        is_error=True,
    )


# --- shared path discipline (NFR-S9) -------------------------------------------


def _safe_name(name: str) -> str:
    """One path segment: non-empty, no separators, no traversal."""
    if not name or name in {".", ".."} or "/" in name or "\\" in name or ":" in name:
        raise AuthoringError(f"invalid document name: {name!r}")
    return name


def _no_symlinks(root: Path, relative: str) -> None:
    """Refuse any symlinked component on the write path (NFR-S9: the
    SDK's read-time no-follow discipline, reused for writes)."""
    probe = root
    if probe.is_symlink():
        raise AuthoringError(f"symlinked package root: {probe}")
    for part in Path(relative).parts:
        if part in {"", ".", ".."}:
            raise AuthoringError(f"traversal in write path: {relative}")
        probe = probe / part
        if probe.is_symlink():
            raise AuthoringError(f"symlinked write path component: {probe}")


def _serialise(document: Any) -> bytes:
    """The write format every authoring write uses (the scaffold's own)."""
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")


#: The patchable contract documents, as portable relative paths inside the
#: plugin's package (never absolute, never outside it).
_CONTRACT_DOCUMENTS: dict[str, str] = {
    "descriptor": "descriptor.json",
    "manifest": "ui/manifest.json",
    "binding_catalogue": "binding-catalogue.json",
}


def _plugin_paths(seam: Any) -> tuple[Any, Path]:
    plugin = seam.session.plugin
    return plugin, Path(plugin.package_dir)


def _read_document(path: Path, label: str) -> bytes:
    from benchweave_sdk.presentation import read_file

    try:
        return read_file(path)
    except (OSError, ValueError) as exc:
        raise AuthoringError(f"unreadable {label}: {exc}") from exc


def _parse(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise AuthoringError(f"malformed {label}: {exc}") from exc


# --- the pre-I2c tools -----------------------------------------------------------


def _plugin_new(destination: str, package: str, with_ui: bool) -> dict[str, Any]:
    """Scaffold a project; return the created file inventory."""
    from benchweave_sdk.presentation import create_ui_resources

    target = Path(destination).expanduser().resolve()
    create_project(target, package, with_ui=with_ui)
    if with_ui:
        create_ui_resources(target, package)
    files = sorted(
        # Posix-form relative paths on EVERY host (the cross-host-meaning
        # rule): str(relative_to) is flavour-dependent — the wire list is
        # platform-invariant or the same tool means different things on
        # different hosts (PR #90's windows-latest leg). as_posix() is a
        # no-op on posix hosts and corrective on Windows.
        path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()
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


# --- structured contract edits (SW-36) --------------------------------------------


def _contract_get(seam: Any, document: str) -> dict[str, Any]:
    if document not in _CONTRACT_DOCUMENTS:
        raise AuthoringError(
            f"unknown contract document: {document!r} "
            f"(known: {', '.join(sorted(_CONTRACT_DOCUMENTS))})"
        )
    plugin, package = _plugin_paths(seam)
    if document != "descriptor" and not plugin.has_presentation:
        raise AuthoringError(
            "this plugin declares no presentation documents; only the "
            "descriptor can be read or patched"
        )
    relative = _CONTRACT_DOCUMENTS[document]
    raw = _read_document(package / relative, document)
    parsed = _parse(raw, document)
    return {
        "document": document,
        "content": parsed,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _patch_findings(exc: JSONPatchError) -> dict[str, Any]:
    return {
        "findings": [
            {"code": f"json_patch_{exc.code}", "path": "", "message": exc.message}
        ]
    }


def _validate_result(
    plugin: Any, package: Path, writes: dict[str, bytes]
) -> list[dict[str, str]]:
    """Validate the patched RESULT the way a load would: the descriptor
    against the SDK checker, then — for a plugin with presentation — the
    whole document set through ``check_ui`` over a staged tree that holds
    exactly the bytes that would land. Returns every finding; an empty list
    is the only state that may write."""
    from .presentation import SUPPORTED_FEATURES, SUPPORTED_PANELS

    findings: list[dict[str, str]] = []
    descriptor_bytes = writes.get("descriptor.json")
    if descriptor_bytes is None:
        descriptor_bytes = _read_document(package / "descriptor.json", "descriptor")
    try:
        validate_descriptor(json.loads(descriptor_bytes))
    except (ValueError, KeyError, TypeError) as exc:
        findings.append(
            {"code": "descriptor_invalid", "path": "descriptor.json", "message": str(exc)}
        )
    if not plugin.has_presentation:
        return findings
    from benchweave_sdk.presentation import check_ui

    # macOS note: mkdtemp() answers under /var/..., a symlinked component
    # the SDK's no-follow reader refuses — resolve() canonicalises to
    # /private/var before any document read touches the staged tree.
    staged_root = Path(tempfile.mkdtemp()).resolve()
    try:
        staged = staged_root / plugin.package
        shutil.copytree(package, staged, symlinks=True)
        for relative, blob in writes.items():
            (staged / relative).write_bytes(blob)
        try:
            report = check_ui(
                staged / "presentation.json",
                staged / "descriptor.json",
                staged,
                staged / "binding-catalogue.json",
                firmware=None,
                features=SUPPORTED_FEATURES,
                panels=SUPPORTED_PANELS,
            )
        except (ValueError, OSError) as exc:
            findings.append(
                {"code": "presentation_invalid", "path": "", "message": str(exc)}
            )
        else:
            findings.extend(
                {
                    "code": str(getattr(finding, "code", "")),
                    "path": str(getattr(finding, "path", "")),
                    "message": str(getattr(finding, "message", "")),
                }
                for finding in getattr(report, "findings", [])
            )
    finally:
        shutil.rmtree(staged_root, ignore_errors=True)
    return findings


def _contract_patch(seam: Any, document: str, patch: Any) -> dict[str, Any]:
    """Apply one JSON Patch to a contract document; write only a clean
    result. Dependent digests recompute in memory FIRST (the envelope and
    its dependents describe the bytes that would land), the result is
    validated through the same checks a load runs, and a failing patch —
    schema-invalid, cross-document-invalid, or malformed — writes nothing.
    """
    if document not in _CONTRACT_DOCUMENTS:
        raise AuthoringError(
            f"unknown contract document: {document!r} "
            f"(known: {', '.join(sorted(_CONTRACT_DOCUMENTS))})"
        )
    plugin, package = _plugin_paths(seam)
    if document != "descriptor" and not plugin.has_presentation:
        raise AuthoringError(
            "this plugin declares no presentation documents; only the "
            "descriptor can be read or patched"
        )
    relative = _CONTRACT_DOCUMENTS[document]
    current = _parse(_read_document(package / relative, document), document)
    try:
        result = apply_patch(current, patch)
    except JSONPatchError as exc:
        raise AuthoringError(
            f"the patch is not applicable: {exc}",
            details=_patch_findings(exc),
        ) from exc

    writes: dict[str, bytes] = {relative: _serialise(result)}
    if document == "descriptor":
        descriptor_digest = hashlib.sha256(writes["descriptor.json"]).hexdigest()
        if plugin.has_presentation:
            manifest = _parse(
                _read_document(package / "ui" / "manifest.json", "manifest"), "manifest"
            )
            manifest["descriptor_sha256"] = descriptor_digest
            writes["ui/manifest.json"] = _serialise(manifest)
            catalogue = _parse(
                _read_document(package / "binding-catalogue.json", "catalogue"),
                "catalogue",
            )
            catalogue["descriptor_sha256"] = descriptor_digest
            writes["binding-catalogue.json"] = _serialise(catalogue)
            envelope = _parse(
                _read_document(package / "presentation.json", "envelope"), "envelope"
            )
            envelope["descriptor_sha256"] = descriptor_digest
            envelope["manifest"]["sha256"] = hashlib.sha256(
                writes["ui/manifest.json"]
            ).hexdigest()
            writes["presentation.json"] = _serialise(envelope)
    elif document == "manifest":
        envelope = _parse(
            _read_document(package / "presentation.json", "envelope"), "envelope"
        )
        envelope["manifest"]["sha256"] = hashlib.sha256(
            writes["ui/manifest.json"]
        ).hexdigest()
        writes["presentation.json"] = _serialise(envelope)

    findings = _validate_result(plugin, package, writes)
    if findings:
        raise AuthoringError(
            f"the patched {document} would not validate: "
            f"{len(findings)} finding(s); nothing was written",
            details={"findings": findings},
        )
    for write_relative, blob in sorted(writes.items()):
        _no_symlinks(package, write_relative)
        target = package / write_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    return {
        "document": document,
        "sha256": hashlib.sha256(writes[relative]).hexdigest(),
        "written": sorted(writes),
        "content": result,
    }


# --- presets and settings schemas (whole documents) --------------------------------


def _preset_path(package: Path, preset_id: str) -> Path:
    return package / "config" / "presets" / f"{_safe_name(preset_id)}.json"


def _settings_path(package: Path) -> Path:
    return package / "config" / "settings.schema.json"


def _preset_firmwares(seam: Any, explicit: str | None) -> list[str]:
    """The firmwares a preset is judged against, in priority order: an
    explicit argument first, then the CONNECTED device's established
    firmware, then every firmware the descriptor itself declares (the
    plugin's own declaration is the authority offline — A02's posture).
    The vendored validator needs one concrete firmware; None is not one."""
    if explicit:
        return [explicit]
    identity = getattr(seam.session, "identity", None) or {}
    established = identity.get("firmware")
    if established:
        return [str(established)]
    descriptor = seam.session.plugin.descriptor
    declared = descriptor.get("identity", {}).get("supported_firmware", [])
    return [str(row) for row in declared]


def _validated_preset(
    seam: Any, blob_or_path: Any, *, preset_id: str, firmware: str | None
) -> tuple[bool, list[dict[str, str]]]:
    """Validate one preset against every candidate firmware: valid when ANY
    candidate accepts it (the preset names a firmware the plugin supports);
    otherwise the findings from every attempt ride the refusal."""
    from benchweave_sdk.presentation import validate_preset

    _plugin, package = _plugin_paths(seam)
    descriptor_raw = _read_document(package / "descriptor.json", "descriptor")
    settings_raw = _read_document(
        _settings_path(package),
        "settings schema (a preset cannot be validated without one)",
    )
    raw = (
        blob_or_path
        if isinstance(blob_or_path, bytes)
        else _read_document(_preset_path(package, preset_id), f"preset {preset_id}")
    )
    findings: list[dict[str, str]] = []
    candidates = _preset_firmwares(seam, firmware)
    if not candidates:
        raise AuthoringError(
            "no firmware to judge the preset against: the descriptor "
            "declares none and no device is established"
        )
    for candidate in candidates:
        report = validate_preset(
            raw,
            descriptor_raw=descriptor_raw,
            settings_schema_raw=settings_raw,
            firmware=candidate,
        )
        if getattr(report, "valid", False):
            return True, []
        findings.extend(
            {
                "code": str(getattr(finding, "code", "")),
                "path": str(getattr(finding, "path", "")),
                "message": f"[{candidate}] {getattr(finding, 'message', '')}",
            }
            for finding in getattr(report, "findings", [])
        )
    return False, findings


def _preset_get(seam: Any, preset_id: str) -> dict[str, Any]:
    _plugin, package = _plugin_paths(seam)
    raw = _read_document(_preset_path(package, preset_id), f"preset {preset_id}")
    return {
        "preset_id": preset_id,
        "document": _parse(raw, f"preset {preset_id}"),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _preset_put(seam: Any, preset_id: str, document: Any) -> dict[str, Any]:
    _plugin, package = _plugin_paths(seam)
    if not isinstance(document, dict):
        raise AuthoringError("a preset document is a JSON object")
    blob = _serialise(document)
    valid, findings = _validated_preset(
        seam, blob, preset_id=preset_id, firmware=None
    )
    if not valid:
        raise AuthoringError(
            f"the preset would not validate: {len(findings)} finding(s); "
            "nothing was written",
            details={"findings": findings},
        )
    relative = f"config/presets/{_safe_name(preset_id)}.json"
    _no_symlinks(package, relative)
    target = package / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob)
    # The host's own authorized write moves the serving pin with it (the
    # construction pin governs writes the host did not make).
    digest = seam.repin_preset(preset_id)
    return {"preset_id": preset_id, "sha256": digest, "written": relative}


def _settings_schema_get(seam: Any) -> dict[str, Any]:
    _plugin, package = _plugin_paths(seam)
    raw = _read_document(_settings_path(package), "settings schema")
    return {
        "document": _parse(raw, "settings schema"),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _settings_schema_put(seam: Any, document: Any) -> dict[str, Any]:
    _plugin, package = _plugin_paths(seam)
    if not isinstance(document, dict):
        raise AuthoringError("a settings schema is a JSON object")
    blob = _serialise(document)
    # Shape-checked only: the schema dialect itself is exercised where it
    # is consumed — preset validation — not here (an honest limit, not a
    # guess at schema-dialect correctness).
    relative = "config/settings.schema.json"
    _no_symlinks(package, relative)
    target = package / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob)
    return {"sha256": hashlib.sha256(blob).hexdigest(), "written": relative}


def _preset_check(
    seam: Any, preset_id: str, firmware: str | None = None
) -> dict[str, Any]:
    _safe_name(preset_id)
    valid, findings = _validated_preset(
        seam, None, preset_id=preset_id, firmware=firmware
    )
    return {"valid": valid, "findings": findings}


# --- the remaining SW-35 checks -----------------------------------------------------


def _inventory(seam: Any) -> dict[str, Any]:
    from benchweave_sdk.packaging import inventory

    plugin, _package = _plugin_paths(seam)
    try:
        rows = inventory(plugin.project_root)
    except (OSError, ValueError) as exc:
        raise AuthoringError(f"inventory refused: {exc}") from exc
    return {"root": str(plugin.project_root), "files": rows}


def _standards_check() -> dict[str, Any]:
    """The sync-standards --check lane as a function: a repository checkout
    verifies its committed lock and vendored tree; an installed SDK verifies
    its packaged lock (the CLI's own two modes, no CLI text)."""
    from benchweave_sdk.cli import _sdk_checkout_root
    from benchweave_sdk.standards_sync import sync, verify_installed

    sdk_root = _sdk_checkout_root()
    try:
        if sdk_root is None:
            verify_installed()
            return {"valid": True, "mode": "installed"}
        report = sync(None, sdk_root=sdk_root, check_only=True)
        drift = any(
            (
                report.added,
                report.changed,
                report.deprecated,
                report.removed,
                report.active_changes,
            )
        )
        if drift:
            raise AuthoringError(
                "standards drift detected; re-run sync-standards to update",
                code="unavailable",
            )
        return {"valid": True, "mode": "checkout"}
    except (OSError, ValueError) as exc:
        raise AuthoringError(f"standards drift: {exc}", code="unavailable") from exc


# --- registration ---------------------------------------------------------------


def register_authoring_tools(mcp: FastMCP, *, seam: Any = None) -> None:
    """Register the authoring tools (authoring mode only).

    The contract-edit, preset, settings and inventory tools operate on the
    HOST's loaded project and therefore need the seam; the check tools that
    take explicit paths (``plugin_new``, ``plugin_check``, ``ui_check``) do
    not.
    """

    def _needs_seam() -> Any:
        if seam is None:
            raise AuthoringError("this tool needs a loaded host session")
        return seam

    async def plugin_new(destination: str, package: str = "example_plugin",
                         with_ui: bool = True) -> Any:
        try:
            return _plugin_new(destination, package, with_ui)
        except (ValueError, OSError) as exc:
            return _error(AuthoringError(str(exc)))

    async def plugin_check(descriptor_path: str) -> Any:
        return _plugin_check(descriptor_path)

    async def ui_check(project_root: str) -> Any:
        return _ui_check(project_root)

    async def contract_get(document: str) -> Any:
        try:
            return _contract_get(_needs_seam(), document)
        except AuthoringError as exc:
            return _error(exc)

    async def contract_patch(document: str, patch: list[dict[str, Any]]) -> Any:
        try:
            return _contract_patch(_needs_seam(), document, patch)
        except AuthoringError as exc:
            return _error(exc)

    async def preset_get(preset_id: str) -> Any:
        try:
            return _preset_get(_needs_seam(), preset_id)
        except AuthoringError as exc:
            return _error(exc)

    async def preset_put(preset_id: str, document: dict[str, Any]) -> Any:
        try:
            return _preset_put(_needs_seam(), preset_id, document)
        except AuthoringError as exc:
            return _error(exc)

    async def settings_schema_get() -> Any:
        try:
            return _settings_schema_get(_needs_seam())
        except AuthoringError as exc:
            return _error(exc)

    async def settings_schema_put(document: dict[str, Any]) -> Any:
        try:
            return _settings_schema_put(_needs_seam(), document)
        except AuthoringError as exc:
            return _error(exc)

    async def preset_check(preset_id: str, firmware: str | None = None) -> Any:
        try:
            return _preset_check(_needs_seam(), preset_id, firmware)
        except AuthoringError as exc:
            return _error(exc)

    async def inventory() -> Any:
        try:
            return _inventory(_needs_seam())
        except AuthoringError as exc:
            return _error(exc)

    async def standards_check() -> Any:
        try:
            return _standards_check()
        except AuthoringError as exc:
            return _error(exc)

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
    contract_get.__doc__ = (
        "Read one patchable contract document (descriptor, manifest or "
        "binding_catalogue) with its content digest."
    )
    contract_patch.__doc__ = (
        "Apply one JSON Patch (RFC 6902) to a contract document. The patched "
        "result is validated against the vendored schema and the "
        "cross-document rules BEFORE any write; dependent digests recompute "
        "on write; a failing patch writes nothing and returns the SDK's "
        "diagnostic findings."
    )
    preset_get.__doc__ = (
        "Read one configuration preset document (config/presets/<id>.json) "
        "with its content digest."
    )
    preset_put.__doc__ = (
        "Write one configuration preset document whole. The document is "
        "validated offline against the plugin's descriptor and settings "
        "schema before the write; the running host's serving pin moves "
        "with the host's own write."
    )
    settings_schema_get.__doc__ = (
        "Read the plugin's settings schema (config/settings.schema.json)."
    )
    settings_schema_put.__doc__ = (
        "Write the plugin's settings schema whole. Shape-checked only; the "
        "schema is exercised where it is consumed (preset validation)."
    )
    preset_check.__doc__ = (
        "Validate one preset offline (the SDK check-preset function); pass "
        "firmware to judge it against a specific device version."
    )
    inventory.__doc__ = (
        "Inventory the loaded plugin project's files with sizes and "
        "sha256 digests (the SDK inventory function, not a shell)."
    )
    standards_check.__doc__ = (
        "Verify the running SDK's vendored standards tree against its "
        "packaged lock (the sync-standards --check lane)."
    )
    mcp.tool(plugin_new, name="plugin_new", description=plugin_new.__doc__ or "")
    mcp.tool(plugin_check, name="plugin_check", description=plugin_check.__doc__ or "")
    mcp.tool(ui_check, name="ui_check", description=ui_check.__doc__ or "")
    mcp.tool(contract_get, name="contract_get", description=contract_get.__doc__ or "")
    mcp.tool(contract_patch, name="contract_patch", description=contract_patch.__doc__ or "")
    mcp.tool(preset_get, name="preset_get", description=preset_get.__doc__ or "")
    mcp.tool(preset_put, name="preset_put", description=preset_put.__doc__ or "")
    mcp.tool(
        settings_schema_get,
        name="settings_schema_get",
        description=settings_schema_get.__doc__ or "",
    )
    mcp.tool(
        settings_schema_put,
        name="settings_schema_put",
        description=settings_schema_put.__doc__ or "",
    )
    mcp.tool(preset_check, name="preset_check", description=preset_check.__doc__ or "")
    mcp.tool(inventory, name="inventory", description=inventory.__doc__ or "")
    mcp.tool(standards_check, name="standards_check", description=standards_check.__doc__ or "")
