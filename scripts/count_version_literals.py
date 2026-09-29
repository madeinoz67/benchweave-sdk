#!/usr/bin/env python3
"""Count standards-version literals in the SDK source tree — ZERO-MODE.

The gateway repo's ``scripts/standards/count_version_literals.py`` is the
definition's authority; this twin copies that definition VERBATIM (the AST
walk, Pattern A + bare-semver, docstrings excluded) and scopes it to this
repository's ``src/benchweave_sdk/`` with this repository's register rows.
The pairing is bound by the gateway's drift-and-obligations counter-sync
row: a change to either copy's DEFINITION or register semantics re-syncs
the other in the same work.

Why a twin (issue #221, design §1.5, the A6 two-sided posture): an SDK-only
PR cannot add a version literal between gateway pointer bumps — this lane
refuses it immediately, and the gateway's ``sdk`` scope re-checks the same
tree at every bump.

DEFINITION (committed; changing it re-baselines by editorial decision, not
silently — and re-syncs the gateway twin in the same work):

- A **version literal** is a string constant in EXECUTABLE code — docstrings
  are excluded (the first string statement of a module, class, or function
  body). Comments are not code and never count.
- Pattern A: a string containing ``<standard-id>/<X.Y.Z>`` for one of the six
  governed standards ids — the path-shaped literal (``execution/0.2.0``).
- Pattern B: a string that IS a bare ``X.Y.Z`` (three-component pure semver),
  counted EVERYWHERE in executable code.

WHAT THE MATCHER DOES NOT CATCH (G4, fold row 7d; issue #269 rewrite): the
matcher folds CONSTANT-ONLY assembly — concatenation, f-strings,
``%``-formatting, ``.format``, ``str.join`` over literal sequences,
``chr``/``str`` over literals, ``bytes.decode``, and string repetition —
and refuses the folded result under the same two patterns (``ASM-A`` /
``ASM-BARE``; bounds: fold depth ≤ 24, folded length ≤ 4096; a module that
shadows ``chr``/``str`` is never folded as the builtins; every fold
failure is an honest miss, never a gate failure). Assembly with ANY
non-literal input — a variable, parameter, function result, comprehension,
or a value read from data, environment, or configuration — remains
invisible: catching that needs taint tracking, still deliberately not
attempted (the follow-on row; the review lanes carry it). ``os.path.join``
and other stdlib string constructors are outside the fold allowlist (named
residual, deferral D-3).

DENOMINATOR BOUNDARY (G1's honest scope, fold row 13): this lane gates
``src/benchweave_sdk/`` only. ``scripts/``, ``tests/`` and ``.github/`` of
this repository are OUTSIDE the gate; the gateway's lanes own the gateway,
plugin and docs trees.

THE REGISTER — the exemption list with teeth (the gateway register's own
shape, #221 §1.3): each entry names a file, the reason it is authored data
rather than a derivation site, and the EXACT number of literals it may
carry; authored-data rows additionally pin the literal VALUES
(``expected_values``), so a semantics-changing substitution fails at
unchanged cardinality. A new literal inside a registered file fails the
gate until the register row is edited — a visible editorial diff. The
contracts.py row carries no value pin because the copies are digest-pinned
whole (``tests/sdk/test_presentation_packaging.py``).

Exit status: 0 when the count outside the register is 0 AND every register
row's expectation holds, 1 otherwise (or on any parse failure — a count
that cannot be computed is a refusal, never a guess). ``--json`` prints
per-site rows for review — registered-file sites carry ``exempt: true``
and the register reason; the display never hides what the gate forgives.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import warnings
from pathlib import Path
from typing import Any

STANDARD_IDS = ("otdp", "registry", "execution", "interface", "plugin-ui", "plugin-ui-preview")
PATTERN_A = re.compile(r"\b(?:" + "|".join(STANDARD_IDS) + r")/\d+\.\d+\.\d+")
PATTERN_BARE = re.compile(r"^\d+\.\d+\.\d+$")

# Environment components ignored in the scan (the gateway counter's filter,
# ported fold row 5): a stray environment inside src/ must make zero-mode
# FAIL loudly if it ever lands in scope, not silently join the census.
ENVIRONMENT_COMPONENTS = frozenset({"venv", ".venv", "node_modules", "site-packages"})

# The registered-exception register (the gateway counter's rows for this
# tree, #221 §1.3): display-relative path -> (reason, expected_sites,
# expected_values). expected_values pins the sorted BARE-literal values for
# authored-data rows (fold row 6); the contracts.py copy is digest-pinned
# whole, so it carries None there.
REGISTER: dict[str, tuple[str, int, tuple[str, ...] | None]] = {
    "src/benchweave_sdk/standards/plugin-ui/contracts.py": (
        "VR-25 branch 2 / D2: plugin-ui corpus-owned code, byte-identical to "
        "its gateway twin (tests/sdk/test_presentation_packaging.py pins the "
        "identity — digest-pinned whole, so no value pin here); motion = the "
        "D2 reopen trigger",
        3,
        None,
    ),
    "src/benchweave_sdk/scaffold.py": (
        "authored example-template fields that are not standards references "
        "(descriptor_version, firmware version, adapter version, provenance "
        "revision); the otdp_version example IS derived "
        "(served.active_version) and stays outside this row",
        4,
        ("0.1.0", "0.1.0", "0.1.0", "1.0.0"),
    ),
}

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src" / "benchweave_sdk"


class StandardSetDrift(Exception):
    """A committed authority disagrees with the matcher's pinned sets."""


def _pin_standard_ids() -> None:
    """The committed standard-id set is the matcher's authority (fold row 5):
    ``STANDARD_IDS`` must equal the standards lock's row ids — this
    repository's authority for the governed set (it carries no standards
    manifest; the lock is what ``benchweave_sdk.served`` derives from). A
    seventh standard would otherwise silently narrow Pattern A's coverage —
    the script refuses instead, and adding the id becomes a deliberate,
    reviewable edit to this file.
    """
    lock_path = REPO_ROOT / "standards-lock.json"
    document = json.loads(lock_path.read_text(encoding="utf-8"))
    lock_ids = sorted({str(row.get("id")) for row in document.get("standards", [])})
    if lock_ids != sorted(STANDARD_IDS):
        raise StandardSetDrift(
            f"standard_set_drift: the standards lock declares {lock_ids} but the "
            f"matcher pins {sorted(STANDARD_IDS)} — update STANDARD_IDS in this "
            "script in the same work as the lock change"
        )


def _docstring_ids(tree: ast.Module) -> set[int]:
    """Ids of the Constant nodes that are docstrings (first string statement)."""
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                skip.add(id(body[0].value))
    return skip


# --- constant-folding assembly detection (issue #269, design §1.1) ---------
# Bounds: a fold attempt exceeding either is UNFOLDABLE (an honest miss,
# never an error).
FOLD_MAX_DEPTH = 24
FOLD_MAX_LENGTH = 4096


class _Unfoldable(Exception):
    """The evaluator's universal miss: this expression is not constant-only."""


def _shadowed_builtin_names(tree: ast.Module) -> frozenset[str]:
    """Module-level names binding ``chr``/``str`` — a module that shadows a
    builtin must never have its calls folded AS the builtin (a local
    ``def chr`` returning something else would fold lies)."""
    shadowed: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if node.name in ("chr", "str"):
                shadowed.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("chr", "str"):
                    shadowed.add(target.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id in ("chr", "str"):
                shadowed.add(node.target.id)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".", 1)[0]
                if bound in ("chr", "str"):
                    shadowed.add(bound)
    return frozenset(shadowed)


def _folded_string(value: object) -> str:
    """The one choke point a folded str passes through: type-checked and
    length-bounded (a longer assembly is pathological — unfoldable)."""
    if not isinstance(value, str):
        raise _Unfoldable
    if len(value) > FOLD_MAX_LENGTH:
        raise _Unfoldable
    return value


def _stringify(value: object) -> str:
    """The f-string/``str()`` conversion over folded values (design §1.1:
    ``int`` → ``"2"``); every other type is unfoldable, not guessed."""
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    raise _Unfoldable


def _fold_expression(node: ast.expr, shadowed: frozenset[str], depth: int = 0) -> object:
    """Fold a constant-only expression to its value, or raise _Unfoldable.

    The allowlist, exactly (design §1.1): constants; f-strings (no
    conversion, no format-spec); ``+`` on two folded strings, ``*``
    string×int (Python's own repetition semantics), ``%`` with a folded
    string left side — the operation APPLIED with Python's own ``%``, never
    re-implemented; ``sep.join(<literal list/tuple of str>)``,
    ``fmt.format(*folded)`` (kwargs unfoldable), ``bytes.decode()``;
    ``chr(i)``/``str(x)`` unless the module shadows the name; list/tuple
    displays fold to list/tuple — the TUPLE rule is load-bearing: ``%``
    accepts only a real tuple, so folding tuples to lists would silently
    unfold every ``%``-tuple shape (battery S5). Every failure is a raise:
    the caller treats ANY exception as an honest miss.
    """
    if depth > FOLD_MAX_DEPTH:
        raise _Unfoldable
    if isinstance(node, ast.Constant):
        if node.value is None or isinstance(node.value, str | int | float | bytes):
            return node.value
        raise _Unfoldable
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(_folded_string(value.value))
            elif isinstance(value, ast.FormattedValue):
                if value.conversion != -1 or value.format_spec is not None:
                    raise _Unfoldable
                parts.append(_stringify(_fold_expression(value.value, shadowed, depth + 1)))
            else:
                raise _Unfoldable
        return _folded_string("".join(parts))
    if isinstance(node, ast.BinOp):
        left = _fold_expression(node.left, shadowed, depth + 1)
        if isinstance(node.op, ast.Add):
            right = _folded_string(_fold_expression(node.right, shadowed, depth + 1))
            return _folded_string(_folded_string(left) + right)
        if isinstance(node.op, ast.Mult):
            right = _fold_expression(node.right, shadowed, depth + 1)
            if isinstance(left, str) and isinstance(right, int) and not isinstance(right, bool):
                return _folded_string(left * right)
            if isinstance(right, str) and isinstance(left, int) and not isinstance(left, bool):
                return _folded_string(right * left)
            raise _Unfoldable
        if isinstance(node.op, ast.Mod):
            template = _folded_string(left)
            operand = _fold_expression(node.right, shadowed, depth + 1)
            try:
                formatted = template % operand
            except Exception as exc:
                raise _Unfoldable from exc
            return _folded_string(formatted)
        raise _Unfoldable
    if isinstance(node, ast.List):
        return [_fold_expression(elt, shadowed, depth + 1) for elt in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_fold_expression(elt, shadowed, depth + 1) for elt in node.elts)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute):
            receiver = node.func.value
            if node.func.attr == "join" and len(node.args) == 1 and not node.keywords:
                separator = _folded_string(_fold_expression(receiver, shadowed, depth + 1))
                argument = node.args[0]
                if not isinstance(argument, ast.List | ast.Tuple):
                    raise _Unfoldable  # comprehensions/generators: unfoldable
                elements = [
                    _folded_string(_fold_expression(elt, shadowed, depth + 1))
                    for elt in argument.elts
                ]
                return _folded_string(separator.join(elements))
            if node.func.attr == "format" and not node.keywords:
                template = _folded_string(_fold_expression(receiver, shadowed, depth + 1))
                arguments = [_fold_expression(arg, shadowed, depth + 1) for arg in node.args]
                try:
                    return _folded_string(template.format(*arguments))
                except Exception as exc:
                    raise _Unfoldable from exc
            if node.func.attr == "decode" and not node.args and not node.keywords:
                payload = _fold_expression(receiver, shadowed, depth + 1)
                if not isinstance(payload, bytes):
                    raise _Unfoldable
                return _folded_string(payload.decode())
            raise _Unfoldable
        if isinstance(node.func, ast.Name):
            if (
                node.func.id == "chr"
                and "chr" not in shadowed
                and len(node.args) == 1
                and not node.keywords
            ):
                code = _fold_expression(node.args[0], shadowed, depth + 1)
                if not isinstance(code, int) or isinstance(code, bool):
                    raise _Unfoldable
                try:
                    return _folded_string(chr(code))
                except ValueError as exc:
                    raise _Unfoldable from exc
            if (
                node.func.id == "str"
                and "str" not in shadowed
                and len(node.args) == 1
                and not node.keywords
            ):
                return _stringify(_fold_expression(node.args[0], shadowed, depth + 1))
        raise _Unfoldable
    raise _Unfoldable


def _fold_sites(tree: ast.Module, relative: str) -> list[dict[str, Any]]:
    """The assembly sites one file's folded expressions produce, outermost
    only: a folded match nested inside another folded match (by span
    containment) is dropped — the OUTER assembled expression is the
    reported site. Inner plain ``Constant`` fragments that independently
    match are NOT touched here (the textual walk owns them; a shape can
    contribute both sites — battery S6/S9)."""
    shadowed = _shadowed_builtin_names(tree)
    folded: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp | ast.JoinedStr | ast.Call | ast.List | ast.Tuple):
            continue
        try:
            value = _fold_expression(node, shadowed)
        except Exception:  # noqa: S112 — ANY raise is an honest miss (design §1.1)
            continue
        if not isinstance(value, str):
            continue  # list/tuple folds only feed nested folds
        kind = None
        if PATTERN_A.search(value):
            kind = "ASM-A"
        elif PATTERN_BARE.match(value.strip()):
            kind = "ASM-BARE"
        if kind is None:
            continue
        folded.append(
            {
                "file": relative,
                "line": node.lineno,
                "pattern": kind,
                "text": value[:80],
                "_box": (
                    node.lineno,
                    node.col_offset,
                    node.end_lineno if node.end_lineno is not None else node.lineno,
                    node.end_col_offset if node.end_col_offset is not None else node.col_offset,
                ),
            }
        )
    unique: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    for row in folded:
        unique.setdefault(row["_box"], row)
    kept = [
        row
        for box, row in unique.items()
        if not any(
            other != box
            and other[0] <= box[0]
            and other[1] <= box[1]
            and other[2] >= box[2]
            and other[3] >= box[3]
            for other in unique
        )
    ]
    for row in kept:
        del row["_box"]
    return kept


def count_sites() -> tuple[list[dict[str, Any]], int]:
    """Every executable literal site, sorted for reproducibility, plus the
    FILES-PARSED census (fold row 5: every scanned file counts, not only
    files carrying sites — the census is the shrinkage detector)."""
    sites: list[dict[str, Any]] = []
    scanned = 0
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        relative_parts = path.relative_to(REPO_ROOT).parts
        if any(component in ENVIRONMENT_COMPONENTS for component in relative_parts):
            continue
        scanned += 1
        relative = path.relative_to(REPO_ROOT).as_posix()
        with warnings.catch_warnings():
            # A docstring escape-sequence warning in scanned source is noise
            # here, not a finding of this counter.
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        skip = _docstring_ids(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in skip:
                continue
            value = node.value
            kind = None
            if PATTERN_A.search(value):
                kind = "A"
            elif PATTERN_BARE.match(value.strip()):
                kind = "BARE"
            if kind is not None:
                sites.append(
                    {"file": relative, "line": node.lineno, "pattern": kind, "text": value[:80]}
                )
        sites.extend(_fold_sites(tree, relative))
    sites.sort(key=lambda row: (row["file"], row["line"], row["pattern"]))
    return sites, scanned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print per-site rows")
    arguments = parser.parse_args(argv)
    try:
        _pin_standard_ids()
        sites, scanned = count_sites()
    except StandardSetDrift as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, SyntaxError) as exc:
        print(f"version_literal_count_failed: {exc}", file=sys.stderr)
        return 1

    by_file: dict[str, list[dict[str, Any]]] = {}
    for row in sites:
        by_file.setdefault(row["file"], []).append(row)
    violations: list[str] = []
    outside = [row for row in sites if row["file"] not in REGISTER]
    for row in outside:
        violations.append(
            f"unregistered literal: {row['file']}:{row['line']} [{row['pattern']}] "
            f"{row['text']} — derive it from the lock or register it with reason "
            "and expected_sites"
        )
    for file_name in sorted(REGISTER):
        reason, expected, expected_values = REGISTER[file_name]
        found_rows = by_file.get(file_name, [])
        found = len(found_rows)
        if found != expected:
            violations.append(
                f"register expectation failed: {file_name} expects {expected} "
                f"literals, found {found} ({reason})"
            )
        if expected_values is not None:
            # Fold row 6: pin the VALUES for authored-data rows — a
            # semantics-changing substitution fails at unchanged cardinality.
            found_values = sorted(row["text"] for row in found_rows)
            if found_values != sorted(expected_values):
                violations.append(
                    f"register value pin failed: {file_name} expects "
                    f"{sorted(expected_values)}, found {found_values} ({reason})"
                )
    for row in sites:
        entry = REGISTER.get(row["file"])
        row["exempt"] = entry is not None
        if entry is not None:
            row["reason"] = entry[0]

    if arguments.json:
        print(
            json.dumps(
                {
                    "mode": "zero",
                    "ok": not violations,
                    "scanned": scanned,
                    "count": len(sites),
                    "outside": len(outside),
                    "violations": violations,
                    "sites": sites,
                },
                indent=2,
            )
        )
        return 0 if not violations else 1

    verdict = "ok" if not violations else "FAILED"
    print(
        f"sdk executable version literals: {len(outside)} outside register "
        f"({len(sites)} sites, {scanned} files scanned, {verdict})"
    )
    for violation in violations:
        print(f"  {violation}")
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
