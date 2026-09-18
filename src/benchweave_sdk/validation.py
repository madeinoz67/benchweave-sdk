"""Offline schema checks and a small explicitly bounded semantic check set."""

from __future__ import annotations

import json
import tomllib
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012


def _project_name(root: Path) -> str | None:
    """The ``project.name`` of the pyproject at ``root``, or None when unreadable."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        with pyproject.open("rb") as handle:
            name = tomllib.load(handle).get("project", {}).get("name")
    except (tomllib.TOMLDecodeError, OSError):
        return None
    return name if isinstance(name, str) else None


@cache
def contract_documents() -> dict[str, Any]:
    """Return the bundled standards documents keyed by relative path.

    Documents load once from the vendored ``standards/`` tree (falling
    back to the repository checkout during editable development) under
    keys such as ``otdp/0.1.0/otdp-runtime.schema.json``.
    """
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
        # Editable development in the main-project submodule mount only
        # (packages/sdk/src/benchweave_sdk/ -> the gateway checkout's corpus).
        # Anywhere else — a standalone clone or an installed wheel — a missing
        # vendored tree is an incomplete installation, not a cue to read files
        # from outside the package.
        checkout = Path(__file__).resolve().parents[4]
        if _project_name(checkout) != "benchweave":
            raise RuntimeError(
                "SDK standards tree missing; run sync-standards or reinstall the SDK"
            )
        directories = [
            (checkout / "standards" / identifier / version, f"{identifier}/{version}")
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
    """Validate a parsed document against a bundled contract, offline only.

    No remote retrieval is permitted: schema references resolve only
    against the bundled registry and fail closed when unresolved.

    Parameters
    ----------
    document
        Parsed JSON document to validate.
    schema_file
        Contract key from ``contract_documents()``, for example
        ``"otdp/0.1.0/otdp-runtime.schema.json"``.
    definition
        Optional ``$defs`` entry to validate against, for example
        ``"operationRequest"``.

    Raises
    ------
    ValueError
        If the document is not strictly JSON (finite numbers only) or
        fails the contract.
    """
    if schema_file not in contract_documents():
        raise ValueError(f"unknown_contract_schema: {schema_file}")
    try:
        json.dumps(document, allow_nan=False)
        schema = contract_documents()[schema_file]
        if definition:
            schema_id = schema.get("$id")
            if schema_id is None:
                raise ValueError(
                    f"schema {schema_file} carries no '$id'; definitions cannot be addressed"
                )
            schema = {"$ref": f"{schema_id}#/$defs/{definition}"}
        validator = Draft202012Validator(
            schema, registry=_registry(), format_checker=FormatChecker()
        )
        validator.validate(document)
    except (
        TypeError,
        ValueError,
        RecursionError,
        SchemaError,
        ValidationError,
        Unresolvable,
    ) as exc:
        # Only document/schema failures are laundered into the domain error;
        # a programming error (say, a KeyError) keeps its own face. A deep
        # enough document overflows the validator's recursion before anything
        # else runs, so RecursionError is a document failure here too.
        raise ValueError(f"Contract validation failed: {exc}") from exc


def validate_request(request: dict[str, Any]) -> None:
    """Validate an OTDP operation request envelope against its contract."""
    validate(request, "otdp/0.1.0/otdp-runtime.schema.json", "operationRequest")


def validate_result(result: dict[str, Any], request: dict[str, Any]) -> None:
    """Validate a result envelope and its correlation with its request.

    Parameters
    ----------
    result
        Operation result envelope to validate.
    request
        The request the result answers. Both documents are validated,
        and the result's ``operation_id`` and ``verb`` must match the
        request's.

    Raises
    ------
    ValueError
        If either envelope fails its contract or the pair does not
        correlate.
    """
    validate_request(request)
    validate(result, "otdp/0.1.0/otdp-runtime.schema.json", "operationResult")
    if (result["operation_id"], result["verb"]) != (request["operation_id"], request["verb"]):
        raise ValueError("Result correlation does not match the request")


def validate_descriptor(descriptor: dict[str, Any]) -> None:
    """Validate a device descriptor against the bundled OTDP contract.

    Beyond the schema, enforces the pinned semantic checks:
    capabilities and operation policies must describe the same verbs and
    parameter names must be unique (S01), and parameter bounds must not
    be reversed (S02).

    Parameters
    ----------
    descriptor
        Parsed device descriptor document.

    Raises
    ------
    ValueError
        If the descriptor fails the schema or a semantic check.

    Examples
    --------
    >>> import json
    >>> from pathlib import Path
    >>> from benchweave_sdk.validation import validate_descriptor
    >>> validate_descriptor(
    ...     json.loads(Path("src/demo_plugin/descriptor.json").read_text()))
    """
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
        # The descriptor schema types ``range`` as a two-element [min, max]
        # array; the earlier mapping-shaped check could never fire.
        bounds = parameter.get("range")
        if isinstance(bounds, list | tuple) and len(bounds) == 2 and bounds[0] > bounds[1]:
            raise ValueError("S02: parameter bounds are reversed")
