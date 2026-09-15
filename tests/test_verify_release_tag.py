"""Verify the release-tag guard used by the publish workflow."""

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_release_tag.py"
PYPROJECT = ROOT / "pyproject.toml"


def run(tag: str, pyproject: Path = PYPROJECT) -> subprocess.CompletedProcess[int]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), tag, "--pyproject", str(pyproject)],
        capture_output=True,
        text=True,
        check=False,
    )


def write_pyproject(tmp_path: Path, version: str) -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(f'[project]\nname = "x"\nversion = "{version}"\n', encoding="utf-8")
    return path


def test_tag_with_v_prefix_matches(tmp_path: Path) -> None:
    assert run("v9.9.9", write_pyproject(tmp_path, "9.9.9")).returncode == 0


def test_bare_tag_matches(tmp_path: Path) -> None:
    assert run("1.2.3", write_pyproject(tmp_path, "1.2.3")).returncode == 0


def test_pre_release_tag_matches(tmp_path: Path) -> None:
    assert run("v0.2.0rc1", write_pyproject(tmp_path, "0.2.0rc1")).returncode == 0


def test_mismatch_fails_with_message(tmp_path: Path) -> None:
    result = run("v0.2.0", write_pyproject(tmp_path, "0.1.0"))
    assert result.returncode == 1
    assert "does not match" in result.stderr


def test_missing_pyproject_is_config_error(tmp_path: Path) -> None:
    assert run("v1.0.0", tmp_path / "nope.toml").returncode == 2


def test_real_pyproject_tag_matches() -> None:
    version = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    assert run(f"v{version}").returncode == 0
