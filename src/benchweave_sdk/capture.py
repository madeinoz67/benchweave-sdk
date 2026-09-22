"""Standalone capture writer: the three capture services on a filesystem backend.

Plugin and device development — and bench testing — happen on machines that
never run the gateway. This module is the standalone leg of the capture
design of record (Decision 9): the same three capture methods an adapter
calls in gateway mode, over one event directory per capture on a local
filesystem.

- ``capture_root`` resolves the standalone capture root (an explicit argument
  over ``BENCHWEAVE_CAPTURE_DIR`` over ``captures/`` under the working
  directory) and refuses a root inside the installed package tree, where a
  reinstall or upgrade would wipe it and the SDK's own inventory verification
  refuses unlisted files.
- ``_valid_capture_segment`` enforces the capture_id path-segment rules
  before any filesystem call: one segment of a portable ASCII allowlist,
  bounded length, no traversal components, no Windows device-name prefixes.
- ``StandaloneCaptureWriter`` (landing with the lifecycle commits) stages
  chunk appends under ``staging/``, finalises by concatenating them into the
  primary artifact atomically (a temp file in the same directory, then
  rename — a crash across finalise leaves a ``.tmp`` remnant, never a
  half-written primary) and publishes a manifest whose digest and length are
  computed over the real bytes, and aborts by deleting only staging plus the
  in-flight primary — a published capture and ``renderings/`` survive an
  unconditional abort.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import unicodedata
from pathlib import Path
from typing import Any

_ENV_CAPTURE_DIR = "BENCHWEAVE_CAPTURE_DIR"

#: The capture_id segment alphabet: the ``safe_resource_path`` allowlist minus
#: the separator — a capture_id names ONE directory segment, so ``/`` (and
#: everything outside the allowlist, including ``\\`` and NUL) is refused at
#: the character gate, before any filesystem call.
_SEGMENT_ALPHABET = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
)
_MAX_SEGMENT_LENGTH = 64

#: Windows device names, refused case-insensitively as the PREFIX of the
#: first dot-separated component: dotted names (``nul.json``, ``con.txt``)
#: still name devices.
_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{digit}" for digit in range(1, 10)}
    | {f"LPT{digit}" for digit in range(1, 10)}
)


def capture_root(explicit: Path | None = None) -> Path:
    """Resolve the standalone capture root.

    Precedence: an explicit argument over the ``BENCHWEAVE_CAPTURE_DIR``
    environment variable over ``captures/`` under the current working
    directory (Decision 9). A resolved root inside the installed package
    tree — the package PARENT, i.e. all of site-packages, not just the
    package directory — is refused loudly: a reinstall or upgrade wipes it,
    and the SDK's own inventory verification refuses unlisted files, so run
    data does not belong there.
    """
    if explicit is not None:
        root = Path(explicit)
    else:
        from_environment = os.environ.get(_ENV_CAPTURE_DIR)
        root = Path(from_environment) if from_environment else Path.cwd() / "captures"
    resolved = root.resolve()
    package_parent = Path(__file__).resolve().parent.parent
    if resolved.is_relative_to(package_parent):
        raise ValueError(
            f"capture root inside the installed package tree is refused: {resolved} "
            f"is under {package_parent}; a reinstall or upgrade wipes it and "
            "inventory verification refuses unlisted files — pass an explicit "
            f"root or set {_ENV_CAPTURE_DIR}"
        )
    return resolved


def _valid_capture_segment(identifier: str) -> bool:
    """The capture_id path-segment rules, checked before any filesystem call.

    One segment of the ASCII allowlist, 1..64 characters, not ``.`` or ``..``,
    and not a Windows device name by case-insensitive prefix of the first
    dot-separated component. A hostile or clumsy id can no longer name a
    directory outside the capture root.
    """
    if not isinstance(identifier, str) or not 0 < len(identifier) <= _MAX_SEGMENT_LENGTH:
        return False
    if any(character not in _SEGMENT_ALPHABET for character in identifier):
        return False
    if identifier in (".", ".."):
        return False
    return identifier.split(".", 1)[0].upper() not in _DEVICE_NAMES


def _existing_event_names(root: Path) -> list[str]:
    """Existing event directory names under ``root`` (empty when absent)."""
    if not root.is_dir():
        return []
    return sorted(entry.name for entry in root.iterdir() if entry.is_dir())


def _segment_is_free(root: Path, identifier: str) -> bool:
    """NFC-normalize-then-casefold collision check against existing events."""
    wanted = unicodedata.normalize("NFC", identifier).casefold()
    for existing in _existing_event_names(root):
        if unicodedata.normalize("NFC", existing).casefold() == wanted:
            return False
    return True


#: Known-format extension map (Decision 9): ``manifest.json``'s ``format``
#: field stays the source of truth; the extension is a convenience.
_FORMAT_EXTENSIONS = {
    "waveform_f64le": ".f64",
    "raw_binary": ".bin",
    "csv": ".csv",
    "text": ".txt",
    "vcd": ".vcd",
}
_DEFAULT_EXTENSION = ".data"

#: Slice 1's declared-format set is the constructor argument ONLY: the two
#: core corpus formats by default; an empty set refuses everything. The
#: descriptor ``x-capture-formats`` wiring and runner configuration land with
#: the standalone runner, not here.
_DEFAULT_FORMATS = frozenset({"waveform_f64le", "raw_binary"})

#: Development-tooling reservation default (not a commissioned envelope).
_DEFAULT_MAX_BYTES = 16 * 1024 * 1024


def _context_is_cancelled(context: Any) -> bool:
    """Cancellation is honoured at append (spec §8); a None context never is."""
    return context is not None and bool(context.is_cancelled())


def _write_manifest(event: Path, manifest: dict[str, Any]) -> None:
    """Write ``manifest.json`` atomically (temp + rename, same directory).

    Manifest presence is the publication marker: a crash between the primary
    rename and this write leaves a complete primary and an UNPUBLISHED event.
    """
    payload = json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False).encode()
    temp = event / "manifest.json.tmp"
    temp.write_bytes(payload)
    os.replace(temp, event / "manifest.json")


def _waveform_fields(metadata: dict[str, Any]) -> dict[str, Any]:
    """Validate the mandatory waveform metadata (corpus ``$defs/captureManifest``
    allOf: ``sample_count``, ``sample_interval_s``, ``unit`` are required when
    the format is ``waveform_f64le``); presence and shape only — the
    count×8 rule is spec §7 prose the GATEWAY's G1/G4 enforce, not the
    standalone writer, which never interprets the bytes it digests."""
    fields: dict[str, Any] = {}
    sample_count = metadata.get("sample_count")
    if type(sample_count) is not int or sample_count < 1:
        raise ValueError(
            "waveform_f64le finalise requires an integer sample_count >= 1"
        )
    interval = metadata.get("sample_interval_s")
    if (
        isinstance(interval, bool)
        or not isinstance(interval, (int, float))
        or not interval > 0
        or not math.isfinite(interval)
    ):
        # math.isfinite: +inf passes "> 0" but is unrepresentable in JSON —
        # the published manifest must be strict JSON (RFC 8259 has no
        # Infinity token).
        raise ValueError(
            "waveform_f64le finalise requires a positive finite sample_interval_s"
        )
    unit = metadata.get("unit")
    if not isinstance(unit, str) or not unit:
        raise ValueError("waveform_f64le finalise requires a non-empty unit")
    fields.update(
        sample_count=sample_count, sample_interval_s=interval, unit=unit
    )
    return fields


class StandaloneCaptureWriter:
    """The three capture methods over one event directory per capture.

    One capture is in flight per instance (§8). States: open (from the first
    successful append) → finalise/abort → terminal; appends after terminal
    are refused. The host exception contract is mirrored (spec §8):
    ``TimeoutError`` for cancellation at append, ``ValueError`` for rejected
    transaction shape, ``RuntimeError`` for host resource conditions such as
    a second concurrent capture.
    """

    def __init__(
        self,
        root: Path | None = None,
        *,
        formats: Any = _DEFAULT_FORMATS,
        max_bytes: int = _DEFAULT_MAX_BYTES,
    ) -> None:
        self._root = capture_root(root)
        self._formats = frozenset(formats)
        self._max_bytes = max_bytes
        self._current: str | None = None
        self._event: Path | None = None
        self._staged_bytes = 0
        self._chunks = 0
        self._terminal: str | None = None

    @property
    def root(self) -> Path:
        """The resolved capture root this writer publishes under."""
        return self._root

    def _open_event(self, capture_id: str) -> Path:
        """Open (or return the already-open) event directory for a capture.

        ``mkdir`` is the two-process arbiter: the case-folded collision check
        runs first, and a concurrent process winning the directory race
        surfaces as a clean prefixed refusal, never an interleave and never
        a bare ``OSError``.
        """
        if self._event is not None:
            return self._event
        if not _segment_is_free(self._root, capture_id):
            capture_root_str = str(self._root)
            raise ValueError(
                f"capture_id collision: an event named like {capture_id!r} "
                f"already exists under {capture_root_str}"
            )
        event = self._root / capture_id
        try:
            event.mkdir(parents=True)
        except FileExistsError as error:
            raise ValueError(
                f"capture event directory already exists: {event} "
                "(created concurrently; one event per directory)"
            ) from error
        return event

    async def artifact_append(self, capture_id: str, data: bytes, context: Any) -> None:
        """Append one chunk to the capture's staging directory.

        The segment rules run first, then cancellation: a cancelled append
        writes nothing at all. An empty append is refused (gateway-writer
        parity), and so is an append that would exceed the declared
        ``max_bytes`` reservation.
        """
        if not _valid_capture_segment(capture_id):
            raise ValueError(f"unsafe capture_id segment: {capture_id!r}")
        if self._terminal is not None:
            raise ValueError(
                f"capture {self._current!r} is closed ({self._terminal}); "
                "appends after terminal are refused"
            )
        if self._current is not None and capture_id != self._current:
            raise RuntimeError(
                f"one capture in flight per writer: {self._current!r} is open; "
                f"close it before appending to {capture_id!r}"
            )
        if _context_is_cancelled(context):
            raise TimeoutError("operation cancelled before append; nothing written")
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise ValueError("append data must be bytes")
        payload = bytes(data)
        if not payload:
            raise ValueError("empty append refused (gateway-writer parity)")
        if self._staged_bytes + len(payload) > self._max_bytes:
            raise ValueError(
                f"append of {len(payload)} bytes exceeds the declared "
                f"max_bytes reservation ({self._max_bytes} bytes, "
                f"{self._staged_bytes} already staged)"
            )
        event = self._open_event(capture_id)
        staging = event / "staging"
        staging.mkdir(exist_ok=True)
        (staging / f"{self._chunks}.part").write_bytes(payload)
        self._chunks += 1
        self._staged_bytes += len(payload)
        self._current = capture_id
        self._event = event

    async def artifact_finalise(
        self, capture_id: str, metadata: dict[str, Any], context: Any
    ) -> dict[str, Any]:
        """Publish the capture: atomic primary, then the manifest.

        The format must be in the constructor's declared set (the refusal
        names the set); waveform metadata is validated for presence and
        shape (the corpus allOf); the digest and length are computed over
        the REAL bytes as they are concatenated into the primary — a temp
        file in the same directory renamed into place, so a crash across
        finalise leaves a ``.tmp`` remnant, never a half-written primary.
        Nothing is interpreted: the count×8 rule is the gateway's G1/G4.
        """
        if self._terminal is not None:
            raise ValueError(
                f"capture {self._current!r} is closed ({self._terminal}); "
                "finalise is refused"
            )
        if self._current is None or capture_id != self._current:
            raise ValueError(
                f"no open capture {capture_id!r} to finalise (nothing appended, "
                "a foreign id, or a second finalise)"
            )
        if not isinstance(metadata, dict):
            raise ValueError("finalise metadata must be an object")
        accepted = frozenset(
            {"format", "started_at", "sample_count", "sample_interval_s", "unit", "renderings"}
        )
        unknown = sorted(set(metadata) - accepted)
        if unknown:
            raise ValueError(
                f"unknown finalise metadata keys {unknown}; accepted: {sorted(accepted)}"
            )
        fmt = metadata.get("format")
        if not isinstance(fmt, str) or fmt not in self._formats:
            raise ValueError(
                f"format {fmt!r} is not in the declared set {sorted(self._formats)}"
            )
        started_at = metadata.get("started_at")
        if not isinstance(started_at, str) or not started_at:
            raise ValueError("finalise metadata requires a non-empty started_at string")
        renderings = metadata.get("renderings")
        if renderings is not None and (
            not isinstance(renderings, list)
            or not all(isinstance(entry, dict) for entry in renderings)
        ):
            raise ValueError(
                "renderings must be a list of {file, byte_length, sha256} objects"
            )
        event = self._event
        if event is None:  # pragma: no cover — an open capture always has one
            raise RuntimeError("writer invariant violated: open capture without event")
        staging = event / "staging"
        if not staging.is_dir():
            # S-F1's typed guard: staging absent at concat entry means the
            # event directory was mangled outside the writer (the writer
            # itself keeps staging until the manifest marker lands). A
            # contract-class refusal naming the state — never a bare
            # FileNotFoundError out of the concat loop.
            raise ValueError(
                f"capture {capture_id!r} has no staging directory to "
                f"finalise ({staging} is absent) — the event was modified "
                "outside the writer; abort it and start a new capture"
            )
        extension = _FORMAT_EXTENSIONS.get(fmt, _DEFAULT_EXTENSION)
        primary = event / f"{capture_id}{extension}"
        temp = event / f"{capture_id}{extension}.tmp"
        hasher = hashlib.sha256()
        total = 0
        with temp.open("wb") as out:
            for index in range(self._chunks):
                chunk = (staging / f"{index}.part").read_bytes()
                hasher.update(chunk)
                out.write(chunk)
                total += len(chunk)
        if total == 0:
            temp.unlink(missing_ok=True)
            raise ValueError(
                "zero-byte finalise refused: failed/incomplete captures are "
                "aborted, not published as complete"
            )
        os.replace(temp, primary)
        digest = hasher.hexdigest()
        manifest: dict[str, Any] = {
            "capture_id": capture_id,
            "format": fmt,
            "artifact_id": "art-" + digest,
            "byte_length": total,
            "sha256": digest,
            "started_at": started_at,
        }
        if fmt == "waveform_f64le":
            manifest.update(_waveform_fields(metadata))
        manifest["x-standalone-state"] = "finalised"
        manifest["x-standalone-manifest-version"] = 1
        if renderings is not None:
            manifest["x-standalone-renderings"] = renderings
        _write_manifest(event, manifest)
        # S-F1: staging teardown AFTER the manifest (the publication
        # marker) — a manifest-write failure leaves the capture fully
        # retryable (staging intact, primary complete, writer open) instead
        # of wedged behind a FileNotFoundError on every natural retry.
        shutil.rmtree(staging, ignore_errors=True)
        self._terminal = "finalised"
        return manifest

    async def artifact_abort(self, capture_id: str) -> None:
        """Discard staging and the in-flight primary; publish nothing.

        A no-op retract after finalise (a published capture stands) and for
        an id this writer never opened — the unconditional
        ``finally: artifact_abort()`` idiom can neither unpublish nor touch
        another event, and ``renderings/`` is never deleted.
        """
        if self._terminal is not None:
            return
        if self._current is None or capture_id != self._current:
            return
        event = self._event
        if event is None:  # pragma: no cover — an open capture always has one
            return
        shutil.rmtree(event / "staging", ignore_errors=True)
        for candidate in event.glob(f"{capture_id}.*"):
            if candidate.is_file():
                candidate.unlink()
        self._terminal = "aborted"
