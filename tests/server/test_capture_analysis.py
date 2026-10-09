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


# --- I4b.1 AR-9 (seam level): the export over markers and assertions ----------------


def test_export_reads_the_overlay_when_the_request_carries_no_markers(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    root = tmp_path / "captures"
    write_capture(root, "fx-exp-overlay", values=(1.0, 2.0, 3.0))
    call(
        marker_seam,
        "capture_analysis",
        {
            "capture_id": "fx-exp-overlay",
            "markers": _rows(("A", 1.0, "from the overlay")),
        },
    )
    result = call(marker_seam, "report_export", {"capture_ids": ["fx-exp-overlay"]})
    document = (root / "reports" / f"{result['report_id']}.html").read_text()
    assert "from the overlay" in document
    assert 'data-bw-marker="A"' in document


def test_export_request_markers_replace_the_overlay_for_that_export(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    root = tmp_path / "captures"
    write_capture(root, "fx-exp-rows", values=(1.0, 2.0, 3.0))
    call(
        marker_seam,
        "capture_analysis",
        {
            "capture_id": "fx-exp-rows",
            "markers": _rows(("A", 0.0, "stored"), ("B", 1.0, "stored b")),
        },
    )
    result = call(
        marker_seam,
        "report_export",
        {
            "capture_ids": ["fx-exp-rows"],
            "markers": [
                {"capture_id": "fx-exp-rows", "label": "A", "t": 2.0,
                 "note": "resolved"}
            ],
        },
    )
    document = (root / "reports" / f"{result['report_id']}.html").read_text()
    assert "resolved" in document
    assert "stored b" not in document  # request rows replace the overlay
    sidecar = json.loads(
        (root / "reports" / f"{result['report_id']}.json").read_text()
    )
    assert sidecar["params"]["markers"] == [
        {"capture_id": "fx-exp-rows", "label": "A", "t": 2.0, "note": "resolved"}
    ]


def test_export_with_assertions_and_settle_pct_is_reproducible(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    """AR-9f at the seam: identical inputs (markers + assertions +
    settle_pct in the params) re-export to the SAME report id, write
    nothing new, and the sidecar records the effective params — the
    document is re-derivable from the sidecar."""
    root = tmp_path / "captures"
    write_capture(root, "fx-exp-full", values=(1.0, 2.0, 3.0))
    arguments = {
        "capture_ids": ["fx-exp-full"],
        "settle_pct": 5.0,
        "markers": [
            {"capture_id": "fx-exp-full", "label": "Z", "t": 1.0, "note": "z"}
        ],
        "assertions": [
            {"capture_id": "fx-exp-full", "min": 0.0, "max": 3.0},
            {"capture_id": "fx-exp-full", "max": 1.5},
        ],
    }
    first = call(marker_seam, "report_export", arguments)
    second = call(marker_seam, "report_export", arguments)
    assert first["report_id"] == second["report_id"]
    assert second["created"] is False
    sidecar = json.loads(
        (root / "reports" / f"{first['report_id']}.json").read_text()
    )
    assert sidecar["params"]["settle_pct"] == 5.0
    assert sidecar["params"]["assertions"] == arguments["assertions"]
    assert sidecar["params"]["markers"][0]["label"] == "Z"
    assert sidecar["params"]["markers"][0]["capture_id"] == "fx-exp-full"
    document = (root / "reports" / f"{first['report_id']}.html").read_text()
    assert ">pass<" in document and ">fail<" in document
    assert "above_max" in document


def test_export_refuses_markers_and_assertions_outside_the_set(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    root = tmp_path / "captures"
    write_capture(root, "fx-exp-set", values=(1.0,))
    with pytest.raises(SeamError) as caught:
        call(
            marker_seam,
            "report_export",
            {
                "capture_ids": ["fx-exp-set"],
                "markers": [
                    {"capture_id": "fx-exp-other", "label": "A", "t": 0.0}
                ],
            },
        )
    assert caught.value.code == "invalid_request"
    assert "fx-exp-other" in caught.value.message
    # A-F6: a MARKER row's out-of-set reference refuses in the marker
    # family, not the assertion family.
    assert "standalone_report_marker_invalid" in caught.value.message
    with pytest.raises(SeamError) as caught:
        call(
            marker_seam,
            "report_export",
            {
                "capture_ids": ["fx-exp-set"],
                "assertions": [{"capture_id": "fx-exp-other", "min": 0.0}],
            },
        )
    assert caught.value.code == "invalid_request"
    # A refused export leaves no reports/ behind (the no-orphans rule).
    assert not (root / "reports").exists()


def test_a_f8_settle_pct_refuses_outside_the_band_bounds(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    """A-F8: the seam-level bound mirrors the schema's (0, 100] — a
    negative (or non-numeric) band refuses at admission even through a
    direct seam call."""
    root = tmp_path / "captures"
    write_capture(root, "fx-exp-band", values=(1.0, 2.0))
    for bad in (-5.0, 0.0, 101.0, float("nan")):
        with pytest.raises(SeamError) as caught:
            call(
                marker_seam,
                "report_export",
                {"capture_ids": ["fx-exp-band"], "settle_pct": bad},
            )
        assert caught.value.code == "invalid_request", bad


# --- the refute fold (I4b.1): A-F3 read-path discipline, A-F4 replayable sidecar ---


def test_a_f3_overlay_read_rows_go_through_the_discipline_at_export(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    """A-F3 (the converge): a HAND-EDITED analysis.json bypasses the
    write path's span/label discipline — t=99 on a 2 s capture used to
    export a glyph off-canvas and then make the sidecar's own replay
    refuse. The read path runs the SAME validation family at export time
    and refuses typed, exactly like the request path."""
    root = tmp_path / "captures"
    event = write_capture(root, "fx-exp-handedit", values=(1.0, 2.0, 3.0))
    (event / "analysis.json").write_text(
        json.dumps(
            {
                "format": "standalone-analysis/1",
                "markers": [{"label": "A", "t": 99.0, "note": "off canvas"}],
            }
        )
    )
    with pytest.raises(SeamError) as caught:
        call(marker_seam, "report_export", {"capture_ids": ["fx-exp-handedit"]})
    assert caught.value.code == "invalid_request"
    assert "standalone_report_marker_invalid" in caught.value.message


def test_a_f3_duplicate_overlay_labels_collapse_like_the_write_path(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    """A-F3's duplicate half: a hand-edited overlay keeping two rows for
    one label used to render two glyphs per chart. The read path applies
    the write path's replace-on-duplicate (last wins)."""
    root = tmp_path / "captures"
    event = write_capture(root, "fx-exp-duplabels", values=(1.0, 2.0, 3.0))
    (event / "analysis.json").write_text(
        json.dumps(
            {
                "format": "standalone-analysis/1",
                "markers": [
                    {"label": "A", "t": 0.0, "note": "first"},
                    {"label": "A", "t": 1.0, "note": "second"},
                ],
            }
        )
    )
    result = call(
        marker_seam,
        "report_export",
        {"capture_ids": ["fx-exp-duplabels"], "lo": 0.0, "hi": 1.5},
    )
    document = (root / "reports" / f"{result['report_id']}.html").read_text()
    # A windowed export renders the context AND zoom charts: one glyph
    # each — two rows for one label used to draw four.
    assert document.count('data-bw-marker="A"') == 2
    assert "second" in document and "first" not in document


def test_a_f4_sidecar_params_replay_verbatim(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    """A-F4 (the converge): the sidecar's params must be a VERBATIM
    replayable report_export input — lo/hi nulls used to fail the
    "number" schema and the markers map was dict-shaped where the schema
    wants an array. Feeding the recorded params back reproduces the
    report (the content-addressed created=False path)."""
    root = tmp_path / "captures"
    write_capture(root, "fx-exp-replay", values=(1.0, 2.0, 3.0, 4.0))
    arguments = {
        "capture_ids": ["fx-exp-replay"],
        "lo": 1.0,
        "hi": 3.0,
        "settle_pct": 5.0,
        "markers": [
            {"capture_id": "fx-exp-replay", "label": "A", "t": 1.5, "note": "r"}
        ],
        "assertions": [{"capture_id": "fx-exp-replay", "max": 10.0}],
    }
    first = call(marker_seam, "report_export", arguments)
    sidecar = json.loads(
        (root / "reports" / f"{first['report_id']}.json").read_text()
    )
    params = sidecar["params"]
    # The recorded shape is the input schema's: markers is an ARRAY of
    # capture-scoped rows; bounded lo/hi are numbers.
    assert isinstance(params["markers"], list)
    assert params["markers"][0]["capture_id"] == "fx-exp-replay"
    replay = call(
        marker_seam, "report_export", {"capture_ids": ["fx-exp-replay"], **params}
    )
    assert replay["report_id"] == first["report_id"]
    assert replay["created"] is False


def test_a_f4_unbounded_bounds_are_omitted_from_the_sidecar(
    marker_seam: StandaloneSeam, tmp_path: Path
) -> None:
    """A-F4's other half: unbounded lo/hi are OMITTED (the input schema
    treats absence as unbounded — a null would fail its "number" type),
    and an empty marker set records as the schema's empty array."""
    root = tmp_path / "captures"
    write_capture(root, "fx-exp-unbounded", values=(1.0, 2.0))
    first = call(marker_seam, "report_export", {"capture_ids": ["fx-exp-unbounded"]})
    sidecar = json.loads(
        (root / "reports" / f"{first['report_id']}.json").read_text()
    )
    assert "lo" not in sidecar["params"]
    assert "hi" not in sidecar["params"]
    assert sidecar["params"]["markers"] == []
    assert sidecar["params"]["settle_pct"] == 2.0
