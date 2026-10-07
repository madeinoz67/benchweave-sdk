# author: Stephen Eaton
"""Claim probes: one cell per manifest row, each emitting a trace artifact.

The shadow claim-conformance lane's evidence layer (design record
``.claude/deep-review/2026-10-07-claim-lane-shadow-design.md``). Every cell
exercises REAL documented behavior over the suite's established doubles and
records a trace artifact — neutral past-tense observation sentences that
describe WHAT WAS OBSERVED, never whether it agrees with the claim. That
neutrality is load-bearing: the trace-vs-excerpt experiment's clean score
separation came from neutral traces, so the artifact passes
``claim_lane.validate_trace`` before it is written.

The cells run as ordinary suite tests; the artifacts only land when
``CLAIM_LANE_ARTIFACT_ROOT`` names a directory (the shadow runner wires
that). The observations double as the cell's documentation of observed
state.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.capture import StandaloneCaptureWriter
from benchweave_sdk.scaffold import create_project
from benchweave_sdk_server.serial import (
    SerialCaptureServices,
    SerialLink,
    negotiable_bauds,
)
from benchweave_sdk_server.session import HostOperationContext

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT_ENV = "CLAIM_LANE_ARTIFACT_ROOT"

_BOOT = {"baud": 115200, "parity": "none", "rtscts": False}
_DECLARED = {**_BOOT, "x-negotiated-bauds": [3_000_000]}


def _lane() -> Any:
    spec = importlib.util.spec_from_file_location(
        "claim_lane_probes", ROOT / "scripts" / "claim_lane.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _recorder() -> Callable[[str, list[str]], None]:
    """The trace writer the fixture hands each cell: validate, then persist
    under the artifact root when one is wired."""
    lane = _lane()
    root = os.environ.get(ARTIFACT_ROOT_ENV)
    root_path = Path(root) if root else None

    def record(claim_id: str, observations: list[str]) -> None:
        artifact = {"claim_id": claim_id, "observations": observations}
        lane.validate_trace(artifact, expected_id=claim_id)
        if root_path is None:
            return
        root_path.mkdir(parents=True, exist_ok=True)
        (root_path / f"{claim_id}.json").write_text(
            json.dumps(artifact, indent=2), encoding="utf-8"
        )

    return record


@pytest.fixture()
def claim_trace() -> Callable[[str, list[str]], None]:
    return _recorder()


def _ctx(timeout_s: float = 2.0) -> HostOperationContext:
    return HostOperationContext(
        f"probe-{uuid.uuid4().hex[:8]}", timeout_ms=int(timeout_s * 1000)
    )


class _Port:
    """pyserial's surface over an in-process buffer (the serial suite's
    own double shape, minimized for the probe cells)."""

    def __init__(self) -> None:
        self.inbound = bytearray()
        self.written: list[bytes] = []
        self.closes = 0
        self._data = threading.Event()

    def write(self, data: bytes) -> int | None:
        self.written.append(bytes(data))
        self._data.set()
        return len(data)

    def read(self, size: int = 1) -> bytes:
        if not self.inbound and not self._data.wait(0.05):
            return b""
        out = bytes(self.inbound[:size])
        del self.inbound[:size]
        return out

    def close(self) -> None:
        self.closes += 1
        self._data.set()


class _Candidate:
    """A list_ports-shaped candidate: device plus USB identity."""

    def __init__(self, device: str, vid: int | None, pid: int | None) -> None:
        self.device = device
        self.vid = vid
        self.pid = pid


_MATCHING_IDENTITY = b"SDK Example,demo,SIM001,1.0.0\n"
_FOREIGN_IDENTITY = b"Other Vendor,other,X999,9.9\n"


def _scan_project(tmp_path: Path, vid: Any) -> Any:
    """A scaffolded plugin whose descriptor declares the given USB hint."""
    from benchweave_sdk_server.session import load_plugin_project

    project = tmp_path / "proj"
    create_project(project, "example_plugin")
    descriptor_path = project / "src" / "example_plugin" / "descriptor.json"
    document = json.loads(descriptor_path.read_text())
    document["transport"]["settings"]["x-standalone-usb-vid"] = vid
    descriptor_path.write_text(json.dumps(document))
    return load_plugin_project(project)


def _scan_hooks() -> tuple[Any, dict[str, _Port], list[str]]:
    """Four openable candidates plus one whose vendor id differs from the
    declared hint (the discovery suite's AR-4 fixture shape)."""
    from benchweave_sdk_server.serial import SerialPortHooks

    ports = {
        "/dev/match-a": _replying_port(_MATCHING_IDENTITY),
        "/dev/match-b": _replying_port(_MATCHING_IDENTITY),
        "/dev/foreign": _replying_port(_FOREIGN_IDENTITY),
        "/dev/silent": _Port(),
    }
    candidates = [
        _Candidate("/dev/match-a", 0x1A86, 0x7523),
        _Candidate("/dev/match-b", 0x1A86, 0x7523),
        _Candidate("/dev/foreign", 0x1A86, 0x0002),
        _Candidate("/dev/silent", 0x1A86, 0x0003),
        _Candidate("/dev/other-vendor", 0x10C4, 0xEA60),
    ]
    opened: list[str] = []

    def open_port(device: str, settings: dict[str, Any]) -> _Port:
        opened.append(device)
        return ports[device]

    hooks = SerialPortHooks(
        enumerate_ports=lambda: list(candidates), open_port=open_port
    )
    return hooks, ports, opened


def _replying_port(identity: bytes) -> _Port:
    port = _Port()

    def write(data: bytes) -> int | None:
        port.written.append(bytes(data))
        if bytes(data) == b"ID?\n":
            port.inbound += identity
            port._data.set()  # noqa: SLF001 - same-file test double
        return len(data)

    port.write = write  # type: ignore[method-assign]
    return port


def _reconfigure_services(
    opener: Callable[..., _Port], settings: dict[str, Any]
) -> SerialCaptureServices:
    from benchweave_sdk_server.serial import LinkReconfigurator

    link = SerialLink(opener("/dev/fake0", settings))
    reconfigurator = LinkReconfigurator(
        opener=opener,
        device_path="/dev/fake0",
        boot_settings=dict(settings),
        allowed_bauds=negotiable_bauds(settings),
        on_link_event=None,
    )
    return SerialCaptureServices(
        link, max_frame_bytes=4096, reconfigurator=reconfigurator
    )


def _waveform_metadata(sample_count: int) -> dict[str, Any]:
    return {
        "format": "waveform_f64le",
        "started_at": "2026-10-07T00:00:00Z",
        "sample_count": sample_count,
        "sample_interval_s": 0.001,
        "unit": "V",
    }


# --- the probe cells (one per manifest row) -------------------------------


@pytest.mark.claim_probe
def test_claim_scan_hint_filter(
    tmp_path: Path, claim_trace: Callable[[str, list[str]], None]
) -> None:
    from benchweave_sdk_server.serial import discover_serial_devices

    plugin = _scan_project(tmp_path, "1a86")
    hooks, ports, opened = _scan_hooks()
    devices = asyncio.run(discover_serial_devices(plugin, hooks=hooks))

    frames = [frame for port in ports.values() for frame in port.written]
    assert opened == ["/dev/match-a", "/dev/match-b", "/dev/foreign", "/dev/silent"]
    assert all(frame == b"ID?\n" for frame in frames) and len(frames) == 4
    assert [row["id"] for row in devices] == ["example_device", "example_device"]

    claim_trace(
        "scan-hint-filter",
        [
            "The scan opened four candidate ports, in the order /dev/match-a, "
            "/dev/match-b, /dev/foreign and /dev/silent.",
            "Each opened port received exactly one identify frame and nothing else.",
            "The candidate whose USB vendor id differed from the declared hint "
            "was never opened.",
            "The scan returned two devices, both carrying the identity fields "
            "the descriptor declares.",
        ],
    )


@pytest.mark.claim_probe
def test_claim_scan_unparseable_hint(
    tmp_path: Path, claim_trace: Callable[[str, list[str]], None]
) -> None:
    from benchweave_sdk_server.serial import SerialPortHooks, discover_serial_devices

    plugin = _scan_project(tmp_path, "zz")
    hooks = SerialPortHooks(
        enumerate_ports=lambda: [], open_port=lambda device, settings: None
    )
    with pytest.raises(ValueError) as excinfo:
        asyncio.run(discover_serial_devices(plugin, hooks=hooks))
    assert "zz" in str(excinfo.value)

    claim_trace(
        "scan-unparseable-hint",
        [
            "A descriptor declaring x-standalone-usb-vid 'zz' made the scan "
            "raise a ValueError.",
            "The refusal message named the declared value 'zz'.",
        ],
    )


@pytest.mark.claim_probe
def test_claim_capture_abort_id_reuse(
    tmp_path: Path, claim_trace: Callable[[str, list[str]], None]
) -> None:
    services = SerialCaptureServices(
        SerialLink(_Port()),
        max_frame_bytes=128,
        capture_root=tmp_path,
        capture_max_bytes=8 * 1024,
    )
    event = tmp_path / "cap-reuse"
    asyncio.run(services.artifact_append("cap-reuse", b"\x01" * (8 * 1024), _ctx()))
    assert event.is_dir(), "a flush at the reservation created the event directory"
    asyncio.run(services.artifact_abort("cap-reuse"))
    assert not event.exists(), "the abort removed the event directory"
    asyncio.run(services.artifact_append("cap-reuse", b"\x07\x08", _ctx()))
    manifest = asyncio.run(
        services.artifact_finalise(
            "cap-reuse",
            {"format": "raw_binary", "started_at": "2026-10-07T00:00:00Z"},
            _ctx(),
        )
    )
    assert manifest["byte_length"] == 2

    claim_trace(
        "capture-abort-id-reuse",
        [
            "An 8192-byte append created the capture's event directory under "
            "the capture root.",
            "The abort removed that event directory.",
            "A new append of two bytes with the same capture id was then accepted.",
            "The capture finalised with a byte_length of 2.",
        ],
    )


@pytest.mark.claim_probe
def test_claim_capture_crash_reserved(
    tmp_path: Path, claim_trace: Callable[[str, list[str]], None]
) -> None:
    capture_root = tmp_path / "captures"
    abandoned = StandaloneCaptureWriter(capture_root)
    asyncio.run(abandoned.artifact_append("cap-crash", b"\x01\x02", _ctx()))
    assert (capture_root / "cap-crash").is_dir()

    survivor = StandaloneCaptureWriter(capture_root)
    with pytest.raises(ValueError, match="capture_id collision"):
        asyncio.run(survivor.artifact_append("cap-crash", b"\x03", _ctx()))

    shutil.rmtree(capture_root)
    fresh = StandaloneCaptureWriter(capture_root)
    asyncio.run(fresh.artifact_append("cap-crash", b"\x04", _ctx()))
    assert (capture_root / "cap-crash").is_dir()

    claim_trace(
        "capture-crash-reserved",
        [
            "An abandoned capture left its event directory under the capture root.",
            "A fresh writer's append with that capture id was refused with a "
            "collision message.",
            "After the capture root was removed, a new writer accepted an "
            "append with the same capture id.",
        ],
    )


@pytest.mark.claim_probe
def test_claim_capture_reservation_crossing(
    tmp_path: Path, claim_trace: Callable[[str, list[str]], None]
) -> None:
    writer = StandaloneCaptureWriter(tmp_path / "captures", max_bytes=1024)
    asyncio.run(writer.artifact_append("cap-limit", b"\x01" * 1000, _ctx()))
    with pytest.raises(ValueError, match="max_bytes reservation") as excinfo:
        asyncio.run(writer.artifact_append("cap-limit", b"\x01" * 100, _ctx()))
    message = str(excinfo.value)
    assert "1024" in message and "1000" in message

    claim_trace(
        "capture-reservation-crossing",
        [
            "A writer with a 1024-byte reservation accepted a 1000-byte append.",
            "A second append of 100 bytes was refused at the append call.",
            "The refusal message reported the reservation of 1024 bytes and "
            "the 1000 bytes already staged.",
        ],
    )


@pytest.mark.claim_probe
def test_claim_negotiated_bauds_validation(
    claim_trace: Callable[[str, list[str]], None]
) -> None:
    for malformed in ([], [0], [True], ["3000000"], "nope"):
        with pytest.raises(ValueError):
            negotiable_bauds({**_BOOT, "x-negotiated-bauds": malformed})
    assert negotiable_bauds(_BOOT) == frozenset({115200})
    assert negotiable_bauds(_DECLARED) == frozenset({115200, 3_000_000})

    claim_trace(
        "negotiated-bauds-validation",
        [
            "Each malformed x-negotiated-bauds value — an empty list, a zero, "
            "a boolean, a string digit and a non-numeric string — produced a "
            "ValueError from the declaration check.",
            "Settings without the declaration produced the allowed baud set "
            "{115200}.",
            "Settings declaring [3000000] produced the allowed baud set "
            "{115200, 3000000}.",
        ],
    )


@pytest.mark.claim_probe
def test_claim_negotiated_switch_undeclared(
    claim_trace: Callable[[str, list[str]], None]
) -> None:
    opens: list[tuple[str, dict[str, Any]]] = []

    def opener(device: str, settings: dict[str, Any]) -> _Port:
        opens.append((device, dict(settings)))
        return _Port()

    plain = _reconfigure_services(opener, _BOOT)
    with pytest.raises(ValueError) as excinfo:
        asyncio.run(plain.reconfigure_link({"baud": 3_000_000}, _ctx()))
    assert "standalone_serial_baud_not_negotiable" in str(excinfo.value)
    assert len(opens) == 1, "a guard refusal performs no I/O"
    assert plain.link_state() == {"baud": 115200, "boot_baud": 115200, "negotiable": False}

    declaring = _reconfigure_services(opener, _DECLARED)
    applied = asyncio.run(declaring.reconfigure_link({"baud": 3_000_000}, _ctx()))
    assert applied["baud"] == 3_000_000

    claim_trace(
        "negotiated-switch-undeclared",
        [
            "Without the x-negotiated-bauds declaration, a switch request to "
            "baud 3000000 was refused.",
            "The refusal carried the prefix standalone_serial_baud_not_negotiable "
            "and performed no port I/O.",
            "The link state reported baud 115200, boot baud 115200 and "
            "negotiable false.",
            "With the declaration present, the same switch request applied "
            "baud 3000000.",
        ],
    )


@pytest.mark.claim_probe
def test_claim_capture_empty_refused(
    tmp_path: Path, claim_trace: Callable[[str, list[str]], None]
) -> None:
    writer = StandaloneCaptureWriter(tmp_path / "captures")
    with pytest.raises(ValueError):
        asyncio.run(writer.artifact_finalise("cap-empty", _waveform_metadata(1), _ctx()))
    assert not (tmp_path / "captures" / "cap-empty").exists()

    claim_trace(
        "capture-empty-refused",
        [
            "A finalise call for a capture with no appended bytes was refused "
            "with a ValueError.",
            "No event directory was left for the refused capture.",
        ],
    )


@pytest.mark.claim_probe
def test_claim_capture_waveform_length(
    tmp_path: Path, claim_trace: Callable[[str, list[str]], None]
) -> None:
    writer = StandaloneCaptureWriter(tmp_path / "captures")
    asyncio.run(writer.artifact_append("cap-wave", b"\x00" * 96, _ctx()))
    with pytest.raises(ValueError, match="sample_count") as excinfo:
        asyncio.run(
            writer.artifact_finalise("cap-wave", _waveform_metadata(11), _ctx())
        )
    assert "11" in str(excinfo.value) and "96" in str(excinfo.value)
    manifest = asyncio.run(
        writer.artifact_finalise("cap-wave", _waveform_metadata(12), _ctx())
    )
    assert manifest["byte_length"] == 96

    claim_trace(
        "capture-waveform-length",
        [
            "A waveform_f64le capture of 96 staged bytes was refused at "
            "finalise with sample_count 11.",
            "The refusal message named both the staged byte count and the "
            "sample_count rule.",
            "The same bytes finalised with sample_count 12 and published a "
            "byte_length of 96.",
        ],
    )


@pytest.mark.claim_probe
def test_claim_capture_env_dir_empty(
    tmp_path: Path,
    claim_trace: Callable[[str, list[str]], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for value in ("", "   "):
        monkeypatch.setenv("BENCHWEAVE_CAPTURE_DIR", value)
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="BENCHWEAVE_CAPTURE_DIR is set but empty"):
            StandaloneCaptureWriter()

    claim_trace(
        "capture-env-dir-empty",
        [
            "With BENCHWEAVE_CAPTURE_DIR set to an empty string, writer "
            "construction was refused with a ValueError.",
            "With the variable set to whitespace only, writer construction "
            "was refused with a ValueError.",
        ],
    )


# --- the lane's own cells (not claim probes) ------------------------------


def test_every_manifest_probe_cell_exists_in_this_file() -> None:
    """AR-2's real-manifest arm: the committed manifest validates against
    the committed probe file."""
    lane = _lane()
    lane.validate_manifest(lane.CLAIMS, probes_root=ROOT)


def test_trace_artifacts_are_schema_valid_and_neutral(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AR-3 end to end: real probe cells run with the artifact root wired;
    every emitted artifact validates and stays neutral."""
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(tmp_path))
    recorder = _recorder()
    test_claim_capture_empty_refused(tmp_path, recorder)
    test_claim_capture_crash_reserved(tmp_path, recorder)
    lane = _lane()
    artifacts = sorted(tmp_path.glob("*.json"))
    assert [path.stem for path in artifacts] == ["capture-crash-reserved", "capture-empty-refused"]
    for path in artifacts:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        assert lane.validate_trace(artifact) == artifact["observations"]
        assert path.read_text(encoding="utf-8").find("TYPESAFE") == -1
