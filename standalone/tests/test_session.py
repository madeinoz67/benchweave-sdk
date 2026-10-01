"""The loader's refusals and the adapter lifecycle (REG-1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchweave_standalone.session import (
    HostOperationContext,
    PluginLoadError,
    PluginSession,
    load_plugin_project,
    mock_exchanges,
)


def test_loader_reads_the_starter(plugin) -> None:
    assert plugin.package == "example_plugin"
    assert plugin.has_presentation
    assert plugin.plugin_version == "0.1.0"
    names = [row["name"] for row in plugin.readable_parameters]
    assert names == ["voltage"]


def test_loader_digests_the_descriptor_bytes(plugin, starter_project: Path) -> None:
    import hashlib

    raw = (starter_project / "src" / "example_plugin" / "descriptor.json").read_bytes()
    assert plugin.descriptor_sha256 == hashlib.sha256(raw).hexdigest()


def test_loader_refuses_a_project_without_src(tmp_path: Path) -> None:
    with pytest.raises(PluginLoadError, match="standalone_plugin_project:"):
        load_plugin_project(tmp_path)


def _private_starter(tmp_path: Path) -> Path:
    """A dedicated scaffold for mutating tests (the shared module fixture
    must stay pristine for the rest of the module)."""
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "private"
    create_project(project, "example_plugin")
    create_ui_resources(project, "example_plugin")
    return project


def test_loader_refuses_an_invalid_descriptor(tmp_path: Path) -> None:
    project = _private_starter(tmp_path)
    descriptor = project / "src" / "example_plugin" / "descriptor.json"
    document = json.loads(descriptor.read_text())
    document.pop("operations")
    descriptor.write_text(json.dumps(document))
    with pytest.raises(PluginLoadError, match="standalone_plugin_invalid:"):
        load_plugin_project(project)


def test_loader_refuses_a_tampered_presentation(tmp_path: Path) -> None:
    project = _private_starter(tmp_path)
    package = project / "src" / "example_plugin"
    manifest = package / "ui" / "manifest.json"
    document = json.loads(manifest.read_text())
    document["plugin_id"] = "something.else"
    manifest.write_text(json.dumps(document))
    with pytest.raises(PluginLoadError, match="standalone_plugin_invalid:"):
        load_plugin_project(project)


def test_context_deadline_comes_from_the_declared_timeout() -> None:
    before = __import__("time").monotonic()
    context = HostOperationContext("op", timeout_ms=250)
    after = __import__("time").monotonic()
    assert before + 0.25 <= context.deadline_monotonic <= after + 0.25
    assert context.dataset_id is None
    assert not context.dispatched
    assert not context.is_cancelled()


def test_context_cancel_and_dispatch_marker() -> None:
    import asyncio

    context = HostOperationContext("op", timeout_ms=1000)
    context.cancel()
    assert context.is_cancelled()
    asyncio.run(context.mark_dispatch_started())
    assert context.dispatched


def test_lifecycle_open_execute_close(plugin, mock_host) -> None:
    import asyncio

    session = PluginSession(plugin, mock_host)
    assert not session.connected
    asyncio.run(session.connect())
    assert session.connected
    envelope = asyncio.run(session.execute("read", {"parameter": "voltage"}))
    assert envelope["status"] == "ok"
    assert envelope["data"]["value"] == 3.3
    asyncio.run(session.close())
    assert not session.connected
    asyncio.run(session.close())  # idempotent-tolerant


def test_execute_refuses_before_open(plugin, mock_host) -> None:
    import asyncio

    session = PluginSession(plugin, mock_host)
    with pytest.raises(RuntimeError, match="standalone_session_not_open"):
        asyncio.run(session.execute("read", {"parameter": "voltage"}))


def test_verb_timeout_comes_from_the_descriptor(plugin, mock_host) -> None:
    session = PluginSession(plugin, mock_host)
    assert session.verb_timeout_ms("identify") == 1000
    assert session.verb_timeout_ms("read") == 1000
    with pytest.raises(KeyError, match="standalone_verb_unbounded"):
        session.verb_timeout_ms("self_test")


def test_mock_exchanges_derive_from_the_plugin_evidence(plugin) -> None:
    script = mock_exchanges(plugin)
    assert [exchange[0]["data"] for exchange in script] == [b"ID?\n", b"V?\n"]
    assert all(exchange[0]["max_bytes"] == 128 for exchange in script)
