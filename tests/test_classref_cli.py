"""The derive-ui / verify-ui CLI commands."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner
from helpers_classref import build_classref_project

from benchweave_sdk.cli import cli


def test_derive_then_verify_clean_roundtrip(tmp_path: Path) -> None:
    project, _derived = build_classref_project(tmp_path / "proj")
    # verify-ui first: the helper already wrote the derived set.
    runner = CliRunner()
    result = runner.invoke(cli, ["verify-ui", str(project)])
    assert result.exit_code == 0, result.output
    # A dirty manifest refuses without --force.
    manifest = next((project / "src").iterdir()) / "ui" / "manifest.json"
    manifest.write_bytes(manifest.read_bytes().replace(b"capture", b"renamed"))
    result = runner.invoke(cli, ["derive-ui", str(project)])
    assert result.exit_code != 0
    assert "derive_ui_dirty_tree" in result.output
    result = runner.invoke(cli, ["derive-ui", str(project), "--force"])
    assert result.exit_code == 0, result.output
    assert "cannot_derive" in result.output


# --- derive-ui's tree guard: stale vs dirty (gateway #541 slice 3, (c)) -----
#
# The discriminator is the descriptor digest the manifest records. A manifest
# generated for a DIFFERENT descriptor is stale and is overwritten; a manifest
# for the SAME descriptor that differs from the derivation is author drift and
# still refuses. `test_derive_then_verify_clean_roundtrip` above is that
# same-descriptor pin and is deliberately untouched.
#
# Arm 1 of the four the fold asks for is the acceptance module's
# `test_a1_the_workflow_runs_clean` (the `new --with-ui` path, which must flip
# green); arm 2 is the pin above. These three carry the rest.


def _descriptor_path(project: Path) -> Path:
    return next((project / "src").iterdir()) / "descriptor.json"


def _manifest_path(project: Path) -> Path:
    return next((project / "src").iterdir()) / "ui" / "manifest.json"


def _mutate_descriptor(project: Path) -> None:
    """A descriptor edit that changes the derivation — so the on-disk manifest
    is no longer the current descriptor's output."""
    import json

    descriptor_path = _descriptor_path(project)
    descriptor = json.loads(descriptor_path.read_bytes())
    descriptor["actions"]["com.veridian-labs.drift_probe/1.0.0"] = {
        "binding": {"kind": "adapter", "key": "drift_probe"},
        "input_constraints": {"properties": {}},
        "timeout_ms": 1000,
        "side_effect": "none",
        "cancellable": True,
        "retry": "never",
    }
    descriptor_path.write_bytes((json.dumps(descriptor, indent=2) + "\n").encode())


def test_derive_ui_stale_manifest_from_another_descriptor_is_overwritten(
    tmp_path: Path,
) -> None:
    """(c) arm 3. The on-disk manifest recorded a DIFFERENT descriptor's
    digest, so it is stale — not author drift — and `derive-ui` overwrites it
    with no `--force` and no refusal. The result is the new derivation's own
    output (nothing of the old manifest survives)."""
    import hashlib
    import json

    from benchweave_sdk.classref import derive_ui, find_reference

    project, _derived = build_classref_project(tmp_path / "proj")
    old_manifest = _manifest_path(project).read_bytes()
    _mutate_descriptor(project)
    runner = CliRunner()
    result = runner.invoke(cli, ["derive-ui", str(project)])
    assert result.exit_code == 0, result.output
    assert "derive_ui_dirty_tree" not in result.output, result.output

    descriptor_path = _descriptor_path(project)
    reference = find_reference("otdp.logic_analyser/1.0.0")
    assert reference is not None
    derived = derive_ui(
        descriptor_path.read_bytes(), reference, descriptor_path=descriptor_path
    )
    written = _manifest_path(project).read_bytes()
    assert written == (json.dumps(derived.manifest, indent=2) + "\n").encode()
    assert written != old_manifest, "the stale manifest was not replaced"
    assert json.loads(written)["descriptor_sha256"] == hashlib.sha256(
        descriptor_path.read_bytes()
    ).hexdigest()


def test_derive_ui_author_manifest_overrides_are_untouched(
    tmp_path: Path,
) -> None:
    """(c) arm 4. Author edits live in `ui/manifest.overrides.json`. The
    overlay file survives a re-derivation byte-for-byte, and a descriptor
    change still re-derives `ui/manifest.json` — the overlay is composed at
    load time, never written into the derived manifest."""
    import json

    project, _derived = build_classref_project(tmp_path / "proj")
    package = next((project / "src").iterdir())
    overrides = package / "ui" / "manifest.overrides.json"
    overrides.write_bytes(
        b'{\n  "pages": [\n    {\n      "id": "capture",\n'
        b'      "title": "My capture"\n    }\n  ]\n}\n'
    )
    before = overrides.read_bytes()
    _mutate_descriptor(project)
    runner = CliRunner()
    result = runner.invoke(cli, ["derive-ui", str(project)])
    assert result.exit_code == 0, result.output
    assert "derive_ui_dirty_tree" not in result.output, result.output
    assert overrides.read_bytes() == before, "the author's overlay was touched"
    manifest = json.loads(_manifest_path(project).read_bytes())
    capture = next(page for page in manifest["pages"] if page["id"] == "capture")
    assert capture["title"] == "Capture", "the overlay leaked into the manifest"


def test_derive_ui_dirty_tree_message_names_author_drift(tmp_path: Path) -> None:
    """The message names its actual cause. The stale face ("the manifest is
    from another descriptor") no longer refuses at all, so a refusal can only
    mean the manifest was derived from THIS descriptor and edited since —
    and the message says that instead of blaming a difference from "the
    expander's own output", which was true of the stale face too and taught
    the wrong remedy."""
    project, _derived = build_classref_project(tmp_path / "proj")
    manifest = _manifest_path(project)
    manifest.write_bytes(manifest.read_bytes().replace(b"capture", b"renamed"))
    runner = CliRunner()
    result = runner.invoke(cli, ["derive-ui", str(project)])
    assert result.exit_code != 0
    assert "derive_ui_dirty_tree" in result.output
    assert "author drift" in result.output, result.output
    assert "differs from the expander" not in result.output, result.output


def test_derive_ui_refuses_a_manifest_that_records_no_descriptor_digest(
    tmp_path: Path,
) -> None:
    """The indeterminate face. A `ui/manifest.json` that records no descriptor
    digest is not expander output, so a descriptor change cannot be told from
    author edits; the refusal says exactly that rather than guessing, and the
    remedy stays the author's own overlay file (or `--force`)."""
    project, _derived = build_classref_project(tmp_path / "proj")
    _manifest_path(project).write_bytes(b"{\n  \"pages\": []\n}\n")
    runner = CliRunner()
    result = runner.invoke(cli, ["derive-ui", str(project)])
    assert result.exit_code != 0
    assert "derive_ui_dirty_tree" in result.output
    assert "cannot be told from author edits" in result.output, result.output
