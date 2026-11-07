"""The working-tree guard's trip probes (#427 fold F1/F2, widened by #442).

Issue #427's refute lane measured the write-by-pass matrix of the
original write_bytes-only guard: write_text, open("w"/"wb"), os.replace,
shutil.copyfile, subprocess writes and symlink swaps were ALL silent,
and an open("w") probe accidentally truncated a real tree file while the
test passed — live lethality proof. These probes pin the vectors the
suite-wide guard (tests/conftest.py) HOOKS: each must trip BEFORE any
byte lands. The vectors it does not hook are named in that guard's
docstring (G4 — the not-caught list is part of the claim).

#442 widened the guard's PATH scope: it now refuses any write inside the
repository working tree (``.pytest_cache`` excepted), not only the
vendored tree. ``test_every_hooked_write_vector_trips_the_working_tree_guard``
is the path-scope row; the tree rows above are unchanged pins.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TREE = REPO / "src/benchweave_sdk/standards"


def _scratch_target() -> Path:
    """A NEW name inside the tree: nothing real can be corrupted if a
    probe ever fails open (the guard-absent failure mode creates this
    file; the finally removes it)."""
    return TREE / "#427-guard-probe.tmp"


def _working_tree_target() -> Path:
    """A NEW name inside the repository root, outside the vendored tree —
    the #442 leak class (``captures/operator-action-token.json`` under the
    checkout root) is exactly this: a write the vendored-tree predicate
    never saw."""
    return REPO / "#442-guard-probe.tmp"


VECTORS: dict[str, Callable[[Path], object]] = {
    "Path.write_bytes": lambda target: target.write_bytes(b"x"),
    "Path.write_text": lambda target: target.write_text("x"),
    'Path.open("w")': lambda target: target.open("w"),
    'open("wb")': lambda target: open(target, "wb"),  # noqa: SIM115
    'Path.open("a")': lambda target: target.open("a"),
}


@pytest.mark.parametrize("vector", sorted(VECTORS))
def test_every_hooked_write_vector_trips_the_guard(vector: str) -> None:
    """The guard refuses the write BEFORE it reaches the filesystem —
    the probe target never exists, whichever hooked vector carries it."""
    target = _scratch_target()
    try:
        with pytest.raises(AssertionError, match="committed vendored tree"):
            VECTORS[vector](target)
        assert not target.exists(), (
            "the guard must refuse before any byte lands on the tree"
        )
    finally:
        target.unlink(missing_ok=True)


@pytest.mark.parametrize("vector", sorted(VECTORS))
def test_every_hooked_write_vector_trips_the_working_tree_guard(vector: str) -> None:
    """#442: the guard's scope widened from the vendored tree to the whole
    repository working tree. The historical leak was
    ``captures/operator-action-token.json`` under the checkout root — no
    vendored-tree predicate covers that path, so the old guard was silent
    on it. The exemption (``.pytest_cache``) is named in the guard's
    docstring; this probe is outside it, as any real leak would be."""
    target = _working_tree_target()
    try:
        with pytest.raises(AssertionError, match="repository working tree"):
            VECTORS[vector](target)
        assert not target.exists(), (
            "the guard must refuse before any byte lands in the working tree"
        )
    finally:
        target.unlink(missing_ok=True)
