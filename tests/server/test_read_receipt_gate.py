# author: Stephen Eaton
"""Issue #567 row 13 at the seam: a non-standard read receipt refuses.

Before the gate, ``_op_parameter_read`` recorded ``data.get("value")`` —
None for any non-standard shape — and the readings page rendered that
None with no gate firing. The gate validates the receipt against the
vendored ``reading`` shape and the descriptor's parameter contract before
the observation ring sees it; a refusal is the typed ``unavailable``
(the PROTOCOL_ERROR mapping) with the parameter named.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk_server.errors import SeamError
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.session import (
    LoadedPlugin,
    load_plugin_project,
    mock_plugin_session,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "binary_frames_plugin"
DEV = "frames_dev"


class _ReceiptAdapter:
    """An adapter that answers identify and one parameter read from a
    canned receipt without touching the transport."""

    def __init__(self, receipt: dict[str, Any]) -> None:
        self._receipt = receipt
        self.services = None

    async def open(self, descriptor: Any, services: Any, context: Any) -> None:
        self.services = services

    async def execute(self, request: dict[str, Any], context: Any) -> dict[str, Any]:
        await context.mark_dispatch_started()
        verb = request.get("verb")
        if verb == "identify":
            return {
                "status": "ok",
                "data": {"manufacturer": "BenchWeave Labs", "model": "frames-demo"},
            }
        return {"status": "ok", "data": dict(self._receipt)}

    async def next_event(self, subscription_id: Any, context: Any) -> None:
        return None

    async def close(self, context: Any) -> None:
        self.services = None


def _seam(receipt: dict[str, Any]) -> StandaloneSeam:
    base = load_plugin_project(FIXTURE)
    plugin: LoadedPlugin = replace(
        base, adapter_factory=lambda: _ReceiptAdapter(receipt)
    )
    return StandaloneSeam(mock_plugin_session(plugin), transport_kind="mock")


def call(seam: StandaloneSeam, operation: str, arguments: dict | None = None) -> dict:
    return asyncio.run(seam.call(operation, arguments or {}))


def _receipt(**overrides) -> dict:
    receipt = {
        "parameter": "sample_avg",
        "value": 2.5,
        "unit": "V",
        "observed_at": "2026-10-26T00:00:00Z",
        "age_ms": 0,
        "quality": "valid",
        "source": "device",
    }
    receipt.update(overrides)
    return receipt


def _first_readable() -> str:
    descriptor = json.loads(
        (FIXTURE / "src" / "binary_frames_demo" / "descriptor.json").read_text()
    )
    for row in descriptor.get("parameters", []):
        if row.get("access") in ("ro", "rw"):
            return str(row["name"])
    raise AssertionError("fixture declares no readable parameter")


def test_standard_receipt_reads_clean() -> None:
    seam = _seam(_receipt(parameter=_first_readable()))
    assert call(seam, "device_connect", {"device_id": DEV})["connected"] is True
    reading = call(seam, "parameter_read", {"device_id": DEV, "parameter": _first_readable()})
    assert reading["value"] == 2.5


def test_non_standard_receipt_refuses_naming_the_parameter() -> None:
    """The defect class: a receipt with no value key used to render None
    on the readings page. Now it refuses before the ring records."""
    broken = _receipt(parameter=_first_readable())
    del broken["value"]
    seam = _seam(broken)
    assert call(seam, "device_connect", {"device_id": DEV})["connected"] is True
    with pytest.raises(SeamError) as caught:
        call(seam, "parameter_read", {"device_id": DEV, "parameter": _first_readable()})
    assert caught.value.code == "unavailable"
    assert "read_receipt_invalid:" in caught.value.message
    assert _first_readable() in caught.value.message


def test_wrong_typed_receipt_refuses() -> None:
    seam = _seam(_receipt(parameter=_first_readable(), value=[1.0]))
    assert call(seam, "device_connect", {"device_id": DEV})["connected"] is True
    with pytest.raises(SeamError) as caught:
        call(seam, "parameter_read", {"device_id": DEV, "parameter": _first_readable()})
    assert caught.value.code == "unavailable"
    assert "read_receipt_invalid:" in caught.value.message
