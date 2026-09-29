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

WHAT THE MATCHER DOES NOT CATCH (G4, fold row 7d): this is a SYNTACTIC
text scan. A version assembled at runtime is invisible to it — string
concatenation, f-strings, ``bytes`` literals, ``%``/``.format``/``str.join``
composition, and values read from data files all escape. Catching those
needs AST-level taint tracking, deliberately NOT attempted in this fold;
the review lanes carry that duty until then.

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
