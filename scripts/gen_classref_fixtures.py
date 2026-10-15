"""Generate the classref acceptance fixtures (record §3.5, gateway #463 L2).

Deterministic; re-run to regenerate. All names invented (Veridian family).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "classref"

CHANNEL_COUNTS = {"f1": 2, "f2": 32, "f3a": 2, "f3b": 34}


def channel(index: int, role: str = "digital_input") -> dict:
    return {
        "id": f"d{index}",
        "label": f"Data line {index}",
        "role": role,
        "quantities": ["digital_level"],
        "parameter_names": [],
    }


def actions(*, decode: bool, vendor: bool, trigger: bool = False) -> dict:
    def row(side_effect: str) -> dict:
        return {
            "binding": {"kind": "adapter", "key": "fixture"},
            "input_constraints": {},
            "timeout_ms": 30000,
            "side_effect": side_effect,
            "cancellable": True,
            "retry": "never",
        }

    rows = {
        "otdp.logic_analyser.configure/1.0.0": row("state_change"),
        "otdp.logic_analyser.arm/1.0.0": row("state_change"),
        "otdp.logic_analyser.fetch/1.0.0": row("none"),
        "otdp.logic_analyser.abort/1.0.0": row("state_change"),
    }
    if trigger:
        rows["otdp.logic_analyser.trigger/1.0.0"] = row("state_change")
    if decode:
        rows["otdp.logic_analyser.decode/1.0.0"] = row("none")
    if vendor:
        rows["com.veridian-labs.auto-threshold/1.0.0"] = row("state_change")
    return rows


def descriptor(name: str, count: int, *, decode: bool, vendor: bool, trigger: bool = False,
               constraints: dict | None = None, decoders: list | None = None) -> dict:
    doc = {
        "otdp_version": "0.2.3",
        "descriptor_version": "1.0.0",
        "id": f"dev.veridian.{name}-la",
        "display_name": f"Veridian LA-32 {name} fixture",
        "description": "Synthetic SDK acceptance fixture; not a real device.",
        "identity": {
            "strategy": "adapter",
            "manufacturer": "Veridian Instruments",
            "model": f"LA-32-{name.upper()}",
            "firmware_policy": "listed",
            "supported_firmware": ["1.0"],
        },
        "integration": {
            "mode": "adapter",
            "adapter": {
                "entry_point": f"fixture_{name}:create_plugin",
                "api_version": "1.1",
                "version": "1.0.0",
                "dependencies": [],
                "permissions": ["scoped_transport", "artifact_writer"],
            },
        },
        "transport": {
            "type": "serial",
            "connection_key": "capture_device",
            "settings": {
                "baud": 115200,
                "data_bits": 8,
                "parity": "none",
                "stop_bits": 1,
                "rtscts": False,
                "max_frame_bytes": 65536,
            },
        },
        "capabilities": ["identify", "invoke"],
        "operations": {
            "identify": {
                "timeout_ms": 2000,
                "side_effect": "none",
                "retry": "never",
                "cancellable": False,
                "completion": "acknowledged",
            },
            "invoke": {
                "timeout_ms": 30000,
                "side_effect": "state_change",
                "retry": "never",
                "cancellable": True,
                "completion": "acknowledged",
            },
        },
        "parameters": [],
        "required_features": [
            "otdp.core/0.1.0",
            "otdp.adapter/0.1.0",
            "otdp.profile_actions/0.1.0",
            "otdp.measurement/0.1.0",
            "otdp.logic_analyser/1.0.0",
        ],
        "provenance": {
            "sources": [
                {
                    "title": "Synthetic fixture for SDK acceptance tests",
                    "reference": "../device-classes.md",
                    "revision": "1.0.0",
                }
            ],
        },
        "channels": [channel(i) for i in range(count)],
        "profiles": ["otdp.logic_analyser/1.0.0"],
        "contracts": [
            {
                "id": "urn:otdp:profile-catalog:0.2.3",
                "path": "device-profile-catalog.json",
                "sha256": "0bb1747fe84f047dbd34e77fb6f848bc8554b0fd1776e8988c79f8185e1273a4",
            },
            {
                "id": "urn:otdp:measurement:0.2.3",
                "path": "otdp-measurement.schema.json",
                "sha256": "383fedc9af7515c17325d2abe938d3a60e23a2460a7153a710bba7fe41cf574b",
            },
        ],
        "actions": actions(decode=decode, vendor=vendor, trigger=trigger),
    }
    if constraints:
        for urn, fragment in constraints.items():
            doc["actions"][urn]["input_constraints"] = fragment
    if decoders:
        doc["decoders"] = decoders
    if vendor:
        doc["contracts"].append(
            {
                "id": "urn:veridian:vendor-catalog:1.0.0",
                "path": "vendor-catalog.json",
                "sha256": _digest("vendor-catalog.json"),
            }
        )
    return doc


def f3a_constraints() -> dict:
    return {
        "otdp.logic_analyser.configure/1.0.0": {
            "type": "object",
            "required": ["configuration_id", "channels", "sample_rate_hz",
                         "sample_count", "trigger"],
            "properties": {
                "channels": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "channel": {"type": "string"},
                            "threshold_v": {"const": 1.5},
                        },
                    },
                },
                "sample_rate_hz": {"enum": [1000000]},
            },
        }
    }


def f3b_constraints() -> dict:
    return {
        "otdp.logic_analyser.configure/1.0.0": {
            "type": "object",
            "required": ["configuration_id", "channels", "sample_rate_hz",
                         "sample_count", "trigger"],
            "properties": {
                "channels": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "channel": {"type": "string"},
                            "threshold_v": {"type": "number", "minimum": -0.5,
                                            "maximum": 5.0},
                        },
                    },
                },
                "sample_rate_hz": {"type": "number", "minimum": 1000, "maximum": 100000000},
            },
        }
    }


def _digest(name: str) -> str:
    return hashlib.sha256((OUT / name).read_bytes()).hexdigest()


def refusal_no_lanes() -> dict:
    d = descriptor("nolanes", 2, decode=False, vendor=False)
    d["channels"] = [
        {"id": "an0", "label": "Analog line 0", "role": "analogue_input",
         "quantities": ["voltage"], "parameter_names": []},
        {"id": "an1", "label": "Analog line 1", "role": "analogue_input",
         "quantities": ["voltage"], "parameter_names": []},
    ]
    return d


def refusal_lane_ceiling() -> dict:
    return descriptor("ceiling", 65, decode=False, vendor=False)


def refusal_action_absent() -> dict:
    d = descriptor("noabort", 2, decode=False, vendor=False)
    del d["actions"]["otdp.logic_analyser.abort/1.0.0"]
    return d


def f1_annotation() -> dict:
    """descriptor-f1-da: F1 plus decode_annotated declared and the uart pin."""
    import hashlib

    da = json.loads(json.dumps(descriptor("f1", 2, decode=True, vendor=True)))
    da["provenance"]["test_vectors"] = _test_vectors()
    da["id"] = "dev.veridian.f1-da-la"
    da["display_name"] = "Veridian LA-32 f1-da fixture"
    da["decoders"] = [{
        "id": "uart",
        "path": "decoder-uart.json",
        "sha256": hashlib.sha256(
            (OUT / "decoder-uart.json").read_bytes()
        ).hexdigest(),
    }]
    da["actions"]["otdp.logic_analyser.decode_annotated/1.0.0"] = {
        "binding": {"kind": "adapter", "key": "fixture"},
        "input_constraints": {},
        "timeout_ms": 30000,
        "side_effect": "none",
        "cancellable": True,
        "retry": "idempotent",
    }
    return da


def _test_vectors() -> list[dict]:
    return [{
        "id": "fixture-vectors",
        "path": "vectors-f1.json",
        "purpose": "Synthetic fixture vectors; not a device simulator",
    }]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    vendor_catalog = {
        "catalog_version": "1.0.0",
        "vendor": "com.veridian-labs",
        "actions": {
            "com.veridian-labs.auto-threshold/1.0.0": {
                "description": "Recompute the auto-threshold calibration.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "margin_ppm": {"type": "integer", "minimum": 0, "maximum": 1000},
                        "hysteresis_mv": {"type": "number", "minimum": 0.0,
                                          "maximum": 500.0},
                    },
                    "required": ["margin_ppm", "hysteresis_mv"],
                    "additionalProperties": False,
                    "$id": "urn:veridian:action:auto-threshold:1.0.0:input",
                },
                "output_schema": {"type": "object"},
                "side_effect": "state_change",
            }
        },
    }
    (OUT / "vendor-catalog.json").write_bytes(
        (json.dumps(vendor_catalog, indent=2) + "\n").encode()
    )
    specs = [
        ("f1", CHANNEL_COUNTS["f1"], dict(decode=True, vendor=True)),
        ("f2", CHANNEL_COUNTS["f2"], dict(decode=True, vendor=True)),
        ("f3a", CHANNEL_COUNTS["f3a"],
         dict(decode=False, vendor=False, constraints=f3a_constraints())),
        ("f3b", CHANNEL_COUNTS["f3b"],
         dict(decode=True, vendor=True, trigger=True, constraints=f3b_constraints(),
              decoders=[])),
    ]
    import hashlib as _hashlib

    for name, count, kwargs in specs:
        doc = descriptor(name, count, **kwargs)
        if name == "f3b":
            doc["decoders"] = [{
                "id": "uart",
                "path": "decoder-uart.json",
                "sha256": _hashlib.sha256(
                    (OUT / "decoder-uart.json").read_bytes()
                ).hexdigest(),
            }]
        doc["provenance"]["test_vectors"] = _test_vectors()
        (OUT / f"descriptor-{name}.json").write_bytes(
            (json.dumps(doc, indent=2) + "\n").encode()
        )
    for name, doc in (
        ("refusal-no-lanes", refusal_no_lanes()),
        ("refusal-lane-ceiling", refusal_lane_ceiling()),
        ("refusal-action-absent", refusal_action_absent()),
    ):
        doc["provenance"]["test_vectors"] = _test_vectors()
        (OUT / f"{name}.json").write_bytes(
            (json.dumps(doc, indent=2) + "\n").encode()
        )
    (OUT / "descriptor-f1-da.json").write_bytes(
        (json.dumps(f1_annotation(), indent=2) + "\n").encode()
    )
    print("fixtures written to", OUT)


if __name__ == "__main__":
    main()
