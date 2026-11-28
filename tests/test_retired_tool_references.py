# author: Stephen Eaton
"""No live file names Gortex (issue #664, finding 3).

Gortex was the code-intelligence layer this repository moved off. Its name stays in
the records written while it was in use, and those records are frozen: a design record is
evidence of what was decided and when, so it is not retrofitted.

The criterion, as narrowed for issue #664:

> AC-1 (narrowed): zero LIVE references to gortex, meaning active instructions, hooks,
> config and ignores. Immutable historical records are excluded and named in the PR body.
> Historical records are never retrofitted (the repository's frozen-bytes convention).

The arm reads every tracked file outside the frozen records, so "live" is not a hand
list: a new file is live by existing, and a reference moved into any live file is found.

The frozen records here are ``.claude/deep-review/`` (design records), ``docs/superpowers/``
(plans and specs) and ``CHANGELOG.md``.

This file is the one live file outside the frozen records that names the tool. A guard
has to name what it forbids, so it is excluded by its own path and nothing else is.

This is the gateway's ``tests/contract/test_retired_tool_references.py`` in this
repository's flat test layout, over this repository's frozen records.

What this test does NOT catch:

- The frozen records. They are excluded by path, and the count of what they hold is a
  sweep for the PR body, not an assertion here.
- An untracked file. ``docs/superpowers/`` is mostly untracked here; only what git
  tracks is read.
- A binary file: a NUL byte in the first 8 KiB is how git reads one, and it is skipped.
- A tree that is not a git checkout. The arm fails there rather than reading an empty
  list as clean.

The tamper arms feed the classifier the shapes above, so a green arm is a measured zero.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = Path(__file__).resolve().relative_to(ROOT).as_posix()

RETIRED = re.compile("gortex", re.IGNORECASE)

# Records of what was decided while the tool was in use. Their bytes are history.
FROZEN_PREFIXES = (
    ".claude/deep-review/",
    "docs/superpowers/",
)
FROZEN_FILES = ("CHANGELOG.md",)

_BINARY_SNIFF_BYTES = 8192
# Fewer tracked files than this means the listing is wrong (a partial checkout, a
# directory that is not the repository), not that the tree is clean.
_TRACKED_FLOOR = 500


def _is_frozen(relpath: str) -> bool:
    """Whether a tracked path is one of the frozen historical records."""
    return relpath in FROZEN_FILES or relpath.startswith(FROZEN_PREFIXES)


def _is_binary(data: bytes) -> bool:
    """git's own reading of a binary file: a NUL byte in the first 8 KiB."""
    return b"\0" in data[:_BINARY_SNIFF_BYTES]


def _live_lines(relpath: str, data: bytes) -> list[int]:
    """The 1-based lines of one tracked file that name the tool, when the file is live.

    A frozen record, this file, and a binary file read as no lines.
    """
    if _is_frozen(relpath) or relpath == GUARD or _is_binary(data):
        return []
    text = data.decode("utf-8", errors="replace")
    return [
        number for number, line in enumerate(text.splitlines(), start=1) if RETIRED.search(line)
    ]


def _live_hits(tracked: Iterator[tuple[str, bytes]]) -> list[str]:
    """``path:line`` for every line of every live tracked file that names the tool."""
    return [
        f"{relpath}:{number}" for relpath, data in tracked for number in _live_lines(relpath, data)
    ]


def _tracked_files() -> Iterator[tuple[str, bytes]]:
    """Every tracked file of this repository with its bytes, as ``(path from the root,
    bytes)``."""
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    relpaths = [part.decode("utf-8") for part in listing.split(b"\0") if part]
    assert len(relpaths) > _TRACKED_FLOOR, (
        f"git ls-files listed {len(relpaths)} files; fewer than {_TRACKED_FLOOR} is a "
        "wrong tree, not a clean one"
    )
    for relpath in relpaths:
        path = ROOT / relpath
        if path.is_file():
            yield relpath, path.read_bytes()


def test_no_live_file_names_the_retired_tool() -> None:
    hits = _live_hits(_tracked_files())
    assert not hits, (
        "a live file names Gortex, the retired code-intelligence layer (issue #664, "
        "finding 3, AC-1 narrowed): remove the reference from the live file; a historical "
        f"record is never retrofitted: {hits}"
    )


def test_tamper_every_shape_the_classifier_sees() -> None:
    """The classifier's detection power on the shapes the criterion names.

    Six paths are live and flagged, case-insensitively and wherever the name sits: one
    is a path that does not exist yet, because a new file is live by existing. Five are
    frozen records or this file and read as no lines. A binary file is skipped, and a
    binary file is one with a NUL byte: a blob without one is text and is scanned.
    """
    for relpath in (
        "AGENTS.md",
        ".gitignore",
        ".claude/settings.json",
        ".claude/hooks/codanna-reindex.ts",
        "template/AGENTS.md.jinja",
        "a/new/file.md",
    ):
        assert _live_lines(relpath, b"see Gortex docs\n") == [1], relpath
        assert _live_lines(relpath, b'<a href="https://example.invalid/x/gortex">G</a>\n') == [1]
        assert _live_lines(relpath, b"nothing here\n") == [], relpath

    for relpath in (
        "CHANGELOG.md",
        ".claude/deep-review/2026-01-01-record.md",
        "docs/superpowers/plans/2026-01-01-plan.md",
        "docs/superpowers/specs/2026-01-01-design.md",
        GUARD,
    ):
        assert _is_frozen(relpath) or relpath == GUARD, relpath
        assert _live_lines(relpath, b"Gortex GORTEX gortex\n") == [], relpath

    # A PNG header: the signature, then the 4-byte length of the IHDR chunk (three NULs).
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR Gortex\n"
    assert _is_binary(png)
    assert _live_lines("docs/assets/logo.png", png) == []
    assert _live_lines("assets/blob.bin", b"Gortex\x00") == [], "a NUL past the name"
    assert not _is_binary(b"text Gortex\n"), "a text file with no NUL byte is not binary"
    assert _live_lines("notes.txt", b"\x89text Gortex\n") == [1]


def test_tamper_the_arm_finds_a_live_reference_and_nothing_else() -> None:
    """Arm 1's detection power over a tree: one live hit is reported with its path and
    line, and the same line in a frozen record is not."""
    tree = [
        ("AGENTS.md", b"intro\nthe owner machine's gortex hooks\n"),
        (".claude/deep-review/2026-01-01-record.md", b"gortex\n"),
        ("CHANGELOG.md", b"- gortex removed\n"),
        (GUARD, b"RETIRED = gortex\n"),
        ("src/probe.py", b"x = 1\n"),
    ]
    assert _live_hits(iter(tree)) == ["AGENTS.md:2"]


def test_the_guard_is_not_inside_the_frozen_records() -> None:
    """If this file were moved under a frozen prefix it would be excluded by path, and
    its own exclusion would no longer be the only one. Fail here, not in silence."""
    assert not _is_frozen(GUARD)
    assert _is_frozen("docs/superpowers/plans/x.md")
    assert not _is_frozen("docs/internal/x.md")


@pytest.mark.parametrize(
    "text",
    ["Gortex", "GORTEX", "gortex", "code-gortex-native", "Gortex's"],
    ids=["capital", "upper", "lower", "inside-a-word", "possessive"],
)
def test_the_name_is_found_in_every_case(text: str) -> None:
    assert RETIRED.search(text)
    assert RETIRED.search("x " + text + " y")
