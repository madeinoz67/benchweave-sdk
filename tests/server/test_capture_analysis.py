"""I4b.1 AR-8: the A-Z markers overlay and the ``capture_analysis`` row.

The overlay is ``analysis.json`` per event directory (format
``standalone-analysis/1``): operator annotation only, never the only copy
of anything (SW-50 — the copy of record is the root, the index gains no
column), removed with its capture exactly like ``metadata.json``, and
rewritten atomically (temp write + ``os.replace``, the ``_write_metadata``
precedent). The catalogue row's admission is ``_stale_row_refusal`` (the
``capture_annotate`` shape); the echo is the stored rows — operator
annotations are input, not processed values (#423's boundary holds).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import struct
from pathlib import Path

import pytest

from benchweave_sdk_server.analysis import read_markers, resolve_markers
from benchweave_sdk_server.errors import SeamError
from benchweave_sdk_server.seam import StandaloneSeam


def write_capture(root: Path, capture_id: str, *, values: tuple[float, ...]) -> Path:
    payload = b"".join(struct.pack("<d", value) for value in values)
    event = root / capture_id
    event.mkdir(parents=True)
    (event / f"{capture_id}.f64").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (event / "manifest.json").write_text(
        json.dumps(
            {
                "capture_id": capture_id,
                "format": "waveform_f64le",
                "artifact_id": "art-" + digest,
                "byte_length": len(payload),
                "sha256": digest,
                "started_at": f"2026-10-08T09:00:00+00:00-{capture_id}",
                "sample_count": len(values),
                "sample_interval_s": 1.0,
                "unit": "V",
            },
            sort_keys=True,
        )
    )
    (event / "metadata.json").write_text(
        json.dumps(
            {
                "capture_id": capture_id,
                "device": {"id": "fx-device", "firmware": "1.0.0"},
                "plugin": {"package": "fx-plugin", "version": "0.1.0",
                           "descriptor_sha256": "d" * 64},
                "surface": "rest",
                "operator": "fx-op",
                "tags": [],
                "notes": "",
            },
            sort_keys=True,
        )
    )
    return event


def call(seam: StandaloneSeam, operation: str, arguments: dict) -> dict:
    return asyncio.run(seam.call(operation, arguments))


@pytest.fixture()
def marker_seam(plugin, tmp_path: Path) -> StandaloneSeam:
    from benchweave_sdk_server.session import mock_plugin_session

    return StandaloneSeam(
        mock_plugin_session(plugin),
        transport_kind="mock",
        capture_root=tmp_path / "captures",
    )


def _rows(*spec: tuple[str, float, str]) -> list[dict]:
    return [{"label": label, "t": t, "note": note} for label, t, note in spec]


def test_save_reload_round_trip_preserves_rows_sorted(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    root = tmp_path / "captures"
    write_capture(root, "fx-marker-a", values=(1.0,) * 3)
    result = call(
        marker_seam,
        "capture_analysis",
        {
            "capture_id": "fx-marker-a",
            "markers": _rows(("B", 1.0, "second"), ("A", 0.0, "first")),
        },
    )
    # Stored sorted by label; the echo is the stored rows.
    assert [row["label"] for row in result["markers"]] == ["A", "B"]
    overlay = json.loads((root / "fx-marker-a" / "analysis.json").read_text())
    assert overlay["format"] == "standalone-analysis/1"
    assert overlay["markers"] == _rows(("A", 0.0, "first"), ("B", 1.0, "second"))
    assert read_markers(root / "fx-marker-a") == _rows(
        ("A", 0.0, "first"), ("B", 1.0, "second")
    )


def test_replace_on_duplicate_keeps_one_row_with_the_second_t(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    root = tmp_path / "captures"
    write_capture(root, "fx-marker-dup", values=(1.0,) * 3)
    result = call(
        marker_seam,
        "capture_analysis",
        {
            "capture_id": "fx-marker-dup",
            "markers": _rows(("A", 0.0, "first"), ("A", 1.0, "second")),
        },
    )
    assert result["markers"] == _rows(("A", 1.0, "second"))


def test_label_refusals_are_typed(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    root = tmp_path / "captures"
    write_capture(root, "fx-marker-label", values=(1.0,) * 3)
    for bad in ("AA", "a", "", "1", "é"):
        with pytest.raises(SeamError) as caught:
            call(
                marker_seam,
                "capture_analysis",
                {"capture_id": "fx-marker-label", "markers": _rows((bad, 0.0, ""))},
            )
        assert caught.value.code == "invalid_request"
        assert "standalone_report_marker_invalid" in caught.value.message


def test_t_refusals_non_finite_and_out_of_bounds(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    root = tmp_path / "captures"
    # 3 samples at 1 s: the displayable time base is [0.0, 2.0].
    write_capture(root, "fx-marker-t", values=(1.0,) * 3)
    for bad in (float("nan"), float("inf"), -0.5, 2.5):
        with pytest.raises(SeamError) as caught:
            call(
                marker_seam,
                "capture_analysis",
                {
                    "capture_id": "fx-marker-t",
                    "markers": [{"label": "A", "t": bad, "note": ""}],
                },
            )
        assert caught.value.code == "invalid_request"
        assert "standalone_report_marker_invalid" in caught.value.message
    # The bounds themselves are admissible (inclusive).
    ok = call(
        marker_seam,
        "capture_analysis",
        {
            "capture_id": "fx-marker-t",
            "markers": _rows(("A", 0.0, ""), ("Z", 2.0, "")),
        },
    )
    assert len(ok["markers"]) == 2


def test_one_overlay_per_call_markers_with_notes_refuses(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    root = tmp_path / "captures"
    write_capture(root, "fx-marker-mix", values=(1.0,) * 3)
    with pytest.raises(SeamError) as caught:
        call(
            marker_seam,
            "capture_analysis",
            {
                "capture_id": "fx-marker-mix",
                "markers": _rows(("A", 0.0, "")),
                "notes": "both overlays in one call",
            },
        )
    assert caught.value.code == "invalid_request"


def test_absent_or_invalid_overlay_reads_as_no_markers(tmp_path: Path) -> None:
    event = write_capture(tmp_path, "fx-marker-read", values=(1.0,) * 3)
    assert read_markers(event) == []
    (event / "analysis.json").write_text("{not json")
    assert read_markers(event) == []
    (event / "analysis.json").write_text('{"markers": "not a list"}')
    assert read_markers(event) == []
    (event / "analysis.json").write_text('{"format": "standalone-analysis/1"}')
    assert read_markers(event) == []


def test_unknown_capture_refuses_not_found(marker_seam: StandaloneSeam) -> None:
    with pytest.raises(SeamError) as caught:
        call(
            marker_seam,
            "capture_analysis",
            {"capture_id": "fx-marker-none", "markers": _rows(("A", 0.0, ""))},
        )
    assert caught.value.code == "not_found"


def test_stale_row_refuses_and_self_heals(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    root = tmp_path / "captures"
    write_capture(root, "fx-marker-stale", values=(1.0,) * 3)
    # Construct the library index (first call), then delete the event
    # directory out of band: the stale row must refuse closed.
    call(marker_seam, "capture_list", {})
    import shutil

    shutil.rmtree(root / "fx-marker-stale")
    with pytest.raises(SeamError) as caught:
        call(
            marker_seam,
            "capture_analysis",
            {"capture_id": "fx-marker-stale", "markers": _rows(("A", 0.0, ""))},
        )
    assert caught.value.code == "not_found"


def test_the_rewrite_is_atomic_no_tmp_and_valid_json(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    root = tmp_path / "captures"
    event = write_capture(root, "fx-marker-atomic", values=(1.0,) * 3)
    for round_index in range(3):
        call(
            marker_seam,
            "capture_analysis",
            {
                "capture_id": "fx-marker-atomic",
                "markers": _rows((chr(ord("A") + round_index), 0.5, f"note {round_index}")),
            },
        )
        assert not list(event.glob("*.tmp")), "no temp file may survive the write"
        json.loads((event / "analysis.json").read_text())  # valid JSON every time


def test_capture_delete_takes_the_overlay_with_it(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    root = tmp_path / "captures"
    write_capture(root, "fx-marker-gone", values=(1.0,) * 3)
    call(
        marker_seam,
        "capture_analysis",
        {"capture_id": "fx-marker-gone", "markers": _rows(("A", 0.0, "kept in report"))},
    )
    assert (root / "fx-marker-gone" / "analysis.json").is_file()
    call(marker_seam, "capture_delete", {"capture_id": "fx-marker-gone"})
    assert not (root / "fx-marker-gone").exists()


def test_resolve_markers_sorts_and_replaces_against_the_manifest(
    tmp_path: Path,
) -> None:
    manifest = {"sample_count": 5, "sample_interval_s": 0.5}
    rows = resolve_markers(
        manifest,
        [{"label": "B", "t": 0.5, "note": "b"}, {"label": "A", "t": 0.0},
         {"label": "B", "t": 1.0, "note": "second b"}],
    )
    assert rows == [
        {"label": "A", "t": 0.0, "note": ""},
        {"label": "B", "t": 1.0, "note": "second b"},
    ]
    with pytest.raises(ValueError, match="standalone_report_marker_invalid"):
        resolve_markers(manifest, [{"label": "A", "t": 2.1, "note": ""}])
    with pytest.raises(ValueError, match="standalone_report_marker_invalid"):
        resolve_markers(manifest, [{"label": "A", "t": math.nan, "note": ""}])


def test_marker_note_with_markup_survives_the_write_verbatim(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    """The note is free text at rest (the annotate precedent): escaping
    happens at RENDER time, so the overlay stores the operator's bytes
    verbatim — the report's escaped rendering is AR-9a's arm."""
    root = tmp_path / "captures"
    write_capture(root, "fx-marker-note", values=(1.0,) * 3)
    hostile = "<script>alert('x')</script> {{7*7}}"
    result = call(
        marker_seam,
        "capture_analysis",
        {"capture_id": "fx-marker-note", "markers": [{"label": "A", "t": 0.0, "note": hostile}]},
    )
    assert result["markers"][0]["note"] == hostile
    overlay = json.loads((root / "fx-marker-note" / "analysis.json").read_text())
    assert overlay["markers"][0]["note"] == hostile
