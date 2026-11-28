"""Declaration completeness of the review-lane model pins (``.claude/agents/*.md``).

Issue #519: the review rubric's G6 lane says each refute run's model is whatever
the installation resolves the agent's DECLARED pin to — that claim presupposes
every agent definition declares a ``model:`` line, and this test is what makes
the presupposition regenerable instead of assumed.

What this test does NOT catch:
- Same-pin convergence: two lanes declaring the same pin is an owner-accepted
  posture (``adversary`` and ``increment-builder`` both pin ``opus``) — this
  test never compares pins.
- Vendor identity: which vendor an installation resolves a pin to is an
  installation property, invisible to repository state — no in-repo test can
  catch it.
- Presence-only: all that is proved is a declared value on a ``model:`` line
  in each frontmatter. That the pin names a real alias (the repo holds no
  authority for the alias set), or that the declared pin served any given
  run, is not proved.
- A vendor-named or misspelled pin passes; the declaration is the
  precondition, not the value.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / ".claude" / "agents"

# Unquoted YAML null tokens — a quoted "null" is an ordinary value, not one
# of these (the refute's five absent shapes are unquoted).
_NULL_SENTINELS = {"null", "~"}


def _frontmatter_lines(text: str) -> list[str]:
    """The lines inside the leading ``---`` frontmatter block, else ``[]``."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    body: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            return body
        body.append(line)
    # No closing fence: treat the frontmatter as absent rather than guessing.
    return []


def _declares_model_pin(frontmatter: list[str]) -> bool:
    """Whether any frontmatter line declares a pin an installation could resolve.

    A declaration must carry a value: absent is a failure, and the five
    valueless shapes the #519 refute named — ``model:``, ``model: ""``,
    ``model: null``, ``model: ~``, and a comment-only value — all count as
    absent. Anything else declares a pin: name shape is not validated here
    (``model: TODO`` and a misspelled alias pass, by design).
    """
    for line in frontmatter:
        if not line.startswith("model:"):
            continue
        rest = line.removeprefix("model:")
        # YAML comment: a " #" ends the scalar (a bare # inside a value is
        # not a comment without the leading space).
        hash_at = rest.find(" #")
        if hash_at != -1:
            rest = rest[:hash_at]
        value = rest.strip()
        if value in ("", "''", '\"\"'):
            continue
        if value.lower() in _NULL_SENTINELS:
            continue
        return True
    return False


def test_every_agent_definition_declares_a_model_pin() -> None:
    agent_files = sorted(AGENTS_DIR.glob("*.md"))
    # The glob, not a hand-list: a new agent joins the check by existing.
    assert agent_files, f"no agent definitions under {AGENTS_DIR} — path moved?"
    missing = [
        path.name
        for path in agent_files
        if not _declares_model_pin(_frontmatter_lines(path.read_text(encoding="utf-8")))
    ]
    assert not missing, (
        "agent definition(s) without a declared model pin (review rubric G6, issue "
        f"#519 — the pin must be declared so an installation can resolve it): {missing}"
    )


@pytest.mark.parametrize(
    "line",
    [
        "model:",
        "model: \"\"",
        "model: ''",
        "model: null",
        "model: ~",
        "model: # declared elsewhere",
    ],
    ids=["empty", "empty-dq", "empty-sq", "null", "tilde", "comment-only"],
)
def test_valueless_pin_declarations_are_absent(line: str) -> None:
    """FOLD-1 (#519): the five valueless shapes the refute named declare nothing.

    ``model:``, ``model: ""``, ``model: null``, ``model: ~``, and a
    comment-only value must all fail the declaration check — an installation
    cannot resolve a pin that carries no value.
    """
    assert not _declares_model_pin([line])


@pytest.mark.parametrize(
    "line",
    ["model: opus", "model: TODO", "model: rival-9", "model: opu", 'model: "null"'],
    ids=["alias", "placeholder", "invented-vendor", "misspelled", "quoted-null"],
)
def test_unrecognised_values_still_declare_a_pin(line: str) -> None:
    """FOLD-2's boundary (#519): name shape is not validated — by design.

    A vendor-named or misspelled pin passes; the declaration is the
    precondition, not the value. A quoted "null" is an ordinary value, not
    one of the unquoted null sentinels.
    """
    assert _declares_model_pin([line])
