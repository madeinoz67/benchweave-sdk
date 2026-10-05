"""R-5b/R-5c — agent-asset drift triangulation (issue #347 WS3, design §3-§4).

The six managed agent assets (``template/AGENTS.md`` and the five
``.claude/skills/benchweave-*/SKILL.md`` members) are AUTHORED agent sources;
the user guide stays the authored human source. Facts unavoidably appear in
both, so this module makes the dual-carriage checkable instead of pretending
single-carriage: every citation in an asset must triangulate against machine
sources, read at test time — never a committed list that can go stale.

The citation conventions the checker parses (design §2.3 — authoring rules
that make the check honest):

- **codes**: a backticked snake_case identifier with a trailing colon —
  `` `version_not_served:` ``. Citable only where BOTH the SDK source and the
  user guide carry it. Prose-refusal surfaces (capture; the plugin-ui lane's
  schema-shaped refusals) cite none — see ``CODE_FREE_SKILLS``.
- **commands**: a code span beginning with the binary name —
  `` `benchweave-sdk check ...` ``. The first word after the binary must be a
  subcommand the click group registers at test time; a ``registry`` first word
  additionally has its second word checked against the registry group.
- **headings**: double-quoted text after the word ``section`` —
  ``section "3. Run the checks"``. Must exist verbatim as a qmd heading
  (Pandoc anchor suffixes tolerated; whitespace normalised across line wraps).

R-5c's three planted-violation arms are PERMANENT: they feed the checker
deliberately-broken asset copies on every push. A checker revision that
passes a planted violation is itself broken.

What the checker does NOT catch (design §3, disclosed residual): it proves a
cited code exists in source and guide, not that a skill's one-line gloss
matches the guide's definition — prose paraphrase drift stays review's job.
Nor does it verify the STE100 register (design §8 risk 4).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from benchweave_sdk.cli import cli

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "template"
GUIDE = REPO / "user_guide" / "plugin-sdk.qmd"
FIXTURES = REPO / "tests" / "fixtures" / "scaffold_expected"

# Project-relative asset path -> template member (unrendered; tokens are inert
# to every check below — `{{ package_name }}` never appears in subcommand
# position and `{{ sdk_version }}` is the only version carrier, asserted).
ASSET_MEMBERS: dict[str, str] = {
    "AGENTS.md": "AGENTS.md.jinja",
    ".claude/skills/benchweave-plugin-workflow/SKILL.md": (
        ".claude/skills/benchweave-plugin-workflow/SKILL.md.jinja"
    ),
    ".claude/skills/benchweave-descriptor/SKILL.md": (
        ".claude/skills/benchweave-descriptor/SKILL.md.jinja"
    ),
    ".claude/skills/benchweave-plugin-ui/SKILL.md": (
        ".claude/skills/benchweave-plugin-ui/SKILL.md.jinja"
    ),
    ".claude/skills/benchweave-adapter-testing/SKILL.md": (
        ".claude/skills/benchweave-adapter-testing/SKILL.md.jinja"
    ),
    ".claude/skills/benchweave-capture/SKILL.md": (
        ".claude/skills/benchweave-capture/SKILL.md.jinja"
    ),
}

# Design §2.2 rows: these surfaces refuse in prose or through module APIs, not
# named prefixes — the skills describe behavior and cite no codes. The zero
# assertion pins the design rule; adding a code citation to one of these
# skills is a deliberate design change that updates this set consciously.
CODE_FREE_SKILLS = (
    ".claude/skills/benchweave-plugin-ui/SKILL.md",
    ".claude/skills/benchweave-adapter-testing/SKILL.md",
    ".claude/skills/benchweave-capture/SKILL.md",
)

CODE_CITATION = re.compile(r"`([a-z][a-z0-9_]+):`")
COMMAND_CITATION = re.compile(r"`benchweave-sdk\s+([a-z][a-z0-9-]*)")
REGISTRY_SUBCOMMAND = re.compile(r"`benchweave-sdk\s+registry\s+([a-z][a-z0-9-]*)")
HEADING_CITATION = re.compile(r'section\s+"([^"]+)"')
HEADING_LINE = re.compile(r"^#{1,6}\s+(.+?)\s*(?:\{#[^}]*\})?\s*$")
VERSION_LITERAL = re.compile(r"\d+\.\d+\.\d+")


def load_assets() -> dict[str, str]:
    """The six unrendered asset files from the template tree."""
    return {
        relative: (TEMPLATE / member).read_text(encoding="utf-8")
        for relative, member in ASSET_MEMBERS.items()
    }


def sdk_source_text() -> str:
    """The concatenated SDK source the code citations must occur in."""
    parts: list[str] = []
    for package in ("benchweave_sdk", "benchweave_sdk_server"):
        for path in sorted((REPO / "src" / package).rglob("*.py")):
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def registered_commands() -> set[str]:
    """The click group's commands, read at test time (no committed list)."""
    return set(cli.commands)


def registry_subcommands() -> set[str]:
    group = cli.commands.get("registry")
    return set(group.commands) if group is not None else set()  # type: ignore[attr-defined]


def citation_violations(
    assets: Mapping[str, str],
    *,
    source_text: str,
    guide_text: str,
    commands: set[str],
    registry_commands: set[str],
) -> list[str]:
    """Every citation in ``assets`` triangulated against machine sources.

    A citation is checked, not trusted: a code must occur in the SDK source
    AND in the user guide (a rename or a guide drop reddens the asset that
    still cites it); a subcommand must be registered in the click group at
    test time; a heading pointer must exist verbatim in the qmd. Returns one
    violation string per failure, naming the asset and the missing half.
    """
    guide_headings = {
        " ".join(match.group(1).split())
        for match in map(HEADING_LINE.match, guide_text.splitlines())
        if match is not None
    }
    violations: list[str] = []
    for name, text in sorted(assets.items()):
        for code in CODE_CITATION.findall(text):
            # Adversary fold A-F2: substring halves admitted plausible
            # neighbors (`max_bytes:`, `operation_id:` occur in both halves
            # as dictionary keys and envelope fields). Both halves are now
            # anchored to the citation surfaces: the source half requires the
            # code at a string-literal start (where refusal messages raise
            # it), the guide half requires the guide's own backticked
            # `` `code:` `` listing — the convention its refusal-code
            # sections use.
            if re.search(rf"[\"']{re.escape(code)}:", source_text) is None:
                violations.append(
                    f"{name}: cited code `{code}:` is not raised in the SDK source"
                )
            if f"`{code}:`" not in guide_text:
                violations.append(
                    f"{name}: cited code `{code}:` is not listed in the user guide"
                )
        for match in COMMAND_CITATION.finditer(text):
            subcommand = match.group(1)
            if subcommand not in commands:
                violations.append(
                    f"{name}: `benchweave-sdk {subcommand}` is not a registered command"
                )
        for subcommand in REGISTRY_SUBCOMMAND.findall(text):
            if subcommand not in registry_commands:
                violations.append(
                    f"{name}: `benchweave-sdk registry {subcommand}` is not a registered "
                    "registry subcommand"
                )
        for heading in HEADING_CITATION.findall(text):
            normalised = " ".join(heading.split())
            if normalised not in guide_headings:
                violations.append(
                    f'{name}: cited heading "{heading}" is not in the user guide'
                )
    return violations


# --- R-5c: the three planted violations, permanent ---------------------------


def test_planted_fake_code_is_caught() -> None:
    """Arm (i): a code that exists nowhere must not pass triangulation."""
    planted = {
        "PLANTED.md": (
            "The check refuses with `not_a_real_code:` when the descriptor "
            'is wrong. See section "3. Run the checks".\n'
        )
    }
    violations = citation_violations(
        planted,
        source_text=sdk_source_text(),
        guide_text=GUIDE.read_text(encoding="utf-8"),
        commands=registered_commands(),
        registry_commands=registry_subcommands(),
    )
    assert any("not_a_real_code" in violation for violation in violations), violations
    assert any("source" in violation for violation in violations), (
        "the arm must name the missing half"
    )
    assert any("guide" in violation for violation in violations), (
        "the arm must name the missing half"
    )


def test_planted_unknown_subcommand_is_caught() -> None:
    """Arm (ii): a subcommand the click group does not register must not pass."""
    planted = {
        "PLANTED.md": "Run `benchweave-sdk frobnicate` to repair the project.\n"
    }
    violations = citation_violations(
        planted,
        source_text=sdk_source_text(),
        guide_text=GUIDE.read_text(encoding="utf-8"),
        commands=registered_commands(),
        registry_commands=registry_subcommands(),
    )
    assert any("frobnicate" in violation for violation in violations), violations


def test_planted_missing_heading_is_caught() -> None:
    """Arm (iii): a pointer to a heading that does not exist must not pass."""
    planted = {
        "PLANTED.md": 'See section "No Such Heading Was Ever Written".\n'
    }
    violations = citation_violations(
        planted,
        source_text=sdk_source_text(),
        guide_text=GUIDE.read_text(encoding="utf-8"),
        commands=registered_commands(),
        registry_commands=registry_subcommands(),
    )
    assert any("No Such Heading Was Ever Written" in violation for violation in violations), (
        violations
    )


def test_planted_plausible_neighbor_is_caught() -> None:
    """Arm (iv), adversary fold A-F2: a substring that occurs in BOTH halves
    but is not a refusal code must not pass. ``max_bytes:`` and
    ``operation_id:`` occur in SDK source and in the guide (as dictionary
    keys and envelope fields) — the raise-site/backtick anchoring is what
    separates a refusal code from these plausible neighbors."""
    for neighbor in ("max_bytes", "operation_id"):
        planted = {
            "PLANTED.md": (
                f"The writer refuses with `{neighbor}:` when the exchange is "
                'wrong. See section "3. Run the checks".\n'
            )
        }
        violations = citation_violations(
            planted,
            source_text=sdk_source_text(),
            guide_text=GUIDE.read_text(encoding="utf-8"),
            commands=registered_commands(),
            registry_commands=registry_subcommands(),
        )
        assert any(neighbor in violation for violation in violations), (
            f"`{neighbor}:` is a plausible neighbor that must not pass; got {violations}"
        )


def test_planted_registry_subcommand_is_caught() -> None:
    """Arm (v), adversary fold F5: a two-word ``benchweave-sdk registry …``
    mention whose second word the registry group does not register must not
    pass — the first-token check alone would accept it."""
    planted = {
        "PLANTED.md": "Run `benchweave-sdk registry frobnicate` to repair a record.\n"
    }
    violations = citation_violations(
        planted,
        source_text=sdk_source_text(),
        guide_text=GUIDE.read_text(encoding="utf-8"),
        commands=registered_commands(),
        registry_commands=registry_subcommands(),
    )
    assert any("frobnicate" in violation for violation in violations), violations


# --- R-5b: the real assets, exhaustively -------------------------------------


def test_real_assets_pass_triangulation() -> None:
    """Every citation in every asset file triangulates. Exhaustive over the
    complete set matched by the three citation regexes — a new citation class
    member that fails any half reddens here by name."""
    violations = citation_violations(
        load_assets(),
        source_text=sdk_source_text(),
        guide_text=GUIDE.read_text(encoding="utf-8"),
        commands=registered_commands(),
        registry_commands=registry_subcommands(),
    )
    assert violations == [], "\n".join(violations)


def test_each_asset_cites_at_least_one_verifiable_thing() -> None:
    """The denominator guard (design §4): per file, the union of matched
    citations is non-empty, so a reformatted-away citation convention cannot
    silently remove a file from checking entirely."""
    for name, text in sorted(load_assets().items()):
        cited = (
            len(CODE_CITATION.findall(text))
            + len(COMMAND_CITATION.findall(text))
            + len(HEADING_CITATION.findall(text))
        )
        assert cited > 0, f"{name} cites nothing the checker can verify"


def test_every_citation_class_is_exercised() -> None:
    """Each of the three citation classes is non-empty over the six files —
    a regex bug that matches nothing everywhere cannot leave a dead check."""
    assets = load_assets()
    joined = "\n".join(assets.values())
    assert CODE_CITATION.findall(joined), "no code citations anywhere — class is dead"
    assert COMMAND_CITATION.findall(joined), "no command citations anywhere — class is dead"
    assert HEADING_CITATION.findall(joined), "no heading citations anywhere — class is dead"


def test_prose_refusal_skills_cite_no_codes() -> None:
    """Design §2.2: the plugin-ui, adapter-testing and capture skills cite no
    codes. The capture surface refuses in prose; the plugin-ui lane refuses
    through the schema/validator surface; adapter-testing documents module
    APIs. A code-shaped token in these files is an invented citation."""
    assets = load_assets()
    for name in CODE_FREE_SKILLS:
        assert not CODE_CITATION.findall(assets[name]), (
            f"{name} cites a code the design says it must not"
        )


def test_the_versioned_docs_url_uses_the_tag_prefixed_bucket() -> None:
    """Adversary fold A-F1: the versioned docs buckets are keyed by the
    release TAG — ``docs/v/v0.6.0/``, tags carry the leading ``v`` (the same
    convention ``scaffold.py`` pins with ``_commit: v{__version__}`` and
    ``scripts/assemble_docs_site.py`` builds under ``docs/v/<tag>/``) — not
    by the bare version. A rendered ``docs/v/0.6.0/`` URL is a dead link in
    every generated project."""
    agents = (TEMPLATE / "AGENTS.md.jinja").read_text(encoding="utf-8")
    assert "https://sdk.benchweave.dev/docs/v/v{{ sdk_version }}/" in agents, (
        "the docs URL must name the v-prefixed tag bucket, not the bare version"
    )


def test_assets_carry_no_version_literals() -> None:
    """Design §2.3: the only version carrier is the `{{ sdk_version }}`
    token — a typed number would let a render ship a stale stamp."""
    for name, text in sorted(load_assets().items()):
        assert not VERSION_LITERAL.search(text), f"{name} carries a typed version literal"
        assert "{{ sdk_version }}" in text, f"{name} lost its sdk_version token"


def test_every_asset_declares_itself_managed() -> None:
    """The managed footer: assets state what maintains them and how they
    move forward (the WS2 managed/owned split, stated in the artifact)."""
    for name, text in sorted(load_assets().items()):
        assert "benchweave-sdk upgrade" in text, f"{name} does not name the upgrade command"


# --- R-5a: the fixture grows exactly the managed set -------------------------


def test_template_carries_the_managed_asset_members() -> None:
    for member in ASSET_MEMBERS.values():
        assert (TEMPLATE / member).is_file(), f"template member missing: {member}"


def test_fixture_arms_grow_exactly_the_managed_assets() -> None:
    """R-5a: both fixture arms carry the six managed assets — byte-pinned by
    the R-2 parity tests — and the fixture's agent-asset set is EXACTLY the
    managed set, so a template growth in `.claude/**` or a new root guide is
    a deliberate change that updates ASSET_MEMBERS."""
    for arm in ("base", "ui"):
        fixture_agent_files = {
            entry.relative_to(FIXTURES / arm).as_posix()
            for entry in (FIXTURES / arm).rglob("*")
            if entry.is_file()
            and (
                ".claude" in entry.relative_to(FIXTURES / arm).parts
                or entry.relative_to(FIXTURES / arm).parts[0] == "AGENTS.md"
            )
        }
        assert fixture_agent_files == set(ASSET_MEMBERS), (
            f"{arm} arm agent-asset set differs from the managed set"
        )
        for relative in ASSET_MEMBERS:
            assert (FIXTURES / arm / relative).is_file(), f"{arm} arm missing {relative}"

    # The skills and AGENTS.md are unconditional (design deferral 4): both
    # arms carry byte-identical copies.
    for relative in ASSET_MEMBERS:
        base_bytes = (FIXTURES / "base" / relative).read_bytes()
        assert base_bytes == (FIXTURES / "ui" / relative).read_bytes(), relative
