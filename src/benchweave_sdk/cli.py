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
    check = commands.add_parser("check", help="Offline descriptor schema and basic semantic checks")
    check.add_argument("descriptor", type=Path)
    bundle = commands.add_parser(
        "inventory", help="Print hashes for a prepared bundle; not a release manifest"
    )
    bundle.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "new":
            create_project(args.directory, args.package)
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
        else:
            print(json.dumps(inventory(args.directory), indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
