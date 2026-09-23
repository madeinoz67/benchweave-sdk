# Issue #170 — `compatibility.notes` preservation through sync regeneration

- Date: 2026-09-24
- Status: design (pre-implementation; this record precedes any change on the fix branch)
- References: gateway issue
  [#170](https://github.com/madeinoz67/benchweave/issues/170) (single issue stream — no
  SDK-side issue exists by design); the AR-6 pairing note it protects originates in the
  #147 design record (`.claude/deep-review/2026-09-22-issue147-transport-provider-contracts.md`)
- SDK base: `main` @ `6121c96`
- Scope: the sync writer's treatment of one lock field. No corpus bytes move, no lock
  schema changes, no check lane changes.

## 0. Grounding — verified against code this session, not the issue prose

1. **The erasure is structural.** `standards_sync.py::_write_vendored` (line 541)
   constructs the new lock document fresh; the compatibility block is built from
   constants plus `_sdk_version()` and hardcodes `"notes": None` (line 585). The old
   lock — read at the top of `sync()` (line 47) for classification — is never consulted
   for it. Every import sync regenerates the lock, so every import sync erases a filled
   `compatibility.notes`. There is no conditional anywhere: a no-op re-import of the
   identical bundle (all-empty `SyncReport`) still runs `_write_vendored` and still
   nulls the field.

2. **The live lock carries the AR-6 pairing text today** (`standards-lock.json`
   `compatibility.notes`: the increment-2/increment-3 pairing constraint, filled at the
   #147 fold landing). It survives only because no sync has run since. The #147 fill had
   to ride the same commit as the sync precisely because a later sync would null it —
   the workflow pain the issue files.

3. **Every SDK verification lane is blind to the compatibility block.** `_verify_tree`,
   `_verify_self_consistency` → `_verify_state`, `verify_installed`, and the
   `hatch_build.py` packaging hook all walk `lock["standards"]` rows (digests, stamps,
   extras sweep). None reads `compatibility`. Consequences: (a) the erasure is invisible
   to every SDK gate — no lane needs to change for preservation, and none could have
   caught the erasure; (b) a preserved notes value cannot break any lane.

4. **The main repository polices the field, one repo away.** CON-12
   (`BenchWeave/docs/internal/invariants.md`): the manifest's `sdk_compatibility`
   mirror must equal the SDK lock's `compatibility` block at the pinned gitlink —
   `standards/check.py::_compare_mirror` refuses `sdk_compatibility_drift`, including
   the non-string form (`SDK lock {field} is not a string or null`, pinned by
   `tests/standards/test_check.py::test_mirror_refuses_non_string_lock_values_without_laundering`);
   null and empty notes normalise equal
   (`test_mirror_null_and_empty_notes_normalise_equal`). Separately,
   `docs/development.md` documents the halt: a null notes halts the check with
   `compatibility_incomplete` "until the migration note is present. That halt is the
   operator prompt." So an erasing sync does not just drop text — it breaks the main
   gate until the note is re-authored from git history, and it invites the wrong fix
   (nulling the mirror to match). The guard exists, but it lives in the other repository
   and fires only after the SDK-side damage is committed.

5. **The precedent exists in-tree.** The main repository's `repin`
   (`src/benchweave/standards/repin.py::repin_manifest`, invariant CON-7) is the one
   mechanical writer of corpus-manifest pins: it rewrites existing rows' digests and
   nothing else — "Rows themselves — path, source, order, count — stay hand-authored
   under governance review … because a machine cannot know reset-import vs supersession-copy
   provenance." A machine writer that regenerates machine-verifiable state while
   byte-preserving operator-authored provenance is the established pattern; the SDK's
   `_write_vendored` violates it for exactly one field.

6. **Test machinery exists.** `tests/test_standards_sync.py::_export` rebuilds a
   corpus-shaped bundle from the committed lock + vendored tree; `_synced_sdk` makes a
   fake sdk root and syncs it. `test_unchanged_resync_is_noop_report` is already the
   no-op re-import vehicle (it asserts the report, not the lock's compatibility). The
   mid-file helpers `_manifest`/`_rewrite_manifest` rewrite bundle manifests for
   version-bump arms. No existing test in `test_standards_sync.py` or
   `test_sync_atomicity.py` asserts anything about `compatibility` (both files read in
   full this session) — so nothing pre-existing pins the erasure.

7. **Adjacent pins that must stay untouched.** `test_sync_atomicity.py` drives only
   `sync()` (never `_write_vendored` directly), and its read-counting test
   (`test_each_bundle_file_is_read_exactly_once`) counts `_bundle_file` reads — bundle
   files, not the lock. The lock is already read once by `sync()`; this design adds one
   more small-file read inside the writer, which no pin counts.

## 1. Root cause

`_write_vendored`'s lock construction treats the whole document as machine-derived, but
one member of `compatibility` is operator-authored prose. The writer has two kinds of
state and only one code path. `notes` is not derivable from the bundle, from the tree,
or from `pyproject.toml` — the same class of fact as repin's `source` provenance — so
regenerating it can only ever produce the placeholder `None`. The defect is the missing
distinction between regenerated state and carried state, not a wrong value.

## 2. The fork, decided

**Preserve-through-regeneration (chosen) vs designated owner (rejected).** A designated
owner — moving `notes` out of the lock into a hand-authored side file, or making the
main-repo mirror the authority — changes the lock's schema (a `lock_version` event),
redefines what CON-12's mirror equality compares, moves `matrix.py`/`check.py`/the
compatibility-matrix render, and turns a writer bug into a cross-repo standards event.
Nothing in the issue or the field's usage demands a new home; the lock is a fine home
with the wrong writer. Minimal increment wins outright.

**Unconditional preservation (chosen) vs report-conditional reset (rejected).** The
documented workflow (`docs/development.md`) reads as though the null-reset is meant to
fire "when a synchronisation changes or deprecates a standard" — a prompt to re-author
the migration note. Making the writer reset `notes` only when the `SyncReport` is
non-empty would require threading the report (or classification) into the writer and
then deciding, per report cell, whether the operator's note is stale: added? removed?
status-only deprecation? Each answer is policy a machine cannot derive — repin's
exact stated reason for never touching provenance — and the substantive-sync erasure
(the #170 pain: re-typing still-current pairing text after every version bump) would
survive. Unconditional preservation plus hand-edit-as-the-only-writer is the only shape
in which the field has one owner. The operator prompt is not lost: `compatibility_incomplete`
still halts on a genuinely absent note (first sync, or an intentional hand-clear), and
an intentionally stale note is cleared by the same hand-edit that would have re-typed it.

## 3. The mechanism

Two functions in `src/benchweave_sdk/standards_sync.py` change; nothing else does.

**(a) `_read_lock_file` (line 264) gains one shape clause** in the existing
validate-once block, inside the `try` so `TypeError` maps through the existing
`lock_invalid:` refusal:

```python
        compatibility = lock.get("compatibility")
        if compatibility is not None:
            if not isinstance(compatibility, dict):
                raise TypeError("compatibility is not a JSON object")
            notes = compatibility.get("notes")
            if not (notes is None or isinstance(notes, str)):
                raise TypeError("compatibility.notes is not a string or null")
```

Rationale, matching the comment already sitting on that block ("keeps a malformed row a
`lock_invalid` refusal in every lane, rather than a bare KeyError from whichever lane
meets it first"): the writer is about to carry this field verbatim, so a malformed value
must be a named refusal in every lane via the one shared reader — not something a
re-sync launders into the placeholder. An absent block stays readable (older shape
tolerated; nothing ever wrote one, but reading it is harmless). The refusal reuses the
existing `lock_invalid` prefix — no new prefix, so the STD-4 list is unchanged.

**(b) `_write_vendored` (line 541) sources `notes` from the committed lock** instead of
the literal, via one new module-private helper:

```python
def _preserved_notes(sdk_root: Path) -> str | None:
    """The committed lock's operator-authored ``compatibility.notes``, carried verbatim.

    Never regenerated: a machine cannot know whether the operator's pairing or
    migration note still holds, so it must not decide — the main repository's repin
    takes the same posture toward hand-authored ``source`` provenance. Hand-editing
    the lock remains the only way to set, update or clear the field. A first sync
    (no lock) or a lock without the block writes ``None``.
    """
    compatibility = _read_lock(sdk_root).get("compatibility")
    if not isinstance(compatibility, dict):  # validation makes this unreachable; keeps the helper total
        return None
    notes = compatibility.get("notes")
    return notes if isinstance(notes, str) else None
```

and the construction becomes `"notes": _preserved_notes(sdk_root)`.

**Why read inside the writer rather than pass down from `sync()`.** `sync()` already
holds the parsed old lock and could pass the value in. The writer-internal read is
chosen for a structural reason: `_write_vendored` already takes its recovery inputs
from disk, not from the caller — the parked-tree rescue (`retired.rename(tree)`) reads
the filesystem state a dead sync left behind, because the caller's snapshot cannot be
trusted to be what is on disk now. The preserved note is the same kind of input. It is
also read under `_sync_mutex` (the only call site is inside `with _sync_mutex(...)`),
which makes it at least as fresh as the value `sync()` parsed before the mutex was
acquired; a lock read that refuses there refuses before anything is written. Cost: one
extra read+parse of a ~9 KB JSON per import sync — the single-pass discipline that
matters (bundle files read exactly once) is untouched.

**Atomicity and ordering are unchanged.** The read happens before staging begins; the
lock write stays the final act after the tree swap; the parked-tree recovery, staging
sweep, swap, and best-effort retirement of the old tree are not touched. A sync that
died between the swap's two renames left the pre-crash lock on disk (the dead sync
never reached its lock write), so a recovery sync preserves the note the same way.

## 4. Semantics after the change

- **Preservation is symmetric and verbatim.** A string survives byte-identical
  (`_canonical_json` sorts keys; it does not touch string contents). Absent, null, or
  no-lock-at-all → `None`. Nothing else is a representable input: `_read_lock_file`
  refuses it first.
- **Hand-edit remains the ONLY writer of the field's content.** Sync never authors,
  updates, or clears `notes`; it carries it. Setting, rewording, and clearing are
  hand-edits to the lock, reviewed in the diff like any prose. This sentence is the
  whole policy.
- **The other two members stay machine-owned.** `sdk` regenerates from `pyproject.toml`
  via `_sdk_version` (correct: it is sync provenance — see
  `docs/internal/release-review-matrix.md` row 8's note), and `main_project` keeps its
  hardcoded floor (deferred, §7).
- **Main-side gates are unchanged and still coherent.** CON-12's mirror equality is
  content-agnostic; `compatibility_incomplete` still halts on an absent note; the
  compatibility-matrix render keeps reading the mirror. A stale-but-present note riding
  a version bump is now possible and is the accepted trade (§9 R1) — it is diff-reviewed
  prose, not machine state.

## 5. The measurable proof — tests and the pre-committed acceptance rule

New section at the bottom of `tests/test_standards_sync.py` (after `_manifest` /
`_rewrite_manifest`, which it reuses), three parametrized tests, six cells:

1. `test_resync_preserves_a_filled_compatibility_notes` — parametrized
   `no-op-reimport` / `version-bump` (the bump arm rewrites the bundle manifest's otdp
   version to `0.3.1`, the existing pattern). Both arms: `_synced_sdk`, hand-edit the
   lock's notes to a fixed string (a tiny `_hand_edit_notes` helper writing canonical
   JSON, the same dump shape the tests already use), re-sync, assert the lock's notes
   equals the string, then `sync(None, sdk, check_only=True)` to prove the preserved
   lock still verifies. Report assertions per arm (all-empty vs `changed == ("otdp",)`).
2. `test_resync_leaves_an_absent_note_null` — parametrized `never-set` / `hand-cleared`.
   Both arms assert the lock's notes is `None` after a re-sync. These are the CONTROL
   cells: green before the fix and after it; their job is to catch overcorrection (a fix
   that invents a value, drops the null case, or crashes on the no-note lock).
3. `test_a_malformed_compatibility_block_is_a_lock_invalid_refusal` — parametrized
   `notes-is-42` / `block-is-a-list`. Both arms hand-corrupt the lock, expect
   `pytest.raises(ValueError, match="^lock_invalid: ")` from `sync`, and assert the
   lock's bytes are unchanged (refusal before any write).

**Discrimination (why fluff cannot pass this matrix).** The two nearest wrong
implementations each fail a distinct cell: an implementation that validates but still
resets fails both preservation cells; an implementation that blindly copies the old
block without validation fails both refusal cells (the corruption rides through). Only
carry-verbatim-plus-validate passes all six.

**Acceptance rule — pre-committed before any run.**

- **RED** (on `main` @ `6121c96` with ONLY the new tests added): exactly the four
  non-control cells fail — the two preservation cells fail on `None != "…"` and the two
  refusal cells fail because `sync` succeeds instead of raising (pytest exits nonzero
  with precisely these four failures and nothing else new). The two control cells pass.
- **GREEN** (fix applied): all six cells pass, and the battery is green from the SDK
  root with `UV_PROJECT_ENVIRONMENT=venv`: `uv run ruff check .` (0 findings), bare
  `uv run mypy` (clean, config-driven — CI's `mypy src` must agree), `uv run pytest -q`
  (exit 0; collected count = the pre-change count + 6; read from `--junitxml`
  attributes or exit codes, never an output-filter summary line), and
  `uv run benchweave-sdk sync-standards --check` (exit 0 — the committed state is
  untouched by the change, so the no-bundle lane must stay green as-is).
- **Ship if**: the four cells go red for the stated reasons on main and green only with
  the fix; no check lane, no swap/staging ordering, and no `hatch_build.py` line
  changed; zero pre-existing tests flip.
- **Kill if**: preservation turns out to require restructuring the writer's write
  ordering or touching any verification lane (the mechanism is more entangled than a
  read — then redesign, do not force it); or a pre-existing test defends the
  unconditional null as desired semantics with a reason (none is known; both sync test
  files were read in full — then the premise, not the test, gets re-argued with that
  evidence).
- **Underpowered-equivalent**: if a preservation cell is already green on main, the
  erasure premise is false — stop and re-ground; do not tune the test until it fails.
  (Deterministic mechanism: there is no sample-size question; the six cells ARE the
  matrix, and the RED run is the live demonstration of the erasure on a
  corpus-shaped bundle. The committed checkout is never mutated to prove it.)

CI cost: zero new jobs; +6 cells on the `sdk` job's existing pytest leg; one extra
small-file read per import sync at runtime.

## 6. Invariant and cross-surface impacts

| Surface | Impact |
|---|---|
| STD-1 (lock ↔ tree ↔ stamps) | Untouched — rows, digests, stamps, sweep unchanged. |
| STD-2 (digests recomputed from bundle bytes) | Untouched — preservation affects only the compatibility block; the rows still come from `recomputed`. |
| STD-3 (three lanes symmetric) | Untouched — no lane reads `compatibility`; nothing to keep symmetric. Confirmed by reading `_verify_tree`, the no-bundle lane, `verify_installed`, and `hatch_build.py`. |
| STD-4 (refusal prefixes) | The new refusal reuses `lock_invalid`; the prefix list does not change. |
| STD-5 / TWO-1 (normative content main-first; landing order) | Untouched — no vendored byte moves. Landing is the standard two-repo order: SDK commit pushed, SDK PR (body notes gateway #170, no SDK-side issue by design), then the main pointer commit. |
| Proposed new row | Add **[STD-6]** to `docs/internal/invariants.md`: the lock's `compatibility.notes` is operator-authored state — sync carries it verbatim and never authors, updates, or clears it; hand-edit is the only writer; a malformed value is a `lock_invalid` refusal in every lane — anchored on `standards_sync.py::_preserved_notes`, pinned by the §5 tests. One row, one sentence of why (the #170 erasure is the evidence). |
| Main repo — code | Nothing moves. CON-12 (`check.py::_compare_mirror`), CON-4's gate, `matrix.py`, `manifest.py` are content-agnostic. |
| Main repo — docs | `docs/development.md` §"Standards synchronisation": the paragraph teaching "sync writes the lock's `compatibility.notes` as `null` — fill it in before committing" becomes wrong (sync now preserves; null appears only when no prior note existed). **Rider on the main pointer commit** — a one-paragraph correction, prose deferring to the machine source. `standards/GOVERNANCE.md`'s mirror paragraph stays accurate as written. |
| SDK docs | `docs/internal/invariants.md` gains the STD-6 row (above). `docs/internal/drift-and-obligations.md` item 3 is walked: the compatibility-notes surface is exactly what changed, and its paired main-side surface is named. No README or user-guide surface documents the notes behavior (checked); `docs/internal/release-review-matrix.md` reads `main_project`/`sdk`, not `notes` — unaffected. |
| On-disk format / schema | **No change** — same keys, same shapes, `notes` stays string-or-null, `lock_version` stays 1. Not a Tier-3 review subject; this is a behavioral fix with RED proof. |

## 7. Deferrals

| # | Deferred | Home |
|---|---|---|
| 1 | `main_project` preservation (same defect class: a hand-edited floor would be erased by the hardcoded `">=0.1.0"`). Not named by the issue, no hand-edit history, and the release-review matrix treats the field as a floor the lock carries — changing its ownership is a release-semantics decision, not a rider. | This design-record row. Reopen only if an operator ever authors a non-default floor. |
| 2 | SDK-side validation of `main_project`/`sdk` string-ness in `_read_lock_file`. The writer regenerates both, so there is nothing to preserve and nothing to launder; main's `_compare_mirror` already refuses drift on them. | This design-record row. |
| 3 | An SDK `--check`-lane assertion that a committed lock's notes is well-formed (SDK-side policing of its own field). SDK lanes verify bytes, not prose; CON-12's main-side refusal is the existing backstop. | This design-record row. |

Zero follow-on issues filed (deferral-discipline rule 3, 2026-09-20: deferrals live in
design-record tables, not tracker rows; at most one follow-on issue per merged PR —
this proposes none).

## 8. Precedents (all read this session)

- `BenchWeave/src/benchweave/standards/repin.py::repin_manifest` — the posture:
  machine writer regenerates digests, byte-preserves hand-authored provenance, refuses
  structural surprises fail-closed, pinned by `tests/standards/test_repin.py`
  (invariant CON-7). This design is that posture applied to one SDK lock field.
- `standards_sync.py::_write_vendored`'s parked-tree recovery — the writer-owns-disk-
  state pattern the internal lock read extends.
- `standards_sync.py::_read_lock_file`'s existing shape-check loop and its comment —
  the one-place validation the new clause joins.
- `tests/test_standards_sync.py` — the "Guards a mutation run showed unpinned" section
  and the parametrized `first_sync`/`resync` shape the new tests reuse.

## 9. Top risks, ranked

1. **Semantic shift: a stale note can now ride a version bump silently.** An operator
   who relied on the null-reset prompt to re-author migration notes loses it for
   substantive syncs. Mitigated: the note is diff-reviewed prose, the matrix render
   carries it, CON-12 keeps mirror == lock, and `compatibility_incomplete` still halts
   on genuinely absent notes. Falsified if a real workflow is found that depends on the
   reset — the #147 fill (which had to fight the reset) is the known counter-case.
2. **The new `lock_invalid` clause refuses locks that previously synced.** Every lock
   ever written by `_write_vendored` carries the well-formed block, and wheels package
   that same lock (PKG-2), so no real population is affected. Falsified if any CI lane
   or installed-distribution check reds on a committed lock after the change.
3. **Main-side doc drift if the rider is forgotten.** The mirror gate cannot catch the
   stale `docs/development.md` paragraph. Mitigated by naming it as the pointer-PR
   rider here and in the PR body; it converts to a gateway-tracker follow-up only if
   the pointer PR lands without it.
4. **Mid-sync hand-edit torn window** (the lock is now read twice: once in `sync()`
   before the mutex, once in the writer under it). The under-mutex read is the fresher
   value; a hand-edit during a sync was never supported — the sync overwrites the lock
   afterward regardless. Not observable by any current pin.

## 10. Verdict

BUILD. The live AR-6 note is one ordinary sync away from erasure, the erasure breaks
the main gate until the text is re-authored from history, the fix extends two proven
in-tree patterns (repin's carry-don't-regenerate posture; the lock reader's
validate-once refusal), the proof is a deterministic six-cell matrix with a pre-committed
acceptance rule, and the blast radius is two functions plus one test section.
