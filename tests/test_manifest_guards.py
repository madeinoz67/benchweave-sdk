"""Manifest and lock rows are judged as strings, identically in every lane."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
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
    # Windows strips a trailing dot or space and resolves device names in any
    # directory, so these alias another file or no file at all.
    pytest.param("otdp/alias.json.", id="trailing-dot"),
    pytest.param("otdp/alias.json ", id="trailing-space"),
    pytest.param("otdp/NUL", id="device-name"),
    pytest.param("otdp/con.json", id="device-name-with-extension"),
    pytest.param("otdp/_GENERATED.txt", id="reserved-stamp-path"),
    pytest.param("otdp/_generated.TXT", id="reserved-stamp-path-other-case"),
    # On a volume with 8.3 short names enabled, the alias resolves to the stamp.
    pytest.param("otdp/_GENER~1.TXT", id="reserved-stamp-8-3-alias"),
    pytest.param("otdp/_gener~2.txt", id="reserved-stamp-8-3-alias-ordinal"),
    # Windows also resolves the superscript digit forms and the console API
    # names as devices, in any directory, with or without an extension.
    pytest.param("otdp/com¹/x.json", id="device-name-superscript"),
    pytest.param("otdp/lpt².json", id="device-name-superscript-with-extension"),
    pytest.param("otdp/conin$/x.json", id="conin-device-name"),
    pytest.param("otdp/conout$.json", id="conout-device-name"),
    # Characters a Windows filesystem cannot write at all: the write would
    # fail mid-sync on one platform for a row every guard passed.
    pytest.param("otdp/a?b.json", id="windows-invalid-question"),
    pytest.param("otdp/a*b.json", id="windows-invalid-star"),
    pytest.param("otdp/a<b.json", id="windows-invalid-lt"),
    pytest.param("otdp/a>b.json", id="windows-invalid-gt"),
    pytest.param("otdp/a|b.json", id="windows-invalid-pipe"),
    pytest.param('otdp/a"b.json', id="windows-invalid-quote"),
    pytest.param("otdp/a\x01b.json", id="windows-invalid-control-char"),
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


def test_com0_is_not_a_device_name() -> None:
    """COM0 is not in Windows' device list (COM1–COM9 are); the class stays exact."""
    _guard_path("otdp", "otdp/com0/x.json")


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
        pytest.param("NUL", id="device-name"),
        pytest.param("con.d", id="device-name-with-extension"),
        pytest.param("com¹", id="device-name-superscript"),
        pytest.param("conin$", id="conin-device-name"),
        pytest.param("otdp.", id="trailing-dot"),
        pytest.param("otdp ", id="trailing-space"),
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


def _checkout(tmp_path: Path) -> Path:
    """A copy of the committed lock and vendored tree, laid out like a checkout."""
    root = tmp_path / "checkout"
    tree = root / "src/benchweave_sdk/standards"
    tree.parent.mkdir(parents=True)
    shutil.copytree(
        REPO / "src/benchweave_sdk/standards", tree, ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copy(REPO / "standards-lock.json", root / "standards-lock.json")
    return root


def _poisoned_checkout(tmp_path: Path) -> Path:
    """A copy of the committed state whose first lock row points outside the tree.

    The out-of-tree file exists and its digest matches, so only a path guard
    can refuse it: an unguarded lane hashes the outside file and vouches for it.
    """
    root = _checkout(tmp_path)
    tree = root / "src/benchweave_sdk/standards"
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


def test_manifest_that_is_not_an_object_is_manifest_invalid(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "bundle-manifest.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="^bundle_manifest_invalid: the manifest is not"):
        _load_bundle(bundle)


# --- The standard id is guarded in every lane too, not only the rows. -----------------


def _checkout_with_lock_id(tmp_path: Path, identifier: str) -> Path:
    root = _checkout(tmp_path)
    lock = json.loads((root / "standards-lock.json").read_bytes())
    lock["standards"][0]["id"] = identifier
    (root / "standards-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    return root


def test_sync_check_lanes_refuse_a_lock_standard_id_outside_the_tree(tmp_path: Path) -> None:
    root = _checkout_with_lock_id(tmp_path, "../escaped")
    with pytest.raises(ValueError, match="^lock_invalid: standard id "):
        _verify_state(root / "standards-lock.json", root / "src/benchweave_sdk/standards")


def test_build_hook_refuses_the_same_lock_standard_id(tmp_path: Path) -> None:
    root = _checkout_with_lock_id(tmp_path, "../escaped")
    with pytest.raises(RuntimeError, match="^Unsafe vendored standard id: "):
        _hatch_build()._validate_vendored_standards(root)


@pytest.mark.parametrize(
    "identifier",
    [
        "../escaped",
        "a/b",
        f"a{BACKSLASH}b",
        "C:",
        "..",
        "",
        "NUL",
        "con.d",
        "com¹",
        "conin$",
        "otdp.",
        "otdp ",
        5,
    ],
)
def test_build_hook_and_sync_lanes_agree_id_by_id(identifier: Any) -> None:
    from benchweave_sdk.standards_sync import _identifier_problem

    assert _hatch_build()._unsafe_identifier(identifier) is True
    assert _identifier_problem(identifier) is not None


def test_both_rules_accept_every_committed_row() -> None:
    """The agreement above is about refusals; this is the other half."""
    from benchweave_sdk.standards_sync import _identifier_problem, _path_problem

    hook = _hatch_build()
    lock = json.loads((REPO / "standards-lock.json").read_bytes())
    for standard in lock["standards"]:
        assert _identifier_problem(standard["id"]) is None
        assert hook._unsafe_identifier(standard["id"]) is False
        for file in standard["files"]:
            assert _path_problem(standard["id"], file["path"]) is None, file["path"]
            assert hook._unsafe_row(standard["id"], file["path"]) is False, file["path"]


# --- A malformed lock is lock_invalid in every lane, never a bare KeyError. ------------


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda lock: lock["standards"][0]["files"][0].pop("sha256"), id="row-no-digest"
        ),
        pytest.param(lambda lock: lock["standards"][0].pop("version"), id="standard-no-version"),
        pytest.param(lambda lock: lock.__setitem__("standards", "otdp"), id="standards-not-a-list"),
    ],
)
def test_malformed_lock_rows_are_lock_invalid(tmp_path: Path, mutate: Any) -> None:
    from benchweave_sdk.standards_sync import _read_lock_file

    lock = json.loads((REPO / "standards-lock.json").read_bytes())
    mutate(lock)
    path = tmp_path / "standards-lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(ValueError, match="^lock_invalid: "):
        _read_lock_file(path)


def test_lock_that_is_not_an_object_is_lock_invalid(tmp_path: Path) -> None:
    from benchweave_sdk.standards_sync import _read_lock_file

    path = tmp_path / "standards-lock.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="^lock_invalid: "):
        _read_lock_file(path)


# --- A linked directory hides what is behind it from the sweep; packaging follows it. ---


def _link_directory(link: Path, target: Path) -> None:
    """A directory link that needs no privilege: a junction on Windows, a symlink elsewhere."""
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def _checkout_with_a_linked_directory(tmp_path: Path) -> Path:
    root = _checkout(tmp_path)
    smuggled = tmp_path / "smuggled"
    smuggled.mkdir()
    (smuggled / "unrecorded.json").write_bytes(b"{}")
    standard = json.loads((root / "standards-lock.json").read_bytes())["standards"][0]["id"]
    _link_directory(root / "src/benchweave_sdk/standards" / standard / "linked", smuggled)
    return root


def test_sync_check_lanes_refuse_a_linked_directory_in_the_tree(tmp_path: Path) -> None:
    root = _checkout_with_a_linked_directory(tmp_path)
    with pytest.raises(ValueError, match=r"^unexpected_vendored_file: .*/linked is a link$"):
        _verify_state(root / "standards-lock.json", root / "src/benchweave_sdk/standards")


def test_build_hook_refuses_a_linked_directory_in_the_tree(tmp_path: Path) -> None:
    root = _checkout_with_a_linked_directory(tmp_path)
    with pytest.raises(RuntimeError, match=r"^unexpected_vendored_file: .*/linked is a link$"):
        _hatch_build()._validate_vendored_standards(root)


def test_wheel_force_include_places_the_lock_where_verify_installed_reads_it() -> None:
    """verify_installed reads <package>/standards-lock.json; only pyproject puts it there."""
    import tomllib

    from benchweave_sdk.standards_sync import LOCK_NAME

    with (REPO / "pyproject.toml").open("rb") as handle:
        wheel = tomllib.load(handle)["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == ["src/benchweave_sdk"]
    assert wheel["force-include"] == {LOCK_NAME: f"benchweave_sdk/{LOCK_NAME}"}


# --- An empty bundle has no rows to guard; the writer must not be the lane that
# decides an empty corpus is valid. -----------------------------------------------------


@pytest.mark.parametrize(
    "standards_value",
    [
        pytest.param([], id="empty-list"),
        pytest.param({}, id="empty-dict"),
        pytest.param(None, id="absent"),
    ],
)
def test_an_empty_standards_list_is_refused_at_the_manifest_gate(
    tmp_path: Path, standards_value: Any
) -> None:
    """No row ever reaches a guard, so only the list itself can be refused."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "bundle-manifest.json").write_text(
        json.dumps({"bundle_version": 1, "standards": standards_value}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="^bundle_manifest_invalid: the standards list"):
        _load_bundle(bundle)


def test_an_empty_bundle_cannot_exchange_the_vendored_tree_for_an_empty_one(
    tmp_path: Path,
) -> None:
    """End to end: the wipe. An empty manifest used to pass every guard, the
    sync would swap in an empty tree and write an empty lock, and every
    verification lane refuses that state only after the destruction."""
    from benchweave_sdk.standards_sync import sync

    root = _checkout(tmp_path)
    tree = root / "src/benchweave_sdk/standards"
    before = sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*") if p.is_file())
    assert before  # the checkout copy carries the real vendored tree
    bundle = tmp_path / "empty-bundle"
    bundle.mkdir()
    (bundle / "bundle-manifest.json").write_text(
        json.dumps({"bundle_version": 1, "standards": []}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="^bundle_manifest_invalid: the standards list"):
        sync(bundle, root)
    after = sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*") if p.is_file())
    assert after == before


def test_duplicate_ids_that_differ_only_by_normalization_are_refused(
    tmp_path: Path,
) -> None:
    """macOS and Windows resolve NFC and NFD spellings to one directory; a
    duplicate that differs only by normalization form collapses there while
    the lock vouches for names that do not exist separately on Linux."""
    import unicodedata

    nfc = "café"
    nfd = "café"
    assert nfc != nfd
    assert unicodedata.normalize("NFC", nfc) == unicodedata.normalize("NFC", nfd)
    bundle = _bundle(tmp_path, [_standard(nfc, []), _standard(nfd, [])])
    with pytest.raises(ValueError, match="^bundle_manifest_invalid: duplicate standard id"):
        _load_bundle(bundle)


# --- One sync at a time: the swap's guarantees are single-flight. ----------------------


def _valid_bundle(tmp_path: Path) -> Path:
    """A one-standard bundle whose bytes match its digest claim."""
    digest = hashlib.sha256(b"{}").hexdigest()
    bundle = _bundle(tmp_path, [_standard("otdp", [{"path": "otdp/x.json", "sha256": digest}])])
    (bundle / "files" / "otdp").mkdir(parents=True)
    (bundle / "files" / "otdp" / "x.json").write_bytes(b"{}")
    return bundle


def test_a_live_sync_lock_is_refused_with_its_pid(tmp_path: Path) -> None:
    from benchweave_sdk.standards_sync import STAGING_DIR, sync

    root = _checkout(tmp_path)
    lock = root / STAGING_DIR / "lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(f"{os.getpid()} 0\n", encoding="utf-8")
    with pytest.raises(
        ValueError, match=f"sync_staging_blocked: another sync .pid {os.getpid()}."
    ):
        sync(_valid_bundle(tmp_path), root)
    assert lock.exists()  # a refused sync never deletes another owner's lock


def test_a_stale_lock_from_a_dead_owner_is_reclaimed(tmp_path: Path) -> None:
    from benchweave_sdk.standards_sync import STAGING_DIR, sync

    root = _checkout(tmp_path)
    probe = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True
    )
    dead_pid = int(probe.stdout.strip())
    lock = root / STAGING_DIR / "lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(f"{dead_pid} 0\n", encoding="utf-8")
    report = sync(_valid_bundle(tmp_path), root)
    assert report.changed == ("otdp",)  # the sync ran; the lock was not in its way
    assert not lock.exists()  # the owner cleans up its own lock

