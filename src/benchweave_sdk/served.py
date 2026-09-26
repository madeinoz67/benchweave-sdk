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
    """Derived move-to: the highest served (¬yanked) version >= the pin.

    Ordered by SEMVER, never lexically ("0.10.0" outranks "0.2.0" — fold
    row 1: a lexical pick steered below-both pins to the older version).
    An unparsable pin (a dev-suffixed or otherwise malformed string) cannot
    be ordered against the served set; the highest served version is the
    best available answer for it — no path here raises a bare parse error
    (#215 fix F2: classification turns a malformed pin into a typed
    refusal, never a traceback).
    """
    served = served_versions(standard)
    pin_order = _tuple_or_none(pin)
    if pin_order is not None:
        candidates = [version for version in served if _tuple(version) >= pin_order]
        if candidates:
            return max(candidates, key=_tuple)
    return max(served, key=_tuple) if served else None


def _tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _tuple_or_none(version: str) -> tuple[int, ...] | None:
    """The numeric parts of an X.Y.Z version, or None when it does not parse."""
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return None


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
        # The fallback fires only when no version of the standard is served
        # (a degenerate lock): it names the declared range's lower bound as
        # GUIDANCE, and refusal_for labels it as exactly that — a fallback,
        # never a servable target (#215 fold-wave F-E 10).
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
    if _tuple_or_none(pin) is None:
        # F2 (#215): an unparsable pin would otherwise crash version
        # ordering inside _move_to — the refusal says why it cannot be
        # classified instead of laundering a parse error.
        return PinClassification(
            state="unserved",
            standard=standard,
            pin=pin,
            supported_range=supported,
            move_to=_move_to(pin, standard),
            migration_note=MIGRATION_NOTE_PENDING,
            detail=(
                f"{standard} {pin} is not a parseable MAJOR.MINOR.PATCH version "
                f"and is not carried by this SDK (supported range {supported}); "
                "dev-head pins are a later slice of issue #203"
            ),
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
    """The typed refusal for a non-validatable pin, five fields attached.

    The move-to is labelled for what the derivation actually is — the
    HIGHEST SERVED version, the recommended re-target (late Forge fold 3,
    #215: "nearest" overpromised an adjacency the pinned derivation does
    not compute) — except on the retired fallback, where nothing is served
    and the guidance names the declared range's LOWER BOUND as a fallback,
    never a servable target (#215 fold-wave F-E 10: a future range edit
    must not be able to steer a reader at a version no path validates
    against).
    """
    prefix = (
        "retired_identifier:"
        if classification.state == "retired"
        else "version_not_served:"
    )
    if classification.move_to is None:
        move_to_note = (
            f"no move-to: no version of {classification.standard} is served "
            "on this lock"
        )
    elif classification.move_to in served_versions(classification.standard):
        move_to_note = (
            f"move-to {classification.move_to} — the highest served version, "
            "the recommended re-target"
        )
    else:
        move_to_note = (
            f"move-to {classification.move_to} — the declared range's lower "
            f"bound, named as a fallback: no version of {classification.standard} "
            "is served on this lock, so it names no servable target"
        )
    return ValueError(
        f"{prefix} {classification.standard} pin {classification.pin} "
        f"(supported range {classification.supported_range}; "
        f"{move_to_note}; {classification.migration_note}) — "
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


def lock_file_digests() -> dict[str, str]:
    """Lock-recorded file digests keyed by row path (``<id>/<version>/<file>``).

    The load path (``validation.contract_documents``) checks every document
    it serves against this map (#215 fix F1 — design §3.2's "digest-checked
    against the SDK lock row" is wired here, not only claimed by
    :func:`verify_vendored_digests` below).
    """
    digests: dict[str, str] = {}
    for row in _lock_document().get("standards", []):
        identifier = row.get("id")
        for file in row.get("files", []):
            relative = file.get("path")
            pinned = file.get("sha256")
            if not isinstance(relative, str) or not isinstance(pinned, str):
                raise ServedStateError(f"lock_invalid: malformed file row in {identifier!r}")
            digests[relative] = pinned
    return digests


def verify_vendored_digests() -> None:
    """Every lock row's file must exist and hash to its pinned digest.

    The whole-tree sweep behind the load path's per-file check (design
    §3.2): the per-pin validation lane serves only digest-verified bytes
    (``validation.contract_documents``), and this check extends the same
    refusal to every lock row's file — including the non-JSON payloads the
    loader never parses. A tampered or missing vendored file refuses by
    name under the same ``vendored_digest_mismatch:`` prefix.
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
