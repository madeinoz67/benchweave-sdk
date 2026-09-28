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

THE REGISTER — the exemption list with teeth (the gateway register's own
shape, #221 §1.3): each entry names a file, the reason it is authored data
rather than a derivation site, and the EXACT number of literals it may
carry. A new literal inside a registered file fails the gate until the
register row is edited — a visible editorial diff.

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

# The registered-exception register (the gateway counter's rows for this
# tree, #221 §1.3): display-relative path -> (reason, expected_sites).
REGISTER: dict[str, tuple[str, int]] = {
    "src/benchweave_sdk/standards/plugin-ui/contracts.py": (
        "VR-25 branch 2 / D2: plugin-ui corpus-owned code, byte-identical to "
        "its gateway twin (tests/sdk/test_presentation_packaging.py pins the "
        "identity); motion = the D2 reopen trigger",
        3,
    ),
    "src/benchweave_sdk/scaffold.py": (
        "authored example-template fields that are not standards references "
        "(descriptor_version, firmware version, adapter version, provenance "
        "revision); the otdp_version example IS derived "
        "(served.active_version) and stays outside this row",
        4,
    ),
}

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src" / "benchweave_sdk"


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


def count_sites() -> list[dict[str, Any]]:
    """Every executable literal site, sorted for reproducibility."""
    sites: list[dict[str, Any]] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
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
    return sorted(sites, key=lambda row: (row["file"], row["line"], row["pattern"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print per-site rows")
    arguments = parser.parse_args(argv)
    try:
        sites = count_sites()
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
        reason, expected = REGISTER[file_name]
        found = len(by_file.get(file_name, []))
        if found != expected:
            violations.append(
                f"register expectation failed: {file_name} expects {expected} "
                f"literals, found {found} ({reason})"
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
                    "scanned": len(set(row["file"] for row in sites)),
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
        f"({len(sites)} sites, {verdict})"
    )
    for violation in violations:
        print(f"  {violation}")
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
