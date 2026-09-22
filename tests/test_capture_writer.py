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

import asyncio
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


async def _append(writer: Any, capture_id: str, chunks: list[bytes]) -> None:
    for chunk in chunks:
        await writer.artifact_append(capture_id, chunk, Context())


def _tree(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


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


# --- S2: the open/append lifecycle --------------------------------------------


def test_append_stages_ordered_chunks_under_the_event_directory(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    asyncio.run(_append(writer, "cap-1", [b"alpha", b"beta", b"gamma"]))
    staging = tmp_path / "captures" / "cap-1" / "staging"
    parts = sorted(path.name for path in staging.iterdir())
    assert parts == ["0.part", "1.part", "2.part"]
    assert (staging / "0.part").read_bytes() == b"alpha"
    assert (staging / "2.part").read_bytes() == b"gamma"


def test_the_capture_methods_are_coroutine_shaped() -> None:
    """The SDK protocol is coroutine-shaped (§8): a sync writer TypeErrors at
    the first await inside an adapter coroutine."""
    assert asyncio.iscoroutinefunction(capture.StandaloneCaptureWriter.artifact_append)
    assert asyncio.iscoroutinefunction(capture.StandaloneCaptureWriter.artifact_finalise)
    assert asyncio.iscoroutinefunction(capture.StandaloneCaptureWriter.artifact_abort)


def test_cancelled_append_writes_nothing(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    asyncio.run(_append(writer, "cap-1", [b"first"]))
    before = _tree(tmp_path / "captures")
    with pytest.raises(TimeoutError):
        asyncio.run(writer.artifact_append("cap-1", b"second", Context(cancelled=True)))
    assert _tree(tmp_path / "captures") == before  # the cancelled append wrote nothing


def test_second_capture_in_flight_is_refused(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    asyncio.run(_append(writer, "cap-1", [b"data"]))
    with pytest.raises(RuntimeError, match="one capture in flight"):
        asyncio.run(_append(writer, "cap-2", [b"data"]))
    # The refused open created nothing for the second id.
    assert not (tmp_path / "captures" / "cap-2").exists()


def test_unsafe_id_is_refused_at_append_before_any_filesystem_call(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path)
    with pytest.raises(ValueError, match="unsafe capture_id segment"):
        asyncio.run(writer.artifact_append("nul.json", b"data", Context()))
    with pytest.raises(ValueError, match="unsafe capture_id segment"):
        asyncio.run(writer.artifact_append("../escape", b"data", Context()))
    assert not (tmp_path / "captures").exists()  # no root, no event, no staging


def test_empty_append_is_refused(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    with pytest.raises(ValueError, match="empty append"):
        asyncio.run(writer.artifact_append("cap-1", b"", Context()))
    assert not (tmp_path / "captures" / "cap-1").exists()


def test_append_over_the_declared_reservation_is_refused(tmp_path: Path) -> None:
    writer = _writer(tmp_path, max_bytes=10)
    asyncio.run(_append(writer, "cap-1", [b"0123456789"]))
    with pytest.raises(ValueError, match="max_bytes reservation"):
        asyncio.run(writer.artifact_append("cap-1", b"x", Context()))
    staging = tmp_path / "captures" / "cap-1" / "staging"
    assert len(list(staging.iterdir())) == 1  # the refused append staged nothing


def test_concurrent_event_directory_creation_is_a_prefixed_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The B13 two-process arbiter, made deterministic: the collision check
    sees no events (another process wins the mkdir between check and create),
    so the writer's own mkdir raises EEXIST — which must surface as a clean
    prefixed refusal, never a bare OSError and never an interleave."""
    root = tmp_path / "captures"
    event = root / "cap-raced"
    event.mkdir(parents=True)
    monkeypatch.setattr(capture, "_existing_event_names", lambda _root: [])
    writer = capture.StandaloneCaptureWriter(root)
    with pytest.raises(ValueError, match="capture event directory already exists"):
        asyncio.run(writer.artifact_append("cap-raced", b"data", Context()))
    # Nothing was written into the other process's directory.
    assert list(event.iterdir()) == []


def test_case_folded_collision_is_refused_at_append(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    (root / "capture-one").mkdir(parents=True)
    writer = capture.StandaloneCaptureWriter(root)
    with pytest.raises(ValueError, match="capture_id collision"):
        asyncio.run(writer.artifact_append("CAPTURE-ONE", b"data", Context()))

