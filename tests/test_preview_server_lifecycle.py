"""Preview server lifecycle: idempotent shutdown, no restart after close."""

from __future__ import annotations

import pytest

from benchweave_sdk.preview_models import PreviewModel
from benchweave_sdk.preview_server import PreviewServer, bundled_assets


def _server() -> PreviewServer:
    model = PreviewModel(plugin_id="demo", renderer_version="0", pages=(), scenarios=())
    return PreviewServer(model, bundled_assets())


def test_shutdown_is_idempotent() -> None:
    server = _server()
    server.start()
    server.shutdown()
    server.shutdown()  # TUI quit + CLI finally both land here; must not raise


def test_shutdown_without_start() -> None:
    server = _server()
    server.shutdown()


def test_start_after_shutdown_is_refused() -> None:
    server = _server()
    server.start()
    server.shutdown()
    with pytest.raises(RuntimeError, match="preview_server_closed"):
        server.start()
