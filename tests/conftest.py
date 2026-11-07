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

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
VENDORED_TREE = REPO / "src/benchweave_sdk/standards"
PYTEST_CACHE = REPO / ".pytest_cache"
# The running interpreter's environment. uv parks it INSIDE the checkout
# (``venv/`` or ``.venv/``), and the import system writes lazy-module
# bytecode caches there through the hooked ``open`` — measured, not
# assumed: the #442 A2 run caught
# ``venv/.../anyio/_core/__pycache__/_subprocesses...pyc`` from ten
# mcp-shim tests. A named exemption, not a quiet widening: that path is
# the interpreter's own state, and git ignores it, so it can never become
# the leaked checkout state this guard surfaces.
PYTHON_ENV = Path(sys.prefix).resolve()

# Editable-install resilience (local macOS, observed 2026-11-06): a
# file-provider daemon can set the macOS hidden flag on the worktree venv's
# editable .pth, and CPython's site.addpackage silently skips hidden .pth
# files — the src path never joins sys.path and benchweave_sdk resolves to
# the namespace-package data portion in site-packages (no submodules).
# Having src on sys.path at all restores resolution — the regular package
# at src wins over any namespace portion regardless of position — and this
# is exactly what the editable .pth does, so on a healthy venv it is a
# no-op duplicate.
_SRC = REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _writes(mode: str) -> bool:
    """A mode string that can mutate the file: w/x/a grant write, and +
    grants write alongside any base mode (r+ mutates without w/a/x)."""
    mode = mode or "r"  # an explicit None is the read default, not a crash
    return any(flag in mode for flag in ("w", "x", "a", "+"))


def _resolve(candidate: object) -> Path | None:
    """The resolved path, or None when the candidate is not a path (an fd
    int, a file object) or cannot be resolved — nothing to judge either
    way, and the write will fail on its own."""
    try:
        path = Path(candidate)  # type: ignore[arg-type]
    except TypeError:
        return None
    try:
        return path.resolve()
    except OSError:
        return None


def _is_tree_path(candidate: object) -> bool:
    resolved = _resolve(candidate)
    return resolved is not None and (
        resolved == VENDORED_TREE or VENDORED_TREE in resolved.parents
    )


def _working_tree_violation(candidate: object) -> Path | None:
    """The resolved path when the write would land inside the repository
    working tree (#442), else None. Two tool-owned directories are
    exempt, both git-ignored and neither the leak class: ``.pytest_cache``
    (pytest's own cache provider writes there) and ``PYTHON_ENV`` (the
    interpreter's bytecode caches)."""
    resolved = _resolve(candidate)
    if resolved is None:
        return None
    if resolved != REPO and REPO not in resolved.parents:
        return None
    if resolved == PYTEST_CACHE or PYTEST_CACHE in resolved.parents:
        return None
    if resolved == PYTHON_ENV or PYTHON_ENV in resolved.parents:
        return None
    return resolved


@pytest.fixture(autouse=True)
def _the_committed_tree_is_never_written(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """No test under tests/ may write the committed vendored standards
    tree (#427) or any other path inside the repository working tree
    (#442) — the vendored bytes are shared state under ``-n auto`` (the
    digest-flake root cause), and a write into the checkout leaks state a
    later run consumes. The #442 class is exactly that: the pre-#427
    ``captures/operator-action-token.json`` landed under the checkout
    root, a path the tree-only predicate never saw.

    MECHANISM, exactly (G4): the guard wraps four write vectors and
    refuses BEFORE delegating, so the byte never lands —
    ``Path.write_bytes``, ``Path.write_text``, ``Path.open`` with a
    write-capable mode (w/x/a/+), and the ``open`` builtin with a
    write-capable mode (which ``shutil``'s pure-Python copy paths and any
    bare ``open(path, "w")`` go through). The trip is an AssertionError
    naming the path.

    The path scope is two predicates, in order: the vendored tree refuses
    first (its message is unchanged since #427), then anything resolved
    under ``REPO`` except two tool-owned, git-ignored directories —
    ``REPO/.pytest_cache`` and ``PYTHON_ENV`` (the interpreter's own
    environment; uv parks it inside the checkout, and lazy-module
    bytecode caches are written there through the hooked ``open``).

    NOT CAUGHT, by the same exactness: ``os.replace``/``os.rename`` into
    either scope, ``os.open``/``os.fdown`` descriptors (including
    ``shutil.copyfile``'s sendfile fast path on POSIX), writes from
    subprocesses, and a symlink swap at either path. A test that
    re-patches these four hooks itself disarms the guard for its own
    duration. Nor does the widened scope see a file descriptor opened
    before the test started, or a leak hidden under either exemption
    (which is why the list is two named tool directories, not a general
    ignore rule). The vectors actually hooked are pinned by
    tests/test_tree_guard.py and tests/server/test_tree_guard_reach.py;
    extending the hooked set means extending those probes in the same
    change.
    """
    refusal = (
        "write to the committed vendored tree attempted: {path} (#427 — "
        "plant tamper bytes on a tmp copy; the committed bytes are shared "
        "state under -n auto)"
    )
    working_tree_refusal = (
        "write into the repository working tree attempted: {path} "
        "(#442 — resolve your root under tmp_path)"
    )

    def _refuse(path: object) -> None:
        if _is_tree_path(path):
            raise AssertionError(refusal.format(path=path))
        leaked = _working_tree_violation(path)
        if leaked is not None:
            raise AssertionError(working_tree_refusal.format(path=leaked))

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
