# author: Stephen Eaton
"""The project's Claude Code configuration stays inside its own boundaries (issue #664).

Arms over ``.claude/settings.json`` and ``.claude/agents/*.md``:

1. The allow list does not pre-approve ``sed``. ``sed -n 'A,Bp' <path>`` prints any file
   the user can read, with no prompt and no path for the harness to show. Read with
   offset and limit is the path-visible way to read a range.
2. The implementer declares its ``tools:`` and refuses the memory writes. An agent without
   the key inherits every tool of the session, MCP servers included.
3. No agent's declared ``tools:`` list reaches a memory write.
4. The ``codanna`` marketplace is pinned to one reviewed commit. A marketplace entry with
   no ``ref`` follows the upstream default branch, so a clone takes whatever that branch
   holds on the day. The pin is a full lowercase commit SHA in ``ref``, which is the only
   field of a marketplace source that holds one, with ``autoUpdate`` false.

Each arm has a tamper arm that feeds it the bad shape, so a green arm is a measured zero
and not a scanner that cannot see.

This is the gateway's ``tests/contract/test_claude_config_hygiene.py`` reduced to the arms
that hold in this repository, in this repository's flat test layout.

What this test does NOT catch:

- ``Bash(rg:*)`` stays on the allow list by decision (issue #664, finding 5). It is the
  exact-string tool the Codanna workflow instructs agents to use, and it can still print
  a whole file (``rg --passthru``). This file has no arm on it.
- Six agent definitions declare no ``tools:`` list and inherit every tool of the session,
  memory writes included, and ``.mcp.json`` defines the memory server: adversary,
  bench-measurer, document-writer, increment-builder, increment-designer and
  mechanism-critic. That gap is outside the findings of issue #664. The memory arm reads
  a declared list wherever there is one and requires none.
- A read reached through an allowed command: ``Bash(codanna:*)`` and ``Bash(git:*)`` run
  programs, and what those programs read is outside an allow-list scan.
- Tools reached from Bash (a script, ``curl``). The arms read declarations, not a session.
- That a declared ``tools:`` list is the list a running session resolved. The frontmatter
  is the only evidence here.
- The main session's own allow entries. The memory arms cover ``.claude/agents/*.md``.
- Which commit arm 4's ``ref`` names. The arm reads the SHA's shape, so a reviewed bump
  touches the settings file alone. That the commit still exists upstream, and that a
  given Claude Code build loads the entry, needs the network or a session; neither is
  read here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_DIR = ROOT / ".claude"
AGENTS_DIR = CLAUDE_DIR / "agents"
IMPLEMENTER = "codanna-implementer.md"

# The per-user file is gitignored and carries one person's own rules, not the project's.
_UNSCOPED = "settings.local.json"

_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(.*)$")
_TOOL_RULE = re.compile(r"^[A-Za-z]+\((?P<command>.*)\)$")
# ``mcp__<server>__muninn_<verb>``, whatever the server is named.
_MEMORY_TOOL = re.compile(
    r"^mcp__(?P<server>[a-z0-9_-]*muninn[a-z0-9_-]*)__muninn_(?P<verb>[a-z_]+)$"
)
# The memory tools an agent may hold: reads and navigation only. Every other memory verb
# counts as a write, so a new verb is refused until it is read and listed here.
_MEMORY_READ_VERBS = frozenset(
    {
        "recall",
        "read",
        "find_by_entity",
        "entity",
        "entities",
        "entity_timeline",
        "traverse",
        "contradictions",
        "where_left_off",
        "status",
        "guide",
    }
)
# The three write tools the gateway's agents name when they refuse the writes.
_MEMORY_WRITE_REFUSALS = ("muninn_remember", "muninn_remember_batch", "muninn_remember_tree")
_WILDCARD_SUFFIX = ":*"

# The one marketplace the project settings declare, and the repository it is cloned from.
_PINNED_MARKETPLACE = "codanna"
_MARKETPLACE_SOURCE = {"source": "github", "repo": "bartolli/codanna"}
# A full lowercase commit SHA: 40 hex digits and nothing else. Not a branch, not a tag,
# not a short SHA.
_COMMIT_SHA = re.compile(r"[0-9a-f]{40}")


# ---- readers -----------------------------------------------------------------------


def _frontmatter(text: str) -> dict[str, str]:
    """The keys of the leading ``---`` block, each with its raw one-line value.

    Only a key's own line is read. The indented lines of a block scalar or a block
    list are not keys. An absent block reads as an empty mapping.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        match = _KEY.match(line)
        if match is not None:
            fields[match[1]] = match[2].strip()
    return fields


def _names(raw: str) -> list[str]:
    """The names in a one-line list: ``a, b`` or ``["a", "b"]``. An empty value is ``[]``."""
    value = raw.strip()
    if value.startswith("["):
        value = value[1:]
        if value.endswith("]"):
            value = value[:-1]
    return [name.strip().strip("\"'") for name in value.split(",") if name.strip()]


def _agent_files() -> list[Path]:
    agent_files = sorted(AGENTS_DIR.glob("*.md"))
    # The glob, not a hand-list: a new agent joins the memory arms by existing.
    assert agent_files, f"no agent definitions under {AGENTS_DIR} — path moved?"
    return agent_files


def _memory_writes(names: list[str]) -> list[str]:
    """The names that reach a memory write: a memory tool whose verb is not a read."""
    flagged = []
    for name in names:
        match = _MEMORY_TOOL.match(name)
        if match is not None and match["verb"] not in _MEMORY_READ_VERBS:
            flagged.append(name)
    return flagged


def _memory_reads(names: list[str]) -> list[str]:
    """The names that are a memory read tool."""
    matched = []
    for name in names:
        match = _MEMORY_TOOL.match(name)
        if match is not None and match["verb"] in _MEMORY_READ_VERBS:
            matched.append(name)
    return matched


def _refused_writes(disallowed: list[str]) -> list[str]:
    """The names in ``disallowed`` that refuse a memory write, whatever the server is."""
    return [name for name in disallowed if _memory_writes([name]) == [name]]


def _settings_files() -> list[Path]:
    """Every project settings file: ``settings*.json`` under ``.claude/``, the per-user
    file excepted."""
    files = [path for path in sorted(CLAUDE_DIR.glob("settings*.json")) if path.name != _UNSCOPED]
    assert files, f"no project settings file under {CLAUDE_DIR} — path moved?"
    return files


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name} is not a JSON object"
    return data


def _command_words(rule: str) -> list[str]:
    """The words of the command a ``Bash(...)`` rule allows. Any other rule is ``[]``."""
    match = _TOOL_RULE.match(rule)
    if match is None:
        return []
    command = match["command"]
    if command.endswith(_WILDCARD_SUFFIX):
        command = command[: -len(_WILDCARD_SUFFIX)]
    return command.split()


def _sed_rules(rules: list[str]) -> list[str]:
    """The rules that pre-approve a ``sed`` command."""
    return [rule for rule in rules if _command_words(rule)[:1] == ["sed"]]


def _allow_rules() -> list[tuple[str, str]]:
    """``permissions.allow`` of every project settings file, as ``(path.name, rule)``.

    The file name travels beside the rule and never inside it: a rule is matched as it
    is written, and the name is for the message.
    """
    rules: list[tuple[str, str]] = []
    for path in _settings_files():
        allow = _load(path).get("permissions", {}).get("allow", [])
        assert isinstance(allow, list), f"{path.name}: permissions.allow is not a list"
        rules += [(path.name, rule) for rule in allow]
    return rules


def _implementer() -> dict[str, str]:
    return _frontmatter((AGENTS_DIR / IMPLEMENTER).read_text(encoding="utf-8"))


# ---- arm 1: the allow list and sed --------------------------------------------------


def test_allow_list_does_not_pre_approve_sed() -> None:
    offenders = [f"{name}: {rule}" for name, rule in _allow_rules() if rule in _sed_rules([rule])]
    assert not offenders, (
        "the allow list pre-approves sed, which prints any file range with no prompt and "
        "no path for the harness to show; Read with offset and limit is the path-visible "
        f"way to read a range (issue #664, finding 5): {offenders}"
    )


def test_tamper_a_sed_rule_is_flagged() -> None:
    """Arm 1's detection power: the rule the finding named is flagged, its neighbours not."""
    rules = ["Bash(codanna mcp:*)", "Bash(sed -n:*)"]
    assert _sed_rules(rules) == ["Bash(sed -n:*)"]
    assert _sed_rules(["Bash(rg:*)", "mcp__codanna__find_symbol", "Bash(awk -f x:*)"]) == []


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ("Bash(sed -n:*)", ["sed", "-n"]),
        ("Bash(sed:*)", ["sed"]),
        ("Bash(rg:*)", ["rg"]),
        ("Bash(codanna mcp:*)", ["codanna", "mcp"]),
        ("mcp__codanna__find_symbol", []),
    ],
    ids=["sed-with-flag", "sed-bare", "rg", "two-words", "not-a-bash-rule"],
)
def test_command_words_read_a_bash_rule_and_nothing_else(rule: str, expected: list[str]) -> None:
    assert _command_words(rule) == expected


# ---- arm 2: the implementer declares its tools and refuses the memory writes --------


def test_implementer_declares_its_tools() -> None:
    declared = _names(_implementer().get("tools", ""))
    assert declared, (
        "codanna-implementer.md declares no tools: list, so it inherits every tool of the "
        "session, MCP servers included (issue #664, finding 6)"
    )


def test_implementer_refuses_the_memory_writes_by_name() -> None:
    """The finding's own ask: the implementer names the writes it refuses, in the shape
    the gateway's agents use, beside its explicit ``tools:`` list."""
    refused = {
        name.rsplit("__", 1)[-1]
        for name in _refused_writes(_names(_implementer().get("disallowedTools", "")))
    }
    assert set(_MEMORY_WRITE_REFUSALS) <= refused, (
        "codanna-implementer.md does not refuse the memory write tools "
        f"(issue #664, finding 6): names {sorted(refused)}"
    )


# ---- arm 3: no agent reaches a memory write -----------------------------------------


def test_no_agent_tool_list_reaches_a_memory_write() -> None:
    offenders = []
    for path in _agent_files():
        fields = _frontmatter(path.read_text(encoding="utf-8"))
        writes = _memory_writes(_names(fields.get("tools", "")))
        if writes:
            offenders.append(f"{path.name}: {writes}")
    assert not offenders, (
        "an agent's tools: list reaches a memory write; memory is read through the read "
        f"tools and written through the proposal ledger (issue #664, finding 6): {offenders}"
    )


def test_an_agent_that_reads_memory_also_refuses_the_writes() -> None:
    """The convention the gateway holds: reads in ``tools:``, the three write tools named
    in ``disallowedTools:``."""
    offenders = []
    for path in _agent_files():
        fields = _frontmatter(path.read_text(encoding="utf-8"))
        if not _memory_reads(_names(fields.get("tools", ""))):
            continue
        refused = {
            name.rsplit("__", 1)[-1]
            for name in _refused_writes(_names(fields.get("disallowedTools", "")))
        }
        if not set(_MEMORY_WRITE_REFUSALS) <= refused:
            offenders.append(f"{path.name}: refuses {sorted(refused)}")
    assert not offenders, (
        "an agent that reads memory does not name the memory writes it refuses "
        f"(issue #664, finding 6): {offenders}"
    )


@pytest.mark.parametrize(
    ("name", "is_write"),
    [
        ("mcp__muninndb-benchweave__muninn_remember", True),
        ("mcp__muninndb-benchweave__muninn_remember_tree", True),
        ("mcp__muninndb-benchweave__muninn_evolve", True),
        ("mcp__muninndb__muninn_forget", True),
        ("mcp__muninndb-benchweave__muninn_new_verb", True),
        ("mcp__muninndb-benchweave__muninn_recall", False),
        ("mcp__muninndb-benchweave__muninn_where_left_off", False),
        ("mcp__codanna__find_symbol", False),
        ("Read", False),
    ],
    ids=[
        "remember",
        "remember-tree",
        "evolve",
        "other-server-forget",
        "unknown-verb",
        "recall",
        "where-left-off",
        "other-server",
        "builtin",
    ],
)
def test_memory_write_names_are_read_by_verb(name: str, is_write: bool) -> None:
    """Arm 3's detection power: an unknown memory verb counts as a write."""
    assert bool(_memory_writes([name])) is is_write


def test_tamper_a_memory_write_in_a_tool_list_is_seen() -> None:
    """Arm 3's detection power on a frontmatter shape: the write is found in ``tools:``
    and absent when the list carries a read only."""
    tainted = "---\nname: a\ntools: Read, mcp__muninndb-benchweave__muninn_remember\n---\n"
    clean = "---\nname: a\ntools: Read, mcp__muninndb-benchweave__muninn_recall\n---\n"
    assert _memory_writes(_names(_frontmatter(tainted)["tools"])) == [
        "mcp__muninndb-benchweave__muninn_remember"
    ]
    assert _memory_writes(_names(_frontmatter(clean)["tools"])) == []


def test_frontmatter_lists_read_every_shape_the_agents_use() -> None:
    """The readers behind arms 2 and 3, on the list shapes in ``.claude/agents/``."""
    text = (
        "---\n"
        "name: a\n"
        "description: >-\n"
        "  tools: not a key, a scalar line\n"
        'tools: ["Read", "Grep"]\n'
        "skills:\n"
        "  - x-ray\n"
        "  - 'graph'\n"
        "---\n"
        "tools: body text\n"
    )
    fields = _frontmatter(text)
    assert fields["name"] == "a"
    assert "not a key, a scalar line" not in fields.values()
    assert _names(fields["tools"]) == ["Read", "Grep"]
    assert _names(_frontmatter("---\nname: a\n---\n").get("tools", "")) == []
    assert _names("Read, Grep, Glob, Bash") == ["Read", "Grep", "Glob", "Bash"]


# ---- arm 4: the codanna marketplace is pinned to one reviewed commit -----------------

# Any full lowercase SHA, for the shapes below. The committed value is not read here.
_ANY_SHA = "0123456789abcdef0123456789abcdef01234567"
_NO_REF = "no ref: the marketplace follows the upstream default branch"
_SHA_KEY = "a sha key, which is not a field of a marketplace source and pins nothing"


def _marketplace_entry(path: Path) -> dict[str, Any] | None:
    """The ``codanna`` entry of one settings file's ``extraKnownMarketplaces``, or ``None``
    when the file does not declare it."""
    marketplaces = _load(path).get("extraKnownMarketplaces", {})
    assert isinstance(marketplaces, dict), f"{path.name}: extraKnownMarketplaces is not an object"
    entry = marketplaces.get(_PINNED_MARKETPLACE)
    if entry is None:
        return None
    assert isinstance(entry, dict), f"{path.name}: the {_PINNED_MARKETPLACE} entry is not an object"
    return entry


def _pin_faults(entry: dict[str, Any] | None) -> list[str]:
    """What keeps a marketplace entry from being a pin on one reviewed commit. An entry
    that is a pin reads as an empty list."""
    if entry is None:
        return [f"no {_PINNED_MARKETPLACE} marketplace entry"]
    faults: list[str] = []
    source = entry.get("source")
    if not isinstance(source, dict):
        return [f"source is {source!r}, not an object"]
    declared = {key: source.get(key) for key in _MARKETPLACE_SOURCE}
    if declared != _MARKETPLACE_SOURCE:
        faults.append(f"source is {declared!r}")
    ref = source.get("ref")
    if ref is None:
        faults.append(_NO_REF)
    elif not isinstance(ref, str) or _COMMIT_SHA.fullmatch(ref) is None:
        faults.append(f"ref is {ref!r}, not a full lowercase commit SHA")
    if "sha" in source:
        faults.append(_SHA_KEY)
    if entry.get("autoUpdate") is not False:
        faults.append(f"autoUpdate is {entry.get('autoUpdate')!r}, not false")
    return faults


def test_codanna_marketplace_is_pinned_to_one_reviewed_commit() -> None:
    unpinned = {
        path.name: faults
        for path in _settings_files()
        if (faults := _pin_faults(_marketplace_entry(path)))
    }
    assert not unpinned, (
        "the codanna marketplace entry is not a pin on one reviewed commit (issue #664, "
        f"HIGH-1): {unpinned}"
    )


def test_tamper_every_shape_that_is_not_a_pin_names_what_is_wrong() -> None:
    """Arm 4's detection power. A pin reads as no fault. Each other shape names its fault:
    the entry as it was before the pin, a ref that is a branch, a tag, a short SHA, an
    uppercase SHA, a number or empty, a `sha` key, an autoUpdate that is not the Boolean
    false, a missing entry, and an entry for another repository."""
    pinned = {"source": {**_MARKETPLACE_SOURCE, "ref": _ANY_SHA}, "autoUpdate": False}
    assert _pin_faults(pinned) == []

    before_the_pin = {"source": dict(_MARKETPLACE_SOURCE)}
    assert _pin_faults(before_the_pin) == [_NO_REF, "autoUpdate is None, not false"]

    for ref in ("main", "v0.18.0", _ANY_SHA[:12], _ANY_SHA.upper(), 1234, ""):
        entry = {"source": {**_MARKETPLACE_SOURCE, "ref": ref}, "autoUpdate": False}
        assert _pin_faults(entry) == [f"ref is {ref!r}, not a full lowercase commit SHA"], ref

    sha_key = {"source": {**_MARKETPLACE_SOURCE, "sha": _ANY_SHA}, "autoUpdate": False}
    assert _pin_faults(sha_key) == [_NO_REF, _SHA_KEY]

    for auto_update in (True, None, "false", 0):
        entry = {"source": {**_MARKETPLACE_SOURCE, "ref": _ANY_SHA}, "autoUpdate": auto_update}
        assert _pin_faults(entry) == [f"autoUpdate is {auto_update!r}, not false"], auto_update

    assert _pin_faults(None) == [f"no {_PINNED_MARKETPLACE} marketplace entry"]
    other_repository = {
        "source": {"source": "github", "repo": "someone/else", "ref": _ANY_SHA},
        "autoUpdate": False,
    }
    assert _pin_faults(other_repository) == [
        "source is {'source': 'github', 'repo': 'someone/else'}"
    ]


@pytest.mark.parametrize(
    ("ref", "is_a_sha"),
    [
        (_ANY_SHA, True),
        ("0000000000000000000000000000000000000000", True),
        ("f" * 40, True),
        (_ANY_SHA[:39], False),
        (_ANY_SHA + "0", False),
        (_ANY_SHA.upper(), False),
        ("g" * 40, False),
        (f" {_ANY_SHA}", False),
        (f"{_ANY_SHA}\n", False),
        ("", False),
    ],
    ids=[
        "sha",
        "all-zero",
        "all-f",
        "39-hex",
        "41-hex",
        "uppercase",
        "not-hex",
        "leading-space",
        "trailing-newline",
        "empty",
    ],
)
def test_the_commit_sha_shape_is_exact(ref: str, is_a_sha: bool) -> None:
    """Forty lowercase hex digits and nothing else."""
    assert (_COMMIT_SHA.fullmatch(ref) is not None) is is_a_sha
