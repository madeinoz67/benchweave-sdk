"""The ``benchweave-sdk-server`` CLI: serve and the stdio MCP entry.

``serve`` validates the plugin's descriptor and presentation documents
BEFORE binding any port (SW-05 — refusal text carries the SDK's diagnostics
under a ``standalone_plugin_invalid:`` prefix), reuses the SDK preview
server's listener rules verbatim (loopback default, wildcard refused,
non-loopback only with ``--allow-network`` plus a warning — NFR-S1), and
constructs the COMPLETE guard set unconditionally. The per-launch bearer
token is printed with the URL. ``mcp`` runs the same MCP server over stdio
with no HTTP listener and no HTTP guard material (NFR-S4).

On an install without the ``[server]`` extra, both commands refuse before
any work with ``benchweave_sdk_server_extras_missing:`` and exit 2 (the
R-9 shim pattern: Python extras cannot gate console scripts, so the
default install's entry point degrades honestly instead of tracebacking).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import click

from benchweave_sdk import __version__

from .seam import StandaloneSeam
from .session import (
    LoadedPlugin,
    PluginLoadError,
    load_plugin_project,
)

if TYPE_CHECKING:
    from .scenarios import ScenarioSelection

#: What a default (no-extra) install hears from serve/mcp/preview-ui: the
#: prefixed error names the install command (the R-9 shim pattern, exit 2).
def _scenario_ids() -> tuple[str, ...]:
    """The nine scenario ids, for the CLI's choice set (lazy import — the
    cli module stays importable on a default install)."""
    from .scenarios import SCENARIOS

    return tuple(row.id for row in SCENARIOS)


_EXTRAS_MESSAGE = (
    "benchweave_sdk_server_extras_missing: install 'benchweave-sdk[server]' "
    "for the serve, mcp and preview-ui commands"
)


def _require_server_extra(exc: ImportError) -> NoReturn:
    """Refuse on a missing extra: message, exit 2, never a traceback."""
    click.echo(_EXTRAS_MESSAGE, err=True)
    raise SystemExit(2) from exc


def _load(project: Path) -> LoadedPlugin:
    try:
        return load_plugin_project(project)
    except PluginLoadError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(2) from exc


def _build_seam(
    project: Path,
    *,
    transport: str = "mock",
    scenario: str | None = None,
    unattended: bool = False,
    device: str | None = None,
    open_port: Any = None,
    capture_root: Any = None,
    bindings: Path | None = None,
    serial_hooks: Any = None,
) -> tuple[StandaloneSeam, ScenarioSelection | None]:
    """Compose the seam over one transport (§4.1's composition step).

    Transport selection happens HERE and nowhere else: the factory bound
    below is the transport's whole expression, and nothing server-side —
    the seam, the routes, the templates — knows or cares which one it is.
    A scenario selection is refused on any transport but the mock
    (scenarios do not exist on real hardware, the banner rule's sibling)
    and returns the mutable selection the device page can switch. The
    session factories read the CURRENT plugin at connect time (the
    late-bound ``mock_plugin_session`` shape) so a reload's reconnect
    speaks the new plugin's own script; scenario mode additionally hands
    the seam the scenario wrapper so a reload re-binds the scenario
    adapter over the reloaded project. The serial branch composes ONE
    ``SerialEndpoint`` (issue #385 §1.4) shared by the session factory and
    the seam, and opens the binding store HERE — a malformed
    ``device-bindings.json`` refuses serve construction with the prefixed
    message and exit 2, never a mid-request traceback. ``--device`` is the
    headless/scripted CONSTANT endpoint (the binding bypass, §1.6);
    without it the endpoint is binding-backed and the host serves
    binding-pending until the operator picks. ``serial_hooks`` is the
    test-injection axis for discovery + resolution enumeration (the
    ``open_port`` sibling).
    """
    from .scenarios import (
        ScenarioSelection,
        scenario_session,
        wrap_scenario_plugin,
    )
    from .serial import SerialEndpoint, serial_plugin_session
    from .session import mock_plugin_session

    plugin = _load(project)
    if scenario is not None:
        if transport != "mock":
            click.echo(
                "standalone_scenario_mock_only: scenarios exist on the mock "
                "transport; serve real hardware without --scenario",
                err=True,
            )
            raise SystemExit(2)
        selection = ScenarioSelection(scenario)
        return (
            StandaloneSeam(
                scenario_session(plugin, selection),
                transport_kind="mock",
                unattended=unattended,
                reload_wrapper=wrap_scenario_plugin,
                capture_root=capture_root,
            ),
            selection,
        )
    if transport == "serial":
        from .binding import BindingStore, binding_endpoint, bindings_path

        try:
            store = BindingStore.open(bindings_path(bindings))
        except ValueError as exc:
            click.echo(str(exc), err=True)
            raise SystemExit(2) from exc
        hooks = serial_hooks
        # ONE enumeration callable serves both masters in both forms: the
        # binding-backed resolver (below) and the mint-time serial
        # recording (serial_plugin_session) — the discovery short-circuit's
        # reconciliation reads what the factory noted, so the CLI's two
        # forms arm it equally (trust-2).
        if hooks is not None:
            enumerate_ports = hooks.enumerate_ports
        else:
            from .serial import _pyserial_enumerate

            enumerate_ports = _pyserial_enumerate
        if device:
            # The --device form is the constant endpoint (the binding
            # bypass, §1.6): the store is loaded and validated but never
            # consulted for resolution, and never modified.
            endpoint = SerialEndpoint(device)
        else:
            # F-385-2 (adopted): serve starts BINDING-PENDING — the
            # refusal moved to connect time (``binding_absent``) so the UI
            # can render the pick; a stored binding resolves straight away.
            endpoint = SerialEndpoint(
                binding_endpoint(
                    store, plugin.package, plugin.device_id, enumerate_ports
                )
            )
        return (
            StandaloneSeam(
                serial_plugin_session(
                    plugin,
                    endpoint,
                    open_port=open_port,
                    capture_root=capture_root,
                    enumerate_ports=enumerate_ports,
                ),
                transport_kind="serial",
                unattended=unattended,
                serial_ports=hooks,
                # The no-re-probe clause (I3 §3.3, issue #389) now flows
                # from the endpoint's last_resolution — the path the live
                # session actually opened. Alias spellings of the same
                # physical port (cu vs tty, by-id symlinks) do not match
                # and still re-probe — the alias-matching follow-up owns
                # that.
                serial_endpoint=endpoint,
                bindings=store,
                capture_root=capture_root,
            ),
            None,
        )
    if device is not None:
        click.echo(
            "standalone_transport_device_serial_only: --device applies only to "
            "--transport serial",
            err=True,
        )
        raise SystemExit(2)
    return (
        StandaloneSeam(
            mock_plugin_session(plugin, capture_root=capture_root),
            transport_kind=transport,
            unattended=unattended,
            capture_root=capture_root,
        ),
        None,
    )


@click.group()
# PR #90 carry-forward row R4: the explicit derived version follows the
# core precedent (benchweave_sdk.cli) — bare version_option() infers the
# distribution name from the module, and benchweave_sdk_server is never a
# distribution (the host rides benchweave-sdk), so --version crashed with
# RuntimeError on every install shape. Derived, never a literal (the
# zero-literal gate's register discipline); a source checkout answers
# "0.0.0+source" instead of crashing.
@click.version_option(__version__)
def cli() -> None:
    """Standalone BenchWeave host: one process, no gateway."""


@cli.command()
@click.argument("project", type=click.Path(path_type=Path, exists=True))
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8477, type=click.IntRange(1, 65535), show_default=True)
@click.option("--allow-network", is_flag=True)
@click.option("--no-open", is_flag=True)
@click.option(
    "--transport",
    type=click.Choice(["mock", "serial"]),
    default="mock",
    show_default=True,
)
@click.option(
    "--device",
    default=None,
    help=(
        "Serial device path: the headless constant endpoint (the binding "
        "bypass). Without it, a serial host serves binding-pending until an "
        "endpoint is picked in the UI, or a stored binding resolves. "
        "Refused on non-serial transports."
    ),
)
@click.option(
    "--bindings",
    type=click.Path(path_type=Path),
    default=None,
    help=(
        "The device-bindings document (default: "
        "BENCHWEAVE_STANDALONE_BINDINGS, then device-bindings.json under "
        "the working directory). One row per plugin and connection key; "
        "validated at startup."
    ),
)
@click.option(
    "--capture-root",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory captures publish under (default: BENCHWEAVE_CAPTURE_DIR, "
    "then captures/ under the working directory). One host process per root.",
)
@click.option(
    "--scenario",
    type=click.Choice(_scenario_ids()),
    default=None,
    help="Serve one of the nine baseline states (mock transport only).",
)
@click.option("--authoring", is_flag=True)
@click.option(
    "--unattended",
    is_flag=True,
    help="Waive the reload confirmation for adapter-code changes while a "
    "device is connected (valid only with --authoring; Q11 option 2).",
)
def serve(
    project: Path,
    host: str,
    port: int,
    allow_network: bool,
    no_open: bool,
    transport: str,
    device: str | None,
    bindings: Path | None,
    capture_root: Path | None,
    scenario: str | None,
    authoring: bool,
    unattended: bool,
) -> None:
    """Serve UI, REST and MCP over one plugin project."""
    if unattended and not authoring:
        raise click.UsageError(
            "--unattended requires --authoring (Q11: it waives an operator gate)"
        )
    try:
        # All three ride the [server] extra: web and uvicorn directly, and
        # security through starlette's middleware base -- the module-level
        # import set must stay free of every name the extra owns, or the
        # console script dies before click can even print --help (the A-E
        # default-venv arm caught exactly that, through starlette).
        import uvicorn

        from .security import GuardPolicy, new_token, validate_listener
        from .web import build_app
    except ImportError as exc:
        _require_server_extra(exc)

    try:
        validate_listener(host, allow_network)
    except ValueError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(2) from exc
    if allow_network:
        click.echo(
            f"warning: listening on {host} exposes this bench beyond loopback; "
            "the bearer token below is the only gate.",
            err=True,
        )
    seam, selection = _build_seam(
        project,
        transport=transport,
        scenario=scenario,
        unattended=unattended,
        device=device,
        bindings=bindings,
        capture_root=capture_root,
    )
    if seam.session.plugin.load_diagnostic is not None:
        # §4.5: the degraded load BINDS (exit 0) with its diagnostic on
        # stderr — the author sees the UI and the reason before the adapter
        # works.
        click.echo(seam.session.plugin.load_diagnostic, err=True)
    policy = GuardPolicy.complete(
        bound_host=host,
        bound_port=port,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )
    app = build_app(seam, policy=policy, authoring=authoring, scenario=selection)
    click.echo(f"Serving {seam.session.plugin.package} on http://{host}:{port}")
    click.echo(f"Bearer token (REST mutations and MCP over HTTP): {policy.bearer_token}")
    if not no_open:
        import webbrowser

        # A host with no registered browser is headless Linux's ordinary
        # state — webbrowser.open RAISES webbrowser.Error there, which used
        # to crash serve before uvicorn ran (crash-before-bind; the old SDK
        # preview carried this same guard, and the old gateway arm pinned
        # it). Degrade to the notice: the server is the point, not the
        # browser (review fold F1 on gateway PR #400).
        try:
            opened = webbrowser.open(f"http://{host}:{port}")
        except webbrowser.Error:
            opened = False
        if not opened:
            click.echo(f"Browser did not open; use http://{host}:{port}", err=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")


@cli.command()
@click.argument("project", type=click.Path(path_type=Path, exists=True))
@click.option("--authoring", is_flag=True)
@click.option(
    "--unattended",
    is_flag=True,
    help="Waive the reload confirmation for adapter-code changes while a "
    "device is connected (valid only with --authoring; Q11 option 2).",
)
def mcp(project: Path, authoring: bool, unattended: bool) -> None:
    """Run the MCP server over stdio (no HTTP listener, no HTTP guards)."""
    if unattended and not authoring:
        raise click.UsageError(
            "--unattended requires --authoring (Q11: it waives an operator gate)"
        )
    try:
        from .mcp import build_mcp
    except ImportError as exc:
        _require_server_extra(exc)

    seam, _ = _build_seam(project, unattended=unattended)
    server = build_mcp(seam, authoring=authoring)
    server.run()


def main(argv: list[str] | None = None) -> int:
    """Run the Click group and return a process-compatible exit code
    (the SDK CLI's main shape: click's own errors — UsageError,
    BadParameter — surface as usage text with their exit codes, never
    as tracebacks out of the console script; fold F2).
    """
    try:
        cli.main(
            args=list(argv) if argv is not None else None,
            prog_name="benchweave-sdk-server",
            standalone_mode=False,
        )
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.exceptions.Exit as exc:
        return exc.exit_code
    except click.exceptions.Abort:
        # Ctrl-C at a prompt: match standalone mode's clean exit, not a
        # traceback (the SDK CLI's wording and rationale, verbatim).
        click.echo("Aborted!", err=True)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
