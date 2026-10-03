"""S5: the cross-repo gate arm and the twin's no-xfail meta-test.

The gate arm runs the full SDK op sequence on a gate-coherent fixture clone
and invokes the registry repository's own validators over the result,
asserting ZERO findings — mechanically pinning every F1/F6/F9-class drift
the green suites on either side could miss. It needs a checkout of the
registry repository's branch (BENCHWEAVE_REGISTRY_CLONE); CI has none, so
the arm skips there and the local/refute runs carry the pin.

The meta-test asserts the namespace twin ships no xfails and no skips beyond
the env-guarded ones — a permanent guard against pins quietly rotting into
expected-failure.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest
from click.testing import CliRunner

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "registry-clone"
RELEASE = "northwind-instruments/vmx3-power-supply@1.0.0"
REPO = Path(__file__).resolve().parents[1]

#: The twin module's env-guarded arms — the only skips ever allowed there.
ENV_GUARDED_TWIN_SKIPS = 2


def test_sdk_op_sequence_passes_the_registry_gate(tmp_path: Path) -> None:
    clone_root = os.environ.get("BENCHWEAVE_REGISTRY_CLONE")
    if not clone_root:
        pytest.skip("BENCHWEAVE_REGISTRY_CLONE not set; no registry checkout")
    validators = Path(clone_root) / "scripts"
    validate_records = validators / "validate_records.py"
    validate_status = validators / "validate_release_status.py"
    for script in (validate_records, validate_status):
        if not script.is_file():
            pytest.skip(f"registry checkout carries no {script.name} (branch state)")

    clone = tmp_path / "registry-clone"
    shutil.copytree(FIXTURE, clone)
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "origin.pem"
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    from benchweave_sdk.cli import cli

    runner = CliRunner()
    ops = [
        ["publish-status", RELEASE, "--origin-key", str(key_path),
         "--expires-at", "2030-01-01T00:00:00Z"],
        ["advise", RELEASE, "--origin-key", str(key_path), "--actor", "registry-maintainer",
         "--id", "BW-2026-0001", "--severity", "medium", "--summary", "probe advisory",
         "--url", "https://example.invalid/a1"],
        ["yank", RELEASE, "--origin-key", str(key_path), "--reason", "probe-yank",
         "--actor", "registry-maintainer"],
        ["unlist", RELEASE, "--reason", "probe-unlist", "--actor", "registry-maintainer"],
        ["transfer", RELEASE, "--to", "harborline-systems", "--reason", "probe-transfer",
         "--actor", "registry-coordinator"],
    ]
    for op in ops:
        result = runner.invoke(cli, ["registry", *op, "--registry-clone", str(clone)])
        assert result.exit_code == 0, (op[0], result.output)

    for script in (validate_records, validate_status):
        completed = subprocess.run(
            [sys.executable, str(script), "--root", str(clone)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, (
            script.name,
            completed.stdout,
            completed.stderr,
        )
        assert "valid" in completed.stdout, (script.name, completed.stdout)


def test_the_namespace_twin_has_no_xfails_and_no_unexpected_skips(
    tmp_path: Path,
) -> None:
    """Lane B's machine-check 2, permanent: the twin module ships zero
    xfails, and its only skips are the env-guarded arms."""
    report = tmp_path / "twin-junit.xml"
    completed = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "tests/test_namespace_twin.py", "-q", "--junitxml", str(report),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    root = ElementTree.parse(report).getroot()
    suite = root.find("testsuite") if root.tag == "testsuites" else root
    assert suite is not None
    xfailed = sum(
        1
        for skipped in suite.iter("skipped")
        if skipped.get("type") == "pytest.xfail"
    )
    assert xfailed == 0, "the namespace twin carries xfail pins — reconcile, do not expect failure"
    total_skipped = sum(1 for _ in suite.iter("skipped"))
    env_set = bool(os.environ.get("BENCHWEAVE_REGISTRY_CLONE"))
    assert total_skipped == (0 if env_set else ENV_GUARDED_TWIN_SKIPS), (
        total_skipped,
        "only the env-guarded arms may skip",
    )
    assert int(suite.get("failures", "0")) == 0
    assert int(suite.get("errors", "0")) == 0
