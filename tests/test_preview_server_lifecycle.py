"""Preview server lifecycle: idempotent shutdown, no restart after close."""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

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


def test_colon_in_an_asset_path_is_not_found(tmp_path: Path) -> None:
    """A colon names a drive or an alternate data stream on Windows.

    ``index.html:hidden`` is created as whatever the platform makes of it —
    a stream of index.html on NTFS, a plain file on POSIX — so the file is
    really there and only the guard can answer 404.
    """
    (tmp_path / "index.html").write_text("preview", encoding="utf-8")
    (tmp_path / "index.html:hidden").write_text("hidden", encoding="utf-8")
    model = PreviewModel(plugin_id="demo", renderer_version="0", pages=(), scenarios=())
    server = PreviewServer(model, tmp_path)
    address = server.start()
    try:
        assert urllib.request.urlopen(address.url + "/index.html", timeout=2).read() == b"preview"
        for path in ("/index.html:hidden", "/C:/Windows/win.ini", "/C:index.html"):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(address.url + path, timeout=2)
            assert error.value.code == 404, path
    finally:
        server.shutdown()
