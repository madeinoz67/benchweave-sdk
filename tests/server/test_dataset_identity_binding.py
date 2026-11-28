# author: Stephen Eaton
"""SDK dataset identity binding (issue #606, ADR 0606): the explicit
publisher is bound to the ACTIVE host invoke.

Before the binding, ``dataset_publish`` read its admission identity from the
caller's own context object (``context.dataset_id``, a plain mutable
attribute) and its correlation from the dispatch RECORD. So an adapter chose
the id its manifest was filed under, and could claim another operation's
mint. These arms run the EXPLICIT publisher through the normal invoke path
with an adapter that does what the issue describes. The refusal prefixes are
the contract (STD-4).

The arms, by ADR 0606 "Verification and tasks":

- T1 — same-seam serialization through the public invoke and preset-apply
  paths (the per-seam mutex is preserved).
- T2 — two admission scopes open at once on ONE controller, each seeing
  only its own mint.
- T3 — the explicit publisher's control and its refusals.
- T4 — every refusal leaves admission state byte-identical.
- T5 — inline publication and ``dataset_lookup``: their existing arms in
  ``tests/server/test_dataset_admission.py`` stay green and byte-unchanged.
  Nothing here edits them; ``test_a1`` (inline) and ``test_a18`` (lookup)
  are the named arms.

Fold wave 1 — three findings from the review of `426d269`, each proved RED
there first. F1: the inline path ran its M10 echo check against the
dispatched input OBJECT, which the adapter can mutate in place. F2: the
scope closer read ``context.operation_id`` late, so a rewrite of that
attribute kept a scope alive after its invoke closed. F3: the capture fell
back to the caller's live object for any input that is not JSON data. The
``test_fold_...`` arms enforce that both admission paths read one captured
value per dispatch, that the closer closes on the operation id captured
before the adapter ran, and that with no record, or no captured input,
admission refuses and never falls back to a caller's object.

Nine arms pass on the tree before the binding. They are pins and controls,
not proofs, and each says so in its docstring: T1 (the mutex predates the
binding; it is alive because removing the mutex turns it red), the
explicit-publisher control, the inline-result pin, publish-then-raise, the
T4 snapshot control, a nested-dispatch pin and a record_dispatch pin. A pin
guards behaviour; it is never RED-then-GREEN evidence.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import sys
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from benchweave_sdk.scaffold import create_project
from benchweave_sdk_server import session as session_module
from benchweave_sdk_server.dataset_admission import (
    DatasetAdmission,
    attach_dataset_members,
)
from benchweave_sdk_server.errors import SeamError
from benchweave_sdk_server.invoke_contracts import resolve_invoke_contracts
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.session import (
    HostOperationContext,
    load_plugin_project,
    mock_plugin_session,
)

REPO = Path(__file__).resolve().parents[2]
VENDORED = REPO / "src" / "benchweave_sdk" / "standards" / "otdp" / "0.2.4"
ADAPTER = (REPO / "tests" / "server" / "fixtures" / "dataset_identity_adapter.py").read_bytes()
PACKAGE = "example_plugin"
DEV = "example_device"
PROBE = "demo.probe/1.0.0"
CORRELATED = "demo.correlated_fetch/1.0.0"
#: The corpus's own configure action — corpus vocabulary, not a device name.
CONFIGURE = "otdp.logic_analyser.configure/1.0.0"
INPUT_ID = "urn:otdp:action:logic_analyser.configure:1.0.0:input"
PRESET_ID = "fast-capture"

#: An operation id, and its dataset id, that no dispatch ever minted.
NEVER_OP = "op-never0001"
NEVER = f"ds:{NEVER_OP}"
#: The dataset id the rewriting adapter claims.
FORGED = "ds:op-forged01"

#: Every wait is bounded, so a hung arm arrives as a red arm that names the
#: hang, never as a CI-ceiling cancellation that reads as infrastructure.
WAIT = 5.0

#: The four refusal prefixes of the binding, as the adapter records them.
ID_MISMATCH = "refused: standalone_dataset_id_mismatch:"
OPERATION_MISMATCH = "refused: standalone_dataset_operation_mismatch:"
INVOKE_CLOSED = "refused: standalone_dataset_invoke_closed:"
NOT_DISPATCHED = "refused: standalone_dataset_not_dispatched:"

#: How each exit class of a dispatch shows at the public seam.
EXIT_SEEN = {
    "success": "returned",
    "error": "seam_error:internal_error",
    "cancel": "cancelled",
}
EXIT_CLASSES = ("success", "error", "cancel")
CALLERS = ("saved", "orphan")

# --- the projects ------------------------------------------------------------

SETTINGS = {
    "configuration_id": "fast-capture",
    "channels": [{"channel": "bank_a", "threshold_v": 1.65}],
    "sample_rate_hz": 12_500_000.0,
    "sample_count": 65_536,
    "trigger": {"kind": "immediate"},
}


def _raw(document: object) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


@pytest.fixture(scope="module")
def identity_project(invoke_project_builder, tmp_path_factory) -> Path:
    """The synthetic invoke project with the identity adapter. The
    correlated-fetch action is declared too, so one project serves every
    invoke arm. Built once: the scaffold is the cost, a load is not."""
    project = invoke_project_builder(
        tmp_path_factory.mktemp("identity") / "proj", catalog_with_correlated_fetch=True
    )
    (project / "src" / PACKAGE / "adapter.py").write_bytes(ADAPTER)
    return project


@pytest.fixture(scope="module")
def action_lane_project(tmp_path_factory) -> Path:
    """A plugin whose commissioned preset rides the ACTION lane: its
    settings schema pins the corpus configure action's input schema, so the
    public ``preset_apply`` dispatches an invoke through the lock-free core.
    The config home alone is enough for the lane resolver (the
    ``test_preset_homes`` fixture's shape, without its presentation)."""
    destination = tmp_path_factory.mktemp("action-lane") / "proj"
    create_project(destination, PACKAGE)
    package = destination / "src" / PACKAGE
    catalog_bytes = (VENDORED / "device-profile-catalog.json").read_bytes()
    measurement_bytes = (VENDORED / "otdp-measurement.schema.json").read_bytes()
    (package / "profile-catalog.json").write_bytes(catalog_bytes)
    (package / "measurement.json").write_bytes(measurement_bytes)
    descriptor = json.loads((package / "descriptor.json").read_text())
    # Commissioned firmware policy: the preset lists the firmware, and the
    # descriptor carries no list of its own.
    descriptor["identity"]["firmware_policy"] = "commissioned"
    descriptor["identity"].pop("supported_firmware", None)
    descriptor["capabilities"] = ["identify", "invoke"]
    descriptor["operations"].pop("read", None)
    descriptor["operations"]["invoke"] = {
        "timeout_ms": 30000,
        "side_effect": "none",
        "retry": "never",
        "cancellable": True,
        "completion": "acknowledged",
    }
    descriptor["required_features"] = sorted(
        set(descriptor.get("required_features", []))
        | {
            "otdp.profile_actions/0.1.0",
            "otdp.measurement/0.1.0",
            "otdp.logic_analyser/1.0.0",
        }
    )
    descriptor["profiles"] = ["otdp.logic_analyser/1.0.0"]
    descriptor["channels"] = [
        {
            "id": "bank_a",
            "label": "Bank A",
            "role": "digital_input",
            "quantities": ["digital"],
            "parameter_names": [],
        }
    ]
    descriptor["actions"] = {
        CONFIGURE: {
            "binding": {"kind": "adapter", "key": CONFIGURE},
            "input_constraints": {},
            "timeout_ms": 30000,
            "side_effect": "state_change",
            "cancellable": True,
            "retry": "never",
        }
    }
    descriptor["contracts"] = [
        {
            "id": "urn:otdp:profile-catalog:0.2.4",
            "path": "profile-catalog.json",
            "sha256": hashlib.sha256(catalog_bytes).hexdigest(),
        },
        {
            "id": "urn:otdp:measurement:0.2.4",
            "path": "measurement.json",
            "sha256": hashlib.sha256(measurement_bytes).hexdigest(),
        },
    ]
    (package / "descriptor.json").write_bytes(_raw(descriptor))
    (package / "adapter.py").write_bytes(ADAPTER)
    catalog = json.loads(catalog_bytes)
    schema_bytes = _raw(catalog["actions"][CONFIGURE]["input_schema"])
    (package / "config" / "presets").mkdir(parents=True)
    (package / "config" / "settings.schema.json").write_bytes(schema_bytes)
    (package / "config" / "presets" / f"{PRESET_ID}.json").write_bytes(
        _raw(
            {
                "contract_version": "0.4.0",
                "id": PRESET_ID,
                "title": "Fast capture",
                "revision": "1",
                "plugin_id": descriptor["id"],
                "profile_ids": ["otdp.logic_analyser/1.0.0"],
                "supported_firmware": ["1.0.0"],
                "settings_schema": {
                    "id": INPUT_ID,
                    "sha256": hashlib.sha256(schema_bytes).hexdigest(),
                },
                "settings": SETTINGS,
                "provenance": {
                    "author": "synthetic fixture",
                    "revision": "1",
                    "evidence": "synthetic",
                },
            }
        )
    )
    return destination


# --- helpers -----------------------------------------------------------------


def _manifest(**overrides: Any) -> dict[str, Any]:
    """A schema-valid inline measurement manifest (the
    ``test_dataset_admission`` template); a publication fills
    ``dataset_id``."""
    manifest: dict[str, Any] = {
        "kind": "scalar_set",
        "configuration_id": None,
        "acquisition_id": None,
        "started_at": None,
        "clock": {
            "domain_id": "host",
            "timestamp_source": "host",
            "synchronisation": "unknown",
            "uncertainty_s": None,
        },
        "axes": [],
        "variables": [
            {
                "id": "reading",
                "quantity": "voltage",
                "unit": "V",
                "channel_ids": [],
                "dtype": "float64",
                "dimensions": [],
                "values": [1.5],
                "uncertainty": {"status": "not_applicable"},
                "calibration": {"status": "unknown"},
                "status": "valid",
            }
        ],
        "trigger": {"source": "immediate", "time_relative_s": None},
        "status": "complete",
        "context": {},
    }
    manifest.update(overrides)
    return manifest


def invoke_args(action_id: str, value: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"device_id": DEV, "action_id": action_id, "input": value or {}}


def call(seam: StandaloneSeam, operation: str, arguments: dict[str, Any] | None = None) -> Any:
    return asyncio.run(seam.call(operation, arguments or {}))


def _load(project: Path, capture_root: Path) -> tuple[StandaloneSeam, Any]:
    """Load the shared project and build a connected seam over it. The
    project's module stays cached between loads, so every knob is reset
    here; write the plans after the last load."""
    plugin = load_plugin_project(Path(project))
    adapter = sys.modules[f"{plugin.package}.adapter"]
    adapter.reset()
    adapter.MANIFEST.clear()
    adapter.MANIFEST.update(_manifest())
    seam = StandaloneSeam(
        mock_plugin_session(plugin), transport_kind="mock", capture_root=capture_root
    )
    call(seam, "device_connect", {"device_id": DEV})
    return seam, adapter


def _publish(services: Any, dataset_id: str, context: Any) -> str:
    """One ``dataset_publish`` from a task of the test's own, outside every
    dispatch."""
    try:
        asyncio.run(services.dataset_publish(_manifest(dataset_id=dataset_id), context))
    except ValueError as exc:
        return f"refused: {exc}"
    return "admitted"


def _sole(outcomes: dict[str, dict[str, str]]) -> str:
    """The one outcome of a dispatch that made exactly one publication."""
    ((_, keys),) = outcomes.items()
    ((_, outcome),) = keys.items()
    return outcome


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _state(seam: StandaloneSeam, *controllers: DatasetAdmission) -> dict[str, Any]:
    """Admission state as plain data: each controller's this-run registry,
    every file under the capture root (the persisted manifests and sidecars,
    the library index and its lock), and the library's dataset rows.

    A file's key is its path under the root in POSIX form (``a/b.json``) on
    every platform. ``str()`` of a relative path gives ``a\\b.json`` on
    Windows, and the arms compare these keys with forward-slash literals."""
    admissions = [seam._dataset_admission, *controllers]
    assert all(admission is not None for admission in admissions), "the lane is armed"
    library = seam._capture_library
    root = Path(seam._capture_root)
    files: dict[str, str] = {}
    if root.is_dir():
        files = {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }
    return {
        "registries": [admission._admitted for admission in admissions],
        "rows": library.list_datasets() if library is not None else [],
        "files": files,
    }


def _snapshot(seam: StandaloneSeam, *controllers: DatasetAdmission) -> bytes:
    return _canonical(_state(seam, *controllers))


def _channels(plugin: Any) -> tuple[str, ...]:
    return tuple(
        str(channel.get("id"))
        for channel in plugin.descriptor.get("channels", [])
        if isinstance(channel, dict)
    )


class _CannedUuid:
    """A stand-in for the ``uuid`` module as ``session`` sees it: each
    operation id minted by ``PluginSession.execute`` consumes the next value."""

    def __init__(self, *hexes: str) -> None:
        self._hexes = iter(hexes)

    def uuid4(self) -> SimpleNamespace:
        return SimpleNamespace(hex=next(self._hexes))


# --- T1: same-seam serialization through the public paths ---------------------


def _public_call(seam: StandaloneSeam, operation: str, label: str) -> Any:
    """One public call on the action-lane project: the preset's apply, or a
    direct invoke of the same action under a label of its own."""
    if operation == "preset_apply":
        return seam.call("preset_apply", {"device_id": DEV, "preset_id": PRESET_ID})
    configuration = {**SETTINGS, "configuration_id": f"{label}-invoke"}
    return seam.call("invoke", invoke_args(CONFIGURE, configuration))


def _dispatched_id(operation: str, label: str) -> str:
    """The ``configuration_id`` the adapter sees for one public call: the
    preset's own, or the label the direct invoke carries."""
    return "fast-capture" if operation == "preset_apply" else f"{label}-invoke"


def _result_id(operation: str, result: dict[str, Any]) -> Any:
    """The ``configuration_id`` one public call's own result carries."""
    if operation == "preset_apply":
        return result["invoke_result"]["result"]["configuration_id"]
    return result["result"]["configuration_id"]


async def _two_public_calls(seam: StandaloneSeam, adapter: Any, first: str, second: str):
    entered, release = adapter.gate("gate")
    adapter.PLANS.append([("hold", "gate"), ("echo_configuration",)])
    tasks = [
        asyncio.create_task(_public_call(seam, operation, label))
        for label, operation in enumerate((first, second))
    ]
    await asyncio.wait_for(entered.wait(), WAIT)
    # Let the second public call run until it blocks.
    for _ in range(20):
        await asyncio.sleep(0)
    while_held = (
        [entry["input"]["configuration_id"] for entry in adapter.ENTRIES],
        tasks[1].done(),
    )
    release.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), WAIT)
    entries = [entry["input"]["configuration_id"] for entry in adapter.ENTRIES]
    return while_held, results, entries


@pytest.mark.parametrize(
    ("first", "second"),
    [("invoke", "invoke"), ("preset_apply", "invoke"), ("invoke", "preset_apply")],
)
def test_t1_a_second_public_invoke_waits_for_the_first(
    action_lane_project: Path, tmp_path: Path, first: str, second: str
) -> None:
    """The first public call holds the adapter. The second must not reach
    the adapter until the first releases the seam, and must then run
    second. Both public paths that dispatch an invoke are covered: a direct
    invoke, and a preset apply whose settings are the configure action's
    input.

    A pin, green before the binding: the mutex is older than this change.
    It stays a live guard — with the mutex removed from either path, the
    cells that use that path go red — but it is no evidence for the
    binding."""
    seam, adapter = _load(action_lane_project, tmp_path / "captures")
    (held, second_done), results, entries = asyncio.run(
        asyncio.wait_for(_two_public_calls(seam, adapter, first, second), WAIT)
    )
    order = [_dispatched_id(first, "0"), _dispatched_id(second, "1")]
    assert second_done is False, "the second call finished while the first held the seam"
    assert held == order[:1], f"only the first call may reach the adapter: {held}"
    assert entries == order, entries
    assert [_result_id(first, results[0]), _result_id(second, results[1])] == order, results


# --- T2: two scopes open at once on ONE controller ----------------------------


def test_t2_overlapping_admission_scopes_each_see_only_their_own_mint(
    identity_project: Path, tmp_path: Path
) -> None:
    """The binding must be dispatch-local. The seam mutex serializes PUBLIC
    dispatches, so this arm calls the LOCK-FREE invoke core from two tasks:
    the only way to hold two scopes open on one controller at once, and the
    question a last-dispatch slot answers wrongly. Each adapter publishes
    under its own mint, then rewrites its context to the OTHER operation's
    mint and publishes a manifest that carries it."""
    seam, adapter = _load(identity_project, tmp_path / "captures")
    adapter.PLANS.append(
        [
            ("remember",),
            ("barrier", 2),
            ("publish", "own", "context", "own"),
            ("publish_cross",),
        ]
    )

    async def overlap() -> None:
        await asyncio.wait_for(
            asyncio.gather(
                seam._invoke_core(invoke_args(PROBE, {"party": "a"}), "t2-a"),
                seam._invoke_core(invoke_args(PROBE, {"party": "b"}), "t2-b"),
            ),
            WAIT,
        )

    asyncio.run(overlap())
    mints = {operation: context.dataset_id for operation, context in adapter.CONTEXTS.items()}
    assert len(mints) == 2, "both dispatches stood at the barrier at once"
    cross = {operation: keys["cross"] for operation, keys in adapter.OUTCOMES.items()}
    assert all(outcome.startswith(ID_MISMATCH) for outcome in cross.values()), (
        f"a scope published under the other scope's mint: {adapter.OUTCOMES}"
    )
    assert {operation: keys["own"] for operation, keys in adapter.OUTCOMES.items()} == {
        operation: "admitted" for operation in mints
    }, adapter.OUTCOMES
    assert [row["dataset_id"] for row in call(seam, "capture_list")["datasets"]] == sorted(
        mints.values()
    ), "only the two own mints are admitted"
    admission = seam._dataset_admission
    assert admission is not None
    for dataset_id in mints.values():
        admitted = admission.admitted_manifest(dataset_id)
        assert admitted is not None and admitted["variables"][0]["values"] == [1.5], (
            "each mint holds its own operation's manifest, never the cross claim"
        )


# --- the refusal scenarios (T3 asserts the refusal, T4 the state) --------------
#
# A scenario runs on a fresh seam and answers a record. ``refusal`` is the
# refused publication's outcome. ``unchanged`` says the admission state is
# byte-identical before and after the refused call: the snapshot brackets
# that call alone, so a scenario may admit outside the bracket. One scenario
# serves both arms, and no arm runs twice inside a test.


def _rewritten_id(
    seam: StandaloneSeam, adapter: Any, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """The issue's reproduction: the adapter rewrites ``context.dataset_id``
    inside ``execute`` and publishes a valid manifest that carries it."""
    adapter.PLANS.append([("rewrite", FORGED), ("publish", "own", "context", "own")])
    before = _snapshot(seam)
    call(seam, "invoke", invoke_args(PROBE))
    return {"refusal": _sole(adapter.OUTCOMES), "unchanged": _snapshot(seam) == before}


def _another_operation(
    seam: StandaloneSeam, adapter: Any, monkeypatch: pytest.MonkeyPatch, *, recorded: bool
) -> dict[str, Any]:
    """From inside an active invoke, the adapter publishes as ANOTHER
    operation: the context of an earlier dispatch that never published (a
    past mint with a dispatch record), or a context naming an operation
    that was never dispatched."""
    if recorded:
        adapter.PLANS.extend([[("save",)], [("publish", "claim", "context", "saved")]])
    else:
        adapter.PLANS.append([("publish", "claim", NEVER, ("copy", NEVER_OP, NEVER))])
    before = _snapshot(seam)
    if recorded:
        call(seam, "invoke", invoke_args(PROBE))
    call(seam, "invoke", invoke_args(PROBE))
    if recorded:
        past = adapter.SAVED["context"]
        claimant = next(op for op in adapter.OUTCOMES if op != past.operation_id)
        refusal = adapter.OUTCOMES[claimant]["claim"]
    else:
        refusal = _sole(adapter.OUTCOMES)
    return {"refusal": refusal, "unchanged": _snapshot(seam) == before}


def _undispatched(
    seam: StandaloneSeam, adapter: Any, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """A publication for an operation this controller never dispatched: a
    context the caller built, outside every invoke."""
    before = _snapshot(seam)
    context = HostOperationContext(NEVER_OP, timeout_ms=1000, dataset_id=NEVER)
    refusal = _publish(seam.session.services, NEVER, context)
    return {"refusal": refusal, "unchanged": _snapshot(seam) == before}


def _closed_scope(
    seam: StandaloneSeam,
    adapter: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    exit_class: str,
    caller: str,
) -> dict[str, Any]:
    """A dispatch saves its context and leaves an orphan task that inherited
    its scope. It then exits by ``exit_class``. After it, the saved context
    or the released orphan publishes under the closed invoke. The orphan
    runs in its dispatch's own event loop: a loop that closes would cancel
    it before it could publish."""
    adapter.ORPHANS["late"] = [("publish", "late", "context", "own")]
    plan: list[tuple] = [("spawn", "late"), ("save",)]
    if exit_class == "error":
        plan.append(("raise", "the adapter failed"))
    elif exit_class == "cancel":
        plan.append(("hold", "span"))
    adapter.PLANS.append(plan)
    entered = adapter.gate("span")[0]

    async def dispatch() -> str:
        task = asyncio.create_task(seam.call("invoke", invoke_args(PROBE)))
        if exit_class == "cancel":
            await entered.wait()
            task.cancel()
        try:
            await task
        except SeamError as exc:
            return f"seam_error:{exc.code}"
        except asyncio.CancelledError:
            return "cancelled"
        return "returned"

    async def orphan_publishes() -> str:
        adapter.release_orphan("late")
        await asyncio.gather(*adapter.TASKS)
        return adapter.ORPHAN_OUTCOMES["late"]["late"]

    async def dispatch_then_orphan() -> tuple[str, str, bool]:
        exit_seen = await dispatch()
        # The snapshot brackets the orphan's publication alone.
        before = _snapshot(seam)
        refusal = await orphan_publishes()
        return exit_seen, refusal, _snapshot(seam) == before

    if caller == "saved":
        exit_seen = asyncio.run(asyncio.wait_for(dispatch(), WAIT))
        before = _snapshot(seam)
        saved = adapter.SAVED["context"]
        refusal = _publish(seam.session.services, saved.dataset_id, saved)
        unchanged = _snapshot(seam) == before
    else:
        exit_seen, refusal, unchanged = asyncio.run(
            asyncio.wait_for(dispatch_then_orphan(), WAIT)
        )
    return {"refusal": refusal, "unchanged": unchanged, "exit": exit_seen}


def _publish_then_raise(
    seam: StandaloneSeam, adapter: Any, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """The adapter publishes its own dataset, then fails."""
    adapter.PLANS.append(
        [
            ("publish", "inside", "context", "own"),
            ("raise", "the adapter failed after it published"),
        ]
    )
    with pytest.raises(SeamError) as caught:
        call(seam, "invoke", invoke_args(PROBE))
    ((_, keys),) = adapter.OUTCOMES.items()
    return {"exit": f"seam_error:{caught.value.code}", "inside": keys["inside"]}


def _cross_operation(
    seam: StandaloneSeam, adapter: Any, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """The issue's cross-operation consequence. The mint is pinned, so the
    forger can name the id of an operation that runs LATER: it claims
    ``ds:op-22222222``; then that operation publishes its own dataset."""
    monkeypatch.setattr(session_module, "uuid", _CannedUuid("11111111", "22222222"))
    adapter.PLANS.extend(
        [
            [("rewrite", "ds:op-22222222"), ("publish", "forged", "context", "own", 9.9)],
            [("publish", "own", "context", "own")],
        ]
    )
    # The snapshot brackets the forgery alone. The later operation's own
    # publication is a legitimate admission and follows the bracket.
    before = _snapshot(seam)
    call(seam, "invoke", invoke_args(PROBE))
    forged = adapter.OUTCOMES["op-11111111"]["forged"]
    unchanged = _snapshot(seam) == before
    call(seam, "invoke", invoke_args(PROBE))
    return {
        "refusal": forged,
        "own": adapter.OUTCOMES["op-22222222"]["own"],
        "unchanged": unchanged,
    }


def _inherited_borrows_active(
    seam: StandaloneSeam, adapter: Any, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """An orphan task that inherited a CLOSED scope publishes while a LATER
    operation is active, naming that active operation's real context. The
    active operation then publishes its own dataset. 9.9 makes the borrowed
    claim a different manifest: a host that admits it makes the active
    operation's own publication refuse as immutable."""
    adapter.ORPHANS["late"] = [("publish", "borrowed", "context", "saved", 9.9)]
    entered, release = adapter.gate("span")
    active_plan = [("save",), ("hold", "span"), ("publish", "own", "context", "own")]
    adapter.PLANS.extend([[("spawn", "late")], active_plan])

    async def scenario() -> tuple[str, bool, str]:
        await seam.call("invoke", invoke_args(PROBE))
        active = asyncio.create_task(seam.call("invoke", invoke_args(PROBE)))
        await entered.wait()
        # The snapshot brackets the orphan's publication alone.
        before = _snapshot(seam)
        adapter.release_orphan("late")
        await asyncio.gather(*adapter.TASKS)
        unchanged = _snapshot(seam) == before
        release.set()
        await asyncio.wait_for(active, WAIT)
        active_operation = adapter.SAVED["context"].operation_id
        return (
            adapter.ORPHAN_OUTCOMES["late"]["borrowed"],
            unchanged,
            adapter.OUTCOMES[active_operation]["own"],
        )

    refusal, unchanged, own = asyncio.run(asyncio.wait_for(scenario(), WAIT))
    return {"refusal": refusal, "own": own, "unchanged": unchanged}


def _another_controller(
    seam: StandaloneSeam, adapter: Any, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """From inside an active invoke of one controller, the adapter publishes
    through ANOTHER controller's services member, under its own ids."""
    plugin = seam.session.plugin
    foreign = DatasetAdmission(
        contracts=resolve_invoke_contracts(plugin),
        channels=_channels(plugin),
        library=lambda: seam._library(""),
        surface=lambda: None,
    )
    adapter.FOREIGN_SERVICES = attach_dataset_members(object(), controller=foreign)
    adapter.PLANS.append([("publish_foreign", "claim")])
    before = _snapshot(seam, foreign)
    call(seam, "invoke", invoke_args(PROBE))
    return {
        "refusal": _sole(adapter.OUTCOMES),
        "unchanged": _snapshot(seam, foreign) == before,
    }


def _mutated_input(
    seam: StandaloneSeam, adapter: Any, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """The adapter mutates the dispatched input IN PLACE and publishes a
    manifest that echoes the mutated value."""
    adapter.MANIFEST["configuration_id"] = "cfg-forged"
    adapter.PLANS.append(
        [
            ("mutate_input", "configuration_id", "cfg-forged"),
            ("publish", "own", "context", "own"),
        ]
    )
    before = _snapshot(seam)
    call(seam, "invoke", invoke_args(CORRELATED, {"configuration_id": "cfg-7"}))
    return {"refusal": _sole(adapter.OUTCOMES), "unchanged": _snapshot(seam) == before}


_SCENARIOS: dict[str, Any] = {
    "rewritten-id": _rewritten_id,
    "another-operation-past": partial(_another_operation, recorded=True),
    "another-operation-never-dispatched": partial(_another_operation, recorded=False),
    "undispatched": _undispatched,
    "forged-mint-cross-operation": _cross_operation,
    "inherited-scope-borrows-the-active-id": _inherited_borrows_active,
    "another-controller": _another_controller,
    "input-captured-before-adapter-entry": _mutated_input,
}
for _exit in EXIT_CLASSES:
    for _caller in CALLERS:
        _SCENARIOS[f"closed-{_exit}-{_caller}"] = partial(
            _closed_scope, exit_class=_exit, caller=_caller
        )


def _run(
    arm: str, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[StandaloneSeam, dict[str, Any]]:
    """One refusal scenario on a seam of its own: the seam and the record."""
    seam, adapter = _load(project, tmp_path / "captures")
    record = _SCENARIOS[arm](seam, adapter, monkeypatch)
    assert isinstance(record["refusal"], str) and record["refusal"], (
        f"{arm}: no publication was answered"
    )
    return seam, record


# --- T3: the explicit publisher ------------------------------------------------


def test_t3_the_control_publishes_under_its_own_mint(
    identity_project: Path, tmp_path: Path
) -> None:
    """The control: an unchanged context and the matching host-minted id
    succeed, and the admission changes exactly what one admission changes.
    Green before the binding too: a control, not evidence for it."""
    seam, adapter = _load(identity_project, tmp_path / "captures")
    before = _state(seam)
    adapter.PLANS.append([("publish", "own", "context", "own")])
    call(seam, "invoke", invoke_args(PROBE))
    assert _sole(adapter.OUTCOMES) == "admitted", adapter.OUTCOMES
    ((operation, _),) = adapter.OUTCOMES.items()
    mint = f"ds:{operation}"
    after = _state(seam)
    assert _canonical(after) != _canonical(before), "the control must change the state"
    assert after["registries"] == [{mint: _manifest(dataset_id=mint)}]
    assert [row["dataset_id"] for row in after["rows"]] == [mint]
    segment = mint.replace(":", "-", 1)
    assert {
        f"datasets/{segment}/manifest.json",
        f"datasets/{segment}/metadata.json",
    } <= set(after["files"]), after["files"]


def test_t3_a_rewritten_context_dataset_id_is_refused(
    identity_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The issue's reproduction. The adapter rewrites ``context.dataset_id``
    inside ``execute`` and publishes a valid manifest that carries the
    rewritten id. Before the binding the host admitted it under an id the
    adapter chose."""
    _, record = _run("rewritten-id", identity_project, tmp_path, monkeypatch)
    assert record["refusal"].startswith(ID_MISMATCH), (
        f"the rewritten id was admitted: {record['refusal']!r}"
    )
    assert FORGED in record["refusal"], record["refusal"]


def test_t3_pin_the_inline_result_already_refused_a_rewritten_context(
    identity_project: Path, tmp_path: Path
) -> None:
    """A pin, green before the binding: the inline path admits the result
    against the mint the host captured before the adapter ran, so a
    dataset-shaped result that carries a rewritten id already refuses."""
    seam, adapter = _load(identity_project, tmp_path / "captures")
    before = _snapshot(seam)
    adapter.PLANS.append([("rewrite", FORGED), ("dataset_result", "context")])
    with pytest.raises(SeamError) as caught:
        call(seam, "invoke", invoke_args(PROBE))
    assert caught.value.code == "invalid_request"
    assert "standalone_dataset_invalid:" in caught.value.message, caught.value.message
    assert FORGED in caught.value.message and "host-minted id" in caught.value.message
    assert _snapshot(seam) == before


@pytest.mark.parametrize(
    "arm", ["another-operation-past", "another-operation-never-dispatched"]
)
def test_t3_another_operations_id_is_refused(
    identity_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str
) -> None:
    """From inside an active invoke, a publication as another operation
    refuses: a dispatch RECORD is correlation, not authority, and an id no
    dispatch minted has neither."""
    _, record = _run(arm, identity_project, tmp_path, monkeypatch)
    assert record["refusal"].startswith(OPERATION_MISMATCH), (
        f"the publication as another operation was admitted: {record['refusal']!r}"
    )


def test_t3_an_undispatched_operation_is_refused(
    identity_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A context for an operation this controller never dispatched carries
    no mint to publish under."""
    _, record = _run("undispatched", identity_project, tmp_path, monkeypatch)
    assert record["refusal"].startswith(NOT_DISPATCHED), (
        f"an undispatched operation published: {record['refusal']!r}"
    )
    assert NEVER_OP in record["refusal"], record["refusal"]


@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("exit_class", EXIT_CLASSES)
def test_t3_a_closed_scope_is_refused(
    identity_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exit_class: str,
    caller: str,
) -> None:
    """The scope closes when the invoke closes — on success, on error and
    on cancellation. After that, the saved context has no authority, and a
    task that inherited the scope has lost it."""
    _, record = _run(f"closed-{exit_class}-{caller}", identity_project, tmp_path, monkeypatch)
    assert record["exit"] == EXIT_SEEN[exit_class], (
        f"the dispatch did not exit by {exit_class}: {record['exit']!r}"
    )
    assert record["refusal"].startswith(INVOKE_CLOSED), (
        f"a closed scope published after {exit_class}: {record['refusal']!r}"
    )


def test_t3_pin_a_publish_inside_a_failing_span_stands(
    identity_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pin, green before the binding: the scope is open for the whole
    adapter span, so the operation's own publication before a raise stands
    while the dispatch itself fails."""
    seam, adapter = _load(identity_project, tmp_path / "captures")
    record = _publish_then_raise(seam, adapter, monkeypatch)
    assert record == {"exit": EXIT_SEEN["error"], "inside": "admitted"}, record


def test_t3_a_forged_mint_cannot_deny_its_operation_its_own_dataset(
    identity_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The issue's cross-operation consequence. One operation forges the
    mint of an operation that runs later. The forgery must refuse, and the
    later operation must then publish its own dataset under its own mint."""
    seam, record = _run("forged-mint-cross-operation", identity_project, tmp_path, monkeypatch)
    assert (record["refusal"].startswith(ID_MISMATCH), record["own"]) == (True, "admitted"), (
        f"the forgery: {record['refusal']!r}; the operation's own publication "
        f"afterwards: {record['own']!r}"
    )
    admission = seam._dataset_admission
    assert admission is not None
    own = admission.admitted_manifest("ds:op-22222222")
    assert own is not None and own["variables"][0]["values"] == [1.5], (
        "the mint must hold its own operation's manifest, not the forgery"
    )


def test_t3_an_inherited_scope_cannot_borrow_the_active_invoke(
    identity_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A task that inherited a closed scope publishes while a later
    operation is ACTIVE, and names that operation's real context. Presenting
    the active operation's ids is not authority: the call is not made in
    that invoke."""
    _, record = _run(
        "inherited-scope-borrows-the-active-id", identity_project, tmp_path, monkeypatch
    )
    assert (record["refusal"].startswith(INVOKE_CLOSED), record["own"]) == (True, "admitted"), (
        f"the inherited scope borrowing the active id: {record['refusal']!r}; the active "
        f"operation's own publication afterwards: {record['own']!r}"
    )


def test_t3_another_controllers_invoke_grants_no_authority_here(
    identity_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An invoke active on another controller of this process is no
    authority for this controller's member, even under matching ids."""
    _, record = _run("another-controller", identity_project, tmp_path, monkeypatch)
    assert record["refusal"].startswith(NOT_DISPATCHED), (
        f"another controller's invoke published here: {record['refusal']!r}"
    )


def test_t3_the_scope_carries_the_invoke_input_captured_before_adapter_entry(
    identity_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scope's fourth field is the dispatched input as the host saw it.
    An adapter that mutates the input object in place cannot move the M10
    echo check with it."""
    control, adapter = _load(identity_project, tmp_path / "control")
    adapter.MANIFEST["configuration_id"] = "cfg-7"
    adapter.PLANS.append([("publish", "own", "context", "own")])
    call(control, "invoke", invoke_args(CORRELATED, {"configuration_id": "cfg-7"}))
    assert _sole(adapter.OUTCOMES) == "admitted", "the control: the honest echo admits"
    _, record = _run(
        "input-captured-before-adapter-entry", identity_project, tmp_path, monkeypatch
    )
    assert record["refusal"].startswith("refused: standalone_dataset_invalid:"), (
        f"the mutated echo was admitted: {record['refusal']!r}"
    )
    assert "M10" in record["refusal"] and "cfg-7" in record["refusal"], record["refusal"]


# --- T4: no state on refusal ---------------------------------------------------


@pytest.mark.parametrize("arm", sorted(_SCENARIOS))
def test_t4_no_state_on_refusal(
    identity_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str
) -> None:
    """Every refusal of the binding happens before any admission or index
    write: the admission state is byte-identical before and after the
    refused call."""
    _, record = _run(arm, identity_project, tmp_path, monkeypatch)
    assert record["unchanged"], f"{arm}: the refused call changed admission state"


def test_t4_the_snapshot_is_stable_at_rest_and_sees_one_admission(
    identity_project: Path, tmp_path: Path
) -> None:
    """T4's own control, green before the binding. A snapshot that cannot
    change proves nothing, and one that changes at rest would fail every
    arm for the wrong reason."""
    seam, adapter = _load(identity_project, tmp_path / "captures")
    at_rest = _snapshot(seam)
    assert _snapshot(seam) == at_rest, "at rest the snapshot is byte-identical"
    adapter.PLANS.append([("publish", "own", "context", "own")])
    call(seam, "invoke", invoke_args(PROBE))
    after = _state(seam)
    assert _canonical(after) != at_rest, "one admission must change the snapshot"
    assert len(after["registries"][0]) == 1, "the this-run registry"
    assert len(after["rows"]) == 1, "the library index"
    assert {"library.lock", "library.sqlite3"} <= set(after["files"]), after["files"]
    segment = next(iter(after["registries"][0])).replace(":", "-", 1)
    assert {
        f"datasets/{segment}/manifest.json",
        f"datasets/{segment}/metadata.json",
    } <= set(after["files"]), after["files"]
    assert _snapshot(seam) == _canonical(after), "at rest again the snapshot is stable"


# --- fold wave 1: both admission paths read what the host captured -----------
#
# Three findings from the review of `426d269`. Every arm is RED there unless
# its name says control or pin.
#
# F1  The INLINE admission path ran its M10 echo check against the dispatched
#     input OBJECT, which the adapter is handed and can mutate in place.
# F2  The scope closer read ``context.operation_id`` LATE, when it ran. An
#     adapter that rewrote that attribute made the span's ``finally`` close
#     the wrong scope: its own stayed open, so a task that inherited it kept
#     its publishing authority after the invoke had closed.
# F3  The capture fell back to the caller's LIVE object for any input that is
#     not JSON data (one NaN anywhere in it was enough), which put the
#     explicit publisher back on a mutable object for every field.
#
# What the arms enforce after the fold: both admission paths read ONE
# captured value per dispatch (the operation id, the minted dataset id, the
# action id and the input as a private copy), taken before the adapter ran;
# the closer closes on the operation id captured then; and with no dispatch
# record, or no captured input, admission refuses before any write and never
# falls back to a caller's object.

#: What the caller sends, and what the adapter mutates it to.
SENT = "cfg-7"
MUTATED = "cfg-forged"
#: The adapter's in-place mutation of the dispatched input object.
_MUTATE = [("mutate_input", "configuration_id", MUTATED)]
#: An input that passes an open object schema and that JSON cannot express.
_NOT_JSON = {"tag": {"not", "json"}}
#: Operation ids the arms pin the mint to.
OWN = "op-11111111"
OTHER = "op-22222222"
FORGED_OPERATION = "op-forged01"
#: An action that declares ``configuration_id`` (so M10 is armed) and leaves
#: the rest of its input open, so an awkward value can travel beside it.
OPEN_CORRELATED = "demo.correlated_open/1.0.0"


class _Opaque:
    """A value JSON cannot express and ``copy.deepcopy`` can."""

    def __init__(self) -> None:
        self.parts = [1, 2, 3]


def _uncopyable() -> Any:
    """A value the host cannot copy at all."""
    return (str(index) for index in range(3))


AWKWARD = [
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="infinity"),
    pytest.param(b"bytes", id="bytes"),
    pytest.param(_Opaque(), id="opaque-object"),
]
#: The awkward values a schema that types a field as ``number`` still admits:
#: jsonschema takes NaN and Infinity for numbers.
AWKWARD_NUMBER = AWKWARD[:2]


def _with_open_correlated_action(project: Path) -> Path:
    """Add ``OPEN_CORRELATED`` to a built project: its catalog action and
    descriptor row, and the catalog pin's digest."""
    package = project / "src" / PACKAGE
    catalog = json.loads((package / "profile-catalog.json").read_text())
    catalog["actions"][OPEN_CORRELATED] = {
        "description": (
            "Synthetic fetch action that declares the configuration_id echo "
            "field and leaves the rest of the input open (the F3 arms)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"configuration_id": {"type": "string", "minLength": 1}},
            "required": ["configuration_id"],
        },
        "output_schema": {"type": "object"},
        "side_effect": "none",
        "lifecycle": "direct",
    }
    payload = (json.dumps(catalog, indent=2) + "\n").encode()
    (package / "profile-catalog.json").write_bytes(payload)
    descriptor = json.loads((package / "descriptor.json").read_text())
    for pin in descriptor["contracts"]:
        if pin["path"] == "profile-catalog.json":
            pin["sha256"] = hashlib.sha256(payload).hexdigest()
    descriptor["actions"][OPEN_CORRELATED] = {
        "binding": {"kind": "adapter", "key": OPEN_CORRELATED},
        "input_constraints": {},
        "timeout_ms": 30000,
        "side_effect": "none",
        "cancellable": True,
        "retry": "never",
    }
    (package / "descriptor.json").write_bytes((json.dumps(descriptor, indent=2) + "\n").encode())
    return project


@pytest.fixture(scope="module")
def open_identity_project(invoke_project_builder, tmp_path_factory) -> Path:
    """The identity project plus the open correlated action. Built once."""
    project = invoke_project_builder(
        tmp_path_factory.mktemp("identity-open") / "proj", catalog_with_correlated_fetch=True
    )
    (project / "src" / PACKAGE / "adapter.py").write_bytes(ADAPTER)
    return _with_open_correlated_action(project)


def _divergence_free(message: str) -> str:
    """A refusal without the D10 divergence sentence (the same in each)."""
    return message.split(" The standalone host")[0]


def _admitted_echoes(seam: StandaloneSeam) -> set[Any]:
    admission = seam._dataset_admission
    assert admission is not None
    return {manifest.get("configuration_id") for manifest in admission._admitted.values()}


def _open_scopes(seam: StandaloneSeam) -> list[str]:
    """The operations whose scope is still open on the controller."""
    admission = seam._dataset_admission
    assert admission is not None
    return sorted(admission._open)


def _dispatch_input(action: str, value: Any = None) -> dict[str, Any]:
    """What the caller sends: the echo field, and beside it an awkward value
    for the actions that leave the rest of the input open."""
    sent: dict[str, Any] = {"configuration_id": SENT}
    if value is not None:
        sent["payload"] = value
    return invoke_args(action, sent)


def _run_arm(
    seam: StandaloneSeam,
    adapter: Any,
    *,
    path: str,
    plan: list[tuple],
    echo: str,
    action: str = CORRELATED,
    value: Any = None,
) -> dict[str, Any]:
    """One arm on one path. The adapter mutates the dispatched input as the
    plan says, then answers a dataset-shaped result (inline) or publishes
    (explicit) a manifest that carries ``echo``. Answers what the seam said,
    what was admitted, whether the admission state is unchanged, and what
    the caller's input reads now."""
    adapter.MANIFEST["configuration_id"] = echo
    if path == "inline":
        step = ("dataset_result", "context")
    else:
        step = ("publish", "own", "context", "own")
    adapter.PLANS.append([*plan, step])
    dispatch = _dispatch_input(action, value)
    before = _snapshot(seam)
    if path == "inline":
        try:
            call(seam, "invoke", dispatch)
        except SeamError as exc:
            outcome = f"refused: {exc.code}: {_divergence_free(exc.message)}"
        else:
            outcome = "returned"
    else:
        call(seam, "invoke", dispatch)
        outcome = _sole(adapter.OUTCOMES)
    return {
        "outcome": outcome,
        "admitted": _admitted_echoes(seam),
        "unchanged": _snapshot(seam) == before,
        "sent_now": dispatch["input"]["configuration_id"],
    }


def _refused_by_m10(record: dict[str, Any], *, inline: bool) -> None:
    """The seam answers an inline refusal as ``invalid_request``; the
    explicit publisher's refusal reaches the adapter without a seam code."""
    outcome = str(record["outcome"])
    prefix = "refused: invalid_request: " if inline else "refused: "
    assert outcome.startswith(prefix + "standalone_dataset_invalid:"), record
    assert "M10" in outcome and f"'{SENT}'" in outcome, record
    assert record["admitted"] == set(), "nothing may be admitted"
    assert record["unchanged"], "the refusal precedes any admission or index write"


def _echo(services: Any, dataset_id: str, context: Any, echo: str) -> str:
    """One ``dataset_publish`` from the test's own task, with a manifest that
    carries ``echo``."""
    manifest = _manifest(dataset_id=dataset_id, configuration_id=echo)
    try:
        asyncio.run(services.dataset_publish(manifest, context))
    except ValueError as exc:
        return f"refused: {exc}"
    return "admitted"


def test_fold_f1a_the_inline_result_cannot_move_m10_by_mutating_the_input(
    identity_project: Path, tmp_path: Path
) -> None:
    """F1-a. The adapter mutates the dispatched input object in place, then
    answers a dataset-shaped result that echoes the mutated value. The
    invoke must be refused by M10 and nothing admitted. RED on `426d269`:
    the invoke returned and the forged echo was admitted."""
    seam, adapter = _load(identity_project, tmp_path / "captures")
    record = _run_arm(seam, adapter, path="inline", plan=_MUTATE, echo=MUTATED)
    assert record["sent_now"] == MUTATED, "the adapter did mutate the dispatched input object"
    _refused_by_m10(record, inline=True)


def test_fold_f1b_the_inline_result_echoing_the_original_input_stands_under_mutation(
    identity_project: Path, tmp_path: Path
) -> None:
    """F1-b. The same in-place mutation, but the result echoes the input as
    the host RECEIVED it. That one must be admitted: the comparison base is
    the captured copy, not the object the adapter moved. RED on `426d269`:
    the honest echo was refused because the stored object had moved."""
    seam, adapter = _load(identity_project, tmp_path / "captures")
    record = _run_arm(seam, adapter, path="inline", plan=_MUTATE, echo=SENT)
    assert record["sent_now"] == MUTATED, "the adapter did mutate the dispatched input object"
    assert record["outcome"] == "returned", record
    assert record["admitted"] == {SENT}, record
    assert not record["unchanged"], "one admission changes the state"


@pytest.mark.parametrize(
    ("path", "plan", "echo"),
    [
        ("inline", [], SENT),
        ("inline", [], MUTATED),
        ("explicit", _MUTATE, MUTATED),
        ("explicit", _MUTATE, SENT),
    ],
    ids=["inline-honest", "inline-forged-echo", "explicit-mutated", "explicit-original"],
)
def test_fold_control_the_repro_arms_keep_their_outcomes(
    identity_project: Path, tmp_path: Path, path: str, plan: list[tuple], echo: str
) -> None:
    """F1-d, CONTROLS: green on `426d269` and after the fold. An honest echo
    is admitted on either path. A forged echo is refused by M10 when the
    input was not mutated (inline), and when the mutation meets the explicit
    publisher's captured copy."""
    seam, adapter = _load(identity_project, tmp_path / "captures")
    record = _run_arm(seam, adapter, path=path, plan=plan, echo=echo)
    if plan:
        assert record["sent_now"] == MUTATED, "the mutation reached the caller's object"
    if echo == SENT:
        # The inline path answers with the invoke's return; the explicit
        # publisher's outcome is the publication's own.
        expected = "returned" if path == "inline" else "admitted"
        assert record["outcome"] == expected, record
        assert record["admitted"] == {SENT}, record
    else:
        _refused_by_m10(record, inline=path == "inline")


@pytest.mark.parametrize("mutate", [False, True], ids=["honest-result", "forged-result"])
def test_fold_f1c_with_no_dispatch_record_the_inline_result_is_refused(
    identity_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutate: bool
) -> None:
    """F1-c. The host has no dispatch record for the operation, because the
    recording never happened. The inline admission must refuse with its own
    prefix, before any state, whether the result is honest or forged: it
    never falls back to the caller's input object. RED on `426d269`: both
    results were admitted."""
    seam, adapter = _load(identity_project, tmp_path / "captures")
    admission = seam._dataset_admission
    assert admission is not None
    monkeypatch.setattr(admission, "record_dispatch", lambda *args, **kwargs: None)
    plan = _MUTATE if mutate else []
    record = _run_arm(
        seam, adapter, path="inline", plan=plan, echo=MUTATED if mutate else SENT
    )
    assert record["outcome"].startswith(
        "refused: invalid_request: standalone_dataset_not_dispatched:"
    ), record
    assert record["admitted"] == set(), record
    assert record["unchanged"], record


@pytest.mark.parametrize("awkward", ["none", "not-json-data"])
def test_fold_f1e_the_dispatch_record_holds_a_copy_the_caller_cannot_reach(
    identity_project: Path, tmp_path: Path, awkward: str
) -> None:
    """F1-e at the record. The caller mutates its input object AFTER the
    record was written. The record must still carry the input as the host
    received it, as a copy. The JSON cell is a control, green on `426d269`.
    RED on `426d269` for the other cell: the record WAS the caller's object,
    because an input JSON cannot express got the live reference."""
    seam, _ = _load(identity_project, tmp_path / "captures")
    admission = seam._dataset_admission
    assert admission is not None
    sent: dict[str, Any] = {"configuration_id": SENT}
    if awkward == "not-json-data":
        sent.update(_NOT_JSON)
    original = copy.deepcopy(sent)
    admission.record_dispatch(
        "op-fold0001", dataset_id="ds:op-fold0001", action_id=CORRELATED, input=sent
    )
    sent["configuration_id"] = MUTATED
    admission.close_dispatch("op-fold0001")
    stored = admission.dispatch_state("op-fold0001")
    assert stored is not None and _open_scopes(seam) == []
    assert stored["input"] == original, f"the record carries the caller's mutation: {stored}"
    assert stored["input"] is not sent


def test_fold_f1e_the_record_does_not_hand_out_its_copy_by_reference(
    identity_project: Path, tmp_path: Path
) -> None:
    """F1-e at the record's reader. A host-side reader mutates the input it
    was handed by ``dispatch_state``. The publisher must still compare
    against what the host captured. RED on `426d269`: the record handed out
    its own copy, so the reader's edit moved the comparison base."""
    seam, _ = _load(identity_project, tmp_path / "captures")
    admission, services = seam._dataset_admission, seam.session.services
    assert admission is not None and services is not None
    operation = "op-fold0001"
    admission.record_dispatch(
        operation,
        dataset_id=f"ds:{operation}",
        action_id=CORRELATED,
        input={"configuration_id": SENT},
    )
    handed = admission.dispatch_state(operation)
    assert handed is not None
    handed["input"]["configuration_id"] = MUTATED
    context = HostOperationContext(operation, timeout_ms=1000, dataset_id=f"ds:{operation}")
    try:
        honest = _echo(services, f"ds:{operation}", context, SENT)
        forged = _echo(services, f"ds:{operation}", context, MUTATED)
    finally:
        admission.close_dispatch(operation)
    assert honest == "admitted", honest
    assert forged.startswith("refused: standalone_dataset_invalid:") and "M10" in forged, forged


@pytest.mark.parametrize(("path", "expected"), [("inline", "invalid_request"), ("explicit", "")])
def test_fold_f1e_an_input_the_host_cannot_copy_refuses_admission(
    open_identity_project: Path, tmp_path: Path, path: str, expected: str
) -> None:
    """F1-e at the seam, with F3's rule. An input the host cannot copy at all
    leaves no captured input, so there is nothing to check an echo field
    against. Both admission paths refuse, before any state, with the typed
    prefix; neither falls back to the caller's object. RED on `426d269`:
    both admitted."""
    seam, adapter = _load(open_identity_project, tmp_path / "captures")
    record = _run_arm(
        seam, adapter, path=path, plan=[], echo=SENT, action=OPEN_CORRELATED, value=_uncopyable()
    )
    refused = f"refused: {expected + ': ' if expected else ''}standalone_dataset_input_absent:"
    assert record["outcome"].startswith(refused), record
    assert record["admitted"] == set(), record
    assert record["unchanged"], record


@pytest.mark.parametrize("restore", [True, False], ids=["restore", "tamper"])
@pytest.mark.parametrize("exit_class", EXIT_CLASSES)
def test_fold_f2_a_rewritten_operation_id_cannot_keep_the_scope_alive(
    identity_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exit_class: str,
    restore: str,
) -> None:
    """F2-a to F2-d. The adapter starts a task that inherits its scope, then
    rewrites ``context.operation_id`` and the invoke exits by success, error
    or cancellation. The inherited task publishes after the invoke closed.
    With the real id put back on the context (restore) that was ADMITTED on
    `426d269`; without it (tamper) it was refused for the wrong reason. In
    both the scope stayed open. The task must be refused ``invoke_closed``
    and no scope may remain."""
    seam, adapter = _load(identity_project, tmp_path / "captures")
    monkeypatch.setattr(session_module, "uuid", _CannedUuid("11111111"))
    adapter.ORPHANS["late"] = ([("rewrite_operation", OWN)] if restore else []) + [
        ("publish", "late", "context", "own")
    ]
    plan: list[tuple] = [("spawn", "late"), ("rewrite_operation", FORGED_OPERATION)]
    if exit_class == "cancel":
        plan.append(("hold", "span"))
    elif exit_class == "error":
        plan.append(("raise", "the adapter failed"))
    adapter.PLANS.append(plan)
    entered = adapter.gate("span")[0]
    before = _snapshot(seam)

    async def scenario() -> dict[str, Any]:
        task = asyncio.create_task(seam.call("invoke", invoke_args(PROBE)))
        if exit_class == "cancel":
            await entered.wait()
            task.cancel()
        try:
            await task
        except SeamError as exc:
            exit_seen = f"seam_error:{exc.code}"
        except asyncio.CancelledError:
            exit_seen = "cancelled"
        else:
            exit_seen = "returned"
        # The invoke has closed here: the adapter span's finally has run.
        still_open = _open_scopes(seam)
        adapter.release_orphan("late")
        await asyncio.gather(*adapter.TASKS)
        return {
            "exit": exit_seen,
            "still_open": still_open,
            "outcome": adapter.ORPHAN_OUTCOMES["late"]["late"],
        }

    record = asyncio.run(asyncio.wait_for(scenario(), WAIT))
    record["unchanged"] = _snapshot(seam) == before
    assert record["exit"] == EXIT_SEEN[exit_class], record
    assert (record["outcome"].startswith(INVOKE_CLOSED), record["still_open"]) == (True, []), (
        f"the inherited task must lose its authority and the scope must be closed: {record}"
    )
    assert record["unchanged"] and _open_scopes(seam) == [], record


def test_fold_f2e_a_rewritten_operation_id_cannot_close_another_operation(
    identity_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2-e, cross-denial. Two scopes are live on one controller. The first
    adapter rewrites its operation id to the OTHER operation's real id. The
    other operation must still publish its own dataset, and the first
    operation's scope must not survive its own invoke. RED on `426d269`: the
    first closer closed the OTHER scope, which refused its own publication,
    and the first scope stayed open and admitted its inherited task."""
    seam, adapter = _load(identity_project, tmp_path / "captures")
    monkeypatch.setattr(session_module, "uuid", _CannedUuid("11111111", "22222222"))
    adapter.ORPHANS["late"] = [("rewrite_operation", OWN), ("publish", "late", "context", "own")]
    adapter.PLANS.extend(
        [
            [("remember",), ("barrier", 2), ("spawn", "late"), ("rewrite_operation", OTHER)],
            [("remember",), ("barrier", 2), ("hold", "b"), ("publish", "own", "context", "own")],
        ]
    )
    held, release = adapter.gate("b")

    async def scenario() -> dict[str, Any]:
        # The seam mutex serializes public dispatches (T1); the lock-free
        # core from two tasks is the only way to hold two scopes open at once.
        first = asyncio.create_task(seam._invoke_core(invoke_args(PROBE, {"party": "a"}), "f2e-a"))
        second = asyncio.create_task(seam._invoke_core(invoke_args(PROBE, {"party": "b"}), "f2e-b"))
        await asyncio.wait_for(first, WAIT)  # the first span's finally has run
        open_after_first = _open_scopes(seam)
        release.set()
        await asyncio.wait_for(second, WAIT)
        other_own = adapter.OUTCOMES[OTHER]["own"]
        adapter.release_orphan("late")
        await asyncio.gather(*adapter.TASKS)
        return {
            "open_after_first": open_after_first,
            "other_own": other_own,
            "inherited": adapter.ORPHAN_OUTCOMES["late"]["late"],
        }

    record = asyncio.run(asyncio.wait_for(scenario(), WAIT))
    record["open_at_end"] = _open_scopes(seam)
    assert record["open_after_first"] == [OTHER], (
        f"after the first span closed, only the other scope may be open: {record}"
    )
    assert (record["other_own"], record["inherited"].startswith(INVOKE_CLOSED)) == (
        "admitted",
        True,
    ), record
    assert record["open_at_end"] == [], record
    admission = seam._dataset_admission
    assert admission is not None
    assert sorted(admission._admitted) == [f"ds:{OTHER}"], (
        "exactly the other operation's own dataset is admitted"
    )


@pytest.mark.parametrize("value", AWKWARD)
def test_fold_f3_an_awkward_value_does_not_put_the_explicit_publisher_back_on_the_live_object(
    identity_project: Path, tmp_path: Path, value: Any
) -> None:
    """F3 at the record and the explicit publisher. The input carries an
    awkward value beside the JSON echo field, and the dispatched object is
    mutated in place after the record was written. A manifest echoing the
    mutated value must be refused and one echoing the original admitted.
    RED on `426d269`: the capture failed on the awkward value, kept the live
    object, and so admitted the mutated echo and refused the honest one."""
    seam, _ = _load(identity_project, tmp_path / "captures")
    admission, services = seam._dataset_admission, seam.session.services
    assert admission is not None and services is not None
    operation = "op-fold0001"
    sent = {"configuration_id": SENT, "payload": value}
    admission.record_dispatch(
        operation, dataset_id=f"ds:{operation}", action_id=CORRELATED, input=sent
    )
    sent["configuration_id"] = MUTATED
    context = HostOperationContext(operation, timeout_ms=1000, dataset_id=f"ds:{operation}")
    try:
        forged = _echo(services, f"ds:{operation}", context, MUTATED)
        honest = _echo(services, f"ds:{operation}", context, SENT)
    finally:
        admission.close_dispatch(operation)
    assert (forged.startswith("refused: standalone_dataset_invalid:"), "M10" in forged) == (
        True,
        True,
    ), forged
    assert honest == "admitted", honest
    assert _admitted_echoes(seam) == {SENT}


def test_fold_f3_an_input_the_host_cannot_copy_refuses_with_a_typed_prefix(
    identity_project: Path, tmp_path: Path
) -> None:
    """F3, the copy that cannot be made. When the host cannot copy the input
    at all, admission refuses with the typed prefix for any echo, and admits
    nothing. It never degrades to the caller's object. RED on `426d269`: the
    mutated echo was admitted and the honest one refused."""
    seam, _ = _load(identity_project, tmp_path / "captures")
    admission, services = seam._dataset_admission, seam.session.services
    assert admission is not None and services is not None
    operation = "op-fold0001"
    sent = {"configuration_id": SENT, "payload": _uncopyable()}
    before = _snapshot(seam)
    admission.record_dispatch(
        operation, dataset_id=f"ds:{operation}", action_id=CORRELATED, input=sent
    )
    sent["configuration_id"] = MUTATED
    context = HostOperationContext(operation, timeout_ms=1000, dataset_id=f"ds:{operation}")
    try:
        forged = _echo(services, f"ds:{operation}", context, MUTATED)
        honest = _echo(services, f"ds:{operation}", context, SENT)
    finally:
        admission.close_dispatch(operation)
    assert "standalone_dataset_input_absent:" in forged, forged
    assert "standalone_dataset_input_absent:" in honest, honest
    assert _snapshot(seam) == before, "the refusals precede any admission or index write"


@pytest.mark.parametrize("echo", [MUTATED, SENT], ids=["forged-echo", "original-echo"])
@pytest.mark.parametrize("value", AWKWARD_NUMBER)
def test_fold_f3_an_awkward_number_in_a_real_action_input_does_not_move_the_explicit_publisher(
    action_lane_project: Path, tmp_path: Path, value: Any, echo: str
) -> None:
    """F3 through the public invoke and the pinned corpus action, whose input
    schema declares ``configuration_id`` and types a field as ``number``. A
    NaN or an Infinity passes that gate. The adapter mutates the dispatched
    input in place and publishes through the explicit member. RED on
    `426d269` for every cell. Bytes and an opaque object cannot pass a typed
    field; the open-action and record arms carry them."""
    seam, adapter = _load(action_lane_project, tmp_path / "captures")
    adapter.MANIFEST["configuration_id"] = echo
    adapter.PLANS.append([*_MUTATE, ("publish", "own", "context", "own"), ("echo_configuration",)])
    sent = {**SETTINGS, "configuration_id": SENT, "sample_rate_hz": value}
    dispatch = invoke_args(CONFIGURE, sent)
    before = _snapshot(seam)
    call(seam, "invoke", dispatch)
    record = {
        "outcome": _sole(adapter.OUTCOMES),
        "admitted": _admitted_echoes(seam),
        "unchanged": _snapshot(seam) == before,
        "sent_now": dispatch["input"]["configuration_id"],
    }
    assert record["sent_now"] == MUTATED, "the adapter did mutate the dispatched input object"
    if echo == MUTATED:
        _refused_by_m10(record, inline=False)
    else:
        assert record["outcome"] == "admitted", record
        assert record["admitted"] == {SENT}, record


@pytest.mark.parametrize("echo", [MUTATED, SENT], ids=["forged-echo", "original-echo"])
@pytest.mark.parametrize("path", ["inline", "explicit"])
@pytest.mark.parametrize("value", AWKWARD)
def test_fold_f3_an_awkward_value_does_not_move_the_echo_check_on_either_path(
    open_identity_project: Path, tmp_path: Path, path: str, echo: str, value: Any
) -> None:
    """F3 through the public invoke on BOTH paths, M10 armed. RED on
    `426d269` for every cell: inline read the live object; explicit fell back
    to it when the capture failed on the awkward value."""
    seam, adapter = _load(open_identity_project, tmp_path / "captures")
    record = _run_arm(
        seam, adapter, path=path, plan=_MUTATE, echo=echo, action=OPEN_CORRELATED, value=value
    )
    assert record["sent_now"] == MUTATED, "the adapter did mutate the dispatched input object"
    if echo == MUTATED:
        _refused_by_m10(record, inline=path == "inline")
    else:
        expected = "returned" if path == "inline" else "admitted"
        assert record["outcome"] == expected, record
        assert record["admitted"] == {SENT}, record


@pytest.mark.parametrize(
    ("step", "expected"),
    [("publish_in_thread", OPERATION_MISMATCH), ("publish_via_to_thread", "admitted")],
    ids=["bare-thread", "to-thread"],
)
def test_pin_publishing_from_a_bare_worker_thread_fails_closed(
    identity_project: Path, tmp_path: Path, step: str, expected: str
) -> None:
    """A pin, true on `426d269` and after the fold, and a compatibility
    fact. The active invoke travels with the dispatch CONTEXT. A bare worker
    thread starts with none, so a publication from one is refused: while the
    invoke is open it is ``operation_mismatch``, because that call is not
    made in the active invoke. ``asyncio.to_thread`` copies the context into
    the worker, so a publication through it is the invoke's own. No thread
    support is added."""
    seam, adapter = _load(identity_project, tmp_path / "captures")
    adapter.PLANS.append([(step, "own")])
    call(seam, "invoke", invoke_args(PROBE))
    assert _sole(adapter.OUTCOMES).startswith(expected), adapter.OUTCOMES


# --- pins: behaviour the binding must preserve ---------------------------------


def test_pin_a_nested_dispatch_on_another_seam_does_not_close_the_outer_scope(
    identity_project: Path, tmp_path: Path
) -> None:
    """A pin, green before the binding. An adapter that awaits a second
    public dispatch on another seam runs it INSIDE its own span, in one
    task. When the inner dispatch closes, the outer scope must still be the
    outer operation's: its next publication must still admit."""
    outer, adapter = _load(identity_project, tmp_path / "outer")
    inner, _ = _load(identity_project, tmp_path / "inner")
    adapter.PLANS.extend(
        [
            [
                ("publish", "before", "context", "own"),
                ("nested",),
                ("publish", "after", "context", "own"),
            ],
            [("publish", "inner", "context", "own")],
        ]
    )

    def nested() -> Any:
        return inner.call("invoke", invoke_args(PROBE))

    adapter.NESTED = nested

    async def scenario() -> None:
        await outer.call("invoke", invoke_args(PROBE))

    asyncio.run(asyncio.wait_for(scenario(), WAIT))
    (outer_operation, outer_keys), (inner_operation, inner_keys) = sorted(
        adapter.OUTCOMES.items(), key=lambda item: "before" not in item[1]
    )
    assert outer_keys == {"before": "admitted", "after": "admitted"}, adapter.OUTCOMES
    assert inner_keys == {"inner": "admitted"}, adapter.OUTCOMES
    outer_admission, inner_admission = outer._dataset_admission, inner._dataset_admission
    assert outer_admission is not None and inner_admission is not None
    assert list(outer_admission._admitted) == [f"ds:{outer_operation}"]
    assert list(inner_admission._admitted) == [f"ds:{inner_operation}"]


def test_pin_record_dispatch_stays_the_per_operation_correlation_record(
    identity_project: Path, tmp_path: Path
) -> None:
    """A pin, green before the binding: the dispatch record — the mint, the
    action and the input against the operation — is still written for every
    dispatch and is still read back by operation id."""
    seam, adapter = _load(identity_project, tmp_path / "captures")
    call(seam, "invoke", invoke_args(PROBE, {"probe": 1}))
    ((operation, keys),) = adapter.OUTCOMES.items()
    assert keys == {}, "this dispatch publishes nothing"
    admission = seam._dataset_admission
    assert admission is not None
    assert admission.dispatch_state(operation) == {
        "dataset_id": f"ds:{operation}",
        "action_id": PROBE,
        "input": {"probe": 1},
    }
    assert admission.dispatch_state(NEVER_OP) is None
