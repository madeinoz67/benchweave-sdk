"""The operator's instance binding: one connection key, one physical endpoint.

Issue #385's mechanism (design §1.1): the standalone host's device id IS the
descriptor's ``connection_key``, and until this module existed the physical
endpoint existed only as a CLI string — nothing persisted it, a restart
re-typed it, and two identical boards returned two indistinguishable
discovery rows. This module owns ONE document, ``device-bindings.json``,
holding the operator's pick WITH its evidence: which discriminator the
bench's own scan supported, the port observed at bind, the identity the
scan confirmed, and when and through which surface the pick was made.

NOT the gateway's ``transport-settings.json`` shape, deliberately: that
document is administrator ADMISSION (which provider contract serves a key)
and is endpoint-free by standing obligation (the gateway's
drift-and-obligations row 16); this one is the operator's INSTANCE pick
(which physical thing). Different acts, different documents. When the
gateway's deferred commissioning shape reopens, this row — discriminator,
staleness semantics, provenance fields — is the promotion candidate.

Resolution (§1.4) is pure over a row plus an enumeration: enumerating ports
opens no port and transmits nothing, so the NFR-O3 write-bar is untouched.
Writes are atomic (temp file in the same directory, fsync of the file
before the rename) but carry NO digest machinery: this is operator state,
not evidence. Refusals are prefixed and machine-matchable (STD-4's
posture): ``standalone_binding_unreadable:`` (a file that cannot be read,
parsed, or is over the cap) and ``standalone_binding_schema:`` (a document
or row the closed schema refuses, duplicates included — never last-wins).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .library import _pid_is_dead
from .serial import _identity_int, _port_name

#: The environment override in ``capture_root``'s exact family (Decision 9):
#: explicit argument over environment over ``device-bindings.json`` under
#: the current working directory.
_ENV_BINDINGS = "BENCHWEAVE_STANDALONE_BINDINGS"

#: The document byte cap, the admission-document family's 1 MiB: a planted
#: huge file refuses at load, never a mid-request traceback.
_MAX_BINDINGS_BYTES = 1_048_576

#: The one config version this store understands.
CONFIG_VERSION = "1"

#: The corpus's own connection-key pattern (the descriptor schema's
#: transport defs) — a lowercase identifier, mirrored not reinvented. The
#: same shape governs ``plugin_package`` (scaffold packages are lowercase
#: identifiers) and the short enum-ish words (``transport``, ``bound_via``).
_KEY_PATTERN = r"^[a-z][a-z0-9_]*$"

#: A USB id as the descriptor's ``x-standalone-usb-vid``/``-pid`` keys spell
#: it: base-16 with an optional 0x prefix (the resolver parses both sides
#: through the same ``_identity_int`` the discovery filter uses).
_USB_ID_PATTERN = r"^(0x)?[0-9a-fA-F]{1,4}$"

#: An OS port path: any non-NUL printable run, bounded. POSIX slashes,
#: Windows drives and backslashes all pass; a NUL or an empty string never
#: names a port.
_PATH_PATTERN = r"^[^\x00\n\r]{1,1024}$"

#: The stamp shape the host's own ``utc_now`` emits (ISO-8601, Z or an
#: explicit offset) — same shape as the capture sidecar's ``at``.
_STAMP_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"

#: The confirmed pick's evidence. manufacturer and model are the
#: confirm-by-identify conjuncts and ride on the discovery row the pick is
#: cross-checked against. firmware is null because the row IS the wire
#: shape (issue #385 §1.2 widened it with port_path/usb_serial only): the
#: scan's identify answer carried firmware, but the host retains the ROW,
#: not the answer — an honest null, never a fabricated one.
_IDENTITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "manufacturer": {"type": "string", "minLength": 1, "maxLength": 256},
        "model": {"type": "string", "minLength": 1, "maxLength": 256},
        "firmware": {"type": ["string", "null"], "maxLength": 256},
    },
    "required": ["manufacturer", "model", "firmware"],
    "additionalProperties": False,
}

_BINDING_ROW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "connection_key": {"type": "string", "pattern": _KEY_PATTERN},
        "plugin_package": {"type": "string", "pattern": _KEY_PATTERN},
        "transport": {"type": "string", "pattern": _KEY_PATTERN},
        "endpoint_kind": {"enum": ["usb_serial", "port_path"]},
        "usb_serial": {
            "type": ["string", "null"],
            "pattern": "^[^\\x00]{1,256}$",
        },
        "vid": {"type": ["string", "null"], "pattern": _USB_ID_PATTERN},
        "pid": {"type": ["string", "null"], "pattern": _USB_ID_PATTERN},
        "port_path": {"type": "string", "pattern": _PATH_PATTERN},
        "identity": _IDENTITY_SCHEMA,
        "bound_at": {"type": "string", "pattern": _STAMP_PATTERN},
        "bound_via": {"type": "string", "pattern": _KEY_PATTERN},
    },
    "required": [
        "connection_key",
        "plugin_package",
        "transport",
        "endpoint_kind",
        "usb_serial",
        "vid",
        "pid",
        "port_path",
        "identity",
        "bound_at",
        "bound_via",
    ],
    "additionalProperties": False,
    "allOf": [
        {
            # usb_serial rows carry the serial they key on (§1.3): a null
            # serial on a usb_serial row is a discriminator that never
            # chose itself.
            "if": {
                "properties": {"endpoint_kind": {"const": "usb_serial"}},
                "required": ["endpoint_kind"],
            },
            "then": {
                "properties": {"usb_serial": {"type": "string", "minLength": 1}}
            },
        },
        {
            # port_path rows key on the path alone: the USB fields ride as
            # nothing at all — present-but-null, the closed shape's honest
            # "not the key" spelling.
            "if": {
                "properties": {"endpoint_kind": {"const": "port_path"}},
                "required": ["endpoint_kind"],
            },
            "then": {
                "properties": {
                    "usb_serial": {"type": "null"},
                    "vid": {"type": "null"},
                    "pid": {"type": "null"},
                }
            },
        },
    ],
}

_DOCUMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "config_version": {"const": CONFIG_VERSION},
        "bindings": {"type": "array", "items": _BINDING_ROW_SCHEMA},
    },
    "required": ["config_version", "bindings"],
    "additionalProperties": False,
}

_ROW_VALIDATOR = Draft202012Validator(_BINDING_ROW_SCHEMA)
_DOCUMENT_VALIDATOR = Draft202012Validator(_DOCUMENT_SCHEMA)


class BindingError(RuntimeError):
    """The connect-time binding refusals' base. ``RuntimeError`` so the
    session's connect path passes it through UNWRAPPED (its own
    ``except RuntimeError: raise`` clause) — a typed binding refusal is not
    a plugin-connect failure to be re-wrapped message-poor (§0's
    stale-open finding), and the seam maps it to ``not_ready`` with the
    ``binding_absent``/``binding_stale`` reason."""

    pass


class BindingAbsent(BindingError):
    """No row exists for ``(plugin_package, connection_key)``: the host
    serves binding-pending and the operator must scan and pick (§1.4 case
    2)."""


class BindingStale(BindingError):
    """The bound endpoint no longer resolves: the USB serial is absent (or
    duplicated — ambiguity is staleness, never a guess), or the bound path
    is gone from a fresh enumeration. The operator must scan and re-pick."""


def _dead_pid() -> int:
    """A pid that provably holds no live process here (the library lock
    tests' own finder, mirrored for this module's stale-lock arm)."""
    pid = os.getpid() - 1
    while pid > 1:
        if _pid_is_dead(pid):
            return pid
        pid -= 1
    raise RuntimeError("no dead pid found to test the stale-lock path")


#: How long a writer waits for a live writer's per-write lock before
#: refusing (the lock scopes ONE merge+write — milliseconds in practice;
#: the budget only needs to outlast a slow fsync, never an operator).
_LOCK_WAIT_S = 5.0


@contextmanager
def _write_lock(path: Path) -> Iterator[None]:
    """The per-write exclusive lockfile over one bindings document.

    The ``library.lock`` precedent's mechanics (``O_CREAT | O_EXCL``, the
    holder's pid inside, a provably-dead holder's lock stolen), scoped to
    ONE write instead of the store's lifetime: two live writers serialise
    here for the re-read-and-merge span, so neither's full-document
    rewrite can erase the other's rows (the trust-3/drift-1 fold). A LIVE
    holder is waited out (bounded); an unprovable one is refused loudly
    with ``standalone_binding_locked:`` — conservative refuse, never steal.
    """
    lock = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + _LOCK_WAIT_S
    while True:
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError as taken:
            try:
                holder = json.loads(lock.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                holder = None
            pid = holder.get("pid") if isinstance(holder, dict) else None
            if isinstance(pid, int) and _pid_is_dead(pid):
                # A crashed writer's lock must not wedge the document.
                with suppress(OSError):
                    lock.unlink()
                continue
            if time.monotonic() >= deadline:
                shown = pid if isinstance(pid, int) else "unknown"
                raise ValueError(
                    f"standalone_binding_locked: another writer holds "
                    f"{lock} (pid {shown}); it refused to clear within "
                    f"{_LOCK_WAIT_S}s"
                ) from taken
            time.sleep(0.01)
    try:
        os.write(handle, json.dumps({"pid": os.getpid()}).encode("utf-8"))
        yield
    finally:
        os.close(handle)
        with suppress(OSError):
            lock.unlink()


def bindings_path(explicit: Path | None = None) -> Path:
    """Resolve the bindings document's path.

    Precedence: an explicit argument over the
    ``BENCHWEAVE_STANDALONE_BINDINGS`` environment variable over
    ``device-bindings.json`` under the current working directory — the
    ``capture_root`` family (Decision 9), same words, same posture: the
    standalone's state files are one family. A resolved path inside the
    installed package tree (the package PARENT — all of site-packages, or
    ``src/`` in a checkout) is refused loudly: a reinstall or upgrade wipes
    it. A set-but-empty environment value is refused rather than falling
    back.
    """
    if explicit is not None:
        path = Path(explicit)
    else:
        from_environment = os.environ.get(_ENV_BINDINGS)
        if from_environment is not None and not from_environment.strip():
            raise ValueError(
                f"standalone_binding_path: {_ENV_BINDINGS} is set but empty or "
                f"whitespace-only ({from_environment!r}); unset it to use "
                "device-bindings.json under the working directory, or set "
                "it to a file path"
            )
        path = (
            Path(from_environment)
            if from_environment
            else Path.cwd() / "device-bindings.json"
        )
    resolved = path.resolve()
    package_parent = Path(__file__).resolve().parent.parent
    if resolved.is_relative_to(package_parent):
        raise ValueError(
            f"standalone_binding_path: bindings file inside the installed "
            f"package tree is refused: {resolved} is under {package_parent}; "
            "a reinstall or upgrade wipes it — pass an explicit path or set "
            f"{_ENV_BINDINGS}"
        )
    return resolved


def _read_rows(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """The document at ``path`` as validated rows; a missing file is empty.

    The ONE reader both the constructor and every write's merge go through
    (the trust-3/drift-1 fold): a write re-reads through this, so the load
    and the merge refuse with the same typed prefixes — never a silently
    overwritten document, never a divergent second validation."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ValueError(
            f"standalone_binding_unreadable: {path}: {exc}"
        ) from exc
    if len(raw) > _MAX_BINDINGS_BYTES:
        raise ValueError(
            f"standalone_binding_unreadable: {path}: {len(raw)} bytes "
            f"exceeds the {_MAX_BINDINGS_BYTES}-byte cap"
        )
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(
            f"standalone_binding_unreadable: {path}: {exc}"
        ) from exc
    findings = sorted(
        _DOCUMENT_VALIDATOR.iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if findings:
        first = findings[0]
        raise ValueError(
            f"standalone_binding_schema: {path}: "
            f"{list(first.absolute_path)}: {first.message}"
        )
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in document["bindings"]:
        key = (row["plugin_package"], row["connection_key"])
        if key in rows:
            raise ValueError(
                f"standalone_binding_schema: {path}: duplicate binding "
                f"for plugin {key[0]!r} connection key {key[1]!r}; "
                "rows are unique per plugin and key, never last-wins"
            )
        rows[key] = dict(row)
    return rows


def utc_now() -> str:
    """The real UTC now, in the host's stamp shape (the services' own)."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def usb_id_hex(value: int | None) -> str | None:
    """A USB id as the document's hex-string spelling (``1a86`` — the
    descriptor's own ``x-standalone-usb-vid`` style); ``None`` passes
    through, because a candidate without the id constrains nothing."""
    if value is None:
        return None
    return format(int(value), "x")


class BindingStore:
    """One ``device-bindings.json``: loaded typed, mutated in memory, and
    written atomically. Rows are unique by ``(plugin_package,
    connection_key)``; a duplicate refuses at load, never last-wins. The
    in-memory rows are the truth for this process's READS (a bind through
    this store is visible to the next resolution without a reload); every
    WRITE re-reads and merges under the per-write lock, so a second process
    sharing the document keeps its rows (trust-3/drift-1 — last-writer-wins
    per key, never per document)."""

    def __init__(self, path: Path, rows: dict[tuple[str, str], dict[str, Any]]) -> None:
        self._path = path
        self._rows = rows

    @classmethod
    def open(cls, path: Path) -> BindingStore:
        """Load and validate the document at ``path``; a missing file is an
        empty store (the binding-pending start). Refuses with
        ``standalone_binding_unreadable:`` (unreadable, over the cap,
        unparseable) or ``standalone_binding_schema:`` (schema violation,
        duplicate row) — at construction, never mid-request."""
        return cls(path, _read_rows(path))

    @property
    def path(self) -> Path:
        return self._path

    def rows(self) -> list[dict[str, Any]]:
        """Every row, sorted by ``(plugin_package, connection_key)`` — the
        written document's stable order."""
        return [self._rows[key] for key in sorted(self._rows)]

    def get(self, plugin_package: str, connection_key: str) -> dict[str, Any] | None:
        """The row for one plugin and key, or ``None`` (binding-pending)."""
        return self._rows.get((plugin_package, connection_key))

    def bind(self, row: dict[str, Any]) -> None:
        """Upsert one row (the operator's pick) and write the document
        atomically. The row is validated against the closed schema BEFORE
        any write: a refused row leaves the file untouched. The write takes
        the per-write lock and MERGES: rows another process wrote since this
        store opened survive (their keys), this row wins its own key —
        last-writer-wins per KEY, never per document (trust-3/drift-1)."""
        findings = sorted(
            _ROW_VALIDATOR.iter_errors(row),
            key=lambda error: list(error.absolute_path),
        )
        if findings:
            first = findings[0]
            raise ValueError(
                f"standalone_binding_schema: {self._path}: "
                f"{list(first.absolute_path)}: {first.message}"
            )
        with _write_lock(self._path):
            self._merge_foreign_rows()
            self._rows[(row["plugin_package"], row["connection_key"])] = dict(row)
            self._write()

    def unbind(self, plugin_package: str, connection_key: str) -> bool:
        """Remove one row and write; ``False`` when no row existed. The
        same locked merge as bind: a row another process bound is visible
        to this unbind — the operator's one document, not each process's
        private view."""
        with _write_lock(self._path):
            self._merge_foreign_rows()
            if self._rows.pop((plugin_package, connection_key), None) is None:
                return False
            self._write()
            return True

    def _merge_foreign_rows(self) -> None:
        """Fold the document's CURRENT rows into memory, foreign keys only
        (this process's rows win theirs — its picks are the newer ones for
        its own keys). Called under the write lock, immediately before the
        write, so the rewrite carries every live row."""
        foreign = _read_rows(self._path)
        for key, row in foreign.items():
            self._rows.setdefault(key, row)

    def _write(self) -> None:
        """The atomic write: temp file in the same directory, fsync of the
        file, then ``os.replace``. A leftover ``.tmp`` from a killed write
        is inert by construction — load reads only the named file, and the
        next write reuses (replaces) the same temp name."""
        payload = json.dumps(
            {"config_version": CONFIG_VERSION, "bindings": self.rows()},
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._path.with_name(self._path.name + ".tmp")
        with temp.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, self._path)


def resolve_endpoint(
    row: dict[str, Any], enumerate_ports: Callable[[], Iterable[Any]]
) -> str:
    """The §1.4 resolution algorithm, pure over one row plus an enumeration
    (a read-only OS query that opens no port and transmits nothing).

    - ``usb_serial`` rows resolve to the CURRENT path of the port whose
      ``(serial_number, vid, pid)`` matches the row's conjuncts (a null
      vid/pid in the row does not constrain). Zero matches or TWO OR MORE
      are :class:`BindingStale` — ambiguity is staleness, never a guess,
      and no fallback to any surviving same-class candidate ever runs.
    - ``port_path`` rows resolve to the stored path when a fresh
      enumeration still lists it; an absent path is :class:`BindingStale`.
      A path that enumerates but refuses to OPEN is the opener's own
      ``standalone_plugin_connect:`` refusal — distinguished here, before
      any port opens.
    """
    if row["endpoint_kind"] == "usb_serial":
        wanted = str(row["usb_serial"])
        want_vid = _identity_int(row.get("vid"))
        want_pid = _identity_int(row.get("pid"))
        matches = [
            _port_name(port)
            for port in enumerate_ports()
            if str(getattr(port, "serial_number", None) or "") == wanted
            and (want_vid is None or _identity_int(getattr(port, "vid", None)) == want_vid)
            and (want_pid is None or _identity_int(getattr(port, "pid", None)) == want_pid)
        ]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise BindingStale(
                f"the bound endpoint is stale: no enumerated port carries "
                f"USB serial {wanted!r}; scan and re-pick the device"
            )
        raise BindingStale(
            f"the bound endpoint is stale: USB serial {wanted!r} matches "
            f"{len(matches)} ports ({', '.join(sorted(matches))}); scan "
            "and re-pick the device"
        )
    path = str(row["port_path"])
    if path not in {_port_name(port) for port in enumerate_ports()}:
        raise BindingStale(
            f"the bound endpoint is stale: port path {path!r} is absent "
            "from a fresh enumeration; scan and re-pick the device"
        )
    return path


def binding_endpoint(
    store: BindingStore,
    plugin_package: str,
    connection_key: str,
    enumerate_ports: Callable[[], Iterable[Any]],
) -> Callable[[], str]:
    """The binding-backed endpoint source (§1.4): consulted at connect
    time, so a rebind changes the next connection's port. No row is
    :class:`BindingAbsent` — the connect-time refusal, not a startup one:
    the host serves binding-pending precisely so the UI can render the
    pick."""

    def source() -> str:
        row = store.get(plugin_package, connection_key)
        if row is None:
            raise BindingAbsent(
                f"no endpoint is bound for device {connection_key!r} "
                f"(plugin {plugin_package}); scan for devices and pick a "
                "port, or pass --device <path>"
            )
        return resolve_endpoint(row, enumerate_ports)

    return source
