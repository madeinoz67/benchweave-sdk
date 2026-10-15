"""`new --with-ui` on a class-conformant descriptor (gateway #463 row 1).

The issue's headline: one command derives the full presentation from the
descriptor. Today's posture refuses channel/action-shaped descriptors
("UI scaffolding requires at least one readable descriptor parameter") —
the root cause the record §0 establishes. RED-first."""

from __future__ import annotations

import json
from pathlib import Path

from benchweave_sdk.presentation import create_ui_resources
from benchweave_sdk.scaffold import create_project

FIXTURES = Path(__file__).parent / "fixtures" / "classref"


def _project_with_class_descriptor(tmp_path: Path, fixture: str) -> Path:
    destination = tmp_path / "veridian-class"
    create_project(destination, "veridian_class_plugin", with_ui=True)
    package = destination / "src" / "veridian_class_plugin"
    descriptor_raw = (FIXTURES / fixture).read_bytes()
    (package / "descriptor.json").write_bytes(descriptor_raw)
    for pinned in ("vendor-catalog.json", "decoder-uart.json", "vectors-f1.json"):
        source = FIXTURES / pinned
        if source.is_file():
            (package / pinned).write_bytes(source.read_bytes())
    return destination


def test_with_ui_derives_a_class_descriptor(tmp_path: Path) -> None:
    destination = _project_with_class_descriptor(tmp_path, "descriptor-f1.json")
    package = destination / "src" / "veridian_class_plugin"
    # Today: the scalar derivation refuses the class-shaped descriptor.
    create_ui_resources(destination, "veridian_class_plugin")
    manifest = json.loads((package / "ui" / "manifest.json").read_bytes())
    assert manifest["pages"], "the derived manifest carries the reference's pages"
    assert any(page["id"] == "capture" for page in manifest["pages"])
    # The birth declaration and the scaffold preset ship with the set.
    declaration = json.loads((package / "ui" / "class-reference.json").read_bytes())
    assert declaration["profile_ids"] == ["otdp.logic_analyser/1.0.0"]
    assert (package / "ui" / "presets" / "configure.json").is_file()
    # The derived set validates through the canonical validator.
    from benchweave_sdk.presentation import check_ui

    report = check_ui(
        package / "presentation.json",
        package / "descriptor.json",
        package,
        package / "binding-catalogue.json",
        firmware=None,
        features=frozenset(),
        panels=frozenset(),
    )
    assert report.valid, [(f.code, f.path, f.message) for f in report.findings]


def test_with_ui_still_scaffolds_scalar_descriptors(tmp_path: Path) -> None:
    """The legacy parameter-shaped path is unchanged (no regression)."""
    destination = tmp_path / "veridian-scalar"
    create_project(destination, "veridian_scalar_plugin", with_ui=True)
    create_ui_resources(destination, "veridian_scalar_plugin")
    package = destination / "src" / "veridian_scalar_plugin"
    manifest = json.loads((package / "ui" / "manifest.json").read_bytes())
    assert manifest["pages"][0]["kind"] == "readings"
