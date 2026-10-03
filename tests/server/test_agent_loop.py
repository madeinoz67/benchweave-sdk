"""The agent loop and plugin_test (I2c §4.2, SW-39; gate I2-L — the PRD §9
exit gate's own clause: an agent completes patch, reload and test on the
mock-transport starter).

The loop is the real thing, not a sketch: an in-process MCP client drives
an authoring host (``--authoring --unattended``, the PRD's benches-with-
no-energy-sourcing case) through scaffold → check → check → patch →
reload → re-render → refused-invalid-patch-writes-nothing → per-test
results → reads-still-serve → advisory-visible.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient
from fastmcp import Client

from benchweave_sdk_server import authoring
from benchweave_sdk_server.mcp import build_mcp
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.session import load_plugin_project, mock_plugin_session
from benchweave_sdk_server.web import build_app

DEV = {"device_id": "example_device"}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seam(project: Path) -> StandaloneSeam:
    plugin = load_plugin_project(project)
    return StandaloneSeam(
        mock_plugin_session(plugin), transport_kind="mock", unattended=True
    )


def _call(mcp, name: str, arguments: dict) -> dict:
    async def run() -> dict:
        async with Client(mcp) as client:
            result = await client.call_tool(name, arguments, raise_on_error=False)
            if result.structured_content and "error" in result.structured_content:
                raise AssertionError(f"{name} refused: {result.structured_content}")
            return result.structured_content or {}

    return asyncio.run(run())


# --- plugin_test in isolation ----------------------------------------------------


def test_plugin_test_runs_the_starter_suite_per_test(tmp_path) -> None:
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "starter"
    create_project(project, "example_plugin")
    create_ui_resources(project, "example_plugin")
    result = authoring._plugin_test(_seam(project))
    assert result["status"] == "done"
    assert result["exit_code"] == 0, result["output"]
    names = {row["test"] for row in result["tests"]}
    assert any("test_identify_and_read" in name for name in names)
    assert all(row["outcome"] == "PASSED" for row in result["tests"])
    # The scaffolded suite carries the SDK conformance arms (check_lifecycle,
    # validate_result) — the tool's run covers them by running the suite.
    assert any("test_quiet_lifecycle" in name for name in names)


def test_plugin_test_reports_failing_tests_honestly(tmp_path) -> None:
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "starter"
    create_project(project, "example_plugin")
    create_ui_resources(project, "example_plugin")
    (project / "tests" / "test_plugin.py").write_text(
        "def test_alright():\n    assert True\n\n\n"
        "def test_broken():\n    assert False, 'deliberate'\n",
        encoding="utf-8",
    )
    result = authoring._plugin_test(_seam(project))
    assert result["status"] == "done"
    assert result["exit_code"] == 1, "pytest's own failure code must survive the wire"
    outcomes = {row["test"]: row["outcome"] for row in result["tests"]}
    assert outcomes["tests/test_plugin.py::test_alright"] == "PASSED"
    assert outcomes["tests/test_plugin.py::test_broken"] == "FAILED"
    assert "deliberate" in result["output"] or result["tests"]


def test_plugin_test_timeout_is_honest(tmp_path) -> None:
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "starter"
    create_project(project, "example_plugin")
    create_ui_resources(project, "example_plugin")
    (project / "tests" / "test_plugin.py").write_text(
        "import time\n\n\ndef test_hangs():\n    time.sleep(30)\n",
        encoding="utf-8",
    )
    result = authoring._plugin_test(_seam(project), timeout_s=2)
    assert result["status"] == "timeout"
    assert result["exit_code"] is None
    assert "timed out" in result["message"]


# --- the exit-gate loop (I2-L) -----------------------------------------------------


def test_the_agent_completes_patch_reload_and_test(tmp_path) -> None:
    """The PRD §9 exit gate's verbatim clause, driven end to end over MCP
    by an in-process agent loop."""
    project = tmp_path / "agent-made"
    # The scaffolding tool runs on a bootstrap host over the same starter
    # shape the conftest builds; the LOOP's host is this project's own.
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    create_project(project, "example_plugin")
    create_ui_resources(project, "example_plugin")
    seam = _seam(project)
    mcp = build_mcp(seam, authoring=True)

    # plugin_check clean, ui_check clean.
    descriptor_path = str(project / "src" / "example_plugin" / "descriptor.json")
    check = _call(mcp, "plugin_check", {"descriptor_path": descriptor_path})
    assert check["valid"] is True, check
    ui = _call(mcp, "ui_check", {"project_root": str(project)})
    assert ui["valid"] is True, ui

    # contract_patch: descriptor title + a manifest page title.
    package = project / "src" / "example_plugin"
    descriptor_before = _digest(package / "descriptor.json")
    _call(
        mcp,
        "contract_patch",
        {
            "document": "descriptor",
            "patch": [
                {"op": "replace", "path": "/display_name", "value": "Agent-renamed demo"}
            ],
        },
    )
    _call(
        mcp,
        "contract_patch",
        {
            "document": "manifest",
            "patch": [
                {"op": "replace", "path": "/pages/0/title", "value": "Agent readings"}
            ],
        },
    )

    # A schema-invalid patch is refused and writes NOTHING (digest-compared).
    fingerprint = {
        str(path.relative_to(project)): _digest(path)
        for path in sorted(package.rglob("*.json"))
    }
    refused = _call_refused(
        mcp,
        "contract_patch",
        {
            "document": "descriptor",
            "patch": [{"op": "remove", "path": "/identity"}],
        },
    )
    assert refused["code"] == "invalid_request"
    assert refused["details"]["findings"]
    after_refusal = {
        str(path.relative_to(project)): _digest(path)
        for path in sorted(package.rglob("*.json"))
    }
    assert after_refusal == fingerprint

    # plugin_reload over MCP (unattended host: no confirmation gate).
    reloaded = _call(mcp, "plugin_reload", {"source": "mcp"})
    assert reloaded["status"] == "reloaded"
    assert reloaded["descriptor_sha256"] != descriptor_before

    # Pages re-render the patch after the reload; the advisory is wired.
    policy = GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )
    app = build_app(seam, policy=policy, authoring=True)
    with TestClient(app, base_url="http://127.0.0.1:8477") as client:
        page = client.get("/pages/readings").text
        assert "Agent readings" in page
        assert "authoring-panel" in page
        # parameter_read still serves after the reload (over REST).
        reading = client.post(
            "/v1/device_connect",
            headers={"authorization": f"Bearer {policy.bearer_token}"},
            json=DEV,
        ).json()
        assert reading["data"]["connected"] is True
        value = client.post(
            "/v1/parameter_read",
            headers={"authorization": f"Bearer {policy.bearer_token}"},
            json={**DEV, "parameter": "voltage"},
        ).json()
        assert value["data"]["value"] == 3.3
        # The reload advisory is visible through the event stream's own
        # surfaces: the bus carries plugin_reloaded and the page declares
        # the hydrator + regions that render it (the browser lane's arm
        # pins the rendered TEXT end to end).
        assert 'src="/assets/bw-events.js"' in page
        assert 'id="reload-advisory"' in page
    events = asyncio.run(
        seam.call("events_get", {"after_id": 0})
    )["events"]
    assert any(row["kind"] == "plugin_reloaded" for row in events)

    # plugin_test: per-test pass/fail over MCP on the reloaded project.
    tested = _call(mcp, "plugin_test", {})
    assert tested["status"] == "done"
    assert tested["exit_code"] == 0, tested["output"]
    assert tested["tests"]
    assert all(row["outcome"] == "PASSED" for row in tested["tests"])


def _call_refused(mcp, name: str, arguments: dict) -> dict:
    async def run() -> dict:
        async with Client(mcp) as client:
            result = await client.call_tool(name, arguments, raise_on_error=False)
            content = result.structured_content or {}
            if "error" not in content:
                raise AssertionError(f"{name} was expected to refuse")
            return content["error"]

    return asyncio.run(run())

