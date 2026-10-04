"""The rebuildable capture index over the capture root (I3b slice 2).

The design record's mechanism (issue #285, I3b): a stdlib ``sqlite3`` index
(the fork's ``library.py`` name, deliberately), rebuilt at startup by walking
the capture root — ``manifest.json`` plus ``metadata.json`` per event
directory. The index is query acceleration ONLY: everything it holds is
rebuildable from the root, and the FILE is the authority for annotation and
pin state (AR-6's RED arm — an index edit without the matching
``metadata.json`` rewrite is lost on the next rebuild, so every mutation
rewrites the file atomically: temp write, then ``os.replace``).

A lockfile in the capture root (``library.lock``, ``O_CREAT | O_EXCL`` with a
JSON pid payload) refuses a second host process over the same root — the
``serve`` and stdio-``mcp`` entry points must not become the fork's
two-writers hazard. A lock whose pid is provably dead (the crashed host) is
stolen; a lock whose payload cannot be parsed, or whose liveness cannot be
probed, is refused conservatively — an unprovable lock is treated as live.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

#: The row's column set (the design record's columns plus the disclosed
#: ``stop_reason``). ``tags`` is stored as a JSON array string.
_COLUMNS: tuple[str, ...] = (
    "capture_id",
    "started_at",
    "format",
    "byte_length",
    "sha256",
    "surface",
    "operator",
    "project",
    "pinned",
    "tags",
    "notes",
    "stop_reason",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS captures (
    capture_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    format TEXT NOT NULL,
    byte_length INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    surface TEXT,
    operator TEXT,
    project TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    tags TEXT NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL DEFAULT '',
    stop_reason TEXT
)
"""

_INDEX_NAME = "library.sqlite3"
_LOCK_NAME = "library.lock"


#: ``OpenProcess``'s minimal access right for asking a process about
#: itself, and the kernel's error for a pid it does not know — a stale
#: pid, the crashed host whose lock the steal path exists to reclaim.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_INVALID_PARAMETER = 87


def _windows_process_probe(pid: int) -> tuple[int, int]:
    """``(OpenProcess handle, GetLastError)`` — the kernel's own answer
    on win32. ``os.kill(pid, 0)`` is no liveness probe there: signal 0 is
    refused with ``WinError 87`` before anything is asked, so the kernel
    is asked directly instead. ctypes is imported in-function — the POSIX
    hosts never pay for the win32 leg (the seam's lazy-import posture)."""
    if sys.platform != "win32":  # pragma: no cover - the POSIX leg
        return 0, 0
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return 0, int(kernel32.GetLastError())
    kernel32.CloseHandle(handle)
    return int(handle), 0


def _windows_pid_is_dead(pid: int) -> bool:
    """The Windows liveness mapping: a handle is a live pid; a 0 handle
    with ``ERROR_INVALID_PARAMETER`` (87) is a pid the kernel does not
    know — provably dead; any other failure is unprovable."""
    handle, error = _windows_process_probe(pid)
    if handle:
        return False
    return error == _ERROR_INVALID_PARAMETER


def _pid_is_dead(pid: int) -> bool:
    """Whether ``pid`` provably holds no live process here.

    POSIX: signal 0 probes existence without delivering anything:
    ``ProcessLookupError`` is a provably dead pid (steal the lock);
    ``PermissionError`` is a LIVE pid under another user; a clean return is
    a live pid. Windows: the ``OpenProcess`` probe above (the same
    conservative rule at the end). Anything else — a non-positive pid, an
    OS refusal — is unprovable, and an unprovable lock is treated as live
    (conservative refuse), never stolen.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_pid_is_dead(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    except OSError:
        return False
    return False


def _read_metadata(event: Path) -> dict[str, Any]:
    """The event's ``metadata.json``, ``{}`` when absent or unparseable.

    The metadata sidecar is the annotation/pin authority; a missing or
    mangled file is not a capture-library failure — the rebuild serves the
    honest defaults for every field it would have carried.
    """
    try:
        payload = json.loads((event / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_metadata(event: Path, metadata: dict[str, Any]) -> None:
    """Rewrite ``metadata.json`` atomically (temp write, then replace)."""
    payload = json.dumps(metadata, sort_keys=True).encode("utf-8")
    temp = event / "metadata.json.tmp"
    temp.write_bytes(payload)
    os.replace(temp, event / "metadata.json")


def _row_of(manifest: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """The index row for one published event (manifest + metadata merged)."""
    tags = metadata.get("tags")
    return {
        "capture_id": str(manifest.get("capture_id", "")),
        "started_at": str(manifest.get("started_at", "")),
        "format": str(manifest.get("format", "")),
        "byte_length": int(manifest.get("byte_length", 0) or 0),
        "sha256": str(manifest.get("sha256", "")),
        "surface": metadata.get("surface"),
        "operator": metadata.get("operator"),
        "project": metadata.get("project"),
        "pinned": bool(metadata.get("pinned", False)),
        "tags": list(tags) if isinstance(tags, list) else [],
        "notes": str(metadata.get("notes", "")),
        "stop_reason": metadata.get("stop_reason"),
    }


class CaptureLibrary:
    """One host process's index over one capture root.

    Constructing acquires the root's lockfile and REBUILDS the index from
    the root's event directories (directories carrying a parseable
    ``manifest.json``; anything else — files in the root, staging orphans,
    corrupt events, the index and lockfile themselves — is not a capture).
    ``close()`` releases the lock; the index file stays for the next
    process, which rebuilds it anyway.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = self._acquire_lock()
        self._connection = sqlite3.connect(self._root / _INDEX_NAME)
        self._connection.execute(_SCHEMA)
        self._connection.commit()
        self._released = False
        self.rebuild()

    @property
    def root(self) -> Path:
        """The resolved capture root this library indexes (file reads for
        ``capture_get``/``artifact_read`` go through it — the disk is the
        truth the index accelerates)."""
        return self._root

    # --- the lockfile ------------------------------------------------------

    def _acquire_lock(self) -> Path:
        lock = self._root / _LOCK_NAME
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as taken:
            holder = self._lock_holder(lock)
            pid = holder.get("pid") if holder is not None else None
            if isinstance(pid, int) and _pid_is_dead(pid):
                # A crashed host's lock must not wedge the root forever.
                lock.unlink()
                try:
                    handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except OSError as error:
                    raise RuntimeError(
                        f"standalone_library_locked: could not take {lock} "
                        f"after stealing the dead pid {pid}'s lock: {error}"
                    ) from error
            else:
                shown = pid if isinstance(pid, int) else "unknown"
                raise RuntimeError(
                    "standalone_library_locked: another library owns "
                    f"{lock} (pid {shown}); one host process per capture root"
                ) from taken
        os.write(handle, json.dumps({"pid": os.getpid()}).encode("utf-8"))
        os.close(handle)
        return lock

    @staticmethod
    def _lock_holder(lock: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(lock.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    # --- the rebuild (AR-6) -------------------------------------------------

    def rebuild(self) -> None:
        """Rebuild every row from the capture root; the root is the truth."""
        with self._connection:
            self._connection.execute("DELETE FROM captures")
            for entry in sorted(self._root.iterdir()):
                if not entry.is_dir():
                    continue
                manifest_path = entry / "manifest.json"
                if not manifest_path.is_file():
                    continue
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except ValueError:
                    # A mangled manifest is skipped, not fatal: one corrupt
                    # event must not wedge the whole index.
                    continue
                if not isinstance(manifest, dict):
                    continue
                capture_id = manifest.get("capture_id")
                if not isinstance(capture_id, str) or not capture_id:
                    # A null/missing/non-string id is not a capture: no row
                    # may be published under a str()-coerced "None" (A-F4).
                    continue
                try:
                    row = _row_of(manifest, _read_metadata(entry))
                except (TypeError, ValueError):
                    # The row coercions sit inside the guard too: a
                    # valid-JSON manifest with an uncoercible field (a
                    # byte_length of "12x") skips this row instead of
                    # escaping the constructor (A-F3).
                    continue
                self._connection.execute(
                    "INSERT OR REPLACE INTO captures VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    _row_values(row),
                )

    # --- reads --------------------------------------------------------------

    def list_captures(self) -> list[dict[str, Any]]:
        """Every published capture as a row dict, ordered by capture_id."""
        cursor = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM captures ORDER BY capture_id"
        )
        return [self._row_dict(row) for row in cursor.fetchall()]

    def get(self, capture_id: str) -> dict[str, Any] | None:
        """One capture's row, ``None`` when the index has no such id."""
        cursor = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM captures WHERE capture_id = ?",
            (capture_id,),
        )
        row = cursor.fetchone()
        return self._row_dict(row) if row is not None else None

    # --- runtime row maintenance (the lifecycle slice's interface) ----------

    def record_published(
        self, capture_id: str, manifest: dict[str, Any], metadata: dict[str, Any]
    ) -> None:
        """Insert or refresh one published capture's row (host runtime path
        — the rebuild is the same row over the same files)."""
        row = _row_of({**manifest, "capture_id": capture_id}, metadata)
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO captures VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _row_values(row),
            )

    def set_pinned(self, capture_id: str, pinned: bool) -> None:
        """Pin or unpin: index row plus the ``metadata.json`` authority."""
        self._mutate(capture_id, {"pinned": bool(pinned)})

    def set_stop_reason(self, capture_id: str, reason: str | None) -> None:
        """Record how the capture ended (index row plus metadata file)."""
        self._mutate(capture_id, {"stop_reason": reason})

    def update_annotation(
        self, capture_id: str, *, notes: str | None = None, tags: list[str] | None = None
    ) -> None:
        """Edit notes and/or tags (SW-54: they stay editable)."""
        fields: dict[str, Any] = {}
        if notes is not None:
            fields["notes"] = notes
        if tags is not None:
            fields["tags"] = list(tags)
        if not fields:
            return
        self._mutate(capture_id, fields)

    def remove(self, capture_id: str) -> None:
        """Remove one capture: the event directory and its index row."""
        if self.get(capture_id) is None:
            raise KeyError(capture_id)
        event = self._root / capture_id
        if event.is_dir():
            shutil.rmtree(event)
        with self._connection:
            self._connection.execute(
                "DELETE FROM captures WHERE capture_id = ?", (capture_id,)
            )

    def _mutate(self, capture_id: str, metadata_fields: dict[str, Any]) -> None:
        """One mutation: refuse unknown ids, rewrite the ``metadata.json``
        authority atomically, then update every column the fields name so
        the index agrees with the file until the next rebuild."""
        if self.get(capture_id) is None:
            raise KeyError(capture_id)
        event = self._root / capture_id
        metadata = _read_metadata(event)
        metadata.update(metadata_fields)
        _write_metadata(event, metadata)
        assignments: list[str] = []
        parameters: list[Any] = []
        for name in _COLUMNS:
            if name not in metadata_fields:
                continue
            value: Any = metadata_fields[name]
            if name == "pinned":
                value = int(bool(value))
            elif name == "tags":
                value = json.dumps(list(value))
            assignments.append(f"{name} = ?")
            parameters.append(value)
        if assignments:
            with self._connection:
                self._connection.execute(
                    f"UPDATE captures SET {', '.join(assignments)} "
                    "WHERE capture_id = ?",
                    (*parameters, capture_id),
                )

    # --- plumbing -----------------------------------------------------------

    @staticmethod
    def _row_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        decoded = dict(zip(_COLUMNS, row, strict=True))
        decoded["pinned"] = bool(decoded["pinned"])
        tags = decoded["tags"]
        if isinstance(tags, str):
            try:
                decoded["tags"] = json.loads(tags)
            except ValueError:
                decoded["tags"] = []
        return decoded

    def close(self) -> None:
        """Release the root: close the index and remove the lockfile.
        Tolerates repeated calls (the lifespan close-down idempotency) — and
        never removes a lock a LATER library over the same root has since
        taken (the release flag, not the file's absence, decides)."""
        if self._released:
            return
        self._released = True
        self._connection.close()
        self._lock.unlink(missing_ok=True)


def _row_values(row: dict[str, Any]) -> tuple[Any, ...]:
    values = list(row[column] for column in _COLUMNS)
    values[_COLUMNS.index("pinned")] = int(bool(row["pinned"]))
    values[_COLUMNS.index("tags")] = json.dumps(list(row["tags"]))
    return tuple(values)
