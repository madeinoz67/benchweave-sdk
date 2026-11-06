"""The invoke operation and its per-action contract (issue #589 §3.1/§3.2,
PR-2): the I1–I5 gates, the post-dispatch result gates, the per-action
deadline, the load-time budget feasibility check, the stated
side_effect/cancellable event row, the retry-never unknown surfacing, and
the device_reset row.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk_server.errors import SeamError
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.session import load_plugin_project, mock_plugin_session

DEV = "example_device"


def _seam(project: Path, **kwargs: Any) -> tuple[StandaloneSeam, Any]:
    """Load the project, fish the freshly imported scripted adapter, build
    the seam, and connect it (the arms all run connected)."""
    plugin = load_plugin_project(Path(project))
    adapter = sys.modules[f"{plugin.package}.adapter"]
    seam = StandaloneSeam(mock_plugin_session(plugin), transport_kind="mock", **kwargs)
    call(seam, "device_connect", {"device_id": DEV})
    return seam, adapter


def call(seam: StandaloneSeam, operation: str, arguments: dict[str, Any] | None = None) -> Any:
    return asyncio.run(seam.call(operation, arguments or {}))


def invoke_args(action_id: str, value: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"device_id": DEV, "action_id": action_id, "input": value or {}}


# --- the I1–I5 gates (the gateway's _invoke_gate, zero adapter calls) ----------


def test_invoke_serves_a_declared_action(tmp_path: Path, invoke_project_builder) -> None:
    seam, adapter = _seam(invoke_project_builder(tmp_path / "happy"))
    adapter.SCRIPT["invoke"] = {"ok": True}
    result = call(seam, "invoke", invoke_args("demo.probe/1.0.0"))
    assert result == {"action_id": "demo.probe/1.0.0", "result": {"ok": True}}


def test_i1_refuses_when_no_invoke_operation_is_declared(
    tmp_path: Path, invoke_project_builder
) -> None:
    seam, adapter = _seam(invoke_project_builder(tmp_path / "no-verb", declare_invoke=False))
    # A loud adapter failure proves the gate refused BEFORE any dispatch:
    # had the adapter run, the refusal would carry its envelope.
    adapter.SCRIPT["invoke"] = {"__error__": {
        "status": "error",
        "error": {"code": "INTERNAL_ERROR", "message": "dispatched",
                  "dispatch_state": "dispatched"},
    }}
    with pytest.raises(SeamError) as caught:
        call(seam, "invoke", invoke_args("demo.probe/1.0.0"))
    assert caught.value.code == "unavailable"
    assert caught.value.details.get("reason") == "contracts_unresolved"


def test_i2_refuses_an_undeclared_action_before_any_dispatch(
    tmp_path: Path, invoke_project_builder
) -> None:
    seam, adapter = _seam(invoke_project_builder(tmp_path / "undeclared"))
    adapter.SCRIPT["invoke"] = {"__error__": {
        "status": "error",
        "error": {"code": "INTERNAL_ERROR", "message": "dispatched",
                  "dispatch_state": "dispatched"},
    }}
    with pytest.raises(SeamError) as caught:
        call(seam, "invoke", invoke_args("bogus.action/1.0.0"))
    assert caught.value.code == "invalid_request"
    assert "not declared" in caught.value.message


def test_i3_refuses_an_action_the_catalog_does_not_resolve(
    tmp_path: Path, invoke_project_builder
) -> None:
    """M14: an action the descriptor declares but the pinned catalog does
    not carry is never opaque success."""
    ghost = {"bogus.ghost/1.0.0": {
        "binding": {"kind": "adapter", "key": "bogus.ghost/1.0.0"},
        "input_constraints": {},
        "timeout_ms": 30000,
        "side_effect": "none",
        "cancellable": True,
        "retry": "never",
    }}
    seam, _adapter = _seam(invoke_project_builder(tmp_path / "ghost", actions=ghost))
    with pytest.raises(SeamError) as caught:
        call(seam, "invoke", invoke_args("bogus.ghost/1.0.0"))
    assert caught.value.code == "invalid_request"
    assert "(M14)" in caught.value.message


def test_i4_refuses_input_violating_the_catalog_schema_at_json_path(
    tmp_path: Path, invoke_project_builder
) -> None:
    seam, _adapter = _seam(invoke_project_builder(tmp_path / "i4"))
    with pytest.raises(SeamError) as caught:
        # typed_echo's catalog input demands a non-empty mode string: an
        # empty value violates at $.mode (a MISSING key reports at $, the
        # required-key finding's own shape).
        call(seam, "invoke", invoke_args("demo.typed_echo/1.0.0", {"mode": ""}))
    assert caught.value.code == "invalid_request"
    assert "$.mode" in caught.value.message


def test_i5_refuses_input_violating_the_descriptor_constraints(
    tmp_path: Path, invoke_project_builder
) -> None:
    """I5 narrows BELOW the catalog: typed_echo's catalog admits any mode
    string; the descriptor's input_constraints demand an integer — the
    catalog-valid value refuses at the constraints gate."""
    actions = {
        "demo.probe/1.0.0": {
            "binding": {"kind": "adapter", "key": "demo.probe/1.0.0"},
            "input_constraints": {
                "properties": {"mode": {"type": "integer"}},
                "required": ["mode"],
            },
            "timeout_ms": 30000,
            "side_effect": "state_change",
            "cancellable": True,
            "retry": "never",
        },
    }
    seam, _adapter = _seam(
        invoke_project_builder(tmp_path / "i5", actions=actions)
    )
    with pytest.raises(SeamError) as caught:
        call(seam, "invoke", invoke_args("demo.probe/1.0.0", {"mode": "fast"}))
    assert caught.value.code == "invalid_request"
    assert "$.mode" in caught.value.message


# --- the post-dispatch result gates (the gateway's post-dispatch checks) -------


def test_the_result_envelope_is_closed(tmp_path: Path, invoke_project_builder) -> None:
    seam, adapter = _seam(invoke_project_builder(tmp_path / "envelope"))
    adapter.SCRIPT["invoke"] = {"__data__": {
        "action_id": "demo.probe/1.0.0", "result": {}, "extra": 1,
    }}
    with pytest.raises(SeamError) as caught:
        call(seam, "invoke", invoke_args("demo.probe/1.0.0"))
    assert caught.value.code == "unavailable"
    assert "exactly {action_id, result}" in caught.value.message


def test_the_result_must_echo_the_requests_action_id(
    tmp_path: Path, invoke_project_builder
) -> None:
    seam, adapter = _seam(invoke_project_builder(tmp_path / "echo"))
    adapter.SCRIPT["invoke"] = {"__data__": {
        "action_id": "demo.typed_echo/1.0.0", "result": {},
    }}
    with pytest.raises(SeamError) as caught:
        call(seam, "invoke", invoke_args("demo.probe/1.0.0"))
    assert caught.value.code == "unavailable"
    assert "uncorrelated" in caught.value.message


def test_the_result_must_satisfy_the_catalog_output_schema(
    tmp_path: Path, invoke_project_builder
) -> None:
    seam, adapter = _seam(invoke_project_builder(tmp_path / "output"))
    adapter.SCRIPT["invoke"] = {"value": "not-a-number"}
    with pytest.raises(SeamError) as caught:
        call(seam, "invoke", invoke_args("demo.typed_echo/1.0.0", {"mode": "fast"}))
    assert caught.value.code == "unavailable"
    assert "$.value" in caught.value.message


def test_a_dataset_shaped_result_refuses_naming_the_absent_admission(
    tmp_path: Path, invoke_project_builder
) -> None:
    """A dataset-shaped result is never laundered as a plain result: until
    the admission path exists (PR-3's seam) it refuses ``unavailable``
    naming the absent surface. The required key set is derived from the
    pinned measurement schema (the vendored 0.2.4 dataset definition), read
    here from the vendored bytes so the arm reddens loudly if the corpus
    ever moves it."""
    measurement = json.loads(
        (Path(__file__).resolve().parents[2]
         / "src/benchweave_sdk/standards/otdp/0.2.4/otdp-measurement.schema.json")
        .read_text()
    )
    dataset_shaped = {key: None for key in measurement["$defs"]["dataset"]["required"]}
    seam, adapter = _seam(invoke_project_builder(tmp_path / "dataset"))
    adapter.SCRIPT["invoke"] = dataset_shaped
    with pytest.raises(SeamError) as caught:
        call(seam, "invoke", invoke_args("demo.probe/1.0.0"))
    assert caught.value.code == "unavailable"
    assert "dataset" in caught.value.message
    assert caught.value.details.get("reason") == "dataset_admission_absent"


# --- D8: the per-action deadline and the feasibility check ---------------------


def test_the_context_is_minted_with_the_actions_deadline_not_the_verbs(
    tmp_path: Path, invoke_project_builder
) -> None:
    """M7's arm: the adapter answers the measured context slack — the
    action row's 500 ms must mint the deadline, never the verb's 30000."""
    actions = {"demo.probe/1.0.0": {
        "binding": {"kind": "adapter", "key": "demo.probe/1.0.0"},
        "input_constraints": {},
        "timeout_ms": 500,
        "side_effect": "state_change",
        "cancellable": True,
        "retry": "never",
    }}
    project = invoke_project_builder(tmp_path / "deadline", actions=actions)
    seam, adapter = _seam(project)
    adapter.SCRIPT["invoke"] = "__deadline__"
    result = call(seam, "invoke", invoke_args("demo.probe/1.0.0"))
    slack = result["result"]["deadline_slack_ms"]
    assert 0 < slack <= 2000, f"the context carried the verb budget: {slack} ms"


def test_an_action_timeout_above_the_verb_budget_refuses_construction(
    tmp_path: Path, invoke_project_builder
) -> None:
    """M8's arm: the load-time cross-field check refuses a descriptor whose
    action deadline cannot fit the serving verb's budget."""
    actions = {"demo.probe/1.0.0": {
        "binding": {"kind": "adapter", "key": "demo.probe/1.0.0"},
        "input_constraints": {},
        "timeout_ms": 61000,
        "side_effect": "state_change",
        "cancellable": True,
        "retry": "never",
    }}
    project = invoke_project_builder(
        tmp_path / "infeasible", actions=actions,
        invoke_policy={
            "timeout_ms": 60000, "side_effect": "none", "retry": "never",
            "cancellable": True, "completion": "acknowledged",
        },
    )
    with pytest.raises(ValueError, match=r"^standalone_action_budget_infeasible:"):
        StandaloneSeam(
            mock_plugin_session(load_plugin_project(project)),
            transport_kind="mock",
        )


def test_the_worked_example_passes_the_check(
    tmp_path: Path, invoke_project_builder
) -> None:
    """The record's §3.2 worked example: an action declaring 60000 ms
    against an invoke budget of 60000 ms PASSES the construction check —
    the check is a bound-coherence guard, not a completion guarantee (the
    per-attempt cost is nowhere in the descriptor; three attempts at ~23 s
    still cannot complete, and the honoured action deadline is what makes
    that failure visible instead of silent)."""
    actions = {"example.configure_fpga/1.0.0": {
        "binding": {"kind": "adapter", "key": "example.configure_fpga/1.0.0"},
        "input_constraints": {},
        "timeout_ms": 60000,
        "side_effect": "state_change",
        "cancellable": False,
        "retry": "never",
    }}
    project = invoke_project_builder(
        tmp_path / "worked-example", actions=actions,
        invoke_policy={
            "timeout_ms": 60000, "side_effect": "none", "retry": "never",
            "cancellable": True, "completion": "acknowledged",
        },
    )
    # The action is declared but not catalog-resolved (the synthetic catalog
    # carries no such row), so invoke answers I3 — construction itself is
    # the arm: it must not refuse.
    seam, adapter = _seam(project)
    adapter.SCRIPT["invoke"] = "__deadline__"
    with pytest.raises(SeamError) as caught:
        call(seam, "invoke", invoke_args("example.configure_fpga/1.0.0"))
    assert caught.value.code == "invalid_request"


def test_an_infeasible_budget_maps_to_serve_exit_2(
    tmp_path: Path, invoke_project_builder, capsys
) -> None:
    """The CLI's fail-fast: a construction refusal exits 2 with the typed
    prefix on stderr, never a traceback."""
    from benchweave_sdk_server.cli import _build_seam

    actions = {"demo.probe/1.0.0": {
        "binding": {"kind": "adapter", "key": "demo.probe/1.0.0"},
        "input_constraints": {},
        "timeout_ms": 61000,
        "side_effect": "state_change",
        "cancellable": True,
        "retry": "never",
    }}
    project = invoke_project_builder(
        tmp_path / "exit2", actions=actions,
        invoke_policy={
            "timeout_ms": 60000, "side_effect": "none", "retry": "never",
            "cancellable": True, "completion": "acknowledged",
        },
    )
    with pytest.raises(SystemExit) as caught:
        _build_seam(project)
    assert caught.value.code == 2
    assert "standalone_action_budget_infeasible:" in capsys.readouterr().err


# --- D9's action-contract rows on the event bus --------------------------------


def test_side_effect_and_cancellable_ride_the_invoke_event_row(
    tmp_path: Path, invoke_project_builder
) -> None:
    """Both are STATED verbatim from the descriptor row (§3.2): a watcher
    sees which actions mutate and which cannot be torn down; the host adds
    no semantics of its own."""
    seam, adapter = _seam(invoke_project_builder(tmp_path / "events"))
    adapter.SCRIPT["invoke"] = {"ok": True}
    call(seam, "invoke", invoke_args("demo.probe/1.0.0"))
    rows = [row for row in seam.events.after(0) if row["kind"] == "invoke"]
    assert rows, "a successful invoke must publish its state event"
    data = rows[-1]["data"]
    assert data["device_id"] == DEV
    assert data["action_id"] == "demo.probe/1.0.0"
    # demo.probe's descriptor row: state_change / cancellable true.
    assert data["side_effect"] == "state_change"
    assert data["cancellable"] is True


def test_a_retry_never_unknown_is_surfaced_verbatim(
    tmp_path: Path, invoke_project_builder
) -> None:
    """The one safety property kept (§3.2): an action declaring
    ``retry: "never"`` whose dispatch answers ``unknown`` is surfaced
    verbatim — never re-issued (the seam makes exactly one dispatch per
    call; there is no retry loop to disarm), never coerced to a decided
    outcome."""
    seam, adapter = _seam(invoke_project_builder(tmp_path / "unknown"))
    adapter.SCRIPT["invoke"] = {"__error__": {
        "status": "unknown",
        "error": {"code": "TIMEOUT",
                  "message": "the attempt did not complete before its deadline",
                  "dispatch_state": "unknown"},
    }}
    with pytest.raises(SeamError) as caught:
        call(seam, "invoke", invoke_args("demo.probe/1.0.0"))
    assert caught.value.code == "not_ready"
    assert caught.value.details["adapter"]["dispatch_state"] == "unknown"
    assert "did not complete" in caught.value.message


# --- D8's reset row ------------------------------------------------------------


def test_device_reset_dispatches_under_the_declared_policy(
    tmp_path: Path, invoke_project_builder
) -> None:
    seam, _adapter = _seam(invoke_project_builder(tmp_path / "reset", declare_reset=True))
    result = call(seam, "device_reset", {"device_id": DEV})
    assert result == {"device_id": DEV, "acknowledged": True}
    kinds = [row["kind"] for row in seam.events.after(0)]
    assert "device_reset" in kinds


def test_device_reset_requires_the_declared_policy(
    tmp_path: Path, invoke_project_builder
) -> None:
    seam, _adapter = _seam(invoke_project_builder(tmp_path / "no-reset"))
    with pytest.raises(SeamError) as caught:
        call(seam, "device_reset", {"device_id": DEV})
    assert caught.value.code == "unavailable"
    assert "reset operation policy" in caught.value.message


def test_a_reset_receipt_without_acknowledged_refuses(
    tmp_path: Path, invoke_project_builder
) -> None:
    seam, adapter = _seam(invoke_project_builder(tmp_path / "bad-reset", declare_reset=True))
    adapter.SCRIPT["reset"] = {"acknowledged": False}
    with pytest.raises(SeamError) as caught:
        call(seam, "device_reset", {"device_id": DEV})
    assert caught.value.code == "unavailable"
    assert "acknowledged" in caught.value.message


def test_the_invoke_core_runs_inside_a_caller_held_mutex(
    tmp_path: Path, invoke_project_builder
) -> None:
    """PR-6's reentrancy shape: the gate work lives in a LOCK-FREE core so
    a caller that already holds ``_op_mutex`` (a preset apply dispatching
    its configure action through invoke) can run the invoke path without
    deadlocking — ``asyncio.Lock`` is not reentrant, so a locked core
    called from a locked span hangs, it does not race. The run is bounded
    at 5s so that regression arrives as a red arm naming the deadlock,
    never as a CI-ceiling cancellation that reads as infrastructure.
    """
    seam, adapter = _seam(invoke_project_builder(tmp_path / "core"))
    adapter.SCRIPT["invoke"] = {"ok": True}

    async def _under_caller_held_mutex() -> dict[str, Any]:
        async with seam._op_mutex:
            try:
                return await asyncio.wait_for(
                    seam._invoke_core(
                        invoke_args("demo.probe/1.0.0"), "test-correlation"
                    ),
                    timeout=5.0,
                )
            except TimeoutError as exc:
                raise AssertionError(
                    "_invoke_core did not return within 5s while the caller "
                    "held _op_mutex — the core acquired the mutex it must "
                    "not (the lock-free contract, issue #589 PR-2)"
                ) from exc

    result = asyncio.run(_under_caller_held_mutex())
    assert result == {"action_id": "demo.probe/1.0.0", "result": {"ok": True}}
