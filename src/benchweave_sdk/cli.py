"""Software-only SDK commands. No registry publication or hardware access."""

from __future__ import annotations

import ipaddress
import sys
import webbrowser
from collections.abc import Callable, Sequence
from functools import wraps
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import click

from . import __version__
from .console import ConsoleOutput
from .packaging import inventory
from .scaffold import create_project
from .validation import validate_descriptor


def _domain_errors[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return function(*args, **kwargs)
        except (ValueError, OSError, RuntimeError) as exc:
            raise click.ClickException(str(exc)) from exc

    return guarded


def _presentation_options[R](function: Callable[..., R]) -> Callable[..., R]:
    options = (
        click.option("--descriptor", required=True, type=click.Path(path_type=Path)),
        click.option(
            "--resources",
            required=True,
            type=click.Path(path_type=Path),
            help="Package resource root",
        ),
        click.option("--catalogue", required=True, type=click.Path(path_type=Path)),
        click.option("--firmware"),
        click.option("--feature", multiple=True),
        click.option("--panel", multiple=True),
    )
    decorated = function
    for option in reversed(options):
        decorated = option(decorated)
    return decorated


@click.group()
@click.version_option(__version__)
def cli() -> None:
    """Software-only SDK commands; no publication or hardware access."""


@cli.command("new")
@click.argument("directory", type=click.Path(path_type=Path))
@click.option("--package", "package_name", default="example_plugin", show_default=True)
@click.option("--with-ui", is_flag=True, help="Add optional read-only UI resources")
@_domain_errors
def new_command(directory: Path, package_name: str, with_ui: bool) -> None:
    """Create a synthetic external plugin project."""
    create_project(directory, package_name)
    if with_ui:
        from .presentation import create_ui_resources

        create_ui_resources(directory, package_name)
    ConsoleOutput().message(
        f"Created synthetic plugin at {directory}; review before hardware or publication.",
        style="green",
    )


@cli.command("check")
@click.argument("descriptor", type=click.Path(path_type=Path))
@_domain_errors
def check_command(descriptor: Path) -> None:
    """Run offline descriptor schema and basic semantic checks."""
    import json

    from .presentation import read_file

    validate_descriptor(json.loads(read_file(descriptor)))
    ConsoleOutput().message(
        "Descriptor schema and basic S01/S02 checks passed; "
        "full conformance and hardware evidence remain separate.",
        style="green",
    )


@cli.command("inventory")
@click.argument("directory", type=click.Path(path_type=Path))
@_domain_errors
def inventory_command(directory: Path) -> None:
    """Print hashes for a prepared bundle; not a release manifest."""
    ConsoleOutput().document(inventory(directory))


def _render_report(report: object) -> None:
    output = ConsoleOutput()
    findings = [(row.code, row.path, row.message) for row in report.findings]  # type: ignore[attr-defined]
    findings.extend(("panel_unavailable", str(page), "") for page in report.unavailable_pages)  # type: ignore[attr-defined]
    if findings:
        output.findings(findings)
    if not report.valid:  # type: ignore[attr-defined]
        raise click.ClickException("Presentation validation failed.")
    output.message(
        "Offline presentation checks passed; not admission or approval to apply settings.",
        style="green",
    )


@cli.command("check-ui")
@click.argument("envelope", type=click.Path(path_type=Path))
@_presentation_options
@_domain_errors
def check_ui_command(
    envelope: Path,
    descriptor: Path,
    resources: Path,
    catalogue: Path,
    firmware: str | None,
    feature: tuple[str, ...],
    panel: tuple[str, ...],
) -> None:
    """Validate a presentation candidate offline."""
    from .presentation import check_ui

    report = check_ui(
        envelope,
        descriptor,
        resources,
        catalogue,
        firmware=firmware,
        features=frozenset(feature),
        panels=frozenset(panel),
    )
    _render_report(report)


@cli.command("check-preset")
@click.argument("preset", type=click.Path(path_type=Path))
@click.option("--descriptor", required=True, type=click.Path(path_type=Path))
@click.option("--settings-schema", required=True, type=click.Path(path_type=Path))
@click.option("--firmware", required=True)
@_domain_errors
def check_preset_command(
    preset: Path, descriptor: Path, settings_schema: Path, firmware: str
) -> None:
    """Validate complete settings offline."""
    from .presentation import read_file, validate_preset

    report = validate_preset(
        read_file(preset),
        descriptor_raw=read_file(descriptor),
        settings_schema_raw=read_file(settings_schema),
        firmware=firmware,
    )
    _render_report(report)


@cli.command("sync-standards")
@click.argument("bundle", type=click.Path(path_type=Path))
@click.option("--check", "check_only", is_flag=True, help="Verify the vendored tree only")
@_domain_errors
def sync_standards_command(bundle: Path, check_only: bool) -> None:
    """Import a standards bundle into the SDK's vendored tree and lock."""
    from .standards_sync import sync

    report = sync(
        bundle,
        sdk_root=Path(__file__).resolve().parents[2],
        check_only=check_only,
    )
    summary = ", ".join(
        f"{label}: {len(rows)}"
        for label, rows in (
            ("added", report.added),
            ("changed", report.changed),
            ("deprecated", report.deprecated),
            ("removed", report.removed),
        )
    )
    ConsoleOutput().message(
        f"Standards {'verified' if check_only else 'synced'} ({summary}).",
        style="green",
    )


def _renderer_origin(renderer_url: str | None) -> str | None:
    if renderer_url is None:
        return None
    parsed = urlsplit(renderer_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"preview_renderer_url_invalid: {renderer_url}")
    host = parsed.hostname or ""
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if not loopback:
        # Author-editable plugin docs can suggest command lines; a non-loopback
        # renderer would get CORS-trusted API access without the bundled
        # renderer's simulation labelling. Keep trust on the operator's machine.
        raise ValueError(
            f"preview_renderer_origin_not_local: {renderer_url} must name a loopback "
            "host; serve third-party renderers locally"
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def _renderer_target(renderer_url: str | None, api_base: str) -> str:
    if renderer_url is None:
        return api_base
    parsed = urlsplit(renderer_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["apiBase"] = api_base
    return urlunsplit(parsed._replace(query=urlencode(query)))


def _run_preview(
    *,
    envelope: Path,
    descriptor: Path,
    resources: Path,
    catalogue: Path,
    fixtures: Path | None,
    firmware: str | None,
    feature: tuple[str, ...],
    panel: tuple[str, ...],
    renderer_url: str | None,
    host: str,
    port: int,
    allow_network: bool,
    no_open: bool,
) -> None:
    from .fixtures import build_preview_model
    from .presentation import load_validated_preview_inputs
    from .preview_server import PreviewServer, bundled_assets, validate_listener

    validate_listener(host, allow_network)
    renderer_origin = _renderer_origin(renderer_url)
    if fixtures is not None and not fixtures.is_dir():
        raise ValueError(f"preview_fixtures_directory_expected: {fixtures}")
    candidate = load_validated_preview_inputs(
        envelope,
        descriptor,
        resources,
        catalogue,
        firmware=firmware,
        features=frozenset(feature),
        panels=frozenset(panel),
    )
    if fixtures is not None:
        candidate = type(candidate)(
            envelope=candidate.envelope,
            manifest=candidate.manifest,
            binding_catalogue=candidate.binding_catalogue,
            resource_root=fixtures.parent,
        )
    model = build_preview_model(candidate)
    server = PreviewServer(
        model,
        bundled_assets(),
        host=host,
        port=port,
        allow_network=allow_network,
        allowed_origin=renderer_origin,
    )
    try:
        address = server.start()
        target_url = _renderer_target(renderer_url, address.url)
        if renderer_url is not None:
            ConsoleOutput().message(
                "Custom renderer: a developer-supplied page is display, not the bundled "
                "BenchWeave renderer; all data remains simulated.",
                style="yellow",
            )
        if no_open or not sys.stdout.isatty():
            ConsoleOutput().preview_ready(
                target_url,
                scenarios=len(model.scenarios),
                renderer_version=model.renderer_version,
            )
            try:
                opened = False if no_open else webbrowser.open(target_url)
            except webbrowser.Error:
                opened = False
            if not no_open and not opened:
                ConsoleOutput().message(f"Browser did not open; use {target_url}", style="yellow")
            server.wait()
            return
        from .preview_tui import PreviewStatusApp

        PreviewStatusApp(
            url=target_url,
            renderer_version=model.renderer_version,
            scenarios=len(model.scenarios),
            open_browser=webbrowser.open,
            shutdown=server.shutdown,
            open_on_mount=True,
        ).run()
    except KeyboardInterrupt:
        return
    finally:
        server.shutdown()


@cli.command("preview-ui")
@click.argument("envelope", type=click.Path(path_type=Path))
@_presentation_options
@click.option("--fixtures", type=click.Path(path_type=Path))
@click.option("--renderer-url")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=0, type=click.IntRange(0, 65535), show_default=True)
@click.option("--allow-network", is_flag=True)
@click.option("--no-open", is_flag=True)
@_domain_errors
def preview_ui_command(**options: object) -> None:
    """Preview simulated presentation states on a local renderer."""
    _run_preview(**options)  # type: ignore[arg-type]


def main(args: Sequence[str] | None = None) -> int:
    """Run the Click group and return a process-compatible exit code."""
    try:
        cli.main(
            args=list(args) if args is not None else None,
            prog_name="benchweave-sdk",
            standalone_mode=False,
        )
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.exceptions.Exit as exc:
        return exc.exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
