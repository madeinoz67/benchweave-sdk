"""Bounded loopback HTTP server for deterministic SDK UI previews."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import mimetypes
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.parse import unquote, urlsplit

from .preview_models import PREVIEW_API_VERSION, PreviewModel, PreviewScenario

MAX_REQUEST_BYTES = 64 * 1024


def verify_bundled_assets(root: Path) -> None:
    """Verify the packaged renderer against its inventory before serving it.

    The build hook checks these hashes when the wheel is assembled; this closes
    the gap between install-time and serve-time, where a same-venv build backend
    could otherwise swap the rendered bytes silently.
    """
    try:
        inventory = json.loads((root / "inventory.json").read_bytes())
        assets = inventory["assets"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("preview_renderer_inventory_invalid") from exc
    if inventory.get("api_version") != 1 or not isinstance(assets, list) or not assets:
        raise ValueError("preview_renderer_inventory_invalid")
    for asset in assets:
        relative = PurePosixPath(str(asset.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
            raise ValueError(f"preview_renderer_asset_unsafe: {relative}")
        content = (root / relative).read_bytes()
        if (
            len(content) != asset.get("size")
            or hashlib.sha256(content).hexdigest() != asset.get("sha256")
        ):
            raise ValueError(f"preview_renderer_asset_tampered: {relative}")


def bundled_assets() -> Path:
    """Return the version-matched renderer root included in the SDK package."""
    root = Path(__file__).with_name("preview_assets")
    verify_bundled_assets(root)
    return root / "site"


def validate_listener(host: str, allow_network: bool) -> None:
    """Reject wildcard listeners and require acknowledgement outside loopback."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError(f"preview_invalid_listener: {host}") from exc
    if address.is_unspecified:
        raise ValueError(f"preview_unsafe_listener: wildcard address {host} is prohibited")
    if not address.is_loopback and not allow_network:
        raise ValueError(
            f"preview_network_acknowledgement_required: {host} requires --allow-network"
        )


@dataclass(frozen=True, slots=True)
class PreviewAddress:
    host: str
    port: int

    @property
    def url(self) -> str:
        bracketed = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{bracketed}:{self.port}"


class _PreviewHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def _handler(
    model: PreviewModel,
    assets: Path,
    allowed_origin: str | None = None,
) -> type[BaseHTTPRequestHandler]:
    scenarios = {scenario.id: scenario for scenario in model.scenarios}

    class Handler(BaseHTTPRequestHandler):
        server_version = "BenchWeavePreview/1"

        def log_message(self, format: str, *args: object) -> None:
            return

        def _host_is_trusted(self) -> bool:
            """Reject DNS-rebinding: the Host header must name this listener."""
            bound_address = cast(tuple[Any, ...], self.server.server_address)
            bound_host, bound_port = bound_address[0], bound_address[1]
            try:
                bound_loopback = ipaddress.ip_address(str(bound_host)).is_loopback
            except ValueError:
                bound_loopback = False
            header = self.headers.get("Host", "")
            if header.startswith("["):
                closing = header.find("]")
                if closing < 0:
                    return False
                name = header[1:closing]
                port = header[closing + 1 :].lstrip(":")
            else:
                name, separator, port = header.partition(":")
                if not separator:
                    return False
            if not port.isdigit() or int(port) != int(bound_port):
                return False
            if name.lower() == "localhost":
                return bound_loopback
            try:
                return ipaddress.ip_address(name).is_loopback and bound_loopback
            except ValueError:
                return name == str(bound_host)

        def _reject_untrusted_host(self) -> bool:
            if self._host_is_trusted():
                return False
            self._send_json({"error": "invalid_host"}, HTTPStatus.FORBIDDEN)
            return True

        def _send_json(self, document: object, status: HTTPStatus = HTTPStatus.OK) -> None:
            raw = json.dumps(document, allow_nan=False, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            if allowed_origin and self.headers.get("Origin") == allowed_origin:
                self.send_header("Access-Control-Allow-Origin", allowed_origin)
                self.send_header("Vary", "Origin")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _not_found(self) -> None:
            self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

        def do_GET(self) -> None:  # noqa: N802
            if self._reject_untrusted_host():
                return
            path = urlsplit(self.path).path
            if path == "/healthz":
                self._send_json({"ready": True, "api_version": PREVIEW_API_VERSION})
                return
            if path == "/api/v1/preview":
                self._send_json(model.to_document())
                return
            if path == "/api/v1/scenarios":
                self._send_json(
                    [
                        {"id": row.id, "title": row.title, "baseline": row.baseline}
                        for row in model.scenarios
                    ]
                )
                return
            prefix = "/api/v1/scenarios/"
            if path.startswith(prefix):
                scenario = scenarios.get(unquote(path.removeprefix(prefix)))
                if scenario is None:
                    self._not_found()
                else:
                    self._send_json(scenario.to_document())
                return
            self._serve_asset(path)

        def do_OPTIONS(self) -> None:  # noqa: N802
            if self._reject_untrusted_host():
                return
            if allowed_origin and self.headers.get("Origin") == allowed_origin:
                self.send_response(HTTPStatus.NO_CONTENT)
                self.send_header("Access-Control-Allow-Origin", allowed_origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self._send_json({"error": "origin_not_allowed"}, HTTPStatus.FORBIDDEN)

        def _serve_asset(self, request_path: str) -> None:
            relative = unquote(request_path).lstrip("/") or "index.html"
            pure = PurePosixPath(relative)
            # A backslash is inert in PurePosixPath but a separator on Windows;
            # reject it here so the guard means the same thing on every platform.
            if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
                self._not_found()
                return
            target = assets.joinpath(*pure.parts)
            try:
                raw = target.read_bytes()
            except (FileNotFoundError, IsADirectoryError, OSError):
                self._not_found()
                return
            media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", media_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self) -> None:  # noqa: N802
            if self._reject_untrusted_host():
                return
            prefix = "/api/v1/scenarios/"
            suffix = "/requests"
            path = urlsplit(self.path).path
            if not path.startswith(prefix) or not path.endswith(suffix):
                self._not_found()
                return
            scenario_id = unquote(path[len(prefix) : -len(suffix)]).rstrip("/")
            scenario = scenarios.get(scenario_id)
            if scenario is None:
                self._not_found()
                return
            length = self.headers.get("Content-Length")
            if length is None or not length.isdigit() or int(length) > MAX_REQUEST_BYTES:
                self._send_json({"error": "invalid_request_size"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                document = json.loads(self.rfile.read(int(length)))
                binding_id = document["binding_id"]
            except (json.JSONDecodeError, KeyError, TypeError):
                self._send_json({"error": "invalid_request"}, HTTPStatus.BAD_REQUEST)
                return
            receipt = _receipt(scenario, binding_id)
            if receipt is None:
                self._send_json({"error": "unknown_binding"}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json({**receipt.to_document(), "simulated": True})

    return Handler


def _receipt(scenario: PreviewScenario, binding_id: object) -> Any | None:
    if not isinstance(binding_id, str):
        return None
    return next((row for row in scenario.request_outcomes if row.binding_id == binding_id), None)


class PreviewServer:
    """Run a preview server in a managed background thread."""

    def __init__(
        self,
        model: PreviewModel,
        assets: Path,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        allow_network: bool = False,
        allowed_origin: str | None = None,
    ) -> None:
        validate_listener(host, allow_network)
        if not assets.joinpath("index.html").is_file():
            raise ValueError(f"preview_assets_missing: {assets / 'index.html'}")
        self._server = _PreviewHTTPServer((host, port), _handler(model, assets, allowed_origin))
        bound_host, bound_port = self._server.server_address[:2]
        self.address = PreviewAddress(str(bound_host), int(bound_port))
        self._thread: threading.Thread | None = None

    def start(self) -> PreviewAddress:
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="benchweave-preview",
                daemon=True,
            )
            self._thread.start()
        return self.address

    def wait(self) -> None:
        """Block until shutdown while the background server remains responsive."""
        if self._thread is None:
            raise RuntimeError("preview_server_not_started")
        self._thread.join()

    def shutdown(self) -> None:
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=2)
            self._thread = None
        self._server.server_close()

    def __enter__(self) -> PreviewAddress:
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.shutdown()
