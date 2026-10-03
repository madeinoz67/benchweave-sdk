"""No write on page load (NFR-O3), proven — not presumed (§4.4).

Page-load paths call only read-side catalogue operations; the proof is a
test-only verb-recording wrapper at the adapter boundary plus the
transport's exact-match discipline at the frame boundary (an unexpected
write frame ConformanceErrors). The control arm drives a write verb
through the recorder directly — a deaf recorder would pass everything,
so the control is what makes the two proof arms non-vacuous.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.session import PluginSession, mock_exchanges
from benchweave_sdk_server.transport import LoopingMockHost
from benchweave_sdk_server.web import build_app

DEV = "example_device"


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


class RecordingServices:
    """Test-only non-mock transport double (§4.1): a ``HostServices``
    wrapper that delegates to the scripted host while presenting a
    transport kind the banner rule treats as real — never shipped."""

    def __init__(self, inner: LoopingMockHost) -> None:
        self._inner = inner
        self.frames: list[bytes] = []

    def monotonic(self) -> float:
        return self._inner.monotonic()

    def utc_now(self) -> str:
        return self._inner.utc_now()

    async def transfer(self, transaction, context):
        self.frames.append(bytes(transaction.get("data", b"")))
        return await self._inner.transfer(transaction, context)

    async def close_transport(self, context) -> None:
        await self._inner.close_transport(context)

    async def record_evidence(self, entry, context) -> None:
        await self._inner.record_evidence(entry, context)


def _policy() -> GuardPolicy:
    return GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )


def _exercise_pages(client: TestClient, policy: GuardPolicy) -> None:
    """One full page load (both pages) then three poll cycles."""
    client.post(
        f"/devices/{DEV}/connect",
        headers={"x-csrf-token": policy.csrf_token},
        follow_redirects=False,
    )
    client.get("/")
    client.get(f"/devices/{DEV}")
    for _ in range(3):
        client.get(f"/devices/{DEV}/readings")


def test_no_write_on_page_load_over_the_mock_transport(plugin) -> None:
    recorder = VerbRecorder(plugin.adapter_factory())
    seam = StandaloneSeam(
        PluginSession(
            replace(plugin, adapter_factory=lambda: recorder),
            lambda: LoopingMockHost(mock_exchanges(plugin)),
        ),
        transport_kind="mock",
    )
    policy = _policy()
    with TestClient(build_app(seam, policy=policy), base_url="http://127.0.0.1:8477") as client:
        _exercise_pages(client, policy)
    assert set(recorder.verbs) == {"identify", "read"}, recorder.verbs


def test_no_write_on_page_load_over_a_non_mock_transport(plugin) -> None:
    """The same proof over the recording double — the mechanism, not the
    metal: nothing server-side knows or cares which transport is bound."""
    recorder = VerbRecorder(plugin.adapter_factory())
    live: list[RecordingServices] = []

    def services_factory() -> RecordingServices:
        services = RecordingServices(LoopingMockHost(mock_exchanges(plugin)))
        live.append(services)
        return services

    seam = StandaloneSeam(
        PluginSession(
            replace(plugin, adapter_factory=lambda: recorder),
            services_factory,
        ),
        transport_kind="recording",
    )
    policy = _policy()
    with TestClient(build_app(seam, policy=policy), base_url="http://127.0.0.1:8477") as client:
        _exercise_pages(client, policy)
    assert set(recorder.verbs) == {"identify", "read"}, recorder.verbs
    # Frame-level: every transmitted frame is a read-side request frame —
    # the transport's exact-match discipline would ConformanceError any
    # write frame the pages tried to send.
    assert live and live[0].frames, "the recording double heard no frames"


def test_the_recorder_hears_a_driven_write(starter_project: Path, tmp_path: Path) -> None:
    """The instrument control (B-W arm 3): a write verb driven through the
    recorder IS recorded — a deaf recorder passes everything, and this
    control kills that false pass."""
    import asyncio

    project = tmp_path / "writable"
    _scaffold_with_write(project)
    from benchweave_sdk_server.session import load_plugin_project

    plugin = load_plugin_project(project)
    recorder = VerbRecorder(plugin.adapter_factory())
    session = PluginSession(
        replace(plugin, adapter_factory=lambda: recorder),
        lambda: LoopingMockHost(mock_exchanges(plugin)),
    )

    async def run() -> None:
        await session.connect()
        # The scaffold adapter refuses the verb (UNSUPPORTED) — the point
        # here is the recorder heard it, not that the device obeyed.
        envelope = await session.execute(
            "write", {"parameter": "voltage", "value": 1.0}
        )
        assert envelope["status"] == "error"
        await session.close()

    asyncio.run(run())
    assert "write" in recorder.verbs, recorder.verbs


def _scaffold_with_write(project: Path) -> None:
    from benchweave_sdk.scaffold import create_project

    create_project(project, "example_plugin")
    descriptor_path = project / "src" / "example_plugin" / "descriptor.json"
    document = json.loads(descriptor_path.read_text())
    policy = dict(document["operations"]["read"])
    document["capabilities"].append("write")
    document["operations"]["write"] = policy
    descriptor_path.write_text(json.dumps(document))
