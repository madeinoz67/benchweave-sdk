# author: Stephen Eaton
"""``codanna index`` runs without a path argument (issue #664).

``.codanna/settings.toml`` is tracked with a relative ``workspace_root`` and explicit
source directories, so one committed file serves every clone and worktree. A path
argument undoes that. Measured on codanna 0.18.0:

- ``codanna index .`` rewrites the file. ``workspace_root`` becomes absolute, the path
  is appended to ``indexed_paths``, and the comments and every other section are
  dropped.
- A ``"."`` root entry makes one physical file enter the index twice: once as
  ``src/...`` from ``codanna index`` and once as ``./src/...`` from the watch
  auto-index. Every symbol is then doubled.

The arms:

1. The instruction scan. No instruction an agent loads passes a path to ``codanna index``.
2. The settings guard. The tracked file is byte-identical after an index run.
3. The symbol guard. One physical file stays one index entry across the sequence that
   doubles it under a root entry.

Two control arms run the same instruments on the two known-bad shapes. Each control
must fail its guard's assertion, so a green guard is a measured zero.

This is the gateway's ``tests/contract/test_codanna_index_config.py`` in this
repository's flat test layout. The instruction surfaces are this repository's.

What this test does NOT catch:

- Arms 2 and 3 and their controls need the ``codanna`` CLI and skip when it is absent.
  This repository's CI has none, so those arms gate on a machine that has the CLI. The
  instruction scan and the shape pin run everywhere.
- The controls pin the behaviour of one tool on one version. A codanna release that
  stops rewriting the settings, or stops double-keying, reddens its control. That is the
  signal to measure again, not a defect in this repository.
- The guards prove the tracked file. A hook or a script that passes a path at runtime is
  outside this file.
- The scan reads one line at a time. A command split across lines is not seen.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / ".codanna" / "settings.toml"
IGNORE = ROOT / ".codannaignore"

# The surfaces an agent loads as instructions.
INSTRUCTION_FILES = [
    ROOT / "CLAUDE.md",
    ROOT / "AGENTS.md",
    *sorted((ROOT / ".claude" / "agents").glob("*.md")),
    *sorted((ROOT / ".claude" / "skills").rglob("*.md")),
]

_COMMAND = re.compile(r"\bcodanna\s+index\b")
_INDEXED_PATHS = re.compile(r"(indexed_paths = \[.*?)(\n\])", re.DOTALL)
# The options of `codanna index` that consume the next token.
_VALUE_OPTIONS = frozenset({"-c", "--config", "-t", "--threads", "--max-files"})
_QUOTES = ("`", "'", '"')

_SOURCE = """\
def alpha():
    return 1


def beta():
    return alpha()


class Gamma:
    def delta(self):
        return beta()
"""
_CLI_TIMEOUT_S = 120


# ---- arm 1: the instruction scan ---------------------------------------------------


def _path_arguments(line: str) -> list[str]:
    """The path arguments of every ``codanna index`` on ``line``.

    The argument list ends where the span that opened the command closes, or at the
    first token that opens prose. A fenced block carries the bare command to the end of
    the line. Options and the values they take are not paths. A ``<placeholder>`` is
    prose about a path. Every token after ``--`` is a path.
    """
    arguments: list[str] = []
    for command in _COMMAND.finditer(line):
        before = line[: command.start()].rstrip()
        rest = line[command.end() :]
        if before.endswith(_QUOTES):
            end = rest.find(before[-1])
            if end != -1:
                rest = rest[:end]
        paths_only = False
        takes_value = False
        for token in rest.split():
            if token[0] in _QUOTES:
                break
            if paths_only:
                arguments.append(token)
            elif token == "--":
                paths_only = True
            elif takes_value:
                takes_value = False
            elif token in _VALUE_OPTIONS:
                takes_value = True
            elif token[0] in "-<":
                continue
            else:
                arguments.append(token)
    return arguments


def test_no_instruction_passes_a_path_to_codanna_index() -> None:
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{number}: {argument!r}"
        for path in INSTRUCTION_FILES
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        for argument in _path_arguments(line)
    ]
    assert not offenders, (
        "an instruction passes a path to `codanna index`. A path argument rewrites the "
        "tracked .codanna/settings.toml and can double every symbol: run "
        "`codanna index` with no path: " + "; ".join(offenders)
    )


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("codanna index . --no-progress", ["."]),
        ("run `codanna index .` and retry.", ["."]),
        ("(`codanna index .` from the worktree root)", ["."]),
        ("codanna index src lib", ["src", "lib"]),
        ("codanna index -- src/probe.py", ["src/probe.py"]),
        ("codanna index", []),
        ("codanna index --no-progress", []),
        ("run `codanna index` in the current checkout and retry.", []),
        ("codanna index --config .codanna/other.toml", []),
        ("`codanna index <path>` rewrites the settings", []),
        ("no `codanna index`/`init`, no git writes.", []),
    ],
    ids=[
        "fenced-dot",
        "span-dot",
        "span-in-parentheses",
        "two-directories",
        "after-separator",
        "bare",
        "option-only",
        "span-closes-empty",
        "option-value",
        "placeholder",
        "span-then-prose",
    ],
)
def test_scan_sees_a_path_and_nothing_else(line: str, expected: list[str]) -> None:
    """The scanner's detection power: five shapes are a path, six are not."""
    assert _path_arguments(line) == expected


# ---- the tracked shape (runs everywhere) -------------------------------------------


def test_tracked_settings_stay_relative_with_no_root_entry() -> None:
    """The committed file is the shape a path argument destroys."""
    tracked = tomllib.loads(SETTINGS.read_text(encoding="utf-8"))
    assert tracked["workspace_root"] == "."
    offenders = [
        entry
        for entry in _indexed_paths(tracked)
        if entry == "." or entry.startswith("./") or Path(entry).is_absolute()
    ]
    assert not offenders, f"indexed_paths carries a root entry: {offenders}"


# ---- arms 2 and 3: the real CLI ----------------------------------------------------


def _codanna() -> str:
    path = shutil.which("codanna")
    if path is None:
        pytest.skip(
            "codanna is not on PATH. The settings and symbol guards build a real index "
            "and need the CLI (https://github.com/bartolli/codanna)."
        )
    return path


def _indexed_paths(settings: dict[str, Any]) -> list[str]:
    """``indexed_paths``, which the tracked file keeps inside its ``[indexing]`` table."""
    return list(settings["indexing"]["indexed_paths"])


def _scratch(tmp_path: Path, settings: str) -> Path:
    """A throwaway tree with every directory the settings indexes and one module."""
    _codanna()
    tree = tmp_path / "tree"
    (tree / ".codanna").mkdir(parents=True)
    (tree / ".codanna" / "settings.toml").write_text(settings, encoding="utf-8")
    for directory in _indexed_paths(tomllib.loads(settings)):
        (tree / directory).mkdir(parents=True, exist_ok=True)
    (tree / ".codannaignore").write_bytes(IGNORE.read_bytes())
    (tree / "src" / "probe.py").write_text(_SOURCE, encoding="utf-8")
    return tree


def _cli(tree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the CLI in the tree; an index run writes progress to stdout, so nothing is
    parsed here."""
    result = subprocess.run(
        [_codanna(), *args],
        cwd=tree,
        check=False,
        capture_output=True,
        text=True,
        timeout=_CLI_TIMEOUT_S,
    )
    assert result.returncode == 0, (
        f"codanna {' '.join(args)} exited {result.returncode}\n{result.stderr}"
    )
    return result


def _query(tree: Path, *args: str) -> dict[str, Any]:
    """Run one ``codanna mcp`` query and return its JSON envelope."""
    result = _cli(tree, *args, "--json")
    envelope: dict[str, Any] = json.loads(result.stdout)
    return envelope


def _settings_bytes(tree: Path) -> bytes:
    return (tree / ".codanna" / "settings.toml").read_bytes()


def _file_keys(tree: Path, name: str) -> list[str]:
    """The path each record of ``name`` is stored under."""
    result = _query(tree, "mcp", "find_symbol", name)
    return sorted(row["file_path"] for row in result["data"])


def _file_count(tree: Path) -> int:
    result = _query(tree, "mcp", "get_index_info")
    return int(result["data"]["file_count"])


def _index_watch_index(tree: Path) -> None:
    """The sequence that doubles a root entry: an index run, the watch auto-index, an
    index run."""
    _cli(tree, "index", "--no-progress")
    _cli(tree, "mcp", "get_index_info", "--watch", "--json")
    _cli(tree, "index", "--no-progress")


def _with_root_entry(settings: str) -> str:
    """The tracked settings with one ``"."`` root entry appended to ``indexed_paths``."""
    rewritten, count = _INDEXED_PATHS.subn(
        lambda match: f'{match.group(1)}\n    ".",{match.group(2)}', settings, count=1
    )
    assert count == 1, "no indexed_paths block in the tracked settings"
    return rewritten


def test_index_without_a_path_argument_leaves_the_tracked_settings_byte_identical(
    tmp_path: Path,
) -> None:
    """Arm 2: the guard. ``settings.toml`` is the same bytes after an index run."""
    tracked = SETTINGS.read_bytes()
    tree = _scratch(tmp_path, tracked.decode("utf-8"))
    _cli(tree, "index", "--no-progress")
    assert _settings_bytes(tree) == tracked


def test_control_a_path_argument_rewrites_the_tracked_settings(tmp_path: Path) -> None:
    """Arm 2's control: the same assertion fails on ``codanna index .``.

    This tree is the reason the instruction scan exists.
    """
    tracked = tomllib.loads(SETTINGS.read_text(encoding="utf-8"))
    tree = _scratch(tmp_path, SETTINGS.read_text(encoding="utf-8"))
    _cli(tree, "index", ".", "--no-progress")
    rewritten = _settings_bytes(tree)
    assert rewritten != SETTINGS.read_bytes(), "a path argument no longer rewrites the file"
    parsed = tomllib.loads(rewritten.decode("utf-8"))
    assert Path(parsed["workspace_root"]).is_absolute(), parsed["workspace_root"]
    added = [entry for entry in _indexed_paths(parsed) if entry not in _indexed_paths(tracked)]
    assert len(added) == 1 and Path(added[0]).is_absolute(), _indexed_paths(parsed)


def test_index_without_a_path_argument_keeps_one_entry_per_file(tmp_path: Path) -> None:
    """Arm 3: the guard. One module stays one file and one ``alpha`` across the sequence."""
    tree = _scratch(tmp_path, SETTINGS.read_text(encoding="utf-8"))
    _index_watch_index(tree)
    assert _file_keys(tree, "alpha") == ["src/probe.py"]
    assert _file_count(tree) == 1


def test_control_a_root_entry_doubles_every_symbol(tmp_path: Path) -> None:
    """Arm 3's control: the same assertions fail under a ``"."`` root entry.

    The one module is stored twice, as ``src/probe.py`` and as ``./src/probe.py``.
    """
    settings = _with_root_entry(SETTINGS.read_text(encoding="utf-8"))
    assert "." in _indexed_paths(tomllib.loads(settings)), "the root entry was not added"
    tree = _scratch(tmp_path, settings)
    _index_watch_index(tree)
    assert _file_keys(tree, "alpha") == ["./src/probe.py", "src/probe.py"]
    assert _file_count(tree) == 2
