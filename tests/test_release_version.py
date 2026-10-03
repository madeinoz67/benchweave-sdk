"""Pin the reported version to the declared package version."""

import tomllib
from pathlib import Path

import benchweave_sdk

ROOT = Path(__file__).resolve().parents[1]


def test_dunder_version_tracks_pyproject() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert benchweave_sdk.__version__ == pyproject["project"]["version"]


def test_server_dunder_version_tracks_the_same_distribution() -> None:
    """Issue #309 slice A: the server host rides the benchweave-sdk
    distribution, so its __version__ derives from the same installed dist
    (importlib.metadata) — the standalone distribution's own 0.1.0 died
    with it, and the literal-free rule (zero-literal gate) holds only if
    the derivation, not a constant, carries the number."""
    import benchweave_sdk_server

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert benchweave_sdk_server.__version__ == pyproject["project"]["version"]
