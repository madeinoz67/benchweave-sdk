"""Generated offline presentation-preview conformance smoke test."""

from importlib.resources import files
from pathlib import Path

from benchweave_sdk.fixtures import BASELINE_IDS, build_preview_model
from benchweave_sdk.presentation import load_validated_preview_inputs


def _materialise(source, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        if entry.is_dir():
            _materialise(entry, destination / entry.name)
        else:
            (destination / entry.name).write_bytes(entry.read_bytes())

def test_presentation_preview_contract(tmp_path: Path) -> None:
    package = tmp_path / "example_plugin"
    _materialise(files("example_plugin"), package)
    candidate = load_validated_preview_inputs(
        package / "presentation.json",
        package / "descriptor.json",
        package,
        package / "binding-catalogue.json",
        firmware=None,
        features=frozenset(),
        panels=frozenset(),
    )
    model = build_preview_model(candidate)
    scenarios = model.scenarios
    assert BASELINE_IDS <= {row.id for row in scenarios}
    assert model.plot_views, "the scaffold plot must project"
