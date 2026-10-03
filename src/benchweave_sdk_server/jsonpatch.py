"""Hand-rolled JSON Patch and JSON Pointer (RFC 6902/6901) — SW-36.

The authoring surface patches the plugin's JSON contract documents, and the
design rules out a new runtime dependency for it: the op set is closed
(``add``/``remove``/``replace``/``move``/``copy``/``test``), the pointer
grammar is small, and everything outside the RFC fails loudly by name — the
fail-loud closed-set discipline the catalogue already carries. The tests pin
the implementation against the RFC's own examples (Appendix A and §4), not
against a third-party implementation's behaviour.

Two rules the callers rely on, both structural:

- :func:`apply_patch` works on a deep copy and returns a NEW document; the
  input is never mutated, so a patch that fails on its last operation
  leaves the caller's document exactly as it was (the in-memory half of
  SW-36's failing-patch-writes-nothing rule).
- ``test`` compares with JSON semantics: booleans never equal numbers
  (Python's ``True == 1`` is a type-system accident, not a JSON fact).
"""

from __future__ import annotations

import copy
import re
from typing import Any

#: The closed RFC 6902 operation set. An operation naming anything else is
#: refused with ``unknown_op`` — silently ignoring an op is how documents
#: drift (the closed-vocabulary rule, applied at patch granularity).
OP_CODES: frozenset[str] = frozenset(
    {"add", "remove", "replace", "move", "copy", "test"}
)

_INDEX: re.Pattern[str] = re.compile(r"^(0|[1-9][0-9]*)$")


class JSONPatchError(ValueError):
    """A refused patch or pointer: a stable code plus a human message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"json_patch_{code}: {message}")
        self.code = code
        self.message = message


# --- RFC 6901 pointers ---------------------------------------------------------


def parse_pointer(pointer: str) -> list[str]:
    """Split one RFC 6901 pointer into its reference tokens.

    ``""`` is the whole document; ``/a/b`` is ``["a", "b"]``; ``~1`` and
    ``~0`` escape ``/`` and ``~`` respectively (in that order, so ``~01``
    is the literal ``~1``). A non-empty pointer that does not start with
    ``/``, or an escape character followed by anything but ``0``/``1``, is
    refused.
    """
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise JSONPatchError("pointer_not_rooted", f"pointer: {pointer!r}")
    tokens: list[str] = []
    for token in pointer[1:].split("/"):
        index = 0
        while True:
            found = token.find("~", index)
            if found < 0:
                break
            if found + 1 >= len(token) or token[found + 1] not in "01":
                raise JSONPatchError(
                    "bad_escape", f"token {token!r}: ~ is only ~0 or ~1"
                )
            index = found + 2
        # Order matters: ~1 first, so ~01 keeps its literal 1 (RFC 6901 §3).
        tokens.append(token.replace("~1", "/").replace("~0", "~"))
    return tokens


def _walk(document: Any, tokens: list[str]) -> Any:
    """Resolve ``tokens`` to a location; raise when the path does not hold."""
    current = document
    for token in tokens:
        if isinstance(current, dict):
            if token not in current:
                raise JSONPatchError("target_missing", f"no member {token!r}")
            current = current[token]
        elif isinstance(current, list):
            index = _array_index(token, len(current))
            current = current[index]
        else:
            raise JSONPatchError(
                "escapes_scalar", f"cannot descend into {type(current).__name__}"
            )
    return current


def _parent(document: Any, tokens: list[str]) -> tuple[dict[str, Any] | list[Any], str]:
    """Resolve a token list to its (container, last-token) pair."""
    if not tokens:
        raise JSONPatchError("root_has_no_parent", "the document root has no parent")
    current: Any = document
    for token in tokens[:-1]:
        if isinstance(current, dict):
            if token not in current:
                raise JSONPatchError("target_missing", f"no member {token!r}")
            current = current[token]
        elif isinstance(current, list):
            current = current[_array_index(token, len(current))]
        else:
            raise JSONPatchError(
                "escapes_scalar", f"cannot descend into {type(current).__name__}"
            )
    if not isinstance(current, (dict, list)):
        raise JSONPatchError(
            "escapes_scalar", f"cannot patch into {type(current).__name__}"
        )
    return current, tokens[-1]


def _array_index(token: str, length: int) -> int:
    """An array index that must exist (RFC 6901: no leading zeros, no ``-``)."""
    if not _INDEX.match(token):
        raise JSONPatchError("index_invalid", f"array index: {token!r}")
    index = int(token)
    if index >= length:
        raise JSONPatchError("index_out_of_range", f"index {index} of {length}")
    return index


def _insert_index(token: str, length: int) -> int:
    """An array index for ``add``: one past the end appends via ``-``."""
    if token == "-":
        return length
    if not _INDEX.match(token):
        raise JSONPatchError("index_invalid", f"array index: {token!r}")
    index = int(token)
    if index > length:
        raise JSONPatchError("index_out_of_range", f"index {index} of {length}")
    return index


def _json_equal(left: Any, right: Any) -> bool:
    """JSON equality: two literal kinds, numbers numerically equal,
    structures recursively equal — booleans never equal numbers."""
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, (dict, list)) != isinstance(right, (dict, list)):
        return False
    return bool(left == right)


# --- RFC 6902 operations ---------------------------------------------------------


def _op_add(document: Any, tokens: list[str], value: Any) -> Any:
    if not tokens:
        # RFC 6902 §4.1: adding at the root replaces the whole document.
        return copy.deepcopy(value)
    container, key = _parent(document, tokens)
    if isinstance(container, dict):
        container[key] = copy.deepcopy(value)
    else:
        container.insert(_insert_index(key, len(container)), copy.deepcopy(value))
    return document


def _op_remove(document: Any, tokens: list[str]) -> Any:
    container, key = _parent(document, tokens)
    if isinstance(container, dict):
        if key not in container:
            raise JSONPatchError("target_missing", f"no member {key!r}")
        del container[key]
    else:
        del container[_array_index(key, len(container))]
    return document


def _op_test(document: Any, tokens: list[str], value: Any) -> Any:
    actual = _walk(document, tokens)
    if not _json_equal(actual, value):
        raise JSONPatchError(
            "test_failed", f"value at pointer is {actual!r}, patch tested {value!r}"
        )
    return document


def apply_patch(document: Any, patch: Any) -> Any:
    """Apply one JSON Patch (a list of RFC 6902 operations) and return the
    new document. The input is never mutated; any refused operation raises
    :class:`JSONPatchError` and discards the whole patch — including the
    operations before the failing one.
    """
    if not isinstance(patch, list):
        raise JSONPatchError("patch_not_array", "a JSON Patch is an array of operations")
    result = copy.deepcopy(document)
    for position, operation in enumerate(patch):
        if not isinstance(operation, dict):
            raise JSONPatchError(
                "operation_not_object", f"operation {position} is not an object"
            )
        op = operation.get("op")
        if op not in OP_CODES:
            raise JSONPatchError("unknown_op", f"operation {op!r} is not in the RFC 6902 set")
        if not isinstance(operation.get("path"), str):
            raise JSONPatchError("path_missing", f"operation {op!r} has no path")
        tokens = parse_pointer(operation["path"])
        if op == "add":
            if "value" not in operation:
                raise JSONPatchError("value_missing", "add needs a value")
            result = _op_add(result, tokens, operation["value"])
        elif op == "remove":
            result = _op_remove(result, tokens)
        elif op == "replace":
            if "value" not in operation:
                raise JSONPatchError("value_missing", "replace needs a value")
            if not tokens:
                # Replacing the root: RFC 6902 §4.3 defers to add's semantics.
                result = copy.deepcopy(operation["value"])
            else:
                container, key = _parent(result, tokens)
                if isinstance(container, dict):
                    if key not in container:
                        raise JSONPatchError("target_missing", f"no member {key!r}")
                    container[key] = copy.deepcopy(operation["value"])
                else:
                    index = _array_index(key, len(container))
                    container[index] = copy.deepcopy(operation["value"])
        elif op in ("move", "copy"):
            source = operation.get("from")
            if not isinstance(source, str):
                raise JSONPatchError("from_missing", f"{op} needs a from location")
            if op == "move" and source == operation["path"]:
                # RFC 6902 §4.4: equal from and path leave the value in place.
                continue
            source_tokens = parse_pointer(source)
            if op == "move" and len(tokens) > len(source_tokens) and (
                tokens[: len(source_tokens)] == source_tokens
            ):
                # The pointer-level proper-prefix check (both container
                # forms): the destination is INSIDE the subtree being
                # moved. The dict form trips the structural failure on its
                # own (remove-then-add cannot reach the target); the array
                # form's re-indexing RESOLVES the post-removal path and
                # silently accepted a move of a value into itself.
                raise JSONPatchError(
                    "move_into_self",
                    f"cannot move {source!r} into its own descendant "
                    f"{operation['path']!r}",
                )
            value = copy.deepcopy(_walk(result, source_tokens))
            if op == "move":
                result = _op_remove(result, source_tokens)
            result = _op_add(result, tokens, value)
        else:  # test
            if "value" not in operation:
                raise JSONPatchError("value_missing", "test needs a value")
            result = _op_test(result, tokens, operation["value"])
    return result
