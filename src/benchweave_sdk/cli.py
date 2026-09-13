"""Software-only SDK commands. No registry publication or hardware access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .packaging import inventory
from .scaffold import create_project
from .validation import validate_descriptor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="Create a synthetic external plugin project")
    new.add_argument("directory", type=Path)
    new.add_argument("--package", default="example_plugin")
    new.add_argument("--with-ui", action="store_true", help="Add optional read-only UI resources")
    check = commands.add_parser("check", help="Offline descriptor schema and basic semantic checks")
    check.add_argument("descriptor", type=Path)
    bundle = commands.add_parser(
        "inventory", help="Print hashes for a prepared bundle; not a release manifest"
    )
    bundle.add_argument("directory", type=Path)
    ui = commands.add_parser("check-ui", help="Validate a presentation candidate offline")
    ui.add_argument("envelope", type=Path)
    ui.add_argument("--descriptor", required=True, type=Path)
    ui.add_argument("--resources", required=True, type=Path, help="Package resource root")
    ui.add_argument("--catalogue", required=True, type=Path)
    ui.add_argument("--firmware")
    ui.add_argument("--feature", action="append", default=[])
    ui.add_argument("--panel", action="append", default=[])
    preset = commands.add_parser("check-preset", help="Validate complete settings offline")
    preset.add_argument("preset", type=Path)
    preset.add_argument("--descriptor", required=True, type=Path)
    preset.add_argument("--settings-schema", required=True, type=Path)
    preset.add_argument("--firmware", required=True)
    args = parser.parse_args()
    try:
        if args.command == "new":
            create_project(args.directory, args.package)
            if args.with_ui:
                from .presentation import create_ui_resources

                create_ui_resources(args.directory, args.package)
            print(
                f"Created synthetic plugin at {args.directory}; "
                "review before hardware or publication."
            )
        elif args.command == "check":
            validate_descriptor(json.loads(args.descriptor.read_text(encoding="utf-8")))
            print(
                "Descriptor schema and basic S01/S02 checks passed; "
                "full conformance and hardware evidence remain separate."
            )
        elif args.command in ("check-ui", "check-preset"):
            from .presentation import check_ui, read_file, validate_preset

            if args.command == "check-ui":
                report = check_ui(
                    args.envelope,
                    args.descriptor,
                    args.resources,
                    args.catalogue,
                    firmware=args.firmware,
                    features=frozenset(args.feature),
                    panels=frozenset(args.panel),
                )
            else:
                report = validate_preset(
                    read_file(args.preset),
                    descriptor_raw=read_file(args.descriptor),
                    settings_schema_raw=read_file(args.settings_schema),
                    firmware=args.firmware,
                )
            for finding in report.findings:
                print(f"{finding.code}: {finding.path}: {finding.message}")
            for page in report.unavailable_pages:
                print(f"panel_unavailable: {page}")
            if not report.valid:
                parser.exit(1, "Presentation validation failed.\n")
            print(
                "Offline presentation checks passed; not admission or approval to apply settings."
            )
        else:
            print(json.dumps(inventory(args.directory), indent=2))
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
