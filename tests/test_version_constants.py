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

import pytest

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


# --- #215 fix wave F3: import survives tree/lock skew; the load names the drift. ---


def _lock_with_an_unservable_row() -> dict[str, Any]:
    """The committed lock plus one fake otdp@0.2.3 row whose files point at a
    directory the vendored tree does not carry (the F3 plant)."""
    import copy

    lock = copy.deepcopy(LOCK)
    template = next(
        s for s in lock["standards"] if s["id"] == "otdp" and s["version"] == "0.2.2"
    )
    fake = copy.deepcopy(template)
    fake["version"] = "0.2.3"
    fake["active"] = False
    fake["files"] = [
        {
            "path": file["path"].replace("otdp/0.2.2/", "otdp/0.2.3/", 1),
            "sha256": file["sha256"],
        }
        for file in template["files"]
    ]
    lock["standards"].append(fake)
    return lock


def test_a_lock_row_without_a_vendored_directory_is_a_typed_drift_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The document load refuses by name — ``served_set_drift:`` naming the
    row — never a raw ``FileNotFoundError`` out of ``iterdir``."""
    import benchweave_sdk.served as served
    import benchweave_sdk.validation as validation_module

    monkeypatch.setattr(served, "_lock_document", _lock_with_an_unservable_row)
    served.lock_rows.cache_clear()
    validation_module.contract_documents.cache_clear()
    try:
        with pytest.raises(ValueError, match="^served_set_drift: otdp@0.2.3") as refusal:
            validation_module.contract_documents()
        assert "no such directory" in str(refusal.value)
    finally:
        served.lock_rows.cache_clear()
        validation_module.contract_documents.cache_clear()


def test_import_survives_a_lock_row_without_a_vendored_directory(
    tmp_path: Path,
) -> None:
    """``import benchweave_sdk`` must not die on tree/lock skew: the version
    constants derive lazily (PEP 562), so the check/repair CLI can import and
    report the drift instead of tracebacking before dispatch.

    Touching ``OTDP_VERSION`` still answers from the lock's active row (the
    plant only adds an inactive row); touching ``ADAPTER_API_VERSION`` loads
    documents and raises the typed refusal — a ServedStateError ValueError,
    on stderr, not a ``FileNotFoundError`` traceback.
    """
    import os
    import shutil
    import subprocess
    import sys

    package = tmp_path / "benchweave_sdk"
    shutil.copytree(
        ROOT / "src/benchweave_sdk", package, ignore=shutil.ignore_patterns("__pycache__")
    )
    (package / "standards-lock.json").write_text(
        json.dumps(_lock_with_an_unservable_row()), encoding="utf-8"
    )
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    imported = subprocess.run(
        [sys.executable, "-c", "import benchweave_sdk"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert imported.returncode == 0, imported.stderr
    active = subprocess.run(
        [sys.executable, "-c", "import benchweave_sdk; print(benchweave_sdk.OTDP_VERSION)"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert active.returncode == 0, active.stderr
    assert active.stdout.strip() == "0.2.2"
    adapter = subprocess.run(
        [sys.executable, "-c", "import benchweave_sdk; benchweave_sdk.ADAPTER_API_VERSION"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert adapter.returncode != 0
    assert "FileNotFoundError" not in adapter.stderr
    assert "served_set_drift: otdp@0.2.3" in adapter.stderr
