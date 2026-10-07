"""The serve env-file loader (issue #422 increment 1) — the gateway twin.

``benchweave_sdk_server serve --env-file <path>`` loads ``KEY=VALUE`` lines
into the process environment, set-if-not-set, before the host resolves its
configuration. The parse rules and refusal wording are shared VERBATIM
with the gateway twin (``benchweave/cli/env_file.py``); the twin test
suites assert the same literal expected strings, so the two repos cannot
drift silently.

The locator is an explicit ``--env-file`` flag, not data-dir
auto-discovery (the recorded divergence, design record section 3): the SDK
surface has no setup step, no data directory and no canonical file, so an
auto-discovered location would be new architecture with no consumer.
Without the flag, zero filesystem reads change.

Refusals are typed with the ``env_file:`` prefix and name the path, the
line number, the key (when parseable) and the problem class — never the
raw line, because a refusal that echoes the line echoes a secret. Serve
exits non-zero before any work.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import NoReturn

#: The machine-matchable refusal prefix (the gateway twin's vocabulary).
ENV_FILE_REFUSAL_PREFIX = "env_file:"

#: The closed SDK serve allowlist: the two keys the serve surface reads.
#: Anything else (``BENCHWEAVE_DB`` included) refuses as unknown — the
#: SDK serve has no store, and the refusal teaches that.
ENV_FILE_HAND_NAMED_KEYS = (
    "BENCHWEAVE_STANDALONE_BINDINGS",
    "BENCHWEAVE_CAPTURE_DIR",
)

_KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
#: Line splitting on the three newline forms ONLY (fold R4): U+2028/NEL
#: are not line ends here — ``str.splitlines()`` would split on them and
#: truncate values. They are not C0, so they stay in the value verbatim.
_LINE_SEPARATOR = re.compile(r"\r\n|\r|\n")
#: Any C0 control in a VALUE refuses (fold R3): allowlist value domains
#: (paths, urlsafe tokens, ints, enums) never carry controls.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f]")


class EnvFileError(RuntimeError):
    """A typed env-file refusal (the CLI shows it and exits non-zero)."""


def _refuse(path: Path, lineno: int, detail: str) -> NoReturn:
    raise EnvFileError(f"{ENV_FILE_REFUSAL_PREFIX} {path}: line {lineno}: {detail}")


def _strip_one_quote_layer(value: str, path: Path, lineno: int, key: str) -> str:
    """Strip ONE layer of matching single or double quotes (systemd
    ``EnvironmentFile`` compatibility for operators copying shell-export
    lines). No escape sequences, no variable expansion — a value that
    opens a quote it does not close refuses rather than half-apply."""
    first = value[:1]
    if first not in ("\"", "'"):
        return value
    if len(value) >= 2 and value[-1] == first:
        return value[1:-1]
    _refuse(path, lineno, f"{key}: mismatched quotes")


def _check_owner_only(path: Path) -> None:
    """Refuse group/other access on POSIX (the file may carry credentials;
    ssh's posture, not a warning). Windows: mode bits do not reach the ACL
    — no check here (W1 residual, corroborated by the Windows CI leg)."""
    if sys.platform == "win32":
        return
    mode = path.stat().st_mode
    # Fold R2: 0o077 (group/other), not 0o177 — the owner-execute bit is
    # not group access, so a 0700 file loads. Bits above 0o777
    # (setuid/setgid/sticky) are unexamined — disclosed residual.
    if mode & 0o077:
        raise EnvFileError(
            f"{ENV_FILE_REFUSAL_PREFIX} {path}: mode {mode & 0o7777:o} allows"
            " group or other access — the file carries a live secret;"
            " restrict it to the owner (chmod 0600)"
        )


def parse_env_file(
    path: Path,
    allowed: frozenset[str],
    excluded: Mapping[str, str] | None = None,
) -> list[tuple[int, str, str]]:
    """Validate the WHOLE file and return ``(lineno, key, value)`` entries.

    This is the two-phase core (fold R5): nothing touches ``os.environ``
    until every line has parsed and validated, so a refused file leaves no
    residue. Per-line rules beyond the original set: a value whose first
    character is a space/tab after the ``=`` refuses (fold R1 — the ``KEY
    = value`` typo class; NOT systemd-style trimming, which would re-open
    the silent-corruption class); any C0 control character in a value
    refuses (fold R3); a duplicate key refuses naming both lines (fold
    R9 — an editing mistake must not silently keep the old value).
    Refuses carry the ``env_file:`` prefix and never echo the raw line.
    """
    _check_owner_only(path)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            # newline="" keeps \r/\r\n untranslated so the loader's own
            # separator split (fold R4) is the only line splitting.
            text = handle.read()
    except OSError as error:
        raise EnvFileError(
            f"{ENV_FILE_REFUSAL_PREFIX} {path}: cannot read it: {error}"
        ) from error
    except UnicodeDecodeError as error:
        raise EnvFileError(
            f"{ENV_FILE_REFUSAL_PREFIX} {path}: not valid UTF-8: {error}"
        ) from error
    entries: list[tuple[int, str, str]] = []
    first_line: dict[str, int] = {}
    for lineno, raw in enumerate(_LINE_SEPARATOR.split(text), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            _refuse(path, lineno, 'no "=" in line — expected KEY=VALUE')
        key, _, value = line.partition("=")
        if _KEY_PATTERN.fullmatch(key) is None:
            # A BOM lands here too: it corrupts the first key into an
            # invalid key name and refuses (the exact-byte decoder's
            # posture).
            _refuse(path, lineno, f"key name {key!r} does not match [A-Za-z_][A-Za-z0-9_]*")
        if excluded is not None and key in excluded:
            _refuse(path, lineno, f"{key} may not come from the env file — {excluded[key]}")
        if key not in allowed:
            _refuse(
                path,
                lineno,
                f"{key} is not allowlisted for the serve env file — allowed"
                " keys: " + ", ".join(sorted(allowed)),
            )
        if value[:1] in (" ", "\t"):
            _refuse(path, lineno, f'{key}: value starts with whitespace after "="')
        value = _strip_one_quote_layer(value, path, lineno, key)
        if not value.strip():
            _refuse(path, lineno, f"{key} is set but empty")
        control = _CONTROL_CHARS.search(value)
        if control is not None:
            _refuse(
                path,
                lineno,
                f"{key}: value contains a control character"
                f" (0x{ord(control.group()):02x})",
            )
        if key in first_line:
            _refuse(
                path,
                lineno,
                f"{key} appears twice (first at line {first_line[key]})"
                " — one value per key",
            )
        first_line[key] = lineno
        entries.append((lineno, key, value))
    return entries


def apply_env_entries(entries: list[tuple[int, str, str]]) -> list[str]:
    """Apply parsed entries set-if-not-set into ``os.environ``; return the
    applied key names (a key already present in the environment is left
    alone — explicit process environment always wins)."""
    applied: list[str] = []
    for _lineno, key, value in entries:
        if key not in os.environ:
            os.environ[key] = value
            applied.append(key)
    return applied


def load_env_file(
    path: Path,
    allowed: frozenset[str],
    excluded: Mapping[str, str] | None = None,
) -> list[str]:
    """Parse ``path`` per the shared rules, apply set-if-not-set into
    ``os.environ``, and return the applied key names (``parse_env_file``
    followed by ``apply_env_entries`` — kept as the section-2.7 contract).

    Rules (design section 2.4 as amended by the fold wave, shared verbatim
    with the gateway twin): lines split on ``\r\n``/``\r``/``\n`` only;
    blank lines and full-line ``#`` comments are skipped (no inline
    comments); KEY must match ``[A-Za-z_][A-Za-z0-9_]*`` and be
    allowlisted; the first ``=`` separates so a value may contain ``=``; a
    leading space/tab after the ``=``, a C0 control in the value, a
    duplicate key, or a set-but-empty (whitespace-only) value all refuse;
    VALUE strips one layer of matching quotes. Malformed anything refuses
    loudly, prefix ``env_file:``, never echoing the raw line.
    """
    return apply_env_entries(parse_env_file(path, allowed, excluded))


def serve_env_file_keys() -> frozenset[str]:
    """The closed SDK serve allowlist (no import to derive: the SDK serve
    reads exactly these two keys)."""
    return frozenset(ENV_FILE_HAND_NAMED_KEYS)
