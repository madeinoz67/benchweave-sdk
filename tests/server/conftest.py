"""Shared fixtures: a freshly scaffolded starter plugin per module, a seam
and app per test. macOS note: everything scaffolds under canonical
``/private`` paths — the SDK's bounded reader refuses symlinked components,
and ``/tmp`` is one on this platform.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk.presentation import create_ui_resources
from benchweave_sdk.scaffold import create_project
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.session import PluginSession, load_plugin_project, mock_exchanges
from benchweave_sdk_server.transport import LoopingMockHost
from benchweave_sdk_server.web import build_app

TEST_PORT = 8477
TEST_HOST = "127.0.0.1"


@pytest.fixture(scope="module")
def starter_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A ``--with-ui`` scaffolded starter plugin, once per test module."""
    root = tmp_path_factory.mktemp("starter")
    project = root / "starter"
    create_project(project, "example_plugin")
    create_ui_resources(project, "example_plugin")
    return project


@pytest.fixture()
def plugin(starter_project: Path):
    return load_plugin_project(starter_project)


@pytest.fixture()
def mock_host(plugin) -> LoopingMockHost:
    return LoopingMockHost(mock_exchanges(plugin))


@pytest.fixture()
def seam(plugin) -> StandaloneSeam:
    # mock_plugin_session: the factory reads the CURRENT plugin at connect
    # time (the reload-honest late-bound shape; a closure over the original
    # plugin would keep serving the previous version's script after a
    # reload swapped it). capture_root: the library ops (list/get/series/
    # annotate/pin/unpin/delete/artifact_read) are transport-independent —
    # every seam serves them; capture_start itself still needs capture-
    # capable services (the mock transport's host does not implement them,
    # so it refuses unavailable there — pinned by the lifecycle tests).
    import tempfile
    from pathlib import Path

    from benchweave_sdk_server.session import mock_plugin_session

    with tempfile.TemporaryDirectory() as tmp:
        yield StandaloneSeam(
            mock_plugin_session(plugin),
            transport_kind="mock",
            capture_root=Path(tmp),
        )


@pytest.fixture()
def seam_from(starter_project):
    """A seam factory over any project root: loads it fresh each call."""

    def _build(project: Path, **kwargs) -> StandaloneSeam:
        loaded = load_plugin_project(Path(project))
        return StandaloneSeam(
            PluginSession(loaded, lambda: LoopingMockHost(mock_exchanges(loaded))),
            transport_kind="mock",
            **kwargs,
        )

    return _build


@pytest.fixture()
def policy() -> GuardPolicy:
    return GuardPolicy.complete(
        bound_host=TEST_HOST,
        bound_port=TEST_PORT,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )


@pytest.fixture()
def app(seam, policy):
    return build_app(seam, policy=policy)


@pytest.fixture()
def client(app):
    """A context-managed client: the app lifespan (FastMCP's task group)
    must run or every /mcp request 500s."""
    with TestClient(app, base_url=f"http://{TEST_HOST}:{TEST_PORT}") as entered:
        yield entered
