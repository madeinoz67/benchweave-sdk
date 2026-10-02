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

import hashlib
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


# --- the status-document discipline (the section 1.2 fix, generalized) ----------
#
# One monotone sequence per release: publish-status writes the baseline pair
# (sequence 1, lifecycle published); yank and advise rewrite under sequence+1
# and re-sign — mirroring exactly what the gateway resolver enforces
# (check_status sequence/expiry gates, _gate_lifecycle's yanked/revoked
# refusals). CR-12: the origin key is a LOCAL FILE argument to a
# maintainer-run command; it never enters either repository or any CI.
# CR-13/Q12 restated: nothing here changes admission semantics — the lane
# compensates process-side (signed status + records), never admission-side.

_VENDORED_STATUS_SCHEMA = (
    Path(__file__).parent / "standards" / "registry" / "0.1.1" / "release-status.schema.json"
)
_ADVISORY_SEVERITIES = ("info", "low", "medium", "high", "critical")


def release_dir(clone: Path, key: SubKey) -> Path:
    """The release's served directory; absent releases refuse naming the path."""
    releases = clone / "releases"
    if not releases.is_dir():
        raise RegistryOpsError(f"release_absent: no releases/ tree under {clone}")
    for child in sorted(releases.iterdir()):
        if child.is_dir():
            directory = child / key.publisher / key.plugin / key.version
            if (directory / "manifest.json").is_file():
                return directory
            raise RegistryOpsError(
                f"release_absent:{directory} (no manifest.json under the release path)"
            )
    raise RegistryOpsError(f"release_absent:{releases} (empty releases tree)")


def _validate_status_doc(doc: dict[str, Any]) -> None:
    """Refuse any status document that would fail the served schema."""
    import jsonschema

    schema = json.loads(_VENDORED_STATUS_SCHEMA.read_bytes())
    try:
        jsonschema.validate(doc, schema)
    except jsonschema.ValidationError as exc:
        raise RegistryOpsError(f"status_invalid:{exc.message}") from exc


def _write_status_pair(
    clone: Path, directory: Path, doc: dict[str, Any], key_path: Path
) -> Path:
    """Validate, sign, cross-check the clone's root, then write the pair."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from .publishing import sign_manifest_bytes

    _validate_status_doc(doc)
    data = canonical_bytes(doc)
    signature = sign_manifest_bytes(data, key_path)
    root = clone / "keys" / "main.pub.pem"
    if root.is_file():
        # F2's committed root: a signing key the served root would reject
        # refuses HERE, before unresolvable bytes ever land in the tree.
        try:
            public = serialization.load_pem_public_key(root.read_bytes())
            assert isinstance(public, Ed25519PublicKey)
            public.verify(signature, data)
        except (InvalidSignature, ValueError) as exc:
            raise RegistryOpsError(
                f"origin_key_mismatch:{root} does not verify this signature; "
                "sign with the origin key the clone serves"
            ) from exc
    status_path = directory / "status.json"
    status_path.write_bytes(data)
    (directory / "status.sig").write_bytes(signature)
    return status_path


def _publisher_contact(clone: Path, publisher: str) -> str | None:
    """The publisher's support contact from the vetted publishers file."""
    path = clone / "records" / "publishers.json"
    if not path.is_file():
        return None
    try:
        publishers = json.loads(path.read_bytes())
    except ValueError as exc:
        raise RegistryOpsError(f"publishers_invalid:{path} ({exc})") from exc
    for entry in publishers.get("publishers", []):
        if entry.get("publisher_id") == publisher and entry.get("github"):
            return f"https://github.com/{entry['github']}"
    return None


def publish_status(
    clone: Path,
    key: SubKey,
    *,
    key_path: Path,
    reason: str = "initial publication",
    expires_at: str | None = None,
    support_state: str = "maintained",
    support_contact: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Write the baseline status pair (sequence 1, lifecycle published).

    Returns the document and whether the expiry was defaulted (disclosed by
    the caller — a commissioned expiry is an explicit decision).
    """
    from datetime import datetime, timedelta

    directory = release_dir(clone, key)
    status_path = directory / "status.json"
    if status_path.is_file():
        raise RegistryOpsError(
            f"status_present:{status_path} (sequence 1 is the baseline; "
            "later motions go through yank/advise under sequence+1)"
        )
    manifest_bytes = (directory / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if (
        manifest.get("package_id") != f"{key.publisher}/{key.plugin}"
        or str(manifest.get("version")) != key.version
    ):
        raise RegistryOpsError(
            f"release_mismatch:{directory / 'manifest.json'} (package_id/version "
            f"disagree with {key.publisher}/{key.plugin}@{key.version})"
        )
    now = _now_utc()
    defaulted = expires_at is None
    if defaulted:
        expires_at = (datetime.now(UTC) + timedelta(days=365)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    contact = support_contact or _publisher_contact(clone, key.publisher)
    if contact is None:
        raise RegistryOpsError(
            "support_contact_absent: no vetted publisher entry names "
            f"{key.publisher}; pass --support-contact"
        )
    doc: dict[str, Any] = {
        "status_version": "0.1.1",
        "release": {
            "registry_id": directory.parents[2].name,
            "package_id": f"{key.publisher}/{key.plugin}",
            "version": key.version,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        },
        "sequence": 1,
        "updated_at": now,
        "expires_at": expires_at,
        "lifecycle": "published",
        "reason": reason,
        "support_state": support_state,
        "support_contact": contact,
        "reviews": [],
        "advisories": [],
    }
    _write_status_pair(clone, directory, doc, key_path)
    return doc, defaulted


def _read_current_status(
    clone: Path, key: SubKey, refusing_op: str
) -> tuple[Path, dict[str, Any]]:
    directory = release_dir(clone, key)
    status_path = directory / "status.json"
    if not status_path.is_file():
        raise RegistryOpsError(
            f"{refusing_op}:{status_path} (no status document; run "
            "'benchweave-sdk registry publish-status' first)"
        )
    current = _load_json(status_path)
    if not isinstance(current, dict) or not isinstance(current.get("sequence"), int):
        raise RegistryOpsError(f"status_invalid:{status_path} (no sequence)")
    return status_path, current


def yank_release(
    clone: Path,
    key: SubKey,
    *,
    key_path: Path,
    reason: str,
    actor: str,
    kind: str = "admitted-release",
) -> tuple[dict[str, Any], Path]:
    """Sequence+1 lifecycle yanked, preserving advisories and support fields."""
    _status_path, current = _read_current_status(clone, key, "yank_status_absent")
    sequence = int(current["sequence"]) + 1
    doc = {
        **current,
        "sequence": sequence,
        "lifecycle": "yanked",
        "reason": reason,
        "updated_at": _now_utc(),
    }
    _write_status_pair(clone, _status_path.parent, doc, key_path)
    record = append_lifecycle_record(
        clone, key, "yank",
        actor=actor, reason=reason, kind=kind,
        extra={
            "release_manifest_sha256": doc["release"]["manifest_sha256"],
            "status_sequence": sequence,
        },
    )
    return doc, record


def advise_release(
    clone: Path,
    key: SubKey,
    *,
    key_path: Path,
    actor: str,
    advisory: dict[str, str],
    kind: str = "admitted-release",
) -> tuple[dict[str, Any], Path]:
    """Append one advisory under sequence+1; lifecycle is untouched."""
    for field, ok in (
        ("id", bool(advisory.get("id"))),
        ("summary", bool(advisory.get("summary"))),
        ("severity", advisory.get("severity") in _ADVISORY_SEVERITIES),
        ("url", advisory.get("url", "").startswith("https://")),
    ):
        if not ok:
            raise RegistryOpsError(
                f"advisory_field_invalid:{field} (severity is one of "
                + "|".join(_ADVISORY_SEVERITIES)
                + "; url must be https)"
            )
    _status_path, current = _read_current_status(clone, key, "advisory_status_absent")
    existing = list(current.get("advisories", []))
    if any(entry.get("id") == advisory["id"] for entry in existing):
        raise RegistryOpsError(
            f"advisory_duplicate:{advisory['id']} already rides this status"
        )
    sequence = int(current["sequence"]) + 1
    doc = {
        **current,
        "sequence": sequence,
        "advisories": [*existing, dict(advisory)],
        "updated_at": _now_utc(),
    }
    _write_status_pair(clone, _status_path.parent, doc, key_path)
    record = append_lifecycle_record(
        clone, key, "advisory",
        actor=actor,
        reason=f"advisory {advisory['id']} ({advisory['severity']}): {advisory['summary']}",
        kind=kind,
        extra={"advisory": dict(advisory)},
    )
    return doc, record


def unlist_release(
    clone: Path,
    key: SubKey,
    *,
    reason: str,
    actor: str,
    kind: str = "admitted-release",
) -> Path:
    """Append the unlist record ONLY — no status document is read or written.

    An unlisted release stays resolvable and admissible (CR-32/E4): the
    catalogue row drops at index regeneration (the registry lane's generator
    arm); the served state is untouched.
    """
    return append_lifecycle_record(
        clone, key, "unlist", actor=actor, reason=reason, kind=kind
    )


def withdraw_release(
    clone: Path,
    key: SubKey,
    *,
    reason: str,
    actor: str,
    kind: str = "community-shared",
) -> Path:
    """Pre-acceptance withdrawal only (CR-32).

    Refuses once a publish record exists: post-signing withdrawal is an
    advisory or an unlist, never a silent disappearance.
    """
    view = load_records_view(clone)
    if "publish" in view.ops(key):
        raise RegistryOpsError(
            f"withdraw_after_publication:{key.publisher}/{key.plugin}@{key.version} "
            "(a publish record exists; post-signing withdrawal is an advisory "
            "or an unlist — CR-32)"
        )
    return append_lifecycle_record(
        clone, key, "withdraw", actor=actor, reason=reason, kind=kind
    )


def transfer_release(
    clone: Path,
    key: SubKey,
    *,
    to_publisher: str,
    consent_from: str,
    consent_to: str,
    vetting_reference: str,
    reason: str,
    actor: str,
    kind: str = "admitted-release",
) -> Path:
    """Append the transfer record (CR-17/Q9: transfer is re-vetting).

    Both consents must name their publisher; the receiver's vetting
    reference is recorded verbatim — its resolution against publishers.json
    and the V-rows is the registry's records-CI arm (design section 2.4),
    not this command's.
    """
    if to_publisher == key.publisher:
        raise RegistryOpsError(
            f"transfer_invalid:same_publisher ({to_publisher} already owns the release)"
        )
    if key.publisher not in consent_from:
        raise RegistryOpsError(
            f"transfer_invalid:consent_from_not_naming:{key.publisher} "
            f"(got {consent_from!r})"
        )
    if to_publisher not in consent_to:
        raise RegistryOpsError(
            f"transfer_invalid:consent_to_not_naming:{to_publisher} "
            f"(got {consent_to!r})"
        )
    if not vetting_reference.strip():
        raise RegistryOpsError(
            "transfer_invalid:vetting_reference_absent (cite the receiver's "
            "publishers.json entry and V-rows)"
        )
    return append_lifecycle_record(
        clone, key, "transfer",
        actor=actor, reason=reason, kind=kind,
        extra={
            "transfer": {
                "from_publisher": key.publisher,
                "to_publisher": to_publisher,
                "consents": [consent_from, consent_to],
                "vetting_reference": vetting_reference,
            }
        },
    )
