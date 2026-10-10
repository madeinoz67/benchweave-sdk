"""The CLI: listener rules (verbatim SDK reuse), startup validation order,
and the stdio entry's guard exemption posture."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner

from benchweave_sdk_server.cli import cli, main


def test_wildcard_listener_is_refused(starter_project: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["serve", str(starter_project), "--host", "0.0.0.0", "--no-open"]
    )
    assert result.exit_code == 2
    assert "preview_unsafe_listener" in result.output


def test_non_loopback_requires_allow_network(starter_project: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["serve", str(starter_project), "--host", "192.168.1.5", "--no-open"]
    )
    assert result.exit_code == 2
    assert "preview_network_acknowledgement_required" in result.output


def test_invalid_listener_name_is_refused(starter_project: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["serve", str(starter_project), "--host", "not-an-address", "--no-open"]
    )
    assert result.exit_code == 2
    assert "preview_invalid_listener" in result.output


def test_invalid_plugin_refuses_before_any_bind(tmp_path: Path) -> None:
    """SW-05: descriptor validation happens before the port binds — the
    refusal names the plugin, not the listener."""
    runner = CliRunner()
    result = runner.invoke(cli, ["serve", str(tmp_path), "--no-open"])
    assert result.exit_code == 2
    assert "standalone_plugin_project" in result.output


def test_corrupt_descriptor_refuses_with_the_sdk_diagnostics(
    starter_project: Path, tmp_path: Path,
) -> None:
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "corrupt"
    create_project(project, "example_plugin")
    create_ui_resources(project, "example_plugin")
    descriptor = project / "src" / "example_plugin" / "descriptor.json"
    document = json.loads(descriptor.read_text())
    document["parameters"] = "not-a-list"
    descriptor.write_text(json.dumps(document))
    runner = CliRunner()
    result = runner.invoke(cli, ["serve", str(project), "--no-open"])
    assert result.exit_code == 2
    assert "standalone_plugin_invalid" in result.output


def test_mcp_command_builds_without_an_http_listener(starter_project: Path) -> None:
    """The stdio entry's FALLBACK construction (issue #440: the reshaped
    command's no-host path) yields the full tool set; it never binds a
    port (NFR-S4 posture — asserted by building everything short of
    run()). The fallback marker rides the instructions (the disclosed
    no-browser session)."""
    from benchweave_sdk_server.cli import _build_seam
    from benchweave_sdk_server.mcp import registered_tool_names
    from benchweave_sdk_server.shim import FALLBACK_MARKER, build_fallback_server

    seam, _ = _build_seam(starter_project)
    server = build_fallback_server(seam, authoring=True)
    try:
        names = set(registered_tool_names(server))
        assert "bws_v1_host_info" in names
        assert "plugin_new" in names
        assert FALLBACK_MARKER in server.instructions
    finally:
        import asyncio

        asyncio.run(seam.settle_capture_for_shutdown())
        seam.close()


# --- slice A: the console entry degrades gracefully without the extra ------

#: The top-level modules only `benchweave-sdk[server]` installs, including
#: the transitive names the host's import closure can reach: starlette
#: rides fastapi and pydantic rides fastapi/fastmcp (the A-E venv run
#: caught starlette through security.py when the name list had only the
#: four direct dependencies -- a simulation weaker than reality is a
#: false pass, so the set names the closure, not the extras table).
#: benchweave_ui_html joined the closure with the I2a presentation
#: render (PR #97's Windows red: the sim's miss — the plot wrapper put it
#: in the CLI module chain through seam.py; the set names the closure, not
#: the extras table).
_SERVER_EXTRA_MODULES = (
    "fastapi",
    "fastmcp",
    "uvicorn",
    "jinja2",
    "starlette",
    "pydantic",
    "benchweave_ui_html",
)


def _simulate_default_install(monkeypatch: pytest.MonkeyPatch, *blocked: str) -> None:
    """Make the extra's modules absent the way an uninstall is absent: a
    None sys.modules entry makes a top-level ``import <name>`` raise
    ImportError, and every cached submodule under it is dropped so
    ``from <name>.sub import X`` re-resolves through the blocked parent
    instead of a leftover cached module (that bypass is real: the A-E
    venv run caught starlette through security.py while the in-suite
    simulation passed vacuously on the cached starlette.middleware.base).
    Every host submodule is dropped too, so their module-level imports
    re-execute against the blocked set.
    """
    for name in blocked:
        monkeypatch.setitem(sys.modules, name, None)
        for existing in list(sys.modules):
            if existing.startswith(name + "."):
                monkeypatch.delitem(sys.modules, existing, raising=False)
    for module in list(sys.modules):
        if module == "benchweave_sdk_server" or module.startswith("benchweave_sdk_server."):
            monkeypatch.delitem(sys.modules, module, raising=False)


def test_serve_without_the_server_extra_refuses_gracefully(
    starter_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A default install gets the console script but not the stack: serve
    refuses with the prefixed message naming the install command, exit 2 —
    never an ImportError traceback (the R-9 shim pattern, slice A)."""
    _simulate_default_install(monkeypatch, "fastapi", "uvicorn")
    result = CliRunner().invoke(cli, ["serve", str(starter_project), "--no-open"])
    assert result.exit_code == 2
    assert "benchweave_sdk_server_extras_missing:" in result.output
    assert "benchweave-sdk[server]" in result.output


def test_mcp_without_the_server_extra_refuses_gracefully(
    starter_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AM2 (issue #440): the no-extra refusal covers the discovery
    import path too — the reshaped command imports the discovery
    machinery (shim.py stays extra-free) and the extra's own machinery
    inside ONE guard: blocking fastmcp refuses TYPED before any
    discovery work runs, exit 2, never a traceback out of discovery."""
    _simulate_default_install(monkeypatch, "fastmcp")
    result = CliRunner().invoke(cli, ["mcp", str(starter_project)])
    assert result.exit_code == 2
    assert "benchweave_sdk_server_extras_missing:" in result.output


def test_help_works_without_the_server_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI module itself imports nothing from the extra set: --help
    answers on a default install (the cli module is re-imported with the
    whole extra set blocked)."""
    _simulate_default_install(monkeypatch, *_SERVER_EXTRA_MODULES)
    monkeypatch.delitem(sys.modules, "benchweave_sdk_server.cli", raising=False)
    import benchweave_sdk_server.cli as cli_module

    result = CliRunner().invoke(cli_module.cli, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.output


def test_serve_survives_a_browserless_host(
    starter_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The browserless-survival pin, restored SDK-side (review fold F1 on
    gateway PR #400): a host with no registered browser is headless Linux's
    ordinary state — webbrowser.open raises webbrowser.Error — and serve
    must still reach uvicorn and exit cleanly, printing the notice that
    names the URL. The old gateway arm pinned exactly this for the deleted
    preview; the standalone host inherited the crash-before-bind when the
    shim train landed."""
    import webbrowser

    import uvicorn

    reached: dict[str, bool] = {}

    def refusing(url: str) -> bool:
        raise webbrowser.Error("no browser registered")

    monkeypatch.setattr(webbrowser, "open", refusing)
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: reached.update(run=True))
    result = CliRunner().invoke(cli, ["serve", str(starter_project)])
    assert result.exit_code == 0, (result.exit_code, result.output)
    assert reached.get("run") is True, "serve never reached uvicorn.run"
    assert "Browser did not open" in result.output
    assert "http://127.0.0.1:8477" in result.output


# --- trust-1: the operator action token's mint and delivery -------------------


def _serve_output(
    starter_project: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *args: str
) -> str:
    """One serve invocation's stdout, with uvicorn parked and the CWD under
    a scratch root (the capture-root family resolves against it)."""
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    monkeypatch.chdir(tmp_path)
    return CliRunner().invoke(
        cli, ["serve", str(starter_project), "--no-open", *args]
    ).output


def test_serial_serve_mints_and_delivers_the_operator_action_token(
    starter_project: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """trust-1's delivery: a serial serve mints the per-launch operator
    action token and hands it over OUT-OF-BAND — the banner line and a file
    under the capture-root family whose ``url`` field is the armed launch
    URL (the query carries the token, so the page it opens renders the
    forms' headers while a plain GET never yields the credential)."""
    import json
    import os

    output = _serve_output(
        starter_project, monkeypatch, tmp_path, "--transport", "serial"
    )
    banner = next(
        (
            line
            for line in output.splitlines()
            if "Operator action token" in line and "file" not in line.lower()
        ),
        None,
    )
    assert banner is not None, output
    token = banner.rsplit(" ", 1)[1]
    payload = json.loads(
        (tmp_path / "captures" / "operator-action-token.json").read_text()
    )
    assert payload["operator_action_token"] == token
    assert payload["pid"] == os.getpid()
    assert payload["url"] == f"http://127.0.0.1:8477/?operator_action={token}"


def test_the_operator_action_token_is_per_launch(
    starter_project: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two serves mint two DIFFERENT tokens — the credential names this
    launch, so a token from a dead serve must stop working against the
    next one."""
    tokens = []
    for _ in range(2):
        output = _serve_output(
            starter_project, monkeypatch, tmp_path, "--transport", "serial"
        )
        banner = next(
            line
            for line in output.splitlines()
            if "Operator action token" in line and "file" not in line.lower()
        )
        tokens.append(banner.rsplit(" ", 1)[1])
    assert tokens[0] != tokens[1]


def test_a_mock_serve_prints_no_operator_action_token(
    starter_project: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The mock transport has no bind surface: the token is minted (the
    uniform fail-closed shape) but never DELIVERED — no banner line, no
    file. The banner stays honest about what the surface consumes."""
    output = _serve_output(starter_project, monkeypatch, tmp_path)
    assert "Operator action token" not in output
    assert not (tmp_path / "captures" / "operator-action-token.json").exists()


# --- fold F2: main() returns click's exit codes, never a traceback --------


def test_main_returns_the_usage_error_exit_code() -> None:
    """`benchweave-sdk-server serve` (PROJECT missing) answers click's
    usage error with exit 2 through main() — pre-fix this raised
    UsageError out of the entry point (console script: traceback, exit 1).
    Direct main() calls, not CliRunner: the runner swallows exceptions,
    which is exactly how the defect hid from the CliRunner arms."""
    assert main(["serve"]) == 2


def test_main_returns_the_bad_path_exit_code() -> None:
    """`serve /nonexistent` (BadParameter) — the refute lane's second
    repro, same refusal shape."""
    assert main(["serve", "/definitely/not/a/plugin"]) == 2


def test_main_returns_zero_on_the_help_exit() -> None:
    """--help raises click's Exit(0) under standalone_mode=False; main()
    converts it to 0, the SDK CLI's shape."""
    assert main(["--help"]) == 0


# --- PR #90 carry-forward row R4 (prepared, uncommitted) ----------------------


def test_version_answers_without_a_runtime_error() -> None:
    """R4: bare ``@click.version_option()`` infers the distribution name
    from the module — ``benchweave_sdk_server`` is never a distribution
    (the host rides benchweave-sdk), so ``--version`` crashed with
    ``RuntimeError: 'benchweave_sdk_server' is not installed`` on every
    install shape. The core precedent (benchweave_sdk.cli) passes the
    derived ``__version__`` explicitly."""
    from click.testing import CliRunner

    from benchweave_sdk_server.cli import cli

    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0, result.output
    assert "version" in result.output


def test_serve_without_the_full_extra_closure_refuses_through_the_entry(
    starter_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #97's Windows red, as an arm: blocking the extra's FULL import
    closure (benchweave_ui_html included — the sim's miss), the console
    entry's own module chain must stay importable and the serve command
    must answer the prefixed refusal. Pre-fix, the entry died at import:
    cli.py:28 (from .seam import ...) -> seam.py:36 (from .plots import
    ObservationRing) -> plots.py:26 (from benchweave_ui_html.plot import
    ...) -> ModuleNotFoundError — the A-E contract (the CLI module chain
    imports nothing from the extra set) broken by the plot wrapper."""
    _simulate_default_install(monkeypatch, *_SERVER_EXTRA_MODULES)
    monkeypatch.delitem(sys.modules, "benchweave_sdk_server.cli", raising=False)
    import benchweave_sdk_server.cli as cli_module

    result = CliRunner().invoke(
        cli_module.cli, ["serve", str(starter_project), "--no-open"]
    )
    assert result.exit_code == 2, result.output
    assert "benchweave_sdk_server_extras_missing:" in result.output
    assert "benchweave-sdk[server]" in result.output


# --- issue #422 increment 1: serve --env-file (the gateway twin) ---------------


@pytest.fixture()
def clean_benchweave_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Scrub every ``BENCHWEAVE_*`` process-env key for the arm, restoring
    the exact prior state afterwards — INCLUDING keys the env-file loader
    bridges into ``os.environ`` with a bare setdefault, which monkeypatch
    cannot track (the gateway twin's suite carries the same fixture)."""
    original = {
        key: value for key, value in os.environ.items() if key.startswith("BENCHWEAVE_")
    }
    for key in original:
        monkeypatch.delenv(key, raising=False)
    yield
    for key in [key for key in os.environ if key.startswith("BENCHWEAVE_") and key not in original]:
        del os.environ[key]


def _env_file(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "svc.env"
    path.write_text(body, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_s1_env_file_sets_the_capture_dir_the_seam_resolves(
    starter_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    clean_benchweave_env: None,
) -> None:
    """S1: ``--env-file`` carries ``BENCHWEAVE_CAPTURE_DIR`` and the serve
    surface resolves THE FILE's value — proven on the real resolution path:
    the serial transport's operator-action token file lands under the
    file's directory (``capture_root`` reads the environment the loader
    bridged, set-if-not-set)."""
    from_file = tmp_path / "cap-from-file"
    path = _env_file(tmp_path, f"BENCHWEAVE_CAPTURE_DIR={from_file}\n")
    output = _serve_output(
        starter_project,
        monkeypatch,
        tmp_path,
        "--transport",
        "serial",
        "--env-file",
        str(path),
    )
    payload = json.loads((from_file / "operator-action-token.json").read_text())
    assert payload["url"].startswith("http://127.0.0.1:8477/?operator_action=")
    # The default root was NOT used — the file's value is the one that
    # resolved.
    assert not (tmp_path / "captures" / "operator-action-token.json").exists()
    assert "loaded" in output


def test_s2_process_env_capture_dir_beats_the_file(
    starter_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    clean_benchweave_env: None,
) -> None:
    """S2: explicit process environment always wins (flag > process env >
    file — Decision 9's precedence family, the gateway twin's rule)."""
    from_file = tmp_path / "cap-from-file"
    from_env = tmp_path / "cap-from-env"
    path = _env_file(tmp_path, f"BENCHWEAVE_CAPTURE_DIR={from_file}\n")
    monkeypatch.setenv("BENCHWEAVE_CAPTURE_DIR", str(from_env))
    _serve_output(
        starter_project,
        monkeypatch,
        tmp_path,
        "--transport",
        "serial",
        "--env-file",
        str(path),
    )
    assert (from_env / "operator-action-token.json").is_file()
    assert not (from_file / "operator-action-token.json").exists()


def test_s6_without_the_flag_no_file_is_read(
    starter_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    clean_benchweave_env: None,
) -> None:
    """S6: without ``--env-file`` zero filesystem reads change — a canary
    ``benchweave.env`` in the working directory is NOT discovered (the
    explicit-flag divergence the design record's section 3 records), and
    the default capture-root resolution stands."""
    canary = tmp_path / "benchweave.env"
    canary.write_text("BENCHWEAVE_CAPTURE_DIR=/nonexistent-canary\n", encoding="utf-8")
    canary.chmod(0o600)
    output = _serve_output(
        starter_project, monkeypatch, tmp_path, "--transport", "serial"
    )
    payload = json.loads((tmp_path / "captures" / "operator-action-token.json").read_text())
    assert payload["pid"] == os.getpid()
    assert "loaded" not in output
    assert "env_file:" not in output
