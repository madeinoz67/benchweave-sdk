"""D12b overlay composition tests (A5/A6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchweave_sdk.classref import (
    compose_manifest,
    declaration_scaffold,
    derive_ui,
    find_reference,
    validate_declaration,
)

FIXTURES = Path(__file__).parent / "fixtures" / "classref"
REFERENCE = find_reference("otdp.logic_analyser/1.0.0")


def _derive():
    return derive_ui(
        (FIXTURES / "descriptor-f1.json").read_bytes(), REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f1.json",
    )


def test_overlay_effects_survive_rederive_a5() -> None:
    derived = _derive()
    overrides = {
        "pages": [
            {"id": "capture", "title": "Acquire"},
            {"id": "brand-new", "title": "Author page", "kind": "readings",
             "bindings": []},
        ]
    }
    composed = compose_manifest(derived.manifest, overrides)
    pages = {page["id"]: page for page in composed["pages"]}
    assert pages["capture"]["title"] == "Acquire"  # overlay rename survived
    assert "brand-new" in pages  # overlay-only page appended
    # derived rows untouched elsewhere
    assert pages["capture"]["kind"] == "dataset"
    assert composed["plugin_id"] == derived.manifest["plugin_id"]


def test_overlay_cannot_delete_or_touch_immutable_fields() -> None:
    derived = _derive()
    with pytest.raises(ValueError, match="^overlay_immutable_field:"):
        compose_manifest(derived.manifest, {"plugin_id": "evil.plugin"})
    with pytest.raises(ValueError, match="^overlay_delete_refused:"):
        compose_manifest(derived.manifest, {"pages": []})
    with pytest.raises(ValueError, match="^overlay_delete_refused:"):
        compose_manifest(
            derived.manifest,
            {"bindings": [{"id": "not-a-derived-binding", "kind": "dataset",
                           "target_id": "x"}]},
        )


def test_deviation_ledger_shape_a6() -> None:
    derived = _derive()
    declaration = declaration_scaffold(derived)
    assert declaration["profile_ids"] == ["otdp.logic_analyser/1.0.0"]
    ids = {row["expectation_id"] for row in declaration["deviations"]}
    assert "otdp.logic_analyser.configure/1.0.0" in ids
    assert "otdp.logic_analyser.decode/1.0.0" in ids
    with pytest.raises(ValueError, match="^classref_unknown_expectation:"):
        validate_declaration(
            derived, {**declaration, "deviations": [
                {**row, "expectation_id": "no-such-expectation"}
                for row in declaration["deviations"]
            ]}
        )
