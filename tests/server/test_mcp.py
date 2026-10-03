"""The MCP surface: tool-set pin, operations over an in-process client,
authoring-tool presence and absence (gates B, C, F)."""

from __future__ import annotations

import asyncio
import json
import os

from fastmcp import Client

from benchweave_sdk_server import catalogue
from benchweave_sdk_server.mcp import (
    build_mcp,
    operation_tool_schema,
    registered_tool_names,
    tool_name,
)

DEV = {"device_id": "example_device"}
AUTHORING_TOOLS = {"plugin_new", "plugin_check", "ui_check"}


def test_served_tool_names_are_the_catalogue_prefix_set(seam) -> None:
    mcp = build_mcp(seam)
    assert registered_tool_names(mcp) == sorted(
        tool_name(name) for name in catalogue.served_operations()
    )


def test_the_built_server_names_the_ruling_not_the_dead_distribution(seam) -> None:
    """Issue #309 slice A, fold F1: serverInfo.name is wire-visible — the
    dead distribution's name is gone from the tool surface, replaced by
    the distribution the host rides (gate A-R's dash-token grep pins the
    tree; this pins the built object)."""
    mcp = build_mcp(seam)
    assert mcp.name == "benchweave-sdk-server"


def test_pinned_schemas_equal_the_catalogue_verbatim(seam) -> None:
    """Gate F: parameters and output_schema are the catalogue's, exactly."""
    mcp = build_mcp(seam)
    for row in catalogue.CATALOGUE:
        if not row.implemented:
            continue
        readback = operation_tool_schema(mcp, tool_name(row.name))
        assert readback is not None, row.name
        assert readback.input_schema == row.input_schema, row.name
        assert readback.result_schema == {**row.result_schema, "type": "object"}, row.name


def test_inference_is_not_the_wire_authority(seam) -> None:
    """The pin, not the signature: a schema detail inference cannot emit
    (``additionalProperties: false`` with an empty required list on
    no-argument operations) survives on the wire."""
    mcp = build_mcp(seam)
    readback = operation_tool_schema(mcp, tool_name("host_info"))
    assert readback is not None
    assert readback.input_schema["additionalProperties"] is False
    assert readback.input_schema["required"] == []


def _call(mcp, name: str, arguments: dict) -> object:
    async def run() -> object:
        async with Client(mcp) as client:
            return await client.call_tool(name, arguments, raise_on_error=False)

    return asyncio.run(run())


def _structured(result: object) -> dict:
    return result.structured_content or {}


def test_host_info_over_mcp(seam) -> None:
    mcp = build_mcp(seam)
    data = _structured(_call(mcp, "bws_v1_host_info", {}))
    assert data["mode"] == "standalone"
    assert data["absent_guarantees"] == [
        "leases", "policy", "approvals", "procedures", "runs",
    ]
    assert set(data["served_operations"]) == set(catalogue.served_operations())
    assert "capture_start" in data["deferred_operations"]


def test_device_flow_over_mcp(seam) -> None:
    mcp = build_mcp(seam)
    devices = _structured(_call(mcp, "bws_v1_device_discover", {}))["devices"]
    assert len(devices) == 1
    connected = _structured(_call(mcp, "bws_v1_device_connect", DEV))
    assert connected["connected"] is True
    identity = _structured(_call(mcp, "bws_v1_device_get", DEV))
    assert identity["manufacturer"] == "SDK Example"
    assert identity["model"] == "demo"


def test_parameter_read_over_mcp(seam) -> None:
    mcp = build_mcp(seam)
    _call(mcp, "bws_v1_device_connect", DEV)
    _call(mcp, "bws_v1_device_get", DEV)
    data = _structured(
        _call(mcp, "bws_v1_parameter_read", {**DEV, "parameter": "voltage"})
    )
    assert data["value"] == 3.3
    assert data["unit"] == "V"


def test_twenty_sequential_reads_over_mcp(seam) -> None:
    mcp = build_mcp(seam)
    _call(mcp, "bws_v1_device_connect", DEV)
    _call(mcp, "bws_v1_device_get", DEV)
    for _ in range(20):
        data = _structured(
            _call(mcp, "bws_v1_parameter_read", {**DEV, "parameter": "voltage"})
        )
        assert data["value"] == 3.3


def test_deferred_operations_are_absent_from_the_tool_set(seam) -> None:
    """One tool per IMPLEMENTED operation (SW-30): deferred operations are
    absent, not stubbed — the deferral refusal lives in the seam and REST,
    and host_info discloses the deferred set."""
    names = set(registered_tool_names(build_mcp(seam)))
    for name in catalogue.deferred_operations():
        assert tool_name(name) not in names


def test_lease_tools_are_absent_not_stubbed(seam) -> None:
    """SW-32: no lease/run/bench tools exist on the standalone server."""
    names = registered_tool_names(build_mcp(seam))
    for absent in (
        "bws_v1_lease_create", "bws_v1_run_start", "bws_v1_bench_list",
        "stg_v1_lease_create",
    ):
        assert absent not in names


# --- authoring (SW-35 / NFR-S8) ----------------------------------------------


def test_authoring_tools_absent_without_the_flag(seam) -> None:
    names = set(registered_tool_names(build_mcp(seam, authoring=False)))
    assert not (names & AUTHORING_TOOLS)


def test_authoring_tools_present_with_the_flag(seam) -> None:
    names = set(registered_tool_names(build_mcp(seam, authoring=True)))
    assert names & AUTHORING_TOOLS == AUTHORING_TOOLS


def test_plugin_new_scaffolds_and_reports_the_inventory(seam, tmp_path) -> None:
    mcp = build_mcp(seam, authoring=True)
    destination = tmp_path / "second" / "probe"
    result = _structured(
        _call(mcp, "plugin_new", {"destination": str(destination),
                                  "package": "second_probe", "with_ui": True})
    )
    files = result["files"]
    # Normalize the comparison, not the data: the tool reports
    # platform-native separators (authoring.py builds the inventory with
    # str(relative_to), so Windows answers src\second_probe\...). The
    # assertion's intent is that the scaffold carries these relative
    # paths — asserted in posix form on every OS (CI-carried RED: PR #90's
    # windows-latest run, this suite's first Windows exposure).
    posix_files = {str(entry).replace(os.sep, "/") for entry in files}
    assert "src/second_probe/descriptor.json" in posix_files
    assert "src/second_probe/presentation.json" in posix_files
    assert "src/second_probe/ui/manifest.json" in posix_files
    assert (destination / "src" / "second_probe" / "adapter.py").is_file()


def test_plugin_new_inventory_is_posix_under_a_windows_flavour(monkeypatch) -> None:
    """The cross-host-meaning rule on the wire: plugin_new's files list is
    posix-form on EVERY host. The Windows flavour is simulated with a
    PureWindowsPath-driven double — real relative_to/str/as_posix (the
    platform behaviour PR #90's windows-latest leg proved), with discovery
    and the scaffold calls stubbed — so this arm has local teeth: pre-fix
    it fails on macOS exactly as CI failed on Windows, instead of waiting
    for the Windows leg to catch a regression.
    """
    from pathlib import PureWindowsPath

    from benchweave_sdk_server import authoring

    class _WindowsFlavourDouble(PureWindowsPath):
        # Discovery double: no filesystem exists under a Windows path on
        # this host, so rglob serves the listing and expanduser/resolve
        # stand still. str/relative_to/as_posix are the REAL Windows
        # flavour — the part under test is untouched.
        def expanduser(self):
            return self

        def resolve(self):
            return self

        def rglob(self, pattern):
            return (
                self / "src" / "second_probe" / "descriptor.json",
                self / "src" / "second_probe" / "adapter.py",
            )

        def is_file(self):
            return True

    monkeypatch.setattr(authoring, "Path", _WindowsFlavourDouble)
    monkeypatch.setattr(authoring, "create_project", lambda target, package: None)
    monkeypatch.setattr(
        "benchweave_sdk.presentation.create_ui_resources",
        lambda target, package: None,
    )
    result = authoring._plugin_new("C:\\probe", "second_probe", True)
    assert result["files"] == [
        "src/second_probe/adapter.py",
        "src/second_probe/descriptor.json",
    ]


def test_plugin_check_and_ui_check_return_clean(seam, starter_project) -> None:
    mcp = build_mcp(seam, authoring=True)
    descriptor = starter_project / "src" / "example_plugin" / "descriptor.json"
    check = _structured(_call(mcp, "plugin_check", {"descriptor_path": str(descriptor)}))
    assert check["valid"] is True
    ui = _structured(_call(mcp, "ui_check", {"project_root": str(starter_project)}))
    assert ui["valid"] is True, ui
    assert ui["findings"] == []


def test_plugin_check_reports_an_invalid_descriptor(seam, tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"id": "not-a-descriptor"}))
    mcp = build_mcp(seam, authoring=True)
    result = _structured(_call(mcp, "plugin_check", {"descriptor_path": str(bad)}))
    assert result["valid"] is False
    assert result["error"]
