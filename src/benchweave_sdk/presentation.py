"""Offline UI authoring helpers; successful validation is never device approval."""

from __future__ import annotations

import errno
import hashlib
import importlib.util
import json
import os
import stat
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from .validation import contract_documents, validate_descriptor


@dataclass(frozen=True, slots=True)
class ValidatedPreviewInputs:
    """Parsed inputs proven to match the existing presentation validator."""

    envelope: dict[str, Any]
    manifest: dict[str, Any]
    binding_catalogue: dict[str, Any]
    resource_root: Path


@cache
def _contract() -> Any:
    name = "benchweave_sdk._presentation_contract"
    vendored = Path(__file__).with_name("standards") / "plugin-ui" / "contracts.py"
    if not vendored.is_file():
        # The vendored tree is committed (and, in distributions, verified
        # against its lock by the build hook), so a missing validator is an
        # incomplete tree — never a cue to execute code from outside the
        # package.
        raise RuntimeError(
            "SDK presentation validator missing; run sync-standards or reinstall the SDK"
        )
    spec = importlib.util.spec_from_file_location(name, vendored)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the SDK presentation validator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def schemas() -> dict[str, Any]:
    result = dict(contract_documents())
    for document in tuple(result.values()):
        if "$id" in document:
            result[document["$id"]] = document
        for action in document.get("actions", {}).values():
            for key in ("input_schema", "output_schema"):
                schema = action.get(key, {})
                if "$id" in schema:
                    result[schema["$id"]] = schema
    return result


def read_file(path: Path, limit: int = 262144) -> bytes:
    """Open bounded regular files without following symlinks in any component.

    Path-shape refusals — symlinked or non-directory components, non-regular
    targets, oversize input — raise ``ValueError`` on every platform; absence
    and permission failures keep their ``OSError`` face.
    """
    if limit < 0:
        raise ValueError("Input byte limit exceeded")
    if sys.platform == "win32":
        return _read_file_no_dirfd(path, limit)
    parts = path.absolute().parts
    directory = os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
                raise ValueError("Input must be a bounded regular file")
            raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise ValueError("Input byte limit exceeded")
            return raw
    except OSError as exc:
        # Align refusal classes with the Windows branch: a path whose SHAPE is
        # wrong is a domain refusal (ValueError), matching the messages the
        # explicit checks raise; environment errors (ENOENT, EACCES) pass
        # through unchanged.
        if exc.errno == errno.ELOOP:
            raise ValueError("Input path must not contain symlinked components") from exc
        if exc.errno in (errno.ENOTDIR, errno.EISDIR):
            raise ValueError("Input must be a bounded regular file") from exc
        raise
    finally:
        os.close(directory)


def _read_file_no_dirfd(path: Path, limit: int) -> bytes:
    """``read_file`` for platforms without ``O_NOFOLLOW``/``dir_fd`` (Windows).

    Each component is inspected with ``lstat`` — refusing symlinks and
    reparse points (junctions, mount points) — and a same-file check after
    the open ties the descriptor back to the inspected final component. The
    residual race on intermediate components is accepted for an offline
    authoring tool; the POSIX branch keeps the race-free ``dir_fd`` walk.
    """
    resolved = path.absolute()
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    current = Path(resolved.parts[0])
    details = os.lstat(current)
    for part in resolved.parts[1:]:
        current = current / part
        try:
            details = os.lstat(current)
        except NotADirectoryError as exc:
            # A regular file sitting where a directory component should be —
            # the same refusal class the POSIX branch maps ENOTDIR to.
            raise ValueError("Input must be a bounded regular file") from exc
        is_reparse = getattr(details, "st_file_attributes", 0) & reparse_point
        if stat.S_ISLNK(details.st_mode) or is_reparse:
            raise ValueError("Input path must not contain symlinked components")
    if not stat.S_ISREG(details.st_mode):
        # Refuse directories and other non-regular targets before the open,
        # where Windows would otherwise fail with a platform-specific OSError.
        raise ValueError("Input must be a bounded regular file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
    descriptor = os.open(resolved, flags)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise ValueError("Input must be a bounded regular file")
        # samestat against the WALK's own lstat of the final component, not a
        # fresh post-open lstat: the descriptor is thereby tied to the very
        # file that was verified not to be a symlink or reparse point, which
        # closes the swap-in/swap-out window a re-run lstat would miss.
        if not os.path.samestat(metadata, details):
            raise ValueError("Input path changed while being read")
        raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Input byte limit exceeded")
        return raw


def validate_preset(
    raw: bytes, *, descriptor_raw: bytes, settings_schema_raw: bytes, firmware: str | None
) -> Any:
    validate_descriptor(_contract().parse_document(descriptor_raw))
    return _contract().validate_preset(
        raw,
        descriptor_raw=descriptor_raw,
        settings_schema_raw=settings_schema_raw,
        schema_documents=schemas(),
        firmware=firmware,
    )


def validate_presentation(
    envelope_raw: bytes,
    *,
    descriptor_raw: bytes,
    resources: dict[str, bytes],
    binding_catalogue: dict[str, Any],
    supported_features: frozenset[str] = frozenset(),
    supported_panels: frozenset[str] = frozenset(),
    firmware: str | None = None,
) -> Any:
    validate_descriptor(_contract().parse_document(descriptor_raw))
    return _contract().validate_presentation(
        envelope_raw,
        descriptor_raw=descriptor_raw,
        resources=resources,
        binding_catalogue=binding_catalogue,
        schema_documents=schemas(),
        supported_features=supported_features,
        supported_panels=supported_panels,
        firmware=firmware,
    )


def _load_ui_candidate(
    envelope_path: Path,
    descriptor_path: Path,
    root: Path,
    catalogue_path: Path,
    *,
    firmware: str | None,
    features: frozenset[str],
    panels: frozenset[str],
) -> tuple[Any, ValidatedPreviewInputs]:
    contract = _contract()
    envelope_raw = read_file(envelope_path)
    envelope = contract.parse_document(envelope_raw)
    try:
        resource_root = envelope["resource_root"]
        manifest_path = envelope["manifest"]["path"]
        if not contract.safe_resource_path(resource_root) or not contract.safe_resource_path(
            manifest_path
        ):
            raise ValueError("Unsafe presentation resource path")
        base = root / resource_root
        manifest_raw = read_file(base / manifest_path)
        manifest = contract.parse_document(manifest_raw)
        assets = manifest.get("assets", [])
        if not isinstance(assets, list) or len(assets) > 256:
            raise ValueError("Asset collection exceeds limit")
        resources = {manifest_path: manifest_raw}
        total = len(manifest_raw)
        for asset in assets:
            name = asset["path"]
            if not contract.safe_resource_path(name):
                raise ValueError("Unsafe asset path")
            if name not in resources:
                raw = read_file(base / name, min(16 * 1024 * 1024, 64 * 1024 * 1024 - total))
                resources[name] = raw
                total += len(raw)
        catalogue = contract.parse_document(read_file(catalogue_path))
        report = validate_presentation(
            envelope_raw,
            descriptor_raw=read_file(descriptor_path),
            resources=resources,
            binding_catalogue=catalogue,
            supported_features=features,
            supported_panels=panels,
            firmware=firmware,
        )
        return report, ValidatedPreviewInputs(envelope, manifest, catalogue, base)
    except (KeyError, TypeError) as exc:
        raise ValueError("Malformed presentation resource references") from exc


def check_ui(
    envelope_path: Path,
    descriptor_path: Path,
    root: Path,
    catalogue_path: Path,
    *,
    firmware: str | None,
    features: frozenset[str],
    panels: frozenset[str],
) -> Any:
    report, _ = _load_ui_candidate(
        envelope_path,
        descriptor_path,
        root,
        catalogue_path,
        firmware=firmware,
        features=features,
        panels=panels,
    )
    return report


def load_validated_preview_inputs(
    envelope_path: Path,
    descriptor_path: Path,
    root: Path,
    catalogue_path: Path,
    *,
    firmware: str | None,
    features: frozenset[str],
    panels: frozenset[str],
) -> ValidatedPreviewInputs:
    report, candidate = _load_ui_candidate(
        envelope_path,
        descriptor_path,
        root,
        catalogue_path,
        firmware=firmware,
        features=features,
        panels=panels,
    )
    if not report.valid:
        finding = report.findings[0]
        raise ValueError(
            f"preview_invalid_presentation: {finding.code}: {finding.path}: {finding.message}"
        )
    return candidate


def _preview_fixture(target: dict[str, Any], *, suffix: str, severity: str) -> dict[str, Any]:
    variable = target["variables"][0]
    values: dict[str, Any] = {"number": 1.0, "integer": 1, "boolean": True, "string": "simulated"}
    return {
        "contract_version": "0.1.0",
        "id": f"example-{suffix}",
        "title": f"Example {suffix}",
        "description": f"Synthetic {suffix} state generated by benchweave-sdk",
        "timestamp_strategy": "fixed",
        "bindings": [
            {
                "id": target["id"],
                "value": values[variable["type"]],
                "unit": variable.get("unit"),
                "quality": "simulated",
                "freshness_ms": 0,
                "provenance": "Generated SDK fixture; not a hardware observation",
            }
        ],
        "permissions": ["observer"],
        "lease_state": "none",
        "approval_state": "not_required",
        "unavailable_panels": [],
        "expected_severity": severity,
        "request_outcomes": [],
    }


def _write_preview_examples(destination: Path, package: str, targets: list[dict[str, Any]]) -> None:
    fixtures = destination / "src" / package / "ui" / "fixtures"
    fixtures.mkdir()
    for filename, severity in (("normal", "neutral"), ("warning", "warning")):
        document = _preview_fixture(targets[0], suffix=filename, severity=severity)
        fixture = fixtures / f"{filename}.json"
        fixture.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    lines = [
        '"""Generated offline presentation-preview conformance smoke test."""',
        "",
        "from importlib.resources import files",
        "from pathlib import Path",
        "",
        "from benchweave_sdk.fixtures import BASELINE_IDS, build_preview_model",
        "from benchweave_sdk.presentation import load_validated_preview_inputs",
        "",
        "",
        "def _materialise(source, destination: Path) -> None:",
        "    destination.mkdir(parents=True, exist_ok=True)",
        "    for entry in source.iterdir():",
        "        if entry.is_dir():",
        "            _materialise(entry, destination / entry.name)",
        "        else:",
        "            (destination / entry.name).write_bytes(entry.read_bytes())",
        "",
        "def test_presentation_preview_contract(tmp_path: Path) -> None:",
        f'    package = tmp_path / "{package}"',
        f'    _materialise(files("{package}"), package)',
        "    candidate = load_validated_preview_inputs(",
        '        package / "presentation.json",',
        '        package / "descriptor.json",',
        "        package,",
        '        package / "binding-catalogue.json",',
        "        firmware=None,",
        "        features=frozenset(),",
        "        panels=frozenset(),",
        "    )",
        "    scenarios = build_preview_model(candidate).scenarios",
        "    assert BASELINE_IDS <= {row.id for row in scenarios}",
        "",
    ]
    test_path = destination / "tests" / "test_presentation_preview.py"
    test_path.write_text("\n".join(lines), encoding="utf-8")


def _ui_targets(descriptor: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive presentation targets, rejecting unsupported descriptor types."""
    types = {"float": "number", "int": "integer", "bool": "boolean", "string": "string"}
    targets: list[dict[str, Any]] = []
    for parameter in descriptor["parameters"]:
        if parameter["access"] not in ("ro", "rw"):
            continue
        name = parameter["name"]
        variable_type = types.get(str(parameter["type"]))
        if variable_type is None:
            raise ValueError(
                f"preview_unsupported_parameter_type: {name}: {parameter['type']}"
            )
        targets.append(
            {
                "id": name,
                "kind": "observation",
                "parameter_id": name,
                "variables": [
                    {
                        "id": "value",
                        "type": variable_type,
                        "unit": parameter.get("unit"),
                        "shape": "scalar",
                        "axis_role": "value",
                    }
                ],
            }
        )
    return targets


def create_ui_resources(destination: Path, package: str) -> None:
    """Add read-only presentation resources to an already generated SDK starter."""
    root = destination / "src" / package
    raw = read_file(root / "descriptor.json")
    descriptor = _contract().parse_document(raw)
    descriptor_hash = hashlib.sha256(raw).hexdigest()
    # Validate everything derivable before the first write so a rejected
    # descriptor leaves no half-generated project behind.
    targets = _ui_targets(descriptor)
    if not targets:
        raise ValueError("UI scaffolding requires at least one readable descriptor parameter")
    bindings = [{"id": row["id"], "kind": "observation", "target_id": row["id"]} for row in targets]
    manifest = {
        "contract_version": "0.1.0",
        "plugin_id": descriptor["id"],
        "descriptor_sha256": descriptor_hash,
        "bindings": bindings,
        "pages": [
            {
                "id": "readings",
                "title": "Readings",
                "kind": "readings",
                "bindings": [row["id"] for row in bindings],
                "required": True,
            }
        ],
    }
    manifest_raw = (json.dumps(manifest, indent=2) + "\n").encode()
    envelope = {
        "contract_version": "0.1.0",
        "descriptor_sha256": descriptor_hash,
        "resource_root": "ui",
        "manifest": {"path": "manifest.json", "sha256": hashlib.sha256(manifest_raw).hexdigest()},
    }
    catalogue = {
        "contract_version": "0.1.0",
        "descriptor_sha256": descriptor_hash,
        "targets": targets,
    }
    (root / "ui").mkdir()
    (root / "ui/manifest.json").write_bytes(manifest_raw)
    for name, document in (("presentation.json", envelope), ("binding-catalogue.json", catalogue)):
        (root / name).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    _write_preview_examples(destination, package, targets)
    (destination / "UI-GUIDE.md").write_text(
        "# Optional plugin presentation\n\n"
        "The starter declares read-only observations. It adds no device actions.\n"
        f"The project root contains pyproject.toml, AI-GUIDE.md, this guide and tests/.\n"
        f"Its Python package is src/{package}/. Presentation files are laid out as:\n\n"
        f"```text\nsrc/{package}/\n"
        "  descriptor.json\n  presentation.json\n  binding-catalogue.json\n"
        "  ui/\n    manifest.json\n"
        "    fixtures/  # generated synthetic preview examples\n"
        "    settings/  # author-supplied schemas, when configuration exists\n"
        "    presets/   # author-supplied complete configurations\n"
        "    assets/    # author-supplied declared static resources\n```\n\n"
        "The SDK generates ui/manifest.json and schema-valid examples in ui/fixtures/.\n"
        "Add settings/ and presets/ only for configuration actions the descriptor implements.\n"
        "Keep resources inside the Python package so they ship in the wheel.\n"
        "Keep collected data, credentials and deployment configuration outside it.\n\n"
        f"Run from the project root: `benchweave-sdk check-ui src/{package}/presentation.json "
        f"--descriptor src/{package}/descriptor.json --resources src/{package} "
        f"--catalogue src/{package}/binding-catalogue.json`.\n\n"
        "--resources names the package root; the envelope selects resource_root=ui.\n"
        "Manifest asset paths are relative to ui/, for example presets/default.json.\n"
        "Use canonical paths without symlink components. Keep the binding catalogue\n"
        "aligned with the descriptor and update exact byte hashes after edits.\n\n"
        f"Preview with: `benchweave-sdk preview-ui src/{package}/presentation.json "
        f"--descriptor src/{package}/descriptor.json --resources src/{package} "
        f"--catalogue src/{package}/binding-catalogue.json "
        f"--fixtures src/{package}/ui/fixtures`.\n\n"
        "All preview values and receipts are simulated. check-ui and preview-ui are not\n"
        "admission, hardware qualification or permission to operate hardware.\n"
        "Preset selection performs no I/O. Applying settings requires a separately\n"
        "approved procedure. Acquisition and retained observations belong to the gateway.\n",
        encoding="utf-8",
    )
