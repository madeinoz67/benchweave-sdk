"""Shared classref gate-test construction: a real scaffolded project with
the derived F1 documents swapped in (the synthetic plugin body is the
scaffold's own; the class documents ride on top)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchweave_sdk.classref import declaration_scaffold, derive_ui, find_reference
from benchweave_sdk.scaffold import create_project


def build_classref_project(
    destination: Path, descriptor_fixture: str = "descriptor-f1.json"
) -> tuple[Path, Any]:
    """Scaffold a synthetic plugin, swap in the class descriptor and the
    derived documents, return (project, derived)."""
    create_project(destination, "veridian_classref_plugin", with_ui=False)
    package = destination / "src" / "veridian_classref_plugin"
    fixture_dir = Path(__file__).parent / "fixtures" / "classref"
    descriptor_raw = (fixture_dir / descriptor_fixture).read_bytes()
    (package / "descriptor.json").write_bytes(descriptor_raw)
    for pinned in (
        "vendor-catalog.json",
        "vendor-catalog-trio.json",
        "vendor-catalog-pair.json",
        "decoder-uart.json",
        "vectors-f1.json",
    ):
        source = fixture_dir / pinned
        if source.is_file():
            (package / pinned).write_bytes(source.read_bytes())
    reference = find_reference("otdp.logic_analyser/1.0.0")
    derived = derive_ui(
        descriptor_raw, reference, descriptor_path=fixture_dir / descriptor_fixture
    )
    ui = package / "ui"
    ui.mkdir(exist_ok=True)
    (ui / "manifest.json").write_bytes(raw(derived.manifest))
    (package / "presentation.json").write_bytes(raw(derived.envelope))
    (package / "binding-catalogue.json").write_bytes(raw(derived.catalogue))
    settings = ui / "settings"
    settings.mkdir(exist_ok=True)
    (settings / "configure.schema.json").write_bytes(raw(derived.settings_schema))
    presets = ui / "presets"
    presets.mkdir(exist_ok=True)
    for slug, scaffold in derived.preset_scaffolds.items():
        (presets / f"{slug}.json").write_bytes(raw(scaffold))
    declaration = declaration_scaffold(derived)
    (ui / "class-reference.json").write_bytes(raw(declaration))
    return destination, derived


def raw(document: dict[str, Any]) -> bytes:
    indent = 2
    return (json.dumps(document, indent=indent) + "\n").encode()
