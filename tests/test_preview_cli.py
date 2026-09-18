"""The preview-ui CLI validates first and reports a deterministic local endpoint."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from benchweave_sdk import cli, fixtures, presentation, preview_server


class FakeAddress:
    url = "http://127.0.0.1:49152"


class FakeServer:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs
        self.address = FakeAddress()
        self.started = False
        self.waited = False

    def start(self) -> FakeAddress:
        self.started = True
        return self.address

    def wait(self) -> None:
        self.waited = True

    def shutdown(self) -> None:
        return


def preview_arguments(*extra: str) -> list[str]:
    return [
        "preview-ui",
        "presentation.json",
        "--descriptor",
        "descriptor.json",
        "--resources",
        ".",
        "--catalogue",
        "binding-catalogue.json",
        *extra,
    ]


def test_preview_ui_no_open_reports_ready_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FakeServer()
    model = SimpleNamespace(scenarios=(object(),), renderer_version="0.1.0")
    monkeypatch.setattr(presentation, "load_validated_preview_inputs", lambda *a, **k: object())
    monkeypatch.setattr(fixtures, "build_preview_model", lambda candidate: model)
    monkeypatch.setattr(preview_server, "PreviewServer", lambda *a, **k: server)
    monkeypatch.setattr(preview_server, "bundled_assets", lambda: tmp_path)

    result = CliRunner().invoke(cli.cli, preview_arguments("--no-open"))

    assert result.exit_code == 0
    assert "SIMULATED PRESENTATION DATA" in result.output
    assert server.address.url in result.output
    assert server.started and server.waited


def test_development_renderer_receives_api_base_and_exact_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = FakeServer()
    model = SimpleNamespace(scenarios=(object(),), renderer_version="0.1.0")
    captured: dict[str, object] = {}
    monkeypatch.setattr(presentation, "load_validated_preview_inputs", lambda *a, **k: object())
    monkeypatch.setattr(fixtures, "build_preview_model", lambda candidate: model)
    monkeypatch.setattr(preview_server, "bundled_assets", lambda: tmp_path)
    monkeypatch.setattr(
        preview_server, "PreviewServer", lambda *a, **k: captured.update(k) or server
    )
    opened: list[str] = []

    def record_open(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr(cli.webbrowser, "open", record_open)

    result = CliRunner().invoke(
        cli.cli,
        preview_arguments("--renderer-url", "http://127.0.0.1:5173/preview"),
    )
    assert result.exit_code == 0
    assert captured["allowed_origin"] == "http://127.0.0.1:5173"
    assert opened and "apiBase=http%3A%2F%2F127.0.0.1%3A49152" in opened[0]


def test_preview_ui_rejects_non_loopback_without_acknowledgement() -> None:
    result = CliRunner().invoke(
        cli.cli,
        preview_arguments("--host", "192.0.2.10", "--no-open"),
    )
    assert result.exit_code == 1
    assert "preview_network_acknowledgement_required" in result.output


def test_preview_ui_rejects_non_loopback_renderer_origin() -> None:
    result = CliRunner().invoke(
        cli.cli,
        preview_arguments("--renderer-url", "https://evil.example/r.html", "--no-open"),
    )
    assert result.exit_code == 1
    assert "preview_renderer_origin_not_local" in result.output


def test_preview_ui_rejects_missing_fixtures_directory() -> None:
    result = CliRunner().invoke(
        cli.cli,
        preview_arguments("--fixtures", "does/not/exist", "--no-open"),
    )
    assert result.exit_code == 1
    assert "preview_fixtures_directory_expected" in result.output


def test_preview_ui_survives_browserless_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import webbrowser

    server = FakeServer()
    model = SimpleNamespace(scenarios=(object(),), renderer_version="0.1.0")

    def refusing(url: str) -> bool:
        raise webbrowser.Error("no browser")

    monkeypatch.setattr(presentation, "load_validated_preview_inputs", lambda *a, **k: object())
    monkeypatch.setattr(fixtures, "build_preview_model", lambda candidate: model)
    monkeypatch.setattr(preview_server, "PreviewServer", lambda *a, **k: server)
    monkeypatch.setattr(preview_server, "bundled_assets", lambda: Path("."))
    monkeypatch.setattr(cli.webbrowser, "open", refusing)

    result = CliRunner().invoke(cli.cli, preview_arguments())

    assert result.exit_code == 0
    assert "Browser did not open" in result.output


def test_preview_ui_labels_custom_renderer_output() -> None:
    server = FakeServer()
    model = SimpleNamespace(scenarios=(object(),), renderer_version="0.1.0")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(presentation, "load_validated_preview_inputs", lambda *a, **k: object())
    monkeypatch.setattr(fixtures, "build_preview_model", lambda candidate: model)
    monkeypatch.setattr(preview_server, "PreviewServer", lambda *a, **k: server)
    monkeypatch.setattr(preview_server, "bundled_assets", lambda: Path("."))
    try:
        result = CliRunner().invoke(
            cli.cli,
            preview_arguments("--renderer-url", "http://127.0.0.1:5173/preview", "--no-open"),
        )
    finally:
        monkeypatch.undo()
    assert result.exit_code == 0
    assert "Custom renderer" in result.output
