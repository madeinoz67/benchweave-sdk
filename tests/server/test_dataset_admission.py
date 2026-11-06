"""The dataset admission path (issue #589 §4, PR-3): the per-dispatch mint,
the ruled inline admission, the explicit services members, the exposure
surfaces and the D10 disclosure.

The ruling's four answers, each pinned by an arm: where the bytes land (the
capture root's ``datasets/`` family, A11/A12), who may read them afterwards
(the host's guard model plus the this-run registry, A13/A18), what
``dataset_id`` is minted over (``"ds:" + operation_id`` per invoke dispatch,
A1/A2), and what the host does when admission fails (the typed refusal with
ZERO bytes on disk, A5-A11). The design record's arms A1-A20, pre-committed
in `.claude/deep-review/2026-11-06-589-pr3-dataset-admission-design.md` §9.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk_server.errors import SeamError
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.session import (
    HostOperationContext,
    load_plugin_project,
    mock_plugin_session,
)

DEV = "example_device"

#: The vendored measurement schema's dataset required keys, read from the
#: vendored bytes so the detector arms redden loudly if the corpus moves
#: them (the test_invoke precedent).
REQUIRED_KEYS = tuple(
    json.loads(
        (Path(__file__).resolve().parents[2]
         / "src/benchweave_sdk/standards/otdp/0.2.4/otdp-measurement.schema.json")
        .read_text()
    )["$defs"]["dataset"]["required"]
)


def _seam(
    project: Path, capture_root: Path, **kwargs: Any
) -> tuple[StandaloneSeam, Any]:
    """Load the project, fish the freshly imported scripted adapter, build
    the seam over a real capture root, and connect it."""
    plugin = load_plugin_project(Path(project))
    adapter = sys.modules[f"{plugin.package}.adapter"]
    seam = StandaloneSeam(
        mock_plugin_session(plugin),
        transport_kind="mock",
        capture_root=capture_root,
        **kwargs,
    )
    call(seam, "device_connect", {"device_id": DEV})
    return seam, adapter


def call(seam: StandaloneSeam, operation: str, arguments: dict[str, Any] | None = None) -> Any:
    return asyncio.run(seam.call(operation, arguments or {}))


def invoke_args(action_id: str, value: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"device_id": DEV, "action_id": action_id, "input": value or {}}


def _manifest(**overrides: Any) -> dict[str, Any]:
    """A schema-valid inline measurement manifest template (validated
    against the vendored 0.2.4 dataset definition); ``dataset_id`` is the
    adapter's to fill from the context."""
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


def _axis(length: int = 4) -> dict[str, Any]:
    return {
        "id": "t",
        "quantity": "time",
        "unit": "s",
        "length": length,
        "coordinates": {"kind": "regular", "start": 0.0, "step": 0.25},
    }


def _datasets_dir(root: Path) -> Path:
    return root / "datasets"


def _admitted_row(seam: StandaloneSeam) -> dict[str, Any] | None:
    rows = call(seam, "capture_list")["datasets"]
    return rows[0] if rows else None


# --- A1/A2: the mint (D4's core) -----------------------------------------------


def test_a1_the_invoke_dispatch_mints_and_the_inline_dataset_is_admitted(
    tmp_path: Path, invoke_project_builder
) -> None:
    root = tmp_path / "captures"
    seam, adapter = _seam(invoke_project_builder(tmp_path / "proj"), root)
    # The mint, observed the only honest way — through the adapter's own
    # context read: the observed id equals "ds:" + the request's operation id.
    adapter.SCRIPT["invoke"] = "__context__"
    probe = call(seam, "invoke", invoke_args("demo.probe/1.0.0"))["result"]
    assert probe["mint_matches"] is True, probe
    assert str(probe["observed_dataset_id"]).startswith("ds:op-")
    # The ruled path: a dataset-shaped result is admitted, not refused.
    adapter.SCRIPT["invoke"] = "__dataset__"
    adapter.DATASET.clear()
    adapter.DATASET.update(_manifest())
    result = call(seam, "invoke", invoke_args("demo.probe/1.0.0"))
    dataset_id = result["result"]["dataset_id"]
    assert str(dataset_id).startswith("ds:op-")
    row = _admitted_row(seam)
    assert row is not None and row["dataset_id"] == dataset_id
    assert (_datasets_dir(root) / dataset_id.replace(":", "-", 1) / "manifest.json").is_file()


def test_a2_a_non_invoke_dispatch_leaves_the_context_dataset_id_none(
    tmp_path: Path, invoke_project_builder
) -> None:
    seam, adapter = _seam(invoke_project_builder(tmp_path / "proj"), tmp_path / "captures")
    adapter.SCRIPT["identify"] = "__context__"
    envelope = asyncio.run(seam.session.execute("identify", {}))
    assert envelope["data"]["observed_dataset_id"] is None


def test_a3_dataset_publish_on_a_null_context_refuses_typed(
    tmp_path: Path, invoke_project_builder
) -> None:
    """The frozen prefix (rev 7 §7): a non-invoke dispatch's context carries
    a null dataset id, and publishing on one is a typed refusal, never a
    silent no-op."""
    seam, _adapter = _seam(invoke_project_builder(tmp_path / "proj"), tmp_path / "captures")
    services = seam.session.services
    assert services is not None
    context = HostOperationContext("op-null0001", timeout_ms=1000)
    assert context.dataset_id is None
    with pytest.raises(ValueError, match=r"^standalone_dataset_context_absent:"):
        asyncio.run(services.dataset_publish(_manifest(), context))


# --- A4: the detector -----------------------------------------------------------


def test_a4_the_detector_admits_dataset_shaped_results_and_passes_plain_ones(
    tmp_path: Path, invoke_project_builder
) -> None:
    """Required keys only, from the pinned measurement document at runtime:
    the same manifest minus one required key is NOT detected and passes as a
    plain result (the detector's negative control)."""
    root = tmp_path / "captures"
    seam, adapter = _seam(invoke_project_builder(tmp_path / "proj"), root)
    adapter.SCRIPT["invoke"] = "__dataset__"
    adapter.DATASET.clear()
    adapter.DATASET.update(_manifest())
    call(seam, "invoke", invoke_args("demo.probe/1.0.0"))
    assert _admitted_row(seam) is not None
    # The negative control: minus one required key, the result is a plain
    # object and the invoke succeeds with nothing admitted.
    partial = _manifest()
    del partial["trigger"]
    adapter.DATASET.clear()
    adapter.DATASET.update(partial)
    result = call(seam, "invoke", invoke_args("demo.probe/1.0.0"))
    assert "trigger" not in result["result"]
    rows = call(seam, "capture_list")["datasets"]
    assert len(rows) == 1, "the partial manifest must not admit a second row"


# --- A5-A11: the validation core, in the gateway's order -----------------------


def _refused(
    seam: StandaloneSeam,
    adapter: Any,
    manifest: dict[str, Any],
    *,
    action: str = "demo.probe/1.0.0",
    value: dict[str, Any] | None = None,
) -> SeamError:
    adapter.SCRIPT["invoke"] = "__dataset__"
    adapter.DATASET.clear()
    adapter.DATASET.update(manifest)
    with pytest.raises(SeamError) as caught:
        call(seam, "invoke", invoke_args(action, value))
    return caught.value


def test_a5_a_schema_violation_refuses_with_json_path_the_divergence_and_no_directory(
    tmp_path: Path, invoke_project_builder
) -> None:
    root = tmp_path / "captures"
    seam, adapter = _seam(invoke_project_builder(tmp_path / "proj"), root)
    error = _refused(seam, adapter, _manifest(kind="bogus_kind"))
    assert error.code == "invalid_request"
    assert "standalone_dataset_invalid:" in error.message
    assert "$.kind" in error.message, "the refusal names the pinned schema's json_path"
    assert "gateway" in error.message, "the D10 divergence sentence rides every refusal"
    assert not _datasets_dir(root).exists() or not any(_datasets_dir(root).iterdir())


def test_a6_an_undeclared_channel_refuses(
    tmp_path: Path, invoke_project_builder
) -> None:
    """M01's channels cross-check (D9's row): every variable channel id must
    be one the descriptor's ``channels`` declares."""
    root = tmp_path / "captures"
    seam, adapter = _seam(invoke_project_builder(tmp_path / "proj"), root)
    manifest = _manifest()
    manifest["variables"][0]["channel_ids"] = ["ghost_chan"]
    error = _refused(seam, adapter, manifest)
    assert error.code == "invalid_request"
    assert "standalone_dataset_invalid:" in error.message
    assert "M01" in error.message and "ghost_chan" in error.message
    assert not _datasets_dir(root).exists() or not any(_datasets_dir(root).iterdir())


def test_a7_inline_values_against_the_dimension_product_refuse(
    tmp_path: Path, invoke_project_builder
) -> None:
    root = tmp_path / "captures"
    seam, adapter = _seam(invoke_project_builder(tmp_path / "proj"), root)
    manifest = _manifest(axes=[_axis(length=4)])
    manifest["variables"][0]["dimensions"] = ["t"]
    manifest["variables"][0]["values"] = [1.0, 2.0, 3.0]
    error = _refused(seam, adapter, manifest)
    assert "standalone_dataset_invalid:" in error.message
    assert "M02" in error.message


def test_a8_m10_echo_fields_are_checked_only_when_the_action_declares_them(
    tmp_path: Path, invoke_project_builder
) -> None:
    """The gate's both directions: a manifest whose configuration_id
    diverges from the invoke input refuses when the action's pinned input
    schema DECLARES the field; the same divergent value admits when it does
    not (the gateway's declared-properties gate, dataset_services.py:690-715
    parity)."""
    root = tmp_path / "captures"
    project = invoke_project_builder(
        tmp_path / "proj", catalog_with_correlated_fetch=True
    )
    seam, adapter = _seam(project, root)
    # Declared and echoing: admits.
    adapter.SCRIPT["invoke"] = "__dataset__"
    adapter.DATASET.clear()
    adapter.DATASET.update(_manifest(configuration_id="cfg-7"))
    call(seam, "invoke", invoke_args("demo.correlated_fetch/1.0.0", {"configuration_id": "cfg-7"}))
    assert _admitted_row(seam) is not None
    # Declared and diverging: refuses.
    error = _refused(
        seam,
        adapter,
        _manifest(configuration_id="cfg-8"),
        action="demo.correlated_fetch/1.0.0",
        value={"configuration_id": "cfg-7"},
    )
    assert "standalone_dataset_invalid:" in error.message
    assert "M10" in error.message
    # Undeclared (demo.probe's open schema carries no properties): the same
    # divergent value is none of the host's business — admits.
    adapter.SCRIPT["invoke"] = "__dataset__"
    adapter.DATASET.clear()
    adapter.DATASET.update(_manifest(configuration_id="cfg-unrelated"))
    call(seam, "invoke", invoke_args("demo.probe/1.0.0"))
    rows = call(seam, "capture_list")["datasets"]
    assert len(rows) == 2, [row["dataset_id"] for row in rows]


def test_a9_an_artifact_backed_variable_refuses_naming_the_absent_surface(
    tmp_path: Path, invoke_project_builder
) -> None:
    """M11, honestly scoped: no payload lane ships standalone, so the
    finalise registry is empty and an artifact-backed variable refuses
    naming the absent payload surface (S4 carries it)."""
    root = tmp_path / "captures"
    seam, adapter = _seam(invoke_project_builder(tmp_path / "proj"), root)
    manifest = _manifest()
    variable = manifest["variables"][0]
    del variable["values"]
    variable["artifact"] = {
        "artifact_id": "art-" + "1" * 60,
        "encoding": "f64le",
        "byte_length": 8,
        "sha256": "1" * 64,
    }
    error = _refused(seam, adapter, manifest)
    assert "standalone_dataset_invalid:" in error.message
    assert "M11" in error.message
    assert "payload" in error.message


def test_a10_an_idempotent_republish_returns_the_admitted_manifest(
    tmp_path: Path, invoke_project_builder
) -> None:
    root = tmp_path / "captures"
    seam, adapter = _seam(invoke_project_builder(tmp_path / "proj"), root)
    adapter.SCRIPT["invoke"] = "__publish__"
    adapter.PUBLISH_QUEUE.clear()
    adapter.PUBLISH_QUEUE.extend([_manifest(), _manifest()])
    result = call(seam, "invoke", invoke_args("demo.probe/1.0.0"))["result"]
    assert result["publishes"] == ["admitted", "admitted"], result
    assert len(call(seam, "capture_list")["datasets"]) == 1
    # A divergent manifest under the used id refuses naming immutability.
    adapter.PUBLISH_QUEUE.clear()
    divergent = _manifest()
    divergent["variables"][0]["values"] = [9.9]
    adapter.PUBLISH_QUEUE.extend([_manifest(), divergent])
    result = call(seam, "invoke", invoke_args("demo.probe/1.0.0"))["result"]
    assert result["publishes"][0] == "admitted"
    assert result["publishes"][1].startswith("refused: standalone_dataset_invalid:")
    assert "immutable" in result["publishes"][1]


def test_a11_a_validation_refusal_leaves_zero_bytes_under_datasets(
    tmp_path: Path, invoke_project_builder
) -> None:
    """The D4 condition's own acceptance arm: a manifest that PASSES the
    pinned schema but fails an M-check (duplicate variable ids — the schema
    does not enforce uniqueness, M01 does) leaves zero bytes on disk. The
    atomicity is structural: validation precedes any filesystem call."""
    root = tmp_path / "captures"
    seam, adapter = _seam(invoke_project_builder(tmp_path / "proj"), root)
    manifest = _manifest()
    manifest["variables"] = [manifest["variables"][0], dict(manifest["variables"][0])]
    error = _refused(seam, adapter, manifest)
    assert "M01" in error.message
    assert not _datasets_dir(root).exists() or not any(_datasets_dir(root).iterdir())


# --- A12-A15: persistence, exposure and the event ------------------------------


def test_a12_a_fresh_library_rebuilds_the_dataset_row_from_files(
    tmp_path: Path, invoke_project_builder
) -> None:
    """AR-6's discipline, extended to the second family: the index is query
    acceleration; a fresh library over the root rebuilds the dataset row
    from the files alone."""
    from benchweave_sdk_server.library import CaptureLibrary

    root = tmp_path / "captures"
    seam, adapter = _seam(invoke_project_builder(tmp_path / "proj"), root)
    adapter.SCRIPT["invoke"] = "__dataset__"
    adapter.DATASET.clear()
    adapter.DATASET.update(_manifest())
    result = call(seam, "invoke", invoke_args("demo.probe/1.0.0"))
    dataset_id = result["result"]["dataset_id"]
    # Release the seam's lock so a fresh library may own the root.
    assert seam._capture_library is not None
    seam._capture_library.close()
    fresh = CaptureLibrary(root)
    try:
        rows = fresh.list_datasets()
        assert [row["dataset_id"] for row in rows] == [dataset_id]
        row = rows[0]
        assert row["kind"] == "scalar_set"
        assert row["status"] == "complete"
        assert row["action_id"] == "demo.probe/1.0.0"
        assert len(row["sha256"]) == 64
    finally:
        fresh.close()


def test_a13_capture_list_serves_the_datasets_row_and_leaves_captures_alone(
    tmp_path: Path, invoke_project_builder
) -> None:
    root = tmp_path / "captures"
    seam, adapter = _seam(invoke_project_builder(tmp_path / "proj"), root)
    adapter.SCRIPT["invoke"] = "__dataset__"
    adapter.DATASET.clear()
    adapter.DATASET.update(_manifest())
    result = call(seam, "invoke", invoke_args("demo.probe/1.0.0"))
    listing = call(seam, "capture_list")
    assert listing["captures"] == [], "no capture ran; the captures array is unchanged"
    (row,) = listing["datasets"]
    assert set(row) == {
        "dataset_id", "kind", "started_at", "status", "action_id",
        "surface", "operator", "project", "pinned", "tags", "notes",
    }
    assert row["dataset_id"] == result["result"]["dataset_id"]
    assert row["pinned"] is False and row["tags"] == [] and row["notes"] == ""


def test_a14_host_info_carries_the_dataset_admission_disclosure(
    tmp_path: Path, invoke_project_builder
) -> None:
    seam, _adapter = _seam(
        invoke_project_builder(tmp_path / "proj"), tmp_path / "captures"
    )
    info = call(seam, "host_info")
    admission = info["dataset_admission"]
    assert admission["standard"] == "host-admits-on-invoke-result"
    assert "GW-1" in admission["gateway_divergence"]
    assert "#589" in admission["gateway_divergence"]
    # The disclosure is host truth, not lane state: an unarmed host (no
    # invoke lane) carries it too.
    plain, _adapter = _seam(
        invoke_project_builder(tmp_path / "plain", declare_invoke=False),
        tmp_path / "captures-plain",
    )
    assert "dataset_admission" in call(plain, "host_info")


def test_a15_a_dataset_admitted_event_rides_the_bus(
    tmp_path: Path, invoke_project_builder
) -> None:
    seam, adapter = _seam(invoke_project_builder(tmp_path / "proj"), tmp_path / "captures")
    adapter.SCRIPT["invoke"] = "__dataset__"
    adapter.DATASET.clear()
    adapter.DATASET.update(_manifest())
    result = call(seam, "invoke", invoke_args("demo.probe/1.0.0"))
    rows = [row for row in seam.events.after(0) if row["kind"] == "dataset_admitted"]
    assert rows, "a successful admission must publish its event"
    assert rows[-1]["data"] == {
        "dataset_id": result["result"]["dataset_id"],
        "kind": "scalar_set",
        "action_id": "demo.probe/1.0.0",
    }


# --- A18-A20: the explicit members and the protocol pin ------------------------


def test_a18_dataset_lookup_serves_this_runs_admitted_manifests(
    tmp_path: Path, invoke_project_builder
) -> None:
    seam, adapter = _seam(invoke_project_builder(tmp_path / "proj"), tmp_path / "captures")
    adapter.SCRIPT["invoke"] = "__dataset__"
    adapter.DATASET.clear()
    adapter.DATASET.update(_manifest())
    result = call(seam, "invoke", invoke_args("demo.probe/1.0.0"))
    dataset_id = result["result"]["dataset_id"]
    adapter.SCRIPT["invoke"] = "__lookup__"
    adapter.LOOKUP_IDS.clear()
    adapter.LOOKUP_IDS.extend([dataset_id, "ds:op-unknown1"])
    outcome = call(seam, "invoke", invoke_args("demo.probe/1.0.0"))["result"]
    assert outcome["lookups"][0] == f"found:{dataset_id}"
    assert outcome["lookups"][1].startswith("refused: standalone_dataset_unknown:")


def test_a19_the_wrapper_is_transparent_to_the_base_services(
    tmp_path: Path, invoke_project_builder
) -> None:
    """The wrapper delegates ``__getattr__``: the capture duck-checks (and
    every other base member) still resolve through it — the capture lane is
    unbroken (R-B's falsifier)."""
    from benchweave_sdk_server.dataset_admission import attach_dataset_members

    seam, _adapter = _seam(invoke_project_builder(tmp_path / "proj"), tmp_path / "captures")
    services = seam.session.services
    assert services is not None
    assert callable(getattr(services, "transfer", None)), (
        "the base HostServices members must resolve through the wrapper"
    )

    class _CaptureCapable:
        def configure_capture(self, capture_id, *, metadata, max_bytes=None) -> None: ...
        def capture_progress(self, capture_id) -> int:
            return 0

    wrapped = attach_dataset_members(
        _CaptureCapable(), controller=seam._dataset_admission
    )
    assert callable(getattr(wrapped, "configure_capture", None))
    assert callable(getattr(wrapped, "capture_progress", None))


def test_a20_the_protocol_composes_twelve_and_the_wrapper_carries_the_pair(
    tmp_path: Path, invoke_project_builder
) -> None:
    from benchweave_sdk.interfaces import DatasetServices, HostServices

    names: set[str] = set()
    for klass in DatasetServices.__mro__:
        if klass.__name__ in {"Protocol", "Generic", "object"}:
            continue
        names |= {name for name in vars(klass) if not name.startswith("_")}
    assert HostServices in DatasetServices.__mro__
    assert len(names) == 12, sorted(names)
    seam, _adapter = _seam(invoke_project_builder(tmp_path / "proj"), tmp_path / "captures")
    services = seam.session.services
    assert services is not None
    assert asyncio.iscoroutinefunction(services.dataset_publish)
    assert asyncio.iscoroutinefunction(services.dataset_lookup)


# --- the parity arm: the two context shapes cannot drift -----------------------


def test_the_host_context_mirrors_the_reference_contexts_dataset_id_kwarg() -> None:
    """D4's prevention: the SDK's own reference ``OperationContext``
    (testing.MockContext) and the host's ``HostOperationContext`` must agree
    — ``dataset_id`` is a defaulted keyword with a None default on both, so
    an adapter written against either context reads the same shape."""
    from benchweave_sdk.testing import MockContext

    for constructor in (HostOperationContext.__init__, MockContext.__init__):
        parameters = inspect.signature(constructor).parameters
        assert "dataset_id" in parameters, constructor.__qualname__
        assert parameters["dataset_id"].default is None, constructor.__qualname__
