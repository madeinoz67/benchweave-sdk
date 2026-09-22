"""Standalone capture writer: root resolution, segment rules, staged lifecycle.

Derivations (from primary sources, not the plan's restatement):

- Root precedence and the package-tree refusal: the design of record
  (Decision 9) — explicit constructor argument > ``BENCHWEAVE_CAPTURE_DIR``
  > ``captures/`` under the current working directory, and "never inside the
  installed package tree, where the SDK's own inventory verification refuses
  unlisted files".
- Segment alphabet: the ``safe_resource_path`` allowlist minus the separator
  (single segment): ``[A-Za-z0-9_.-]``, bounded length, no ``.``/````,
  Windows device names refused as a case-insensitive prefix of the first
  dot-separated component (dotted ``nul.json``/``con.txt`` name devices).
- Collision check: NFC-normalize-then-casefold against existing event
  directories (so ``CAPTURE-1`` collides with ``capture-1``), and ``mkdir``
  EEXIST from a concurrent process converts to a prefixed refusal.
- The manifest key set and the count-times-eight rule derive from the
  vendored ``otdp-runtime.schema.json`` ``$defs/captureManifest`` (required
  list + the waveform allOf) loaded at test time via ``contract_documents``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import benchweave_sdk.capture as capture


class Context:
    """The minimal OperationContext the writer consults (cancellation)."""

    def __init__(self, *, cancelled: bool = False) -> None:
        self._cancelled = cancelled

    def is_cancelled(self) -> bool:
        return self._cancelled


def _writer(tmp_path: Path, **kwargs: Any) -> Any:
    return capture.StandaloneCaptureWriter(tmp_path / "captures", **kwargs)


# --- S1: capture-root resolution ----------------------------------------------


def test_capture_root_precedence_explicit_env_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = tmp_path / "explicit"
    from_env = tmp_path / "from-env"
    monkeypatch.chdir(tmp_path)
    assert capture.capture_root(explicit) == explicit.resolve()
    monkeypatch.setenv("BENCHWEAVE_CAPTURE_DIR", str(from_env))
    assert capture.capture_root(explicit) == explicit.resolve()  # explicit wins
    assert capture.capture_root() == from_env.resolve()  # env beats the default
    monkeypatch.delenv("BENCHWEAVE_CAPTURE_DIR")
    assert capture.capture_root() == (tmp_path / "captures").resolve()


def test_capture_root_refuses_the_installed_package_tree(tmp_path: Path) -> None:
    """The hazard (Decision 9 + B14): a reinstall/upgrade wipes site-packages,
    and the SDK's inventory verification refuses unlisted files — run data
    does not belong under the package parent (all of it, not just the package
    directory)."""
    package_parent = Path(capture.__file__).resolve().parent.parent
    refusal = package_parent / "captures"
    with pytest.raises(ValueError, match="package tree"):
        capture.capture_root(refusal)
    # The guard covers the package directory itself, not only its parent.
    with pytest.raises(ValueError, match="package tree"):
        capture.capture_root(package_parent)


# --- S1: capture_id segment rules (before any filesystem call) ----------------

SAFE_IDS = ("cap-1", "a", "Event_2026.v2", "capture-000042")

UNSAFE_IDS = (
    "",
    ".",
    "..",
    "a/b",
    "a\\b",
    "a b",
    "x\0y",
    "café",  # non-ASCII: the Unicode class dies at the character gate
    "nul",
    "nul.json",  # device-name PREFIX: the first dot-separated component
    "con.txt",
    "COM1",
    "lpt9.data",
    "aux",
    "a" * 65,  # bounded length: 65 of a 64-char ceiling
)


@pytest.mark.parametrize("identifier", SAFE_IDS)
def test_valid_capture_segment_accepts_portable_ids(identifier: str) -> None:
    assert capture._valid_capture_segment(identifier)


@pytest.mark.parametrize("identifier", UNSAFE_IDS)
def test_valid_capture_segment_refuses_every_unsafe_class(identifier: str) -> None:
    assert not capture._valid_capture_segment(identifier)


def test_valid_capture_segment_bounds_the_length_boundary() -> None:
    assert capture._valid_capture_segment("a" * 64)
    assert not capture._valid_capture_segment("a" * 65)


def test_the_cafe_pair_unicode_dies_at_the_character_gate() -> None:
    """The B9 machine check: the ASCII-allowed spelling is accepted while its
    non-ASCII homoglyph is refused by the alphabet — the café class never
    reaches the filesystem, on every lane."""
    assert capture._valid_capture_segment("cafe")
    assert not capture._valid_capture_segment("café")


def test_segment_collision_is_case_folded(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    (root / "capture-one").mkdir(parents=True)
    assert not capture._segment_is_free(root, "capture-one")
    assert not capture._segment_is_free(root, "CAPTURE-ONE")  # case-folded
    assert capture._segment_is_free(root, "capture-two")
