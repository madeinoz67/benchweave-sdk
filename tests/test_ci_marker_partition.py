"""The ``loop`` lane's CI partition — both halves, guarded.

Issue #556, design record §13. The standalone dev-loop module builds this
repository's wheel and a fresh venv in a session-scoped fixture, so it was moved
out of the ``-n auto`` leg and into a serial ubuntu-only step. That partition
has two halves, and EITHER half alone is the silent state the move exists to
prevent:

* **Half A** — every parallel pytest invocation excludes the marker. Without it
  the module returns to ``-n auto``, where each xdist worker holding one of its
  tests repeats the wheel-and-venv build that breached the CI budget.
* **Half B** — a step selects the marker, gated to ubuntu alone, without ``-n``.
  With half A's exclusion in place and this step gone, the module never runs in
  CI and every lane stays green: the evidence dies silently.

The workflow is parsed, not searched: a comment containing ``not loop`` would
satisfy a text search. The ``-m`` expressions are read out of each step's
``run`` block, so only what pytest would actually receive can satisfy this arm.

What it does not catch, stated so the claim does not outrun it:

* The module's own ``pytestmark``. Removing it returns the module to the
  parallel leg — expensive, not vacuous, and half A's marker would then be the
  one in force.
* The selecting step's position in the job. A step that ran before the
  environment sync would fail loudly on a missing pytest rather than pass
  quietly.
* Its own existence: deleting this module removes the guard silently. That is
  review's job (G5), and §13 records it.
* The macOS/Windows non-coverage §13 records as an accepted limit.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
MARKER = "loop"

#: A pytest ``-m`` argument: double-quoted, single-quoted, or bare.
_MARKER_ARGUMENT = re.compile(r"""-m\s+(?:"([^"]*)"|'([^']*)'|(\S+))""")
#: xdist's worker flag, bounded so ``-m`` and ``--name`` cannot match it.
_XDIST_FLAG = re.compile(r"(?:^|\s)-n(?:\s|$)")
#: A runner image named by a step's ``if`` gate.
_RUNNER_IMAGE = re.compile(r"[a-z]+-latest")


def _steps() -> list[dict[str, Any]]:
    """The ``sdk`` job's steps — the job the loop lane is partitioned inside."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return list(workflow["jobs"]["sdk"]["steps"])


def _pytest_lines(run: str) -> list[str]:
    return [line for line in run.splitlines() if "pytest" in line]


def _marker_expressions(line: str) -> list[str]:
    """The ``-m`` expressions pytest would receive from one command line."""
    return [
        next(group for group in match.groups() if group is not None)
        for match in _MARKER_ARGUMENT.finditer(line)
    ]


def _excludes(expression: str) -> bool:
    return re.search(rf"\bnot\s+{re.escape(MARKER)}\b", expression) is not None


def _selects(expression: str) -> bool:
    return re.search(rf"\b{re.escape(MARKER)}\b", expression) is not None and not _excludes(
        expression
    )


def test_the_loop_lane_keeps_both_halves_of_its_partition() -> None:
    """Half A and half B, in one arm: either half alone is the silent state.

    The three failure messages name their half, so a red says which half moved:
    a parallel invocation that still selects the marker or excludes nothing, a
    selecting step that runs with ``-n``, or no selecting step at all.
    """
    parallel: list[tuple[str, str]] = []  # (step name, command line)
    selecting: list[tuple[str, dict[str, Any], str]] = []  # (step name, step, line)
    for step in _steps():
        name = str(step.get("name", "(unnamed step)"))
        for line in _pytest_lines(str(step.get("run", ""))):
            is_parallel = _XDIST_FLAG.search(line) is not None
            if is_parallel:
                parallel.append((name, line))
            if any(_selects(expression) for expression in _marker_expressions(line)):
                selecting.append((name, step, line))

    # ---- Half B, first refusal: the selecting step must not be parallel. ----
    # Checked before half A: a selecting step that also passes `-n` is both
    # halves' problem, and the cause is the missing `-n`-free serial run.
    for name, _step, line in selecting:
        assert not _XDIST_FLAG.search(line), (
            f"half B is parallelised: step {name!r} selects `{MARKER}` with `-n` "
            f"({line!r}) — every xdist worker holding one of the module's tests repeats "
            "the wheel-and-venv build (issue #556, design record §13)"
        )

    # ---- Half A: no parallel invocation may select the marker. --------------
    assert parallel, (
        "half A missing: no `sdk` step runs pytest with `-n`, so this guard cannot see "
        "the parallel selection at all — re-point it before trusting its green"
    )
    for name, line in parallel:
        expressions = _marker_expressions(line)
        assert expressions, (
            f"half A missing: the parallel invocation in step {name!r} carries no `-m` "
            f"expression, so it selects every marker including `{MARKER}`: {line!r}"
        )
        assert all(_excludes(expression) for expression in expressions), (
            f"half A missing: step {name!r} runs `{line}` — the parallel selection does "
            f"not exclude `{MARKER}`. The loop module would run under `-n auto`, where "
            "every xdist worker holding one of its tests repeats the wheel-and-venv build "
            "(issue #556, design record §13)"
        )

    # ---- Half B: a ubuntu-gated, serial step must select the marker. --------
    assert selecting, (
        f"half B missing: no `sdk` step selects `-m {MARKER}`. With half A's exclusion in "
        "place the module never runs in CI at all, and every lane stays green "
        "(issue #556, design record §13)"
    )
    for name, step, _line in selecting:
        gate = str(step.get("if", ""))
        images = set(_RUNNER_IMAGE.findall(gate))
        assert images == {"ubuntu-latest"}, (
            f"half B is mis-gated: step {name!r} selects `{MARKER}` but its `if` is "
            f"{gate!r}, which does not gate the run to ubuntu-latest alone"
        )
