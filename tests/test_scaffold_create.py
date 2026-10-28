"""The scaffolder either completes a project or leaves nothing behind."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchweave_sdk.scaffold import create_project


def test_create_project_completes(tmp_path: Path) -> None:
    destination = tmp_path / "demo"
    create_project(destination, "demo_plugin")
    assert (destination / "pyproject.toml").is_file()
    assert (destination / "src/demo_plugin/descriptor.json").is_file()
    assert not destination.with_name("demo.partial").exists()


def test_create_project_refuses_existing_destination(tmp_path: Path) -> None:
    destination = tmp_path / "demo"
    destination.mkdir()
    with pytest.raises(FileExistsError):
        create_project(destination, "demo_plugin")


def test_create_project_refuses_dangling_symlink_destination(tmp_path: Path) -> None:
    # exists() is False for a dangling symlink, but the name is taken and the
    # final rename would fail mid-flight; refuse it up front, as documented.
    destination = tmp_path / "demo"
    try:
        destination.symlink_to(tmp_path / "nowhere")
    except OSError:
        pytest.skip("symlinks unavailable (privilege or filesystem)")
    # The full prefix, not "already exists": on Windows the rename this guard
    # pre-empts fails with WinError 183, whose text also says "already exists".
    with pytest.raises(FileExistsError, match="^Destination already exists: "):
        create_project(destination, "demo_plugin")
    assert destination.is_symlink(), "the link itself must be left alone"


def test_create_project_refuses_an_existing_staging_path_and_leaves_it_alone(
    tmp_path: Path,
) -> None:
    """A leftover ``.partial`` sibling is not ours to delete: it may be the user's own directory."""
    destination = tmp_path / "demo"
    staging = tmp_path / "demo.partial"
    staging.mkdir()
    (staging / "notes.txt").write_text("the user's own file", encoding="utf-8")
    with pytest.raises(FileExistsError, match="^Staging path already exists: "):
        create_project(destination, "demo_plugin")
    assert (staging / "notes.txt").read_text(encoding="utf-8") == "the user's own file"
    assert not destination.exists()


def test_interrupted_generation_leaves_no_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Re-anchored at the render entry (issue #347 WS2): copier, not
    # Path.write_text, does the writing now, so the old write-text injection
    # points at nothing (proven: it stopped raising the day of the port).
    # The seam is the copier loader create_project calls; failing inside the
    # render still exercises staging creation, cleanup, and no destination.
    import benchweave_sdk.scaffold as scaffold

    def failing_run_copy(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    destination = tmp_path / "demo"
    monkeypatch.setattr(scaffold, "_load_copier", lambda: failing_run_copy)
    with pytest.raises(OSError, match="disk full"):
        create_project(destination, "demo_plugin")
    assert not destination.exists()
    assert not destination.with_name("demo.partial").exists()


def test_reserved_package_name_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_project(tmp_path / "x", "benchweave_sdk")


def test_provider_transport_scaffold_pins_the_banked_contract(tmp_path: Path) -> None:
    """Row f (issue #568, owner directive 2026-10-28): ``new
    --provider-transport`` emits a provider-declaring plugin — the custom
    transport with the banked FTDI control contract pinned byte-exactly,
    no vectors.json (the mock cannot rehearse provider kinds — the honest
    posture), and a conversation that serves on ``--transport ftdi`` over
    the shipped driver double."""
    import json

    destination = tmp_path / "prov"
    create_project(destination, "example_plugin", provider_transport=True)
    package = destination / "src" / "example_plugin"
    descriptor = json.loads((package / "descriptor.json").read_text())
    assert descriptor["transport"]["type"] == "custom"
    pin = descriptor["transport"]["provider"]
    assert pin["feature_id"].startswith("otdp.transport.ftdi-control/")
    # The pinned bytes are the BANKED contract, byte-equal.
    import hashlib

    from benchweave_sdk.validation import verify_provider_pin

    banked = Path(__file__).resolve().parents[1] / (
        "src/benchweave_sdk/providers/ftdi-control-1.1.0.json"
    )
    pinned_bytes = (package / pin["path"]).read_bytes()
    assert pinned_bytes == banked.read_bytes()
    assert hashlib.sha256(pinned_bytes).hexdigest() == pin["sha256"]
    assert verify_provider_pin(descriptor, package / "descriptor.json") is not None
    # The provider shape ships a provider-dialect vectors.json (issue
    # #570's ruling): the mock rehearses the bring-up at the transaction
    # boundary from the plugin's own corpus.
    corpus = json.loads((package / "vectors.json").read_text())
    assert corpus["transaction_dialect"] == "provider"
    assert len(corpus["exchanges"]) >= 9


def test_provider_transport_scaffold_rehearses_on_the_double(tmp_path: Path) -> None:
    """The provider scaffold's own rehearsal story: the generated plugin
    serves on ``--transport ftdi`` over the SHIPPED driver double, driven
    through the production session — the row-f answer to the mock-parity
    question (no third vectors dialect; the double at the driver
    boundary)."""
    import asyncio
    import base64
    import sys

    destination = tmp_path / "prov"
    create_project(destination, "example_plugin", provider_transport=True)
    # Evict any example_plugin cached from ANOTHER project's src (the
    # starter-project fixtures use the same package name): the import must
    # resolve THIS project's provider-shaped bytes, never a cached twin.
    for name in [m for m in sys.modules if m.startswith("example_plugin")]:
        del sys.modules[name]
    sys.path.insert(0, str(destination / "src"))
    try:
        import example_plugin.protocol as proto
    finally:
        sys.path.remove(str(destination / "src"))
        for name in [m for m in sys.modules if m.startswith("example_plugin")]:
            del sys.modules[name]

    from benchweave_sdk_server.ftdi import ScriptedFtdiDriver, ftdi_plugin_session
    from benchweave_sdk_server.session import load_plugin_project

    script = [
        {"name": "reset", "transaction": proto.reset_device(), "response": {}},
        {"name": "purge", "transaction": proto.purge_rx(), "response": {}},
        {"name": "latency", "transaction": proto.set_latency(), "response": {}},
        {"name": "baud", "transaction": proto.set_baud(), "response": {}},
        {"name": "bitmode", "transaction": proto.set_bitmode(), "response": {}},
        {
            "name": "pins-idle",
            "transaction": proto.read_pins(),
            "response": {"data": base64.b64encode(bytes([proto.PINS_IDLE])).decode()},
        },
        {
            "name": "bitstream",
            "transaction": proto.stream_send(proto.BITSTREAM_CHUNK),
            "response": {},
        },
        {
            "name": "pins-done",
            "transaction": proto.read_pins(),
            "response": {"data": base64.b64encode(bytes([proto.DONE_BYTE])).decode()},
        },
        {
            "name": "status",
            "transaction": proto.status_exchange(),
            "response": {"data": proto.STATUS_REPLY.hex()},
        },
    ]
    plugin = load_plugin_project(destination)
    driver = ScriptedFtdiDriver(script)
    session = ftdi_plugin_session(
        plugin, "ftdi://::0x0403:0x6001/1", driver_factory=lambda url: driver
    )
    asyncio.run(session.connect())
    read = asyncio.run(session.execute("read", {"parameter": "line_status"}))
    assert read["status"] == "ok", read
    asyncio.run(session.close())
