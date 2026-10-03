"""The parity suite (NFR-Q2, oracle re-derived — I2a §3.4, gate I2-P).

For each of the nine baseline scenarios the app is built on a freshly
scaffolded ``--with-ui`` project through ``--scenario <id>`` (#309-B's
mechanism), connected, and asserted over HTTP and over
``POST /v1/parameter_read``:

1. **Component parity** — the page contains the EXACT ``render_reading``
   output built from the scenario's own read (value/unit/quality through
   the pinned map). Exact-substring containment: a host hand-rolling a
   tile cannot pass.
2. **Severity parity** — the page's composed severity equals
   ``generate_baselines``' ``expected_severity`` for the scenario (the
   SDK's baseline rows are the surviving oracle; the stale scenario
   asserts the quality-slot string and the advisory severity;
   disconnected asserts the refused-state render; request-rejected
   asserts the refusal carrying the adapter's code verbatim — SW-12).
3. **Mode parity** — the §D.1 banner entries per transport (simulated
   present on mock, asserted absent on the non-mock recording double).
4. **No-write-on-load** — the verb recorder over the new page set:
   full load + poll cycle ⇒ verbs ⊆ {identify, read}.

The RED controls (the fluff-killers) sit at the end: the bypass-tile
control and the quality-corrupt control must make arms 1 and 2 RED when
their mechanisms are sabotaged — a green control is a KILL (the suite
cannot discriminate). The ST-2 boundary pair lives in
``test_presentation_pages.py`` (the live boundary arms) and the
doctored-template control in the axe lane.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk.fixtures import generate_baselines
from benchweave_sdk_server import presentation as host_presentation
from benchweave_sdk_server.cli import _build_seam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.web import build_app

DEV = "example_device"
NO_GATEWAY = "NO GATEWAY · LOCAL PRESENTATION ONLY"
SIMULATED_WORDING = "SIMULATED PRESENTATION DATA"

#: The nine baseline ids in ``SCENARIOS`` order (the parity driver).
ALL_SCENARIOS = (
    "normal",
    "loading",
    "stale",
    "disconnected",
    "warning",
    "critical",
    "trip",
    "recovery",
    "request-rejected",
)


def _policy() -> GuardPolicy:
    return GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )


@pytest.fixture(scope="module")
def starter(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One ``--with-ui`` scaffold per module: the nine apps vary only in
    their scenario selection (#309-B's mechanism — the selection arms the
    mock factory's next-connection script)."""
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    project = tmp_path_factory.mktemp("parity") / "starter"
    create_project(project, "example_plugin")
    create_ui_resources(project, "example_plugin")
    return project


@pytest.fixture()
def scenario_app(starter: Path, request) -> Iterator[tuple[TestClient, GuardPolicy, str]]:
    scenario_id = getattr(request, "param", "normal")
    seam, _ = _build_seam(starter, scenario=scenario_id)
    policy = _policy()
    client = TestClient(build_app(seam, policy=policy), base_url="http://127.0.0.1:8477")
    with client:
        yield client, policy, scenario_id


def _connect(client: TestClient) -> None:
    body = client.get(f"/devices/{DEV}").text
    marker = 'hx-headers=\'{"X-CSRF-Token": "'
    token = body.split(marker, 1)[1].split('"', 1)[0]
    client.post(f"/devices/{DEV}/connect", headers={"x-csrf-token": token})


def _starter_of(client: TestClient) -> Path:
    """The scenario app's scaffold root (the loaded plugin's project)."""
    return client.app.state.seam.session.plugin.project_root


def _expected_severities(starter: Path) -> dict[str, str]:
    """``generate_baselines``' own rows — the surviving oracle."""
    from benchweave_sdk_server.presentation import load_host_presentation
    from benchweave_sdk_server.session import load_plugin_project

    plugin = load_plugin_project(starter)
    model = load_host_presentation(plugin)
    return {
        row.id: row.expected_severity
        for row in generate_baselines(model.binding_catalogue, model.manifest)
    }


def _expected_tile(data: dict) -> str:
    """The exact partial output the page must contain, built from the LIVE
    read through the design's rules (independent of the host's render)."""
    from benchweave_ui_html.data import ReadingData
    from benchweave_ui_html.partials import render_reading

    value = data["value"]
    if value is None:
        text = "—"
    elif value is True:
        text = "true"
    elif value is False:
        text = "false"
    else:
        text = str(value)
    return render_reading(
        ReadingData(
            label="voltage",
            severity=host_presentation.QUALITY_SEVERITY[data["quality"]],
            value=text,
            unit=str(data.get("unit") or "V"),
            quality=data["quality"],
            freshness=f"{float(data['age_ms']):g} ms",
            stale_verdict="fresh",
        )
    )


# --- 1 + 2: component and severity parity, per scenario ------------------------


@pytest.mark.parametrize("scenario_app", ALL_SCENARIOS, indirect=True)
def test_component_and_severity_parity(scenario_app, starter: Path) -> None:
    client, policy, scenario_id = scenario_app
    _connect(client)
    page = client.get("/pages/readings")
    assert page.status_code == 200
    body = page.text
    expected = _expected_severities(starter)

    if scenario_id in ("disconnected",):
        # Through the pipeline, disconnected IS a refused connection: the
        # page renders the refused state and composes critical.
        assert "Readings refused" in body
        assert "not_ready" in body
        assert f'data-bw-page-severity="{expected[scenario_id]}"' in body
        return
    if scenario_id in ("request-rejected",):
        # The refusal carries the adapter's code verbatim (SW-12) and the
        # page composes the baseline's warning.
        assert "Readings refused" in body
        assert "DEVICE_REJECTED" in body
        assert f'data-bw-page-severity="{expected[scenario_id]}"' in body
        return

    read = client.post(
        "/v1/parameter_read",
        json={"device_id": DEV, "parameter": "voltage"},
        headers={"authorization": f"Bearer {policy.bearer_token}"},
    )
    assert read.status_code == 200
    data = read.json()["data"]
    # HTML and REST arms assert equal values (the tile shows the read).
    assert _expected_tile(data) in body, scenario_id
    quality = data["quality"]
    assert quality in body
    assert f'data-bw-page-severity="{expected[scenario_id]}"' in body
    if scenario_id == "loading":
        assert data["value"] is None
        assert "—" in body


@pytest.mark.parametrize("scenario_app", ["normal", "stale"], indirect=True)
def test_the_quality_slot_carries_the_device_string_verbatim(scenario_app) -> None:
    """ST-3's two channels: the device's own quality string rides the slot
    verbatim (never laundered into the computed verdict)."""
    client, _, scenario_id = scenario_app
    _connect(client)
    body = client.get("/pages/readings").text
    quality = "valid" if scenario_id == "normal" else "stale"
    assert f">{quality} · " in body


# --- 3: mode parity ------------------------------------------------------------


@pytest.mark.parametrize("scenario_app", ["normal", "request-rejected"], indirect=True)
def test_scenario_pages_carry_the_mock_mode_entries(scenario_app) -> None:
    """Scenario mode implies mock: the simulated entry renders beside the
    three standalone truths on every page."""
    client, _, _ = scenario_app
    for page in ("/", f"/devices/{DEV}", "/pages/readings"):
        body = client.get(page).text
        assert SIMULATED_WORDING in body, page
        assert NO_GATEWAY in body, page


def test_a_non_mock_transport_omits_the_simulated_entry(starter: Path) -> None:
    """#309-B's discrimination arm carried into the suite: over a transport
    kind the banner rule treats as real, the simulated entry is asserted
    ABSENT (the mechanism, not the metal — I3 exercises real hardware)."""
    from benchweave_sdk_server.seam import StandaloneSeam
    from benchweave_sdk_server.session import PluginSession, load_plugin_project, mock_exchanges
    from benchweave_sdk_server.transport import LoopingMockHost

    plugin = load_plugin_project(starter)
    seam = StandaloneSeam(
        PluginSession(plugin, lambda: LoopingMockHost(mock_exchanges(plugin))),
        transport_kind="recording",
    )
    policy = _policy()
    with TestClient(
        build_app(seam, policy=policy), base_url="http://127.0.0.1:8477"
    ) as client:
        for page in ("/", "/pages/readings"):
            body = client.get(page).text
            assert NO_GATEWAY in body
            assert SIMULATED_WORDING not in body
            assert 'data-bw-mode="simulated"' not in body


# --- 4: no-write on load, re-proven over the new page set ----------------------


class VerbRecorder:
    """Test-only adapter wrapper: records every ``execute()`` verb."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.verbs: list[str] = []

    async def open(self, descriptor, services, context) -> None:
        await self._inner.open(descriptor, services, context)

    async def execute(self, request, context):
        self.verbs.append(str(request.get("verb")))
        return await self._inner.execute(request, context)

    async def next_event(self, subscription_id, context):
        return await self._inner.next_event(subscription_id, context)

    async def close(self, context) -> None:
        await self._inner.close(context)


def _exercise_the_page_set(client: TestClient, policy: GuardPolicy) -> None:
    """One full load (index, device page, every manifest page) then three
    poll cycles of each page's partial."""
    _connect(client)
    client.get("/")
    client.get(f"/devices/{DEV}")
    client.get("/pages/readings")
    for _ in range(3):
        client.get("/pages/readings/readings")


def test_no_write_on_load_over_the_new_page_set(starter: Path) -> None:
    """NFR-O3 re-proven where the reads now happen (the manifest pages):
    the recorder wraps the host-shipped scenario adapter over the looping
    mock transport — the author's adapter is never imported in scenario
    mode, and the proof covers the full new page set."""
    from dataclasses import replace

    from benchweave_sdk_server.scenarios import (
        ScenarioAdapter,
        ScenarioSelection,
        scenario_exchanges,
    )
    from benchweave_sdk_server.seam import StandaloneSeam
    from benchweave_sdk_server.session import PluginSession, load_plugin_project
    from benchweave_sdk_server.transport import LoopingMockHost

    plugin = load_plugin_project(starter)
    recorder = VerbRecorder(ScenarioAdapter())
    selection = ScenarioSelection("normal")
    identify_declared = "identify" in plugin.descriptor.get("capabilities", [])
    seam = StandaloneSeam(
        PluginSession(
            replace(plugin, adapter_factory=lambda: recorder, load_diagnostic=None),
            lambda: LoopingMockHost(
                scenario_exchanges(plugin, selection.current),
                establishment=1 if identify_declared else 0,
            ),
        ),
        transport_kind="mock",
    )
    policy = _policy()
    with TestClient(
        build_app(seam, policy=policy), base_url="http://127.0.0.1:8477"
    ) as client:
        _exercise_the_page_set(client, policy)
    assert set(recorder.verbs) == {"identify", "read"}, recorder.verbs


def test_the_deaf_recorder_control_hears_a_driven_verb(starter: Path) -> None:
    """The instrument control: a verb driven through the recorder IS
    recorded — a deaf recorder passes everything, and this control kills
    that false pass."""
    import asyncio
    import json

    # The write verb must be DECLARED (an undeclared verb refuses with
    # standalone_verb_unbounded before the adapter is ever reached) — on a
    # COPY, so the shared starter's digests stay pinned for the suite.
    import shutil
    from dataclasses import replace

    from benchweave_sdk_server.scenarios import (
        ScenarioAdapter,
        ScenarioSelection,
        scenario_exchanges,
    )
    from benchweave_sdk_server.session import PluginSession, load_plugin_project
    from benchweave_sdk_server.transport import LoopingMockHost

    writable = starter.parent / "writable"
    if not writable.exists():
        shutil.copytree(starter, writable)
    descriptor_path = writable / "src" / "example_plugin" / "descriptor.json"
    document = json.loads(descriptor_path.read_text())
    document["capabilities"].append("write")
    document["operations"]["write"] = dict(document["operations"]["read"])
    import hashlib

    raw = (json.dumps(document, indent=2) + "\n").encode()
    descriptor_path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    package = writable / "src" / "example_plugin"
    for name in (
        "ui/manifest.json",
        "presentation.json",
        "binding-catalogue.json",
    ):
        path = package / name
        row = json.loads(path.read_text())
        row["descriptor_sha256"] = digest
        row_raw = (json.dumps(row, indent=2) + "\n").encode()
        path.write_bytes(row_raw)
        if name == "ui/manifest.json":
            envelope_path = package / "presentation.json"
            envelope = json.loads(envelope_path.read_text())
            envelope["manifest"]["sha256"] = hashlib.sha256(row_raw).hexdigest()
            envelope_path.write_text(json.dumps(envelope, indent=2) + "\n")
    plugin = load_plugin_project(writable)
    recorder = VerbRecorder(ScenarioAdapter())
    selection = ScenarioSelection("normal")
    identify_declared = "identify" in plugin.descriptor.get("capabilities", [])
    session = PluginSession(
        replace(plugin, adapter_factory=lambda: recorder, load_diagnostic=None),
        lambda: LoopingMockHost(
            scenario_exchanges(plugin, selection.current),
            establishment=1 if identify_declared else 0,
        ),
    )

    async def run() -> None:
        await session.connect()
        # The scenario adapter refuses the verb (UNSUPPORTED) — the point
        # is the recorder heard it, not that the device obeyed.
        envelope = await session.execute("write", {"parameter": "voltage", "value": 1.0})
        assert envelope["status"] == "error"
        await session.close()

    asyncio.run(run())
    assert "write" in recorder.verbs, recorder.verbs


# --- the RED controls (the fluff-killers) --------------------------------------


@pytest.mark.parametrize("scenario_app", ["normal", "warning"], indirect=True)
def test_control_bypass_tile_must_red_the_component_arm(
    scenario_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED control (a): with the host's test hook rendering the I1-era
    hand-rolled tile, the component-parity containment MUST fail — the
    suite discriminates a hand-rolled tile from the partial's exact output
    (a green control is a KILL: the suite is fluff)."""
    client, policy, scenario_id = scenario_app
    _connect(client)
    read = client.post(
        "/v1/parameter_read",
        json={"device_id": DEV, "parameter": "voltage"},
        headers={"authorization": f"Bearer {policy.bearer_token}"},
    )
    data = read.json()["data"]
    # The suite's oracle stays the partial's exact output; the HOST side
    # is sabotaged onto the I1-era hand tile.
    oracle = _expected_tile(data)
    monkeypatch.setattr(host_presentation, "PARTIAL_TILES", False)
    try:
        hand, _severity = host_presentation.reading_tile_html(
            data,
            {"name": "voltage", "unit": "V", "read_policy": {"max_age_ms": 0}},
            label="voltage",
        )
        assert "bw-reading" not in hand, "the hook must render the hand tile"
        body = client.get("/pages/readings").text
        assert hand in body, "the sabotaged host rendered the hand tile"
        # The containment the component arm asserts must now RED:
        with pytest.raises(AssertionError):
            assert oracle in body, scenario_id
    finally:
        monkeypatch.setattr(host_presentation, "PARTIAL_TILES", True)


@pytest.mark.parametrize("scenario_app", ["warning", "critical"], indirect=True)
def test_control_quality_corrupt_must_red_the_severity_arm(
    scenario_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED control (b): corrupting the quality→severity map flips the
    page's composed severity away from the baseline row — the severity
    arm must RED (the map cannot drift silently into green)."""
    client, _, scenario_id = scenario_app
    starter_dir = _starter_of(client)
    _connect(client)
    expected = _expected_severities(starter_dir)
    quality = "warning" if scenario_id == "warning" else "critical"
    truth = host_presentation.QUALITY_SEVERITY[quality]
    monkeypatch.setitem(
        host_presentation.QUALITY_SEVERITY, quality, "trip" if truth != "trip" else "critical"
    )
    try:
        corrupted = host_presentation.QUALITY_SEVERITY[quality]
        assert corrupted != expected[scenario_id]
        with pytest.raises(AssertionError):
            body = client.get("/pages/readings").text
            assert f'data-bw-page-severity="{expected[scenario_id]}"' in body
    finally:
        monkeypatch.setitem(host_presentation.QUALITY_SEVERITY, quality, truth)
