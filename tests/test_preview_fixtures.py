"""Deterministic SDK preview fixtures are closed, finite and serialisable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from benchweave_sdk import fixtures, presentation, preview_models, scaffold

REPO = Path(__file__).resolve().parents[1]
FIXTURE_SCHEMA = REPO / "src/benchweave_sdk/standards/plugin-ui-preview/0.1.0/fixture.schema.json"
DOCUMENT_SCHEMA = (
    REPO / "src/benchweave_sdk/standards/plugin-ui-preview/0.1.0/preview-document.schema.json"
)


def catalogue() -> dict[str, object]:
    return {
        "contract_version": "0.1.0",
        "targets": [
            {
                "id": "voltage",
                "kind": "observation",
                "parameter_id": "voltage",
                "variables": [
                    {
                        "id": "value",
                        "type": "number",
                        "unit": "V",
                        "shape": "scalar",
                        "axis_role": "value",
                    }
                ],
            }
        ],
    }


def author_fixture(binding_id: str = "voltage", unit: str | None = "V") -> dict[str, object]:
    return {
        "contract_version": "0.1.0",
        "id": "high-load",
        "title": "High load",
        "description": "Synthetic high-load state",
        "timestamp_strategy": "fixed",
        "bindings": [
            {
                "id": binding_id,
                "value": 12.0,
                "unit": unit,
                "quality": "simulated",
                "freshness_ms": 0,
                "provenance": "Author fixture",
            }
        ],
        "permissions": ["observer"],
        "lease_state": "none",
        "approval_state": "not_required",
        "unavailable_panels": [],
        "expected_severity": "warning",
        "request_outcomes": [],
    }


def test_fixture_schema_is_closed_and_versioned() -> None:
    schema = json.loads(FIXTURE_SCHEMA.read_bytes())

    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == (
        "https://benchweave.dev/contracts/plugin-ui-preview/0.1.0/fixture.schema.json"
    )
    assert schema["additionalProperties"] is False


def test_preview_scenario_serialises_as_an_immutable_document() -> None:
    models = preview_models
    scenario = models.PreviewScenario(
        id="normal",
        title="Normal",
        description="Nominal simulated state",
        timestamp_strategy="fixed",
        observations=(),
        permissions=frozenset({"observer"}),
        lease_state="none",
        approval_state="not_required",
        unavailable_panels=(),
        expected_severity="neutral",
        request_outcomes=(),
        baseline=True,
    )

    assert scenario.to_document() == {
        "id": "normal",
        "title": "Normal",
        "description": "Nominal simulated state",
        "timestamp_strategy": "fixed",
        "observations": [],
        "permissions": ["observer"],
        "lease_state": "none",
        "approval_state": "not_required",
        "unavailable_panels": [],
        "expected_severity": "neutral",
        "request_outcomes": [],
        "baseline": True,
    }
    with pytest.raises(AttributeError):
        scenario.title = "Changed"


def test_preview_observation_rejects_non_finite_values() -> None:
    models = preview_models
    observation = models.PreviewObservation(
        binding_id="voltage",
        value=float("nan"),
        unit="V",
        quality="simulated",
        freshness_ms=0,
        provenance="SDK baseline",
    )

    with pytest.raises(ValueError, match="finite"):
        observation.to_document()


@pytest.mark.parametrize("scenario_id", sorted(fixtures.BASELINE_IDS))
def test_baseline_scenarios_are_always_generated(scenario_id: str) -> None:
    scenarios = fixtures.generate_baselines(catalogue(), {"pages": [], "plugin_id": "test.plugin"})

    assert scenario_id in {row.id for row in scenarios}


def test_author_fixture_rejects_unknown_binding(tmp_path: Path) -> None:
    (tmp_path / "high-load.json").write_text(
        json.dumps(author_fixture(binding_id="not-declared")), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="preview_unknown_binding"):
        fixtures.load_author_fixtures(tmp_path, catalogue())


def test_author_fixture_rejects_wrong_unit(tmp_path: Path) -> None:
    (tmp_path / "high-load.json").write_text(json.dumps(author_fixture(unit="A")), encoding="utf-8")

    with pytest.raises(ValueError, match="preview_unit_mismatch"):
        fixtures.load_author_fixtures(tmp_path, catalogue())


def test_preview_model_is_built_from_the_validated_candidate(tmp_path: Path) -> None:
    project = tmp_path / "plugin"
    scaffold.create_project(project, "example_plugin")
    presentation.create_ui_resources(project, "example_plugin")
    package = project / "src/example_plugin"

    candidate = presentation.load_validated_preview_inputs(
        package / "presentation.json",
        package / "descriptor.json",
        package,
        package / "binding-catalogue.json",
        firmware="1.0.0",
        features=frozenset(),
        panels=frozenset(),
    )
    model = fixtures.build_preview_model(candidate)

    assert model.plugin_id == "dev.example.example-plugin"
    assert model.simulation is True
    assert len(model.scenarios) == 11
    author_ids = {scenario.id for scenario in model.scenarios if not scenario.baseline}
    assert author_ids == {"example-normal", "example-warning"}

    assert fixtures.__file__ is not None
    inventory = json.loads(
        (Path(fixtures.__file__).with_name("preview_assets") / "inventory.json").read_bytes()
    )
    assert model.renderer_version == inventory["renderer_version"]


def test_served_preview_document_conforms_to_wire_schema(tmp_path: Path) -> None:
    project = tmp_path / "plugin"
    scaffold.create_project(project, "example_plugin")
    presentation.create_ui_resources(project, "example_plugin")
    package = project / "src/example_plugin"
    candidate = presentation.load_validated_preview_inputs(
        package / "presentation.json",
        package / "descriptor.json",
        package,
        package / "binding-catalogue.json",
        firmware="1.0.0",
        features=frozenset(),
        panels=frozenset(),
    )
    document = fixtures.build_preview_model(candidate).to_document()

    schema = json.loads(DOCUMENT_SCHEMA.read_bytes())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    assert not list(validator.iter_errors(document))

    poisoned = json.loads(json.dumps(document))
    poisoned["scenarios"][0]["expected_severity"] = "catastrophic"
    assert list(validator.iter_errors(poisoned))
