"""The retention engine (I3c): rules, evaluator, recorder, sweep.

One launch-configuration artifact (the rules document, JSON, explicit path —
never silently substituted) drives everything here. The engine is
rule-driven; the SHIPPED default is the ruled set (Q13, ruled 2026-10-07):
the packaged :data:`DEFAULTS_DOCUMENT_NAME` document keeps mcp captures 30
days unless pinned, keeps ui and rest captures until deleted (no rule
matches them), and warns at :data:`QUOTA_FRACTION` of a configured byte
quota. :func:`ruled_defaults` loads that document and
:func:`effective_config` composes an operator's document ON TOP of it
(additive — the ruling's composition; nothing can loosen the mcp floor;
pinning is the keep-forever mechanism).

The evaluator is deterministic and hand-computable: same rules, same rows,
same ``now`` — same plan, in a stable order, each removal attributed to the
first selecting rule in id-sorted evaluation order. The retention log is a
JSONL FILE in the capture root (not an index table): it survives index
rebuilt by construction, because the index is acceleration and the root is
the truth.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

#: STD-4's machine-matchable refusal prefix for every malformed rules shape.
RULES_INVALID = "standalone_retention_rules_invalid:"

#: The retention log's filename, in the capture root (survives index
#: rebuilds by construction — it is not an index table).
LOG_NAME = "retention.log"

#: The packaged ruled-defaults document (Q13, ruled 2026-10-07), shipped
#: beside this module: the ruled set as DATA — parsed by the same
#: :func:`parse_config` an operator's document passes, never a host
#: constant (F-3's landing shape).
DEFAULTS_DOCUMENT_NAME = "retention-defaults.json"

#: The closed dispatch-surface vocabulary a rule's ``source`` may name
#: (SW-55's match key is SW-34's recorded surface — ui/rest/mcp).
_SOURCES = frozenset({"ui", "rest", "mcp"})

#: The closed recorder trigger set: who removed the capture.
_TRIGGERS = frozenset(
    {"scheduled", "cli", "sweep", "delete-ui", "delete-rest", "delete-mcp"}
)

#: The sweep's default grace window (s) — an operational constant of the
#: host, not a protective envelope (a zombie still writing keeps its
#: directory mtime fresh; the grace protects it).
DEFAULT_GRACE_S = 900.0

#: The quota warning's rising-edge threshold (fraction of a max_bytes cap).
QUOTA_FRACTION = 0.8

#: One day, in seconds, for the age arithmetic.
_DAY_S = 86400.0


@dataclass(frozen=True)
class RetentionRule:
    """One rule: optional match keys (absent = wildcard), at least one
    limit. Frozen and hashable — the scheduler treats it as configuration."""

    id: str
    source: str | None
    project: str | None
    max_age_d: float | None
    max_count: int | None
    max_bytes: int | None


@dataclass(frozen=True)
class RetentionConfig:
    """The loaded rules document. Every field has a keep-everything default:
    no interval, the default grace, no reserve, no rules."""

    interval_s: float | None = None
    orphan_grace_s: float = DEFAULT_GRACE_S
    reserve_bytes: int | None = None
    rules: tuple[RetentionRule, ...] = ()


@dataclass(frozen=True)
class PlannedRemoval:
    """One planned removal: which capture, under which rule, how many bytes
    (the index row's byte_length)."""

    capture_id: str
    rule_id: str
    bytes: int


@dataclass(frozen=True)
class QuotaUsage:
    """One max_bytes rule's current usage (the quota event's data)."""

    rule_id: str
    used_bytes: int
    cap_bytes: int


def _is_number(value: Any) -> bool:
    """A finite JSON number that is not a bool (bool is an int in Python —
    a ``max_bytes: true`` is a malformed shape, not a cap of 1).

    Non-finite floats refuse here (the fold wave's row 1): Python's json
    accepts ``NaN`` and ``Infinity`` as extensions and ``1e999`` parses to
    ``inf``, and none of them is computable — a NaN grace defeats the
    sweep cutoff, a NaN age detonates the arithmetic, and a NaN interval
    kills the schedule.
    """
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _rule_of(entry: Any, seen: set[str]) -> RetentionRule:
    """Validate one rules-list entry into a :class:`RetentionRule`."""
    # The object check FIRST: the identification f-string below reads
    # entry.get(), which a non-object entry does not have — evaluating it
    # before this guard turned every malformed entry into an AttributeError
    # escaping the prefixed refusal (the fold wave's row 2).
    if not isinstance(entry, dict):
        raise ValueError(f"{RULES_INVALID} a rule must be an object, got {entry!r}")
    where = f"{RULES_INVALID} rule {entry.get('id', '<unidentified>')!r}: "
    unknown = set(entry) - {"id", "source", "project", "max_age_d", "max_count", "max_bytes"}
    if unknown:
        raise ValueError(f"{where}unknown keys {sorted(unknown)}")
    rule_id = entry.get("id")
    if not isinstance(rule_id, str) or not rule_id:
        raise ValueError(f"{where}id must be a non-empty string")
    if rule_id in seen:
        raise ValueError(
            f"{RULES_INVALID} duplicate rule id {rule_id!r}: deterministic "
            "evaluation needs unique sort keys"
        )
    source = entry.get("source")
    if source is not None and source not in _SOURCES:
        raise ValueError(
            f"{where}source must be one of {sorted(_SOURCES)}, got {source!r}"
        )
    project = entry.get("project")
    if project is not None and (not isinstance(project, str) or not project):
        raise ValueError(f"{where}project must be a non-empty string")
    limits = entry.get("max_age_d"), entry.get("max_count"), entry.get("max_bytes")
    max_age_d, max_count, max_bytes = limits
    if max_age_d is not None and (not _is_number(max_age_d) or max_age_d <= 0):
        raise ValueError(f"{where}max_age_d must be a finite number > 0")
    if max_age_d is not None:
        max_age_d = float(max_age_d)
    if max_count is not None and (not _is_int(max_count) or max_count < 0):
        raise ValueError(f"{where}max_count must be an integer >= 0")
    if max_bytes is not None and (not _is_int(max_bytes) or max_bytes < 0):
        raise ValueError(f"{where}max_bytes must be an integer >= 0")
    if all(limit is None for limit in limits):
        raise ValueError(f"{where}at least one limit is required")
    seen.add(rule_id)
    return RetentionRule(rule_id, source, project, max_age_d, max_count, max_bytes)


def parse_config(text: str) -> RetentionConfig:
    """Parse and validate a rules document's TEXT — the body of
    :func:`load_config`, factored out so the packaged ruled-defaults
    document validates through the SAME implementation an operator's
    document does (one validator, never a second one beside it).

    Every malformed shape — unparseable JSON, a non-object, an unknown key,
    a bad type, a duplicate id, a missing limit, an unknown source value —
    refuses with :data:`RULES_INVALID` prefixed ``ValueError`` (STD-4: CI
    and scripts branch on the text).
    """
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"{RULES_INVALID} not parseable JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{RULES_INVALID} the document must be a JSON object")
    unknown = set(payload) - {"interval_s", "orphan_grace_s", "reserve_bytes", "rules"}
    if unknown:
        raise ValueError(f"{RULES_INVALID} unknown top-level keys {sorted(unknown)}")
    interval_s = payload.get("interval_s")
    if interval_s is not None:
        if not _is_number(interval_s) or interval_s <= 0:
            raise ValueError(f"{RULES_INVALID} interval_s must be a finite number > 0")
        interval_s = float(interval_s)
    grace = payload.get("orphan_grace_s")
    if grace is not None:
        if not _is_number(grace) or grace < 0:
            raise ValueError(f"{RULES_INVALID} orphan_grace_s must be a finite number >= 0")
        grace = float(grace)
    reserve = payload.get("reserve_bytes")
    if reserve is not None and (not _is_int(reserve) or reserve < 0):
        raise ValueError(f"{RULES_INVALID} reserve_bytes must be an integer >= 0")
    rules_entry = payload.get("rules", [])
    if not isinstance(rules_entry, list):
        raise ValueError(f"{RULES_INVALID} rules must be a list")
    seen: set[str] = set()
    rules = tuple(_rule_of(entry, seen) for entry in rules_entry)
    return RetentionConfig(
        interval_s=interval_s,
        orphan_grace_s=DEFAULT_GRACE_S if grace is None else grace,
        reserve_bytes=reserve,
        rules=rules,
    )


def load_config(path: Path) -> RetentionConfig:
    """Load and validate the rules document at ``path`` (read +
    :func:`parse_config` — one validation implementation).

    An unreadable document refuses with :data:`RULES_INVALID` prefixed
    ``ValueError`` (STD-4), exactly as every malformed shape does.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"{RULES_INVALID} unreadable rules document: {exc}") from exc
    return parse_config(text)


def ruled_defaults() -> RetentionConfig:
    """The packaged ruled-defaults document (Q13, ruled 2026-10-07), loaded
    and validated like any operator document.

    The ruled set as DATA (:data:`DEFAULTS_DOCUMENT_NAME` beside this
    module): mcp captures are kept 30 days unless pinned; ui and rest
    captures are kept until deleted (no rule matches them); no default
    byte quota, reserve or interval was ruled — the warning threshold is
    :data:`QUOTA_FRACTION` over a quota an operator configures, the
    reserve stays commissioned configuration (A02), and the schedule's
    86400 s default stands. An unreadable or unparseable packaged document
    refuses with the :data:`RULES_INVALID` prefix — never a silent
    fallback to keep-everything. What runtime does NOT catch: a document
    that is VALID JSON with mutated CONTENT (an emptied ``{"rules": []}``
    degrades silently to keep-everything) — content integrity is pinned by
    the suite's exact-rule-set arm (the design record's RD-1), not checked
    here.
    """
    path = Path(__file__).with_name(DEFAULTS_DOCUMENT_NAME)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"{RULES_INVALID} the packaged ruled-defaults document "
            f"{DEFAULTS_DOCUMENT_NAME} is unreadable: {exc}"
        ) from exc
    return parse_config(text)


def effective_config(custom: RetentionConfig | None) -> RetentionConfig:
    """The ruled defaults composed with an optional operator document (the
    ruling's composition: custom rules are ADDITIVE ON TOP).

    ``custom is None`` → the defaults alone. Otherwise the merged rules are
    ``defaults.rules + custom.rules`` under the evaluator's union — a
    custom rule can select rows the defaults keep; NOTHING can loosen the
    mcp-30d floor (pinning stays the keep-forever mechanism, the ruling's
    "unless pinned"). A custom rule id equal to a default rule id refuses
    with :data:`RULES_INVALID` (the loader's duplicate-id family:
    deterministic evaluation needs unique sort keys across the merged set
    too). ``interval_s``, ``orphan_grace_s`` and ``reserve_bytes`` are the
    custom document's knobs — single-valued, so custom wins when set.
    """
    defaults = ruled_defaults()
    if custom is None:
        return defaults
    default_ids = {rule.id for rule in defaults.rules}
    collision = sorted(default_ids & {rule.id for rule in custom.rules})
    if collision:
        raise ValueError(
            f"{RULES_INVALID} rule id {collision[0]!r} collides with a "
            "shipped default rule id: rename the custom rule (deterministic "
            "evaluation needs unique sort keys)"
        )
    return RetentionConfig(
        interval_s=custom.interval_s,
        orphan_grace_s=custom.orphan_grace_s,
        reserve_bytes=custom.reserve_bytes,
        rules=defaults.rules + custom.rules,
    )


# --- the evaluator ------------------------------------------------------------


def _started_at(row: dict[str, Any]) -> datetime | None:
    """The row's ``started_at`` as an aware datetime; ``None`` when absent
    or unparseable (a row that cannot be age-ordered is KEPT — deletion
    needs positive evidence, and a naive stamp is read as UTC)."""
    raw = row.get("started_at")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _applies(rule: RetentionRule, row: dict[str, Any]) -> bool:
    """A rule APPLIES when every present match key matches (absent keys are
    wildcards)."""
    source_matches = rule.source is None or row.get("surface") == rule.source
    project_matches = rule.project is None or row.get("project") == rule.project
    return source_matches and project_matches


def _bytes_of(row: dict[str, Any]) -> int:
    return int(row.get("byte_length") or 0)


def _newest_first(row: dict[str, Any]) -> tuple[datetime, str]:
    """The newest-first sort key (started_at desc, capture_id desc as the
    tiebreak)."""
    return (
        _started_at(row) or datetime.min.replace(tzinfo=UTC),
        str(row["capture_id"]),
    )


def _select(
    rule: RetentionRule, applicable: list[dict[str, Any]], *, now: datetime
) -> set[str]:
    """Which of the rule's applicable rows THIS rule selects.

    ``max_age_d``: strictly older than the cutoff. ``max_count``: all but
    the newest ``max_count`` (newest-first by started_at, capture_id desc as
    the tiebreak). ``max_bytes``: keep the newest-first prefix whose sum is
    ``<= max_bytes`` and select the complement — if the total already fits,
    nothing; a single newest row alone above the cap selects even itself.
    """
    selected: set[str] = set()
    ordered = sorted(applicable, key=_newest_first, reverse=True)
    if rule.max_age_d is not None:
        cutoff = now - timedelta(seconds=rule.max_age_d * _DAY_S)
        selected.update(
            str(row["capture_id"])
            for row in ordered
            if (started := _started_at(row)) is not None and started < cutoff
        )
    if rule.max_count is not None and len(ordered) > rule.max_count:
        selected.update(
            str(row["capture_id"]) for row in ordered[rule.max_count :]
        )
    if rule.max_bytes is not None:
        kept = 0
        running = 0
        for row in ordered:
            running += _bytes_of(row)
            if running > rule.max_bytes:
                break
            kept += 1
        selected.update(str(row["capture_id"]) for row in ordered[kept:])
    return selected


def plan(
    rules: Iterable[RetentionRule],
    rows: Iterable[dict[str, Any]],
    *,
    now: datetime,
    in_flight_ids: Iterable[str] = frozenset(),
) -> list[PlannedRemoval]:
    """The deterministic removal plan over the library's rows.

    Eligibility: not pinned, not in flight, and age-orderable — a row whose
    ``started_at`` cannot be parsed is never selected (deletion needs
    positive evidence), so it cannot appear in a plan. Rows come from the
    library, so ``published`` is already guaranteed (the manifest exists).
    A row
    selected by several rules is attributed to the FIRST selecting rule in
    evaluation order (rules sorted by id) — the golden set is unambiguous.
    The result is sorted by capture_id.
    """
    all_rows = list(rows)
    armed = frozenset(in_flight_ids)
    candidates = [
        row
        for row in all_rows
        if not row.get("pinned")
        and str(row.get("capture_id")) not in armed
        and _started_at(row) is not None
    ]
    selected: dict[str, str] = {}
    for rule in sorted(rules, key=lambda rule: rule.id):
        applicable = [row for row in candidates if _applies(rule, row)]
        for capture_id in _select(rule, applicable, now=now):
            # setdefault: the first selecting rule (id order) keeps the row.
            selected.setdefault(capture_id, rule.id)
    by_id = {str(row.get("capture_id")): row for row in all_rows}
    return sorted(
        (
            PlannedRemoval(capture_id, rule_id, _bytes_of(by_id[capture_id]))
            for capture_id, rule_id in selected.items()
        ),
        key=lambda removal: removal.capture_id,
    )


# --- the quota usage (the schedule's input) ----------------------------------------


def quota_usages(
    rules: Iterable[RetentionRule],
    rows: Iterable[dict[str, Any]],
    *,
    in_flight_ids: Iterable[str] = frozenset(),
) -> list[QuotaUsage]:
    """One usage per ``max_bytes`` rule: the summed byte_length of the
    rule's applicable eligible rows — the same eligibility and
    applicability :func:`plan` runs on (one implementation, not a second
    one beside it)."""
    all_rows = list(rows)
    armed = frozenset(in_flight_ids)
    candidates = [
        row
        for row in all_rows
        if not row.get("pinned")
        and str(row.get("capture_id")) not in armed
        and _started_at(row) is not None
    ]
    return [
        QuotaUsage(
            rule.id,
            sum(_bytes_of(row) for row in candidates if _applies(rule, row)),
            int(rule.max_bytes),
        )
        for rule in sorted(rules, key=lambda rule: rule.id)
        if rule.max_bytes is not None
    ]


# --- the next-effect projection (SW-49) -------------------------------------------


def next_effects(
    rules: Iterable[RetentionRule],
    rows: Iterable[dict[str, Any]],
    *,
    now: datetime,
    in_flight_ids: Iterable[str] = frozenset(),
) -> dict[str, dict[str, str]]:
    """Per-capture next-retention labels over the SAME evaluator
    :func:`plan` runs — one implementation, never a second one beside it.

    A row the plan selects now is ``prunable now by <rule>`` (the first
    selecting rule, plan's own attribution). Otherwise the first applying
    AGE rule names the date it will select (``<rule> at <date>``), else the
    first applying count/bytes rule reads ``eligible under <rule>``, else
    ``kept`` — as do pinned rows, in-flight rows and rows whose
    ``started_at`` cannot be parsed (the evaluator's keep-by-default).
    """
    all_rows = list(rows)
    armed = frozenset(in_flight_ids)
    removals = {
        removal.capture_id: removal.rule_id
        for removal in plan(rules, all_rows, now=now, in_flight_ids=armed)
    }
    effects: dict[str, dict[str, str]] = {}
    for row in all_rows:
        capture_id = str(row.get("capture_id"))
        if capture_id in removals:
            effects[capture_id] = {"label": f"prunable now by {removals[capture_id]}"}
            continue
        started = _started_at(row)
        if row.get("pinned") or capture_id in armed or started is None:
            effects[capture_id] = {"label": "kept"}
            continue
        age_at: datetime | None = None
        age_rule: str | None = None
        eligible_under: str | None = None
        for rule in sorted(rules, key=lambda rule: rule.id):
            if not _applies(rule, row):
                continue
            if rule.max_age_d is not None:
                # The earliest applying age rule's date — the soonest
                # future effect is the informative one, and an age rule
                # outranks a count/bytes "eligible" (a dated effect is a
                # stronger answer than a cohort-dependent one).
                at = started + timedelta(seconds=rule.max_age_d * _DAY_S)
                if age_at is None or at < age_at:
                    age_at, age_rule = at, rule.id
            elif eligible_under is None:
                eligible_under = rule.id
        if age_rule is not None:
            effects[capture_id] = {
                "label": f"{age_rule} at {age_at.date().isoformat() if age_at else ''}"
            }
        elif eligible_under is not None:
            effects[capture_id] = {"label": f"eligible under {eligible_under}"}
        else:
            effects[capture_id] = {"label": "kept"}
    return effects


# --- the recorder ---------------------------------------------------------------


def record(
    root: Path,
    removals: Iterable[dict[str, Any]],
    *,
    trigger: str,
) -> None:
    """Append one JSONL row per removal to ``<root>/retention.log``.

    Each removal dict names ``capture_id``, ``sha256`` (the removed
    manifest's recorded artifact digest — the log row and the capture's own
    record name the same bytes; ``None`` for sweep rows, an orphan never
    published) and ``rule``. Rows are sorted by capture_id and written
    open-append-flush per row (the ``record_evidence`` pattern). The log is
    a file in the root: it survives index rebuilds by construction.
    """
    if trigger not in _TRIGGERS:
        raise ValueError(f"standalone_retention_trigger_unknown: {trigger}")
    entries = sorted(removals, key=lambda entry: str(entry["capture_id"]))
    at = datetime.now(UTC).isoformat()
    log = Path(root) / LOG_NAME
    with log.open("a", encoding="utf-8") as stream:
        for entry in entries:
            row = {
                "capture_id": str(entry["capture_id"]),
                "sha256": entry.get("sha256"),
                "rule": str(entry.get("rule", "")),
                "at": at,
                "trigger": trigger,
            }
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()


# --- the sweep ------------------------------------------------------------------


#: Host-owned persisted surfaces that live beside captures in the root.
#: The I4a report pair writes ``reports/`` under the capture root (the
#: design record's placement); the sweep's own rule ("every directory with
#: no manifest.json is crash residue") would remove it once its mtime aged
#: past the grace — the record's "capture retention does not govern
#: reports/" premise is FALSE against the landed sweep without this
#: reserved-name skip (the build-time re-derivation, disclosed in the I4a
#: commit). Reports are governed by their own rule: they pin their
#: sources, and their retention reopens on the first operator complaint
#: or a disk-growth signal (the design record's named deferral).
_RESERVED_ROOT_DIRS: frozenset[str] = frozenset({"reports"})


def sweep_plan(
    root: Path,
    *,
    now: float,
    grace_s: float = DEFAULT_GRACE_S,
    in_flight_ids: Iterable[str] = frozenset(),
) -> list[str]:
    """Directories the sweep may remove: every directory in the root with
    no ``manifest.json``, not any in-flight capture's directory, not a
    reserved host-owned surface (``reports``), and an mtime older than
    ``now - grace_s``.

    The home of the crash-left residuals: the zombie's re-staged directory
    (a zombie still writing keeps its mtime fresh — the grace protects it),
    the crash-left event dir that wedges its id, and crash residue
    generally. The grace is an operational constant measured from directory
    mtime — same-host semantics; a root moved between hosts re-bases
    mtimes (disclosed: the one-writer lock already precludes a live root
    moving between hosts).
    """
    cutoff = now - grace_s
    if not (math.isfinite(grace_s) and math.isfinite(cutoff) and grace_s >= 0):
        # An uncomputable or negative grace proves nothing about age:
        # sweep NOTHING (deletion needs positive evidence — the same
        # keep-by-default rule the evaluator applies to an unparseable
        # started_at). The loader refuses these shapes at the document;
        # this is the direct-call defense.
        return []
    armed = frozenset(in_flight_ids)
    root_path = Path(root)
    swept: list[str] = []
    for entry in sorted(root_path.iterdir()):
        try:
            # A symlink is never a sweep target: rmtree through a link
            # raises OSError that would kill the whole run's report (the
            # fold wave's row 3), and removing a LINK would leave its
            # target's bytes in place while logging a removal anyway.
            if not entry.is_dir() or entry.is_symlink():
                continue
            if (entry / "manifest.json").is_file():
                continue
            if entry.name in armed:
                continue
            if entry.name in _RESERVED_ROOT_DIRS:
                continue
            if entry.stat().st_mtime >= cutoff:
                continue
        except OSError:
            # Per-entry isolation: one unreadable entry cannot abort the
            # plan for the rest (raced removal, a permission) — it is
            # simply never a candidate.
            continue
        swept.append(entry.name)
    return swept


# --- the quota latch --------------------------------------------------------------


class QuotaLatch:
    """Edge-triggered quota warnings: one latch per max_bytes rule.

    A rule fires when its usage crosses :data:`QUOTA_FRACTION` RISING — a
    rule already above at two consecutive evaluations fires once; a rule
    that drops below and re-crosses fires again. The latch is host state
    held by the scheduler (AR-9e pins exactly-once).
    """

    def __init__(self) -> None:
        self._above: set[str] = set()

    @staticmethod
    def fraction(usage: QuotaUsage) -> float:
        """Usage as a fraction of the cap; a zero cap reads as above only
        when there are actual bytes over it (``max_bytes: 0`` is a legal
        select-everything rule, not a permanently-firing quota)."""
        if usage.cap_bytes > 0:
            return usage.used_bytes / usage.cap_bytes
        return 1.0 if usage.used_bytes > 0 else 0.0

    def crossings(self, usages: Iterable[QuotaUsage]) -> list[QuotaUsage]:
        """The usages whose rule newly crossed the threshold this
        evaluation; updates every rule's latch state."""
        fired: list[QuotaUsage] = []
        for usage in usages:
            if self.fraction(usage) >= QUOTA_FRACTION:
                if usage.rule_id not in self._above:
                    fired.append(usage)
                self._above.add(usage.rule_id)
            else:
                self._above.discard(usage.rule_id)
        return fired
