"""The preview-ui shim (PRD 12 R-9): a mirror-subset alias over serve.

``preview-ui`` is not a second implementation. It is one in-process
delegation to ``benchweave_sdk_server.cli.serve`` with the transport pinned
to the scripted mock, so this module pins the properties that delegation
must keep: the DECLARED surface mirrors serve's options exactly (the parity
pin), the invocation always carries ``transport="mock"`` (a pin the parity
test cannot express — click merges a command's parameter defaults into the
callback's kwargs, so an explicit value and a default-filled one are
indistinguishable past the call), and the default install's refusal is
serve's own (prefix, install command, exit 2 — never a traceback).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from benchweave_sdk import cli as sdk_cli


@pytest.fixture(scope="module")
def starter(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A ``--with-ui`` scaffolded project, once per module (the shim's
    PROJECT argument exists-checks its path before anything else runs)."""
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    project = tmp_path_factory.mktemp("shim") / "starter"
    create_project(project, "example_plugin")
    create_ui_resources(project, "example_plugin")
    return project


def _simulate_default_install(monkeypatch: pytest.MonkeyPatch, *blocked: str) -> None:
    """The ``tests/server/test_cli.py`` helper's shape: extra-owned modules
    are made absent the way an uninstall is absent, and every cached server
    submodule is dropped so its module-level imports re-execute against the
    blocked set."""
    for name in blocked:
        monkeypatch.setitem(sys.modules, name, None)
        for existing in list(sys.modules):
            if existing.startswith(name + "."):
                monkeypatch.delitem(sys.modules, existing, raising=False)
    for module in list(sys.modules):
        if module == "benchweave_sdk_server" or module.startswith("benchweave_sdk_server."):
            monkeypatch.delitem(sys.modules, module, raising=False)


# --- the parity pin (risk R2) -------------------------------------------------


def test_preview_ui_mirrors_exactly_the_serve_option_subset() -> None:
    """The shim declares exactly {project, host, port, allow-network,
    no-open, scenario} — never transport/device/authoring/unattended (R-9:
    mock is pinned; real hardware is ``benchweave-sdk-server serve``
    directly — D-1/D-6) — and every declared name matches serve's own
    declaration on kind, default and requiredness. serve GROWING a flag
    does not redden this pin; serve CHANGING one of the six does."""
    from benchweave_sdk_server.cli import serve

    shim = {param.name: param for param in sdk_cli.preview_ui_command.params}
    served = {param.name: param for param in serve.params}
    assert set(shim) == {
        "project",
        "host",
        "port",
        "allow_network",
        "no_open",
        "scenario",
    }
    for name, param in shim.items():
        assert name in served, f"serve no longer declares {name}"
        twin = served[name]
        assert type(param) is type(twin), name  # Argument/Option kind
        assert param.default == twin.default, name
        assert param.required == twin.required, name
    # What the pin deliberately does NOT compare: --scenario's type. serve
    # declares a click.Choice (resolved at ITS decoration time); the shim
    # declares a plain string because its decoration must not import the
    # server package at benchweave_sdk.cli import time, and enforces the
    # same membership in its command body
    # (test_preview_ui_refuses_scenario_ids_serve_does_not_offer).


# --- the delegation (A3, in-process arm) --------------------------------------


def test_preview_ui_delegates_to_serve_with_mock_pinned(
    starter: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interception replaces the module's ``serve`` with a plain function,
    so click's ``Context.invoke`` forwards the shim's kwargs VERBATIM (a
    Command object would merge its parameter defaults in first, hiding
    whether ``transport`` was passed explicitly): the recorded dict is the
    exact delegation, and ``transport == "mock"`` must be IN it."""
    import benchweave_sdk_server.cli as server_cli

    recorded: dict[str, object] = {}

    def spy(**kwargs: object) -> None:
        recorded.update(kwargs)

    monkeypatch.setattr(server_cli, "serve", spy)
    result = CliRunner().invoke(
        sdk_cli.cli,
        ["preview-ui", str(starter), "--no-open", "--scenario", "normal"],
    )
    assert result.exit_code == 0, result.output
    assert recorded == {
        "project": starter,
        "host": "127.0.0.1",
        "port": 8477,
        "allow_network": False,
        "no_open": True,
        "scenario": "normal",
        "transport": "mock",
    }


# --- refusals -------------------------------------------------------------------


def test_preview_ui_refuses_scenario_ids_serve_does_not_offer(starter: Path) -> None:
    """serve parses ``--scenario`` as a Choice; ``ctx.invoke`` skips option
    processing, so the shim enforces membership itself — the same exit-2
    usage-error family, naming the offered ids."""
    result = CliRunner().invoke(
        sdk_cli.cli,
        ["preview-ui", str(starter), "--scenario", "not-a-state", "--no-open"],
    )
    assert result.exit_code == 2
    assert "--scenario" in result.output
    assert "not-a-state" in result.output
    for offered in ("normal", "trip", "request-rejected"):
        assert offered in result.output


def test_preview_ui_refuses_without_the_server_extra(
    starter: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A2's in-suite companion: on a default install the body-import
    succeeds (the server CLI module is extra-free at module level) and
    serve's own guard refuses — prefix, install command, exit 2, never a
    traceback."""
    _simulate_default_install(monkeypatch, "fastapi", "uvicorn")
    result = CliRunner().invoke(sdk_cli.cli, ["preview-ui", str(starter), "--no-open"])
    assert result.exit_code == 2
    assert "benchweave_sdk_server_extras_missing:" in result.output
    assert "benchweave-sdk[server]" in result.output
    assert "Traceback" not in result.output


def test_preview_ui_refuses_when_the_server_package_bytes_are_absent(
    starter: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shim's own ImportError guard: the body-import itself failing
    (the package's bytes absent — the wheel always ships them, so this is
    the broken-install case) answers with the same prefix and exit 2."""
    monkeypatch.setitem(sys.modules, "benchweave_sdk_server", None)
    monkeypatch.setitem(sys.modules, "benchweave_sdk_server.cli", None)
    result = CliRunner().invoke(sdk_cli.cli, ["preview-ui", str(starter), "--no-open"])
    assert result.exit_code == 2
    assert "benchweave_sdk_server_extras_missing:" in result.output
    assert "benchweave-sdk[server]" in result.output
    assert "Traceback" not in result.output


def test_listener_rules_flow_through_the_shim(starter: Path) -> None:
    """serve's listener rules (owned by the guard module since #308) are
    inherited, not reimplemented: a non-loopback bind without
    acknowledgement refuses before anything serves."""
    result = CliRunner().invoke(
        sdk_cli.cli, ["preview-ui", str(starter), "--host", "192.168.1.5", "--no-open"]
    )
    assert result.exit_code == 2
    assert "preview_network_acknowledgement_required" in result.output


def test_the_old_per_document_surface_dies_loudly(starter: Path) -> None:
    """No silent repurposing: the envelope-era flags are unknown options and
    click says so with its own usage error (the BREAKING migration surface)."""
    result = CliRunner().invoke(
        sdk_cli.cli, ["preview-ui", str(starter), "--renderer-url", "http://127.0.0.1:5173"]
    )
    assert result.exit_code == 2
    assert "No such option" in result.output


# --- the shared refusal text and the import order (risk R1) --------------------


def test_the_extras_refusal_names_all_three_callers() -> None:
    """The refusal names serve, mcp and preview-ui, and the two carried
    copies of the text (one per module — the server module cannot be
    imported to reuse the constant in exactly the mangled-install case)
    never drift apart."""
    from benchweave_sdk_server.cli import _EXTRAS_MESSAGE

    assert sdk_cli._PREVIEW_EXTRAS_MESSAGE == _EXTRAS_MESSAGE
    for token in (
        "benchweave_sdk_server_extras_missing:",
        "benchweave-sdk[server]",
        "preview-ui",
    ):
        assert token in _EXTRAS_MESSAGE


def test_importing_the_sdk_cli_never_imports_the_server_package() -> None:
    """R1's falsifier, in a fresh interpreter: ``benchweave_sdk.cli``'s
    module level stays free of the server package (the command-body import
    is the only bridge), so the core→server layering cannot become an
    import cycle and a mangled server install cannot kill every command."""
    probe = (
        "import sys, benchweave_sdk.cli; "
        "leaked = [m for m in sys.modules if m.startswith('benchweave_sdk_server')]; "
        "assert not leaked, leaked"
    )
    proc = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
