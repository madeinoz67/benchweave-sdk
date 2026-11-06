"""The package-directory pick under ``<project>/src`` (the wheel-install rule).

A real wheel install into ``src/`` (``uv pip install --target``) leaves the
package tree beside its ``<name>-<version>.dist-info`` metadata directory.
``next(path for path in src.iterdir() if path.is_dir())`` then picks whichever
entry the filesystem yields first, so the pick is order-dependent: one order
reads the package's ``descriptor.json``, the other reads
``<dist-info>/descriptor.json`` and dies on a raw ``FileNotFoundError`` — the
A3 acceptance arm's CI failure on the ubuntu runner. The resolver must skip
the metadata directories and read the candidates in sorted order, so the
answer never depends on filesystem order.

These tests import the resolver through ``benchweave_sdk.cli`` (where the rule
lived before it was shared) so this file runs unchanged against the pre-fix
tree and the post-fix tree.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from benchweave_sdk.cli import _package_dir


def _force_sorted_iterdir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve every directory listing in sorted name order.

    The pick was iteration-order dependent, so the tests force one concrete
    order — the metadata directory first — instead of trusting the local
    filesystem's ``iterdir`` order.
    """
    real = Path.iterdir

    def sorted_iterdir(self: Path) -> Iterator[Path]:
        return iter(sorted(real(self), key=lambda path: path.name))

    monkeypatch.setattr(Path, "iterdir", sorted_iterdir)


def test_the_package_directory_is_not_the_wheel_metadata_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The metadata directory never wins, even when it is yielded first."""
    src = tmp_path / "src"
    (src / "aaa-0.1.0.dist-info").mkdir(parents=True)
    (src / "zzz_plugin").mkdir()
    _force_sorted_iterdir(monkeypatch)
    assert _package_dir(tmp_path, refusal="test_refusal") == src / "zzz_plugin"


def test_metadata_directories_alone_refuse_with_the_callers_voice(
    tmp_path: Path,
) -> None:
    """Nothing under ``src/`` but metadata directories is "no package": the
    named refusal, never a ``.dist-info``/``.egg-info``/``__pycache__`` pick."""
    src = tmp_path / "src"
    (src / "aaa-0.1.0.dist-info").mkdir(parents=True)
    (src / "bbb.egg-info").mkdir()
    (src / "__pycache__").mkdir()
    with pytest.raises(ValueError, match="test_refusal: no package under"):
        _package_dir(tmp_path, refusal="test_refusal")
