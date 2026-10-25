"""Gateway #541 slice 3: the Meridian M-400 acceptance fixture (design
record ``.claude/deep-review/2026-10-22-issue541-classref-composition.md``
§5 slice 3, §7 metrics M1–M5).

The issue's acceptance scenario, end to end: a device that is mostly a
DAQ, with vendor features no class serves, gets a complete styled UI with
no upstream request, no manual manifest work, no CSS work and no refusal.
The fixture is invented vocabulary throughout (Meridian Instruments
M-400 — the roster's PSU-01/DAQ-01 shape), per CLAUDE.md §4.

One arm per acceptance outcome:

* A1 — the workflow runs clean (``new --with-ui`` → descriptor filled →
  ``derive-ui`` → ``verify-ui``), and the same pages render on the real
  standalone host with no hand correction.
* A2 — all three resolution layers appear in one device: class surfaces
  from the corpus, the vendor action from the plugin-local composed
  class, the residual member generic but labelled ``custom``.
* A3 — the wheel carries the composed class: packaged, installed into a
  clean environment, and resolved and previewed from the installed tree.
* A4 — no hand work: the authored artefacts are the descriptor, the
  composed declaration and fixtures, and every derived document is
  byte-identical to the derivation's own output.

The scope arms measure the two custom-member shapes the issue names that
this increment does NOT prove (deferral D1: the other six vocabularies).
They pin the measured state so the claim is named in code, never silently
dropped: a computed measurement declares without refusal but derives no
surface, and a custom decoder on a DAQ-class device declares without
refusal but renders no lane. See the report for what that means for the
issue's "a complete styled UI for every feature".
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from benchweave_sdk.classref import ResidualMember, derive_ui, find_reference
from benchweave_sdk.classref_gate import census, verify_ui
from benchweave_sdk.classref_gate_render import render_pages
from benchweave_sdk.cli import cli

FIXTURES = Path(__file__).parent / "fixtures" / "classref"
PACKAGE = "meridian_m400_plugin"
PROFILE = "otdp.daq/1.0.0"
#: The layer-2 class the plugin package ships (the fixture's composed
#: declaration, pinned through ``descriptor.contracts[]``).
CLASS_URN = "otdp.action.meridian_burst/1.0.0"
BURST_URN = "com.meridian.m400.burst_mode/1.0.0"
SELF_CAL_URN = "com.meridian.m400.self_cal/1.0.0"
#: The class actions the served OTDP catalog describes (layer 1). The
#: denominator of the "every declared action resolves" claim is always the
#: descriptor's own action set, asserted from the fixture bytes.
CLASS_ACTIONS = (
    "otdp.daq.abort/1.0.0",
    "otdp.daq.arm/1.0.0",
    "otdp.daq.configure/1.0.0",
    "otdp.daq.fetch/1.0.0",
    "otdp.daq.trigger/1.0.0",
)
#: The derived documents ``derive-ui`` writes — the set no author hand-writes.
DERIVED_DOCUMENTS = (
    "presentation.json",
    "binding-catalogue.json",
    "ui/manifest.json",
    "ui/settings/configure.schema.json",
    "ui/class-reference.json",
)


def _raw(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _fixture_descriptor() -> dict[str, Any]:
    return json.loads((FIXTURES / "descriptor-m400.json").read_bytes())


def _fill_package(package: Path) -> Path:
    """The builder's authored artefacts: the descriptor and the composed
    declaration (plus the pinned files the descriptor declares). Nothing
    else is authored — the rest of the package is the scaffold's own."""
    (package / "descriptor.json").write_bytes(
        (FIXTURES / "descriptor-m400.json").read_bytes()
    )
    (package / "composed-burst.json").write_bytes(
        (FIXTURES / "composed-burst.json").read_bytes()
    )
    return package / "descriptor.json"


def _write_derived(package: Path, derived: Any) -> None:
    """Persist a derivation exactly as ``derive-ui`` does (the same byte
    shape — this is what makes A4's byte comparison meaningful)."""
    ui = package / "ui"
    ui.mkdir(exist_ok=True)
    (ui / "manifest.json").write_bytes(_raw(derived.manifest))
    (package / "presentation.json").write_bytes(_raw(derived.envelope))
    (package / "binding-catalogue.json").write_bytes(_raw(derived.catalogue))
    settings = ui / "settings"
    settings.mkdir(exist_ok=True)
    (settings / "configure.schema.json").write_bytes(_raw(derived.settings_schema))
    presets = ui / "presets"
    presets.mkdir(exist_ok=True)
    for slug, scaffold in derived.preset_scaffolds.items():
        (presets / f"{slug}.json").write_bytes(_raw(scaffold))
    (ui / "class-reference.json").write_bytes(_raw(derived.declaration))


def _m400_project(destination: Path, *, with_ui: bool = True) -> Path:
    """The scaffolded Meridian project with the fixture descriptor filled.

    ``with_ui=True`` runs the brief's ``new --with-ui``; the flag is what
    the acceptance workflow names, so the arms exercise it by default."""
    runner = CliRunner()
    arguments = ["new", str(destination), "--package", PACKAGE]
    if with_ui:
        arguments.append("--with-ui")
    result = runner.invoke(cli, arguments)
    assert result.exit_code == 0, result.output
    package = destination / "src" / PACKAGE
    _fill_package(package)
    return destination


# ---------------------------------------------------------------------------
# A1 — the workflow runs clean (record §7 M1: zero refusals).
# ---------------------------------------------------------------------------


def test_a1_the_workflow_runs_clean(tmp_path: Path) -> None:
    """The acceptance scenario's workflow, in order: ``new --with-ui``, the
    descriptor filled, ``derive-ui``, ``verify-ui`` — each command exits 0
    with zero refusals, and the pages that come out render as-is.

    The render half drives the real standalone host (``render_pages``, the
    same server ``preview-ui`` and ``serve`` use), never a reimplementation.
    """
    project = _m400_project(tmp_path / "m400")
    runner = CliRunner()
    derive = runner.invoke(cli, ["derive-ui", str(project)])
    assert derive.exit_code == 0, derive.output
    for code in (
        "classref_unknown_action",
        "derive_ui_dirty_tree",
        "classref_invalid_composed_class",
        "classref_composed_claim_conflict",
    ):
        assert code not in derive.output, derive.output
    verify = runner.invoke(cli, ["verify-ui", str(project)])
    assert verify.exit_code == 0, verify.output
    assert "Rendered gate clean" in verify.output, verify.output

    package = project / "src" / PACKAGE
    manifest = json.loads((package / "ui" / "manifest.json").read_bytes())
    pages = [str(row["id"]) for row in manifest["pages"]]
    rendered = render_pages(project, pages)
    assert set(rendered) == set(pages)
    for page_id, html in rendered.items():
        assert html.strip(), f"page {page_id} rendered empty"
        # No hand correction: the host's own styling renders, and the
        # plugin authored no stylesheet (A4 asserts the authored set).
        assert "<style" in html or 'rel="stylesheet"' in html or "stylesheet" in html, (
            f"page {page_id} carries no host styling"
        )


# ---------------------------------------------------------------------------
# A2 — all three layers appear in one device (record §7 M3: three distinct
# resolution values for declared actions, each with its own surface).
# ---------------------------------------------------------------------------


def _page_ids(derived: Any) -> list[str]:
    return [str(row["id"]) for row in derived.manifest["pages"]]


def _derived(tmp_path: Path) -> tuple[Path, Any]:
    project = _m400_project(tmp_path / "m400")
    package = project / "src" / PACKAGE
    reference = find_reference(PROFILE)
    assert reference is not None
    derived = derive_ui(
        (package / "descriptor.json").read_bytes(),
        reference,
        descriptor_path=package / "descriptor.json",
    )
    # The derived set replaces the starter's own (`new --with-ui` wrote the
    # read-only starter's documents for the template descriptor); the host
    # then validates the envelope against the filled descriptor's bytes.
    _write_derived(package, derived)
    return project, derived


def test_a2_every_declared_action_resolves(tmp_path: Path) -> None:
    """M1's denominator is the descriptor's action set, never a literal: 100%
    of declared actions appear in the control plan with a non-null
    resolution, and the three layers are all present in the one device."""
    _project, derived = _derived(tmp_path)
    declared = set(_fixture_descriptor()["actions"])
    assert declared, "the fixture declares actions"
    assert set(derived.control_plan) == declared
    unresolved = sorted(
        urn for urn, row in derived.control_plan.items() if not row.get("resolution")
    )
    assert not unresolved, f"plan rows without resolution: {unresolved}"
    resolutions = {
        urn: row["resolution"] for urn, row in derived.control_plan.items()
    }
    assert set(resolutions.values()) == {"catalog", "composed", "custom"}
    assert {urn for urn, value in resolutions.items() if value == "catalog"} == set(
        CLASS_ACTIONS
    )
    assert resolutions[BURST_URN] == "composed"
    assert resolutions[SELF_CAL_URN] == "custom"


def test_a2_class_surfaces_come_from_the_corpus(tmp_path: Path) -> None:
    """Layer 1: the DAQ class's own surfaces — the capture plot with one
    trace per declared measurement, the run buttons and the arm staging
    control, and the configuration data-table — all render from the corpus
    reference, with nothing authored by the fixture."""
    project, derived = _derived(tmp_path)
    pages = [str(row["id"]) for row in derived.manifest["pages"]]
    rendered = render_pages(project, pages)
    capture = census(rendered["capture"])
    assert capture["plots"] == 1
    assert capture["buttons"] == ["arm", "abort", "trigger"]
    assert "action-arm-max_duration_ms" in capture["staged_control_ids"]
    configuration = census(rendered["configuration"])
    assert configuration["data_tables"] == 1
    assert configuration["numerics"] >= 3
    # The measurement members the class covers: one trace per declared
    # channel and quantity, the strain gauge among them.
    dataset = next(
        row for row in derived.catalogue["targets"] if row.get("kind") == "dataset"
    )
    assert [variable["id"] for variable in dataset["variables"]] == [
        "t",
        "ch1-voltage",
        "ch2-voltage",
        "ch3-strain",
    ]


def test_a2_composed_action_surfaces_from_the_plugin_class(tmp_path: Path) -> None:
    """Layer 2: the vendor action resolves through the plugin-local composed
    class (shipped in the package, pinned via ``descriptor.contracts[]``),
    and its control derives from the class's ``input_schema`` — the plan row
    names the class, and the rendered control carries the class's field."""
    project, derived = _derived(tmp_path)
    row = derived.control_plan[BURST_URN]
    assert row["resolution"] == "composed"
    assert row["class"] == CLASS_URN
    assert row["side_effect"] == "state_change"
    assert [field["field"] for field in row["fields"]] == ["burst_count"]
    ledger = derived.declaration
    assert ledger["composed_classes"] == [
        {"class": CLASS_URN, "validated_against": "0.4.0"}
    ]
    assert ledger["composed_actions"] == [
        {"action": BURST_URN, "resolution": "composed", "class": CLASS_URN}
    ]
    pages = _page_ids(derived)
    device_features = census(render_pages(project, pages)["device-features"])
    assert "burst_mode" in device_features["buttons"]
    assert "action-burst_mode-burst_count" in device_features["staged_control_ids"]


def test_a2_residual_action_is_generic_and_labelled_custom(tmp_path: Path) -> None:
    """Layer 3: the residual member derives from its own ``input_constraints``
    and is labelled ``custom`` on every surface the record names — the
    section title the expander mints, the gate's REPORTED row, and the
    declaration's custom inventory."""
    project, derived = _derived(tmp_path)
    row = derived.control_plan[SELF_CAL_URN]
    assert row["resolution"] == "custom"
    assert "class" not in row
    assert [field["field"] for field in row["fields"]] == ["channel"]
    assert derived.declaration["custom_actions"] == [
        {
            "action": SELF_CAL_URN,
            "resolution": "custom",
            "reason": (
                "no served catalog describes this action; controls derive "
                "from the descriptor's own input_constraints"
            ),
        }
    ]
    rendered = render_pages(project, _page_ids(derived))
    html = rendered["device-features"]
    assert "Custom device actions" in html
    assert "action-self_cal-channel" in census(html)["staged_control_ids"]
    report = verify_ui(project)
    assert f"custom: {SELF_CAL_URN}" in report.reported_deviations, (
        report.reported_deviations
    )
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]


# ---------------------------------------------------------------------------
# A3 — the wheel carries the class (the issue's fourth acceptance outcome:
# the composed declaration survives packaging and resolves after install).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def m400_wheel(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """The fixture project's wheel, built once: (project, wheel)."""
    root = tmp_path_factory.mktemp("m400-wheel")
    project = _m400_project(root / "proj", with_ui=False)
    runner = CliRunner()
    derive = runner.invoke(cli, ["derive-ui", str(project)])
    assert derive.exit_code == 0, derive.output
    out = root / "dist"
    built = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out)],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    wheels = sorted(out.glob("*.whl"))
    assert len(wheels) == 1, [path.name for path in wheels]
    return project, wheels[0]


def test_a3_the_wheel_carries_the_composed_declaration(m400_wheel: tuple[Path, Path]) -> None:
    """Packaging half: the wheel carries the composed declaration beside the
    descriptor, along with the derived presentation set — the plugin package
    IS the pinned route, so the pin's file must ride the wheel."""
    _project, wheel = m400_wheel
    members = set(zipfile.ZipFile(wheel).namelist())
    prefix = f"{PACKAGE}/"
    for member in (
        "descriptor.json",
        "composed-burst.json",
        "ui/manifest.json",
        "ui/class-reference.json",
    ):
        assert prefix + member in members, sorted(members)


def test_a3_the_composed_class_resolves_after_install(
    m400_wheel: tuple[Path, Path], tmp_path: Path
) -> None:
    """Install half: the wheel installs into a clean environment, and the
    composed class resolves from the INSTALLED bytes — the descriptor-
    relative pin walk finds the declaration in the installed tree, which is
    the path assumption this arm exists to break.

    The install is a real wheel install into an empty target (the same
    layout a site-packages install produces: package tree + dist-info).
    """
    _project, wheel = m400_wheel
    stage = tmp_path / "installed"
    (stage / "src").mkdir(parents=True)
    installed = subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--target",
            str(stage / "src"),
            "--no-deps",
            str(wheel),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr
    package = stage / "src" / PACKAGE
    assert (package / "composed-burst.json").is_file()
    assert (package / "descriptor.json").is_file()

    reference = find_reference(PROFILE)
    assert reference is not None
    derived = derive_ui(
        (package / "descriptor.json").read_bytes(),
        reference,
        descriptor_path=package / "descriptor.json",
    )
    assert derived.control_plan[BURST_URN]["resolution"] == "composed"
    assert derived.control_plan[BURST_URN]["class"] == CLASS_URN
    assert derived.declaration["composed_classes"] == [
        {"class": CLASS_URN, "validated_against": "0.4.0"}
    ]
    # Preview standalone from the installed tree, through the real host.
    report = verify_ui(stage)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    pages = [str(row["id"]) for row in derived.manifest["pages"]]
    rendered = render_pages(stage, pages)
    assert set(rendered) == set(pages)
    device_features = census(rendered["device-features"])
    assert "action-burst_mode-burst_count" in device_features["staged_control_ids"]


def test_a3_a_clean_environment_install_carries_the_declaration(
    m400_wheel: tuple[Path, Path], tmp_path: Path
) -> None:
    """The literal clean environment: a fresh interpreter venv with the wheel
    installed (no other packages), and the declaration is present beside the
    descriptor in its site-packages tree."""
    _project, wheel = m400_wheel
    venv = tmp_path / "venv"
    made = subprocess.run(
        ["uv", "venv", str(venv)], capture_output=True, text=True, check=False
    )
    assert made.returncode == 0, made.stderr
    installed = subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            # `uv pip install --python` accepts a virtual-environment
            # directory and resolves the interpreter itself, which keeps this
            # arm portable: a POSIX venv puts the interpreter in bin/, a
            # Windows venv in Scripts/.
            str(venv),
            "--no-deps",
            str(wheel),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr
    # POSIX: lib/pythonX.Y/site-packages. Windows: Lib/site-packages.
    site = next(
        path
        for pattern in ("lib/python*/site-packages", "Lib/site-packages")
        for path in venv.glob(pattern)
    )
    package = site / PACKAGE
    assert (package / "descriptor.json").is_file()
    assert (package / "composed-burst.json").is_file()
    assert (
        hashlib.sha256((package / "composed-burst.json").read_bytes()).hexdigest()
        == json.loads((package / "descriptor.json").read_bytes())["contracts"][-1][
            "sha256"
        ]
    )


# ---------------------------------------------------------------------------
# A4 — no hand work. The authored artefacts are the descriptor, the composed
# declaration and fixtures; every derived document is the derivation's own
# output; and the pages are the corpus's pages.
# ---------------------------------------------------------------------------


def test_a4_nothing_is_hand_written(tmp_path: Path) -> None:
    """The derivation produced every page and every derived document. The
    builder authors the descriptor and the composed declaration — nothing
    else: no hand-written manifest pages, no hand-tuned schemas, no CSS."""
    project = _m400_project(tmp_path / "m400")
    runner = CliRunner()
    derive = runner.invoke(cli, ["derive-ui", str(project)])
    assert derive.exit_code == 0, derive.output
    package = project / "src" / PACKAGE

    # Every derived document is byte-identical to what the derivation
    # produces from the descriptor — so nothing was hand-edited after.
    reference = find_reference(PROFILE)
    assert reference is not None
    derived = derive_ui(
        (package / "descriptor.json").read_bytes(),
        reference,
        descriptor_path=package / "descriptor.json",
    )
    for name in DERIVED_DOCUMENTS:
        assert (package / name).is_file(), name
    assert (package / "ui" / "manifest.json").read_bytes() == _raw(derived.manifest)
    assert (package / "presentation.json").read_bytes() == _raw(derived.envelope)
    assert (package / "binding-catalogue.json").read_bytes() == _raw(derived.catalogue)
    assert (package / "ui" / "settings" / "configure.schema.json").read_bytes() == _raw(
        derived.settings_schema
    )
    assert (package / "ui" / "class-reference.json").read_bytes() == _raw(
        derived.declaration
    )
    preset_paths = sorted((package / "ui" / "presets").glob("*.json"))
    assert sorted(derived.preset_scaffolds) == [path.stem for path in preset_paths]
    for path in preset_paths:
        assert path.read_bytes() == _raw(derived.preset_scaffolds[path.stem])

    # The pages are the corpus's pages — no page was authored by hand.
    manifest = json.loads((package / "ui" / "manifest.json").read_bytes())
    reference_pages = [str(row["id"]) for row in reference["pages"]]
    assert [str(row["id"]) for row in manifest["pages"]] == reference_pages

    # No CSS work: the fixture and its package author no stylesheet, and the
    # manifest declares no style asset.
    authored_css = [
        path
        for path in package.rglob("*")
        if path.is_file() and path.suffix in (".css", ".scss", ".less")
    ]
    assert not authored_css, authored_css
    assets = manifest.get("assets") or []
    assert not [
        row for row in assets if str(row.get("path", "")).endswith(".css")
    ], assets

    # The authored set itself: the scaffold's own files plus exactly two
    # authored documents — the descriptor and the composed declaration.
    authored = {path.name for path in package.iterdir() if path.is_file()}
    assert {"descriptor.json", "composed-burst.json"} <= authored
    extra = authored - {
        "descriptor.json",
        "composed-burst.json",
        # the scaffold's own starter files (copier template output)
        "__init__.py",
        "adapter.py",
        "protocol.py",
        "protocol.md",
        "vectors.json",
        # derive-ui's output
        "presentation.json",
        "binding-catalogue.json",
    }
    assert not extra, f"unaccounted authored files: {sorted(extra)}"


# ---------------------------------------------------------------------------
# The fixture's own integrity: the pin names the committed declaration's
# bytes, so a fixture edit cannot silently desynchronise the two.
# ---------------------------------------------------------------------------


def test_the_composed_pin_names_the_fixture_bytes() -> None:
    descriptor = _fixture_descriptor()
    pin = next(
        row
        for row in descriptor["contracts"]
        if row["id"] == "urn:meridian:composed-burst:1.0.0"
    )
    digest = hashlib.sha256((FIXTURES / "composed-burst.json").read_bytes()).hexdigest()
    assert pin["sha256"] == digest


# ---------------------------------------------------------------------------
# Scope arms — the issue's other two custom members, measured. These are the
# honest negative results (project principle 11): the vocabulary admits the
# declaration, the derivation refuses nothing, and no surface comes out.
# They pin that state so a later slice that adds the surface must move them
# deliberately. Not the acceptance claim — named in the report as NOT proved.
# ---------------------------------------------------------------------------


def _computed_descriptor(fixture: str = "descriptor-m400.json") -> dict[str, Any]:
    """A fixture descriptor carrying one computed measurement — V2's
    descriptor-owned layer-2 declaration (``derived_variables``, the
    measurement vocabulary measurement-model.md §8 owns)."""
    descriptor = json.loads((FIXTURES / fixture).read_bytes())
    descriptor["derived_variables"] = [
        {
            "id": "rms_v",
            "quantity": "voltage",
            "unit": "V",
            "expression": "ch1_voltage * 0.707",
        }
    ]
    return descriptor


def _dataset_targets(derived: Any) -> list[dict[str, Any]]:
    return [row for row in derived.catalogue["targets"] if row["kind"] == "dataset"]


def test_scope_b1_computed_measurement_derives_into_every_dataset_target() -> None:
    """(#556 Track B §4 V2) A computed measurement derives into the variable
    set of EVERY dataset target the derivation mints, as an ordinary value
    variable — the descriptor's ``derived_variables`` row is its layer-2
    declaration, and the host computes the value INTO the dataset, so the
    derived wire shape asserting it is honest.

    MOVED DELIBERATELY 2026-10-25 (issue #556 B1): this arm previously pinned
    the honest negative — admitted, derives nothing (D1, "datasets and
    capture shapes"). The design record §4 V2 states the surface, and the old
    arm's own docstring named the condition — "a later slice that adds the
    surface must move them deliberately". Metric: the denominator is
    ``len(descriptor["derived_variables"]) × len(dataset targets)``, both read
    from the derivation, never a literal; the numerator is asserted by
    membership per pair.

    The LA fixture carries TWO dataset targets (the capture slot and the
    decode slot), so "every" is measured over a denominator of two.
    """
    reference = find_reference("otdp.logic_analyser/1.0.0")
    assert reference is not None
    descriptor = _computed_descriptor("descriptor-f1-da.json")
    derived = derive_ui(
        _raw(descriptor),
        reference,
        descriptor_path=FIXTURES / "descriptor-f1-da.json",
    )
    computed = {str(row["id"]) for row in descriptor["derived_variables"]}
    assert computed == {"rms_v"}
    targets = _dataset_targets(derived)
    assert len(targets) == 2, [row["id"] for row in targets]
    pairs = [(member, target["id"]) for target in targets for member in computed]
    assert len(pairs) == len(computed) * len(targets)
    for target in targets:
        variables = {row["id"]: row for row in target["variables"]}
        value_shapes = {
            row["shape"]
            for row in target["variables"]
            if row.get("axis_role") not in ("x", "receipt_time")
        }
        assert len(value_shapes) == 1, target["variables"]
        for member in computed:
            assert member in variables, (member, target["id"], target["variables"])
            # The wire shape decides the variable's shape: a digital-lanes
            # dataset carries vectors, so the computed variable is a vector
            # too — a scalar row would assert a wire shape the dataset does
            # not carry.
            assert variables[member]["shape"] == value_shapes.pop()


def test_scope_b1_computed_measurement_never_derives_an_observation_tile() -> None:
    """KILL (d) guard (#556 Track B §4 V2): a tile is an observation target,
    and the canonical validator requires ``parameter_id`` to name a declared
    readable parameter. A computed variable has no parameter; a tile for it
    would assert a data path that does not exist.

    The DMM fixture is the one with observation tiles, so it is the fixture
    where the guard has something to guard.
    """
    reference = find_reference("otdp.dmm/1.0.0")
    assert reference is not None
    descriptor = _computed_descriptor("descriptor-dmm.json")
    derived = derive_ui(_raw(descriptor), reference, descriptor_path=None)
    observations = [
        row for row in derived.catalogue["targets"] if row["kind"] == "observation"
    ]
    assert observations, "the DMM fixture derives observation tiles"
    computed = {str(row["id"]) for row in descriptor["derived_variables"]}
    declared = {str(row["name"]) for row in descriptor.get("parameters", [])}
    for target in observations:
        assert target["parameter_id"] in declared
        assert computed.isdisjoint(json.dumps(target).split('"'))
    assert computed.isdisjoint(
        json.dumps(derived.manifest["bindings"]).split('"')
    ), derived.manifest["bindings"]


def test_scope_b1_computed_measurement_rides_the_series_rule_where_the_kind_allows() -> None:
    """(#556 Track B §4 V2) The computed variable rides the numeric series
    rule where the plot kind admits it, and nowhere else.

    A waveform dataset page carries numeric vector series, so the computed
    variable is one of the capture plot's y series (the Meridian fixture). A
    digital-lanes plot's y channels are the wire's logic alphabet
    (string/vector, the canonical validator's rule), so the computed variable
    stays in the dataset's variable set and off the plot — the dataset still
    carries it on the wire. The corpus hosts no time_series plot on a dataset
    page (every one is a readings-page plot bound to an observation), so no
    arm here claims a time_series series; the shape rule is pinned by the
    dataset arm above and by the waveform arm here.
    """
    daq_reference = find_reference(PROFILE)
    assert daq_reference is not None
    daq = derive_ui(
        _raw(_computed_descriptor()), daq_reference, descriptor_path=None
    )
    (capture,) = _dataset_targets(daq)
    assert "rms_v" in {row["id"] for row in capture["variables"]}
    waveforms = [
        plot
        for page in daq.manifest["pages"]
        for plot in (page.get("plots") or [])
        if plot["kind"] == "waveform"
    ]
    assert waveforms, "the DAQ fixture derives a waveform plot"
    for plot in waveforms:
        assert "rms_v" in plot["y"], plot

    la_reference = find_reference("otdp.logic_analyser/1.0.0")
    assert la_reference is not None
    la = derive_ui(
        _raw(_computed_descriptor("descriptor-f1-da.json")),
        la_reference,
        descriptor_path=FIXTURES / "descriptor-f1-da.json",
    )
    for target in _dataset_targets(la):
        assert "rms_v" in {row["id"] for row in target["variables"]}, target
    lane_plots = [
        plot
        for page in la.manifest["pages"]
        for plot in (page.get("plots") or [])
        if plot["kind"] == "digital_lanes"
    ]
    assert lane_plots, "the LA fixture derives a digital-lanes plot"
    for plot in lane_plots:
        assert "rms_v" not in plot["y"], plot
        assert "rms_v" not in {hint["variable_id"] for hint in plot["channel_hints"]}


def _decoded_daq(tmp_path: Path) -> tuple[Path, Any, Any]:
    """The Meridian project plus a pinned decoder and its annotation action —
    the shape where decoder lanes are BUILT (the decode_annotated overlay
    fires) but no derived plot carries them (the DAQ plot is a waveform, and
    lanes land only in a digital-lanes plot). Returns (project, package,
    derived)."""
    project = _m400_project(tmp_path / "m400", with_ui=False)
    package = project / "src" / PACKAGE
    decoder_raw = (FIXTURES / "decoder-uart.json").read_bytes()
    (package / "decoder-uart.json").write_bytes(decoder_raw)
    descriptor = _fixture_descriptor()
    descriptor["decoders"] = [
        {
            "id": "uart",
            "path": "decoder-uart.json",
            "sha256": hashlib.sha256(decoder_raw).hexdigest(),
        }
    ]
    descriptor["actions"]["com.meridian.m400.decode_annotated/1.0.0"] = {
        "binding": {"kind": "adapter", "key": "decode_annotated"},
        "input_constraints": {"properties": {}},
        "timeout_ms": 5000,
        "side_effect": "none",
        "cancellable": True,
        "retry": "never",
    }
    descriptor_path = package / "descriptor.json"
    descriptor_path.write_bytes(_raw(descriptor))
    reference = find_reference(PROFILE)
    assert reference is not None
    derived = derive_ui(_raw(descriptor), reference, descriptor_path=descriptor_path)
    return project, package, derived


def test_scope_custom_decoder_declares_without_refusal_but_no_lane(
    tmp_path: Path,
) -> None:
    """A custom decoder (a pinned decoder document plus its annotation
    action) on a DAQ-class device derives with no refusal, and renders no
    decoder lane: the DAQ reference has no decode slot, and the decoder-lane
    derivation lands only in a digital-lanes plot.

    The plan row no longer claims ``rendered_by: "decoder annotation lanes"``
    (R9): the row stops advertising a rendering that does not occur, and the
    gate stays green — the capture page renders a plot, which covers the L4
    dataset surface the row points at. Named here and in the report (deferral
    D1, "channels and decoders"): NOT proved.
    """
    project, package, derived = _decoded_daq(tmp_path)
    row = derived.control_plan["com.meridian.m400.decode_annotated/1.0.0"]
    assert row["resolution"] == "custom"
    # R9: no advertisement of a rendering that does not occur.
    assert "rendered_by" not in row, row

    plot_lanes = [
        plot.get("decoder_lanes")
        for page in derived.manifest["pages"]
        for plot in (page.get("plots") or [])
    ]
    assert not any(plot_lanes), plot_lanes

    _write_derived(package, derived)
    report = verify_ui(project)
    # The gate stays green: the capture page renders a plot, which covers the
    # L4 dataset surface the row points at — the lane claim is never checked.
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    pages = _page_ids(derived)
    capture = census(render_pages(project, pages)["capture"])
    assert capture["lanes_figures"] == 0
    assert capture["lane_labels"] == []


def test_scope_the_daq_class_covers_no_decoder_member() -> None:
    """The fixture declares no decoder member because the DAQ class covers
    none: the reference carries no decode slot, so nothing in the class's
    surface set is a decoder. Stated as a mechanism fact, not a claim."""
    reference = find_reference(PROFILE)
    assert reference is not None
    dataset_slots = {
        key: slot
        for key, slot in reference["slots"].items()
        if slot.get("kind") == "dataset"
    }
    assert set(dataset_slots) == {"capture"}
    assert "decode" not in reference["slots"]


def test_scope_r9_the_claim_stands_when_the_lanes_land() -> None:
    """R9's positive half: the row advertises a rendering exactly when that
    rendering occurs. The logic-analyser fixture has a decode slot and a
    digital-lanes plot, so its pinned decoder's lanes land — and there the
    claim stands. Paired with the DAQ arm above (no advertisement when the
    lanes do not land), this is the honesty rule in both directions.
    """
    reference = find_reference("otdp.logic_analyser/1.0.0")
    assert reference is not None
    derived = derive_ui(
        (FIXTURES / "descriptor-f1-da.json").read_bytes(),
        reference,
        descriptor_path=FIXTURES / "descriptor-f1-da.json",
    )
    urn = "otdp.logic_analyser.decode_annotated/1.0.0"
    row = derived.control_plan[urn]
    assert row["rendered_by"] == "decoder annotation lanes", row
    lanes = [
        plot["decoder_lanes"]
        for page in derived.manifest["pages"]
        for plot in (page.get("plots") or [])
        if plot.get("decoder_lanes")
    ]
    assert lanes, "the lanes the claim names actually derived"


def test_scope_b1_residual_members_are_reported(
    tmp_path: Path,
) -> None:
    """Layer 3's promise is two-sided — never refuses AND never silent. The
    gate's REPORTED channel carries a row for every declared member that
    derives no surface of its vocabulary, and (since #556 B1) V2's
    composed-state row: the computed measurement DOES derive into dataset
    variables and never a tile, so its row states that instead of naming a
    deferral. Silence here is indistinguishable from "we rendered it and it
    looked fine"."""
    project = _m400_project(tmp_path / "m400", with_ui=False)
    package = project / "src" / PACKAGE
    decoder_raw = (FIXTURES / "decoder-uart.json").read_bytes()
    (package / "decoder-uart.json").write_bytes(decoder_raw)
    descriptor = _computed_descriptor()
    descriptor["decoders"] = [
        {
            "id": "uart",
            "path": "decoder-uart.json",
            "sha256": hashlib.sha256(decoder_raw).hexdigest(),
        }
    ]
    (package / "descriptor.json").write_bytes(_raw(descriptor))
    runner = CliRunner()
    derive = runner.invoke(cli, ["derive-ui", str(project)])
    assert derive.exit_code == 0, derive.output
    report = verify_ui(project)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    joined = " | ".join(report.reported_deviations)
    # #556 B1: V2's row flips from "derivation deferred" to the composed-state
    # disclosure — the computed variable DOES derive, into dataset variables,
    # and never a tile (no parameter to read).
    assert (
        "observation variable rms_v: computed variable derives into dataset "
        "variables (no tile; no parameter to read)" in joined
    ), report.reported_deviations
    assert "custom decoder uart" in joined, report.reported_deviations


def test_scope_b1_the_reference_less_arm_reports_them_too(tmp_path: Path) -> None:
    """Both gate arms carry the disclosure (the B6/B7/R3 discipline): the
    reference-less path derives no decoder lanes and no dataset target at
    all, so every declared decoder is a residual member there and every
    computed measurement reports its no-dataset terminal state."""
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "refless"
    create_project(project, "veridian_refless_plugin", with_ui=False)
    package = project / "src" / "veridian_refless_plugin"
    descriptor = json.loads((package / "descriptor.json").read_bytes())
    descriptor["derived_variables"] = [
        {
            "id": "rms_v",
            "quantity": "voltage",
            "unit": "V",
            "expression": "voltage * 0.707",
        }
    ]
    decoder_raw = (FIXTURES / "decoder-uart.json").read_bytes()
    (package / "decoder-uart.json").write_bytes(decoder_raw)
    descriptor["decoders"] = [
        {
            "id": "uart",
            "path": "decoder-uart.json",
            "sha256": hashlib.sha256(decoder_raw).hexdigest(),
        }
    ]
    (package / "descriptor.json").write_bytes(_raw(descriptor))
    create_ui_resources(project, "veridian_refless_plugin")
    report = verify_ui(project, reference=None)
    joined = " | ".join(report.reported_deviations)
    # No class reference, so no dataset target derives: V2's row states that
    # terminal state rather than claiming a dataset variable that no target
    # carries.
    assert (
        "observation variable rms_v: computes no dataset variable (no dataset "
        "target derives on this class); no tile (no parameter to read)"
    ) in joined, report.reported_deviations
    assert (
        "custom decoder uart: no lane host (no derived plot carries its "
        "lanes; lanes host in digital_lanes plots alone)"
    ) in joined, report.reported_deviations


def test_scope_b1_v3_a_channel_matching_no_resolved_slot_is_reported(
    tmp_path: Path,
) -> None:
    """(#556 Track B §4 V3 layer 3, first bullet) A channel whose role matches
    no channels slot the derivation resolves lanes for used to disappear
    without a word anywhere — no lanes and no disclosure. It now yields a
    REPORTED row every run, and a channel that DOES resolve never does.

    Metric: the denominator is ``descriptor.channels`` (asserted from the
    fixture, never a literal); the numerator is channels with a derived lanes
    surface plus channels carrying a row naming the vocabulary. The fixture
    declares four channels and one channels slot (role ``analogue_input``), so
    three resolve and one reports.
    """
    project = _m400_project(tmp_path / "m400", with_ui=False)
    package = project / "src" / PACKAGE
    descriptor = _fixture_descriptor()
    descriptor["channels"].append(
        {
            "id": "clk",
            "label": "Clock lane",
            "role": "digital_input",
            "quantities": ["edge"],
            "parameter_names": [],
        }
    )
    (package / "descriptor.json").write_bytes(_raw(descriptor))
    reference = find_reference(PROFILE)
    assert reference is not None
    derived = derive_ui(
        _raw(descriptor),
        reference,
        descriptor_path=package / "descriptor.json",
    )
    declared = {str(row["id"]) for row in descriptor["channels"]}
    assert len(declared) == 4
    reported = [row for row in derived.residual_members if row.kind == "channel"]
    assert [row.member for row in reported] == ["clk (role digital_input)"]
    assert declared - {"clk"} == {"ch1", "ch2", "ch3"}
    _write_derived(package, derived)
    report = verify_ui(project)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    assert (
        "channel clk (role digital_input): resolves to no lanes surface"
        in report.reported_deviations
    ), report.reported_deviations


def test_scope_b1_v3_the_reference_less_arm_reports_every_channel(
    tmp_path: Path,
) -> None:
    """The closure runs on both gate arms: a descriptor whose profile matches
    no vendored class resolves no channels slot, so every declared channel
    reports — the B6/B7/R3 discipline that every disclosure rides both
    arms."""
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    project = tmp_path / "refless"
    create_project(project, "veridian_refless_plugin", with_ui=False)
    package = project / "src" / "veridian_refless_plugin"
    descriptor = json.loads((package / "descriptor.json").read_bytes())
    descriptor["channels"] = [
        {
            "id": "a1",
            "label": "Analog input 1",
            "role": "analogue_input",
            "quantities": ["voltage"],
            "parameter_names": [],
        }
    ]
    (package / "descriptor.json").write_bytes(_raw(descriptor))
    create_ui_resources(project, "veridian_refless_plugin")
    report = verify_ui(project, reference=None)
    joined = " | ".join(report.reported_deviations)
    assert (
        "channel a1 (role analogue_input): resolves to no lanes surface" in joined
    ), report.reported_deviations


def test_scope_b1_v3_a_decoder_with_no_lane_host_reports_its_reason(
    tmp_path: Path,
) -> None:
    """(#556 Track B §4 V3 layer 3) The decoder disclosure speaks the residual
    vocabulary and names the structural reason: this class's plot is a
    waveform, and lanes host in digital_lanes plots alone. The decoder
    document and its annotation action ARE present — the lanes are built and
    then hosted nowhere — so the row is the only surface that can tell the
    author the decoder has no lane host."""
    project, package, derived = _decoded_daq(tmp_path)
    assert derived.residual_members == (
        ResidualMember(
            "custom decoder",
            "channels and decoders",
            "uart",
            "no lane host (this class's plot is waveform; lanes host in "
            "digital_lanes plots alone)",
        ),
    ), derived.residual_members
    _write_derived(package, derived)
    report = verify_ui(project)
    assert (
        "custom decoder uart: no lane host (this class's plot is waveform; "
        "lanes host in digital_lanes plots alone)"
        in report.reported_deviations
    ), report.reported_deviations


def test_scope_r10_a_decoder_that_renders_is_not_disclosed() -> None:
    """The other direction: the logic-analyser fixture's pinned decoder DOES
    render — its lanes land in the digital-lanes plot — so it must not be
    reported as missing. A decoder that renders is not a deferred member."""
    reference = find_reference("otdp.logic_analyser/1.0.0")
    assert reference is not None
    derived = derive_ui(
        (FIXTURES / "descriptor-f1-da.json").read_bytes(),
        reference,
        descriptor_path=FIXTURES / "descriptor-f1-da.json",
    )
    assert derived.residual_members == (), derived.residual_members
    landed = [
        lane["decoder"]
        for page in derived.manifest["pages"]
        for plot in (page.get("plots") or [])
        for lane in (plot.get("decoder_lanes") or [])
    ]
    assert "uart" in landed, "the decoder this arm says renders actually renders"
