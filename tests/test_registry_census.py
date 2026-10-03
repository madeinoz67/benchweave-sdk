"""C4's no-erasure arms: the command census and the append-only tree diff.

The census pins the Click group's command set exactly, so a ``delete`` or
``purge`` cannot appear silently. The tree-diff snapshots the clone before
and after every registry operation and asserts: records/ changes are
additions only; no file is ever deleted; the ONLY content change any
command may make to an existing file is the operated release's
status.json/status.sig pair (the one sanctioned rewrite target, under
sequence+1 semantics). Self-proving arms demonstrate the checker detects a
planted deletion and the census detects a planted command — the pins are
not vacuously green.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "registry-clone"
RELEASE = "northwind-instruments/vmx3-power-supply@1.0.0"
PRE_ACCEPTANCE = "harborline-systems/sig-analyzer@0.3.0"


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _diff(before: dict[str, str], after: dict[str, str]) -> dict[str, set[str]]:
    return {
        "added": set(after) - set(before),
        "changed": {p for p in set(after) & set(before) if after[p] != before[p]},
        "deleted": set(before) - set(after),
    }


def _invoke(clone: Path, *args: str) -> Any:
    from benchweave_sdk.cli import cli

    return CliRunner().invoke(cli, ["registry", *args, "--registry-clone", str(clone)])


@pytest.fixture()
def clone(tmp_path: Path) -> Path:
    target = tmp_path / "registry-clone"
    shutil.copytree(FIXTURE, target)
    return target


@pytest.fixture()
def origin_key(tmp_path: Path) -> Path:
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
    return key_path


# --- the command census ------------------------------------------------------------


def test_registry_group_command_set_is_pinned_exactly() -> None:
    from benchweave_sdk.cli import cli

    group = cli.commands["registry"]
    assert set(group.commands) == {
        "queue", "status", "publish-status", "yank", "advise",
        "unlist", "withdraw", "transfer",
    }
    # The top-level set is pinned too: the family arrived, nothing else moved
    # (doctor, WS1b, then upgrade/adopt, issue #347 WS2, are the additions since).
    assert set(cli.commands) == {
        "new", "upgrade", "adopt", "check", "inventory", "check-ui", "check-preset",
        "sync-standards", "package", "timestamp", "submit", "preview-ui",
        "registry", "doctor",
    }


def test_the_census_detects_a_planted_command() -> None:
    """Self-proving arm: a 'purge' appearing in the group fails the pin."""
    from benchweave_sdk.cli import cli

    group = cli.commands["registry"]

    @group.command("purge", hidden=True)
    def _planted() -> None:  # pragma: no cover - planted, never invoked
        """A planted destructive command the census must catch."""

    try:
        with pytest.raises(AssertionError):
            assert set(group.commands) == {
                "queue", "status", "publish-status", "yank", "advise",
                "unlist", "withdraw", "transfer",
            }
    finally:
        del group.commands["purge"]


# --- the append-only tree diff ------------------------------------------------------


def test_every_registry_op_is_append_only(clone: Path, origin_key: Path) -> None:
    keyed = ["--origin-key", str(origin_key)]
    ops: list[tuple[str, list[str], set[str]]] = [
        # (label, argv, allowed content-change targets for THIS op)
        ("publish-status", ["publish-status", RELEASE, *keyed,
                            "--expires-at", "2030-01-01T00:00:00Z"],
         {"releases/benchweave-registry/northwind-instruments/"
          "vmx3-power-supply/1.0.0/status.json",
          "releases/benchweave-registry/northwind-instruments/"
          "vmx3-power-supply/1.0.0/status.sig"}),
        ("yank", ["yank", RELEASE, *keyed, "--reason", "r", "--actor", "a"],
         {"releases/benchweave-registry/northwind-instruments/"
          "vmx3-power-supply/1.0.0/status.json",
          "releases/benchweave-registry/northwind-instruments/"
          "vmx3-power-supply/1.0.0/status.sig"}),
        ("advise", ["advise", RELEASE, *keyed, "--actor", "a",
                    "--id", "BW-2026-0001", "--severity", "low",
                    "--summary", "s", "--url", "https://example.invalid/a"],
         {"releases/benchweave-registry/northwind-instruments/"
          "vmx3-power-supply/1.0.0/status.json",
          "releases/benchweave-registry/northwind-instruments/"
          "vmx3-power-supply/1.0.0/status.sig"}),
        ("unlist", ["unlist", RELEASE, "--reason", "r", "--actor", "a"], set()),
        ("transfer", ["transfer", RELEASE, "--to", "harborline-systems",
                      "--consent-from", "northwind-instruments consents",
                      "--consent-to", "harborline-systems accepts",
                      "--reason", "r", "--actor", "a"], set()),
        ("withdraw", ["withdraw", PRE_ACCEPTANCE, "--reason", "r", "--actor", "a",
                      "--kind", "community-shared"], set()),
    ]
    for label, argv, allowed_changes in ops:
        before = _snapshot(clone)
        result = _invoke(clone, *argv)
        assert result.exit_code == 0, (label, result.output)
        after = _snapshot(clone)
        delta = _diff(before, after)
        # C4: no operation erases anything — git history stays the floor.
        assert delta["deleted"] == set(), (label, delta["deleted"])
        # Existing files outside the sanctioned status pair never change.
        assert delta["changed"] <= allowed_changes, (label, delta["changed"])
        # Every records/ change is a NEW file (append-only records).
        records_changed = {p for p in delta["changed"] if p.startswith("records/")}
        assert records_changed == set(), (label, records_changed)
        assert all(
            path.startswith("records/lifecycle/") or path.startswith("releases/")
            for path in delta["added"]
        ), (label, delta["added"])


def test_the_tree_diff_detects_a_planted_deletion(clone: Path) -> None:
    """Self-proving arm: the checker is not vacuously green — a deletion of
    committed bytes between snapshots is reported."""
    before = _snapshot(clone)
    planted = (
        clone / "records" / "lifecycle" / "northwind-instruments"
        / "vmx3-power-supply" / "1.0.0" / "1-publish.json"
    )
    planted.unlink()
    delta = _diff(before, _snapshot(clone))
    planted_rel = (
        "records/lifecycle/northwind-instruments/vmx3-power-supply/1.0.0/1-publish.json"
    )
    assert planted_rel in delta["deleted"]
    assert delta["deleted"] != set()


def test_the_tree_diff_detects_a_planted_rewrite(clone: Path) -> None:
    """Self-proving arm: rewriting a record file (not the status pair) is
    reported as a change outside the sanctioned targets."""
    before = _snapshot(clone)
    planted = (
        clone / "records" / "lifecycle" / "northwind-instruments"
        / "vmx3-power-supply" / "1.0.0" / "1-publish.json"
    )
    doc = json.loads(planted.read_bytes())
    doc["lifecycle"]["reason"] = "rewritten"
    planted.write_text(json.dumps(doc))
    delta = _diff(before, _snapshot(clone))
    assert delta["changed"] == {
        "records/lifecycle/northwind-instruments/vmx3-power-supply/1.0.0/1-publish.json"
    }
