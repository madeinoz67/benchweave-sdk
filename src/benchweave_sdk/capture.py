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

import os
import unicodedata
from pathlib import Path

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
