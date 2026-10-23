"""L6 — the ``migrate-ui`` re-stamp command (issue #460, design §10 proof arms).

The coherent-stale fixture is the exact inverse of the migration: a fresh
``--with-ui`` scaffold from the CURRENT SDK, targeted down-substitution of
``contract_version`` in all three plugin-ui documents, then the envelope hash
recomputed over the downgraded manifest bytes. That is the byte-shape a
v0.10.0-era project actually carried (all three documents at plugin-ui 0.3.0
WITH a coherent envelope hash) — a naive version-swap twin would fail with
``digest_mismatch`` instead of the issue's own ``unsupported_version``
finding, so the fixture builder repairs the hash on purpose.

The historical stale version is pinned as a literal (``0.3.0``, the v0.10.0
release's active row per the design's §2 table); the migration target is
always derived from the lock at run time, so the arms stay meaningful across
future lock bumps (a future schema-shape bump makes the re-stamp refuse —
the design's R1, the safe direction).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk import cli, presentation, scaffold
from benchweave_sdk.served import _tuple, active_version

#: The plugin-ui version a project last touched by SDK v0.10.0 carried
#: (design §2's release-tag table). Fixture INPUT, not a generated stamp.
OLD = "0.3.0"
PACKAGE = "example_plugin"
_ACTIVE = active_version("plugin-ui")


def _stamp(raw: bytes, *, frm: str, to: str) -> bytes:
    """Swap one scaffold-formatted contract_version value; exactly once."""
    needle = f'"contract_version": "{frm}"'.encode()
    assert raw.count(needle) == 1, f"the {frm} stamp must appear exactly once"
    return raw.replace(needle, f'"contract_version": "{to}"'.encode())


def _repair_envelope_hash(package: Path, manifest_raw: bytes) -> None:
    envelope_path = package / "presentation.json"
    envelope = json.loads(envelope_path.read_bytes())
    envelope["manifest"]["sha256"] = hashlib.sha256(manifest_raw).hexdigest()
    envelope_path.write_bytes((json.dumps(envelope, indent=2) + "\n").encode())


def _fresh(project: Path, *, canary_page: dict[str, Any] | None = None) -> Path:
    """A current-SDK ``--with-ui`` scaffold, optionally with author content."""
    scaffold.create_project(project, PACKAGE, with_ui=True)
    presentation.create_ui_resources(project, PACKAGE)
    package = project / "src" / PACKAGE
    if canary_page is not None:
        manifest_path = package / "ui/manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["pages"].append(json.loads(json.dumps(canary_page)))
        manifest_raw = (json.dumps(manifest, indent=2) + "\n").encode()
        manifest_path.write_bytes(manifest_raw)
        _repair_envelope_hash(package, manifest_raw)
    return package


def _coherent_stale(
    project: Path, *, old: str = OLD, canary_page: dict[str, Any] | None = None
) -> Path:
    """The coherent-stale fixture: all three at ``old``, hash still coherent."""
    package = _fresh(project, canary_page=canary_page)
    manifest_path = package / "ui/manifest.json"
    manifest_raw = _stamp(manifest_path.read_bytes(), frm=_ACTIVE, to=old)
    manifest_path.write_bytes(manifest_raw)
    for name in ("presentation.json", "binding-catalogue.json"):
        path = package / name
        path.write_bytes(_stamp(path.read_bytes(), frm=_ACTIVE, to=old))
    _repair_envelope_hash(package, manifest_raw)
    return package


def run(monkeypatch: pytest.MonkeyPatch, *arguments: str | Path) -> int:
    return cli.main([*map(str, arguments)])


def migrate(monkeypatch: pytest.MonkeyPatch, package: Path) -> int:
    return run(
        monkeypatch,
        "migrate-ui",
        package / "presentation.json",
        "--descriptor",
        package / "descriptor.json",
        "--resources",
        package,
        "--catalogue",
        package / "binding-catalogue.json",
    )


def check_ui(monkeypatch: pytest.MonkeyPatch, package: Path) -> int:
    return run(
        monkeypatch,
        "check-ui",
        package / "presentation.json",
        "--descriptor",
        package / "descriptor.json",
        "--resources",
        package,
        "--catalogue",
        package / "binding-catalogue.json",
    )


def _tree(root: Path) -> dict[str, bytes]:
    """Project files keyed by relpath; caches and git internals excluded."""
    return {
        entry.relative_to(root).as_posix(): entry.read_bytes()
        for entry in sorted(root.rglob("*"))
        if entry.is_file()
        and not ({"__pycache__", ".pytest_cache", ".git"} & set(entry.parts))
    }


def _changed(before: dict[str, bytes], after: dict[str, bytes]) -> set[str]:
    return {name for name in set(before) | set(after) if before.get(name) != after.get(name)}


def _load_candidate(package: Path) -> Any:
    from benchweave_sdk.presentation import load_validated_preview_inputs

    return load_validated_preview_inputs(
        package / "presentation.json",
        package / "descriptor.json",
        package,
        package / "binding-catalogue.json",
        firmware=None,
        features=frozenset(),
        panels=frozenset(),
    )


def _generated_suite(project: Path) -> subprocess.CompletedProcess[str]:
    """Run the scaffold-generated conformance test in its own project."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(project / "src")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(project / "tests" / "test_presentation_preview.py"),
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


# --- proof arm 1: the defect, reproduced on the fixture (design §10) ------------


def test_coherent_stale_fixture_reproduces_issue_460(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The reporter's own failure string, on the fixture, before anything else."""
    package = _coherent_stale(tmp_path / "stale")
    with pytest.raises(
        ValueError, match="preview_invalid_presentation: unsupported_version: presentation-envelope"
    ):
        _load_candidate(package)
    capsys.readouterr()
    assert check_ui(monkeypatch, package) == 1
    # The findings table renders on stdout; only the ClickException is stderr.
    rendered = capsys.readouterr().out
    assert "unsupported_version" in rendered
    assert "presentation-envelope" in rendered


# --- proof arm 2: the migration (design §10 GREEN) ------------------------------


def test_migrate_ui_re_stamps_the_coherent_stale_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "project"
    package = _coherent_stale(project)
    before = _tree(project)

    capsys.readouterr()
    assert migrate(monkeypatch, package) == 0
    rendered = capsys.readouterr().out
    assert (
        f"migrated presentation.json: plugin-ui {OLD} -> {_ACTIVE}" in rendered
    ), rendered
    assert f"migrated ui/manifest.json: plugin-ui {OLD} -> {_ACTIVE}" in rendered
    assert f"migrated binding-catalogue.json: plugin-ui {OLD} -> {_ACTIVE}" in rendered

    after = _tree(project)
    assert _changed(before, after) == {
        f"src/{PACKAGE}/presentation.json",
        f"src/{PACKAGE}/ui/manifest.json",
        f"src/{PACKAGE}/binding-catalogue.json",
    }
    # The hash chain is repaired, not just the stamps.
    envelope = json.loads((package / "presentation.json").read_bytes())
    assert envelope["manifest"]["sha256"] == hashlib.sha256(
        (package / "ui/manifest.json").read_bytes()
    ).hexdigest()

    _load_candidate(package)
    assert run(monkeypatch, "check", package / "descriptor.json") == 0
    assert check_ui(monkeypatch, package) == 0

    # The generated conformance suite — the arm the reporter actually hit —
    # passes in the migrated project (collected count 1, failures 0).
    suite = _generated_suite(project)
    assert suite.returncode == 0, suite.stdout + suite.stderr
    assert "1 passed" in suite.stdout, suite.stdout


def test_mixed_versions_migrate_and_repair_the_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The reporter's half-done intermediate state finishes, not refuses."""
    project = tmp_path / "mixed"
    package = _fresh(project)
    manifest_path = package / "ui/manifest.json"
    manifest_raw = _stamp(manifest_path.read_bytes(), frm=_ACTIVE, to=OLD)
    manifest_path.write_bytes(manifest_raw)
    _repair_envelope_hash(package, manifest_raw)

    before = _tree(project)
    capsys.readouterr()
    assert migrate(monkeypatch, package) == 0
    rendered = capsys.readouterr().out
    assert f"migrated ui/manifest.json: plugin-ui {OLD} -> {_ACTIVE}" in rendered
    # The envelope moved only its hash: its version line says so.
    assert "migrated presentation.json:" in rendered
    assert "manifest hash repaired" in rendered
    assert _changed(before, _tree(project)) == {
        f"src/{PACKAGE}/presentation.json",
        f"src/{PACKAGE}/ui/manifest.json",
    }
    assert check_ui(monkeypatch, package) == 0


# --- proof arm 3: the five controls (design §10, bytes not prose) ---------------


def test_noop_control_at_active_project_changes_zero_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "fresh"
    package = _fresh(project)
    before = _tree(project)
    capsys.readouterr()
    assert migrate(monkeypatch, package) == 0
    assert f"already at plugin-ui {_ACTIVE}" in capsys.readouterr().out
    assert _tree(project) == before


def test_canary_control_author_page_survives_deep_equal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hand-added manifest page survives: re-stamp, never re-derivation."""
    canary = {
        "id": "author-notes",
        "title": "Author Notes",
        "kind": "readings",
        "bindings": ["voltage"],
        "required": False,
    }
    project = tmp_path / "canary"
    package = _coherent_stale(project, canary_page=canary)
    assert migrate(monkeypatch, package) == 0
    manifest = json.loads((package / "ui/manifest.json").read_bytes())
    assert manifest["pages"][-1] == canary
    expected = json.loads(json.dumps(manifest))
    expected["contract_version"] = _ACTIVE
    assert manifest == expected
    assert check_ui(monkeypatch, package) == 0


def test_ahead_control_refuses_with_zero_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "ahead"
    package = _coherent_stale(project, old="0.5.0")
    before = _tree(project)
    capsys.readouterr()
    assert migrate(monkeypatch, package) == 1
    assert "migrate_ui_ahead:" in capsys.readouterr().err
    assert _tree(project) == before


def test_refusal_control_drifted_descriptor_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """D1 posture: a drifted descriptor refuses with the digest finding."""
    project = tmp_path / "drifted"
    package = _coherent_stale(project)
    descriptor_path = package / "descriptor.json"
    descriptor = json.loads(descriptor_path.read_bytes())
    descriptor["description"] = descriptor["description"] + " (revised by the author)"
    descriptor_path.write_bytes((json.dumps(descriptor, indent=2) + "\n").encode())

    before = _tree(project)
    capsys.readouterr()
    assert migrate(monkeypatch, package) == 1
    rendered = capsys.readouterr().err
    assert "migrate_ui_invalid_after_stamp:" in rendered
    assert "digest_mismatch" in rendered
    assert _tree(project) == before


def test_stamp_unlocatable_control_is_a_typed_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A unicode-escaped stamp parses but cannot be re-stamped in place."""
    project = tmp_path / "escaped"
    package = _coherent_stale(project)
    manifest_path = package / "ui/manifest.json"
    manifest_raw = manifest_path.read_bytes().replace(
        f'"contract_version": "{OLD}"'.encode(),
        b'"contract_version": "\\u0030.\\u0033.\\u0030"',
    )
    manifest_path.write_bytes(manifest_raw)
    _repair_envelope_hash(package, manifest_raw)

    before = _tree(project)
    capsys.readouterr()
    assert migrate(monkeypatch, package) == 1
    assert "migrate_ui_stamp_unlocatable:" in capsys.readouterr().err
    assert _tree(project) == before


# --- the classref-family ledger (moved to the re-stamp set, #541 slice 2) --------


def test_classref_ledger_restamps_with_the_plugin_ui_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The detection-only advisory is retired for the two family stamps
    (standards record §8): a planted ledger one family behind re-stamps in
    the same run as the plugin-ui documents — byte-in-place, version
    strings only. The planted ledger carries no inventories, which is the
    arithmetic-honest shape for the scaffold's descriptor (every declared
    action served; no custom, no composed)."""
    project = tmp_path / "classref"
    package = _coherent_stale(project)
    family = active_version("plugin-ui-class-reference")
    previous = "0.3.0"
    assert _tuple(previous) < _tuple(family), "the fixture needs a real prior row"
    (package / "ui/class-reference.json").write_bytes(
        (
            json.dumps(
                {
                    "contract_version": previous,
                    "reference_version": previous,
                    "reference_id": "synthetic",
                },
                indent=2,
            )
            + "\n"
        ).encode()
    )
    before = (package / "ui/class-reference.json").read_bytes()
    capsys.readouterr()
    assert migrate(monkeypatch, package) == 0
    # Whitespace-normalized: the CLI wraps long lines, and the stamps-naming
    # line (N4) is longer than the wrap width — the assertion reads the
    # line's content, not its terminal wrapping.
    rendered = " ".join(capsys.readouterr().out.split())
    assert (
        f"migrated ui/class-reference.json: plugin-ui-class-reference "
        f"contract_version {previous} -> {family}, reference_version "
        f"{previous} -> {family}" in rendered
    )
    after = json.loads((package / "ui/class-reference.json").read_bytes())
    assert after["contract_version"] == family
    assert after["reference_version"] == family
    assert after["reference_id"] == "synthetic"
    del before  # the parsed comparison above is the discipline assertion

    # The negative arm: a current ledger adds no ledger line.
    current = tmp_path / "classref-current"
    package = _coherent_stale(current)
    (package / "ui/class-reference.json").write_bytes(
        (
            json.dumps(
                {"contract_version": family, "reference_version": family,
                 "reference_id": "synthetic"},
                indent=2,
            )
            + "\n"
        ).encode()
    )
    capsys.readouterr()
    assert migrate(monkeypatch, package) == 0
    assert "ui/class-reference.json" not in capsys.readouterr().out


def test_classref_ledger_without_stamps_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ledger that cannot be re-stamped in place (a family stamp absent)
    refuses with the sibling documents' malformed-input code — never a
    silent skip, never a write."""
    project = tmp_path / "classref-absent"
    package = _coherent_stale(project)
    (package / "ui/class-reference.json").write_bytes(
        (json.dumps({"contract_version": "0.1.0", "reference_id": "synthetic"}) + "\n").encode()
    )
    before = _tree(project)
    capsys.readouterr()
    assert migrate(monkeypatch, package) == 1
    assert "migrate_ui_version_absent:" in capsys.readouterr().err
    assert _tree(project) == before
