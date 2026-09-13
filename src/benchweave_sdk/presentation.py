"""Offline UI authoring helpers; successful validation is never device approval."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import stat
import sys
from functools import cache
from pathlib import Path
from typing import Any

from .validation import contract_documents, validate_descriptor


@cache
def _contract() -> Any:
    name = "benchweave_sdk._presentation_contract"
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
        # Editable checkout only. Distributions contain this exact file via the build hook.
        source = Path(__file__).resolve().parents[4] / "src/benchweave/presentation/contracts.py"
        if not source.is_file():
            raise RuntimeError("SDK presentation validator missing; reinstall the SDK") from exc
        spec = importlib.util.spec_from_file_location(name, source)
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot load editable SDK validator") from exc
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
    """Open bounded regular files without following symlinks in any component."""
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
    finally:
        os.close(directory)


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
        return validate_presentation(
            envelope_raw,
            descriptor_raw=read_file(descriptor_path),
            resources=resources,
            binding_catalogue=contract.parse_document(read_file(catalogue_path)),
            supported_features=features,
            supported_panels=panels,
            firmware=firmware,
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("Malformed presentation resource references") from exc


def create_ui_resources(destination: Path, package: str) -> None:
    """Add read-only presentation resources to an already generated SDK starter."""
    root = destination / "src" / package
    raw = read_file(root / "descriptor.json")
    descriptor = _contract().parse_document(raw)
    descriptor_hash = hashlib.sha256(raw).hexdigest()
    targets = []
    bindings = []
    types = {"float": "number", "int": "integer", "bool": "boolean", "string": "string"}
    for parameter in descriptor["parameters"]:
        if parameter["access"] not in ("ro", "rw"):
            continue
        name = parameter["name"]
        targets.append(
            {
                "id": name,
                "kind": "observation",
                "parameter_id": name,
                "variables": [
                    {
                        "id": "value",
                        "type": types[parameter["type"]],
                        "unit": parameter.get("unit"),
                        "shape": "scalar",
                        "axis_role": "value",
                    }
                ],
            }
        )
        bindings.append({"id": name, "kind": "observation", "target_id": name})
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
    (destination / "UI-GUIDE.md").write_text(
        "# Optional plugin presentation\n\n"
        "The starter declares read-only observations. It adds no device actions.\n"
        f"The project root contains pyproject.toml, AI-GUIDE.md, this guide and tests/.\n"
        f"Its Python package is src/{package}/. Presentation files are laid out as:\n\n"
        f"```text\nsrc/{package}/\n"
        "  descriptor.json\n  presentation.json\n  binding-catalogue.json\n"
        "  ui/\n    manifest.json\n"
        "    settings/  # author-supplied schemas, when configuration exists\n"
        "    presets/   # author-supplied complete configurations\n"
        "    assets/    # author-supplied declared static resources\n```\n\n"
        "Only ui/manifest.json is generated inside ui/. Add settings/ and presets/\n"
        "only for configuration actions the descriptor actually implements.\n"
        "Keep resources inside the Python package so they ship in the wheel.\n"
        "Keep collected data, credentials and deployment configuration outside it.\n\n"
        f"Run from the project root: `benchweave-sdk check-ui src/{package}/presentation.json "
        f"--descriptor src/{package}/descriptor.json --resources src/{package} "
        f"--catalogue src/{package}/binding-catalogue.json`.\n\n"
        "--resources names the package root; the envelope selects resource_root=ui.\n"
        "Manifest asset paths are relative to ui/, for example presets/default.json.\n"
        "Use canonical paths without symlink components. Keep the binding catalogue\n"
        "aligned with the descriptor and update exact byte hashes after edits.\n\n"
        "check-ui validates offline; it is not admission or permission to operate hardware.\n"
        "Preset selection performs no I/O. Applying settings requires a separately\n"
        "approved procedure. Acquisition and retained observations belong to the gateway.\n",
        encoding="utf-8",
    )
