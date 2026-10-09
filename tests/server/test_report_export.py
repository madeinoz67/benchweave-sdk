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


def write_capture(
    root: Path,
    capture_id: str,
    *,
    values: tuple[float, ...],
    unit: str = "V",
    interval: float = 0.001,
) -> Path:
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
        "sample_interval_s": interval,
        "unit": unit,
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
    # I4b.1 + the A-F4 fold: the sidecar records the EFFECTIVE params in
    # the INPUT SCHEMA's shape so a verbatim replay reproduces the
    # document — markers as the schema's capture-scoped array (the
    # resolved rows), and unbounded lo/hi OMITTED (absence is unbounded;
    # a null would fail the "number" type).
    assert sidecar["params"] == {
        "settle_pct": 2.0,
        "markers": [],
        "assertions": [],
    }
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


# --- fold wave 1: bounded windows and typed refusals (rows 4 and 7) ----------------


def test_window_ceiling_binds_memory_not_just_the_response(
    seam: StandaloneSeam,
    capture_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Row 4: the plot ceiling must bind the ALLOCATION. An over-ceiling
    window refuses payload_too_large without ever materialising the full
    point list (peak stays near the chunk buffers, far under the ~20 MB a
    materialised 300k-tuple window would cost)."""
    import tracemalloc

    from benchweave_sdk_server import report as report_module

    write_capture(
        capture_root, "fx-huge", values=tuple(float(i % 101) for i in range(300_000))
    )
    monkeypatch.setattr(report_module, "REPORT_PLOT_SAMPLE_CEILING", 100)
    tracemalloc.start()
    try:
        with pytest.raises(SeamError) as caught:
            call(seam, "report_export", {"capture_ids": ["fx-huge"]})
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert caught.value.code == "payload_too_large"
    assert "standalone_report_window_too_large" in caught.value.message
    assert peak < 2_000_000, f"the window was materialised first (peak {peak} bytes)"


def test_a_file_named_reports_refuses_typed(
    seam: StandaloneSeam, capture_root: Path
) -> None:
    """Row 7: a FILE named ``reports`` in the capture root is a typed
    conflict, never an unhandled FileExistsError (a 500)."""
    write_capture(capture_root, "fx-ok", values=(1.0, 2.0))
    (capture_root / "reports").write_text("not a directory")
    with pytest.raises(SeamError) as caught:
        call(seam, "report_export", {"capture_ids": ["fx-ok"]})
    assert caught.value.code == "conflict"
    assert "standalone_report_reports_blocked" in caught.value.message


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


# --- fold wave 2 (lane B): re-pinning and non-finite windows (rows B-F3/B-F4) -------


def test_re_export_re_pins_after_an_unpin(
    seam: StandaloneSeam, capture_root: Path
) -> None:
    """B-F3: a re-export of identical inputs must RE-RUN the pin — the
    wire claims pinned:true and the catalogue documents the field 'Always
    true', so an unpinned-then-re-exported source with created:false and
    library pinned=False was the wire lying."""
    write_capture(capture_root, "fx-repin", values=(1.0, 2.0))
    first = call(seam, "report_export", {"capture_ids": ["fx-repin"]})
    call(seam, "capture_unpin", {"capture_id": "fx-repin"})
    row = next(
        row
        for row in call(seam, "capture_list")["captures"]
        if row["capture_id"] == "fx-repin"
    )
    assert row["pinned"] is False, "arrange: the unpin must hold first"
    second = call(seam, "report_export", {"capture_ids": ["fx-repin"]})
    assert second["report_id"] == first["report_id"]
    assert second["created"] is False
    assert all(entry["pinned"] is True for entry in second["captures"])
    row = next(
        row
        for row in call(seam, "capture_list")["captures"]
        if row["capture_id"] == "fx-repin"
    )
    assert row["pinned"] is True, "the re-export must re-pin the source"


def test_non_finite_window_refuses_before_any_side_effect(
    seam: StandaloneSeam, capture_root: Path
) -> None:
    """B-F4 (seam arm, the MCP dispatch path): NaN and inf window bounds
    refuse invalid_request at admission — no pins applied, no reports/
    artifacts (the pre-fold crash path pinned sources and created an
    orphan empty reports/ before the sidecar's allow_nan=False blew up)."""
    write_capture(capture_root, "fx-pinf", values=(1.0, 2.0))
    for bad in (float("nan"), float("inf"), float("-inf")):
        arguments = {"capture_ids": ["fx-pinf"], "lo": bad}
        with pytest.raises(SeamError) as caught:
            call(seam, "report_export", arguments)
        assert caught.value.code == "invalid_request", bad
        assert "standalone_report_window_invalid" in caught.value.message
        assert "finite" in caught.value.message
        assert report_files(capture_root) == []
        rows = {
            row["capture_id"]: row["pinned"]
            for row in call(seam, "capture_list")["captures"]
        }
        assert rows == {"fx-pinf": False}, "a refused export pins nothing"


def test_non_finite_window_refuses_over_rest(
    seam: StandaloneSeam, capture_root: Path
) -> None:
    """B-F4 (REST arm): the JSON body carries NaN/Infinity literals (the
    stdlib parser accepts both); the typed refusal answers 400, never a
    500 from the sidecar."""
    from fastapi.testclient import TestClient

    from benchweave_sdk_server.security import GuardPolicy, new_token
    from benchweave_sdk_server.web import build_app

    write_capture(capture_root, "fx-rest", values=(1.0, 2.0))
    bearer = new_token()
    app = build_app(
        seam,
        policy=GuardPolicy.complete(
            bound_host="127.0.0.1",
            bound_port=8477,
            bearer_token=bearer,
            csrf_token=new_token(),
        ),
    )
    with TestClient(app, base_url="http://127.0.0.1:8477") as client:
        for literal in ("NaN", "Infinity"):
            # Raw JSON literals: the stdlib parser on the SERVER side
            # accepts both (the strict test-client encoder refuses them,
            # which is exactly why the arm sends raw bytes).
            response = client.post(
                "/v1/report_export",
                content='{"capture_ids": ["fx-rest"], "lo": ' + literal
                + ', "hi": 1.0}',
                headers={
                    "Authorization": f"Bearer {bearer}",
                    "Content-Type": "application/json",
                },
            )
            assert response.status_code == 400, literal
            body = response.json()
            assert body["error"]["code"] == "invalid_request"
            assert "standalone_report_window_invalid" in body["error"]["message"]


# --- I4b.2: the power params through report_export (the record §1.6) ----------------


def _write_pair(root: Path, *, n: int = 360, interval: float = 0.01) -> None:
    write_capture(
        root, "fx-px-v", values=(2.0,) * n, unit="V", interval=interval
    )
    write_capture(
        root, "fx-px-i", values=(3.0,) * n, unit="A", interval=interval
    )


def test_power_export_renders_and_sidecar_replays(
    seam: StandaloneSeam, capture_root: Path
) -> None:
    """The power params ride report_export (schema'd), the resolved rails
    land in the sidecar's replay params (AR-10: the report names what it
    used), and re-export FROM the sidecar params reproduces the same
    content-addressed id (AR-4d extended to power)."""
    _write_pair(capture_root)
    result = call(
        seam,
        "report_export",
        {
            "capture_ids": ["fx-px-v", "fx-px-i"],
            "power": {"mode": "battery", "capacity_ah": 12.0},
        },
    )
    html = (capture_root / "reports" / f"{result['report_id']}.html").read_text(
        encoding="utf-8"
    )
    assert "benchweave-power/1" in html
    assert "runtime (h)" in html and ">4<" in html
    sidecar = json.loads(
        (capture_root / "reports" / f"{result['report_id']}.json").read_text(
            encoding="utf-8"
        )
    )
    assert sidecar["params"]["power"] == {
        "mode": "battery",
        "rails": [{"v": "fx-px-v", "i": "fx-px-i"}],
        "capacity_ah": 12.0,
    }
    replay = call(
        seam, "report_export", {"capture_ids": ["fx-px-v", "fx-px-i"], **sidecar["params"]}
    )
    assert replay["report_id"] == result["report_id"]
    assert replay["created"] is False


def test_power_export_without_current_series_renders_reason(
    seam: StandaloneSeam, capture_root: Path
) -> None:
    """AR-3's arm through the export: no current series is a RENDERED
    honest reason, not a refusal — never 0 W."""
    write_capture(capture_root, "fx-nc-a", values=(1.0,) * 10, unit="V")
    write_capture(capture_root, "fx-nc-b", values=(2.0,) * 10, unit="mV")
    result = call(
        seam,
        "report_export",
        {"capture_ids": ["fx-nc-a", "fx-nc-b"], "power": {"mode": "battery"}},
    )
    html = (capture_root / "reports" / f"{result['report_id']}.html").read_text(
        encoding="utf-8"
    )
    assert "power_unavailable: no current series" in html
    assert "mean power (W)" not in html


def test_power_export_refusals(seam: StandaloneSeam, capture_root: Path) -> None:
    """The pairing/power refusal family on the wire: unknown mode and
    out-of-set rails (invalid_request), a non-finite threshold that the
    schema's number type admits (the pure layer's B-F4 mirror), and the
    schema's own exclusiveMinimum on capacity_ah."""
    _write_pair(capture_root, n=10)
    ids = ["fx-px-v", "fx-px-i"]
    with pytest.raises(SeamError) as caught:
        call(seam, "report_export", {"capture_ids": ids, "power": {"mode": "turbo"}})
    assert caught.value.code == "invalid_request"
    assert "standalone_report_power_mode" in caught.value.message
    with pytest.raises(SeamError) as caught:
        call(
            seam,
            "report_export",
            {"capture_ids": ids, "power": {"mode": "battery",
                                           "rails": [{"v": "fx-ghost", "i": "fx-px-i"}]}},
        )
    assert "standalone_report_power_rails" in caught.value.message
    with pytest.raises(SeamError) as caught:
        call(
            seam,
            "report_export",
            {"capture_ids": ids,
             "power": {"mode": "sleep", "threshold": float("nan")}},
        )
    assert "standalone_report_power_param" in caught.value.message
    with pytest.raises(SeamError) as caught:
        call(
            seam,
            "report_export",
            {"capture_ids": ids, "power": {"mode": "battery", "capacity_ah": 0}},
        )
    assert caught.value.code == "invalid_request"
    assert "standalone_report_power_param" in caught.value.message
    # A refused export leaves no reports directory (the no-orphans rule).
    assert report_files(capture_root) == []


def test_power_export_schema_rejects_unknown_power_keys(
    seam: StandaloneSeam, capture_root: Path
) -> None:
    _write_pair(capture_root, n=10)
    with pytest.raises(SeamError) as caught:
        call(
            seam,
            "report_export",
            {"capture_ids": ["fx-px-v", "fx-px-i"],
             "power": {"mode": "battery", "volts": 1}},
        )
    assert caught.value.code == "invalid_request"
