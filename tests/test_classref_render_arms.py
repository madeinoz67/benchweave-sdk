"""The per-class render arms (gateway #463 gap 2, the SDK widening).

One arm family per class of the ACTIVE family, discovered by walking the
vendored class-reference corpus (never a frozen list): the clean arm
proves the derived project renders through the real preview host with the
census equal to the resolved expect; the strip falsifier proves a
schema-valid, check-ui-clean manifest whose render is stripped REDS with
the typed finding; the reference-side count-flip kill proves the arm
catches over-delivery. The specificity arms carry the smu sweep-block
deferral and the function_generator measurement-free shape as live
assertions. Design record:
``.claude/deep-review/2026-10-21-classref-sdk-render-gate-design.md``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import benchweave_sdk
import benchweave_sdk.classref_gate as gate_module
from benchweave_sdk.classref import find_reference
from benchweave_sdk.classref_gate import census, verify_ui
from benchweave_sdk.classref_gate_render import render_pages
from benchweave_sdk.presentation import validate_presentation
from benchweave_sdk.served import active_version

FIXTURES = Path(__file__).parent / "fixtures" / "classref"

#: The family the render arms cover, DISCOVERED from the vendored corpus
#: (the composition gate's rotation rule): profile id -> (slug, document).
#: The count is pinned so a ninth class widens the sample by redding here
#: — its absent arm is a coverage failure, never silence.


def _active_family() -> dict[str, tuple[str, dict[str, Any]]]:
    root = (
        Path(benchweave_sdk.__file__).parent
        / "standards"
        / "plugin-ui-class-reference"
        / active_version("plugin-ui-class-reference")
    )
    family: dict[str, tuple[str, dict[str, Any]]] = {}
    for path in sorted(root.glob("class-*.json")):
        document = json.loads(path.read_text())
        if not isinstance(document, dict) or "profile_id" not in document:
            continue  # the family schema files also match the glob
        family[str(document["profile_id"])] = (
            path.stem.removeprefix("class-"), document
        )
    return family


FAMILY = _active_family()
#: The current family's size, stated over the discovery (a class landing
#: in the corpus reds the equality and owes its own arm family).
FAMILY_SIZE = 8


def _raw(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _build(profile_id: str, destination: Path) -> tuple[Path, Any]:
    from helpers_classref import build_classref_project

    slug = FAMILY[profile_id][0]
    fixture = (
        "descriptor-f1.json"
        if profile_id == "otdp.logic_analyser/1.0.0"
        else f"descriptor-{slug}.json"
    )
    project, derived = build_classref_project(
        destination, fixture, profile_id=profile_id
    )
    return project, derived


def _rewrite_manifest(project: Path, mutate) -> None:
    """Apply ``mutate`` to the written manifest and re-pin the envelope."""
    package = next((project / "src").iterdir())
    manifest = json.loads((package / "ui" / "manifest.json").read_bytes())
    mutate(manifest)
    raw = _raw(manifest)
    (package / "ui" / "manifest.json").write_bytes(raw)
    envelope = json.loads((package / "presentation.json").read_bytes())
    envelope["manifest"]["sha256"] = hashlib.sha256(raw).hexdigest()
    (package / "presentation.json").write_bytes(_raw(envelope))


def _page(manifest: dict[str, Any], page_id: str) -> dict[str, Any]:
    return next(row for row in manifest["pages"] if row["id"] == page_id)


def _layout_page(manifest: dict[str, Any], page_id: str) -> dict[str, Any]:
    block = manifest["extensions"]["plugin-ui-class-reference:layout"]
    return next(row for row in block["pages"] if row["page_id"] == page_id)


def _check_ui_clean(project: Path, derived: Any) -> None:
    """Gap 2's premise, demonstrated: the mutant passes the canonical
    schema gates (check-ui's own validator) — only the render gate sees
    the stripped surface. The resource set carries every settings asset
    the manifest names (per-slot, #556 B4) — never the single-slot
    convenience schema, whose bytes are not what the manifest digests on a
    composed project."""
    package = next((project / "src").iterdir())
    descriptor_raw = (package / "descriptor.json").read_bytes()
    settings_resources = {
        f"settings/{slug}.schema.json": _raw(schema)
        for slug, schema in derived.settings_schemas.items()
    }
    # The production pinned-document seam (#556 B4 motion 1): a composed
    # package's vendor targets name the declaration's pinned profile row,
    # so the candidate validates against the merged set exactly as the
    # shipped check-ui builds it.
    from benchweave_sdk.presentation import (
        pinned_contract_documents,
    )

    report = validate_presentation(
        (package / "presentation.json").read_bytes(),
        descriptor_raw=descriptor_raw,
        resources={
            "manifest.json": (package / "ui" / "manifest.json").read_bytes(),
            **settings_resources,
        },
        binding_catalogue=derived.catalogue,
        pinned_documents=pinned_contract_documents(
            json.loads(descriptor_raw), package / "descriptor.json"
        ),
    )
    assert report.valid, [(f.code, f.path, f.message) for f in report.findings]


def _readings_page_id(reference: dict[str, Any]) -> str | None:
    for page in reference["pages"]:
        if page.get("kind") == "readings":
            return str(page["id"])
    return None


def _plot_page_id(reference: dict[str, Any]) -> str | None:
    for page in reference["pages"]:
        if page.get("plot"):
            return str(page["id"])
    return None


def _strip_spec(profile_id: str) -> tuple[str, str, Any]:
    """(surface, page_id, mutate) — each class's primary surface and the
    manifest mutation that strips it while staying schema-valid."""
    _slug, reference = FAMILY[profile_id]
    readings_page = _readings_page_id(reference)
    plot_page = _plot_page_id(reference)
    if profile_id == "otdp.logic_analyser/1.0.0":
        def strip_run(manifest: dict[str, Any]) -> None:
            page = _layout_page(manifest, "capture")
            page["sections"] = [
                section
                for section in page["sections"]
                if section["id"] != "run"
            ]
        return "button", "capture", strip_run
    if profile_id == "otdp.daq/1.0.0":
        def strip_run(manifest: dict[str, Any]) -> None:
            page = _layout_page(manifest, "capture")
            page["sections"] = [
                section
                for section in page["sections"]
                if section["id"] != "run"
            ]
        return "button", "capture", strip_run
    if profile_id == "otdp.function_generator/1.0.0":
        def strip_table(manifest: dict[str, Any]) -> None:
            page = _layout_page(manifest, "configuration")
            for section in page["sections"]:
                section["children"] = [
                    node
                    for node in section["children"]
                    if node.get("kind") != "data-table"
                ]
        return "data-table", "configuration", strip_table
    if readings_page is not None:
        if profile_id == "otdp.dmm/1.0.0":
            def strip_tiles(manifest: dict[str, Any]) -> None:
                page = _page(manifest, readings_page)
                page["bindings"] = []
                page.pop("plots", None)
            return "reading-tile", readings_page, strip_tiles
        if profile_id == "otdp.dc_psu/1.0.0":
            def strip_tiles_and_plot(manifest: dict[str, Any]) -> None:
                page = _page(manifest, readings_page)
                page["bindings"] = []
                page.pop("plots", None)
            return "reading-tile", readings_page, strip_tiles_and_plot
        assert plot_page is not None
        def strip_plot(manifest: dict[str, Any]) -> None:
            page = _page(manifest, plot_page)
            page.pop("plots", None)
        return "engineering-plot", plot_page, strip_plot
    assert plot_page is not None
    def strip_plot(manifest: dict[str, Any]) -> None:
        page = _page(manifest, plot_page)
        page.pop("plots", None)
    return "engineering-plot", plot_page, strip_plot


def _flip_count(reference: dict[str, Any]) -> dict[str, Any]:
    """The reference-side kill: one expect count flipped upward in an
    in-memory copy (never the corpus bytes) — the design's own shape
    (``1`` → ``2`` on a data-table row)."""
    mutated = json.loads(json.dumps(reference))
    components = mutated["expect"]["components"]
    name, row = next(
        (name, row) for name, row in components.items()
        if str(row["count"]).isdigit()
    )
    row["count"] = str(int(row["count"]) + 1)
    return mutated


def test_the_active_family_is_discovered() -> None:
    """The arms' sample is the vendored corpus's own family — membership
    from discovery, the size pinned (a ninth class reds here and owes its
    own arm family)."""
    assert len(FAMILY) == FAMILY_SIZE, sorted(FAMILY)
    assert "otdp.logic_analyser/1.0.0" in FAMILY


def test_the_expect_grammar_stays_closed(tmp_path: Path) -> None:
    """The widened vocabulary is corpus-defined: the corpus's own names
    resolve through the widened grammar (the widening's face), and a name
    outside them still refuses classref_expect_expression — the SDK adds
    no name the corpus does not carry."""
    from benchweave_sdk.classref import derive_ui

    _slug, reference = FAMILY["otdp.dmm/1.0.0"]
    fixture = FIXTURES / "descriptor-dmm.json"
    raw = fixture.read_bytes()
    # The L11 counter resolves (pre-widening this refuse reds the arm).
    derived = derive_ui(raw, reference, descriptor_path=fixture)
    assert derived.expectation["components"]["reading-tile"]["count"] == 2
    for name in ("{n_bogus}", "{n_reading_tile}"):
        mutated = json.loads(json.dumps(reference))
        mutated["expect"]["components"]["reading-tile"]["count"] = name
        with pytest.raises(ValueError, match="^classref_expect_expression:"):
            derive_ui(raw, mutated, descriptor_path=fixture)


@pytest.mark.parametrize("profile_id", sorted(FAMILY))
def test_clean_arm_renders_green(profile_id: str, tmp_path: Path) -> None:
    """The clean arm: scaffold, swap the class example descriptor, derive,
    write, verify — zero findings through the real host, the reported
    deviations exactly the birth ledger's."""
    project, derived = _build(profile_id, tmp_path / "clean")
    reference = find_reference(profile_id)
    assert reference is not None
    report = verify_ui(project, reference=reference)
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    birth_ids = {
        row["expectation_id"] for row in derived.declaration["deviations"]
    }
    # MOVED DELIBERATELY 2026-10-25 (#556 B4, V6 layer 3): the fixture's
    # unclaimed staged actions gain their settings residual rows on the
    # REPORTED channel — expected alongside the birth ledger's rows, both
    # computed from the derivation, never literals.
    residual_rows = {
        f"{row.kind} {row.member}: {row.detail}"
        for row in derived.residual_members
    }
    assert set(report.reported_deviations) == birth_ids | residual_rows, (
        sorted(report.reported_deviations),
        sorted(birth_ids | residual_rows),
    )


@pytest.mark.parametrize("profile_id", sorted(FAMILY))
def test_strip_falsifier_reds_typed(profile_id: str, tmp_path: Path) -> None:
    """The strip falsifier: a layout-placed or page-declared surface
    removed from the DERIVED manifest stays schema-valid and check-ui
    clean, renders an incomplete page, and REDS the gate with the typed
    finding — component, page, expected count, censused count."""
    surface, page_id, mutate = _strip_spec(profile_id)
    project, derived = _build(profile_id, tmp_path / "strip")
    _rewrite_manifest(project, mutate)
    _check_ui_clean(project, derived)
    reference = find_reference(profile_id)
    assert reference is not None
    report = verify_ui(project, reference=reference)
    typed = [
        f for f in report.findings
        if f.code == "classref_gate_missing" and f.detail.startswith(
            f"{surface} on {page_id}:"
        )
    ]
    assert typed, [f"{f.code}: {f.detail}" for f in report.findings]


@pytest.mark.parametrize("profile_id", sorted(FAMILY))
def test_reference_side_count_flip_kills(profile_id: str, tmp_path: Path) -> None:
    """The rubber-stamp direction: one expect count flipped upward in a
    copy of the reference REDS the clean project — the gate compares the
    render against the reference, never the other way round."""
    project, _derived = _build(profile_id, tmp_path / "flip")
    _slug, reference = FAMILY[profile_id]
    report = verify_ui(project, reference=_flip_count(reference))
    assert not report.clean, [
        f"{f.code}: {f.detail}" for f in report.findings
    ]
    assert any(
        f.code in ("classref_gate_missing", "classref_gate_excess")
        for f in report.findings
    ), [f"{f.code}: {f.detail}" for f in report.findings]


@pytest.mark.parametrize("profile_id", sorted(FAMILY))
def test_red_sanity_neutralized_detector(
    profile_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED-sanity (the composition gate's precedent): with the component
    detectors neutralized (findings forced empty), the strip mutant's typed
    finding VANISHES — the falsifier's red rode the census-vs-expect
    comparison, not incidental breakage, so the arms discriminate.
    MOVED DELIBERATELY 2026-10-26 (#556 B4 fold F2): the gate now carries
    a SECOND component detector — the per-surface data-table comparison —
    which reds the function_generator strip (its target surface is a
    data-table) independently of ``_assert_expect``; neutralizing the
    count detector alone would leave that red standing and prove nothing
    about either. Both detectors neutralize together; the per-surface
    arm's own red-sanity runs beside the F2 arms."""
    _surface, _page_id, mutate = _strip_spec(profile_id)
    project, _derived = _build(profile_id, tmp_path / "sanity")
    _rewrite_manifest(project, mutate)
    monkeypatch.setattr(
        gate_module, "_assert_expect", lambda *a, **k: ([], [])
    )
    monkeypatch.setattr(
        gate_module, "_data_table_surface_findings", lambda *a, **k: []
    )
    reference = find_reference(profile_id)
    assert reference is not None
    report = verify_ui(project, reference=reference)
    component = [
        f for f in report.findings if f.code in (
            "classref_gate_missing", "classref_gate_excess"
        ) and " on " in f.detail
    ]
    assert not component, [f"{f.code}: {f.detail}" for f in report.findings]


def test_smu_sweep_block_surfaces_reported(tmp_path: Path) -> None:
    """The smu specificity arm: the sweep block's declared actions carry
    no sweep surface (no plot and no data table beyond the class's own
    output page) and surface on the Device features page — declared,
    REPORTED, never silent (the corpus's own sweep-surfaces deferral,
    carried as a live assertion). abort is the D7 carve-out: it renders
    its button and may never ride a deviation ledger."""
    project, derived = _build("otdp.smu/1.0.0", tmp_path / "smu")
    package = next((project / "src").iterdir())
    sweep_slugs = ("configure_sweep", "arm", "trigger", "fetch", "abort")
    sweep = [
        urn for urn in derived.control_plan
        if urn.startswith("otdp.smu.")
        and urn.split("/")[0].rsplit(".", 1)[-1] in sweep_slugs
    ]
    assert {urn.split("/")[0].rsplit(".", 1)[-1] for urn in sweep} == set(
        sweep_slugs
    )
    assert all(
        derived.control_plan[urn]["page"] == "device-features"
        for urn in sweep
    ), {urn: derived.control_plan[urn]["page"] for urn in sweep}
    declared = [urn for urn in sweep if not urn.split("/")[0].endswith(".abort")]
    declaration = json.loads(
        (package / "ui" / "class-reference.json").read_bytes()
    )
    declaration["deviations"].extend(
        {"expectation_id": urn, "reason": "sweep block deferred as a unit"}
        for urn in declared
    )
    (package / "ui" / "class-reference.json").write_bytes(_raw(declaration))
    report = verify_ui(project, reference=find_reference("otdp.smu/1.0.0"))
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    assert set(declared) <= set(report.reported_deviations)
    abort_urn = next(urn for urn in sweep if urn.split("/")[0].endswith(".abort"))
    assert abort_urn not in report.reported_deviations
    pages = [str(page["id"]) for page in derived.manifest["pages"]]
    censused = {
        page: census(html) for page, html in render_pages(project, pages).items()
    }
    assert sum(seen["plots"] for seen in censused.values()) == 1
    assert censused["output"]["data_tables"] == 1
    assert censused["device-features"]["data_tables"] == 0


def test_function_generator_renders_no_plot_and_no_tile(tmp_path: Path) -> None:
    """The measurement-free class: no plot and no reading tile renders
    anywhere; the configuration page owns the one data table."""
    project, derived = _build(
        "otdp.function_generator/1.0.0", tmp_path / "fgen"
    )
    report = verify_ui(
        project, reference=find_reference("otdp.function_generator/1.0.0")
    )
    assert report.clean, [f"{f.code}: {f.detail}" for f in report.findings]
    pages = [str(page["id"]) for page in derived.manifest["pages"]]
    censused = {
        page: census(html) for page, html in render_pages(project, pages).items()
    }
    assert sum(seen["plots"] for seen in censused.values()) == 0
    assert sum(seen["readings"] for seen in censused.values()) == 0
    assert censused["configuration"]["data_tables"] == 1


# ---------------------------------------------------------------------------
# #556 B4 fold F2 — the per-surface data-table census. The pooled count
# launders coverage in two shapes: a strip-plus-pad (the member's table
# removed, a data-table node padded on another page — the pooled expect row
# re-satisfied) and the logic_analyser strip (the class carries no
# data-table expect row at all, and the A02 birth deviation downgrades the
# L3 coverage miss). The census now attributes every served table to its
# binding; the gate compares (page, binding) sets against the DERIVED
# layout's own minted surfaces, never sums.
# ---------------------------------------------------------------------------


def _m400_project(destination: Path) -> tuple[Path, Any]:
    """The M-400 fixture as a verify-ui project: daq reference, the member
    declaration and the vendor catalog pinned (the B4 composed shape whose
    configuration page carries BOTH data-table surfaces)."""
    from helpers_classref import build_classref_project

    project, derived = build_classref_project(
        destination, "descriptor-m400.json", profile_id="otdp.daq/1.0.0"
    )
    package = next((project / "src").iterdir())
    for pin in (
        "composed-burst.json",
        "member-declaration-m400.json",
        "meridian-actions.json",
    ):
        (package / pin).write_bytes(
            (FIXTURES / pin).read_bytes()
        )
    return project, derived


def test_strip_and_pad_no_longer_launder_the_pooled_count(
    tmp_path: Path,
) -> None:
    """Refute shape (a): the member's data-table stripped from the
    configuration page while a data-table node padded onto the capture page
    keeps every pooled count the gate read — the expect row still says 2,
    check-ui stays clean — yet the render is missing the member's surface
    and carrying one the derivation never minted. The per-surface
    comparison reds BOTH directions, naming the binding and the page."""
    project, derived = _m400_project(tmp_path / "m400")
    assert [
        (p["page_id"], n["binding_id"])
        for p in derived.layout_block["pages"]
        for s in p["sections"]
        for n in s.get("children", [])
        if n.get("kind") == "data-table"
    ] == [("configuration", "configure"), ("configuration", "vendor-configure")]

    def strip_and_pad(manifest: dict[str, Any]) -> None:
        configuration = _layout_page(manifest, "configuration")
        for section in configuration["sections"]:
            section["children"] = [
                node
                for node in section.get("children", [])
                if not (
                    node.get("kind") == "data-table"
                    and node.get("binding_id") == "vendor-configure"
                )
            ]
        capture = _layout_page(manifest, "capture")
        capture["sections"][-1]["children"].append(
            {"binding_id": "vendor-configure", "kind": "data-table"}
        )

    _rewrite_manifest(project, strip_and_pad)
    _check_ui_clean(project, derived)
    report = verify_ui(project, reference=find_reference("otdp.daq/1.0.0"))
    details = [f.detail for f in report.findings]
    assert (
        "data-table vendor-configure on configuration: the derivation mints "
        "this surface, the render serves no table for it"
    ) in details, details
    assert (
        "data-table vendor-configure on capture: the render serves a table "
        "the derivation does not mint"
    ) in details, details


def test_the_logic_analyser_table_strip_reds_without_an_expect_row(
    tmp_path: Path,
) -> None:
    """Refute shape (b): the logic_analyser class carries no data-table
    expect row at all, and its L3 coverage rows ride the A02 birth
    deviation — so stripping every configuration table left the gate clean.
    The minted-surface comparison owes nothing to either: the derivation
    minted the surface, the render dropped it, the gate reds."""
    project, derived = _build(
        "otdp.logic_analyser/1.0.0", tmp_path / "strip-tables"
    )
    minted = [
        (p["page_id"], n["binding_id"])
        for p in derived.layout_block["pages"]
        for s in p["sections"]
        for n in s.get("children", [])
        if n.get("kind") == "data-table"
    ]
    assert minted, "the fixture derives at least one data-table surface"

    def strip_tables(manifest: dict[str, Any]) -> None:
        for page in manifest["extensions"][
            "plugin-ui-class-reference:layout"
        ]["pages"]:
            for section in page["sections"]:
                section["children"] = [
                    node
                    for node in section.get("children", [])
                    if node.get("kind") != "data-table"
                ]

    _rewrite_manifest(project, strip_tables)
    _check_ui_clean(project, derived)
    report = verify_ui(
        project, reference=find_reference("otdp.logic_analyser/1.0.0")
    )
    details = [f.detail for f in report.findings]
    for page_id, binding in minted:
        assert (
            f"data-table {binding} on {page_id}: the derivation mints this "
            "surface, the render serves no table for it"
        ) in details, details


def test_table_surface_red_sanity_neutralized_detector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED-sanity for the per-surface arm: with the surface detector
    neutralized (findings forced empty), the logic_analyser strip mutant's
    per-surface findings VANISH — the red rode the minted-vs-served set
    comparison, not incidental breakage."""
    project, _derived = _build(
        "otdp.logic_analyser/1.0.0", tmp_path / "sanity-tables"
    )

    def strip_tables(manifest: dict[str, Any]) -> None:
        for page in manifest["extensions"][
            "plugin-ui-class-reference:layout"
        ]["pages"]:
            for section in page["sections"]:
                section["children"] = [
                    node
                    for node in section.get("children", [])
                    if node.get("kind") != "data-table"
                ]

    _rewrite_manifest(project, strip_tables)
    monkeypatch.setattr(
        gate_module,
        "_data_table_surface_findings",
        lambda *a, **k: [],
    )
    reference = find_reference("otdp.logic_analyser/1.0.0")
    assert reference is not None
    report = verify_ui(project, reference=reference)
    surface = [
        f
        for f in report.findings
        if "the derivation mints this surface" in f.detail
    ]
    assert not surface, [f"{f.code}: {f.detail}" for f in surface]


# ---------------------------------------------------------------------------
# #556 B4 fold F5 — the V6 classifier's class-action discriminator. A
# served profile row's required/optional actions list the CLASS's run-verbs;
# an action so listed is a class action whatever its derived level, never a
# vendor settings member. The other direction holds: an action no served row
# lists (the fixture's invented vendor action, staged on device-features)
# still reports.
# ---------------------------------------------------------------------------


def test_smu_class_run_verbs_are_not_settings_members(tmp_path: Path) -> None:
    """Both directions on the SMU fixture: otdp.smu.arm and otdp.smu.fetch
    are listed in the served otdp.smu profile row's optional actions — class
    run-verbs staged on device-features, never vendor settings members —
    while an invented vendor action no served row lists still carries the
    settings-member row."""
    from benchweave_sdk.classref import derive_ui

    staged_urn = "com.meridian.m400.audit_log/1.0.0"
    descriptor = json.loads((FIXTURES / "descriptor-smu.json").read_bytes())
    descriptor["actions"][staged_urn] = {
        "binding": {"kind": "adapter", "key": "fixture"},
        "input_constraints": {
            "properties": {"retain_days": {"type": "integer"}},
            "required": ["retain_days"],
        },
        "timeout_ms": 5000,
        "side_effect": "state_change",
        "cancellable": True,
        "retry": "never",
    }
    scratch = tmp_path / "smu-f5"
    scratch.mkdir()
    raw_descriptor = _raw(descriptor)
    (scratch / "descriptor.json").write_bytes(raw_descriptor)
    derived = derive_ui(
        raw_descriptor,
        find_reference("otdp.smu/1.0.0"),
        descriptor_path=scratch / "descriptor.json",
    )
    members = {
        row.member
        for row in derived.residual_members
        if row.kind == "settings member"
    }
    assert "otdp.smu.arm/1.0.0" not in members, sorted(members)
    assert "otdp.smu.fetch/1.0.0" not in members, sorted(members)
    assert staged_urn in members, sorted(members)
