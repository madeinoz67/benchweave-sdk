"""Pin the public version constants to the vendored machine sources.

The constants in ``benchweave_sdk.__init__`` are prose for machines: they must
agree with the sha-pinned vendored corpus (the lock and the descriptor
schema), not with any doc claim or reset sweep. The adapter API version is
not an OTDP standard version — the descriptor schema's ``const`` is its
authority — so both pins derive their expected values from the corpus itself.
"""

import json
from pathlib import Path
from typing import Any

import benchweave_sdk
from benchweave_sdk.scaffold import descriptor_for

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "standards-lock.json").read_text(encoding="utf-8"))


def _otdp_standard() -> dict[str, Any]:
    # Multi-version serving (#203 slice 1): the lock carries several otdp
    # rows; the constant tracks the ACTIVE one (the row's marker, with the
    # derived active version as the cross-check).
    from benchweave_sdk.served import active_version

    active = active_version("otdp")
    return next(
        s for s in LOCK["standards"] if s["id"] == "otdp" and s["version"] == active
    )


def _descriptor_schema() -> dict[str, Any]:
    otdp_files = _otdp_standard()["files"]
    entry = next(f for f in otdp_files if f["path"].endswith("otdp-device-descriptor.schema.json"))
    path = ROOT / "src/benchweave_sdk/standards" / entry["path"]
    return json.loads(path.read_text(encoding="utf-8"))


def test_otdp_version_tracks_standards_lock() -> None:
    assert _otdp_standard()["version"] == benchweave_sdk.OTDP_VERSION


def test_adapter_api_version_tracks_descriptor_schema_const() -> None:
    schema = _descriptor_schema()
    expected = schema["$defs"]["adapter"]["properties"]["api_version"]["const"]
    assert isinstance(expected, str)
    assert expected == benchweave_sdk.ADAPTER_API_VERSION


def test_scaffold_descriptor_agrees_with_public_constants() -> None:
    descriptor = descriptor_for("benchweave_acme_model100")
    assert descriptor["otdp_version"] == benchweave_sdk.OTDP_VERSION
    adapter = descriptor["integration"]["adapter"]
    assert adapter["api_version"] == benchweave_sdk.ADAPTER_API_VERSION
