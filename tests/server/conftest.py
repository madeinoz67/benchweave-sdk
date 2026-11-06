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
def invoke_project_builder():
    """The PR-2 invoke project builder (issue #589 §3): a scaffolded plugin
    whose descriptor pins a SYNTHETIC profile catalog (invented names only)
    beside the vendored measurement schema, and whose adapter (the
    ``scripted_invoke_adapter`` fixture file) answers identify/invoke/reset
    from a module-level SCRIPT the test rewrites per arm (fished from
    ``sys.modules`` immediately after the load — the loader evicts and
    re-imports per project, so the fishing always names the project just
    loaded)."""

    import hashlib
    import json

    REPO = Path(__file__).resolve().parents[2]
    VENDORED = REPO / "src/benchweave_sdk/standards/otdp/0.2.4"
    ADAPTER = (REPO / "tests/server/fixtures/scripted_invoke_adapter.py").read_bytes()

    def _catalog(*, with_measurement_ref: bool = False) -> dict[str, Any]:
        """The synthetic profile catalog: valid against the vendored catalog
        schema, invented action names, one action per gate the arms need.
        The measurement-referencing action is OPT-IN — a catalog that
        references the measurement urn by definition refuses when the
        measurement is not pinned (the gateway's own closed-set rule), so
        the half-pair soft arms must use the ref-free default."""

        def closed(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
            return {"type": "object", "properties": properties,
                    "required": required, "additionalProperties": False}

        actions: dict[str, Any] = {
            "demo.probe/1.0.0": {
                "description": "Open synthetic action: any object in, any object out.",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "side_effect": "state_change",
                "lifecycle": "direct",
            },
            "demo.typed_echo/1.0.0": {
                "description": "Typed synthetic action: closed input and output.",
                "input_schema": closed(
                    {"mode": {"type": "string", "minLength": 1}}, ["mode"]
                ),
                "output_schema": closed({"value": {"type": "number"}}, ["value"]),
                "side_effect": "none",
                "lifecycle": "direct",
            },
        }
        if with_measurement_ref:
            actions["demo.measurement_ref/1.0.0"] = {
                "description": (
                    "Synthetic action whose input references the measurement "
                    "schema by urn (the closed-registry probe arms)."
                ),
                "input_schema": {"$ref": "urn:otdp:measurement:0.2.4"},
                "output_schema": {"type": "object"},
                "side_effect": "none",
                "lifecycle": "direct",
            }
        return {
            "catalog_version": "0.2.4",
            "otdp_version": "0.2.4",
            "profiles": [
                {
                    "id": "example.probe/1.0.0",
                    "title": "Synthetic probe profile",
                    "channel_roles": ["control"],
                    "required_actions": ["demo.probe/1.0.0"],
                    "optional_actions": [],
                }
            ],
            "actions": actions,
        }

    def _pin(package: Path, name: str, payload: bytes) -> dict[str, Any]:
        (package / name).write_bytes(payload)
        return {
            "id": f"urn:example:{name.rsplit('.', 1)[0]}:1",
            "path": name,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def _action(
        key: str,
        *,
        timeout_ms: int = 30000,
        side_effect: str = "none",
        cancellable: bool = True,
        retry: str = "never",
        constraints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "binding": {"kind": "adapter", "key": key},
            "input_constraints": constraints if constraints is not None else {},
            "timeout_ms": timeout_ms,
            "side_effect": side_effect,
            "cancellable": cancellable,
            "retry": retry,
        }

    def _build(
        destination: Path,
        *,
        actions: dict[str, Any] | None = None,
        invoke_policy: dict[str, Any] | None = None,
        declare_invoke: bool = True,
        declare_reset: bool = False,
        pin_catalog: bool = True,
        catalog_with_measurement_ref: bool = False,
        pin_measurement: bool = True,
        extra_pins: list[dict[str, Any]] | None = None,
    ) -> Path:
        """Scaffold, rewire the descriptor for invoke, pin the pair, and
        replace the adapter with the scripted one."""
        create_project(destination, "example_plugin")
        package = destination / "src" / "example_plugin"
        pins: list[dict[str, Any]] = list(extra_pins or [])
        if pin_measurement:
            # The vendored measurement bytes, copied verbatim: the
            # measurement-by-shape arm resolves a real dataset definition.
            # The pin's id names the document's own $id (the detection is
            # by shape; the agreement is hygiene).
            measurement = _pin(
                package,
                "measurement.json",
                (VENDORED / "otdp-measurement.schema.json").read_bytes(),
            )
            measurement["id"] = "urn:otdp:measurement:0.2.4"
            pins.append(measurement)
        if pin_catalog:
            document = _catalog(
                with_measurement_ref=catalog_with_measurement_ref
            )
            payload = (json.dumps(document, indent=2) + "\n").encode()
            pins.append(_pin(package, "profile-catalog.json", payload))
        descriptor = json.loads((package / "descriptor.json").read_text())
        # The descriptor schema's bi-conditionals govern: every capability
        # names its operation policy and only a declared capability may
        # carry one (the starter declares identify+read; the scripted
        # adapter serves neither read nor write, so the read policy goes).
        descriptor["capabilities"] = ["identify"]
        descriptor["operations"].pop("read", None)
        if declare_invoke:
            # allOf[29]: an invoke capability REQUIRES channels, profiles,
            # contracts, actions, the invoke policy and the two feature rows.
            descriptor["capabilities"].append("invoke")
            descriptor["operations"]["invoke"] = invoke_policy or {
                "timeout_ms": 30000,
                "side_effect": "none",
                "retry": "never",
                "cancellable": True,
                "completion": "acknowledged",
            }
            descriptor["required_features"] = sorted(
                set(descriptor.get("required_features", []))
                | {"otdp.profile_actions/0.1.0", "otdp.measurement/0.1.0"}
            )
            descriptor["profiles"] = ["example.probe/1.0.0"]
            descriptor["channels"] = [{
                "id": "control",
                "label": "Control channel",
                "role": "configuration",
                "quantities": ["digital"],
                "parameter_names": [],
            }]
        if declare_reset:
            descriptor["capabilities"].append("reset")
            descriptor["operations"]["reset"] = {
                "timeout_ms": 5000,
                "side_effect": "state_change",
                "retry": "never",
                "cancellable": False,
                "completion": "acknowledged",
            }
        descriptor["actions"] = actions or {
            "demo.probe/1.0.0": _action(
                "demo.probe/1.0.0", side_effect="state_change"
            ),
            "demo.typed_echo/1.0.0": _action(
                "demo.typed_echo/1.0.0", side_effect="none", cancellable=False
            ),
        }
        if pins:
            descriptor["contracts"] = pins
        raw = (json.dumps(descriptor, indent=2) + "\n").encode()
        (package / "descriptor.json").write_bytes(raw)
        (package / "adapter.py").write_bytes(ADAPTER)
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
