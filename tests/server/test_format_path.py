"""Issue #589 PR-4: the format path — every format ``_FORMATS`` admits
renders on every display surface.

D5's defect: ``raw_binary`` is the DEFAULT capture format and every display
surface refused it (the series gate, the loader gate) or hid it (the web
picker's waveform-only filter). The corpus's own ``captureManifest``
defines ``raw_binary`` as the no-timing format — ``byte_length`` for every
format, the timing trio only under ``waveform_f64le`` — so the fix derives
each format's grid from the fields its manifest honestly carries: the
index axis for ``raw_binary`` (x is the 0-based sample index, y the byte),
never a fabricated time base.

The arms A1–A14 are the design record §8's pre-committed set; the
exhaustion walk (A7) parametrizes over the DERIVED enum, so a format added
to the registry joins the walk by construction. Fixtures are synthetic
with invented ``fx-*`` names.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import struct
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk_server.catalogue import _FORMATS
from benchweave_sdk_server.errors import SeamError
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.web import build_app

TEST_HOST = "127.0.0.1"
TEST_PORT = 8477
DEV = "example_device"

#: The fixture payload of A1/A3/A4/A5/A8/A9/A10/A12/A13 — six bytes whose
#: values span the honest byte range (0, 1, 2, 253, 254, 255).
_RAW_BYTES = bytes((0, 1, 2, 253, 254, 255))


# --- the fixture family: hand-written published events -----------------------


def write_event(
    root: Path,
    capture_id: str,
    *,
    fmt: str,
    payload: bytes,
    manifest_overrides: dict[str, Any] | None = None,
    manifest_drop: tuple[str, ...] = (),
    suffix: str | None = None,
) -> Path:
    """One published event directory as the writer + host leave it.

    ``manifest_overrides`` replaces fields (a contradictory
    ``byte_length``); ``manifest_drop`` removes them (a hand-edited
    manifest missing the corpus-required field); ``suffix`` overrides the
    primary's extension (an unknown format's own).
    """
    event = root / capture_id
    event.mkdir(parents=True)
    primary_name = suffix if suffix is not None else (
        ".f64" if fmt == "waveform_f64le" else ".bin"
    )
    (event / f"{capture_id}{primary_name}").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    manifest: dict[str, Any] = {
        "capture_id": capture_id,
        "format": fmt,
        "artifact_id": "art-" + digest,
        "byte_length": len(payload),
        "sha256": digest,
        "started_at": f"2026-11-07T09:00:00+00:00-{capture_id}",
    }
    if fmt == "waveform_f64le":
        manifest["sample_count"] = len(payload) // 8
        manifest["sample_interval_s"] = 0.001
        manifest["unit"] = "V"
    manifest.update(manifest_overrides or {})
    for field in manifest_drop:
        manifest.pop(field, None)
    (event / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    (event / "metadata.json").write_text(
        json.dumps(
            {
                "capture_id": capture_id,
                "device": {"id": "fx-device", "firmware": "1.0.0"},
                "plugin": {"package": "fx-plugin", "version": "0.4.0",
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


def write_waveform(
    root: Path,
    capture_id: str,
    values: tuple[float, ...],
    *,
    unit: str = "V",
    interval: float = 0.001,
) -> Path:
    payload = b"".join(struct.pack("<d", value) for value in values)
    event = write_event(root, capture_id, fmt="waveform_f64le", payload=payload)
    manifest = json.loads((event / "manifest.json").read_text())
    manifest["sample_count"] = len(values)
    manifest["sample_interval_s"] = interval
    manifest["unit"] = unit
    (event / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    return event


def write_raw(root: Path, capture_id: str, payload: bytes) -> Path:
    return write_event(root, capture_id, fmt="raw_binary", payload=payload)


@pytest.fixture()
def capture_root(tmp_path: Path) -> Path:
    return tmp_path / "captures"


@pytest.fixture()
def seam(plugin, capture_root: Path) -> StandaloneSeam:
    from benchweave_sdk_server.session import mock_plugin_session

    return StandaloneSeam(
        mock_plugin_session(plugin),
        transport_kind="mock",
        capture_root=capture_root,
    )


@pytest.fixture()
def client(plugin, capture_root: Path):
    from benchweave_sdk_server.session import mock_plugin_session

    seam = StandaloneSeam(
        mock_plugin_session(plugin),
        transport_kind="mock",
        capture_root=capture_root,
    )
    app = build_app(
        seam,
        policy=GuardPolicy.complete(
            bound_host=TEST_HOST,
            bound_port=TEST_PORT,
            bearer_token=new_token(),
            csrf_token=new_token(),
            operator_action_token=new_token(),
        ),
    )
    entered = TestClient(app, base_url=f"http://{TEST_HOST}:{TEST_PORT}")
    with entered:
        yield entered


def call(seam: StandaloneSeam, operation: str, arguments: dict | None = None) -> dict:
    return asyncio.run(seam.call(operation, arguments or {}))


# --- the lifecycle machinery (the capture-capable host, local copy) ----------

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_PACKAGE = "wavegen_plugin"
_ID_REPLY = b"Bench Fixture,wavegen,SIMW001,1.0.0\n"


class _LoopbackPort:
    """The pyserial surface over a scripted reply table (no real port)."""

    def __init__(self, replies: dict[bytes, bytes] | None = None) -> None:
        self.inbound = bytearray()
        self.replies = replies or {}

    def write(self, data: bytes) -> int | None:
        self.inbound += self.replies.get(bytes(data), b"")
        return len(data)

    def read(self, size: int = 1) -> bytes:
        out = bytes(self.inbound[:size])
        del self.inbound[:size]
        if not out:
            time.sleep(0.005)
        return out

    def close(self) -> None:
        return None


def lifecycle_seam(tmp_path: Path, *, default_count: int = 8) -> StandaloneSeam:
    """A serial-transport seam over the wavegen fixture plugin, its
    descriptor declaring BOTH capture formats — the walk's host."""
    from benchweave_sdk.scaffold import create_project
    from benchweave_sdk_server.serial import serial_plugin_session
    from benchweave_sdk_server.session import load_plugin_project

    root = tmp_path / "proj"
    create_project(root, _PACKAGE)
    descriptor_path = root / "src" / _PACKAGE / "descriptor.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["capabilities"] = ["identify", "read", "capture"]
    descriptor["identity"]["manufacturer"] = "Bench Fixture"
    descriptor["identity"]["model"] = "wavegen"
    descriptor["operations"]["capture"] = {
        "timeout_ms": 5000,
        "side_effect": "state_change",
        "retry": "never",
        "cancellable": True,
        "completion": "acknowledged",
    }
    descriptor["capture_formats"] = ["waveform_f64le", "raw_binary"]
    descriptor["capture_limits"] = {"max_samples": 100_000, "max_bytes": 16 * 1024 * 1024}
    descriptor_path.write_text(json.dumps(descriptor, indent=2), encoding="utf-8")
    shutil.copy(_FIXTURES / "wavegen_adapter.py", root / "src" / _PACKAGE / "adapter.py")
    (root / "src" / _PACKAGE / "behaviour.json").write_text(
        json.dumps({"mode": "ok", "default_count": default_count}), encoding="utf-8"
    )
    loaded = load_plugin_project(root)
    port = _LoopbackPort(replies={b"ID?\n": _ID_REPLY})
    captures = tmp_path / "captures"
    session = serial_plugin_session(
        loaded,
        "/dev/fixture-loopback",
        open_port=lambda device, settings: port,
        capture_root=captures,
    )
    return StandaloneSeam(session, transport_kind="serial", capture_root=captures)


def publish(host: StandaloneSeam, arguments: dict[str, Any]) -> dict[str, Any]:
    """connect → start → settle at the bound; the published outcome row.
    A host already connected by an earlier publish stays connected."""

    async def scenario() -> dict[str, Any]:
        try:
            await host.call("device_connect", {"device_id": DEV})
        except SeamError as exc:
            if "already connected" not in exc.message:
                raise
        started = await host.call("capture_start", arguments, surface="rest")
        outcome = await host.await_capture()
        assert outcome is not None and outcome["state"] == "published", outcome
        return {**outcome, "capture_id": started["capture_id"]}

    return asyncio.run(scenario())


def _start(fmt: str, count: int, **extra: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "device_id": DEV,
        "count": count,
        "format": fmt,
        "project": "fx-format-path",
    }
    if fmt == "waveform_f64le":
        arguments["sample_interval_s"] = 0.001
        arguments["unit"] = "V"
    arguments.update(extra)
    return arguments


# --- A7: the exhaustion gate -------------------------------------------------


def test_a7_the_served_enum_derives_from_the_registry() -> None:
    """The single-source guard: the served enum IS the registry's key
    list, same order, same membership both ways. Replacing the derivation
    with a literal and adding a format to it alone reddens here — every
    registry-driven site would refuse that format at runtime while the
    schema admits it (D5's resurrection)."""
    from benchweave_sdk_server.catalogue import _FORMAT_SPECS

    assert list(_FORMATS["enum"]) == list(_FORMAT_SPECS)
    assert set(_FORMATS["enum"]) == set(_FORMAT_SPECS)
    assert len(_FORMATS["enum"]) >= 2
    print(
        "A7 walk denominator: "
        f"{len(_FORMATS['enum'])} formats x 3 surfaces = "
        f"{3 * len(_FORMATS['enum'])} cells"
    )


@pytest.mark.parametrize("fmt", [*_FORMATS["enum"]])
def test_a7_walk_every_admitted_format_over_every_surface(
    tmp_path: Path, fmt: str
) -> None:
    """One REAL capture per admitted format through the lifecycle
    machinery (the descriptor declares both formats), then all three
    display surfaces: ``capture_series``, ``analysis_view``,
    ``report_export`` — success and the honest axis per format. The
    parametrize reads the DERIVED enum, so a registry entry with no live
    path reddens at admission time."""
    from benchweave_sdk_server.catalogue import _FORMAT_SPECS

    spec = _FORMAT_SPECS[fmt]
    expected_x_label = {"time": "s", "index": "sample index"}[spec.axis]
    # The grid step the walk itself declared at start (waveform) or the
    # index step (raw): x == index x step for BOTH formats.
    step = 0.001 if spec.axis == "time" else 1.0
    host = lifecycle_seam(tmp_path, default_count=8)
    outcome = publish(host, _start(fmt, 6))
    capture_id = outcome["capture_id"]
    event = tmp_path / "captures" / capture_id
    primary = (event / f"{capture_id}{spec.suffix}").read_bytes()
    # Surface 1: the series serves the format's own decode.
    served = call(host, "capture_series", {"capture_id": capture_id})
    assert served["format"] == fmt
    assert [point["x"] for point in served["points"]] == [
        index * step
        for index in range(len(primary) // spec.bytes_per_sample)
    ]
    # Surface 2: the view labels the axis the format's spec declares.
    entries, _ = host.analysis_view([capture_id], None, None)
    assert entries[0]["x_label"] == expected_x_label
    if spec.axis == "index":
        assert entries[0]["unit"] is None
    # Surface 3: the report exports and prints no lying axis.
    exported = call(host, "report_export", {"capture_ids": [capture_id]})
    assert exported["created"] is True
    document = (
        tmp_path / "captures" / "reports" / f"{exported['report_id']}.html"
    ).read_text()
    assert expected_x_label in document
    if spec.axis == "index":
        assert ">t (s)<" not in document


# --- A1/A2: the series grid, per format --------------------------------------


def test_a1_raw_series_serves_the_index_axis_exactly(seam, capture_root) -> None:
    """A1: x is the 0-based sample index — 0.0 to N-1, EXACTLY, no
    multiplier — y is the byte, the format echoes, and decimation binds
    under a small column budget."""
    write_raw(capture_root, "fx-raw-series", _RAW_BYTES)
    served = call(seam, "capture_series", {"capture_id": "fx-raw-series"})
    assert served["format"] == "raw_binary"
    assert [point["x"] for point in served["points"]] == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    assert [point["y"] for point in served["points"]] == [0.0, 1.0, 2.0, 253.0, 254.0, 255.0]
    decimated = call(
        seam, "capture_series", {"capture_id": "fx-raw-series", "max_points": 3}
    )
    assert decimated["decimated"] is True
    assert decimated["max_points"] == 3
    assert len(decimated["points"]) <= 6


def test_a2_waveform_series_is_unchanged(seam, capture_root) -> None:
    """A2 (the regression pin): x == index x sample_interval_s, the
    manifest's own grid fields, exactly as before PR-4."""
    values = (1.5, -2.5, 4.0)
    write_waveform(capture_root, "fx-wave-pin", values, interval=0.25)
    served = call(seam, "capture_series", {"capture_id": "fx-wave-pin"})
    assert served["format"] == "waveform_f64le"
    assert [point["x"] for point in served["points"]] == [0.0, 0.25, 0.5]
    assert [point["y"] for point in served["points"]] == list(values)


# --- A3: the view over a raw source ------------------------------------------


def test_a3_analysis_view_stats_and_labels_over_raw(seam, capture_root) -> None:
    """A3: statistics over the byte values with their denominators, and
    the entry carries the honest labels — x 'sample index', y 'byte
    value', unit None (a byte plane has no unit)."""
    write_raw(capture_root, "fx-raw-view", _RAW_BYTES)
    entries, _ = seam.analysis_view(["fx-raw-view"], None, None)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["x_label"] == "sample index"
    assert entry["y_label"] == "byte value"
    assert entry["unit"] is None
    stats = entry["stats"]
    assert stats.count == 6
    assert stats.null_count == 0
    assert stats.min == 0.0 and stats.max == 255.0
    assert stats.mean is not None and stats.mean == pytest.approx(
        sum(_RAW_BYTES) / 6
    )


# --- A4: the report over a raw source ----------------------------------------


def test_a4_report_exports_raw_with_the_honest_absences(
    seam, capture_root
) -> None:
    """A4: the export succeeds; the caption and manifest block carry the
    format and the index axis; sample_interval_s prints the honest
    absence; no 's' axis appears anywhere in the document."""
    write_raw(capture_root, "fx-raw-report", _RAW_BYTES)
    exported = call(seam, "report_export", {"capture_ids": ["fx-raw-report"]})
    assert exported["created"] is True
    document = (
        capture_root / "reports" / f"{exported['report_id']}.html"
    ).read_text()
    assert "raw_binary" in document, "the caption carries the format"
    assert "sample index" in document, "the x axis is the index, named"
    assert "byte value" in document, "the y label is the spec's, named"
    assert "<tr><th>sample_interval_s</th><td>—</td></tr>" in document
    assert ">t (s)<" not in document, "no seconds axis for an index source"


# --- A5: the two-label ceiling ------------------------------------------------


def test_a5_the_units_ceiling_counts_labels(seam, capture_root) -> None:
    """A5: V + A + raw_binary is THREE labels and refuses; V + raw_binary
    is two and renders."""
    write_waveform(capture_root, "fx-ceiling-v", (1.0, 2.0), unit="V")
    write_waveform(capture_root, "fx-ceiling-a", (0.5,), unit="A")
    write_raw(capture_root, "fx-ceiling-raw", _RAW_BYTES)
    with pytest.raises(SeamError) as caught:
        call(seam, "report_export", {
            "capture_ids": ["fx-ceiling-v", "fx-ceiling-a", "fx-ceiling-raw"]
        })
    assert caught.value.code == "invalid_request"
    assert "standalone_report_units_unsupported" in caught.value.message
    assert "byte value" in caught.value.message
    mixed = call(
        seam, "report_export", {"capture_ids": ["fx-ceiling-v", "fx-ceiling-raw"]}
    )
    assert mixed["created"] is True


# --- A6: the bit-plane archetype ---------------------------------------------


def test_a6_bitplane_archetype_completes_the_whole_path(tmp_path: Path) -> None:
    """A6: an invented-name logic-analyser-shaped capture (a raw byte
    plane from the fixture's streamed bytes) completes capture → series →
    analysis → report, all green — the D5 customer shape end to end."""
    host = lifecycle_seam(tmp_path, default_count=8)
    outcome = publish(
        host,
        _start("raw_binary", 8, tags=["fx-bitplane"], notes="fx-logic-probe run"),
    )
    capture_id = outcome["capture_id"]
    assert outcome["byte_length"] == 64  # eight staged f64 samples
    served = call(host, "capture_series", {"capture_id": capture_id})
    assert served["format"] == "raw_binary"
    assert len(served["points"]) == 64
    assert served["points"][0]["x"] == 0.0
    assert served["points"][63]["x"] == 63.0
    entries, _ = host.analysis_view([capture_id], None, None)
    assert entries[0]["y_label"] == "byte value"
    exported = call(host, "report_export", {"capture_ids": [capture_id]})
    assert exported["created"] is True


# --- A8: markers on an index-axis capture ------------------------------------


def test_a8_markers_on_raw_validate_in_index_units(seam, capture_root) -> None:
    """A8: t inside [0, N-1] stores and re-exports (the overlay survives a
    fresh round-trip); t outside refuses standalone_report_marker_invalid."""
    write_raw(capture_root, "fx-raw-marked", _RAW_BYTES)
    stored = call(seam, "capture_analysis", {
        "capture_id": "fx-raw-marked",
        "markers": [
            {"label": "A", "t": 0.0, "note": "first byte"},
            {"label": "B", "t": 5.0, "note": "last byte"},
        ],
    })
    assert [row["t"] for row in stored["markers"]] == [0.0, 5.0]
    first = call(seam, "report_export", {"capture_ids": ["fx-raw-marked"]})
    document = (
        capture_root / "reports" / f"{first['report_id']}.html"
    ).read_text()
    assert "first byte" in document and "last byte" in document
    second = call(seam, "report_export", {"capture_ids": ["fx-raw-marked"]})
    assert second["report_id"] == first["report_id"]
    with pytest.raises(SeamError) as caught:
        call(seam, "capture_analysis", {
            "capture_id": "fx-raw-marked",
            "markers": [{"label": "C", "t": 6.0, "note": "outside"}],
        })
    assert caught.value.code == "invalid_request"
    assert "standalone_report_marker_invalid" in caught.value.message


# --- A9: the unknown format refuses on both gates ----------------------------


def test_a9_unknown_format_refuses_on_both_gates(seam, capture_root) -> None:
    """A9: a hand-written manifest with format 'csv' — capture_series
    refuses with the artifact_read guidance; the loader refuses
    standalone_report_format_unsupported naming the ADMITTED set."""
    write_event(
        capture_root,
        "fx-csv-event",
        fmt="csv",
        payload=b"a,b\n",
        suffix=".csv",
    )
    with pytest.raises(SeamError) as caught:
        call(seam, "capture_series", {"capture_id": "fx-csv-event"})
    assert caught.value.code == "invalid_request"
    assert "artifact_read" in caught.value.message
    with pytest.raises(SeamError) as loader:
        seam.analysis_view(["fx-csv-event"], None, None)
    assert loader.value.code == "invalid_request"
    message = loader.value.message
    assert "standalone_report_format_unsupported" in message
    assert "waveform_f64le" in message and "raw_binary" in message, (
        "the refusal names the admitted set, both members"
    )


# --- A10: the raw manifest's own required field ------------------------------


def test_a10_raw_manifest_validates_byte_length(seam, capture_root) -> None:
    """A10: a missing or non-int byte_length is manifest_incomplete
    naming it; a primary that contradicts byte_length is primary_length."""
    # All three fixtures exist before the first call: the library builds
    # its index over the root once.
    write_event(
        capture_root, "fx-raw-nobl", fmt="raw_binary",
        payload=_RAW_BYTES, manifest_drop=("byte_length",),
    )
    write_event(
        capture_root, "fx-raw-badbl", fmt="raw_binary",
        payload=_RAW_BYTES, manifest_overrides={"byte_length": "many"},
    )
    write_event(
        capture_root, "fx-raw-short", fmt="raw_binary",
        payload=_RAW_BYTES, manifest_overrides={"byte_length": 3},
    )
    with pytest.raises(SeamError) as missing:
        call(seam, "report_export", {"capture_ids": ["fx-raw-nobl"]})
    assert missing.value.code == "invalid_request"
    assert "standalone_report_manifest_incomplete" in missing.value.message
    assert "byte_length" in missing.value.message
    # A non-int byte_length never indexes (the library's rebuild skips
    # uncoercible rows), so the pure loader carries this refusal.
    from benchweave_sdk_server.analysis import AnalysisRefusal, load_series_set

    with pytest.raises(AnalysisRefusal) as bad:
        load_series_set(capture_root, ["fx-raw-badbl"])
    assert "standalone_report_manifest_incomplete" in str(bad.value)
    assert "byte_length" in str(bad.value)
    with pytest.raises(SeamError) as short:
        call(seam, "report_export", {"capture_ids": ["fx-raw-short"]})
    assert short.value.code == "conflict"
    assert "standalone_report_primary_length" in short.value.message


# --- A11: the write-side mirror ----------------------------------------------


def test_a11_capture_start_refuses_an_unknown_format(tmp_path: Path) -> None:
    """A11: the write-side mirror. ``seam.call`` validates against the
    served schema (whose enum now DERIVES from the registry), so the
    mirror guards the handler boundary itself — the A-F8 settle_pct
    posture: a direct handler call with an unknown format refuses
    standalone_capture_format_unknown and publishes nothing, where today
    it publishes a capture every display surface refuses."""
    host = lifecycle_seam(tmp_path)
    asyncio.run(host.call("device_connect", {"device_id": DEV}))
    with pytest.raises(SeamError) as caught:
        asyncio.run(host._op_capture_start(
            {"device_id": DEV, "count": 4, "format": "csv"}, "fx-test"
        ))
    assert caught.value.code == "invalid_request"
    assert caught.value.message.startswith("standalone_capture_format_unknown:")
    rows = call(host, "capture_list")["captures"]
    assert rows == []
    root = tmp_path / "captures"
    assert not root.is_dir() or not any(entry.is_dir() for entry in root.iterdir())


# --- A12: the web picker and figure ------------------------------------------


def test_a12_picker_lists_raw_and_figure_labels_the_index_axis(
    client: TestClient, capture_root: Path
) -> None:
    """A12: a published raw_binary row is selectable; the figure's x_unit
    is the index label and the axes string carries 'sample index;byte
    value'; an unknown-format row stays excluded."""
    write_raw(capture_root, "fx-raw-pick", _RAW_BYTES)
    write_event(
        capture_root, "fx-csv-pick", fmt="csv", payload=b"a,b\n", suffix=".csv"
    )
    page = client.get("/analyse").text
    assert "fx-raw-pick" in page, "a published admitted-format row is offered"
    assert "fx-csv-pick" not in page, "an unknown-format row stays excluded"
    rendered = client.get("/analyse", params={"capture": "fx-raw-pick"}).text
    assert '"x_unit": "sample index"' in rendered
    assert 'data-bw-axes="sample index;byte value"' in rendered


# --- A13: the power family with a byte plane present -------------------------


def test_a13_power_family_with_a_byte_source_present(seam, capture_root) -> None:
    """A13: no crash; the byte source forms no rail (byte planes are
    neither currents nor voltages); a raw-only power request answers the
    EXISTING power_unavailable reason."""
    write_raw(capture_root, "fx-raw-power", _RAW_BYTES)
    write_waveform(capture_root, "fx-v-power", (3.0, 3.1), unit="V")
    entries, power = seam.analysis_view(
        ["fx-raw-power"], None, None, power={"mode": "battery"}
    )
    assert len(entries) == 1, "the raw source itself renders"
    assert power is not None and power.unavailable == "power_unavailable: no current series"
    with pytest.raises(SeamError) as caught:
        seam.analysis_view(
            ["fx-raw-power"],
            None,
            None,
            power={"mode": "battery", "rails": [{"i": "fx-raw-power"}]},
        )
    assert "standalone_report_power_rails" in caught.value.message


# --- A14: the write path is untouched ----------------------------------------


def test_a14_the_manifest_asymmetry_is_the_corpus_shape(tmp_path: Path) -> None:
    """A14: through the real writer — a waveform manifest carries the
    three timing fields; a raw_binary manifest carries none of them (the
    vendored captureManifest requires them only under waveform_f64le).
    Nobody 'fixes' the asymmetry here: the manifest was never the liar."""
    host = lifecycle_seam(tmp_path)
    wave = publish(host, _start("waveform_f64le", 4))
    raw = publish(host, _start("raw_binary", 4))
    wave_manifest = json.loads(
        (tmp_path / "captures" / wave["capture_id"] / "manifest.json").read_text()
    )
    raw_manifest = json.loads(
        (tmp_path / "captures" / raw["capture_id"] / "manifest.json").read_text()
    )
    assert wave_manifest["sample_count"] == 4
    assert wave_manifest["sample_interval_s"] == 0.001
    assert wave_manifest["unit"] == "V"
    assert "sample_count" not in raw_manifest
    assert "sample_interval_s" not in raw_manifest
    assert "unit" not in raw_manifest
    assert raw_manifest["byte_length"] == 32
