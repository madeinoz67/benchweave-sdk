"""Offline schema checks and a small explicitly bounded semantic check set."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from functools import cache
from importlib.resources import files
from pathlib import Path, PurePosixPath
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
            project = tomllib.load(handle).get("project")
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError):
        # tomllib reports bytes that are not UTF-8 as UnicodeDecodeError.
        return None
    name = project.get("name") if isinstance(project, dict) else None
    return name if isinstance(name, str) else None


@cache
def contract_documents() -> dict[str, Any]:
    """Return the bundled standards documents keyed by relative path.

    Documents load once from the vendored ``standards/`` tree (falling
    back to the repository checkout during editable development) under
    keys such as ``otdp/0.2.0/otdp-runtime.schema.json``.
    """
    vendored = files("benchweave_sdk").joinpath("standards")
    sets = (
        ("otdp", "0.2.1"),
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
    validate(request, "otdp/0.2.1/otdp-runtime.schema.json", "operationRequest")


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
    validate(result, "otdp/0.2.1/otdp-runtime.schema.json", "operationResult")
    if (result["operation_id"], result["verb"]) != (request["operation_id"], request["verb"]):
        raise ValueError("Result correlation does not match the request")


# ---------------------------------------------------------------------------
# Transport providers (0.2.1): declaration census, contract validation, pins
# ---------------------------------------------------------------------------

#: The sanctioned provider sub-namespace (transport-providers §2).
_PROVIDER_FEATURE_NAMESPACE = "otdp.transport."

#: The generic §8.1 transfer kinds (specification §8.1; transport-providers
#: §3): a provider grammar introduces NEW kinds and never shadows one. The
#: set is prose-carried — the vendored runtime schema does not enumerate the
#: transaction kinds — so it is spelled here and moves with the corpus.
_RESERVED_TRANSFER_KINDS = frozenset(
    {
        "stream_send",
        "stream_receive",
        "stream_exchange",
        "can_receive",
        "can_send",
        "i2c_transfer",
        "spi_transfer",
    }
)

#: The required_features id shape (the descriptor schema's items pattern).
_FEATURE_ID = re.compile(r"^[a-z][a-z0-9_.-]*/[0-9]+\.[0-9]+(?:\.[0-9]+)?$")


def _otdp_document(suffix: str) -> str:
    """The one vendored OTDP document ending in ``suffix``, any version."""
    matches = [
        key
        for key in contract_documents()
        if key.startswith("otdp/") and key.endswith(f"/{suffix}")
    ]
    if len(matches) != 1:
        raise ValueError(
            f"unknown_contract_schema: expected one vendored otdp {suffix!r}, found {matches}"
        )
    return matches[0]


@cache
def _corpus_known_otdp_features() -> frozenset[str]:
    """The corpus-known ``otdp.*`` feature ids, derived from the vendored tree.

    The lanes are the feature-shaped ``const`` values the vendored descriptor
    schema itself carries — its ``required_features`` contains-conditions
    spell exactly the core lanes (five at 0.2.1) — and the profiles are the
    vendored catalog's ``profiles[].id`` (twelve at 0.2.1). The closure rule
    is transport-providers §2: an ``otdp.*`` identifier that is neither
    corpus-known (the core lanes and catalog profile ids) nor declared
    through a transport-provider object is a refusal at every admission
    point — the namespace is corpus-owned, and a typo must not sail through.
    """
    documents = contract_documents()
    lanes: set[str] = set()

    def sweep(node: object) -> None:
        if isinstance(node, dict):
            const = node.get("const")
            if isinstance(const, str) and _FEATURE_ID.fullmatch(const):
                lanes.add(const)
            for value in node.values():
                sweep(value)
        elif isinstance(node, list):
            for item in node:
                sweep(item)

    sweep(documents[_otdp_document("otdp-device-descriptor.schema.json")])
    catalog = documents[_otdp_document("device-profile-catalog.json")]
    profiles = {profile["id"] for profile in catalog["profiles"]}
    return frozenset(lanes | profiles)


def _check_provider_features(descriptor: dict[str, Any]) -> None:
    """S04 (extended): provider declarations and the closed ``otdp.*`` namespace.

    Three refusals, in this order so each single fault lands on its named
    prefix (transport-providers §2):

    - ``provider_feature_missing:`` a pinned provider whose feature the
      integration does not require;
    - ``provider_transport_undeclared:`` an ``otdp.transport.*`` feature with
      no effective declaration — no provider object at all, or one pinning
      a different feature. A declaration is effective only on the ``custom``
      transport of an adapter-mode integration (specification §6.4); the
      schema itself refuses the misplaced shapes — the transport arms are
      closed objects, and the declarative row's enum names custom's
      non-members — so this sweep runs after it and judges the census;
    - ``unknown_otdp_feature:`` any other ``otdp.*`` id that is neither
      corpus-known nor declared. The ``otdp.transport.*`` sub-namespace is
      the sweep's own to judge, so the closure never double-reports it.
    """
    transport = descriptor["transport"]
    provider = transport.get("provider")
    required = descriptor["required_features"]
    if isinstance(provider, dict) and provider.get("feature_id") not in required:
        raise ValueError(
            f"provider_feature_missing: {provider.get('feature_id')!r} is pinned by "
            "the transport provider but is not in required_features"
        )
    effective = (
        isinstance(provider, dict)
        and transport.get("type") == "custom"
        and descriptor["integration"]["mode"] == "adapter"
    )
    for feature in required:
        if not feature.startswith(_PROVIDER_FEATURE_NAMESPACE):
            continue
        if effective and feature == provider.get("feature_id"):
            continue
        if not isinstance(provider, dict):
            detail = "no transport provider is declared"
        else:
            detail = "the declared provider pins a different feature_id"
        raise ValueError(
            f"provider_transport_undeclared: {feature!r} is required but {detail}"
        )
    known = _corpus_known_otdp_features()
    for feature in required:
        if not feature.startswith("otdp.") or feature.startswith(_PROVIDER_FEATURE_NAMESPACE):
            continue
        if feature not in known:
            raise ValueError(
                f"unknown_otdp_feature: {feature!r} is neither a corpus feature nor "
                "declared through a transport provider; the otdp.* namespace is "
                "corpus-owned"
            )


def validate_transport_provider(document: Any) -> None:
    """Validate a transport-provider contract document offline (0.2.1).

    The vendored ``otdp-transport-provider.schema.json`` — which also holds
    the ``otdp.transport.*`` namespace rule for the contract's own
    ``feature_id`` — plus the checks JSON Schema cannot express
    (transport-providers §1/§3):

    - each grammar entry's ``request_schema``/``result_schema`` meta-validates
      as Draft 2020-12: the schema's ``{"type": "object"}`` holders admit
      any object, including schemas the metaschema refuses;
    - grammar kinds are unique as strings across the grammar: the schema's
      ``uniqueItems`` refuses byte-identical entries only;
    - no grammar kind reuses a generic §8.1 transfer kind: provider grammars
      extend the table, never shadow it;
    - the three identity equalities hold: urn-embedded version == ``version``,
      feature_id-embedded version == ``version``, and the feature_id name
      segment == the urn name segment.

    Raises
    ------
    ValueError
        ``provider_contract_invalid:`` — structure only; JSON validity grants
        no authority, and admission stays a host-side act.
    """
    try:
        validate(document, "otdp/0.2.1/otdp-transport-provider.schema.json")
    except ValueError as exc:
        raise ValueError(f"provider_contract_invalid: {exc}") from exc
    grammar = document["transaction_grammar"]
    kinds: list[str] = []
    for entry in grammar:
        kind = entry["kind"]
        if kind in _RESERVED_TRANSFER_KINDS:
            raise ValueError(
                f"provider_contract_invalid: grammar kind {kind!r} reuses a generic "
                "transfer-table kind; a provider grammar extends the table and never "
                "shadows it"
            )
        for field in ("request_schema", "result_schema"):
            try:
                Draft202012Validator.check_schema(entry[field])
            except SchemaError as exc:
                raise ValueError(
                    f"provider_contract_invalid: {kind}.{field} is not a valid "
                    "Draft 2020-12 schema"
                ) from exc
        kinds.append(kind)
    if len(set(kinds)) != len(kinds):
        raise ValueError(
            "provider_contract_invalid: grammar kinds must be unique strings across "
            "transaction_grammar"
        )
    version = document["version"]
    urn_parts = document["id"].split(":")
    urn_name, urn_version = urn_parts[3], urn_parts[4]
    feature_name, _, feature_version = (
        document["feature_id"][len(_PROVIDER_FEATURE_NAMESPACE) :].rpartition("/")
    )
    if urn_version != version:
        raise ValueError(
            f"provider_contract_invalid: the id embeds version {urn_version!r} but the "
            f"contract is version {version!r}"
        )
    if feature_version != version:
        raise ValueError(
            f"provider_contract_invalid: the feature_id embeds version {feature_version!r} "
            f"but the contract is version {version!r}"
        )
    if feature_name != urn_name:
        raise ValueError(
            f"provider_contract_invalid: the feature_id names {feature_name!r} but the "
            f"id names {urn_name!r}"
        )


def verify_provider_pin(
    descriptor: dict[str, Any], descriptor_path: Path
) -> dict[str, Any] | None:
    """Resolve and verify the descriptor's pinned provider contract (check lane).

    The provider triple resolves **relative to the descriptor's own package
    root** — the descriptor's directory — so a plugin and its pinned
    contract travel one package (transport-providers §2; the bundle-root
    rule governs only the root ``contracts`` array). The pin must name a
    contained regular file — no traversal, no absolute path, no symlinked
    component — hash to the pinned ``sha256``, parse, pass
    :func:`validate_transport_provider`, and agree with the declaration's
    ``feature_id`` and ``id`` (the feature-id agreement transport-providers
    §7 lists as offline-provable).

    Raises
    ------
    ValueError
        ``provider_contract_missing:`` (the pin does not resolve inside the
        package), ``provider_contract_hash_mismatch:`` (bytes disagree with
        the pin), or ``provider_contract_invalid:`` (the document is not a
        valid, agreeing contract). Returns None when the descriptor declares
        no provider: the unbacked custom transport stays the
        honestly-incomplete posture, not a refusal.
    """
    transport = descriptor.get("transport")
    provider = transport.get("provider") if isinstance(transport, dict) else None
    if not isinstance(provider, dict):
        return None
    relative = provider["path"]
    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or PurePosixPath(relative).is_absolute()
        or any(part in (".", "..") for part in relative.split("/"))
        or any(not part for part in relative.split("/"))
    ):
        raise ValueError(
            f"provider_contract_missing: {relative!r} is not a package-relative pin path"
        )
    package_root = descriptor_path.parent
    target = package_root
    for part in PurePosixPath(relative).parts:
        target = target / part
        if target.is_symlink():
            raise ValueError(
                f"provider_contract_missing: {relative!r} crosses a symlink; a provider "
                "pin resolves inside the plugin's own package only"
            )
    if not target.is_file() or not target.resolve().is_relative_to(package_root.resolve()):
        raise ValueError(
            f"provider_contract_missing: {relative!r} does not name a contained regular "
            "file in the descriptor's package"
        )
    from .presentation import read_file  # local: presentation imports this module

    raw = read_file(target)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != provider["sha256"]:
        raise ValueError(
            f"provider_contract_hash_mismatch: {relative!r} hashes to {digest} but the "
            f"descriptor pins {provider['sha256']}"
        )
    try:
        parsed: Any = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"provider_contract_invalid: {relative!r} is not JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(
            f"provider_contract_invalid: {relative!r} is not a JSON object"
        )
    document: dict[str, Any] = parsed
    validate_transport_provider(document)
    if (
        document.get("feature_id") != provider["feature_id"]
        or document.get("id") != provider["id"]
    ):
        raise ValueError(
            f"provider_contract_invalid: the pinned contract at {relative!r} does not "
            "declare the descriptor's provider feature and identity"
        )
    return document


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
    parameter names must be unique (S01), parameter bounds must not
    be reversed (S02), and provider declarations must cohere with
    ``required_features`` and the corpus-owned ``otdp.*`` namespace (S04).

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
        validate(descriptor, "otdp/0.2.1/otdp-device-descriptor.schema.json")
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
        # The descriptor schema types ``range`` as a two-element [min, max]
        # array; the earlier mapping-shaped check could never fire.
        bounds = parameter.get("range")
        if isinstance(bounds, list | tuple) and len(bounds) == 2 and bounds[0] > bounds[1]:
            raise ValueError("S02: parameter bounds are reversed")
    _check_provider_features(descriptor)
    if "derived_variables" in descriptor:
        _check_derived_variables(descriptor["derived_variables"])
