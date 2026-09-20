"""Manifest and lock rows are judged as strings, identically in every lane."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.standards_sync import _guard_path, _load_bundle, _verify_state

REPO = Path(__file__).resolve().parents[1]
BACKSLASH = chr(92)
GOOD_DIGEST = "0" * 64


def _bundle(tmp_path: Path, standards: list[dict[str, Any]]) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    document = {"bundle_version": 1, "standards": standards}
    (bundle / "bundle-manifest.json").write_text(json.dumps(document), encoding="utf-8")
    return bundle


def _standard(identifier: Any, files: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": identifier, "version": "1.0.0", "status": "stable", "files": files}


UNSAFE_ROWS = [
    pytest.param(f"otdp/..{BACKSLASH}..{BACKSLASH}escape.json", id="backslash-traversal"),
    pytest.param("otdp" + BACKSLASH + "escape.json", id="backslash-only"),
    pytest.param("otdp/../../escape.json", id="parent-traversal"),
    pytest.param("otdp/./alias.json", id="dot-segment"),
    pytest.param("otdp//alias.json", id="empty-segment"),
    pytest.param("otdp/alias.json/", id="trailing-slash"),
    pytest.param("otdp/C:escape.json", id="drive-separator"),
    pytest.param("/otdp/absolute.json", id="absolute"),
    pytest.param("registry/0.1.0/foreign.json", id="foreign-standard"),
    pytest.param("otdp", id="no-file-component"),
]


@pytest.mark.parametrize("row", UNSAFE_ROWS)
def test_guard_path_refuses_rows_that_any_filesystem_would_resolve_elsewhere(row: str) -> None:
    """A backslash is a character to PurePosixPath and a separator to the Windows writer.

    The guard reasons about the string, so the same rows are refused on every
    platform rather than only where they happen to escape.
    """
    with pytest.raises(ValueError, match="^bundle_path_invalid: "):
        _guard_path("otdp", row)


def test_guard_path_accepts_an_ordinary_row() -> None:
    _guard_path("otdp", "otdp/0.2.0/examples/reference-psu.json")


@pytest.mark.parametrize(
    "identifier",
    [
        pytest.param("../escaped", id="parent-traversal"),
        pytest.param("a/b", id="two-segments"),
        pytest.param("a" + BACKSLASH + "b", id="backslash"),
        pytest.param("C:", id="drive"),
        pytest.param("..", id="dot-dot"),
        pytest.param("", id="empty"),
        pytest.param(5, id="not-a-string"),
    ],
)
def test_standard_ids_are_a_single_segment_even_with_no_files(
    tmp_path: Path, identifier: Any
) -> None:
    """The stamp is written at <tree>/<id>/ and a file-less standard never reaches _guard_path."""
    bundle = _bundle(tmp_path, [_standard(identifier, [])])
    with pytest.raises(ValueError, match="^bundle_manifest_invalid: standard id"):
        _load_bundle(bundle)


@pytest.mark.parametrize(
    "digest",
    [
        pytest.param("0" * 63, id="short"),
        pytest.param("A" * 64, id="uppercase"),
        pytest.param(None, id="not-a-string"),
    ],
)
def test_manifest_digests_are_64_lowercase_hex(tmp_path: Path, digest: Any) -> None:
    bundle = _bundle(tmp_path, [_standard("otdp", [{"path": "otdp/x.json", "sha256": digest}])])
    with pytest.raises(ValueError, match="^bundle_manifest_invalid: sha256 for otdp/x.json"):
        _load_bundle(bundle)


def test_manifest_row_without_a_digest_is_manifest_invalid(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, [_standard("otdp", [{"path": "otdp/x.json"}])])
    with pytest.raises(ValueError, match="^bundle_manifest_invalid: "):
        _load_bundle(bundle)


def test_well_formed_manifest_loads(tmp_path: Path) -> None:
    rows = [{"path": "otdp/x.json", "sha256": GOOD_DIGEST}]
    document = _load_bundle(_bundle(tmp_path, [_standard("otdp", rows)]))
    assert document["standards"][0]["id"] == "otdp"


# --- STD-3: a poisoned lock row is refused by every lane ------------------------------


def _poisoned_checkout(tmp_path: Path) -> Path:
    """A copy of the committed state whose first lock row points outside the tree.

    The out-of-tree file exists and its digest matches, so only a path guard
    can refuse it: an unguarded lane hashes the outside file and vouches for it.
    """
    root = tmp_path / "checkout"
    tree = root / "src/benchweave_sdk/standards"
    tree.parent.mkdir(parents=True)
    shutil.copytree(
        REPO / "src/benchweave_sdk/standards", tree, ignore=shutil.ignore_patterns("__pycache__")
    )
    lock = json.loads((REPO / "standards-lock.json").read_bytes())
    row = lock["standards"][0]["files"][0]
    identifier = lock["standards"][0]["id"]
    original = tree / row["path"]
    outside = tree.parent / "outside.json"
    outside.write_bytes(original.read_bytes())
    original.unlink()
    row["path"] = f"{identifier}/../../outside.json"
    assert hashlib.sha256(outside.read_bytes()).hexdigest() == row["sha256"]
    (root / "standards-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    return root


def test_sync_check_lanes_refuse_a_lock_row_outside_the_tree(tmp_path: Path) -> None:
    root = _poisoned_checkout(tmp_path)
    with pytest.raises(ValueError, match="^lock_invalid: path "):
        _verify_state(root / "standards-lock.json", root / "src/benchweave_sdk/standards")


def _hatch_build() -> types.ModuleType:
    """hatch_build.py with hatchling stubbed: the hook is never installed in the test env."""
    names = [
        "hatchling",
        "hatchling.builders",
        "hatchling.builders.hooks",
        "hatchling.builders.hooks.plugin",
        "hatchling.builders.hooks.plugin.interface",
    ]
    stubs = {name: types.ModuleType(name) for name in names}
    stubs[names[-1]].BuildHookInterface = object  # type: ignore[attr-defined]
    saved = {name: sys.modules.get(name) for name in names}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location(
            "_hatch_build_under_test", REPO / "hatch_build.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def test_build_hook_refuses_the_same_lock_row(tmp_path: Path) -> None:
    root = _poisoned_checkout(tmp_path)
    with pytest.raises(RuntimeError, match="^Unsafe vendored standards path: "):
        _hatch_build()._validate_vendored_standards(root)


def test_build_hook_accepts_the_committed_state() -> None:
    _hatch_build()._validate_vendored_standards(REPO)


@pytest.mark.parametrize("row", UNSAFE_ROWS)
def test_build_hook_and_sync_lanes_agree_row_by_row(row: str) -> None:
    from benchweave_sdk.standards_sync import _path_problem

    assert _hatch_build()._unsafe_row("otdp", row) is True
    assert _path_problem("otdp", row) is not None
