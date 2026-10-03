"""`doctor` names a stale SDK offline: scaffold pin vs installed version (#347 WS1b)."""

from pathlib import Path

import pytest

from benchweave_sdk import __version__, cli, scaffold

PYPROJECT_TEMPLATE = """[build-system]
requires = ["hatchling>=1.26"]
build-backend = "hatchling.build"
[project]
name = "{name}"
version = "0.1.0"
dependencies = []
[project.optional-dependencies]
{extras}
"""


def run(*arguments: str | Path) -> int:
    return cli.main([*map(str, arguments)])


def _pin_project(tmp_path: Path, pin: str, *, name: str = "pinned") -> Path:
    extras = f'test = ["benchweave-sdk=={pin}", "pytest>=8.0"]'
    project = tmp_path / name
    project.mkdir()
    (project / "pyproject.toml").write_text(
        PYPROJECT_TEMPLATE.format(name=name, extras=extras), encoding="utf-8"
    )
    return project


def test_stale_pin_names_both_versions_and_a_next_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R-3's falsifier: doctor prints 'project vX, you have vY, run Z' — and a
    mismatch is a report, never a failure (design note Q2)."""
    if __version__ == "0.0.1":
        pytest.skip("installed SDK equals the fixture pin; a mismatch is unprovable")
    project = _pin_project(tmp_path, "0.0.1")
    assert run("doctor", project) == 0
    out = capsys.readouterr().out
    assert "0.0.1" in out
    assert __version__ in out
    assert "benchweave-sdk==0.0.1" in out  # the concrete next step


def test_matching_pin_confirms(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _pin_project(tmp_path, __version__)
    assert run("doctor", project) == 0
    out = capsys.readouterr().out
    assert __version__ in out
    assert "matches" in out


def test_no_recorded_pin_is_reported_not_failed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "unpinned"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        PYPROJECT_TEMPLATE.format(name="unpinned", extras='test = ["pytest>=8.0"]'),
        encoding="utf-8",
    )
    assert run("doctor", project) == 0
    assert "No scaffold version recorded" in capsys.readouterr().out


def test_missing_pyproject_is_no_record_not_a_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "empty"
    project.mkdir()
    assert run("doctor", project) == 0
    assert "No scaffold version recorded" in capsys.readouterr().out


def test_missing_directory_is_a_typed_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("doctor", tmp_path / "nope") == 1
    assert "project_directory_not_found" in capsys.readouterr().err


def test_default_directory_is_the_cwd(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _pin_project(tmp_path, __version__)
    monkeypatch.chdir(project)
    assert run("doctor") == 0
    assert __version__ in capsys.readouterr().out


# --- the marker mechanism: what `new` writes is what `doctor` reads ---


def test_recorded_version_reads_the_test_extra_pin(tmp_path: Path) -> None:
    assert scaffold.recorded_sdk_version(_pin_project(tmp_path, "0.0.1")) == "0.0.1"


def test_recorded_version_ignores_unpinned_and_other_extras(tmp_path: Path) -> None:
    project = tmp_path / "loose"
    project.mkdir()
    extras = 'dev = ["benchweave-sdk==0.0.1"]\ntest = ["benchweave-sdk", "pytest>=8.0"]'
    (project / "pyproject.toml").write_text(
        PYPROJECT_TEMPLATE.format(name="loose", extras=extras), encoding="utf-8"
    )
    assert scaffold.recorded_sdk_version(project) is None


def test_recorded_version_refuses_a_broken_pyproject_typed(tmp_path: Path) -> None:
    project = tmp_path / "broken"
    project.mkdir()
    (project / "pyproject.toml").write_text("not [ toml", encoding="utf-8")
    with pytest.raises(ValueError, match="pyproject_unreadable"):
        scaffold.recorded_sdk_version(project)


def test_scaffold_writes_the_pin_doctor_reads(tmp_path: Path) -> None:
    """Symmetry proof: `new` records exactly the SDK version `doctor` compares
    against, so a fresh scaffold always doctors clean."""
    project = tmp_path / "generated"
    scaffold.create_project(project, "example_plugin")
    assert scaffold.recorded_sdk_version(project) == __version__
