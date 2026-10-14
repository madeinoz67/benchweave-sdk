"""Issue #449 slice 1 — preview host fidelity (the design record's §7 gate).

The standalone host renders THROUGH the installed ui-html package for every
declared plot: the digital-lanes figure is the package's own
``render_lanes(compose_lanes(declaration))`` output (byte parity, AR-1), the
package's ``bw-host.js`` theme script serves and loads (AR-2), and a
manifest-declared ``preview.css`` override serves digest-verified, after the
token stylesheets, on the preview host's pages only (AR-4).

The pre-committed acceptance rule lives in the design record (gateway repo,
``.claude/deep-review/2026-10-12-issue449-preview-fidelity-design.md`` §7);
the tests below are that rule, executable. The lanes plugin fixture is a
fully validated project — descriptor (invoke + actions + profiles),
binding catalogue (dataset targets), manifest (the AR-1 declared shape: 3
channel lanes, 1 bus group of 2 members, 1 decoder lane), envelope digests
repinned — so the host's real load path admits it and the served page is
the host's real render.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk.presentation import create_ui_resources
from benchweave_sdk.scaffold import create_project
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.session import load_plugin_project

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
UI_ASSETS = SRC / "benchweave_sdk_server" / "ui_assets"
HOST_PACKAGE = SRC / "benchweave_sdk_server"

# --- the lanes plugin fixture ----------------------------------------------------


def _daq_contracts() -> list[dict[str, Any]]:
    """The corpus-pinned contract rows (from the vendored OTDP 0.2.0
    example descriptor): the invoke-carrying descriptor branch requires a
    contracts block whose digests must match the vendored bytes."""
    document = json.loads(
        (SRC / "benchweave_sdk/standards/otdp/0.2.0/examples/class-daq.json").read_text()
    )
    return document["contracts"]


def build_lanes_project(destination: Path, *, preview_css: bytes | None = None) -> Path:
    """A validated lanes plugin project (module-fixture input).

    ``preview_css`` declares the override asset in the manifest
    (``assets[]`` with the digest pin) and writes the bytes; ``None``
    ships no override — the default-tokens arm's project.
    """
    create_project(destination, "example_plugin")
    create_ui_resources(destination, "example_plugin")
    package = destination / "src" / "example_plugin"

    descriptor = json.loads((package / "descriptor.json").read_text())
    descriptor["capabilities"] = ["identify", "read", "invoke"]
    descriptor["operations"]["invoke"] = {
        "timeout_ms": 30000,
        "side_effect": "none",
        "retry": "never",
        "cancellable": True,
        "completion": "acknowledged",
    }
    descriptor["required_features"] = descriptor.get("required_features", []) + [
        "otdp.profile_actions/0.1.0",
        "otdp.measurement/0.1.0",
        "otdp.logic_analyser/1.0.0",
    ]
    descriptor["channels"] = [
        {
            "id": "logic_a",
            "label": "Logic bank A",
            "role": "digital_input",
            "quantities": ["digital"],
            "parameter_names": [],
        }
    ]
    descriptor["profiles"] = ["otdp.logic_analyser/1.0.0"]
    descriptor["contracts"] = _daq_contracts()
    descriptor["actions"] = {
        "otdp.logic_analyser.fetch/1.0.0": {
            "binding": {"kind": "adapter", "key": "otdp.logic_analyser.fetch/1.0.0"},
            "input_constraints": {},
            "timeout_ms": 30000,
            "side_effect": "none",
            "cancellable": True,
            "retry": "never",
        },
        "otdp.logic_analyser.decode/1.0.0": {
            "binding": {"kind": "adapter", "key": "otdp.logic_analyser.decode/1.0.0"},
            "input_constraints": {},
            "timeout_ms": 30000,
            "side_effect": "none",
            "cancellable": True,
            "retry": "never",
        },
    }
    raw = (json.dumps(descriptor, indent=2) + "\n").encode()
    (package / "descriptor.json").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()

    catalogue_path = package / "binding-catalogue.json"
    catalogue = json.loads(catalogue_path.read_text())

    def lane_variable(name: str) -> dict[str, Any]:
        return {"id": name, "type": "string", "unit": None, "shape": "vector"}

    catalogue["targets"] = [
        {
            "id": "logic",
            "kind": "dataset",
            "action_id": "otdp.logic_analyser.fetch/1.0.0",
            "profile_ids": ["otdp.logic_analyser/1.0.0"],
            "measurement_schema_id": "urn:otdp:measurement:0.2.0",
            "variables": [
                {
                    "id": "time",
                    "type": "number",
                    "unit": "s",
                    "shape": "vector",
                    "axis_role": "x",
                },
                lane_variable("d0"),
                lane_variable("d1"),
                lane_variable("d2"),
                lane_variable("d3"),
            ],
        },
        {
            "id": "decode-events",
            "kind": "dataset",
            "action_id": "otdp.logic_analyser.decode/1.0.0",
            "profile_ids": ["otdp.logic_analyser/1.0.0"],
            "measurement_schema_id": "urn:otdp:measurement:0.2.0",
            "variables": [
                {
                    "id": "time",
                    "type": "number",
                    "unit": "s",
                    "shape": "vector",
                    "axis_role": "x",
                },
                lane_variable("payload"),
            ],
        },
    ]
    catalogue["descriptor_sha256"] = digest
    catalogue_path.write_bytes((json.dumps(catalogue, indent=2) + "\n").encode())

    manifest_path = package / "ui" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["descriptor_sha256"] = digest
    manifest["bindings"] = [
        {"id": "logic-capture", "kind": "dataset", "target_id": "logic"},
        {"id": "decode-capture", "kind": "dataset", "target_id": "decode-events"},
    ]
    manifest["pages"] = [
        {
            "id": "capture",
            "title": "Capture",
            "kind": "dataset",
            "bindings": ["logic-capture", "decode-capture"],
            "required": True,
            "plots": [
                {
                    "kind": "digital_lanes",
                    "binding_id": "logic-capture",
                    "x": "time",
                    "y": ["d0", "d1", "d2", "d3"],
                    # F1's shape: a schema-valid lanes visibility hint —
                    # d2 declares ``visible: false`` (the lanes-legal hint
                    # form; colour_role is forbidden for this kind).
                    "channel_hints": [{"variable_id": "d2", "visible": False}],
                    "lane_groups": [
                        {
                            "id": "bus_ab",
                            "label": "Bus AB",
                            "member_ids": ["d0", "d1"],
                            "radix": "hex",
                        },
                        # F2's distinct shape: no label (label falls back
                        # to the group id) and no radix (schema default).
                        {"id": "bus_ef", "member_ids": ["d2", "d3"]},
                    ],
                    "decoder_lanes": [
                        {
                            "id": "uart",
                            "label": "UART",
                            "decoder": "uart8n1",
                            "source_channel_ids": ["d0"],
                            "binding_id": "decode-capture",
                        }
                    ],
                }
            ],
        }
    ]
    if preview_css is not None:
        (package / "ui" / "preview.css").write_bytes(preview_css)
        manifest["assets"] = [
            {
                "id": "preview-override",
                "path": "preview.css",
                "sha256": hashlib.sha256(preview_css).hexdigest(),
            }
        ]
    manifest_raw = (json.dumps(manifest, indent=2) + "\n").encode()
    manifest_path.write_bytes(manifest_raw)

    envelope_path = package / "presentation.json"
    envelope = json.loads(envelope_path.read_text())
    envelope["descriptor_sha256"] = digest
    envelope["manifest"]["sha256"] = hashlib.sha256(manifest_raw).hexdigest()
    envelope_path.write_text(json.dumps(envelope, indent=2) + "\n")
    return destination


# --- the pin-scoped corpus scope -------------------------------------------------


def _re_pin_descriptor(project: Path, version: str) -> None:
    """Re-pin the lanes project's descriptor to ``version`` and re-stamp the
    digest chain (catalogue, manifest, envelope) so the host admits it."""
    package = project / "src" / "example_plugin"
    descriptor_path = package / "descriptor.json"
    descriptor = json.loads(descriptor_path.read_text())
    descriptor["otdp_version"] = version
    raw = (json.dumps(descriptor, indent=2) + "\n").encode()
    descriptor_path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    catalogue_path = package / "binding-catalogue.json"
    catalogue = json.loads(catalogue_path.read_text())
    catalogue["descriptor_sha256"] = digest
    catalogue_path.write_bytes((json.dumps(catalogue, indent=2) + "\n").encode())
    manifest_path = package / "ui" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["descriptor_sha256"] = digest
    manifest_raw = (json.dumps(manifest, indent=2) + "\n").encode()
    manifest_path.write_bytes(manifest_raw)
    envelope_path = package / "presentation.json"
    envelope = json.loads(envelope_path.read_text())
    envelope["descriptor_sha256"] = digest
    envelope["manifest"]["sha256"] = hashlib.sha256(manifest_raw).hexdigest()
    envelope_path.write_text(json.dumps(envelope, indent=2) + "\n")


def test_profile_rows_follow_the_descriptor_pin_down_as_well_as_up(
    tmp_path: Path,
) -> None:
    """The corpus catalog scope follows the descriptor's OWN pin: a lanes
    project pinned DOWN to 0.2.2 validates against 0.2.2's profile rows even
    though 0.2.3 is active and served (the pin selects the catalog, not the
    active row). Without the pin scope, two served versions whose profile
    rows legitimately evolved read as a profile_shadow refusal — 0.2.3's
    added decode_annotated optional action diverges the
    otdp.logic_analyser/1.0.0 row across the served set."""
    project = build_lanes_project(tmp_path / "pinned-down")
    _re_pin_descriptor(project, "0.2.2")
    plugin = load_plugin_project(project)
    assert plugin is not None


# --- host/app clients ------------------------------------------------------------


def _policy() -> GuardPolicy:
    return GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )


def _app_client(project: Path, **kwargs: Any) -> TestClient:
    from benchweave_sdk_server.cli import _build_seam
    from benchweave_sdk_server.web import build_app

    seam, selection = _build_seam(project, **kwargs)
    policy = _policy()
    app = build_app(seam, policy=policy, scenario=selection)
    return TestClient(app, base_url="http://127.0.0.1:8477")


@pytest.fixture(scope="module")
def lanes_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    project = tmp_path_factory.mktemp("lanes") / "lanes_plugin"
    return build_lanes_project(project)


@pytest.fixture(scope="module")
def lanes_view(lanes_project: Path):
    """The projected digital-lanes view the host itself renders from —
    through the host's real load path (the same ``plot_views`` the page
    route walks)."""
    from benchweave_sdk_server.presentation import load_host_presentation

    plugin = load_plugin_project(lanes_project)
    views = load_host_presentation(plugin).plot_views
    assert [view.kind for view in views] == ["digital_lanes"]
    return views[0]


@pytest.fixture(scope="module")
def lanes_clients(lanes_project: Path) -> list[TestClient]:
    """Three served pages of the fixture's page: the default serve plus two
    generated baseline scenarios (normal, stale). The host's scenario
    surface carries only the nine generated baselines — authored fixtures
    are not scenario-selectable — so the design's third render is the
    default serve; the figure is declaration-only, hence scenario-
    independent, which is what the triple render proves."""
    return [
        _app_client(lanes_project),
        _app_client(lanes_project, scenario="normal"),
        _app_client(lanes_project, scenario="stale"),
    ]


def _declaration_from(view: Any):
    """The design §3.1.2 projection as a DRIFT PIN + package-determinism
    check (fold F2): this is a same-commit transcription of the host's
    ``build_lanes_declaration`` — the byte-parity metric cannot distinguish
    a shared misreading of the design from host drift, and it is not
    claimed to. What it proves: the host renders THROUGH the package (the
    AR-3 control shows any host-authored markup breaks it) and the package
    render is deterministic for the projected view. Distinct declared
    shapes ride the fixture (F2b): the F1 visibility-hint channel, a
    labelled hex group and a label-fallback/radix-default group, and a
    decoder lane."""
    from benchweave_ui_html.lanes import LanesDeclaration, LaneSpec

    lanes = []
    index = 0
    for channel in view.channels:
        lanes.append(
            LaneSpec(
                index=index,
                kind="channel",
                label=channel.label,
                # F1: the projected hint's visibility maps to the spec's
                # hidden flag — an OMITTED or true hint stays visible.
                hidden=channel.visible is False,
            )
        )
        index += 1
    for group in view.lane_groups:
        members = tuple(str(member) for member in group["member_ids"])
        lanes.append(
            LaneSpec(
                index=index,
                kind="group",
                label=str(group.get("label") or group["id"]),
                members=members,
                bit_width=len(members),
                radix=group.get("radix", "hex"),
            )
        )
        index += 1
    for decoder in view.decoder_lanes:
        lanes.append(
            LaneSpec(
                index=index,
                kind="decoder",
                label=str(decoder.get("label") or decoder["id"]),
                source_channel=str(decoder["source_channel_ids"][0]),
            )
        )
        index += 1
    from benchweave_sdk_server.plots import PLOT_COLUMNS

    return LanesDeclaration(
        title=view.title,
        description=(
            f"{view.title}: the declared capture structure; "
            "no capture data is acquired in preview."
        ),
        lanes=tuple(lanes),
        acquired=0,
        columns=PLOT_COLUMNS,
        axis_label=view.x.label,
        axis_unit="s",
    )


def _package_render(view: Any) -> str:
    """The package's figure for the transcribed declaration — the same two
    package calls the host must route through."""
    from benchweave_ui_html.lanes import compose_lanes
    from benchweave_ui_html.partials import render_lanes

    declaration = _declaration_from(view)
    member_states = {
        str(member): ()
        for group in view.lane_groups
        for member in group["member_ids"]
    }
    return render_lanes(compose_lanes(declaration, member_states))


LANES_FIGURE = re.compile(r'<figure class="bw-lanes".*?</figure>', re.DOTALL)


def _figure(body: str) -> str:
    match = LANES_FIGURE.search(body)
    assert match is not None, "the page carries the package's lanes figure"
    return match.group(0)


# --- AR-1: fidelity by construction ---------------------------------------------


def test_ar1_the_served_lanes_figure_is_byte_equal_to_the_package_render(
    lanes_clients: list[TestClient], lanes_view: Any
) -> None:
    expected = _package_render(lanes_view)
    figures = [_figure(client.get("/pages/capture").text) for client in lanes_clients]
    assert figures[0] == figures[1] == figures[2], (
        "the declaration-only figure is stable across host states"
    )
    assert figures[0] == expected, "the host renders the package's exact bytes"
    for literal in (
        "data-bw-lane",
        "data-bw-lane-kind",
        "data-bw-acquisition",
        "bw-lanes__label",
    ):
        assert literal in figures[0], literal


def test_ar1_a_declared_visibility_hint_hides_its_lane(
    lanes_clients: list[TestClient],
) -> None:
    """Fold F1: a schema-valid lanes visibility hint
    (``channel_hints: [{variable_id: "d2", visible: false}]``) has its
    rendered effect — the projected ``PlotChannel.visible`` maps to
    ``LaneSpec.hidden`` and the package renders ``data-hidden`` plus its
    hidden marker on that lane. The scalar branch honors the same field;
    the lanes branch may not silently ignore it. Note the hint constrains
    the CHANNEL lane only: the bus group claiming d2 still renders."""
    figure = _figure(lanes_clients[0].get("/pages/capture").text)
    d2_lane = re.search(
        r'<div class="bw-lanes__lane"[^>]*data-bw-lane="2"[^>]*>', figure
    )
    assert d2_lane is not None, "the d2 channel lane renders"
    assert "data-hidden" in d2_lane.group(0), (
        "the declared visibility hint hides the d2 lane"
    )
    assert "hidden by presentation preference" in figure, (
        "the package's hidden marker renders beside the label"
    )


def test_ar1_no_host_lanes_disclosure_string_remains() -> None:
    """The skeleton's disclosure text is gone from the host package — in
    ANY file type (fold F7: the old arm narrowed to ``*.py``, blind to a
    disclosure that survives in a template, asset or doc). The package's
    own acquisition line is the one shown (the AR-3 control restores the
    skeleton and this grep must fail with it)."""
    offenders = [
        path
        for path in sorted(HOST_PACKAGE.rglob("*"))
        if path.is_file()
        and "captures begin at I3"
        in path.read_bytes().decode("utf-8", errors="ignore")
    ]
    assert offenders == []


def test_ar1_the_lanes_figure_renders_outside_the_readings_poll_region(
    lanes_clients: list[TestClient],
) -> None:
    """The lanes figure owns its wrapper (no poll trigger): a poll must not
    wipe viewport state — the page's own controls rule, extended to the
    figure. Scalar plots stay in the poll region."""
    client = lanes_clients[0]
    body = client.get("/pages/capture").text
    wrapper = re.search(r'<section class="bw-lanes-region"[^>]*>', body)
    assert wrapper is not None, "the lanes figure has its own wrapper element"
    assert "hx-trigger" not in wrapper.group(0), "the wrapper carries no poll trigger"
    # The figure renders INSIDE that wrapper.
    assert body.index(wrapper.group(0)) < body.index("<figure")

    # The poll partial never carries the figure.
    partial = client.get("/pages/capture/readings").text
    assert LANES_FIGURE.search(partial) is None, (
        "the poll swap region must not re-render the lanes figure"
    )


def test_ar1_the_capture_page_is_waveform_first(
    lanes_clients: list[TestClient], tmp_path: Path
) -> None:
    """Fold F8 (owner directive, live preview review — issue comment
    6127477670): a digital analyzer UI is waveform-first, so the capture
    page LEADS with the lane traces — the lanes figure precedes the
    readings region in the served DOM. Reading tiles stay the secondary
    surface (below; the console's stacking as the reference shape).
    Scope guard: a page WITHOUT lanes plots keeps its tile-first shape —
    the reorder is gated on the lanes region's presence."""
    body = lanes_clients[0].get("/pages/capture").text
    assert body.index('<figure class="bw-lanes"') < body.index(
        'id="page-readings"'
    ), "the capture page leads with the lane traces"

    # Scope guard, end to end: the scaffolded starter (time_series only,
    # no lanes plots) keeps the readings region before any figure.
    from benchweave_sdk.presentation import create_ui_resources

    scaffold = tmp_path / "starter"
    create_project(scaffold, "example_plugin")
    create_ui_resources(scaffold, "example_plugin")
    from benchweave_sdk_server.cli import _build_seam
    from benchweave_sdk_server.web import build_app

    seam, selection = _build_seam(scaffold)
    app = build_app(seam, policy=_policy(), scenario=selection)
    with TestClient(app, base_url="http://127.0.0.1:8477") as client:
        tile_page = client.get("/pages/readings").text
    assert tile_page.index('id="page-readings"') < tile_page.index("<figure"), (
        "a page without lanes plots keeps the tile-first shape"
    )


# --- AR-2: theme/asset parity ----------------------------------------------------


def test_ar2_the_host_script_serves_from_the_installed_package(
    lanes_clients: list[TestClient],
) -> None:
    from benchweave_ui_html.assets import ASSETS_DIR

    served = lanes_clients[0].get("/assets/bw-host.js")
    assert served.status_code == 200
    assert served.content == (Path(ASSETS_DIR) / "bw-host.js").read_bytes()
    page = lanes_clients[0].get("/pages/capture").text
    assert '<script src="/assets/bw-host.js" defer></script>' in page


def test_ar2_the_host_renders_no_csrf_meta(lanes_project: Path) -> None:
    """Design risk 6, proved by construction: ``bw-host.js`` stamps
    ``x-csrf-token`` onto htmx requests ONLY when a ``bw-csrf-token`` meta
    exists; the host delivers its token through explicit ``hx-headers`` and
    renders no such meta — the listener is inert. The guard suite (the
    forms' own tests) pins the behaviour end to end."""
    from benchweave_sdk_server.cli import _build_seam
    from benchweave_sdk_server.web import build_app

    seam, selection = _build_seam(lanes_project)
    policy = _policy()
    app = build_app(seam, policy=policy, scenario=selection)
    with TestClient(app, base_url="http://127.0.0.1:8477") as client:
        for path in ("/", "/devices/example_device", "/pages/capture"):
            body = client.get(path).text
            assert 'name="bw-csrf-token"' not in body, path


# --- AR-4: the digest-pinned local override --------------------------------------

PREVIEW_CSS = b"/* preview override */\n.bw-lanes__label { letter-spacing: 0.04em; }\n"


@pytest.fixture(scope="module")
def override_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    project = tmp_path_factory.mktemp("override") / "override_plugin"
    return build_lanes_project(project, preview_css=PREVIEW_CSS)


@pytest.fixture(scope="module")
def override_client(override_project: Path) -> TestClient:
    return _app_client(override_project)


def test_ar4_the_declared_override_serves_after_the_token_stylesheets(
    override_client: TestClient,
) -> None:
    served = override_client.get("/assets/preview.css")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("text/css")
    assert served.content == PREVIEW_CSS
    page = override_client.get("/pages/capture").text
    assert page.index('href="/assets/preview.css"') > page.index(
        'href="/assets/globals.css"'
    ), "the override loads after the package's token stylesheets"


def test_ar4_a_tampered_override_refuses_and_the_page_renders_default_tokens(
    override_project: Path, override_client: TestClient
) -> None:
    """The manifest's digest discipline re-verified at SERVE time: tampered
    bytes refuse with the machine-matchable prefix, and the page renders
    the default tokens (no override link)."""
    css_path = override_project / "src" / "example_plugin" / "ui" / "preview.css"
    css_path.write_bytes(b"/* tampered */\n")
    try:
        served = override_client.get("/assets/preview.css")
        assert served.status_code == 403
        assert served.text.startswith("standalone_preview_override_refused:")
        page = override_client.get("/pages/capture").text
        assert 'href="/assets/preview.css"' not in page, (
            "the tampered override never loads; default tokens render"
        )
        assert 'href="/assets/globals.css"' in page
    finally:
        css_path.write_bytes(PREVIEW_CSS)


def test_ar4_refused_override_is_distinct_from_undeclared_at_the_page(
    override_project: Path,
    override_client: TestClient,
    lanes_clients: list[TestClient],
) -> None:
    """Fold F3: an author iterating on a tampered override gets a VISIBLE
    signal — the page carries the ``data-bw-override-refused`` marker —
    while an undeclared-override page renders no marker. Refused ≠
    undeclared at the page surface; the direct-fetch trichotomy
    (200 verified / 403 refused / 404 undeclared) stays pinned by the
    neighbouring tests."""
    css_path = override_project / "src" / "example_plugin" / "ui" / "preview.css"
    css_path.write_bytes(b"/* tampered */\n")
    try:
        refused = override_client.get("/pages/capture").text
    finally:
        css_path.write_bytes(PREVIEW_CSS)
    undeclared = lanes_clients[0].get("/pages/capture").text
    assert "data-bw-override-refused" in refused, (
        "a refused override must be visible at the page surface"
    )
    assert "data-bw-override-refused" not in undeclared, (
        "an undeclared override renders no refusal marker"
    )


def test_ar4_an_undeclared_override_refuses(
    lanes_clients: list[TestClient],
) -> None:
    """A plugin that declares no override asset renders pure gateway
    tokens: ``preview.css`` is undeclared, so no link renders and the
    asset route refuses the path (it is not part of the host's verified
    tree)."""
    client = lanes_clients[0]
    page = client.get("/pages/capture").text
    assert 'href="/assets/preview.css"' not in page
    served = client.get("/assets/preview.css")
    assert served.status_code == 404


def test_ar4_the_override_loads_last(override_client: TestClient) -> None:
    """Fold F5 (cascade honesty): this pin is ORDER only. Link order does
    NOT make the override win: standalone.css's lanes state-kind rules sit
    at the (0,2,0) specificity floor — above a plugin's class-level
    overrides — and globals.css's reduced-motion block carries
    ``!important`` on universal selectors, an accessibility floor that is
    unreachable by the override BY DESIGN. The host grants the override
    order, not rank."""
    page = override_client.get("/pages/capture").text
    stylesheet_order = [
        match for match in re.findall(r'href="/assets/[a-z.-]+\.css"', page)
    ]
    assert stylesheet_order[-1] == 'href="/assets/preview.css"', stylesheet_order


@pytest.mark.parametrize(
    ("size", "expected_status"),
    [
        pytest.param(64 * 1024, 200, id="at-the-cap-serves"),
        pytest.param(64 * 1024 + 1, 403, id="one-byte-over-refuses"),
    ],
)
def test_ar4_the_override_size_cap_boundary_is_exact(
    tmp_path: Path, size: int, expected_status: int
) -> None:
    """Fold F4: the cap boundary is EXACT — 65536 bytes serve
    byte-identical; 65537 refuse with the cap message. The cap is a
    serve-time bound (the load-time reader caps at 16 MiB per asset; this
    surface refuses above 64 KiB)."""
    css = (b"/* cap probe */\n" + b"x" * size)[:size]
    project = tmp_path / f"cap_plugin_{size}"
    build_lanes_project(project, preview_css=css)
    client = _app_client(project)
    served = client.get("/assets/preview.css")
    assert served.status_code == expected_status, served.text[:120]
    if expected_status == 200:
        assert served.content == css, "at-cap bytes serve byte-identical"
    else:
        assert served.text.startswith("standalone_preview_override_refused:")
        assert "exceeds the 64 KiB cap" in served.text


# --- §3.1.6: the host's lanes component CSS (§E.4 constraints) --------------------


def test_the_lanes_css_realizes_state_kinds_in_geometry_with_token_colours() -> None:
    """Monochrome-discriminable state kinds (geometry, never colour-only),
    token-referenced colours (``var(--bw-*)`` — no colour literals), and no
    glow on normal readings."""
    css = (UI_ASSETS / "standalone.css").read_text(encoding="utf-8")
    block = css[css.index("/* The digital-lanes figure") :]
    # Colour literals and glow live in CSS values; the comment block is
    # prose (its "#449" is an issue number, not a colour) and is stripped
    # before the value checks.
    values = re.sub(r"/\*.*?\*/", "", block, flags=re.DOTALL)

    for kind in ("high", "low", "hatch", "midline"):
        assert f'data-bw-state-kind="{kind}"' in values, kind
    assert "data-bw-glitch" in values, "the glitch mark has its own geometry"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", values), "no colour literals"
    assert "box-shadow" not in values, "no glow on normal readings"


def test_the_lanes_css_stays_at_the_specificity_floor() -> None:
    """Fold F5: every lanes rule stays at or below the (0,2,0)
    specificity floor — zero id selectors, at most two class/attribute
    tokens per selector (type tokens cannot outrank a lower-b tuple, so
    (0,1,1) is inside the floor). The host grants the plugin override
    order, not rank: the state-kind geometry keeps its floor regardless
    of where the override link sits."""
    css = (UI_ASSETS / "standalone.css").read_text(encoding="utf-8")
    block = css[css.index("/* The digital-lanes figure") :]
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.DOTALL)
    for rule in block.split("}"):
        selector = rule.split("{")[0].strip()
        if not selector:
            continue
        for single in selector.split(","):
            single = single.strip()
            if not single:
                continue
            specificity = (
                single.count("#"),
                len(re.findall(r"\.", single)) + len(re.findall(r"\[", single)),
                len(re.findall(r"::", single)),
            )
            assert specificity <= (0, 2, 0), (
                f"{single!r} exceeds the (0,2,0) lanes specificity floor"
            )


# --- the AR-3 RED control is a REPORT-level proof (cp-backup revert of
# --- plots.py) and lives in the run report, not the suite.
