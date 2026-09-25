"""Standalone capture writer: root resolution, segment rules, staged lifecycle.

Derivations (from primary sources, not the plan's restatement):

- Root precedence and the package-tree refusal: the design of record
  (Decision 9) — explicit constructor argument > ``BENCHWEAVE_CAPTURE_DIR``
  > ``captures/`` under the current working directory, and "never inside the
  installed package tree, where the SDK's own inventory verification refuses
  unlisted files".
- Segment alphabet: the ``safe_resource_path`` allowlist minus the separator
  (single segment): ``[A-Za-z0-9_.-]``, bounded length, no trailing dot
  (so no ``.``/``..``, and nothing Windows would strip), Windows device
  names refused as a case-insensitive prefix of the first dot-separated
  component (dotted ``nul.json``/``con.txt`` name devices).
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
    "abc.",  # trailing dot: Windows strips it, so 'abc.' would publish into 'abc'
    "...",  # all dots: Windows strips them to nothing (raw FileNotFoundError)
    "a...",
    "abc ",  # trailing space: Windows strips it too (refused by the alphabet)
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


@pytest.mark.parametrize("identifier", ["abc.", "...", "a..."])
def test_a_trailing_dot_id_is_refused_at_append_before_any_filesystem_call(
    tmp_path: Path, identifier: str
) -> None:
    """Windows strips trailing dots from a path segment: 'abc.' published
    into the directory 'abc' under a manifest naming 'abc.', and '...' or
    'a...' raised a raw FileNotFoundError after creating an orphan
    directory. The segment gate refuses the shape as a string, on every OS."""
    writer = _writer(tmp_path)
    with pytest.raises(ValueError, match="unsafe capture_id segment"):
        asyncio.run(writer.artifact_append(identifier, b"\x00" * 8, Context()))
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


# --- S3: atomic finalise, real-digest manifest, abort scoping ------------------

_WAVEFORM = {
    "format": "waveform_f64le",
    "started_at": "2026-09-22T00:00:00Z",
    "sample_count": 3,
    "sample_interval_s": 0.001,
    "unit": "V",
}


def _capture_manifest_def() -> dict[str, Any]:
    """``$defs/captureManifest`` from the vendored corpus, at test time."""
    from benchweave_sdk.validation import contract_documents

    matches = [
        key
        for key in contract_documents()
        if key.startswith("otdp/") and key.endswith("/otdp-runtime.schema.json")
    ]
    assert len(matches) == 1, matches
    runtime = contract_documents()[matches[0]]
    defs = runtime["$defs"]["captureManifest"]
    assert isinstance(defs, dict)
    return defs


def _finalise(writer: Any, capture_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(writer.artifact_finalise(capture_id, metadata, Context()))


def test_finalise_digest_is_recomputed_over_the_published_file(tmp_path: Path) -> None:
    import hashlib

    writer = _writer(tmp_path)
    chunks = [b"\x00" * 8, b"\x01" * 8, b"\x02" * 8]
    asyncio.run(_append(writer, "cap-1", chunks))
    manifest = _finalise(writer, "cap-1", dict(_WAVEFORM))
    primary = tmp_path / "captures" / "cap-1" / "cap-1.f64"
    published = primary.read_bytes()
    digest = hashlib.sha256(published).hexdigest()  # over the FILE, not the buffers
    assert published == b"".join(chunks)
    assert manifest["sha256"] == digest
    assert manifest["byte_length"] == len(published)
    # B10: artifact_id = art-<sha256> over the real bytes — the same
    # construction as the gateway's content store, no store needed.
    assert manifest["artifact_id"] == "art-" + digest


def test_finalise_manifest_json_matches_the_returned_manifest(tmp_path: Path) -> None:
    import json as json_module

    writer = _writer(tmp_path)
    asyncio.run(_append(writer, "cap-1", [b"data-bytes"]))
    manifest = _finalise(writer, "cap-1", dict(_WAVEFORM, sample_count=1))
    written = json_module.loads(
        (tmp_path / "captures" / "cap-1" / "manifest.json").read_text()
    )
    assert written == manifest


def test_core_manifest_contains_the_corpus_required_keys_and_validates(
    tmp_path: Path,
) -> None:
    """R9 (B10 form): CONTAINS, not equality — ``x-standalone-*`` extension
    keys are schema-legal beside the corpus-required set, and a core-format
    manifest must validate against ``$defs/captureManifest`` itself. The
    writer enforces presence/shape only; the count×8 rule is spec §7 prose
    enforced by the GATEWAY's G1/G4 — the standalone writer names, digests
    and lengths bytes, it never interprets them (Decision 9)."""
    import jsonschema

    schema = _capture_manifest_def()
    writer = _writer(tmp_path)
    asyncio.run(_append(writer, "cap-1", [b"\x00" * 8]))
    manifest = _finalise(writer, "cap-1", dict(_WAVEFORM))
    required = set(schema["required"])  # derived from the corpus at test time
    assert required <= set(manifest), required - set(manifest)
    jsonschema.validate(manifest, schema)


def test_raw_binary_manifest_validates_against_the_corpus_def(tmp_path: Path) -> None:
    import jsonschema

    schema = _capture_manifest_def()
    writer = _writer(tmp_path)
    asyncio.run(_append(writer, "cap-raw", [b"\xff" * 5]))
    manifest = _finalise(
        writer,
        "cap-raw",
        {"format": "raw_binary", "started_at": "2026-09-22T00:00:00Z"},
    )
    assert (tmp_path / "captures" / "cap-raw" / "cap-raw.bin").exists()
    jsonschema.validate(manifest, schema)


def test_standalone_extras_live_under_x_standalone_keys(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    asyncio.run(_append(writer, "cap-1", [b"\x00" * 8]))
    manifest = _finalise(
        writer,
        "cap-1",
        dict(
            _WAVEFORM,
            renderings=[{"file": "plot.svg", "byte_length": 12, "sha256": "0" * 64}],
        ),
    )
    assert manifest["x-standalone-state"] == "finalised"
    assert manifest["x-standalone-manifest-version"] == 1
    assert manifest["x-standalone-renderings"] == [
        {"file": "plot.svg", "byte_length": 12, "sha256": "0" * 64}
    ]
    # No non-corpus key outside the x-standalone namespace.
    schema = _capture_manifest_def()
    allowed = set(schema["properties"]) | {
        "x-standalone-state",
        "x-standalone-renderings",
        "x-standalone-manifest-version",
    }
    assert set(manifest) <= allowed, set(manifest) - allowed


def test_finalise_refuses_an_undeclared_format_naming_the_declared_set(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path)  # default declared set: the two core formats
    asyncio.run(_append(writer, "cap-1", [b"data"]))
    with pytest.raises(ValueError, match=r"declared set \['raw_binary', 'waveform_f64le'\]"):
        _finalise(writer, "cap-1", {"format": "csv", "started_at": "2026-09-22T00:00:00Z"})
    # An empty declared set refuses everything (B12, named).
    empty = _writer(tmp_path / "empty", formats=frozenset())
    asyncio.run(_append(empty, "cap-2", [b"data"]))
    with pytest.raises(ValueError, match=r"declared set \[\]"):
        _finalise(empty, "cap-2", {"format": "csv", "started_at": "2026-09-22T00:00:00Z"})


def test_a_declared_extension_format_publishes_with_its_extension(
    tmp_path: Path,
) -> None:
    known = _writer(tmp_path / "csv", formats=frozenset({"csv"}))
    asyncio.run(_append(known, "cap-csv", [b"a,b\n1,2\n"]))
    _finalise(known, "cap-csv", {"format": "csv", "started_at": "2026-09-22T00:00:00Z"})
    assert (tmp_path / "csv" / "captures" / "cap-csv" / "cap-csv.csv").exists()
    unknown = _writer(tmp_path / "custom", formats=frozenset({"custom-format"}))
    asyncio.run(_append(unknown, "cap-x", [b"z"]))
    _finalise(
        unknown, "cap-x", {"format": "custom-format", "started_at": "2026-09-22T00:00:00Z"}
    )
    assert (tmp_path / "custom" / "captures" / "cap-x" / "cap-x.data").exists()


def test_finalise_requires_the_mandatory_waveform_metadata(tmp_path: Path) -> None:
    """Derived from ``$defs/captureManifest``'s allOf: sample_count,
    sample_interval_s and unit are REQUIRED when format == waveform_f64le."""
    for missing in ("sample_count", "sample_interval_s", "unit"):
        writer = _writer(tmp_path / missing)
        asyncio.run(_append(writer, "cap-1", [b"\x00" * 8]))
        metadata = dict(_WAVEFORM)
        del metadata[missing]
        with pytest.raises(ValueError, match=missing):
            _finalise(writer, "cap-1", metadata)


def test_zero_byte_publication_is_refused_in_both_modes(tmp_path: Path) -> None:
    """B11 parity: an adapter that appends nothing and finalises is refused —
    the same adapter behavior the gateway's zero-byte finalise refusal pins —
    and nothing is published (no primary, no manifest)."""
    writer = _writer(tmp_path)
    with pytest.raises(ValueError):
        _finalise(writer, "cap-empty", dict(_WAVEFORM))
    event = tmp_path / "captures" / "cap-empty"
    assert not event.exists()


def test_finalise_refuses_unknown_metadata_keys_and_foreign_ids(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path)
    asyncio.run(_append(writer, "cap-1", [b"data"]))
    with pytest.raises(ValueError, match="unknown finalise metadata keys"):
        _finalise(writer, "cap-1", dict(_WAVEFORM, extra_field="x"))
    with pytest.raises(ValueError, match="no open capture"):
        _finalise(writer, "cap-foreign", dict(_WAVEFORM))


def test_finalise_removes_staging_and_marks_the_event_published(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    asyncio.run(_append(writer, "cap-1", [b"\x00" * 8]))
    _finalise(writer, "cap-1", dict(_WAVEFORM))
    event = tmp_path / "captures" / "cap-1"
    assert not (event / "staging").exists()
    # The publication marker is manifest presence (B13).
    assert (event / "manifest.json").exists()


def test_abort_leaves_zero_chunk_residue_and_no_publication(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    asyncio.run(_append(writer, "cap-1", [b"one", b"two"]))
    asyncio.run(writer.artifact_abort("cap-1"))
    event = tmp_path / "captures" / "cap-1"
    assert not (event / "staging").exists()
    assert not any(event.glob("cap-1.*"))
    assert not (event / "manifest.json").exists()


def test_abort_is_a_no_op_retract_after_finalise(tmp_path: Path) -> None:
    """R9: an unconditional post-finalise ``artifact_abort`` (the adapter's
    ``finally`` idiom) must NOT delete the published artifact or the user's
    renderings."""
    writer = _writer(tmp_path)
    asyncio.run(_append(writer, "cap-1", [b"\x00" * 8]))
    _finalise(writer, "cap-1", dict(_WAVEFORM))
    event = tmp_path / "captures" / "cap-1"
    renderings = event / "renderings"
    renderings.mkdir()
    (renderings / "plot.svg").write_bytes(b"<svg/>")
    asyncio.run(writer.artifact_abort("cap-1"))
    assert (event / "cap-1.f64").exists()
    assert (event / "manifest.json").exists()
    assert (renderings / "plot.svg").exists()


def test_abort_for_an_id_this_writer_never_opened_is_a_no_op(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    asyncio.run(writer.artifact_abort("never-opened"))
    assert not (tmp_path / "captures").exists()


def test_appends_after_terminal_are_refused(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    asyncio.run(_append(writer, "cap-1", [b"\x00" * 8]))
    _finalise(writer, "cap-1", dict(_WAVEFORM))
    with pytest.raises(ValueError, match="appends after terminal are refused"):
        asyncio.run(writer.artifact_append("cap-1", b"more", Context()))
    aborted = _writer(tmp_path / "other")
    asyncio.run(_append(aborted, "cap-2", [b"data"]))
    asyncio.run(aborted.artifact_abort("cap-2"))
    with pytest.raises(ValueError, match="appends after terminal are refused"):
        asyncio.run(aborted.artifact_append("cap-2", b"more", Context()))


def test_second_finalise_after_terminal_is_refused(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    asyncio.run(_append(writer, "cap-1", [b"\x00" * 8]))
    _finalise(writer, "cap-1", dict(_WAVEFORM))
    with pytest.raises(ValueError, match="closed"):
        _finalise(writer, "cap-1", dict(_WAVEFORM))


def test_a_crash_across_finalise_never_leaves_a_half_written_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B13's crash shape: the primary is written atomically (temp + rename in
    the same directory). A process death between the rename and the manifest
    write leaves a COMPLETE primary and no manifest — the event is not
    published (manifest presence is the marker); stale-``.tmp`` residue
    cleanup is deferred to the runner scope and named, not silently claimed."""
    writer = _writer(tmp_path)
    chunks = [b"\x00" * 8, b"\x01" * 8]
    asyncio.run(_append(writer, "cap-1", chunks))

    def exploding_manifest(event: Path, manifest: dict[str, Any]) -> None:
        raise RuntimeError("simulated crash before manifest write")

    monkeypatch.setattr(capture, "_write_manifest", exploding_manifest)
    with pytest.raises(RuntimeError, match="simulated crash"):
        _finalise(writer, "cap-1", dict(_WAVEFORM))
    event = tmp_path / "captures" / "cap-1"
    assert (event / "cap-1.f64").read_bytes() == b"".join(chunks)  # complete
    assert not (event / "manifest.json").exists()  # not published


# --- S4: the honest docstring and the compatibility sentence -------------------


def test_capture_services_docstring_names_the_writer_and_its_true_size() -> None:
    """The B14 honest 3-of-8 wording: the protocol's own docstring must name
    the standalone writer as the first implementation of the three capture
    methods and say the full eight-member protocol awaits a composing
    runtime — not "nothing implements this protocol yet"."""
    import inspect

    from benchweave_sdk.interfaces import CaptureServices

    doc = inspect.getdoc(CaptureServices) or ""
    assert "StandaloneCaptureWriter" in doc
    assert "Nothing in this SDK or in the gateway implements" not in doc


def test_user_guide_compatibility_sentence_covers_capture() -> None:
    """S-F3: BOTH compatibility surfaces (user_guide/plugin-sdk.qmd §4 and
    README.md's 'Compatibility and limits') must not claim capture is
    unsupported once the capture slice lands; streaming and profile
    actions stay unsupported. The guard sweeps the whole README too, so a
    regressed sentence ANYWHERE in either file fails the pin."""
    repo = Path(__file__).resolve().parents[1]
    guide = (repo / "user_guide" / "plugin-sdk.qmd").read_text(encoding="utf-8")
    readme = (repo / "README.md").read_text(encoding="utf-8")
    for surface, text in (("guide", guide), ("readme", readme)):
        assert "capture and streaming remain unsupported" not in text, surface
        assert "capture and streaming are not implemented" not in text, surface
        assert "single-channel capture" in text, surface
        # Streaming stays named as not implemented (each surface's own
        # wording: the guide says "remain unsupported", the README says
        # "not implemented").
        assert "streaming" in text, surface
    assert "streaming remain unsupported" in guide
    assert "streaming are not implemented" in readme




# --- S-F1: a finalise failure after staging removal must not wedge the writer


def test_a_manifest_write_failure_keeps_the_retry_path_alive(tmp_path):
    """The SDK-lane refutation F1: staging removal ran BEFORE the manifest
    write, so a manifest-write I/O failure (ENOSPC mid-capture is an
    ordinary bench event) left a complete primary + no staging + a writer
    still open — and both natural recoveries raised raw FileNotFoundError,
    off the mirrored §8 contract. FIX OPTION CHOSEN: staging teardown moves
    AFTER the manifest write (the publication marker), so the failed
    finalise leaves the capture fully retryable; a typed guard at concat
    entry covers the externally-mangled shape. Retries must never raise a
    bare OSError and must never destroy the complete primary."""
    writer = _writer(tmp_path)
    chunks = [b"\x01" * 8, b"\x02" * 8]
    asyncio.run(_append(writer, "cap-1", chunks))

    def failing_manifest(event: Path, manifest: dict) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch_manifest = failing_manifest
    original = capture._write_manifest
    capture._write_manifest = monkeypatch_manifest  # type: ignore[assignment]
    try:
        with pytest.raises(OSError, match="No space"):
            _finalise(writer, "cap-1", dict(_WAVEFORM, sample_count=2))
    finally:
        capture._write_manifest = original  # type: ignore[assignment]
    event = tmp_path / "captures" / "cap-1"
    assert (event / "cap-1.f64").read_bytes() == b"".join(chunks)  # complete
    assert (event / "staging").is_dir()  # the retry path is intact
    assert not (event / "manifest.json").exists()  # not published
    assert writer._terminal is None  # still open, not wedged
    # Natural recovery A: retry finalise — no bare FileNotFoundError.
    manifest = _finalise(writer, "cap-1", dict(_WAVEFORM, sample_count=2))
    assert manifest["sha256"] == __import__("hashlib").sha256(b"".join(chunks)).hexdigest()
    assert (event / "manifest.json").exists()
    assert not (event / "staging").exists()  # success tears staging down


def test_a_crashed_finalise_leaves_staging_for_the_retry(tmp_path, monkeypatch):
    """The crash-window shape (the landed crash test's sibling): a process
    death between the primary rename and the manifest write now leaves the
    complete primary AND staging (the retry path) — coherent with the
    reordering, and the residue-cleanup deferral to the runner is
    unchanged (a successful retry leaves no residue)."""
    writer = _writer(tmp_path)
    chunks = [b"\x01" * 8]
    asyncio.run(_append(writer, "cap-1", chunks))

    def exploding_manifest(event: Path, manifest: dict) -> None:
        raise RuntimeError("simulated crash before manifest write")

    monkeypatch.setattr(capture, "_write_manifest", exploding_manifest)
    with pytest.raises(RuntimeError, match="simulated crash"):
        _finalise(writer, "cap-1", dict(_WAVEFORM, sample_count=1))
    event = tmp_path / "captures" / "cap-1"
    assert (event / "cap-1.f64").read_bytes() == b"".join(chunks)  # complete
    assert not (event / "manifest.json").exists()  # not published
    assert (event / "staging").is_dir()  # the retry path survives the crash


def test_append_then_finalise_after_a_failed_finalise_recovers(tmp_path):
    """The refuter's recovery B: append-then-finalise after the failure —
    must succeed (or refuse with a contract ValueError), never raise a
    bare FileNotFoundError from the concat loop."""
    writer = _writer(tmp_path)
    asyncio.run(_append(writer, "cap-1", [b"\x01" * 8]))

    def failing_manifest(event: Path, manifest: dict) -> None:
        raise OSError(28, "No space left on device")

    original = capture._write_manifest
    capture._write_manifest = failing_manifest  # type: ignore[assignment]
    try:
        with pytest.raises(OSError, match="No space"):
            _finalise(writer, "cap-1", dict(_WAVEFORM, sample_count=1))
    finally:
        capture._write_manifest = original  # type: ignore[assignment]
    asyncio.run(_append(writer, "cap-1", [b"\x02" * 8]))
    manifest = _finalise(writer, "cap-1", dict(_WAVEFORM, sample_count=2))
    assert manifest["byte_length"] == 16


# --- S-F2: the published manifest must be strict JSON --------------------------------


def test_an_infinite_interval_is_refused_and_every_manifest_is_strict_json(
    tmp_path,
):
    """The SDK-lane refutation F2: sample_interval_s=+inf passed the >0
    gate and json.dumps' default wrote the bare token Infinity — RFC-8259
    ILLEGAL, so jq and every strict parser refuse the whole file while a
    Python consumer round-trips it blind. The interval gate now requires
    finiteness AND the manifest dump carries allow_nan=False (the
    structural seam — no non-finite float can reach the file)."""
    writer = _writer(tmp_path)
    asyncio.run(_append(writer, "cap-1", [b"\x01" * 8]))
    with pytest.raises(ValueError, match="finite"):
        _finalise(
            writer,
            "cap-1",
            dict(_WAVEFORM, sample_count=1, sample_interval_s=float("inf")),
        )

    def refuse_constants(token: str) -> None:
        raise AssertionError(f"non-strict JSON token {token!r} in manifest")

    writer2 = _writer(tmp_path / "two")
    asyncio.run(_append(writer2, "cap-2", [b"\x01" * 8]))
    _finalise(writer2, "cap-2", dict(_WAVEFORM, sample_count=1))
    import json as json_module

    published = (tmp_path / "two" / "captures" / "cap-2" / "manifest.json").read_text()
    assert "Infinity" not in published and "NaN" not in published
    json_module.loads(published, parse_constant=refuse_constants)  # strict re-parse


# --- S-F4: the declared-format constructor argument is type-validated --------


def test_a_bare_string_formats_argument_is_refused_naming_the_fix(tmp_path):
    """The SDK-lane refutation F4: formats="csv" char-split into
    {'c','s','v'} and silently refused the format the caller declared.
    CHOICE (disclosed): a bare string is REFUSED at construction — a
    plural parameter taking a string is always a mistake, and wrapping it
    would hide it."""
    with pytest.raises(ValueError, match="set or iterable of format names"):
        capture.StandaloneCaptureWriter(tmp_path / "captures", formats="csv")


def test_non_string_format_elements_are_refused_naming_the_value(tmp_path):
    with pytest.raises(ValueError, match="3"):
        capture.StandaloneCaptureWriter(
            tmp_path / "captures", formats=["csv", 3]
        )
    with pytest.raises(ValueError, match="None"):
        capture.StandaloneCaptureWriter(
            tmp_path / "captures", formats=frozenset({"csv", None})
        )


# --- S-F5: started_at is validated against the corpus date-time annotation ------


def test_an_unparseable_started_at_is_refused(tmp_path):
    """The SDK-lane refutation F5: the corpus annotates started_at
    {"format": "date-time"} but the writer checked non-emptiness only —
    and bare jsonschema.validate is structurally blind to format
    annotations, so a manifest could satisfy the R9 machine check while
    violating the annotated contract."""
    writer = _writer(tmp_path)
    asyncio.run(_append(writer, "cap-1", [b"\x01" * 8]))
    with pytest.raises(ValueError, match="RFC 3339"):
        _finalise(writer, "cap-1", dict(_WAVEFORM, sample_count=1, started_at="banana"))
    # The refused finalise left the capture retryable (S-F1's ordering).
    manifest = _finalise(writer, "cap-1", dict(_WAVEFORM, sample_count=1))
    assert manifest["started_at"] == "2026-09-22T00:00:00Z"


def test_started_at_accepts_the_rfc3339_shapes_the_stdlib_parses(tmp_path):
    """The validation bound (disclosed): datetime.fromisoformat is the
    validator — Python 3.13 parses RFC 3339 date-times including the Z
    suffix and numeric offsets; the corpus's exact grammar is approximated
    by the stdlib (a full RFC 3339 validator is already a runtime
    dependency if the runner ever needs the stricter form)."""
    writer = _writer(tmp_path)
    asyncio.run(_append(writer, "cap-1", [b"\x01" * 8]))
    manifest = _finalise(
        writer,
        "cap-1",
        dict(
            _WAVEFORM,
            sample_count=1,
            started_at="2026-09-22T00:00:00+08:00",
        ),
    )
    assert manifest["started_at"] == "2026-09-22T00:00:00+08:00"
