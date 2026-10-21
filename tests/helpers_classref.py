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
    destination: Path,
    descriptor_fixture: str = "descriptor-f1.json",
    *,
    profile_id: str = "otdp.logic_analyser/1.0.0",
) -> tuple[Path, Any]:
    """Scaffold a synthetic plugin, swap in the class descriptor and the
    derived documents, return (project, derived).

    The per-class arms pass the class fixture pair: ``descriptor-<slug>``
    names the OTDP example shape under invented identity, and a descriptor
    that declares read-only parameters (the readings classes) additionally
    installs the readings adapter module and its own vectors script so the
    connected render reads every declared parameter. The founding pair
    stays the default so the existing arms' behaviour is byte-identical."""
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
    descriptor = json.loads(descriptor_raw)
    slug = descriptor_fixture.removeprefix("descriptor-").removesuffix(".json")
    if any(
        row.get("access") in ("ro", "rw")
        for row in descriptor.get("parameters", [])
    ):
        # The readings classes: the connected render reads every declared
        # parameter, so the project carries the readings adapter and its
        # own scripted vectors (identify + one exchange per parameter, in
        # binding order). Every other fixture keeps the scaffold's own
        # vectors.json untouched.
        class_vectors = fixture_dir / f"vectors-{slug}.json"
        if not class_vectors.is_file():
            raise AssertionError(f"no vectors fixture for readings class {slug}")
        (package / "vectors.json").write_bytes(class_vectors.read_bytes())
        (package / "readings_adapter.py").write_bytes(
            (fixture_dir / "readings_adapter.py").read_bytes()
        )
    reference = find_reference(profile_id)
    if reference is None:
        raise AssertionError(f"no vendored reference for {profile_id}")
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
