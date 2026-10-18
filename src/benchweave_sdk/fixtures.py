"""Validated author fixtures and mandatory deterministic preview scenarios.

The example-fixture lane (issue #463 row 8) refuses with these
``snake_case:`` prefixes (STD-4): ``regen_fixtures_no_catalogue:`` (the
project's binding catalogue is absent), ``regen_fixtures_no_observation_target:``
(the catalogue declares no observation target, so no example can be
composed), ``regen_fixtures_author_content:`` (an example filename already
carries a non-example scenario id — author content; nothing is written,
all-or-nothing), ``regen_fixtures_unreadable_example:`` (an example
filename exists but cannot be OPENED — distinct from author content: the
file was never judged), ``regen_fixtures_id_collision:`` (another fixture
file already carries an example id, so writing the example at its own
name would mint a duplicate the loader refuses; nothing is written),
``regen_fixtures_invalid_generated:`` (a generated document fails the same
validation ``load_author_fixtures`` applies — the generator/loader-drift
guard; nothing is written) and ``regen_fixtures_write_failed:`` (staging
or replacing the generated documents failed — the staged-tempfile write
path). The CLI adds ``regen_fixtures_no_package:`` for a project without
a package under ``src/``.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
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
from .served import active_version

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


def _fixture_schema() -> Any:
    """The ACTIVE plugin-ui-preview fixture schema, digest-verified at load.

    Late Forge fold 1 (#215): this load used to read the vendored tree
    directly, outside the digest gate — a parse-valid tamper of the schema
    byte loaded clean while every schema the validation lane served was
    digest-checked. It now rides the one verified loader
    (``validation.contract_documents``, whose enumeration covers every
    carried standard, this one included), so tampered bytes refuse
    ``vendored_digest_mismatch:`` before any author fixture is judged
    against them. The fallback trust posture (the gateway checkout only)
    is the loader's own, pinned by its tests.
    """
    from .validation import contract_documents

    key = f"plugin-ui-preview/{active_version('plugin-ui-preview')}/fixture.schema.json"
    document = contract_documents().get(key)
    if document is None:
        raise RuntimeError(
            "SDK preview fixture schema missing; run sync-standards or reinstall the SDK"
        )
    return document


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


def _validated_scenario(
    document: Mapping[str, Any],
    path: Path,
    validator: Draft202012Validator,
    targets: Mapping[str, Mapping[str, Any]],
    seen: set[str],
) -> PreviewScenario:
    """One document through the per-file checks ``load_author_fixtures``
    applies: the digest-verified ACTIVE schema, the duplicate-id census and
    the catalogue cross-check — the ONE validation mechanism, shared with
    ``regenerate_example_fixtures`` so a generated document is judged by
    exactly the loader that will read it back (issue #463 row 8). The check
    order is the loader's own, unchanged by the extraction."""
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        location = "/".join(map(str, errors[0].path)) or "/"
        raise ValueError(f"preview_invalid_fixture: {path}: {location}: {errors[0].message}")
    if document["id"] in seen:
        raise ValueError(f"preview_duplicate_scenario: {path}: {document['id']}")
    seen.add(document["id"])
    return _scenario(document, path, targets)


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
    schema = _fixture_schema()
    validator = Draft202012Validator(schema)
    targets = _target_index(catalogue)
    scenarios = []
    seen: set[str] = set()
    total = 0
    for path in paths:
        raw = read_file(path)
        total += len(raw)
        if total > 8 * 1024 * 1024:
            raise ValueError("preview_fixture_bytes_exceeded: maximum is 8 MiB")
        document = _parse(raw)
        scenarios.append(_validated_scenario(document, path, validator, targets, seen))
    return tuple(scenarios)


def _preview_fixture(target: dict[str, Any], *, suffix: str, severity: str) -> dict[str, Any]:
    # The value variable carries the reading; a receipt-time axis variable may
    # sit beside it (the plot example adds one) but never the fixture value.
    variable = next(row for row in target["variables"] if row.get("axis_role") != "receipt_time")
    values: dict[str, Any] = {"number": 1.0, "integer": 1, "boolean": True, "string": "simulated"}
    return {
        # The lock's active plugin-ui-preview version (issue #221, gateway
        # #221 slice 7): derived, never stated — one lock bump moves the
        # fixture with the corpus it must validate against.
        "contract_version": active_version("plugin-ui-preview"),
        "id": f"example-{suffix}",
        "title": f"Example {suffix}",
        "description": f"Synthetic {suffix} state generated by benchweave-sdk",
        "timestamp_strategy": "fixed",
        "bindings": [
            {
                "id": target["id"],
                "value": values[variable["type"]],
                "unit": variable.get("unit"),
                "quality": "simulated",
                "freshness_ms": 0,
                "provenance": "Generated SDK fixture; not a hardware observation",
            }
        ],
        "permissions": ["observer"],
        "lease_state": "none",
        "approval_state": "not_required",
        "unavailable_panels": [],
        "expected_severity": severity,
        "request_outcomes": [],
    }


@dataclass(frozen=True, slots=True)
class RegenOutcome:
    """What one ``regenerate_example_fixtures`` run did, as report lines for
    the CLI to render (the ``MigrationOutcome`` shape).

    ``written`` names the example files whose bytes changed (``normal.json``
    / ``warning.json``); ``noop`` marks the nothing-changed case (safe in
    scripts and CI); ``notes`` carries the mint-case disclosures.
    """

    written: tuple[str, ...] = ()
    noop: bool = False
    notes: tuple[str, ...] = ()


def regenerate_example_fixtures(catalogue_path: Path, fixtures_dir: Path) -> RegenOutcome:
    """Regenerate the two scaffolded example fixtures from the catalogue.

    One generator, two callers: this is the scaffold's own
    ``_preview_fixture`` (moved here so a command can reach it, issue #463
    row 8), composed over the FIRST ``kind == "observation"`` target in
    catalogue order whose shape ``_observation_value_variable`` admits (a
    malformed first target refuses through the loader's own
    ``preview_unsupported_shape:``). Both documents are validated in memory
    through the same per-document checks ``load_author_fixtures`` applies
    BEFORE any write; a document that would not load refuses with nothing
    written. An example filename whose parsed ``id`` is not the matching
    example id is author content — the named refusal, nothing written,
    all-or-nothing; an example filename that cannot be opened refuses as
    unreadable instead (F5). Another fixture file already carrying an
    example id refuses as an id collision — writing the example at its own
    name would mint a duplicate the loader refuses (F2). Writes go through
    staged tempfiles replaced onto their targets, so a read-only example
    FILE still regenerates (rename needs the directory's permission, not
    the file's) and every deterministic write failure refuses with nothing
    written (F1). Every other ``*.json`` in the directory is untouched.
    Unchanged bytes are not rewritten, so the run is idempotent; an absent
    directory is minted.

    Parameters
    ----------
    catalogue_path
        The project's ``binding-catalogue.json``.
    fixtures_dir
        The ``ui/fixtures`` directory (may not exist yet — minted).

    Returns
    -------
    RegenOutcome
        ``noop`` when both files already carry the generated bytes;
        otherwise one written name per changed file, plus notes on mint.

    Raises
    ------
    ValueError
        ``regen_fixtures_no_catalogue:``, ``regen_fixtures_no_observation_target:``,
        ``preview_unsupported_shape:`` (a malformed target, the loader's own
        path), ``regen_fixtures_author_content:``,
        ``regen_fixtures_unreadable_example:``, ``regen_fixtures_id_collision:``,
        ``regen_fixtures_invalid_generated:`` (each before any byte is
        written) or ``regen_fixtures_write_failed:``.
    """
    if not catalogue_path.is_file():
        raise ValueError(f"regen_fixtures_no_catalogue: {catalogue_path}")
    catalogue = json.loads(read_file(catalogue_path))
    if not isinstance(catalogue, Mapping):
        raise ValueError("preview_invalid_catalogue: catalogue must be an object")
    target = next(
        (
            row
            for row in _target_index(catalogue).values()
            if row.get("kind") == "observation"
        ),
        None,
    )
    if target is None:
        raise ValueError(
            f"regen_fixtures_no_observation_target: {catalogue_path}"
        )
    # F3: the selection admits only shapes the loader itself admits, so a
    # malformed first observation target refuses through the loader's named
    # path — never a KeyError/StopIteration from the generator's internals.
    _observation_value_variable(target)
    documents = {
        filename: _preview_fixture(
            dict(target), suffix=filename, severity=severity
        )
        for filename, severity in (("normal", "neutral"), ("warning", "warning"))
    }
    # The ownership guard runs before any write for BOTH files — a refusal
    # on one leaves the other untouched too (the migrate-ui validate-before-
    # write posture). F5: a file that cannot be OPENED was never judged —
    # that is an unreadable example, not author content; a file that does
    # not PARSE is content the generator never wrote — author content,
    # never overwritten. (read_file's own ValueError refusals, e.g.
    # symlinked components, propagate under their own names.)
    for filename, document in documents.items():
        path = fixtures_dir / f"{filename}.json"
        if not path.exists():
            continue
        try:
            raw_existing = read_file(path)
        except OSError as exc:
            raise ValueError(f"regen_fixtures_unreadable_example: {path}") from exc
        try:
            existing = json.loads(raw_existing)
        except ValueError:
            raise ValueError(f"regen_fixtures_author_content: {path}") from None
        if not isinstance(existing, Mapping) or existing.get("id") != document["id"]:
            raise ValueError(f"regen_fixtures_author_content: {path}")
    # F2: census the MERGED directory before writing. The guide calls the
    # examples "a valid, copyable format model", so an author copy at its
    # own filename carrying an example id is an invited state — and
    # writing the example at its canonical name beside that copy would
    # mint a duplicate the loader refuses, reddening the project test
    # AFTER a successful regen. Refuse, naming the colliding author file.
    # (Files that do not parse are the loader's jurisdiction, not regen's;
    # the census skips them.)
    example_ids = {document["id"] for document in documents.values()}
    for path in sorted(fixtures_dir.glob("*.json")):
        if path.name in {f"{filename}.json" for filename in documents}:
            continue
        try:
            other = json.loads(read_file(path))
        except (ValueError, OSError):
            continue
        if isinstance(other, Mapping) and other.get("id") in example_ids:
            raise ValueError(
                f"regen_fixtures_id_collision: {path}: {other['id']} — the id "
                "belongs to a generated example; delete or re-id this copy"
            )
    # In-memory validation through the ONE loader mechanism, before any
    # write: a generated document the loader would refuse is a
    # generator/loader drift, not an author error.
    validator = Draft202012Validator(_fixture_schema())
    index = _target_index(catalogue)
    seen: set[str] = set()
    try:
        for filename, document in documents.items():
            _validated_scenario(
                document, fixtures_dir / f"{filename}.json", validator, index, seen
            )
    except ValueError as exc:
        raise ValueError(f"regen_fixtures_invalid_generated: {exc}") from exc
    pending: dict[str, bytes] = {}
    for filename, document in documents.items():
        path = fixtures_dir / f"{filename}.json"
        raw = (json.dumps(document, indent=2) + "\n").encode("utf-8")
        if path.is_file() and path.read_bytes() == raw:
            continue
        pending[f"{filename}.json"] = raw
    if not pending:
        return RegenOutcome(noop=True)
    notes: tuple[str, ...] = ()
    if not fixtures_dir.exists():
        notes = (
            "the scaffold's class-reference path writes no example fixtures; "
            "this command is the author-side way to get them",
            "wiring the examples into project tests is the author's choice",
        )
        fixtures_dir.mkdir(parents=True)
    # F1: stage BOTH documents as tempfiles inside the target directory,
    # then rename each onto its target. Staging is the write — if it fails
    # (an unwritable directory), NO target has been touched. Rename needs
    # the DIRECTORY's write permission, not the target file's, so the
    # refute's read-only-example repro regenerates cleanly instead of
    # tearing the pair. A failure between the two renames is the residual
    # torn window (directory revocation mid-pair); the staged tempfile is
    # cleaned up and the refusal names the file — the author's VCS is the
    # recovery, the same disclosed posture as migrate-ui's sequential
    # writes.
    staged: dict[str, Path] = {}
    try:
        for name, raw in pending.items():
            descriptor, temporary_name = tempfile.mkstemp(
                dir=fixtures_dir, prefix=".regen-", suffix=".tmp"
            )
            staged[name] = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
    except OSError as exc:
        for leftover in staged.values():
            leftover.unlink(missing_ok=True)
        raise ValueError(f"regen_fixtures_write_failed: {fixtures_dir}") from exc
    written: list[str] = []
    try:
        for name, staged_path in staged.items():
            os.replace(staged_path, fixtures_dir / name)
            written.append(name)
    except OSError as exc:
        for leftover in staged.values():
            leftover.unlink(missing_ok=True)
        failed = fixtures_dir / next(name for name in staged if name not in written)
        raise ValueError(f"regen_fixtures_write_failed: {failed}") from exc
    return RegenOutcome(written=tuple(written), notes=notes)


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
    """The document emitter's version: the SDK's own ``__version__``.

    Since 0.7.0 (#308) the served document's ``renderer_version`` reports
    the emitter — the same ``importlib.metadata`` derivation
    ``benchweave_sdk.__init__`` uses for ``__version__`` (derived, never a
    literal; the zero-literal gate's register discipline). The React
    renderer's frozen build version, once read from the deleted renderer
    bundle's inventory, died with the bundle; the wire schema keeps
    requiring a string.
    """
    from . import __version__

    return __version__


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
                    lane_groups=tuple(plot.get("lane_groups", ())),
                    decoder_lanes=tuple(plot.get("decoder_lanes", ())),
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
