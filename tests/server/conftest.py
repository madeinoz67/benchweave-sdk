"""Shared fixtures: a freshly scaffolded starter plugin per module, a seam
and app per test. macOS note: everything scaffolds under canonical
``/private`` paths — the SDK's bounded reader refuses symlinked components,
and ``/tmp`` is one on this platform.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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


@pytest.fixture(scope="module")
def lanes_project_builder():
    """The validated lanes-plugin project builder (issue #449's fixture
    shape), shared by the lanes test modules — one implementation, no
    cross-module test imports (the suite has no test package, so a sibling
    module import only resolves under some invocation shapes; xdist proved
    it). Bytes match the fidelity suite's local copy until that module
    consumes this fixture (disclosed in the slice-3 run report)."""
    import hashlib
    import json

    REPO = Path(__file__).resolve().parents[2]
    SRC = REPO / "src"

    def _daq_contracts() -> list[dict[str, Any]]:
        """The corpus-pinned contract rows (from the vendored OTDP 0.2.0
        example descriptor): the invoke-carrying descriptor branch requires a
        contracts block whose digests must match the vendored bytes."""
        document = json.loads(
            (SRC / "benchweave_sdk/standards/otdp/0.2.0/examples/class-daq.json").read_text()
        )
        return document["contracts"]

    def _build(destination: Path, *, preview_css: bytes | None = None) -> Path:
        create_project(destination, "example_plugin")
        create_ui_resources(destination, "example_plugin")
        package = destination / "src" / "example_plugin"

        descriptor = json.loads((package / "descriptor.json").read_text())
        descriptor["capabilities"] = ["identify", "read", "invoke"]
        descriptor["operations"]["invoke"] = {
            "timeout_ms": 30000,
            "side_effect": "none",
            "retry": "never",
            "cancellable": True,
            "completion": "acknowledged",
        }
        descriptor["required_features"] = descriptor.get("required_features", []) + [
            "otdp.profile_actions/0.1.0",
            "otdp.measurement/0.1.0",
            "otdp.logic_analyser/1.0.0",
        ]
        descriptor["channels"] = [
            {
                "id": "logic_a",
                "label": "Logic bank A",
                "role": "digital_input",
                "quantities": ["digital"],
                "parameter_names": [],
            }
        ]
        descriptor["profiles"] = ["otdp.logic_analyser/1.0.0"]
        descriptor["contracts"] = _daq_contracts()
        descriptor["actions"] = {
            "otdp.logic_analyser.fetch/1.0.0": {
                "binding": {"kind": "adapter", "key": "otdp.logic_analyser.fetch/1.0.0"},
                "input_constraints": {},
                "timeout_ms": 30000,
                "side_effect": "none",
                "cancellable": True,
                "retry": "never",
            },
            "otdp.logic_analyser.decode/1.0.0": {
                "binding": {"kind": "adapter", "key": "otdp.logic_analyser.decode/1.0.0"},
                "input_constraints": {},
                "timeout_ms": 30000,
                "side_effect": "none",
                "cancellable": True,
                "retry": "never",
            },
        }
        raw = (json.dumps(descriptor, indent=2) + "\n").encode()
        (package / "descriptor.json").write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()

        catalogue_path = package / "binding-catalogue.json"
        catalogue = json.loads(catalogue_path.read_text())

        def lane_variable(name: str) -> dict[str, Any]:
            return {"id": name, "type": "string", "unit": None, "shape": "vector"}

        catalogue["targets"] = [
            {
                "id": "logic",
                "kind": "dataset",
                "action_id": "otdp.logic_analyser.fetch/1.0.0",
                "profile_ids": ["otdp.logic_analyser/1.0.0"],
                "measurement_schema_id": "urn:otdp:measurement:0.2.0",
                "variables": [
                    {
                        "id": "time",
                        "type": "number",
                        "unit": "s",
                        "shape": "vector",
                        "axis_role": "x",
                    },
                    lane_variable("d0"),
                    lane_variable("d1"),
                    lane_variable("d2"),
                    lane_variable("d3"),
                ],
            },
            {
                "id": "decode-events",
                "kind": "dataset",
                "action_id": "otdp.logic_analyser.decode/1.0.0",
                "profile_ids": ["otdp.logic_analyser/1.0.0"],
                "measurement_schema_id": "urn:otdp:measurement:0.2.0",
                "variables": [
                    {
                        "id": "time",
                        "type": "number",
                        "unit": "s",
                        "shape": "vector",
                        "axis_role": "x",
                    },
                    lane_variable("payload"),
                ],
            },
        ]
        catalogue["descriptor_sha256"] = digest
        catalogue_path.write_bytes((json.dumps(catalogue, indent=2) + "\n").encode())

        manifest_path = package / "ui" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["descriptor_sha256"] = digest
        manifest["bindings"] = [
            {"id": "logic-capture", "kind": "dataset", "target_id": "logic"},
            {"id": "decode-capture", "kind": "dataset", "target_id": "decode-events"},
        ]
        manifest["pages"] = [
            {
                "id": "capture",
                "title": "Capture",
                "kind": "dataset",
                "bindings": ["logic-capture", "decode-capture"],
                "required": True,
                "plots": [
                    {
                        "kind": "digital_lanes",
                        "binding_id": "logic-capture",
                        "x": "time",
                        "y": ["d0", "d1", "d2", "d3"],
                        # F1's shape: a schema-valid lanes visibility hint —
                        # d2 declares ``visible: false`` (the lanes-legal hint
                        # form; colour_role is forbidden for this kind).
                        "channel_hints": [{"variable_id": "d2", "visible": False}],
                        "lane_groups": [
                            {
                                "id": "bus_ab",
                                "label": "Bus AB",
                                "member_ids": ["d0", "d1"],
                                "radix": "hex",
                            },
                            # F2's distinct shape: no label (label falls back
                            # to the group id) and no radix (schema default).
                            {"id": "bus_ef", "member_ids": ["d2", "d3"]},
                        ],
                        "decoder_lanes": [
                            {
                                "id": "uart",
                                "label": "UART",
                                "decoder": "uart8n1",
                                "source_channel_ids": ["d0"],
                                "binding_id": "decode-capture",
                            }
                        ],
                    }
                ],
            }
        ]
        if preview_css is not None:
            (package / "ui" / "preview.css").write_bytes(preview_css)
            manifest["assets"] = [
                {
                    "id": "preview-override",
                    "path": "preview.css",
                    "sha256": hashlib.sha256(preview_css).hexdigest(),
                }
            ]
        manifest_raw = (json.dumps(manifest, indent=2) + "\n").encode()
        manifest_path.write_bytes(manifest_raw)

        envelope_path = package / "presentation.json"
        envelope = json.loads(envelope_path.read_text())
        envelope["descriptor_sha256"] = digest
        envelope["manifest"]["sha256"] = hashlib.sha256(manifest_raw).hexdigest()
        envelope_path.write_text(json.dumps(envelope, indent=2) + "\n")
        return destination

    return _build


@pytest.fixture(scope="module")
def app_client_factory():
    """A host TestClient over any project root (the fidelity suite's
    ``_app_client`` shape, shared): the complete guard policy, the real
    seam build and the generated scenario selection the serve CLI picks."""

    def _build(project: Path, **kwargs: Any) -> TestClient:
        from benchweave_sdk_server.cli import _build_seam

        built_policy = GuardPolicy.complete(
            bound_host=TEST_HOST,
            bound_port=TEST_PORT,
            bearer_token=new_token(),
            csrf_token=new_token(),
        )
        seam, selection = _build_seam(project, **kwargs)
        built_app = build_app(seam, policy=built_policy, scenario=selection)
        return TestClient(built_app, base_url=f"http://{TEST_HOST}:{TEST_PORT}")

    return _build


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
