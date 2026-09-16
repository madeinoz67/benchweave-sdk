"""Offline schema checks and a small explicitly bounded semantic check set."""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012


@cache
def contract_documents() -> dict[str, Any]:
    vendored = files("benchweave_sdk").joinpath("standards")
    sets = (
        ("otdp", "0.1.0"),
        ("registry", "0.1.0"),
        ("plugin-ui", "0.1.0"),
    )
    if vendored.is_dir():
        # The vendored tree is standards/<id>/<version>/...; document keys stay
        # <id>/<version>/... so schema_file lookups and $ref registries follow.
        directories = [
            (vendored.joinpath(identifier, version), f"{identifier}/{version}")
            for identifier, version in sets
        ]
    else:
        # Editable development before the first standards sync only.
        checkout = Path(__file__).resolve().parents[4] / "standards"
        directories = [
            (checkout / identifier / version, f"{identifier}/{version}")
            for identifier, version in sets
        ]
    documents: dict[str, Any] = {}

    def visit(directory: Any, prefix: str) -> None:
        for child in sorted(directory.iterdir(), key=lambda item: item.name):
            key = f"{prefix}/{child.name}" if prefix else child.name
            if child.is_dir():
                visit(child, key)
            elif child.name.endswith(".json"):
                documents[key] = json.loads(child.read_text(encoding="utf-8"))

    for directory, prefix in directories:
        visit(directory, prefix)
    return documents


@cache
def _registry() -> Registry[Any]:
    # Registry has no network retriever by default; unresolved refs fail closed.
    registry: Registry[Any] = Registry()
    for name, document in contract_documents().items():
        if not isinstance(document, dict) or "$schema" not in document:
            continue
        resource = Resource.from_contents(document, default_specification=DRAFT202012)
        registry = registry.with_resource(name, resource)
        if "$id" in document:
            registry = registry.with_resource(document["$id"], resource)
    return registry


def validate(document: Any, schema_file: str, definition: str | None = None) -> None:
    """Validate against bundled contracts. No remote retrieval is permitted."""
    try:
        json.dumps(document, allow_nan=False)
        schema = contract_documents()[schema_file]
        if definition:
            schema = {"$ref": f"{schema['$id']}#/$defs/{definition}"}
        validator = Draft202012Validator(
            schema, registry=_registry(), format_checker=FormatChecker()
        )
        validator.validate(document)
    except Exception as exc:
        raise ValueError(f"Contract validation failed: {exc}") from exc


def validate_request(request: dict[str, Any]) -> None:
    validate(request, "otdp/0.1.0/otdp-runtime.schema.json", "operationRequest")


def validate_result(result: dict[str, Any], request: dict[str, Any]) -> None:
    validate_request(request)
    validate(result, "otdp/0.1.0/otdp-runtime.schema.json", "operationResult")
    if (result["operation_id"], result["verb"]) != (request["operation_id"], request["verb"]):
        raise ValueError("Result correlation does not match the request")


def validate_descriptor(descriptor: dict[str, Any]) -> None:
    validate(descriptor, "otdp/0.1.0/otdp-device-descriptor.schema.json")
    capabilities = descriptor["capabilities"]
    if len(capabilities) != len(set(capabilities)) or set(capabilities) != set(
        descriptor["operations"]
    ):
        raise ValueError("S01: capabilities and operation policies must match")
    names = [parameter["name"] for parameter in descriptor["parameters"]]
    if len(names) != len(set(names)):
        raise ValueError("S01: parameter names must be unique")
    for parameter in descriptor["parameters"]:
        bounds = parameter.get("range")
        if isinstance(bounds, dict) and bounds.get("min", 0) > bounds.get("max", 0):
            raise ValueError("S02: parameter bounds are reversed")
