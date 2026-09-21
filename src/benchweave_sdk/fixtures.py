"""Validated author fixtures and mandatory deterministic preview scenarios."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .presentation import ValidatedPreviewInputs, read_file
from .preview_models import (
    PlotAxis,
    PlotChannel,
    PlotView,
    PreviewModel,
    PreviewObservation,
    PreviewScenario,
    Severity,
    SimulatedReceipt,
)

BASELINE_IDS = frozenset(
    {
        "normal",
        "loading",
        "stale",
        "disconnected",
        "warning",
        "critical",
        "trip",
        "recovery",
        "request-rejected",
    }
)


def _schema_path() -> Path:
    packaged = (
        Path(__file__).with_name("standards")
        / "plugin-ui-preview"
        / "0.1.1"
        / "fixture.schema.json"
    )
    if packaged.is_file():
        return packaged
    checkout = (
        Path(__file__).resolve().parents[4]
        / "standards/plugin-ui-preview/0.1.1/fixture.schema.json"
    )
    if checkout.is_file():
        return checkout
    raise RuntimeError(
        "SDK preview fixture schema missing; run sync-standards or reinstall the SDK"
    )


def _parse(raw: bytes) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"Preview fixture numbers must be finite: {value}")

    document = json.loads(raw, parse_constant=reject_constant)
    if not isinstance(document, dict):
        raise ValueError("preview_invalid_fixture: fixture must be an object")
    return document


def _target_index(catalogue: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    targets = catalogue.get("targets", [])
    if not isinstance(targets, list):
        raise ValueError("preview_invalid_catalogue: targets must be an array")
    return {
        str(target["id"]): target
        for target in targets
        if isinstance(target, Mapping) and isinstance(target.get("id"), str)
    }


def _observation_value_variable(target: Mapping[str, Any]) -> Mapping[str, Any]:
    """The value variable of an observation target: the single non-receipt-time
    scalar, with at most one receipt-time scalar beside it — exactly the shape
    ``_target_findings`` admits, so the preview is never stricter than the
    presentation contract whose canonical time-series plot needs both."""
    variables = target.get("variables", [])
    if not isinstance(variables, list) or any(
        not isinstance(row, Mapping) for row in variables
    ):
        raise ValueError(f"preview_unsupported_shape: {target.get('id', '<unknown>')}")
    rows: list[Mapping[str, Any]] = list(variables)
    values = [row for row in rows if row.get("axis_role") != "receipt_time"]
    times = [row for row in rows if row.get("axis_role") == "receipt_time"]
    if (
        len(values) != 1
        or values[0].get("shape") != "scalar"
        or len(times) > 1
        or any(
            row.get("type") != "number" or row.get("unit") != "s" or row.get("shape") != "scalar"
            for row in times
        )
    ):
        raise ValueError(f"preview_unsupported_shape: {target.get('id', '<unknown>')}")
    return values[0]


def _check_value(path: Path, binding_id: str, value: object, expected: object) -> None:
    valid = {
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "string": isinstance(value, str),
    }.get(str(expected), False)
    if value is not None and not valid:
        raise ValueError(f"preview_type_mismatch: {path}: {binding_id}: expected {expected}")


def _scenario(
    document: Mapping[str, Any],
    path: Path,
    targets: Mapping[str, Mapping[str, Any]],
) -> PreviewScenario:
    scenario_id = str(document["id"])
    if scenario_id in BASELINE_IDS:
        raise ValueError(f"preview_reserved_scenario: {path}: {scenario_id}")
    observations = []
    for binding in document["bindings"]:
        binding_id = binding["id"]
        target = targets.get(binding_id)
        if target is None:
            raise ValueError(f"preview_unknown_binding: {path}: {binding_id}")
        if target.get("kind") != "observation":
            # The snapshot data model is one simulated scalar per observation
            # target; dataset/configuration/procedure bindings stay
            # unrepresentable in author fixtures.
            raise ValueError(f"preview_unsupported_shape: {path}: {binding_id}")
        variable = _observation_value_variable(target)
        if binding["unit"] != variable.get("unit"):
            raise ValueError(
                f"preview_unit_mismatch: {path}: {binding_id}: expected {variable.get('unit')!r}"
            )
        _check_value(path, binding_id, binding["value"], variable.get("type"))
        observations.append(
            PreviewObservation(
                binding_id=binding_id,
                value=binding["value"],
                unit=binding["unit"],
                quality=binding["quality"],
                freshness_ms=binding["freshness_ms"],
                provenance=binding["provenance"],
            )
        )
    receipts = tuple(
        SimulatedReceipt(row["binding_id"], row["outcome"], row["message"])
        for row in document["request_outcomes"]
    )
    return PreviewScenario(
        id=scenario_id,
        title=str(document["title"]),
        description=str(document["description"]),
        timestamp_strategy=document["timestamp_strategy"],
        observations=tuple(observations),
        permissions=frozenset(document["permissions"]),
        lease_state=str(document["lease_state"]),
        approval_state=str(document["approval_state"]),
        unavailable_panels=tuple(document["unavailable_panels"]),
        expected_severity=document["expected_severity"],
        request_outcomes=receipts,
        baseline=False,
    )


def load_author_fixtures(
    directory: Path, catalogue: Mapping[str, Any]
) -> tuple[PreviewScenario, ...]:
    """Load author fixtures as validated, deterministic preview scenarios.

    Every ``*.json`` file under ``directory`` is parsed, validated
    against the vendored fixture schema, and cross-checked against the
    binding catalogue: unknown bindings, unit mismatches, type
    mismatches, reserved scenario ids, and duplicate scenario ids are
    rejected. Files are processed in sorted order, so the result is
    deterministic.

    Parameters
    ----------
    directory
        Fixture directory; a directory that does not exist yields no
        scenarios.
    catalogue
        Validated binding catalogue indexable by target id.

    Returns
    -------
    tuple
        One ``PreviewScenario`` per fixture file, in path order.

    Raises
    ------
    ValueError
        If the fixture count exceeds 128, the total size exceeds 8 MiB,
        or any fixture fails schema or catalogue validation.

    Examples
    --------
    >>> from pathlib import Path
    >>> from benchweave_sdk.fixtures import load_author_fixtures
    >>> scenarios = load_author_fixtures(
    ...     Path("src/demo_plugin/fixtures"), catalogue)
    """
    if not directory.exists():
        return ()
    paths = sorted(directory.glob("*.json"))
    if len(paths) > 128:
        raise ValueError("preview_fixture_count_exceeded: maximum is 128")
    schema = _parse(read_file(_schema_path()))
    validator = Draft202012Validator(schema)
    targets = _target_index(catalogue)
    scenarios = []
    seen = set()
    total = 0
    for path in paths:
        raw = read_file(path)
        total += len(raw)
        if total > 8 * 1024 * 1024:
            raise ValueError("preview_fixture_bytes_exceeded: maximum is 8 MiB")
        document = _parse(raw)
        errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
        if errors:
            location = "/".join(map(str, errors[0].path)) or "/"
            raise ValueError(f"preview_invalid_fixture: {path}: {location}: {errors[0].message}")
        if document["id"] in seen:
            raise ValueError(f"preview_duplicate_scenario: {path}: {document['id']}")
        seen.add(document["id"])
        scenarios.append(_scenario(document, path, targets))
    return tuple(scenarios)


def _synthetic_value(variable: Mapping[str, Any]) -> bool | int | float | str:
    values: dict[str, bool | int | float | str] = {
        "boolean": False,
        "integer": 0,
        "number": 0.0,
        "string": "simulated",
    }
    return values[str(variable["type"])]


def generate_baselines(
    catalogue: Mapping[str, Any], manifest: Mapping[str, Any]
) -> tuple[PreviewScenario, ...]:
    """Generate the mandatory scenario set without claiming device evidence.

    Non-observation targets contribute no synthetic observations: dataset,
    configuration and procedure targets are skipped — a disclosed degradation
    (their declared plots still project, with the renderer owing the no-data
    disclosure) where the previous behavior refused the whole preview.
    """
    observations = []
    for binding_id, target in _target_index(catalogue).items():
        if target.get("kind") != "observation":
            continue
        variable = _observation_value_variable(target)
        observations.append(
            PreviewObservation(
                binding_id=binding_id,
                value=_synthetic_value(variable),
                unit=variable.get("unit"),
                quality="simulated",
                freshness_ms=0,
                provenance="SDK generated baseline",
            )
        )
    rows: tuple[tuple[str, str, Severity, str], ...] = (
        ("normal", "Normal", "neutral", "simulated"),
        ("loading", "Loading", "neutral", "loading"),
        ("stale", "Stale", "advisory", "stale"),
        ("disconnected", "Disconnected", "critical", "disconnected"),
        ("warning", "Warning", "warning", "simulated"),
        ("critical", "Critical", "critical", "simulated"),
        ("trip", "Protective trip", "trip", "simulated"),
        ("recovery", "Recovery", "success", "simulated"),
        ("request-rejected", "Request rejected", "warning", "simulated"),
    )
    first_binding = observations[0].binding_id if observations else "request"
    if {row[0] for row in rows} != BASELINE_IDS:
        raise ValueError("preview_baseline_rows_drift")
    scenarios = []
    for scenario_id, title, severity, quality in rows:
        scenario_observations = tuple(
            PreviewObservation(
                binding_id=row.binding_id,
                value=None if quality in {"loading", "disconnected"} else row.value,
                unit=row.unit,
                quality=quality,
                freshness_ms=None if quality == "disconnected" else row.freshness_ms,
                provenance=row.provenance,
            )
            for row in observations
        )
        receipts = (
            (
                SimulatedReceipt(
                    first_binding,
                    "permission_rejected",
                    "Simulated permission rejection",
                ),
            )
            if scenario_id == "request-rejected"
            else ()
        )
        scenarios.append(
            PreviewScenario(
                id=scenario_id,
                title=title,
                description=f"SDK generated {title.lower()} state",
                timestamp_strategy="relative",
                observations=scenario_observations,
                permissions=frozenset({"observer", "controller"}),
                lease_state="held",
                approval_state="not_required",
                unavailable_panels=(),
                expected_severity=severity,
                request_outcomes=receipts,
                baseline=True,
            )
        )
    return tuple(scenarios)


def _renderer_version() -> str:
    """Report the version stamped by the renderer build, not a Python literal."""
    inventory = json.loads(
        (Path(__file__).with_name("preview_assets") / "inventory.json").read_bytes()
    )
    version = inventory.get("renderer_version")
    if not isinstance(version, str) or not version:
        raise ValueError("preview_renderer_inventory_invalid")
    return version


def project_plot_views(candidate: ValidatedPreviewInputs) -> tuple[PlotView, ...]:
    """Project one renderer-ready view per declared manifest plot.

    Reads validated structure only and invents nothing: plot axis membership,
    numeric/shape rules and channel-hint membership were enforced by the
    presentation validator that produced ``candidate``; this function is not a
    second copy of those findings. The input type is the frozen
    ``ValidatedPreviewInputs`` (built only by ``load_validated_preview_inputs``
    after a clean report), so an unvalidated manifest is structurally
    unrepresentable here.

    Deterministic by construction: one view per declared plot in page order
    then plot order; ``title`` is the page's own title for single-plot pages
    and ``"{page title} (i/n)"`` otherwise (manifest plots carry no title);
    labels are variable ids verbatim; units come from the catalogue variables.
    """
    targets = _target_index(candidate.binding_catalogue)
    bindings = {
        str(row["id"]): row
        for row in candidate.manifest.get("bindings", [])
        if isinstance(row, Mapping) and isinstance(row.get("id"), str)
    }
    views: list[PlotView] = []
    for page in candidate.manifest.get("pages", []):
        plots = page.get("plots", [])
        count = len(plots)
        for index, plot in enumerate(plots):
            binding = bindings.get(str(plot["binding_id"]), {})
            # Preview observations speak target ids, so the target id — not
            # the manifest binding's own id — is the renderer's join key.
            target = targets.get(str(binding.get("target_id", "")), {})
            variables = {str(row["id"]): row for row in target.get("variables", [])}
            x_variable = variables.get(str(plot["x"]), {})
            hints = {
                str(hint["variable_id"]): hint for hint in plot.get("channel_hints", [])
            }
            channels = []
            for name in plot["y"]:
                hint = hints.get(str(name))
                channels.append(
                    PlotChannel(
                        variable_id=str(name),
                        label=str(name),
                        unit=variables.get(str(name), {}).get("unit"),
                        color_role=hint.get("color_role") if hint else None,
                        visible=hint.get("visible") if hint else None,
                    )
                )
            title = (
                str(page["title"])
                if count == 1
                else f"{page['title']} ({index + 1}/{count})"
            )
            views.append(
                PlotView(
                    page_id=str(page["id"]),
                    kind=plot["kind"],
                    binding_id=str(binding.get("target_id", "")),
                    title=title,
                    x=PlotAxis(label=str(plot["x"]), unit=x_variable.get("unit")),
                    channels=tuple(channels),
                )
            )
    return tuple(views)


def build_preview_model(candidate: ValidatedPreviewInputs) -> PreviewModel:
    """Build one immutable preview model from the exact validated candidate."""
    baselines = generate_baselines(candidate.binding_catalogue, candidate.manifest)
    authored = load_author_fixtures(
        candidate.resource_root / "fixtures", candidate.binding_catalogue
    )
    return PreviewModel(
        plugin_id=str(candidate.manifest["plugin_id"]),
        renderer_version=_renderer_version(),
        pages=tuple(candidate.manifest.get("pages", [])),
        scenarios=baselines + authored,
        plot_views=project_plot_views(candidate),
    )
