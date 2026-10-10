"""Suite-wide guards over the committed repository state.

Issue #427: a test that opens a write window on the committed vendored
standards tree corrupts shared state for every concurrent reader under
``-n auto`` (the 1-in-3 xdist digest flakes the issue root-caused). The
guard below fires for EVERY test under ``tests/`` — the original guard
lived in ``test_dependency_serving.py`` only, and the refute lane showed
both holes at once: the narrow surface (write_bytes alone — write_text
and open("w") sailed through, one probe truncated a real tree file while
its test passed) and the module scope (any other module wrote
unwatched).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
VENDORED_TREE = REPO / "src/benchweave_sdk/standards"


def _writes(mode: str) -> bool:
    """A mode string that can mutate the file: w/x/a grant write, and +
    grants write alongside any base mode (r+ mutates without w/a/x)."""
    mode = mode or "r"  # an explicit None is the read default, not a crash
    return any(flag in mode for flag in ("w", "x", "a", "+"))


def _is_tree_path(candidate: object) -> bool:
    try:
        path = Path(candidate)  # type: ignore[arg-type]
    except TypeError:
        return False  # an fd int or other non-path — not ours to judge
    try:
        resolved = path.resolve()
    except OSError:
        # An unresolvable path cannot be inside the tree either way; the
        # write will fail on its own.
        return False
    return resolved == VENDORED_TREE or VENDORED_TREE in resolved.parents


@pytest.fixture(autouse=True)
def _the_committed_tree_is_never_written(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """No test under tests/ may write the committed vendored standards
    tree (#427) — the bytes are shared state under ``-n auto``, and the
    digest-flake root cause was exactly such a window.

    MECHANISM, exactly (G4): the guard wraps four write vectors and
    refuses BEFORE delegating, so the byte never lands —
    ``Path.write_bytes``, ``Path.write_text``, ``Path.open`` with a
    write-capable mode (w/x/a/+), and the ``open`` builtin with a
    write-capable mode (which ``shutil``'s pure-Python copy paths and any
    bare ``open(path, "w")`` go through). The trip is an AssertionError
    naming the path.

    NOT CAUGHT, by the same exactness: ``os.replace``/``os.rename`` into
    the tree, ``os.open``/``os.fdown`` descriptors (including
    ``shutil.copyfile``'s sendfile fast path on POSIX), writes from
    subprocesses, and a symlink swap at a tree path. A test that
    re-patches these four hooks itself disarms the guard for its own
    duration. The vectors actually hooked are pinned by
    tests/test_tree_guard.py and tests/server/test_tree_guard_reach.py;
    extending the hooked set means extending those probes in the same
    change.
    """
    refusal = (
        "write to the committed vendored tree attempted: {path} (#427 — "
        "plant tamper bytes on a tmp copy; the committed bytes are shared "
        "state under -n auto)"
    )

    def _refuse(path: object) -> None:
        if _is_tree_path(path):
            raise AssertionError(refusal.format(path=path))

    original_write_bytes = Path.write_bytes
    original_write_text = Path.write_text
    original_path_open = Path.open
    original_open = open  # the open builtin, resolved now, restored by monkeypatch

    def guarded_write_bytes(self: Path, data: bytes) -> int:
        _refuse(self)
        return original_write_bytes(self, data)

    def guarded_write_text(self: Path, data: str, **kwargs: Any) -> int:
        _refuse(self)
        return original_write_text(self, data, **kwargs)

    def guarded_path_open(self: Path, mode: str = "r", **kwargs: Any) -> Any:
        if _writes(mode):
            _refuse(self)
        return original_path_open(self, mode, **kwargs)

    def guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if _writes(mode):
            _refuse(file)
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "write_bytes", guarded_write_bytes)
    monkeypatch.setattr(Path, "write_text", guarded_write_text)
    monkeypatch.setattr(Path, "open", guarded_path_open)
    monkeypatch.setattr("builtins.open", guarded_open)
    yield
