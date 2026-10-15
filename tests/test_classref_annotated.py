"""The decode_annotated-only case: annotation lanes bind the capture
dataset binding (no decode target exists)."""

from __future__ import annotations

import json
from pathlib import Path

from benchweave_sdk.classref import derive_ui, find_reference

FIXTURES = Path(__file__).parent / "fixtures" / "classref"
REFERENCE = find_reference("otdp.logic_analyser/1.0.0")


def test_annotation_only_lanes_bind_capture() -> None:
    descriptor = json.loads((FIXTURES / "descriptor-f1-da.json").read_bytes())
    del descriptor["actions"]["otdp.logic_analyser.decode/1.0.0"]
    derived = derive_ui(
        json.dumps(descriptor).encode(), REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f1-da.json",
    )
    plot = derived.manifest["pages"][0]["plots"][0]
    assert len(plot["decoder_lanes"]) == 1
    assert plot["decoder_lanes"][0]["binding_id"] == "capture"
    row = derived.control_plan["otdp.logic_analyser.decode_annotated/1.0.0"]
    assert row["level"] == "L4"
