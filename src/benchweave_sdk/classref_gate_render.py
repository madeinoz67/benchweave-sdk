"""The gate's render half: the standalone host over in-process ASGI.

Lives apart from the gate core so the SDK core never imports the server
package on the import path; ``verify-ui`` requires the ``[server]`` extra
(the preview-ui precedent)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def render_pages(project: Path, page_ids: list[str]) -> dict[str, str]:
    """Serve one plugin project in-process and return each page's HTML."""
    try:
        from starlette.testclient import TestClient
    except ImportError as exc:  # pragma: no cover - the extras-missing case
        raise ValueError(
            "benchweave_sdk_server_extras_missing: install 'benchweave-sdk[server]' "
            "for verify-ui"
        ) from exc

    def raw(document: dict[str, Any]) -> bytes:
        return (json.dumps(document, indent=2) + "\n").encode()

    from benchweave_sdk_server.seam import StandaloneSeam
    from benchweave_sdk_server.session import (
        PluginSession,
        load_plugin_project,
        mock_exchanges,
    )
    from benchweave_sdk_server.transport import LoopingMockHost
    from benchweave_sdk_server.web import build_app

    package_dir = next(
        (path for path in (project / "src").iterdir() if path.is_dir()), None
    )
    if package_dir is None:
        raise ValueError(f"classref_gate_project: no package under {project / 'src'}")
    plugin = load_plugin_project(project)
    descriptor = json.loads((package_dir / "descriptor.json").read_bytes())
    seam = StandaloneSeam(
        PluginSession(plugin, lambda: LoopingMockHost(mock_exchanges(plugin))),
        transport_kind="mock",
    )
    from benchweave_sdk_server.security import GuardPolicy, new_token

    policy = GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )
    html_by_page: dict[str, str] = {}
    with TestClient(build_app(seam, policy=policy), base_url="http://127.0.0.1:8477") as client:
        for page_id in page_ids:
            response = client.get(f"/pages/{page_id}")
            html_by_page[page_id] = response.text
    return html_by_page
