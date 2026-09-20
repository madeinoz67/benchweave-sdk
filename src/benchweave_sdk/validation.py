"""Offline schema checks and a small explicitly bounded semantic check set."""

from __future__ import annotations

import json
import re
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012


@cache
def contract_documents() -> dict[str, Any]:
    """Return the bundled standards documents keyed by relative path.

    Documents load once from the vendored ``standards/`` tree (falling
    back to the repository checkout during editable development) under
    keys such as ``otdp/0.2.0/otdp-runtime.schema.json``.
    """
    vendored = files("benchweave_sdk").joinpath("standards")
    sets = (
        ("otdp", "0.2.0"),
        ("registry", "0.1.1"),
        ("plugin-ui", "0.2.0"),
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
    """Validate a parsed document against a bundled contract, offline only.

    No remote retrieval is permitted: schema references resolve only
    against the bundled registry and fail closed when unresolved.

    Parameters
    ----------
    document
        Parsed JSON document to validate.
    schema_file
        Contract key from ``contract_documents()``, for example
        ``"otdp/0.2.0/otdp-runtime.schema.json"``.
    definition
        Optional ``$defs`` entry to validate against, for example
        ``"operationRequest"``.

    Raises
    ------
    ValueError
        If the document is not strictly JSON (finite numbers only) or
        fails the contract.
    """
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
    """Validate an OTDP operation request envelope against its contract."""
    validate(request, "otdp/0.2.0/otdp-runtime.schema.json", "operationRequest")


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
    validate(result, "otdp/0.2.0/otdp-runtime.schema.json", "operationResult")
    if (result["operation_id"], result["verb"]) != (request["operation_id"], request["verb"]):
        raise ValueError("Result correlation does not match the request")


#: The grammar's ``digits`` are exactly ASCII 0-9 (the OTDP schema
#: pattern's class) — ``str.isdigit`` admits Unicode digit-class characters
#: and the two checkers would then disagree on identical content.
_ASCII_DIGITS = frozenset("0123456789")


def _derivation_tokens(expression: str) -> list[tuple[str, str]]:
    """Tokenize a derived-variable expression (S19; measurement-model §8).

    Offline re-implementation of the gateway's grammar: the SDK is
    self-contained by PKG-1 and cannot import the gateway module. The
    closed token set is ``+ - * / ( ) number identifier`` with space as
    whitespace; both implementations are pinned to one truth by the
    corpus-vendored ``derivation-vectors.json`` census (tested main-side).
    """

    tokens: list[tuple[str, str]] = []
    index = 0
    length = len(expression)
    while index < length:
        char = expression[index]
        if char == " ":
            index += 1
            continue
        if char in "+-*/()":
            tokens.append((char, char))
            index += 1
            continue
        if char in _ASCII_DIGITS or char == ".":
            start = index
            if char in _ASCII_DIGITS:
                while index < length and expression[index] in _ASCII_DIGITS:
                    index += 1
            if index < length and expression[index] == ".":
                index += 1
                if index >= length or expression[index] not in _ASCII_DIGITS:
                    raise ValueError(
                        f"S19: derivation_grammar: malformed number at {start} "
                        f"in {expression!r}"
                    )
                while index < length and expression[index] in _ASCII_DIGITS:
                    index += 1
            if index == start:
                raise ValueError(
                    f"S19: derivation_grammar: malformed number at {start} in {expression!r}"
                )
            tokens.append(("num", expression[start:index]))
            continue
        match = re.match(r"[a-z][a-z0-9_]*", expression[index:])
        if match is not None:
            tokens.append(("id", match.group()))
            index += match.end()
            continue
        raise ValueError(
            f"S19: derivation_grammar: illegal character {char!r} at {index} "
            f"in {expression!r}"
        )
    return tokens


def _derivation_identifiers(expression: str) -> list[str]:
    """Parse per the §8 grammar; return identifiers in first-occurrence order.

    Recursive descent with the same precedence and association rules as the
    gateway: ``expression := term (("+"|"-") term)*``,
    ``term := factor (("*"|"/") factor)*``,
    ``factor := ("+"|"-") factor | atom``,
    ``atom := number | identifier | "(" expression ")"``; nesting is capped
    at 32 and length at 256. No eval, no compile, no ast.parse — the token
    set is finite and identifiers stay data.
    """

    if not isinstance(expression, str) or not expression:
        raise ValueError("S19: derivation_grammar: expression must be a non-empty string")
    if len(expression) > 256:
        raise ValueError(
            f"S19: derivation_grammar: expression length {len(expression)} exceeds 256"
        )
    tokens = _derivation_tokens(expression)
    if not tokens:
        raise ValueError(f"S19: derivation_grammar: expression {expression!r} carries no tokens")
    position = 0
    depth = 0
    ordered: list[str] = []
    seen: set[str] = set()

    def take() -> tuple[str, str]:
        nonlocal position
        if position >= len(tokens):
            raise ValueError(
                f"S19: derivation_grammar: unexpected end of expression {expression!r}"
            )
        token = tokens[position]
        position += 1
        return token

    def peek() -> tuple[str, str] | None:
        return tokens[position] if position < len(tokens) else None

    def atom() -> None:
        nonlocal depth
        kind, text = take()
        if kind == "id":
            if text not in seen:
                seen.add(text)
                ordered.append(text)
            return
        if kind == "num":
            return
        if kind == "(":
            depth += 1
            if depth > 32:
                raise ValueError(
                    f"S19: derivation_grammar: parenthesis nesting exceeds 32 "
                    f"in {expression!r}"
                )
            expression_rule()
            closing = take()
            if closing[0] != ")":
                raise ValueError(
                    f"S19: derivation_grammar: expected ')' but found "
                    f"{closing[1]!r} in {expression!r}"
                )
            depth -= 1
            return
        raise ValueError(
            f"S19: derivation_grammar: unexpected {text!r} where an operand "
            f"was expected in {expression!r}"
        )

    def factor() -> None:
        token = peek()
        if token is not None and token[0] in ("+", "-"):
            take()
            factor()
            return
        atom()

    def term() -> None:
        factor()
        while (token := peek()) is not None and token[0] in ("*", "/"):
            take()
            factor()

    def expression_rule() -> None:
        term()
        while (token := peek()) is not None and token[0] in ("+", "-"):
            take()
            term()

    expression_rule()
    trailing = peek()
    if trailing is not None:
        raise ValueError(
            f"S19: derivation_grammar: unexpected {trailing[1]!r} after a "
            f"complete expression in {expression!r}"
        )
    if not ordered:
        raise ValueError(
            f"S19: derivation_grammar: expression {expression!r} references no "
            "dataset variable (constant-only expressions cannot carry the "
            "derivation marker's operand_ids)"
        )
    return ordered


def _check_derived_variables(derived: Any) -> None:
    """S19: grammar and static checks over ``derived_variables``.

    Checked: array/entry shape; id grammar and uniqueness; expression
    length, character surface, token formation and nesting; at least one
    identifier; no self-reference; the derived-from-derived graph is
    acyclic in declaration order. NOT checked (evaluation-time in the
    gateway, not admission): operand existence in any dataset and unit
    agreement — operand units live in datasets.
    """

    if not isinstance(derived, list):
        raise ValueError(
            f"S19: derivation_shape: derived_variables must be a list, "
            f"got {type(derived).__name__}"
        )
    parsed: list[tuple[str, list[str]]] = []
    for entry in derived:
        if not isinstance(entry, dict):
            raise ValueError(f"S19: derivation_shape: declaration {entry!r} is not an object")
        for field in ("id", "quantity", "unit", "expression"):
            value = entry.get(field)
            if not isinstance(value, str):
                raise ValueError(f"S19: derivation_shape: declaration requires string {field}")
            if field != "expression" and not value:
                raise ValueError(
                    f"S19: derivation_shape: declaration requires non-empty string {field}"
                )
        if not re.fullmatch(r"[a-z][a-z0-9_]*", entry["id"]):
            raise ValueError(
                f"S19: derivation_shape: derived id {entry['id']!r} must match "
                "^[a-z][a-z0-9_]*$"
            )
        parsed.append((entry["id"], _derivation_identifiers(entry["expression"])))
    seen: set[str] = set()
    for index, (identifier, operands) in enumerate(parsed):
        if identifier in seen:
            raise ValueError(
                f"S19: derivation_duplicate_id: {identifier!r} declared more than once"
            )
        seen.add(identifier)
        if identifier in operands:
            raise ValueError(
                f"S19: derivation_self_reference: {identifier!r} appears in its "
                "own expression"
            )
        for operand in operands:
            for earlier in range(index):
                if parsed[earlier][0] == operand:
                    break
            else:
                for later in range(index + 1, len(parsed)):
                    if parsed[later][0] == operand:
                        raise ValueError(
                            f"S19: derivation_cycle: {identifier!r} references "
                            f"{operand!r}, declared later (declaration order is "
                            "the evaluation order)"
                        )


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
    try:
        validate(descriptor, "otdp/0.2.0/otdp-device-descriptor.schema.json")
    except ValueError:
        # When derived_variables is present, S19 runs even on a
        # schema-invalid document: the derivation_*: reason is the
        # actionable one for the author, and both checkers (this lane and
        # the gateway admission seam) then agree on the census prefixes.
        if isinstance(descriptor, dict) and isinstance(
            descriptor.get("derived_variables"), list
        ):
            _check_derived_variables(descriptor["derived_variables"])
        raise
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
    if "derived_variables" in descriptor:
        _check_derived_variables(descriptor["derived_variables"])
