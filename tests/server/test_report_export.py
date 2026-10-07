"""I4a AR-5: the ``report_export`` operation — side effects, idempotency,
and the refusal family on the wire.

The design record's mechanism §1.3: one new catalogue row (row 22, fork
F-C adopted), the seam handler that renders + writes the content-addressed
report pair under ``reports/`` and PINS every source (SW-56), REST/MCP
following structurally from the catalogue machinery, the retention sweep
learning the reserved ``reports`` directory (the build-time discovery:
the landed I3c sweep removes every manifest-less directory in the root,
and the design's "capture retention does not govern reports/" premise is
false against it), and the capture metadata recording its transport (the
data source the report's SIMULATED mark derives from).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import struct
from pathlib import Path

import pytest

from benchweave_sdk_server.errors import SeamError
from benchweave_sdk_server.seam import StandaloneSeam


def write_capture(root: Path, capture_id: str, *, values: tuple[float, ...]) -> Path:
    payload = b"".join(struct.pack("<d", value) for value in values)
    event = root / capture_id
    event.mkdir(parents=True)
    (event / f"{capture_id}.f64").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    manifest = {
        "capture_id": capture_id,
        "format": "waveform_f64le",
        "artifact_id": "art-" + digest,
        "byte_length": len(payload),
        "sha256": digest,
        "started_at": f"2026-10-07T11:00:00+00:00-{capture_id}",
        "sample_count": len(values),
        "sample_interval_s": 0.001,
        "unit": "V",
        "x-standalone-state": "finalised",
        "x-standalone-manifest-version": 1,
    }
    (event / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    (event / "metadata.json").write_text(
        json.dumps(
            {
                "capture_id": capture_id,
                "device": {"id": "fx-device", "firmware": "1.0.0"},
                "plugin": {"package": "fx-plugin", "version": "0.2.0",
                           "descriptor_sha256": "b" * 64},
                "surface": "rest",
                "operator": "fx-op",
                "tags": [],
                "notes": "",
            },
            sort_keys=True,
        )
    )
    return event


@pytest.fixture()
def capture_root(tmp_path: Path) -> Path:
    """The seam's capture root, WITHOUT constructing the library: taking
    it through ``seam._library()`` would build (and cache) the index over
    an empty root before the test's on-disk captures exist."""
    return tmp_path / "captures"


@pytest.fixture()
def seam(plugin, capture_root: Path) -> StandaloneSeam:
    from benchweave_sdk_server.session import mock_plugin_session

    return StandaloneSeam(
        mock_plugin_session(plugin),
        transport_kind="mock",
        capture_root=capture_root,
    )


def call(seam: StandaloneSeam, operation: str, arguments: dict | None = None) -> dict:
    return asyncio.run(seam.call(operation, arguments or {}))


def report_files(capture_root: Path) -> list[str]:
    root = capture_root / "reports"
    if not root.is_dir():
        return []
    return sorted(entry.name for entry in root.iterdir())


def test_ar5_export_pins_sources_and_writes_the_pair(
    seam: StandaloneSeam, capture_root: Path
) -> None:
    write_capture(capture_root, "fx-set-a", values=(1.0, 2.0, 3.0, 2.0, 1.0))
    write_capture(capture_root, "fx-set-b", values=(5.0, 4.0, 3.0))
    result = call(seam, "report_export", {"capture_ids": ["fx-set-a", "fx-set-b"]})
    assert re.fullmatch(r"rep-[0-9a-f]{16}", result["report_id"])
    assert result["created"] is True
    assert result["html_sha256"] == hashlib.sha256(
        (capture_root / "reports" / f"{result['report_id']}.html").read_bytes()
    ).hexdigest()
    # Exactly one html + one sidecar.
    files = report_files(capture_root)
    assert files == [f"{result['report_id']}.html", f"{result['report_id']}.json"]
    # Every source pinned (SW-56).
    for row in call(seam, "capture_list")["captures"]:
        if row["capture_id"] in {"fx-set-a", "fx-set-b"}:
            assert row["pinned"] is True, row["capture_id"]
    # The sidecar names source ids, their manifest digests, the params,
    # the pinned asset versions, generated_at and the report file's own
    # sha256.
    sidecar = json.loads(
        (capture_root / "reports" / f"{result['report_id']}.json").read_text()
    )
    assert sidecar["report_id"] == result["report_id"]
    sources = {entry["capture_id"]: entry["sha256"] for entry in sidecar["sources"]}
    assert set(sources) == {"fx-set-a", "fx-set-b"}
    assert sources["fx-set-a"] == hashlib.sha256(
        (capture_root / "fx-set-a" / "fx-set-a.f64").read_bytes()
    ).hexdigest()
    assert sidecar["params"] == {"lo": None, "hi": None}
    assert sidecar["assets"]["ui_html_version"]
    assert sidecar["assets"]["tokens_sha256"] and sidecar["assets"]["themes_sha256"]
    assert sidecar["generated_at"]
    assert sidecar["html_sha256"] == result["html_sha256"]
    # The rendered document stays clock-free: generated_at is sidecar-only.
    html = (capture_root / "reports" / f"{result['report_id']}.html").read_text()
    assert sidecar["generated_at"] not in html


def test_ar5_identical_export_writes_nothing_new(
    seam: StandaloneSeam, capture_root: Path
) -> None:
    write_capture(capture_root, "fx-once", values=(1.0, 2.0))
    first = call(seam, "report_export", {"capture_ids": ["fx-once"]})
    second = call(seam, "report_export", {"capture_ids": ["fx-once"]})
    assert second["report_id"] == first["report_id"]
    assert second["created"] is False
    assert report_files(capture_root) == [
        f"{first['report_id']}.html", f"{first['report_id']}.json"
    ]


def test_ar5_unknown_capture_refuses_with_no_orphan_reports(
    seam: StandaloneSeam, capture_root: Path
) -> None:
    write_capture(capture_root, "fx-known", values=(1.0,))
    with pytest.raises(SeamError) as caught:
        call(seam, "report_export", {"capture_ids": ["fx-known", "fx-absent"]})
    assert caught.value.code == "not_found"
    # The landed stale-row refusal answers unknown ids with the capture
    # family's own wording (capture_get/annotate/pin/delete say the same);
    # the report loader's standalone_report_capture_unknown prefix stays
    # the pure-module refusal (pinned in test_analysis).
    assert "no published capture: fx-absent" in caught.value.message
    assert report_files(capture_root) == []


def test_window_bounds_are_validated(seam: StandaloneSeam, capture_root: Path) -> None:
    write_capture(capture_root, "fx-win", values=(1.0, 2.0, 3.0))
    with pytest.raises(SeamError) as caught:
        call(
            seam,
            "report_export",
            {"capture_ids": ["fx-win"], "lo": 2.0, "hi": 1.0},
        )
    assert caught.value.code == "invalid_request"
    assert "standalone_report_window_invalid" in caught.value.message
    assert report_files(capture_root) == []


def test_tampered_source_refuses_conflict(
    seam: StandaloneSeam, capture_root: Path
) -> None:
    write_capture(capture_root, "fx-tamper", values=(1.0, 2.0))
    (capture_root / "fx-tamper" / "fx-tamper.f64").write_bytes(
        struct.pack("<dd", 1.0, 9.0)
    )
    with pytest.raises(SeamError) as caught:
        call(seam, "report_export", {"capture_ids": ["fx-tamper"]})
    assert caught.value.code == "conflict"
    assert "standalone_report_primary_mismatch" in caught.value.message
    assert report_files(capture_root) == []


def test_non_waveform_source_refuses(
    seam: StandaloneSeam, capture_root: Path
) -> None:
    write_capture(capture_root, "fx-wave", values=(1.0,))
    event = capture_root / "fx-raw"
    event.mkdir()
    (event / "fx-raw.bin").write_bytes(b"\x01\x02")
    (event / "manifest.json").write_text(
        json.dumps(
            {
                "capture_id": "fx-raw",
                "format": "raw_binary",
                "artifact_id": "art-x",
                "byte_length": 2,
                "sha256": "x",
                "started_at": "2026-10-07T11:00:00+00:00",
            },
            sort_keys=True,
        )
    )
    with pytest.raises(SeamError) as caught:
        call(seam, "report_export", {"capture_ids": ["fx-raw"]})
    assert caught.value.code == "invalid_request"
    assert "standalone_report_format_unsupported" in caught.value.message
    assert report_files(capture_root) == []


def test_export_is_served_over_rest(seam: StandaloneSeam) -> None:
    """The catalogue machinery routes the row: /v1/report_export answers."""
    from fastapi.testclient import TestClient

    from benchweave_sdk_server.security import GuardPolicy, new_token
    from benchweave_sdk_server.web import build_app

    app = build_app(
        seam,
        policy=GuardPolicy.complete(
            bound_host="127.0.0.1",
            bound_port=8477,
            bearer_token=new_token(),
            csrf_token=new_token(),
        ),
    )
    with TestClient(app, base_url="http://127.0.0.1:8477") as client:
        response = client.post(
            "/v1/report_export",
            json={"capture_ids": ["fx-none"]},
            headers={"Authorization": "Bearer missing"},
        )
        # The bearer guard refuses REST mutations without the launch
        # token — the route exists and is guarded, which is the arm.
        assert response.status_code == 403
        assert response.json()["error"] == "standalone_bearer_required"


def test_mcp_registers_the_report_tool(seam: StandaloneSeam) -> None:
    from benchweave_sdk_server.mcp import build_mcp, tool_name

    build_mcp(seam)  # the drift check raises on any missing handler
    assert tool_name("report_export") == "bws_v1_report_export"


# --- the retention sweep's reserved directory (build-time re-derivation) ----------


def test_sweep_spares_the_reserved_reports_directory(tmp_path: Path) -> None:
    """The landed sweep removes every manifest-less directory past its
    grace; ``reports`` is a host-owned persisted surface, never crash
    residue — the design's "capture retention does not govern reports/"
    premise, made true by the reserved-name skip."""
    import os

    from benchweave_sdk_server.retention import sweep_plan

    root = tmp_path / "captures"
    root.mkdir()
    (root / "reports").mkdir()
    (root / "reports" / "rep-deadbeef0000ffff.html").write_text("<html></html>")
    (root / "crash-residue").mkdir()
    old = 1_000_000_000.0
    for directory in (root / "reports", root / "crash-residue"):
        os.utime(directory, (old, old))
        assert directory.stat().st_mtime == old
    swept = sweep_plan(root, now=old + 10_000, grace_s=1.0)
    assert "crash-residue" in swept
    assert "reports" not in swept
    assert (root / "reports" / "rep-deadbeef0000ffff.html").is_file()


# --- the capture metadata's transport field ---------------------------------------


def test_capture_metadata_records_the_transport(seam: StandaloneSeam) -> None:
    """New captures record their transport kind — the field the report's
    SIMULATED mark derives from (absent on every pre-I4a capture; the
    derivation's disclosed boundary matches the gateway's
    SIMULATION_MARK stance)."""
    metadata = seam._capture_metadata(  # noqa: SLF001 - test probe
        {"count": 2}, "fx-meta-cap", {"count": 2}, "waveform_f64le"
    )
    assert metadata["transport"] == "mock"
