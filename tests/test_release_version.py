"""Pin the reported version to the declared package version."""

import tomllib
from pathlib import Path

import benchweave_sdk

ROOT = Path(__file__).resolve().parents[1]


def test_dunder_version_tracks_pyproject() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert benchweave_sdk.__version__ == pyproject["project"]["version"]
