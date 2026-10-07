"""The binding store and resolver (issue #385 §1.1/§1.4): pure-function arms.

The store owns ONE document, ``device-bindings.json``, resolved in
``capture_root``'s exact family; the resolver is pure over a row plus an
enumeration (an enumeration opens no port and transmits nothing — NFR-O3's
write-bar is untouched). Every arm here is deterministic: the ports are
``ListPortInfo``-shaped doubles, the paths are invented.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk_server.binding import (
    BindingAbsent,
    BindingStale,
    BindingStore,
    binding_endpoint,
    bindings_path,
    resolve_endpoint,
)

_ENV = "BENCHWEAVE_STANDALONE_BINDINGS"


class UsbPort:
    """A ``ListPortInfo``-shaped double: the four fields the resolver reads."""

    def __init__(
        self,
        device: str,
        serial_number: str | None = None,
        vid: int | None = None,
        pid: int | None = None,
    ) -> None:
        self.device = device
        self.serial_number = serial_number
        self.vid = vid
        self.pid = pid


def _row(
    *,
    endpoint_kind: str = "usb_serial",
    usb_serial: str | None = "A1B2C3",
    vid: str | None = "1a86",
    pid: str | None = "7523",
    port_path: str = "/dev/match-b",
    connection_key: str = "example_device",
    plugin_package: str = "example_plugin",
) -> dict[str, Any]:
    return {
        "connection_key": connection_key,
        "plugin_package": plugin_package,
        "transport": "serial",
        "endpoint_kind": endpoint_kind,
        "usb_serial": usb_serial if endpoint_kind == "usb_serial" else None,
        "vid": vid if endpoint_kind == "usb_serial" else None,
        "pid": pid if endpoint_kind == "usb_serial" else None,
        "port_path": port_path,
        "identity": {
            "manufacturer": "SDK Example",
            "model": "demo",
            "firmware": None,
        },
        "bound_at": "2026-10-04T09:00:00Z",
        "bound_via": "ui",
    }


def _write_document(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"config_version": "1", "bindings": rows}, indent=2),
        encoding="utf-8",
    )


# --- bindings_path: the capture_root resolution family ----------------------


def test_bindings_path_explicit_wins_over_env_and_cwd(tmp_path: Path) -> None:
    explicit = tmp_path / "chosen.json"
    os.environ[_ENV] = str(tmp_path / "from-env.json")
    try:
        assert bindings_path(explicit) == explicit.resolve()
    finally:
        del os.environ[_ENV]


def test_bindings_path_env_wins_over_cwd(tmp_path: Path, monkeypatch: Any) -> None:
    from_env = tmp_path / "from-env.json"
    monkeypatch.setenv(_ENV, str(from_env))
    monkeypatch.chdir(tmp_path)
    assert bindings_path() == from_env.resolve()


def test_bindings_path_cwd_default(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    assert bindings_path() == (tmp_path / "device-bindings.json").resolve()


def test_bindings_path_empty_env_refuses(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv(_ENV, "   ")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match=_ENV):
        bindings_path()


def test_bindings_path_refuses_the_installed_package_tree(tmp_path: Path) -> None:
    """Same posture as ``capture_root``: a path under the installed package
    parent (site-packages, or ``src/`` in a checkout) is refused — a
    reinstall wipes it and inventory verification refuses unlisted files."""
    import benchweave_sdk_server.binding as binding_module

    package_parent = Path(binding_module.__file__).resolve().parent.parent
    inside = package_parent / "nested" / "device-bindings.json"
    with pytest.raises(ValueError, match="installed package tree"):
        bindings_path(inside)


# --- load: typed refusals, closed schema -------------------------------------


def test_open_missing_file_is_an_empty_store(tmp_path: Path) -> None:
    store = BindingStore.open(tmp_path / "device-bindings.json")
    assert store.rows() == []
    assert store.get("example_plugin", "example_device") is None


def test_open_loads_a_valid_document_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "device-bindings.json"
    _write_document(path, [_row()])
    store = BindingStore.open(path)
    loaded = store.get("example_plugin", "example_device")
    assert loaded is not None and loaded["port_path"] == "/dev/match-b"
    assert store.get("example_plugin", "other") is None
    assert store.get("other", "example_device") is None


def test_open_refuses_malformed_json_with_the_unreadable_prefix(
    tmp_path: Path,
) -> None:
    path = tmp_path / "device-bindings.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="standalone_binding_unreadable:"):
        BindingStore.open(path)


def test_open_refuses_an_oversize_document(tmp_path: Path) -> None:
    """The 1 MiB cap (AR-F's family): a planted huge file refuses at load,
    never a mid-request traceback."""
    path = tmp_path / "device-bindings.json"
    path.write_bytes(b'{"config_version": "1", "bindings": ["' + b"x" * (1 << 20) + b'"]}')
    with pytest.raises(ValueError, match="standalone_binding_unreadable:"):
        BindingStore.open(path)


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param({"config_version": "2"}, id="wrong-config-version"),
        pytest.param({"extra": 1}, id="unknown-top-level-key"),
        pytest.param(
            lambda row: row.pop("port_path"), id="missing-port-path"
        ),
        pytest.param(
            lambda row: row.update(endpoint_kind="firmware"), id="bad-endpoint-kind"
        ),
        pytest.param(
            lambda row: row.update(bound_at="yesterday"), id="bad-stamp"
        ),
        pytest.param(
            lambda row: row.update(connection_key=""), id="empty-connection-key"
        ),
        pytest.param(
            lambda row: row.update(usb_serial=None), id="usb-serial-row-with-null-serial"
        ),
        pytest.param(
            lambda row: (
                row.update(endpoint_kind="port_path", usb_serial="A1B2C3", vid="1a86")
            ),
            id="port-path-row-with-usb-fields",
        ),
        pytest.param(
            lambda row: row.update(identity={"manufacturer": "SDK Example"}),
            id="identity-missing-model",
        ),
        pytest.param(
            lambda row: row.update(
                identity={
                    "manufacturer": "SDK Example",
                    "model": "demo",
                    "extra": 1,
                }
            ),
            id="identity-unknown-key",
        ),
    ],
)
def test_open_refuses_schema_violations(
    tmp_path: Path, mutation: Any
) -> None:
    row = _row()
    if callable(mutation):
        mutation(row)
    else:
        document = {"config_version": "1", "bindings": [_row()]}
        document.update(mutation)
        path = tmp_path / "device-bindings.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(ValueError, match="standalone_binding_schema:"):
            BindingStore.open(path)
        return
    path = tmp_path / "device-bindings.json"
    _write_document(path, [row])
    with pytest.raises(ValueError, match="standalone_binding_schema:"):
        BindingStore.open(path)


def test_open_refuses_a_duplicate_package_and_key_pair(tmp_path: Path) -> None:
    """Rows are unique by ``(plugin_package, connection_key)`` — never
    last-wins (§1.1)."""
    path = tmp_path / "device-bindings.json"
    _write_document(
        path,
        [
            _row(port_path="/dev/match-a"),
            _row(port_path="/dev/match-b"),
        ],
    )
    with pytest.raises(ValueError, match="standalone_binding_schema:"):
        BindingStore.open(path)


# --- writes: atomic, upsert, honest leftovers --------------------------------


def test_bind_writes_a_valid_document_and_leaves_no_temp(
    tmp_path: Path,
) -> None:
    path = tmp_path / "device-bindings.json"
    store = BindingStore.open(path)
    store.bind(_row())
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["config_version"] == "1"
    assert [r["port_path"] for r in document["bindings"]] == ["/dev/match-b"]
    assert not list(path.parent.glob("*.tmp")), "the temp file is replaced, not left"


def test_bind_reloads_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "device-bindings.json"
    BindingStore.open(path).bind(_row())
    reopened = BindingStore.open(path)
    assert reopened.get("example_plugin", "example_device") is not None


def test_bind_upserts_by_package_and_key(tmp_path: Path) -> None:
    path = tmp_path / "device-bindings.json"
    store = BindingStore.open(path)
    store.bind(_row(port_path="/dev/match-a"))
    store.bind(_row(port_path="/dev/match-b"))
    document = json.loads(path.read_text(encoding="utf-8"))
    assert len(document["bindings"]) == 1
    assert document["bindings"][0]["port_path"] == "/dev/match-b"


def test_bind_refuses_a_schema_invalid_row_before_any_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "device-bindings.json"
    store = BindingStore.open(path)
    bad = _row()
    bad["endpoint_kind"] = "firmware"
    with pytest.raises(ValueError, match="standalone_binding_schema:"):
        store.bind(bad)
    assert not path.exists(), "a refused row writes nothing"


def test_unbind_leaves_a_valid_document(tmp_path: Path) -> None:
    path = tmp_path / "device-bindings.json"
    store = BindingStore.open(path)
    store.bind(_row())
    assert store.unbind("example_plugin", "example_device") is True
    assert BindingStore.open(path).rows() == []
    assert store.unbind("example_plugin", "example_device") is False


def test_a_leftover_tmp_from_a_killed_write_is_inert(tmp_path: Path) -> None:
    """AR-F: load ignores a leftover ``.tmp``; the next write replaces it."""
    path = tmp_path / "device-bindings.json"
    temp = tmp_path / "device-bindings.json.tmp"
    temp.write_text("{killed write", encoding="utf-8")
    store = BindingStore.open(path)
    assert store.rows() == [], "a leftover tmp never loads"
    store.bind(_row())
    assert json.loads(path.read_text(encoding="utf-8"))["bindings"], (
        "the next write still lands"
    )


# --- concurrent writers: re-read-and-merge (trust-3/drift-1) ------------------
#
# Two processes CAN legitimately share one device-bindings.json (two hosts,
# one working directory — the document's own rows-unique-by-key shape admits
# it). Atomic writes alone make each write crash-safe but last-writer-wins:
# a second opener's full-document rewrite silently erased the first opener's
# rows. The fold: every write re-reads the document under a per-write
# exclusive lockfile and MERGES (this process's rows win their keys; foreign
# keys survive); same-key writes stay last-writer-wins per KEY, never per
# document.


def test_two_openers_interleaved_writes_both_rows_survive(tmp_path: Path) -> None:
    """The lost-update reproduction (probe 5's shape): two stores opened
    before either wrote, one bind through each — the FILE carries both rows."""
    path = tmp_path / "device-bindings.json"
    store_one = BindingStore.open(path)
    store_two = BindingStore.open(path)
    store_one.bind(
        _row(
            connection_key="device_a",
            plugin_package="plugin_x",
            port_path="/dev/one",
        )
    )
    store_two.bind(
        _row(
            connection_key="device_b",
            plugin_package="plugin_y",
            port_path="/dev/two",
        )
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    assert [row["connection_key"] for row in document["bindings"]] == [
        "device_a",
        "device_b",
    ], "the second opener's write must not erase the first opener's row"


def test_two_openers_same_key_last_write_wins_per_key(tmp_path: Path) -> None:
    """Same-key contention resolves to the MOST RECENT pick (an operator
    re-picking through a second host), never to an erased document: the
    losing row is replaced, every other row survives."""
    path = tmp_path / "device-bindings.json"
    store_one = BindingStore.open(path)
    store_two = BindingStore.open(path)
    store_one.bind(_row(port_path="/dev/match-a"))
    store_two.bind(_row(port_path="/dev/match-b"))
    document = json.loads(path.read_text(encoding="utf-8"))
    assert [row["port_path"] for row in document["bindings"]] == ["/dev/match-b"]


def test_unbind_removes_a_row_another_process_wrote(tmp_path: Path) -> None:
    """The merge is not write-only: an unbind re-reads too, so a row another
    process bound is removable by this one (the operator's one document, not
    each process's private view)."""
    path = tmp_path / "device-bindings.json"
    store_one = BindingStore.open(path)
    store_two = BindingStore.open(path)
    store_one.bind(_row())
    assert store_two.unbind("example_plugin", "example_device") is True
    assert BindingStore.open(path).rows() == []


def test_a_write_refuses_when_the_document_turned_unreadable(
    tmp_path: Path,
) -> None:
    """The merge read is typed like the load: a document that went garbage
    between open and write refuses the write loudly (prefixed), never
    silently overwrites the operator's evidence."""
    path = tmp_path / "device-bindings.json"
    store = BindingStore.open(path)
    path.write_text("{not json anymore", encoding="utf-8")
    with pytest.raises(ValueError, match="standalone_binding_unreadable:"):
        store.bind(_row())
    assert path.read_text(encoding="utf-8") == "{not json anymore", (
        "a refused merge overwrites nothing"
    )


def test_the_write_lock_does_not_linger(tmp_path: Path) -> None:
    path = tmp_path / "device-bindings.json"
    store = BindingStore.open(path)
    store.bind(_row())
    assert not (tmp_path / "device-bindings.json.lock").exists(), (
        "the per-write lock is released with the write"
    )


def test_a_stale_lock_from_a_dead_process_is_stolen(tmp_path: Path) -> None:
    """The library.lock precedent's steal rule: a crashed writer's lockfile
    names a dead pid and must not wedge the document forever."""
    from benchweave_sdk_server.binding import _dead_pid

    path = tmp_path / "device-bindings.json"
    (tmp_path / "device-bindings.json.lock").write_text(
        json.dumps({"pid": _dead_pid()}), encoding="utf-8"
    )
    store = BindingStore.open(path)
    store.bind(_row())
    assert store.get("example_plugin", "example_device") is not None


# --- resolve: the §1.4 algorithm ---------------------------------------------


def _ports(*ports: UsbPort) -> Any:
    return lambda: list(ports)


def test_resolve_usb_serial_single_match_returns_the_current_path() -> None:
    enumerate = _ports(
        UsbPort("/dev/elsewhere", serial_number="ZZ9Z9", vid=0x1A86, pid=0x7523),
        UsbPort("/dev/moved-b", serial_number="A1B2C3", vid=0x1A86, pid=0x7523),
    )
    assert resolve_endpoint(_row(), enumerate) == "/dev/moved-b"


def test_resolve_usb_serial_zero_matches_is_stale_naming_the_serial() -> None:
    enumerate = _ports(UsbPort("/dev/elsewhere", serial_number="ZZ9Z9"))
    with pytest.raises(BindingStale, match="A1B2C3"):
        resolve_endpoint(_row(), enumerate)


def test_resolve_usb_serial_two_matches_is_stale_never_a_guess() -> None:
    enumerate = _ports(
        UsbPort("/dev/one", serial_number="A1B2C3", vid=0x1A86, pid=0x7523),
        UsbPort("/dev/two", serial_number="A1B2C3", vid=0x1A86, pid=0x7523),
    )
    with pytest.raises(BindingStale, match="2"):
        resolve_endpoint(_row(), enumerate)


def test_resolve_usb_serial_vid_conjunct_narrows_a_duplicate_serial() -> None:
    """vid/pid ride as resolution conjuncts (§1.1): a serial duplicated
    across bridge classes still resolves when the row's vid/pid pick one."""
    enumerate = _ports(
        UsbPort("/dev/clone", serial_number="A1B2C3", vid=0x10C4, pid=0xEA60),
        UsbPort("/dev/real", serial_number="A1B2C3", vid=0x1A86, pid=0x7523),
    )
    assert resolve_endpoint(_row(), enumerate) == "/dev/real"


def test_resolve_usb_serial_null_conjuncts_match_any_vid_pid() -> None:
    row = _row(vid=None, pid=None)
    assert resolve_endpoint(row, _ports(UsbPort("/dev/moved-b", serial_number="A1B2C3"))) == (
        "/dev/moved-b"
    )


def test_resolve_port_path_present_returns_the_stored_path() -> None:
    row = _row(endpoint_kind="port_path", port_path="/dev/match-b")
    enumerate = _ports(UsbPort("/dev/match-b"), UsbPort("/dev/match-a"))
    assert resolve_endpoint(row, enumerate) == "/dev/match-b"


def test_resolve_port_path_absent_is_stale_naming_the_path() -> None:
    row = _row(endpoint_kind="port_path", port_path="/dev/gone")
    with pytest.raises(BindingStale, match="/dev/gone"):
        resolve_endpoint(row, _ports(UsbPort("/dev/match-a")))


# --- the binding-backed endpoint source --------------------------------------


def test_binding_endpoint_absent_row_refuses_naming_the_key(tmp_path: Path) -> None:
    store = BindingStore.open(tmp_path / "device-bindings.json")
    source = binding_endpoint(
        store, "example_plugin", "example_device", _ports()
    )
    with pytest.raises(BindingAbsent, match="example_device"):
        source()


def test_binding_endpoint_resolves_late_through_the_store(tmp_path: Path) -> None:
    """A rebind changes the NEXT connection's port (§1.4): the source reads
    the store at call time, never a cached path."""
    store = BindingStore.open(tmp_path / "device-bindings.json")
    enumerate = _ports(
        UsbPort("/dev/match-a", serial_number="SER-A", vid=0x1A86, pid=0x7523),
        UsbPort("/dev/match-b", serial_number="SER-B", vid=0x1A86, pid=0x7523),
    )
    source = binding_endpoint(store, "example_plugin", "example_device", enumerate)
    store.bind(_row(usb_serial="SER-A", port_path="/dev/match-a"))
    assert source() == "/dev/match-a"
    store.bind(_row(usb_serial="SER-B", port_path="/dev/match-b"))
    assert source() == "/dev/match-b"


def test_bindings_path_refusals_carry_the_machine_prefix(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """drift-4 (review fold): the module's two path-resolution refusals —
    the set-but-empty environment value and the installed-package-tree
    refusal — are exit-2 serve refusals, so each carries the
    ``standalone_binding_path:`` prefix and stays machine-classifiable
    with every other prefixed refusal."""
    import benchweave_sdk_server.binding as binding_module

    monkeypatch.setenv(_ENV, "   ")
    with pytest.raises(ValueError, match=r"^standalone_binding_path:"):
        bindings_path()
    package_parent = Path(binding_module.__file__).resolve().parent.parent
    with pytest.raises(ValueError, match=r"^standalone_binding_path:"):
        bindings_path(package_parent / "nested" / "device-bindings.json")
