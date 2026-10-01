"""Software-only SDK commands. No hardware access; publication is prepared
offline and never signed here (the signing half is maintainer-side)."""

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
from .publishing import (
    build_submission,
    parse_dependency,
    validate_transport_triple,
)
from .scaffold import create_project
from .validation import validate_descriptor, verify_provider_pin


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
    """Software-only SDK commands; no hardware access, no signing, no service."""


@cli.command("new")
@click.argument("directory", type=click.Path(path_type=Path))
@click.option("--package", "package_name", default="example_plugin", show_default=True)
@click.option("--with-ui", is_flag=True, help="Add optional read-only UI resources")
@_domain_errors
def new_command(directory: Path, package_name: str, with_ui: bool) -> None:
    """Create a synthetic external plugin project."""
    # Resolve before the first write: `new --with-ui` reads the descriptor back
    # through the symlink-refusing walk, so a destination reached through a
    # symlinked ancestor must become its canonical path up front.
    destination = directory.expanduser().resolve()
    create_project(destination, package_name)
    if with_ui:
        from .presentation import create_ui_resources

        create_ui_resources(destination, package_name)
    ConsoleOutput().message(
        f"Created synthetic plugin at {destination}; review before hardware or publication.",
        style="green",
    )


@cli.command("check")
@click.argument("descriptor", type=click.Path(path_type=Path))
@_domain_errors
def check_command(descriptor: Path) -> None:
    """Run offline descriptor schema and basic semantic checks."""
    import json
    import warnings

    from .presentation import read_file
    from .validation import YankedPinWarning

    document = json.loads(read_file(descriptor))
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        validate_descriptor(document)
    # The provider pin is the one check that needs the package on disk: it
    # resolves descriptor-relative and hashes the pinned bytes.
    verify_provider_pin(document, descriptor)
    for warning in captured:
        if issubclass(warning.category, YankedPinWarning):
            ConsoleOutput().message(f"warning: {warning.message}", style="yellow")
    ConsoleOutput().message(
        "Descriptor schema and basic S01/S02/S04 checks passed; "
        "full conformance and hardware evidence remain separate.",
        style="green",
    )


@cli.command("inventory")
@click.argument("directory", type=click.Path(path_type=Path))
@_domain_errors
def inventory_command(directory: Path) -> None:
    """Print hashes for a prepared bundle; not a release manifest."""
    ConsoleOutput().document(inventory(directory))


def _render_report(report: object, note: str | None = None) -> None:
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
    if note is not None:
        output.message(note, style="yellow")


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
@click.option(
    "--action",
    "action",
    default=None,
    help="Force the action whose envelope is applied "
    "(default: resolve from the settings-schema identity)",
)
@_domain_errors
def check_preset_command(
    preset: Path, descriptor: Path, settings_schema: Path, firmware: str, action: str | None
) -> None:
    """Validate complete settings offline."""
    from .presentation import read_file, resolve_preset_action, validate_preset

    report = validate_preset(
        read_file(preset),
        descriptor_raw=read_file(descriptor),
        settings_schema_raw=read_file(settings_schema),
        firmware=firmware,
        action_id=action,
    )
    note: str | None = None
    if report.valid:
        # Recomputed via the same resolver the enforcement uses, so the note
        # cannot disagree with what was applied.
        resolved = (
            action
            if action is not None
            else resolve_preset_action(
                read_file(preset), descriptor_raw=read_file(descriptor)
            )
        )
        note = (
            f"envelope applied: {resolved}"
            if resolved is not None
            else "no descriptor envelope applied (settings schema is not a corpus "
            "action schema; pass --action to force one)"
        )
    _render_report(report, note=note)


def _sdk_checkout_root() -> Path | None:
    """The SDK repository checkout containing this module, or None when installed.

    Repo mode needs both halves to hold: the grandparent directory is a
    checkout whose pyproject names this project, AND this module actually
    runs from that checkout's ``src`` tree. A --target/PYTHONPATH install
    that happens to sit inside a checkout satisfies the first test but not
    the second — sync must not treat the checkout as the running package.
    """
    from .validation import _project_name

    package_dir = Path(__file__).resolve().parent
    candidate = package_dir.parents[1]
    if _project_name(candidate) != "benchweave-sdk":
        return None
    if package_dir != candidate / "src" / "benchweave_sdk":
        return None
    return candidate


@cli.command("sync-standards")
@click.argument("bundle", required=False, type=click.Path(path_type=Path))
@click.option("--check", "check_only", is_flag=True, help="Verify the vendored tree only")
@_domain_errors
def sync_standards_command(bundle: Path | None, check_only: bool) -> None:
    """Import a standards bundle into the SDK's vendored tree and lock.

    With --check and no bundle, verify the committed lock and vendored tree
    alone; no main-project export is read. An installed SDK (no repository
    checkout) supports only that --check form, against its packaged lock.
    """
    from .standards_sync import sync, verify_installed

    sdk_root = _sdk_checkout_root()
    if sdk_root is None:
        if bundle is not None or not check_only:
            raise ValueError(
                "sync_requires_repo_checkout: importing a bundle rewrites the SDK "
                "source tree; an installed SDK supports only 'sync-standards --check'"
            )
        verify_installed()
        ConsoleOutput().message(
            "Standards verified (packaged lock and vendored tree agree).",
            style="green",
        )
        return
    report = sync(
        bundle,
        sdk_root=sdk_root,
        check_only=check_only,
    )
    summary = ", ".join(
        f"{label}: {len(rows)}"
        for label, rows in (
            ("added", report.added),
            ("changed", report.changed),
            ("deprecated", report.deprecated),
            ("removed", report.removed),
            ("active-changes", report.active_changes),
        )
    )
    if check_only and any(
        (
            report.added,
            report.changed,
            report.deprecated,
            report.removed,
            report.active_changes,
        )
    ):
        # A non-empty report in check mode is drift awaiting sync, not success.
        raise click.ClickException(
            f"standards drift detected ({summary}); re-run sync-standards to update"
        )
    if bundle is None:
        ConsoleOutput().message(
            "Standards verified (committed lock and vendored tree agree).",
            style="green",
        )
        return
    ConsoleOutput().message(
        f"Standards {'verified' if check_only else 'synced'} ({summary}).",
        style="green",
    )


def _capability_map(flags: tuple[str, ...]) -> dict[str, bool] | None:
    """--capability flags to the closed three-way declaration (CR-45)."""
    allowed = {
        "network-egress": "network_egress",
        "subprocess-or-native-library": "subprocess_or_native_library",
        "filesystem-writes": "filesystem_writes_beyond_evidence_retention",
    }
    declaration = {
        "network_egress": False,
        "subprocess_or_native_library": False,
        "filesystem_writes_beyond_evidence_retention": False,
    }
    for flag in flags:
        if flag not in allowed:
            raise click.ClickException(
                f"capability_unknown:{flag} (expected none of or any of: "
                + ", ".join(sorted(allowed))
                + ")"
            )
        declaration[allowed[flag]] = True
    return declaration


@cli.command("package")
@click.argument("plugin_dir", type=click.Path(path_type=Path))
@click.option(
    "--registry-clone", required=True, type=click.Path(path_type=Path),
    help="A clone of benchweave-registry (namespace rules, prior releases)",
)
@click.option("--source-url", required=True, help="The plugin source repository URL")
@click.option(
    "--revision", required=True, help="Immutable commit digest (40- or 64-hex) being released"
)
@click.option("--publisher", required=True, help="Your vetted publisher id")
@click.option("--plugin", default=None, help="Plugin name (default: the directory name)")
@click.option(
    "--version", default=None, help="Release version (default: the plugin's pyproject version)"
)
@click.option(
    "--out",
    required=True,
    type=click.Path(path_type=Path),
    help="Output directory for the artefact set",
)
@click.option(
    "--capability",
    multiple=True,
    help=(
        "Declared capability, repeatable: network-egress | "
        "subprocess-or-native-library | filesystem-writes; pass none for an explicit none"
    ),
)
@click.option(
    "--dependency",
    multiple=True,
    help="Registry dependency <registry_id>/<package_id>@<version>:<sha256>, repeatable",
)
@click.option(
    "--transport-triple",
    multiple=True,
    help="Admitted triple <id>@<version>:<sha256> a transport-declaring descriptor publishes",
)
@click.option("--licence-spdx", default="MIT", show_default=True)
@_domain_errors
def package_command(
    plugin_dir: Path,
    registry_clone: Path,
    source_url: str,
    revision: str,
    publisher: str,
    plugin: str | None,
    version: str | None,
    out: Path,
    capability: tuple[str, ...],
    dependency: tuple[str, ...],
    transport_triple: tuple[str, ...],
    licence_spdx: str,
) -> None:
    """Package a finished plugin into the submission artefact set (offline, keyless)."""
    from .publishing import PublishingError

    if capability == ("none",):
        capability = ()
    try:
        artifacts = build_submission(
            plugin_dir,
            registry_clone=registry_clone,
            source_url=source_url,
            revision=revision,
            publisher=publisher,
            plugin=plugin,
            version=version,
            capability_declaration=_capability_map(capability),
            dependencies=[parse_dependency(spec) for spec in dependency],
            transport_triples=tuple(
                validate_transport_triple(triple) for triple in transport_triple
            ),
            licence_spdx=licence_spdx,
        )
    except PublishingError as exc:
        raise click.ClickException(str(exc)) from exc
    written = artifacts.write(out)
    output = ConsoleOutput()
    output.message(
        f"Packaged {artifacts.manifest['package_id']}@{artifacts.manifest['version']} "
        f"(manifest sha256 {artifacts.submission['manifest_sha256'][:12]}…); "
        "deterministic and keyless — signing is maintainer-side.",
        style="green",
    )
    for path in written:
        output.message(f"  {path}", style="green")


@cli.command("submit")
@click.argument("artifacts_dir", type=click.Path(path_type=Path))
@click.option(
    "--registry-clone", required=True, type=click.Path(path_type=Path),
    help="Working clone of benchweave-registry; the submission branch is created here",
)
@click.option("--base", default="main", show_default=True)
@click.option("--open-pr", is_flag=True, help="Open the PR via gh when available")
@_domain_errors
def submit_command(artifacts_dir: Path, registry_clone: Path, base: str, open_pr: bool) -> None:
    """Write a packaged artefact set into the registry repository and branch (CR-6)."""
    import json
    import subprocess

    from .publishing import submission_branch

    submission = json.loads((artifacts_dir / "submission.json").read_bytes())
    branch, target, remote_url = submission_branch(
        registry_clone, artifacts_dir, submission, base=base
    )
    output = ConsoleOutput()
    output.message(
        f"Submission branch {branch} created; artefacts staged under {target}",
        style="green",
    )
    if remote_url:
        compare = f"{remote_url.rstrip('.git')}/compare/{base}...{branch}"
        if open_pr and subprocess.run(["gh", "--version"], capture_output=True).returncode == 0:
            subprocess.run(  # noqa: S603, S607 — optional sugar over git
                [
                    "gh", "pr", "create", "--repo", remote_url, "--head", branch,
                    "--title",
                    f"Submission {submission['package_id']}@{submission['version']}",
                    "--fill",
                ],
                check=False,
            )
        else:
            output.message(f"Open the submission PR: {compare}", style="yellow")


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
    except click.exceptions.Abort:
        # Ctrl-C at a prompt: match standalone mode's clean exit, not a traceback.
        click.echo("Aborted!", err=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
