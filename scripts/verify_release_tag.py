"""Verify a release tag equals project.version before publishing to PyPI."""

import argparse
import sys
import tomllib
from pathlib import Path


def tag_matches(tag: str, version: str) -> bool:
    return tag.removeprefix("v") == version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="release tag, e.g. v0.1.0")
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    args = parser.parse_args(argv)
    try:
        version = tomllib.loads(args.pyproject.read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        print(
            f"verify_release_tag: cannot read project.version from {args.pyproject}: {exc}",
            file=sys.stderr,
        )
        return 2
    if not tag_matches(args.tag, version):
        print(
            f"verify_release_tag: tag {args.tag!r} does not match project.version {version!r}",
            file=sys.stderr,
        )
        return 1
    print(f"verify_release_tag: tag {args.tag} matches project.version {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
