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
from typing import TYPE_CHECKING, NoReturn

import click

from .seam import StandaloneSeam
from .session import (
    LoadedPlugin,
    PluginLoadError,
    PluginSession,
    load_plugin_project,
    mock_exchanges,
)
from .transport import LoopingMockHost

if TYPE_CHECKING:
    from .scenarios import ScenarioSelection

#: What a default (no-extra) install hears from serve/mcp: the prefixed
#: error names the install command (the R-9 shim pattern, exit 2).
def _scenario_ids() -> tuple[str, ...]:
    """The nine scenario ids, for the CLI's choice set (lazy import — the
    cli module stays importable on a default install)."""
    from .scenarios import SCENARIOS

    return tuple(row.id for row in SCENARIOS)


_EXTRAS_MESSAGE = (
    "benchweave_sdk_server_extras_missing: install 'benchweave-sdk[server]' "
    "for the serve and mcp commands"
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
    project: Path, *, transport: str = "mock", scenario: str | None = None
) -> tuple[StandaloneSeam, ScenarioSelection | None]:
    """Compose the seam over one transport (§4.1's composition step).

    Transport selection happens HERE and nowhere else: the factory bound
    below is the transport's whole expression, and nothing server-side —
    the seam, the routes, the templates — knows or cares which one it is.
    A scenario selection is refused on any transport but the mock
    (scenarios do not exist on real hardware, the banner rule's sibling)
    and returns the mutable selection the device page can switch.
    """
    from .scenarios import ScenarioSelection, scenario_session

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
            StandaloneSeam(scenario_session(plugin, selection), transport_kind="mock"),
            selection,
        )
    return (
        StandaloneSeam(
            PluginSession(plugin, lambda: LoopingMockHost(mock_exchanges(plugin))),
            transport_kind=transport,
        ),
        None,
    )


@click.group()
@click.version_option()
def cli() -> None:
    """Standalone BenchWeave host: one process, no gateway."""


@cli.command()
@click.argument("project", type=click.Path(path_type=Path, exists=True))
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8477, type=click.IntRange(1, 65535), show_default=True)
@click.option("--allow-network", is_flag=True)
@click.option("--no-open", is_flag=True)
@click.option("--transport", type=click.Choice(["mock"]), default="mock", show_default=True)
@click.option(
    "--scenario",
    type=click.Choice(_scenario_ids()),
    default=None,
    help="Serve one of the nine baseline states (mock transport only).",
)
@click.option("--authoring", is_flag=True)
def serve(
    project: Path,
    host: str,
    port: int,
    allow_network: bool,
    no_open: bool,
    transport: str,
    scenario: str | None,
    authoring: bool,
) -> None:
    """Serve UI, REST and MCP over one plugin project."""
    try:
        # All three ride the [server] extra: web and uvicorn directly, and
        # security through starlette's middleware base -- the module-level
        # import set must stay free of every name the extra owns, or the
        # console script dies before click can even print --help (the A-E
        # default-venv arm caught exactly that, through starlette).
        import uvicorn

        from .security import GuardPolicy, new_token
        from .web import build_app
    except ImportError as exc:
        _require_server_extra(exc)

    from benchweave_sdk.preview_server import validate_listener

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
    seam, selection = _build_seam(project, transport=transport, scenario=scenario)
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

        webbrowser.open(f"http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


@cli.command()
@click.argument("project", type=click.Path(path_type=Path, exists=True))
@click.option("--authoring", is_flag=True)
def mcp(project: Path, authoring: bool) -> None:
    """Run the MCP server over stdio (no HTTP listener, no HTTP guards)."""
    try:
        from .mcp import build_mcp
    except ImportError as exc:
        _require_server_extra(exc)

    seam, _ = _build_seam(project)
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
