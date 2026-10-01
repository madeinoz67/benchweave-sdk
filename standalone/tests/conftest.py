"""Shared fixtures: a freshly scaffolded starter plugin per module, a seam
and app per test. macOS note: everything scaffolds under canonical
``/private`` paths — the SDK's bounded reader refuses symlinked components,
and ``/tmp`` is one on this platform.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from benchweave_sdk.presentation import create_ui_resources
from benchweave_sdk.scaffold import create_project
from fastapi.testclient import TestClient

from benchweave_standalone.seam import StandaloneSeam
from benchweave_standalone.security import GuardPolicy, new_token
from benchweave_standalone.session import PluginSession, load_plugin_project, mock_exchanges
from benchweave_standalone.transport import LoopingMockHost
from benchweave_standalone.web import build_app

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
def seam(plugin, mock_host) -> StandaloneSeam:
    return StandaloneSeam(PluginSession(plugin, mock_host), transport_kind="mock")


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
