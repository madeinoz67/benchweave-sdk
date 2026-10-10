"""The committed-tree guard reaches every descendant module (#427 fold
F2): the original guard lived in test_dependency_serving.py only, so a
tamper arm anywhere else in the suite could write the shared bytes with
nothing watching — exactly the shape issue #427 itself was. One probe,
from the server subpackage, proves the suite-wide conftest guard fires
here too."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TREE = REPO / "src/benchweave_sdk/standards"


def test_the_guard_fires_from_a_server_module_too() -> None:
    target = TREE / "#427-guard-probe.tmp"
    try:
        with pytest.raises(AssertionError, match="committed vendored tree"):
            target.write_text("x")
        assert not target.exists()
    finally:
        target.unlink(missing_ok=True)
