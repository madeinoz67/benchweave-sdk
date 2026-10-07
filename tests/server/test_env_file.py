"""Issue #422 increment 1: the serve env-file loader (the gateway twin).

``benchweave_sdk_server serve --env-file <path>`` loads ``KEY=VALUE`` lines
into the environment, set-if-not-set, before the host resolves its
configuration — the SAME standard as the gateway's ``benchweave serve``
data-dir autoload (the issue's one-standard directive). This module pins
the loader's refusal surface (arms S3-S5 of the design record's section 3)
plus the shared semantics; the wiring arms S1/S2/S6 live in
``test_cli.py`` beside the other serve arms.

The parse rules and refusal wording are shared verbatim with the gateway
twin (``benchweave/cli/env_file.py``); the twin arms assert the SAME
literal expected strings both repos' suites assert, so the two cannot
drift silently.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from benchweave_sdk_server.cli import cli


@pytest.fixture()
def clean_benchweave_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Scrub every ``BENCHWEAVE_*`` process-env key for the arm, restoring
    the exact prior state afterwards — INCLUDING keys the env-file loader
    bridges into ``os.environ`` with a bare setdefault, which monkeypatch
    cannot track (the gateway twin's suite carries the same fixture)."""
    original = {
        key: value for key, value in os.environ.items() if key.startswith("BENCHWEAVE_")
    }
    for key in original:
        monkeypatch.delenv(key, raising=False)
    yield
    for key in [key for key in os.environ if key.startswith("BENCHWEAVE_") and key not in original]:
        del os.environ[key]


def _env_file(tmp_path: Path, body: str, mode: int = 0o600) -> Path:
    path = tmp_path / "svc.env"
    path.write_text(body, encoding="utf-8")
    path.chmod(mode)
    return path


def test_s3_a_db_key_in_an_sdk_env_file_refuses_as_unknown(
    starter_project: Path, tmp_path: Path, clean_benchweave_env: None
) -> None:
    """The SDK serve has no store: ``BENCHWEAVE_DB`` is not in its
    allowlist, and the refusal teaches that."""
    path = _env_file(tmp_path, "BENCHWEAVE_DB=/elsewhere/state.sqlite\n")
    result = CliRunner().invoke(
        cli, ["serve", str(starter_project), "--no-open", "--env-file", str(path)]
    )
    assert result.exit_code == 2, result.output
    assert "env_file:" in result.output
    assert "BENCHWEAVE_DB" in result.output
    assert "allowlisted" in result.output
    # The refusal names the SDK's own allowlist, not the gateway's.
    assert "BENCHWEAVE_STANDALONE_BINDINGS" in result.output
    assert "BENCHWEAVE_CAPTURE_DIR" in result.output


def test_s4_malformed_line_refuses_with_the_twin_literal(
    starter_project: Path, tmp_path: Path, clean_benchweave_env: None
) -> None:
    path = _env_file(tmp_path, "BENCHWEAVE_CAPTURE_DIR\n")
    result = CliRunner().invoke(
        cli, ["serve", str(starter_project), "--no-open", "--env-file", str(path)]
    )
    assert result.exit_code == 2, result.output
    # The twin literal — identical bytes in the gateway suite's A5 arm:
    assert (
        f'env_file: {path}: line 1: no "=" in line — expected KEY=VALUE'
        in result.output
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits; W1 residual")
def test_s5_group_readable_file_refuses_with_the_twin_literal(
    starter_project: Path, tmp_path: Path, clean_benchweave_env: None
) -> None:
    path = _env_file(tmp_path, "BENCHWEAVE_CAPTURE_DIR=/captures\n", mode=0o644)
    result = CliRunner().invoke(
        cli, ["serve", str(starter_project), "--no-open", "--env-file", str(path)]
    )
    assert result.exit_code == 2, result.output
    # The twin literal — identical bytes in the gateway suite's A11 arm:
    assert (
        f"env_file: {path}: mode 644 allows group or other access — the file"
        " carries a live secret; restrict it to the owner (chmod 0600)"
        in result.output
    )


def test_the_loader_applies_set_if_not_set_and_returns_applied_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_benchweave_env: None
) -> None:
    from benchweave_sdk_server.env_file import load_env_file, serve_env_file_keys

    assert serve_env_file_keys() == frozenset(
        {"BENCHWEAVE_STANDALONE_BINDINGS", "BENCHWEAVE_CAPTURE_DIR"}
    )
    path = _env_file(
        tmp_path,
        "# operator notes\n"
        "\n"
        "BENCHWEAVE_CAPTURE_DIR=/captures/with=equals#and-hash\n"
        "BENCHWEAVE_STANDALONE_BINDINGS=/bindings/doc.json\n",
    )
    monkeypatch.setenv("BENCHWEAVE_CAPTURE_DIR", "/from-process-env")
    applied = load_env_file(path, serve_env_file_keys())
    assert applied == ["BENCHWEAVE_STANDALONE_BINDINGS"]
    # Explicit process environment always wins (set-if-not-set); the first
    # '=' separates so a value may contain '='; a mid-line '#' is value
    # content; blank and comment-only lines are skipped.
    assert os.environ["BENCHWEAVE_CAPTURE_DIR"] == "/from-process-env"
    assert os.environ["BENCHWEAVE_STANDALONE_BINDINGS"] == "/bindings/doc.json"


def test_an_empty_value_refuses_and_never_sets_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benchweave_sdk_server.env_file import (
        EnvFileError,
        load_env_file,
        serve_env_file_keys,
    )

    monkeypatch.delenv("BENCHWEAVE_CAPTURE_DIR", raising=False)
    path = _env_file(tmp_path, "BENCHWEAVE_CAPTURE_DIR=\n")
    with pytest.raises(EnvFileError, match="set but empty"):
        load_env_file(path, serve_env_file_keys())
    assert "BENCHWEAVE_CAPTURE_DIR" not in os.environ


# --- fold wave (review battery): the twin parse-hardening rows ------------------


def _serve_env_loaded(
    starter_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    path: Path,
) -> Result:
    """One mock serve over ``--env-file`` with uvicorn parked and the cwd
    under a scratch root; the loader's bare env writes are the observable
    (the clean_benchweave_env fixture restores them)."""
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    monkeypatch.chdir(tmp_path)
    return CliRunner().invoke(
        cli, ["serve", str(starter_project), "--no-open", "--env-file", str(path)]
    )


def test_r1_leading_whitespace_after_the_equals_refuses(
    starter_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    clean_benchweave_env: None,
) -> None:
    """Fold R1 (twin): a value whose first character is a space/tab after
    the ``=`` refuses — the ``KEY = value`` typo class; NOT systemd-style
    trimming (trimming would re-open the silent-corruption class)."""
    for body in ('BENCHWEAVE_CAPTURE_DIR= "/caps"\n', "BENCHWEAVE_CAPTURE_DIR= /caps\n"):
        path = _env_file(tmp_path, body)
        result = _serve_env_loaded(starter_project, monkeypatch, tmp_path, path)
        assert result.exit_code == 2, result.output
        # The twin literal — identical bytes in the gateway suite's R1 arm:
        assert (
            f'env_file: {path}: line 1: BENCHWEAVE_CAPTURE_DIR: value starts'
            ' with whitespace after "=" in result.output'
        )
    # The healthy quoted form still loads.
    path = _env_file(tmp_path, 'BENCHWEAVE_CAPTURE_DIR="/caps"\n')
    result = _serve_env_loaded(starter_project, monkeypatch, tmp_path, path)
    assert result.exit_code == 0, result.output
    assert os.environ.get("BENCHWEAVE_CAPTURE_DIR") == "/caps"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits; W1 residual")
def test_r2_owner_only_mode_applies(
    starter_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    clean_benchweave_env: None,
) -> None:
    """Fold R2 (twin): the perms mask is 0o077 (group/other) — a file mode
    0700 is owner-only access and LOADS; S5's 0644 refusal stands."""
    path = _env_file(tmp_path, "BENCHWEAVE_CAPTURE_DIR=/caps\n", mode=0o700)
    result = _serve_env_loaded(starter_project, monkeypatch, tmp_path, path)
    assert result.exit_code == 0, result.output
    assert os.environ.get("BENCHWEAVE_CAPTURE_DIR") == "/caps"


def test_r3_control_characters_in_a_value_refuse(
    starter_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    clean_benchweave_env: None,
) -> None:
    """Fold R3 (twin): allowlist value domains never carry C0 controls —
    any 0x00-0x1F in a value refuses, validated before any env write."""
    path = _env_file(tmp_path, "BENCHWEAVE_CAPTURE_DIR=/ca\x01ps\n")
    result = _serve_env_loaded(starter_project, monkeypatch, tmp_path, path)
    assert result.exit_code == 2, result.output
    # The twin literal — identical bytes in the gateway suite's R3 arm:
    assert (
        f"env_file: {path}: line 1: BENCHWEAVE_CAPTURE_DIR: value contains"
        " a control character (0x01)" in result.output
    )


def test_r4_unicode_line_separators_stay_in_the_value(
    starter_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    clean_benchweave_env: None,
) -> None:
    """Fold R4 (twin): lines split on \r\n / \r / \n ONLY — U+2028 stays
    in the applied value verbatim (str.splitlines() would truncate)."""
    path = _env_file(tmp_path, "BENCHWEAVE_CAPTURE_DIR=/ca\u2028ps\n")
    result = _serve_env_loaded(starter_project, monkeypatch, tmp_path, path)
    assert result.exit_code == 0, result.output
    assert os.environ.get("BENCHWEAVE_CAPTURE_DIR") == "/ca\u2028ps"


def test_r9_duplicate_key_refuses_naming_both_lines(
    starter_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    clean_benchweave_env: None,
) -> None:
    """Fold R9 (twin): a duplicate key in one file is an editing mistake —
    refuse naming the key and both line numbers, never silently keep the
    first value."""
    path = _env_file(
        tmp_path,
        "BENCHWEAVE_CAPTURE_DIR=/one\nBENCHWEAVE_CAPTURE_DIR=/two\n",
    )
    result = _serve_env_loaded(starter_project, monkeypatch, tmp_path, path)
    assert result.exit_code == 2, result.output
    # The twin literal — identical bytes in the gateway suite's R9 arm:
    assert (
        f"env_file: {path}: line 2: BENCHWEAVE_CAPTURE_DIR appears twice"
        " (first at line 1) — one value per key" in result.output
    )


def test_r10_env_file_help_is_composed_from_the_allowlist_constant() -> None:
    """Fold R10: the --env-file help names the allowlist THROUGH the
    constant (no third spelling) — pinned by asserting the help carries
    the composed join AND that cli.py references the constant itself."""
    from benchweave_sdk_server import cli as cli_module
    from benchweave_sdk_server.env_file import ENV_FILE_HAND_NAMED_KEYS

    result = CliRunner().invoke(cli, ["serve", "--help"])
    assert result.exit_code == 0, result.output
    # Whitespace-normalized so click's help wrapping (word boundaries only)
    # cannot break the joined string.
    normalized = " ".join(result.output.split())
    assert ", ".join(ENV_FILE_HAND_NAMED_KEYS) in normalized
    assert "ENV_FILE_HAND_NAMED_KEYS" in Path(cli_module.__file__).read_text(
        encoding="utf-8"
    ), "the help must be composed from the allowlist constant, not spelled"
