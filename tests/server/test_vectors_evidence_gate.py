# author: Stephen Eaton
"""Issue #566 row 11 at the connect seam: the vectors evidence gate.

The standalone host parses ``vectors.json`` at connect time
(``session.vectors_script``); an evidence claim the file cannot back must
surface as the typed ``not_ready`` refusal with the
``standalone_vectors_evidence_*:`` family — the same family-D shape as the
dialect/encoding/row refusals in ``test_mock_bytestream.py``, never a raw
exception and never a silent pass.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from benchweave_sdk_server.errors import SeamError
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.session import load_plugin_project, mock_plugin_session

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "binary_frames_plugin"
DEV = "frames_dev"


def call(seam: StandaloneSeam, operation: str, arguments: dict | None = None) -> dict:
    return asyncio.run(seam.call(operation, arguments or {}))


def _with_vectors(tmp_path: Path, mutate) -> Path:
    """A copy of the fixture whose vectors.json ``mutate`` rewrote."""
    root = tmp_path / "proj"
    shutil.copytree(FIXTURE, root)
    path = root / "src" / "binary_frames_demo" / "vectors.json"
    document = json.loads(path.read_text())
    mutate(document)
    path.write_text(json.dumps(document, indent=2) + "\n")
    return root


def _seam(root: Path) -> StandaloneSeam:
    return StandaloneSeam(mock_plugin_session(load_plugin_project(root)), transport_kind="mock")


def test_hardware_claim_without_recorded_rows_is_not_ready(tmp_path: Path) -> None:
    def mutate(document: dict) -> None:
        document["evidence"] = "hardware"

    with pytest.raises(SeamError) as caught:
        call(_seam(_with_vectors(tmp_path, mutate)), "device_connect", {"device_id": DEV})
    assert caught.value.code == "not_ready"
    assert "standalone_vectors_evidence_unrecorded:" in caught.value.message


def test_row_hardware_claim_without_recorded_slot_is_not_ready(tmp_path: Path) -> None:
    def mutate(document: dict) -> None:
        document["evidence"] = "hardware"
        document["exchanges"][0]["evidence"] = "hardware"

    with pytest.raises(SeamError) as caught:
        call(_seam(_with_vectors(tmp_path, mutate)), "device_connect", {"device_id": DEV})
    assert caught.value.code == "not_ready"
    assert "standalone_vectors_evidence_unrecorded:" in caught.value.message
    assert "identify" in caught.value.message


def test_unknown_evidence_value_is_not_ready(tmp_path: Path) -> None:
    def mutate(document: dict) -> None:
        document["evidence"] = "captured"

    with pytest.raises(SeamError) as caught:
        call(_seam(_with_vectors(tmp_path, mutate)), "device_connect", {"device_id": DEV})
    assert caught.value.code == "not_ready"
    assert "standalone_vectors_evidence_unknown:" in caught.value.message


def test_recorded_hardware_row_connects_and_operates(tmp_path: Path) -> None:
    """The additive bound: a file that DOES carry hand-recorded bytes with
    provenance keeps rehearsing on the mock — the gate refuses the empty
    claim, not the honest capture."""

    def mutate(document: dict) -> None:
        document["evidence"] = "hardware"
        document["exchanges"][0]["evidence"] = "hardware"
        document["exchanges"][0]["recorded"] = {
            "when": "2026-10-26T12:00:00+08:00",
            "transport": "usb",
        }

    seam = _seam(_with_vectors(tmp_path, mutate))
    assert call(seam, "device_connect", {"device_id": DEV}) == {
        "device_id": DEV,
        "connected": True,
    }
    identity = call(seam, "device_get", {"device_id": DEV})
    assert identity["model"] == "frames-demo"
