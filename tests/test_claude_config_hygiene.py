# author: Stephen Eaton
"""The project's Claude Code configuration stays inside its own boundaries (#664, #669).

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
5. Every agent declares its ``tools:`` list (issue #669). An agent with no such list
   inherits every tool of the session. The issue found six agents with neither list. The
   arm also reads a ``tools:`` key with no tool in it, and a ``disallowedTools:`` list
   with no ``tools:`` list, as no list: three named refusals leave every other tool
   inherited.
6. Every agent outside ``_TOOLS_ONLY`` names the three memory writes in ``disallowedTools:``
   beside its list (issue #669). The list already holds the writes back; the refusal is
   the record, and it can be searched for.
7. A ``tools:`` list is one the agent's body can run and use (issue #669). The memory
   protocol's proposal route is a shell command, so an agent whose body carries it holds
   ``Bash``. And for every agent outside ``_TOOLS_ONLY``, each tool it declares is on
   record in ``_SENDS_TO`` with a line of its body that sends the agent to that tool, and
   each line on record has its tool declared.

Each arm has a tamper arm that feeds it the bad shape, so a green arm is a measured zero
and not a scanner that cannot see.

The gateway's ``tests/contract/test_claude_config_hygiene.py`` is the source of arms 1 to
5, in this repository's flat test layout. Arm 5 tightens its second arm from the presence
of the key to a tool in the list: a key with nothing in it is not read as a list.
Arms 6 and 7 were written here.

What this test does NOT catch:

- ``Bash(rg:*)`` stays on the allow list by decision (issue #664, finding 5). It is the
  exact-string tool the Codanna workflow instructs agents to use, and it can still print
  a whole file (``rg --passthru``). This file has no arm on it.
- ``codanna-explorer`` and ``code-reviewer`` name no refusal. Each holds a ``tools:`` list
  and no ``disallowedTools:``; the list holds the memory writes back, and arm 3 reads
  that. That neither names the writes, and that neither has a row in ``_SENDS_TO``, is
  the shape issue #669 left alone. A new agent is read by arms 6 and 7.
- Whether a line on record in ``_SENDS_TO`` truly needs the tool it is tied to. The table
  is a reading of each body, and it is checked against the body's text. A reader who
  disagrees with a row changes the row or the list.
- An instruction in prose that only a tool can carry out, beyond the proposal route. An
  agent told to read memory is read through ``_SENDS_TO``, not by a rule.
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


# ---- arm 5: every agent declares its tools (issue #669) ------------------------------

# The agents that held a ``tools:`` list and no ``disallowedTools:`` before issue #669, which
# left them alone. Arms 6 and 7 skip them by name. A new agent is not in the tuple, so both
# arms read it.
_TOOLS_ONLY = ("codanna-explorer.md", "code-reviewer.md")


def _declares_tools(fields: dict[str, str]) -> bool:
    """Whether a frontmatter's ``tools:`` list names a tool. An absent key and an empty
    list both read as false: neither names a tool the agent may hold."""
    return bool(_names(fields.get("tools", "")))


def test_every_agent_declares_its_tools() -> None:
    undeclared = [
        path.name
        for path in _agent_files()
        if not _declares_tools(_frontmatter(path.read_text(encoding="utf-8")))
    ]
    assert not undeclared, (
        "agent definition(s) with no tool in a tools: list; an agent with no tools: list "
        f"inherits every tool of the session, MCP servers included (issue #669): {undeclared}"
    )


def test_tamper_an_agent_that_inherits_the_session_is_seen() -> None:
    """Arm 5's detection power. An absent list, an empty one, and a refusal with no list
    behind it all read as no list. One tool in ``tools:`` reads as declared, in either
    list shape the agents use."""
    inherited = (
        "---\nname: a\n---\nbody\n",
        "---\nname: a\ntools:\n---\nbody\n",
        "---\nname: a\ntools: []\n---\nbody\n",
        "---\nname: a\ndisallowedTools: Read\n---\nbody\n",
    )
    declared = (
        "---\nname: a\ntools: Read\n---\nbody\n",
        '---\nname: a\ntools: ["Read", "Grep"]\n---\nbody\n',
    )
    assert not any(_declares_tools(_frontmatter(text)) for text in inherited)
    assert all(_declares_tools(_frontmatter(text)) for text in declared)


# ---- arm 6: the refusal is on record beside the list (issue #669) --------------------


def _unnamed_writes(fields: dict[str, str]) -> list[str]:
    """The three memory writes, in the order they are named, that a frontmatter's
    ``disallowedTools:`` list does not refuse, whatever the memory server is called."""
    disallowed = _names(fields.get("disallowedTools", ""))
    refused = {name.rsplit("__", 1)[-1] for name in _refused_writes(disallowed)}
    return [name for name in _MEMORY_WRITE_REFUSALS if name not in refused]


def test_every_agent_refuses_the_memory_writes_by_name() -> None:
    """Every agent outside ``_TOOLS_ONLY``. The list already holds the writes back; naming
    them is what makes the refusal readable without knowing how a list resolves."""
    stale = [name for name in _TOOLS_ONLY if not (AGENTS_DIR / name).is_file()]
    assert not stale, f"_TOOLS_ONLY names a file that is not under {AGENTS_DIR}: {stale}"
    offenders = []
    for path in _agent_files():
        if path.name in _TOOLS_ONLY:
            continue
        fields = _frontmatter(path.read_text(encoding="utf-8"))
        if unnamed := _unnamed_writes(fields):
            offenders.append(f"{path.name}: {unnamed}")
    assert not offenders, (
        "an agent does not name the memory write tools in disallowedTools:; the refusal is "
        f"what a reader and a search can see (issue #669): {offenders}"
    )


def test_tamper_a_refusal_that_is_absent_or_partial_is_seen() -> None:
    """Arm 6's detection power. No ``disallowedTools:`` list and an empty one refuse
    nothing; one write missing is the one named; the three through another server name
    are the same refusal."""
    one = "mcp__muninndb-benchweave__muninn_remember"
    three = f"{one}, {one}_batch, {one}_tree"
    frontmatter = "---\nname: a\ntools: Read\ndisallowedTools: {}\n---\n"
    everything = list(_MEMORY_WRITE_REFUSALS)
    assert _unnamed_writes(_frontmatter(frontmatter.format(""))) == everything
    assert _unnamed_writes(_frontmatter(frontmatter.format("[]"))) == everything
    assert _unnamed_writes(_frontmatter(frontmatter.format(f"{one}, {one}_batch"))) == [
        "muninn_remember_tree"
    ]
    assert _unnamed_writes(_frontmatter(frontmatter.format(three))) == []
    other_server = three.replace("-benchweave", "")
    assert _unnamed_writes(_frontmatter(frontmatter.format(other_server))) == []


# ---- arm 7: a declared list is one the agent's body can run and use (issue #669) ------

# The memory protocol's route for a finding worth keeping: a script, run from the shell,
# that appends a proposal to a ledger a hook drains later. It is the sanctioned way to write
# to memory, so an agent whose body carries it holds ``Bash``.
_PROPOSAL_SCRIPT = "memory-propose.mjs"

# ``codanna-implementer`` names its own list in its body, so one line sends it to all six.
_IMPLEMENTER_LIST = (
    "Your tools are the six named in the frontmatter: Read, Grep, Glob, Bash, Write, Edit"
)

# What sends each agent to each tool it declares: a fragment of its own body, quoted
# verbatim. Read the body first, then the list: the shell is for commands, and the native
# tools are for what the body has the agent read, search, create or change. The table is
# the reading behind each list, and the arm holds the list and the body to it.
_SENDS_TO: dict[str, dict[str, str]] = {
    IMPLEMENTER: {
        tool: _IMPLEMENTER_LIST for tool in ("Read", "Grep", "Glob", "Bash", "Write", "Edit")
    },
    "adversary.md": {
        "Read": "**Read `CLAUDE.md`, `docs/internal/invariants.md`",
        "Grep": "Enumerate every path in the class",
        "Glob": "what does the wheel contain that the repo doesn't",
        "Bash": "`sync-standards --check`",
        "Write": "an unrecorded file in the vendored tree",
        "Edit": "a byte changed against the lock",
    },
    "bench-measurer.md": {
        "Read": "reads paths from configuration",
        "Grep": "a sync history with no refusals",
        "Glob": "Copy the projects, trees or histories into your scratch directory",
        "Bash": "`node .claude/hooks/memory-propose.mjs`",
        "Write": "If a harness must land in-tree, it uses synthetic fixtures",
    },
    "document-writer.md": {
        "Read": "read its SKILL.md and `references/rules.md`",
        "Grep": "banned words, term consistency",
        "Glob": "Match the repo's existing doc structure and frontmatter conventions",
        "Write": "Deliver: the written document at the given path",
        "Edit": "sentence splits, voice fixes, word substitutions",
    },
    "increment-builder.md": {
        "Read": "Read the design document you were pointed at",
        "Grep": "Grep your diff for real content",
        "Glob": "Name the module that carries your test",
        "Bash": "uv run ruff check .",
        "Write": "Write the test first.",
        "Edit": "Neutralize the mechanism",
        "mcp__muninndb-benchweave__muninn_recall": "recall the memory vault with the symptom",
    },
    "increment-designer.md": {
        "Read": "Read before you theorize",
        "Grep": "the tests that pin them",
        "Glob": "The vendored standards themselves",
        "Bash": "`node .claude/hooks/memory-propose.mjs`",
        "Write": "Save the design to",
    },
    "mechanism-critic.md": {
        "Read": "Read `CLAUDE.md`, `docs/internal/invariants.md` and the vendored standards",
        "Grep": "Grep for every refusal path",
        "Glob": "Enumerate, don't sample",
        "Bash": "You have `Bash`. Use it.",
    },
}


def _body(text: str) -> str:
    """The agent's instructions: the text after the frontmatter block. Text that does not
    open with a closed block is all body."""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                return "\n".join(lines[index + 1 :])
    return text


def _one_line(text: str) -> str:
    """The text with every run of whitespace as one space. A line break is how a quote is
    wrapped, not part of it."""
    return " ".join(text.split())


def _unrunnable_faults(fields: dict[str, str], body: str) -> list[str]:
    """The instruction a ``tools:`` list cannot run. One is read: the proposal route."""
    if _PROPOSAL_SCRIPT in body and "Bash" not in _names(fields.get("tools", "")):
        return [
            f"its body sends findings through {_PROPOSAL_SCRIPT}, a shell command, and "
            "tools: does not declare Bash"
        ]
    return []


def test_the_proposal_route_stays_runnable() -> None:
    """The fix takes the memory write tools away, not the shell: every agent whose body
    carries the proposal route holds ``Bash``."""
    offenders = []
    for path in _agent_files():
        text = path.read_text(encoding="utf-8")
        if faults := _unrunnable_faults(_frontmatter(text), _body(text)):
            offenders.append(f"{path.name}: {faults}")
    assert not offenders, (
        "an agent is told to propose findings through the memory protocol's script and its "
        "tools: list does not declare Bash, so the route rests on what the agent inherits "
        f"or is cut (issue #669): {offenders}"
    )


def _record_faults(text: str, sends_to: dict[str, str]) -> list[str]:
    """Where an agent's ``tools:`` list and the lines on record for it disagree."""
    declared = _names(_frontmatter(text).get("tools", ""))
    body = _one_line(_body(text))
    sent_to: list[str] = []
    gone: list[str] = []
    for tool, quote in sends_to.items():
        if _one_line(quote) not in body:
            gone.append(f"{quote!r} for {tool}")
        elif tool not in declared:
            sent_to.append(tool)
    faults = []
    if sent_to:
        faults.append(f"the body sends the agent to {sent_to}, and tools: does not declare them")
    if gone:
        faults.append(f"the body no longer carries the lines on record: [{', '.join(gone)}]")
    unrecorded = [tool for tool in declared if tool not in sends_to]
    if unrecorded:
        faults.append(f"tools: declares {unrecorded}, and no line of the body is on record")
    return faults


def test_a_declared_tool_is_one_the_body_sends_the_agent_to() -> None:
    """Every agent outside ``_TOOLS_ONLY``, and any agent that has a row. Both directions:
    a tool the body sends the agent to is declared, and a declared tool has a line of the
    body behind it."""
    read = {path.name: path.read_text(encoding="utf-8") for path in _agent_files()}
    scope = (read.keys() - set(_TOOLS_ONLY)) | _SENDS_TO.keys()
    offenders = []
    for name in sorted(scope):
        if name not in read:
            offenders.append(f"{name}: _SENDS_TO holds an agent that is not there to read")
        elif name not in _SENDS_TO:
            offenders.append(f"{name}: no line of its body is on record for the tools it names")
        elif faults := _record_faults(read[name], _SENDS_TO[name]):
            offenders.append(f"{name}: {faults}")
    assert not offenders, (
        "an agent's tools: list and the lines of its body that send it to those tools "
        f"disagree (issue #669): {offenders}"
    )


def test_tamper_a_proposal_route_the_list_cannot_run_is_seen() -> None:
    """Arm 7's detection power on the route. A body that carries it with no ``Bash`` on the
    list is a fault, with no list at all and with a list. ``Bash`` on the list, or a body
    that does not carry the route, is not."""
    route = f"Findings go through `node .claude/hooks/{_PROPOSAL_SCRIPT}`."
    frontmatter = "---\nname: a\ntools: {}\n---\n{}\n"
    for tools in ("", "Read, Grep"):
        text = frontmatter.format(tools, route)
        assert _unrunnable_faults(_frontmatter(text), _body(text)), tools
    for tools, body in (("Read, Bash", route), ("Read, Grep", "No memory instruction here.")):
        text = frontmatter.format(tools, body)
        assert _unrunnable_faults(_frontmatter(text), _body(text)) == [], tools


def test_tamper_a_list_that_drifts_from_the_body_is_seen() -> None:
    """Arm 7's detection power on the table. A tool the lines send the agent to and the
    list does not declare, a tool the list declares with no line on record, and a line on
    record that the body no longer carries are each a fault. A quote wrapped over two
    lines is still in the body."""
    body = "Read `CLAUDE.md`.\nRun `uv run pytest -q`, then save the design\ninto the record.\n"
    record = {
        "Read": "Read `CLAUDE.md`",
        "Bash": "Run `uv run pytest -q`",
        "Write": "save the design into the record",
    }
    agrees = "---\nname: a\ntools: Read, Bash, Write\n---\n" + body
    assert _record_faults(agrees, record) == []
    assert _record_faults(agrees.replace("Read, Bash, Write", "Read, Write"), record) == [
        "the body sends the agent to ['Bash'], and tools: does not declare them"
    ]
    assert _record_faults(agrees.replace("Bash, Write", "Bash, Write, WebFetch"), record) == [
        "tools: declares ['WebFetch'], and no line of the body is on record"
    ]
    not_carried = {**record, "Edit": "change a byte against the lock"}
    assert _record_faults(agrees, not_carried) == [
        "the body no longer carries the lines on record: "
        "['change a byte against the lock' for Edit]"
    ]
