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


def _project(tmp_path: Path, extras: str, *, name: str = "pinned") -> Path:
    project = tmp_path / name
    project.mkdir()
    (project / "pyproject.toml").write_text(
        PYPROJECT_TEMPLATE.format(name=name, extras=extras), encoding="utf-8"
    )
    return project


def _pin_project(tmp_path: Path, pin: str, *, name: str = "pinned") -> Path:
    return _project(tmp_path, f'test = ["benchweave-sdk=={pin}", "pytest>=8.0"]', name=name)


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


# --- refute fold wave (F1–F7): PEP 508 parsing, normalized compare, honest wording ---


@pytest.mark.parametrize(
    ("requirement", "expected"),
    [
        ("benchweave-sdk[signing]==0.5.0", "0.5.0"),
        ("benchweave-sdk == 0.5.0", "0.5.0"),
        ("BenchWeave-SDK==0.5.0", "0.5.0"),
    ],
)
def test_pep508_spellings_still_record(tmp_path: Path, requirement: str, expected: str) -> None:
    """F1: a hand-edited pin's realistic spellings must not silently unrecord."""
    extras = f"test = ['{requirement}', 'pytest>=8.0']"
    assert scaffold.recorded_sdk_version(_project(tmp_path, extras, name="spelling")) == expected


def test_env_marker_after_the_pin_still_records(tmp_path: Path) -> None:
    """F1: the marker case alone — TOML literal quoting keeps its double quotes verbatim."""
    extras = 'test = [\'benchweave-sdk==0.5.0; python_version >= "3.13"\', \'pytest>=8.0\']'
    assert scaffold.recorded_sdk_version(_project(tmp_path, extras, name="marker")) == "0.5.0"


def test_a_non_version_pin_is_not_a_record(tmp_path: Path) -> None:
    """F1: garbage after == is not a recorded version (previously it was returned as-is)."""
    extras = "test = ['benchweave-sdk==..++--', 'pytest>=8.0']"
    assert scaffold.recorded_sdk_version(_project(tmp_path, extras, name="garbage")) is None


def test_duplicate_pins_first_valid_wins(tmp_path: Path) -> None:
    """F7 (documented behavior): the first requirement with a version-shaped == pin wins."""
    extras = "test = ['benchweave-sdk==zz', 'benchweave-sdk==0.0.1', 'benchweave-sdk==9.9.9']"
    assert scaffold.recorded_sdk_version(_project(tmp_path, extras, name="dupes")) == "0.0.1"


def test_under_padded_pin_matches_the_normalized_installed_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """F2: `0.5` vs installed `0.5.0` is a match — the comparison normalizes both sides."""
    parts = __version__.split("+")[0].split(".")
    if len(parts) < 3:
        pytest.skip("installed release already minimal; the padding case is unprovable")
    if parts[2] != "0":
        pytest.skip(
            f"padding appends .0, so the under-padded pin means {parts[0]}.{parts[1]}.0 — "
            f"a genuinely different version from the installed {__version__} "
            "(first non-zero-patch release exposed this); the case is provable "
            "only when the patch digit is 0"
        )
    project = _pin_project(tmp_path, ".".join(parts[:2]))
    assert run("doctor", project) == 0
    out = capsys.readouterr().out
    assert "matches" in out
    assert "mismatch" not in out


def test_advice_command_uses_the_normalized_pin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """F2: the advised reinstall never carries a v prefix."""
    if __version__ == "0.0.1":
        pytest.skip("installed SDK equals the normalized fixture pin; unprovable")
    project = _pin_project(tmp_path, "v0.0.1")
    assert run("doctor", project) == 0
    out = capsys.readouterr().out
    assert "'benchweave-sdk==0.0.1'" in out
    assert "==v0.0.1" not in out


def test_mismatch_claims_a_pin_not_provenance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """F3: the pin is a mutable requirement line; the message must not claim otherwise."""
    if __version__ == "0.0.1":
        pytest.skip("installed SDK equals the fixture pin; unprovable")
    project = _pin_project(tmp_path, "0.0.1")
    assert run("doctor", project) == 0
    out = capsys.readouterr().out
    assert "this project pins benchweave-sdk 0.0.1" in out
    assert "scaffolded with" not in out


def test_a_file_argument_is_a_distinct_refusal_from_a_missing_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """F4: an existing file path is `not a directory`, not `not found`."""
    blocker = tmp_path / "notes.txt"
    blocker.write_text("a regular file", encoding="utf-8")
    assert run("doctor", blocker) == 1
    assert "project_not_a_directory" in capsys.readouterr().err
    assert run("doctor", tmp_path / "nope") == 1
    assert "project_directory_not_found" in capsys.readouterr().err


def test_empty_and_blank_arguments_are_the_default_cwd(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """F5: `doctor ""` and a blank argument explicitly target `.`, never an error
    (the blank arm: previously exit 1 with a space-suffixed `not found` path)."""
    monkeypatch.chdir(_pin_project(tmp_path, __version__))
    for argument in ("", "  "):
        capsys.readouterr()
        assert run("doctor", argument) == 0
        assert "matches" in capsys.readouterr().out
