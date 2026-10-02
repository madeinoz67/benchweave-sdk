"""Registry management operations for the ``registry`` CLI family (issue #225).

Read side (this module's first half): the queue's seven-stage derivation
(CR-27) and the contributor status surface (CR-31). Both are offline and
git-native over a clone of the registry repository — committed records plus,
for the queue, PR state (a ``--pr-state`` fixture, or ``gh pr list --json``
when a live ``gh`` can reach the repository). Without PR state the queue
degrades LOUDLY: every row whose stage could rise carries ``stage_partial``
and the report's disclosures name ``stage_partial: pr_state_unavailable``.

Stage precedence (design 2026-10-02 section 2.2, most-advanced-first):
``published`` (a lifecycle publish record) > ``withdrawn`` (a withdraw
record, or a closed-unmerged PR with no publish record) > ``signed`` (an
accepted latest review plus the PR carrying ``manifest.sig`` — the adopted
F1 reading) > ``accepted`` (a committed accepted review, no publish record)
> ``changes requested`` (the latest review record's changes-requested
outcome, or a PR review requesting changes) > ``in review`` (an open PR
with maintainer review activity and no committed record) > ``submitted``.

Two readings the design text leaves open, resolved here and pinned by
tests: the LATEST review outcome governs (a stale accepted review cannot
sign — the only reading that keeps ``changes requested`` reachable once a
review history exists), and a rejected latest review renders as
``changes requested`` with the true outcome in the evidence (the
seven-stage list carries no rejected stage). A PR is mapped to its
submission key by the ``records/submissions/<p>/<x>/<v>/`` paths it
carries — never guessed from its branch name; an unmappable PR is
disclosed, not dropped.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any

from .publishing import canonical_bytes

_VERSION = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
_SUBMISSION_PATH = re.compile(
    rf"^records/submissions/([a-z0-9][a-z0-9-]*)/([a-z0-9][a-z0-9_-]*)/({_VERSION})/"
)
_LIFECYCLE_NAME = re.compile(r"^(\d+)-([a-z]+)\.json$")
_REVIEW_NAME = re.compile(r"^review-(\d+)\.json$")

#: The disclosure line the records-only degradation emits (design section 2.1:
#: "without either, degrades loudly: ``stage_partial: pr_state_unavailable``
#: naming which stages are under-derived").
STAGE_PARTIAL_DISCLOSURE = (
    "stage_partial: pr_state_unavailable (stages not derivable from records "
    "alone: signed, in review; withdrawn, changes requested and submitted may "
    "under-derive from PR-side activity; pass --pr-state or run where gh can "
    "reach the repository)"
)

#: Stages a records-only row can be raised FROM once PR state arrives; the
#: two records-terminal stages (published, withdrawn-by-record) sit above
#: every PR-dependent stage in the precedence table.
_RECORDS_PARTIAL_STAGES = frozenset({"accepted", "changes requested", "submitted"})


class RegistryOpsError(ValueError):
    """A registry operation refused; the message carries a stable machine prefix."""


@dataclass(frozen=True, order=True)
class SubKey:
    """A submission identity ``(publisher, plugin, version)``."""

    publisher: str
    plugin: str
    version: str

    @property
    def path(self) -> str:
        return f"records/submissions/{self.publisher}/{self.plugin}/{self.version}"


def parse_release_ref(ref: str) -> SubKey:
    """Parse ``<publisher>/<plugin>@<version>`` — the keyed commands' target."""
    match = re.fullmatch(rf"([a-z0-9][a-z0-9-]*)/([a-z0-9][a-z0-9_-]*)@({_VERSION})", ref)
    if match is None:
        raise RegistryOpsError(
            f"release_ref_invalid:{ref!r} (expected <publisher>/<plugin>@<X.Y.Z>)"
        )
    return SubKey(match.group(1), match.group(2), match.group(3))


# --- committed records -----------------------------------------------------------


@dataclass(frozen=True, order=True)
class LifecycleEntry:
    """One committed lifecycle record, keyed by its file sequence number."""

    seq: int
    op: str
    actor: str
    created_at: str
    reason: str


@dataclass(frozen=True)
class RecordsView:
    """Every committed record relevant to stage derivation and timelines."""

    submissions: frozenset[SubKey]
    lifecycle: dict[SubKey, tuple[LifecycleEntry, ...]]
    reviews: dict[SubKey, tuple[str, ...]]

    def ops(self, key: SubKey) -> frozenset[str]:
        return frozenset(entry.op for entry in self.lifecycle.get(key, ()))

    def timeline(self, key: SubKey) -> list[dict[str, str | int]]:
        return [
            {
                "seq": entry.seq,
                "op": entry.op,
                "actor": entry.actor,
                "created_at": entry.created_at,
                "reason": entry.reason,
            }
            for entry in sorted(self.lifecycle.get(key, ()))
        ]


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise RegistryOpsError(f"record_invalid:{path} ({exc})") from exc


def _require_str(record: dict[str, Any], field: str, path: Path) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise RegistryOpsError(f"record_invalid:{path} (missing {field})")
    return value


def load_records_view(clone: Path) -> RecordsView:
    """Read the committed records tree; malformed records refuse loudly."""
    submissions: set[SubKey] = set()
    lifecycle: dict[SubKey, list[LifecycleEntry]] = {}
    reviews: dict[SubKey, list[tuple[int, str]]] = {}

    submissions_root = clone / "records" / "submissions"
    if submissions_root.is_dir():
        for path in sorted(submissions_root.rglob("*.json")):
            match = _SUBMISSION_PATH.match(path.relative_to(clone).as_posix())
            if match is None:
                continue
            key = SubKey(match.group(1), match.group(2), match.group(3))
            submissions.add(key)
            review_match = _REVIEW_NAME.match(path.name)
            if review_match is not None:
                record = _load_json(path)
                if not isinstance(record, dict):
                    raise RegistryOpsError(f"record_invalid:{path} (not an object)")
                block = record.get("review")
                if not isinstance(block, dict):
                    raise RegistryOpsError(f"record_invalid:{path} (no review block)")
                outcome = _require_str(block, "outcome", path)
                reviews.setdefault(key, []).append((int(review_match.group(1)), outcome))

    lifecycle_root = clone / "records" / "lifecycle"
    if lifecycle_root.is_dir():
        for path in sorted(lifecycle_root.rglob("*.json")):
            name_match = _LIFECYCLE_NAME.match(path.name)
            if name_match is None:
                raise RegistryOpsError(
                    f"record_path_invalid:{path} (expected <seq>-<op>.json)"
                )
            parts = path.relative_to(lifecycle_root).parts
            if len(parts) != 4:
                raise RegistryOpsError(f"record_path_invalid:{path} (not under <p>/<x>/<v>/)")
            record = _load_json(path)
            if not isinstance(record, dict):
                raise RegistryOpsError(f"record_invalid:{path} (not an object)")
            block = record.get("lifecycle")
            if not isinstance(block, dict):
                raise RegistryOpsError(f"record_invalid:{path} (no lifecycle block)")
            key = SubKey(parts[0], parts[1], parts[2])
            for field in ("publisher", "plugin", "version"):
                if block.get(field) != getattr(key, field):
                    raise RegistryOpsError(
                        f"record_key_mismatch:{path} ({field} disagrees with the tree path)"
                    )
            if block.get("op") != name_match.group(2):
                raise RegistryOpsError(
                    f"record_key_mismatch:{path} (op disagrees with the file name)"
                )
            lifecycle.setdefault(key, []).append(
                LifecycleEntry(
                    seq=int(name_match.group(1)),
                    op=name_match.group(2),
                    actor=_require_str(record, "actor", path),
                    created_at=_require_str(record, "created_at", path),
                    reason=_require_str(block, "reason", path),
                )
            )

    return RecordsView(
        submissions=frozenset(submissions),
        lifecycle={
            key: tuple(sorted(entries)) for key, entries in lifecycle.items()
        },
        reviews={
            key: tuple(outcome for _number, outcome in sorted(outcomes))
            for key, outcomes in reviews.items()
        },
    )


# --- PR state ---------------------------------------------------------------------


@dataclass(frozen=True)
class PullRequest:
    """One PR in the gh-normalized shape the derivation consumes."""

    number: int
    state: str  # "open" | "closed" | "merged"
    head_ref: str
    files: tuple[str, ...]
    reviews: tuple[str, ...]

    def submission_keys(self) -> frozenset[SubKey]:
        keys: set[SubKey] = set()
        for path in self.files:
            match = _SUBMISSION_PATH.match(path)
            if match is not None:
                keys.add(SubKey(match.group(1), match.group(2), match.group(3)))
        return frozenset(keys)

    def carries_manifest_sig(self, key: SubKey) -> bool:
        prefix = f"{key.path}/"
        return any(path.startswith(prefix) and path.rsplit("/", 1)[-1] == "manifest.sig"
                   for path in self.files)


@dataclass(frozen=True)
class PRState:
    prs: tuple[PullRequest, ...]

    def by_key(self) -> dict[SubKey, PullRequest]:
        mapped: dict[SubKey, PullRequest] = {}
        for pr in self.prs:
            for key in pr.submission_keys():
                mapped[key] = pr
        return mapped


def _normalize_prs(payload: Any, source: str) -> tuple[PullRequest, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("prs"), list):
        raise RegistryOpsError(
            f"pr_state_invalid:{source} (expected an object with a 'prs' array)"
        )
    prs: list[PullRequest] = []
    for item in payload["prs"]:
        if not isinstance(item, dict):
            raise RegistryOpsError(f"pr_state_invalid:{source} (a pr entry is not an object)")
        state = str(item.get("state", "")).lower()
        if state not in {"open", "closed", "merged"}:
            raise RegistryOpsError(
                f"pr_state_invalid:{source} (state {state!r} is not open|closed|merged)"
            )
        raw_files = item.get("files", [])
        files = tuple(
            entry["path"] if isinstance(entry, dict) else str(entry) for entry in raw_files
        )
        raw_reviews = item.get("reviews", [])
        reviews = tuple(
            str(entry["state"]).lower() if isinstance(entry, dict) else str(entry).lower()
            for entry in raw_reviews
        )
        prs.append(
            PullRequest(
                number=int(item.get("number", 0)),
                state=state,
                head_ref=str(item.get("head_ref", item.get("headRefName", ""))),
                files=files,
                reviews=reviews,
            )
        )
    return tuple(prs)


def load_pr_state_fixture(path: Path) -> PRState:
    """The ``--pr-state`` fixture: the gh-normalized PR shape, committed or ad hoc."""
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise RegistryOpsError(f"pr_state_invalid:{path} ({exc})") from exc
    return PRState(_normalize_prs(payload, str(path)))


def gh_available() -> bool:
    """A live ``gh`` binary on PATH (its absence is an answer, not an error)."""
    completed = subprocess.run(["gh", "--version"], capture_output=True, check=False)
    return completed.returncode == 0


def load_pr_state_gh(clone: Path) -> PRState | None:
    """Live PR state via ``gh pr list --json`` against the clone's origin.

    Returns None whenever the live path cannot answer (no origin remote, gh
    failure) — the caller then degrades loudly rather than guessing.
    """
    completed = subprocess.run(
        ["git", "-C", str(clone), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    remote = completed.stdout.strip().removesuffix(".git")
    listing = subprocess.run(
        [
            "gh", "pr", "list", "-R", remote, "--state", "all",
            "--json", "number,state,headRefName,files,reviews", "--limit", "500",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if listing.returncode != 0:
        return None
    try:
        payload = json.loads(listing.stdout)
    except ValueError:
        return None
    # gh returns a bare PR array; the normalizer expects the fixture envelope.
    return PRState(_normalize_prs({"prs": payload}, remote))


# --- stage derivation (CR-27) -----------------------------------------------------


@dataclass(frozen=True)
class StageResult:
    stage: str
    evidence: tuple[str, ...]
    partial: bool

    def row(self, key: SubKey) -> dict[str, Any]:
        return {
            "publisher": key.publisher,
            "plugin": key.plugin,
            "version": key.version,
            "stage": self.stage,
            "stage_partial": self.partial,
            "evidence": list(self.evidence),
        }


def _latest_review(view: RecordsView, key: SubKey) -> str | None:
    outcomes = view.reviews.get(key)
    return outcomes[-1] if outcomes else None


def _records_stage(view: RecordsView, key: SubKey) -> StageResult:
    """The coarse records-only stage; PR-dependent refinement happens above."""
    ops = view.ops(key)
    if "publish" in ops:
        return StageResult("published", ("lifecycle:publish",), False)
    if "withdraw" in ops:
        return StageResult("withdrawn", ("lifecycle:withdraw",), False)
    latest = _latest_review(view, key)
    if latest is not None:
        # accepted stays accepted (the signed refinement needs PR state);
        # changes-requested and the rejected mapping render at the same
        # coarse stage — a closed PR could still withdraw either.
        stage = "accepted" if latest == "accepted" else "changes requested"
        return StageResult(stage, (f"review:{latest}",), stage in _RECORDS_PARTIAL_STAGES)
    return StageResult("submitted", ("records:submission",), True)


def derive_stage(view: RecordsView, key: SubKey, pr: PullRequest | None) -> StageResult:
    """One submission's stage under the section 2.2 precedence table.

    Full mode: PR state was consulted, so the result is never partial —
    ``pr is None`` here means the submission HAS no PR (checked), making it
    records-final. Records-only mode calls :func:`_records_stage` directly,
    whose partial semantics mark every stage PR state could have raised.
    """
    base = _records_stage(view, key)
    if base.stage == "published":
        return base  # precedence 1 dominates every PR-derived stage
    if pr is None:
        # Checked against available PR state: no PR exists — records-final.
        return StageResult(base.stage, base.evidence, False)
    if pr.state == "closed":
        # Precedence 2's PR arm: closed-unmerged with no publish record.
        return StageResult("withdrawn", (f"pr:{pr.number}:closed-unmerged",), False)
    latest = _latest_review(view, key)
    if latest == "accepted":
        if pr.carries_manifest_sig(key):
            return StageResult(
                "signed",
                ("review:accepted", f"pr:{pr.number}:carries-manifest.sig"),
                False,
            )
        return StageResult("accepted", ("review:accepted",), False)
    if latest is not None:
        return StageResult("changes requested", (f"review:{latest}",), False)
    if "changes_requested" in pr.reviews:
        return StageResult(
            "changes requested", (f"pr:{pr.number}:review-changes-requested",), False
        )
    if pr.reviews:
        return StageResult("in review", (f"pr:{pr.number}:review-activity",), False)
    if pr.state == "open":
        return StageResult("submitted", (f"pr:{pr.number}:open",), False)
    # A merged PR whose records have not landed yet: records-derived, final.
    return StageResult(base.stage, base.evidence, False)


# --- the reports ------------------------------------------------------------------


def _stage_row(
    view: RecordsView, key: SubKey, prs: dict[SubKey, PullRequest] | None
) -> dict[str, Any]:
    """Records-only when no PR state (``prs is None``); full mode otherwise."""
    if prs is None:
        return _records_stage(view, key).row(key)
    return derive_stage(view, key, prs.get(key)).row(key)


def queue_report(clone: Path, pr_state: PRState | None) -> dict[str, Any]:
    """The maintainer's queue: every submission's stage, ranked and evidenced."""
    view = load_records_view(clone)
    prs = pr_state.by_key() if pr_state is not None else None
    keys = set(view.submissions) | set(view.lifecycle) | set(view.reviews)
    if prs is not None:
        keys |= set(prs)
    disclosures: list[str] = []
    if pr_state is None:
        disclosures.append(STAGE_PARTIAL_DISCLOSURE)
    else:
        for pr in pr_state.prs:
            if not pr.submission_keys():
                disclosures.append(
                    f"pr_unmapped:{pr.number} ({pr.head_ref} carries no "
                    "records/submissions/<publisher>/<plugin>/<version>/ path; "
                    "submission keys are never guessed from branch names)"
                )
    return {
        "submissions": [_stage_row(view, key, prs) for key in sorted(keys)],
        "disclosures": disclosures,
    }


def status_report(
    clone: Path, publisher: str | None = None, plugin: str | None = None
) -> dict[str, Any]:
    """The contributor surface (CR-31): records-only, publisher-scoped.

    Exact submission sets plus each release's lifecycle event timeline —
    no PR state is read, so the same ``stage_partial`` disclosure applies.
    """
    view = load_records_view(clone)
    keys = set(view.submissions) | set(view.lifecycle) | set(view.reviews)
    if publisher is not None:
        keys = {key for key in keys if key.publisher == publisher}
    if plugin is not None:
        keys = {key for key in keys if key.plugin == plugin}
    return {
        "publisher": publisher,
        "plugin": plugin,
        "submissions": [_stage_row(view, key, None) for key in sorted(keys)],
        "releases": [
            {"publisher": key.publisher, "plugin": key.plugin,
             "version": key.version, "timeline": view.timeline(key)}
            for key in sorted(keys)
        ],
        "disclosures": [STAGE_PARTIAL_DISCLOSURE],
    }


# --- lifecycle record appends + the status-document discipline --------------------
#
# (The keyed write commands — publish-status, yank, advise — and the
# record-only ones — unlist, withdraw, transfer — land with their own
# commits against this module; every write is an append-only new file under
# records/lifecycle/<publisher>/<plugin>/<version>/<seq>-<op>.json plus, for
# the status-document commands, the one sanctioned content-change target:
# the release's status.json/status.sig pair under sequence+1 semantics.)


def append_lifecycle_record(
    clone: Path,
    key: SubKey,
    op: str,
    *,
    actor: str,
    reason: str,
    kind: str = "admitted-release",
    extra: dict[str, Any] | None = None,
) -> Path:
    """Append one lifecycle record as a NEW file (never a rewrite).

    The sequence number is the release's next file sequence — max existing
    plus one — matching the committed ``<seq>-<op>.json`` naming.
    """
    if kind not in {"admitted-release", "in-tree-fixture", "community-shared"}:
        raise RegistryOpsError(
            f"record_kind_invalid:{kind} (admitted-release | in-tree-fixture | community-shared)"
        )
    view = load_records_view(clone)
    seq = max((entry.seq for entry in view.lifecycle.get(key, ())), default=0) + 1
    block: dict[str, Any] = {
        "op": op,
        "publisher": key.publisher,
        "plugin": key.plugin,
        "version": key.version,
        "reason": reason,
    }
    if extra:
        block.update(extra)
    record = {
        "record_type": "lifecycle",
        "record_version": "1.1.0",
        "kind": kind,
        "created_at": _now_utc(),
        "actor": actor,
        "lifecycle": block,
    }
    path = clone / "records" / "lifecycle" / key.publisher / key.plugin / key.version
    path.mkdir(parents=True, exist_ok=True)
    target = path / f"{seq}-{op}.json"
    if target.exists():
        raise RegistryOpsError(
            f"record_sequence_conflict:{target} (append-only writes never overwrite)"
        )
    target.write_bytes(canonical_bytes(record))
    return target


def _now_utc() -> str:
    from datetime import datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
