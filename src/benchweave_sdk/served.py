"""The served-standards state derived from the packaged SDK lock.

Issue #203 slice 1 (design §3.2): the lock carries one row per CARRIED
(id, version) — retained ∧ in-range, yanked-in-interval versions marked —
plus a verbatim mirror of the gateway's ``dependency_policy`` block. This
module is the one reader every consumer shares: the carried and served sets,
the active version, pin classification (served / yanked / retired /
unserved, each refusal carrying the five VR-37 fields: standard, pinned
version, supported range, nearest move-to, migration-note pointer), and the
offline digest verification of the vendored bytes against the lock rows.

The lock is read packaged-first (``benchweave_sdk/standards-lock.json`` is
force-included in wheels) with a repository-checkout fallback for editable
development — the same resolution posture ``contract_documents`` has always
used. Nothing here reads the gateway checkout or the network (PKG-1, VR-32).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

LOCK_NAME = "standards-lock.json"
STANDARD = "otdp"


class ServedStateError(ValueError):
    """An unservable lock or an unclassifiable pin; always names the pin."""


@dataclass(frozen=True)
class PinClassification:
    """One pin's fate: ``served``, ``yanked`` (carried, warned), ``retired``
    (used and dead, never reissued) or ``unserved`` (out-of-range or never
    carried by this SDK)."""

    state: str
    standard: str
    pin: str
    supported_range: str
    move_to: str | None
    migration_note: str
    detail: str = ""


def _lock_document() -> dict[str, Any]:
    """The packaged lock, or the repository checkout's in editable dev."""
    packaged = files("benchweave_sdk").joinpath(LOCK_NAME)
    if packaged.is_file():
        document: dict[str, Any] = json.loads(packaged.read_bytes())
        return document
    checkout = Path(__file__).resolve().parents[2] / LOCK_NAME
    if checkout.is_file():
        loaded: dict[str, Any] = json.loads(checkout.read_bytes())
        return loaded
    raise ServedStateError(
        "lock_missing: this SDK carries no standards lock (packaged or "
        "checkout); the served set cannot be derived"
    )


@cache
def lock_rows() -> tuple[tuple[str, str, bool, bool], ...]:
    """Carried rows as (id, version, active, yanked), sorted and deduplicated."""
    rows: set[tuple[str, str, bool, bool]] = set()
    for row in _lock_document().get("standards", []):
        identifier = row.get("id")
        version = row.get("version")
        if not isinstance(identifier, str) or not isinstance(version, str):
            raise ServedStateError(f"lock_invalid: a row carries non-string id/version: {row!r}")
        active = bool(row.get("active", False))
        yanked = bool(row.get("yanked", False))
        rows.add((identifier, version, active, yanked))
    return tuple(sorted(rows))


def carried_versions(standard: str = STANDARD) -> tuple[str, ...]:
    """Every retained ∧ in-range version carried by this SDK (yanked included)."""
    return tuple(version for (identifier, version, _a, _y) in lock_rows() if identifier == standard)


def served_versions(standard: str = STANDARD) -> tuple[str, ...]:
    """The served set: carried ∧ ¬yanked — what auto-selection may choose."""
    return tuple(
        version
        for (identifier, version, _active, yanked) in lock_rows()
        if identifier == standard and not yanked
    )


def active_version(standard: str = STANDARD) -> str:
    """The lock's active row for one standard (exactly one, structurally)."""
    marked = [
        version
        for (identifier, version, active, _yanked) in lock_rows()
        if identifier == standard and active
    ]
    if len(marked) == 1:
        return marked[0]
    rows = [version for (identifier, version, _a, _y) in lock_rows() if identifier == standard]
    if not marked and len(rows) == 1:
        # The pre-multi-version one-row-per-id shape: its single row is active.
        return rows[0]
    raise ServedStateError(
        f"lock_invalid: {standard} carries {len(marked)} active-marked rows "
        f"({', '.join(marked)}); exactly one is required"
    )


def _policy_row(standard: str) -> dict[str, Any]:
    policy = _lock_document().get("dependency_policy")
    if not isinstance(policy, dict):
        raise ServedStateError(
            "policy_mirror_absent: the lock carries no dependency_policy mirror; "
            "re-sync the standards (the range and statuses cannot be classified)"
        )
    row = policy.get("standards", {}).get(standard)
    if not isinstance(row, dict):
        raise ServedStateError(
            f"policy_mirror_absent: no dependency_policy row for {standard!r}"
        )
    return row


def supported_range(standard: str = STANDARD) -> str:
    value = _policy_row(standard).get("range")
    if not isinstance(value, str):
        raise ServedStateError(f"policy_mirror_absent: {standard} declares no range")
    return value


def _retired(standard: str) -> tuple[str, ...]:
    retired = _policy_row(standard).get("retired", [])
    if not isinstance(retired, list):
        raise ServedStateError(f"policy_mirror_absent: {standard} retired is not a list")
    return tuple(str(item) for item in retired)


def _move_to(pin: str, standard: str = STANDARD) -> str | None:
    """Derived move-to: the highest served (¬yanked) version >= the pin."""
    candidates = [
        version
        for version in served_versions(standard)
        if _tuple(version) >= _tuple(pin)
    ]
    if candidates:
        return candidates[-1]
    served = served_versions(standard)
    return served[-1] if served else None


def _tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


MIGRATION_NOTE_PENDING = (
    "migration guidance pending (per-version migration notes land from "
    "adoption, issue #203 slice 5); the dependency_policy mirror in this "
    "lock names the yank or retirement record"
)


def classify_pin(pin: str, standard: str = STANDARD) -> PinClassification:
    """The Q6 taxonomy for one pin, with the five VR-37 fields attached."""
    supported = supported_range(standard)
    carried = carried_versions(standard)
    if pin in _retired(standard):
        move_to = _move_to(pin, standard) or supported.split(",")[0].lstrip(">=")
        return PinClassification(
            state="retired",
            standard=standard,
            pin=pin,
            supported_range=supported,
            move_to=move_to,
            migration_note=MIGRATION_NOTE_PENDING,
            detail=(
                f"{standard} {pin} is a retired identifier — used and dead, never "
                "reissued; re-target (OTDP's next minor skips the number)"
            ),
        )
    if pin in carried:
        yanked = any(
            version == pin and flag
            for (identifier, version, _active, flag) in lock_rows()
            if identifier == standard
        )
        if yanked:
            return PinClassification(
                state="yanked",
                standard=standard,
                pin=pin,
                supported_range=supported,
                move_to=_move_to(pin, standard),
                migration_note=MIGRATION_NOTE_PENDING,
                detail=f"{standard} {pin} is yanked from serving and auto-selection",
            )
        return PinClassification(
            state="served",
            standard=standard,
            pin=pin,
            supported_range=supported,
            move_to=None,
            migration_note=MIGRATION_NOTE_PENDING,
            detail=f"{standard} {pin} is served",
        )
    return PinClassification(
        state="unserved",
        standard=standard,
        pin=pin,
        supported_range=supported,
        move_to=_move_to(pin, standard),
        migration_note=MIGRATION_NOTE_PENDING,
        detail=(
            f"{standard} {pin} is not carried by this SDK (out of the declared "
            f"range {supported} or never retained here)"
        ),
    )


def refusal_for(classification: PinClassification) -> ValueError:
    """The typed refusal for a non-validatable pin, five fields attached."""
    prefix = (
        "retired_identifier:"
        if classification.state == "retired"
        else "version_not_served:"
    )
    return ValueError(
        f"{prefix} {classification.standard} pin {classification.pin} "
        f"(supported range {classification.supported_range}; nearest move-to "
        f"{classification.move_to}; {classification.migration_note}) — "
        f"{classification.detail}"
    )


def vendored_root() -> Path:
    """The vendored standards tree: packaged-first, checkout fallback.

    Both mounts resolve to the same shape — the tree sits directly beside
    this module's package in a wheel (``benchweave_sdk/standards/``), in the
    standalone checkout (``src/benchweave_sdk/standards/``) and in the
    gateway submodule mount alike — so the fallback is simply the package
    directory itself.
    """
    packaged = files("benchweave_sdk").joinpath("standards")
    if packaged.is_dir():
        return Path(str(packaged))
    checkout = Path(__file__).resolve().parent / "standards"
    if checkout.is_dir():
        return checkout
    raise ServedStateError(
        "standards_tree_missing: run sync-standards or reinstall the SDK"
    )


def verify_vendored_digests() -> None:
    """Every lock row's file must exist and hash to its pinned digest.

    The per-pin validation lane loads the vendored served set; this check is
    what makes that load digest-verified against the lock (design §3.2). A
    tampered or missing vendored file refuses by name.
    """
    root = vendored_root()
    for row in _lock_document().get("standards", []):
        identifier = row.get("id")
        for file in row.get("files", []):
            relative = file.get("path")
            pinned = file.get("sha256")
            if not isinstance(relative, str) or not isinstance(pinned, str):
                raise ServedStateError(f"lock_invalid: malformed file row in {identifier!r}")
            target = root / relative
            if not target.is_file():
                raise ServedStateError(
                    f"vendored_digest_mismatch: {relative} is missing from the "
                    "vendored tree; reinstall the SDK or re-run sync-standards"
                )
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if digest != pinned:
                raise ServedStateError(
                    f"vendored_digest_mismatch: {relative} hashes to {digest} but "
                    f"the lock pins {pinned}"
                )
