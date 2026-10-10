"""The committed-tree guard's trip probes (#427 fold F1/F2).

Issue #427's refute lane measured the write-by-pass matrix of the
original write_bytes-only guard: write_text, open("w"/"wb"), os.replace,
shutil.copyfile, subprocess writes and symlink swaps were ALL silent,
and an open("w") probe accidentally truncated a real tree file while the
test passed — live lethality proof. These probes pin the vectors the
suite-wide guard (tests/conftest.py) HOOKS: each must trip BEFORE any
byte lands. The vectors it does not hook are named in that guard's
docstring (G4 — the not-caught list is part of the claim).
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
