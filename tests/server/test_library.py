"""I3b slice 2: the rebuildable capture index over the capture root.

The design record's mechanism: a stdlib ``sqlite3`` index (the fork's
``library.py`` name, deliberately), rebuilt at startup by walking the root
(manifest.json + metadata.json per event), query acceleration only — never
the only copy of anything. Pin state lives in metadata.json (AR-6's RED
arm: the FILE is authoritative). A lockfile in the root refuses a second
host process over the same root (the two-writers hazard).
"""

from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path

import pytest

from benchweave_sdk_server.library import CaptureLibrary, _pid_is_dead

# --- the on-disk shape the writer + host publish (the rebuild's source) ---


def write_capture(
    root: Path,
    capture_id: str,
    *,
    samples: tuple[float, ...] = (1.0, -2.0, 3.0),
    interval: float = 0.001,
    unit: str = "V",
    pinned: bool = False,
    strip_pinned: bool = False,
    tags: list[str] | None = None,
    notes: str = "",
    surface: str | None = "rest",
    project: str | None = None,
    operator: str = "benchop",
    stop_reason: str | None = "completed",
) -> Path:
    """Publish one event directory exactly as the writer + host do."""
    started = f"2026-10-04T10:00:00+00:00-{capture_id}"
    payload = b"".join(struct.pack("<d", value) for value in samples)
    event = root / capture_id
    event.mkdir()
    (event / f"{capture_id}.f64").write_bytes(payload)
    digest = __import__("hashlib").sha256(payload).hexdigest()
    manifest = {
        "capture_id": capture_id,
        "format": "waveform_f64le",
        "artifact_id": "art-" + digest,
        "byte_length": len(payload),
        "sha256": digest,
        "started_at": started,
        "sample_count": len(samples),
        "sample_interval_s": interval,
        "unit": unit,
        "x-standalone-state": "finalised",
        "x-standalone-manifest-version": 1,
    }
    (event / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    meta = {
        "capture_id": capture_id,
        "device": {"id": "example_device", "firmware": "1.0.0"},
        "plugin": {"package": "example_plugin", "version": "0.1.0"},
        "surface": surface,
        "operator": operator,
        "project": project,
        "tags": tags or [],
        "notes": notes,
        "config": {},
        "declared": {"format": "waveform_f64le", "bound": {"count": len(samples)}},
        "at": started,
        "pinned": pinned,
        "stop_reason": stop_reason,
    }
    if strip_pinned:
        del meta["pinned"]
    (event / "metadata.json").write_text(json.dumps(meta, sort_keys=True))
    return event


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    return tmp_path / "captures"


# --- the lockfile ---------------------------------------------------------


def test_lockfile_refuses_a_second_library(root: Path) -> None:
    """The record's falsifier: two library objects over one root — the
    second refuses."""
    root.mkdir()
    first = CaptureLibrary(root)
    try:
        with pytest.raises(RuntimeError) as caught:
            CaptureLibrary(root)
        assert "standalone_library_locked" in str(caught.value)
    finally:
        first.close()


def test_close_releases_the_lock(root: Path) -> None:
    root.mkdir()
    first = CaptureLibrary(root)
    first.close()
    second = CaptureLibrary(root)  # must not raise
    second.close()


def test_stale_lock_from_a_dead_process_is_stolen(root: Path) -> None:
    """A crashed host's lockfile must not wedge the root forever: a lock
    whose pid is provably gone is stolen."""
    root.mkdir()
    lock = root / "library.lock"
    lock.write_text(json.dumps({"pid": _dead_pid()}))
    library = CaptureLibrary(root)  # must not raise
    library.close()


def _dead_pid() -> int:
    """A pid that is not this process and holds no live process here —
    found with the library's own portable probe (the same liveness rule
    the lock steal runs, so the arm cannot diverge from the mechanism:
    ``os.kill(pid, 0)`` is refused outright on Windows, WinError 87)."""
    pid = os.getpid() - 1
    while pid > 1:
        if _pid_is_dead(pid):
            return pid
        pid -= 1
    raise RuntimeError("no dead pid found to test the stale-lock path")


def test_the_windows_probe_branch_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """ROW-3: the Windows liveness mapping, pinned against a mocked kernel
    seam — macOS cannot run the real branch, so this arm is the local proxy
    and CI's Windows leg is the live proof (the W1 posture). A handle is a
    live pid; a 0 handle with ERROR_INVALID_PARAMETER (87) is a pid the
    kernel does not know — provably dead, the lock is stolen; any other
    failure is unprovable — conservative refuse."""
    from benchweave_sdk_server import library

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        "benchweave_sdk_server.library._windows_process_probe", lambda pid: (0, 87)
    )
    assert library._pid_is_dead(4242) is True
    monkeypatch.setattr(
        "benchweave_sdk_server.library._windows_process_probe",
        lambda pid: (0x1A2B, 0),
    )
    assert library._pid_is_dead(4242) is False
    monkeypatch.setattr(
        "benchweave_sdk_server.library._windows_process_probe", lambda pid: (0, 5)
    )
    assert library._pid_is_dead(4242) is False


def test_lockfile_records_the_owner_pid(root: Path) -> None:
    root.mkdir()
    library = CaptureLibrary(root)
    try:
        payload = json.loads((root / "library.lock").read_text())
        assert payload["pid"] == os.getpid()
    finally:
        library.close()


# --- the rebuild (AR-6) ----------------------------------------------------


def test_rebuild_is_identical_after_deleting_the_index(root: Path) -> None:
    """AR-6: a capture set with mixed pins/tags/notes; delete the SQLite
    file; the rebuilt list state is identical."""
    root.mkdir()
    write_capture(root, "cap-a", pinned=True, tags=["heat"], notes="keep me")
    write_capture(root, "cap-b", project="proj-1", surface="mcp")
    write_capture(root, "cap-c", notes="c notes", tags=["x", "y"])
    library = CaptureLibrary(root)
    try:
        before = library.list_captures()
    finally:
        library.close()
    assert len(before) == 3
    (root / "library.sqlite3").unlink()
    library = CaptureLibrary(root)
    try:
        after = library.list_captures()
    finally:
        library.close()
    assert before == after


def test_metadata_json_is_the_pin_authority(root: Path) -> None:
    """AR-6's RED arm: hand-strip ``pinned`` from one metadata.json — the
    rebuild reports that capture unpinned (the file, not the index, is
    authoritative)."""
    root.mkdir()
    write_capture(root, "cap-pinned", pinned=True)
    write_capture(root, "cap-stripped", pinned=True, strip_pinned=True)
    library = CaptureLibrary(root)
    try:
        rows = {row["capture_id"]: row for row in library.list_captures()}
        assert rows["cap-pinned"]["pinned"] is True
        assert rows["cap-stripped"]["pinned"] is False
    finally:
        library.close()


def test_missing_metadata_defaults_honest(root: Path) -> None:
    """An event published by the bare writer (no metadata.json) still
    indexes; the absent fields take their honest defaults."""
    root.mkdir()
    event = write_capture(root, "cap-bare")
    (event / "metadata.json").unlink()
    library = CaptureLibrary(root)
    try:
        row = library.get("cap-bare")
        assert row is not None
        assert row["pinned"] is False
        assert row["tags"] == []
        assert row["notes"] == ""
        assert row["surface"] is None
        assert row["project"] is None
        assert row["stop_reason"] is None
    finally:
        library.close()


def test_manifest_only_events_are_what_the_rebuild_reads(root: Path) -> None:
    """Directories without a published manifest are not captures (staging
    orphans belong to I3c's sweep) and files in the root are not events."""
    root.mkdir()
    write_capture(root, "cap-real")
    orphan = root / "cap-orphan"
    orphan.mkdir()
    (orphan / "staging").mkdir()
    (root / "retention.log").write_text("")
    library = CaptureLibrary(root)
    try:
        assert [row["capture_id"] for row in library.list_captures()] == ["cap-real"]
    finally:
        library.close()


# --- the runtime row maintenance (the lifecycle slice's interface) ---------


def test_record_update_and_remove_round_trip(root: Path) -> None:
    root.mkdir()
    write_capture(root, "cap-a")
    library = CaptureLibrary(root)
    try:
        library.set_pinned("cap-a", True)
        assert library.get("cap-a")["pinned"] is True
        library.update_annotation("cap-a", notes="new", tags=["t1"])
        row = library.get("cap-a")
        assert row["notes"] == "new"
        assert row["tags"] == ["t1"]
        # The annotation lands in metadata.json too (the file is the
        # authority — an index edit alone would be lost on rebuild).
        meta = json.loads((root / "cap-a" / "metadata.json").read_text())
        assert meta["notes"] == "new"
        assert meta["tags"] == ["t1"]
        library.remove("cap-a")
        assert library.get("cap-a") is None
    finally:
        library.close()


def test_rows_carry_the_recorded_columns(root: Path) -> None:
    """The record's column set (plus the disclosed stop_reason)."""
    root.mkdir()
    write_capture(root, "cap-a", project="p", tags=["t"], stop_reason="completed")
    library = CaptureLibrary(root)
    try:
        row = library.get("cap-a")
        assert set(row) == {
            "capture_id", "started_at", "format", "byte_length", "sha256",
            "surface", "operator", "project", "pinned", "tags", "notes",
            "stop_reason",
        }
    finally:
        library.close()


def test_corrupt_event_directory_is_skipped_not_fatal(root: Path) -> None:
    """A mangled event (unparseable manifest) must not wedge the whole
    index: it is skipped, and the skip is visible to the operator."""
    root.mkdir()
    write_capture(root, "cap-good")
    bad = write_capture(root, "cap-bad")
    (bad / "manifest.json").write_text("{not json")
    library = CaptureLibrary(root)
    try:
        assert [row["capture_id"] for row in library.list_captures()] == ["cap-good"]
    finally:
        library.close()


def test_uncoercible_field_skips_the_row_not_the_index(root: Path) -> None:
    """A-F3 (L7 shape): a VALID-JSON manifest whose byte_length is
    uncoercible ("12x") skips that row — the constructor must not escape,
    wedging every capture op on the root until manual deletion."""
    root.mkdir()
    write_capture(root, "cap-good")
    bad = write_capture(root, "cap-wedge")
    manifest = json.loads((bad / "manifest.json").read_text())
    manifest["byte_length"] = "12x"
    (bad / "manifest.json").write_text(json.dumps(manifest))
    library = CaptureLibrary(root)
    try:
        assert [row["capture_id"] for row in library.list_captures()] == [
            "cap-good"
        ]
    finally:
        library.close()


def test_null_capture_id_publishes_no_row_named_none(root: Path) -> None:
    """A-F4 (L7b shape): a manifest whose capture_id is null publishes no
    row — the index must never serve a capture named "None"."""
    root.mkdir()
    write_capture(root, "cap-good")
    bad = write_capture(root, "cap-null")
    manifest = json.loads((bad / "manifest.json").read_text())
    manifest["capture_id"] = None
    (bad / "manifest.json").write_text(json.dumps(manifest))
    library = CaptureLibrary(root)
    try:
        assert [row["capture_id"] for row in library.list_captures()] == [
            "cap-good"
        ]
    finally:
        library.close()


def test_sqlite_file_is_not_an_event(root: Path) -> None:
    root.mkdir()
    write_capture(root, "cap-a")
    library = CaptureLibrary(root)
    library.close()
    library = CaptureLibrary(root)  # rebuild over its own database file
    try:
        assert [row["capture_id"] for row in library.list_captures()] == ["cap-a"]
    finally:
        library.close()


# --- the datasets family (issue #589 PR-3, §2a of the design record) ------------


def write_dataset(
    root: Path,
    dataset_id: str,
    *,
    kind: str = "scalar_set",
    status: str = "complete",
    action_id: str | None = "demo.probe/1.0.0",
    started_at: str | None = None,
    surface: str | None = "rest",
    operator: str = "benchop",
    project: str | None = None,
) -> Path:
    """Publish one dataset event directory exactly as the admission core
    does: ``datasets/<segment>/manifest.json`` (segment = the id with its
    single ``:`` replaced by ``-``) plus the ``metadata.json`` sidecar that
    carries the provenance and the action."""
    segment = dataset_id.replace(":", "-", 1)
    event = root / "datasets" / segment
    event.mkdir(parents=True)
    manifest = {
        "dataset_id": dataset_id,
        "kind": kind,
        "configuration_id": None,
        "acquisition_id": None,
        "started_at": started_at,
        "status": status,
        "context": {},
    }
    (event / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    metadata = {
        "dataset_id": dataset_id,
        "action_id": action_id,
        "surface": surface,
        "operator": operator,
        "project": project,
        "pinned": False,
        "tags": [],
        "notes": "",
    }
    (event / "metadata.json").write_text(json.dumps(metadata, sort_keys=True))
    return event


def test_record_dataset_and_rebuild_agree(root: Path) -> None:
    """AR-6 for the second family: the runtime insert and the rebuild walk
    produce the same row from the same files — the index is query
    acceleration, never the only copy. The row's sha256 is the canonical
    manifest digest, recomputed by both paths."""
    root.mkdir()
    dataset_id = "ds:op-library01"
    write_dataset(root, dataset_id)
    manifest = json.loads(
        (root / "datasets" / "ds-op-library01" / "manifest.json").read_text()
    )
    metadata = json.loads(
        (root / "datasets" / "ds-op-library01" / "metadata.json").read_text()
    )
    library = CaptureLibrary(root)
    try:
        library.record_dataset(dataset_id, manifest, metadata)
        assert len(library.list_datasets()) == 1
        row = library.list_datasets()[0]
    finally:
        library.close()
    # One library per root by design (the lockfile): the fresh library owns
    # the root only after the first released it.
    fresh = CaptureLibrary(root)
    try:
        rebuilt = fresh.list_datasets()[0]
    finally:
        fresh.close()
    assert row == rebuilt
    assert row["dataset_id"] == dataset_id
    assert row["kind"] == "scalar_set"
    assert row["status"] == "complete"
    assert row["action_id"] == "demo.probe/1.0.0"
    assert row["operator"] == "benchop"
    assert len(row["sha256"]) == 64


def test_get_dataset_serves_the_row_and_misses_unknown_ids(root: Path) -> None:
    root.mkdir()
    write_dataset(root, "ds:op-alpha0001")
    library = CaptureLibrary(root)
    try:
        assert library.get_dataset("ds:op-alpha0001") is not None
        assert library.get_dataset("ds:op-nothing01") is None
    finally:
        library.close()


def test_the_capture_walk_is_blind_to_the_datasets_family(root: Path) -> None:
    """The design record's §2a placement argument, pinned: a dataset
    manifest under ``datasets/`` is NOT a capture row (a top-level manifest
    would be indexed with format "" and byte_length 0 — a lie in a closed
    row)."""
    root.mkdir()
    write_capture(root, "cap-a")
    write_dataset(root, "ds:op-beside001")
    library = CaptureLibrary(root)
    try:
        assert [row["capture_id"] for row in library.list_captures()] == ["cap-a"]
        assert [row["dataset_id"] for row in library.list_datasets()] == [
            "ds:op-beside001"
        ]
    finally:
        library.close()


def test_a_forged_segment_directory_publishes_no_row_under_the_forged_id(
    root: Path,
) -> None:
    """The id-verified read: the row keys on the manifest's TRUE dataset_id,
    never on the directory name — a caller-supplied ``ds-op-…`` forgery
    finds the directory and refuses on the id check."""
    root.mkdir()
    # The directory claims one id; the manifest carries another.
    event = root / "datasets" / "ds-op-forged0001"
    event.mkdir(parents=True)
    (event / "manifest.json").write_text(
        json.dumps({"dataset_id": "ds:op-true0000001", "kind": "scalar_set",
                    "status": "complete"})
    )
    library = CaptureLibrary(root)
    try:
        assert library.get_dataset("ds:op-forged0001") is None
        assert library.get_dataset("ds:op-true0000001") is not None
    finally:
        library.close()
