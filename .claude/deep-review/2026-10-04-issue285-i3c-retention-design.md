# Issue #285 — I3c: retention, storage guard, shutdown — design record

Date: 2026-10-04. Status: DESIGN (no code written). Repo: `benchweave-sdk`,
branch `feat/issue285-i3c-retention`, based on `feat/issue285-i3b-capture`
(I3b at fold-refute-complete, unmerged; I3c rebases/merge-serial after I3b
lands). This file is the branch's first commit, not pushed.

Authority chain: the I3 record
(`.claude/deep-review/2026-10-04-issue285-i3-hardware-capture-design.md`, with
its two dated addenda) is the slice-map authority — its §1 I3c row and §5
AR-9/10/11 define scope and proof shapes; PRD 11 (Draft v0.3) rows SW-49,
SW-55–59, NFR-O1 are the requirements. This record sharpens the mechanism
against the LANDED I3a/I3b code (cited `file:line` throughout), absorbs the
residuals the folds disclosed as I3c's by right, and pre-commits the
acceptance rules before any measurement runs.

## 0. Verification of premises (done before designing)

Read from the branch, not assumed:

- The I3 record's I3c section names: `retention.py` (rule engine, keep-
  everything defaults per Q13's unruled fork F-3), prune (schedule in-host +
  CLI with `--dry-run`), the append-only `captures/retention.log`, the
  SW-58 storage guard, the NFR-O1 close-down, and the SW-49 library UI.
  AR-9/10/11 are the proof shapes; the exit-gate clause this slice must be
  able to prove is "a retention dry run and prune match configured rules
  with every removal in the retention log".
- PRD rows, exact: SW-55 (rules by source tag and project; each any of max
  age/count/bytes; "Defaults are set in §8 Q13" — Q13 is UNRULED, so the
  engine ships keep-everything and every default is a parameter); SW-57
  (prune never touches in-flight; schedule + on demand; dry run lists
  removals and their rule; each removal deletes directory and index row
  together and appends (capture id, manifest digest, rule, time, trigger)
  to an append-only retention log in the capture root); SW-58 (`capture_start`
  refused `unavailable` when the bound would breach a CONFIGURED free-space
  reserve; a running capture that reaches the reserve stops and finalises,
  nothing discarded silently); SW-59 (UI delete confirms naming the capture;
  MCP `capture_delete` refuses pinned; neither bypasses the log); NFR-O1
  (SIGINT/SIGTERM/lifespan exit runs the adapter quiet path and finalises or
  aborts in-flight captures; no half-written primary).
- The landed surfaces this builds on: `library.py` (the rebuildable index,
  file-authoritative `metadata.json`, `library.lock` with dead-pid steal,
  `remove()` = directory + row together at library.py:289-299); `seam.py`'s
  capture lifecycle — `_op_capture_start` (1243), the watcher and its LOCKED
  terminal table (1776-1898), `_finalise_capture` (1909), `_abort_capture`
  (1973), the B-F5 stop-timeout escape (1404-1435), `await_capture` (1373,
  whose docstring already names "the lifecycle tests and the shutdown
  close-down" as its consumers), `_op_capture_delete` (1705); `serial.py`'s
  reservation machinery (`configure_capture` 471, the writer-as-authority
  addendum, `artifact_abort`'s manifest-marker gate 629-649); the bus
  (`events.py`, one append-only sequence, seam-only publisher); the CLI
  (`cli.py` — `serve`/`mcp`, `--capture-root`, `_build_seam` as the factory
  point); `web.py`'s lifespan (104-117 — the `finally` that this slice
  extends, with the comment naming I3c) and the CSRF'd HTML-POST pattern
  (device.html:18-29, web.py:781-798).
- The disclosed residuals named I3c's: the lifespan in-flight settle
  (web.py:113-116); FOLD-8's zombie orphan-dir residual (seam.py:1411-1413);
  the I3a addendum's crash-left event-dir id-wedge ("the orphan sweep
  belongs to I3c"); retention-log reuse for `capture_delete` (I3b's ruling
  9 — the recorder this slice builds is the reuse target).
- Q5/Q7/Q13 remain unruled (grep "Ruled" over PRD 11 returns only Q1/Q12).
  The design carries every Q13-dependent value as configuration; it assumes
  no ruling.
- Fixture precedent: `tests/server/test_capture_lifecycle.py`'s
  `LoopbackPort` + scaffolded `wavegen_plugin` with patched descriptors is
  the capture-test fixture shape I3c's arms extend.

Two defects found in the landed I3b state while verifying (§2) ride this
slice as RED-first fixes.

## 1. Mechanism

Four mechanisms, one new module, no `standards/` bytes, no new dependency
(everything is stdlib: `json`, `sqlite3` already in-tree, `shutil`,
`asyncio`, `time`).

### 1.1 `retention.py` — rules, evaluator, recorder, sweep

**The rules document** (one launch configuration artifact, JSON, explicit
path — never silently substituted):

```json
{
  "interval_s": 86400,
  "orphan_grace_s": 900,
  "reserve_bytes": 2000000000,
  "rules": [
    {"id": "mcp-aging", "source": "mcp", "max_age_d": 30},
    {"id": "tunnel-keep-5", "project": "wind-tunnel", "max_count": 5},
    {"id": "root-cap", "max_bytes": 5000000000}
  ]
}
```

- Every top-level key optional. Absent document entirely = keep-everything,
  no scheduler, no reserve, default grace — the Q13 posture (F-3): the
  engine is rule-driven; defaults land only when the PRD is ruled.
- A rule carries optional match keys `source` (one of `ui`/`rest`/`mcp` —
  the closed dispatch-surface set) and `project` (exact string); absent
  keys are wildcards. Limits: any of `max_age_d` (> 0), `max_count`
  (>= 0), `max_bytes` (>= 0); at least one required. Ids unique,
  non-empty (deterministic evaluation needs unique sort keys).
- Loader raises `ValueError` with the `standalone_retention_rules_invalid:`
  prefix on every malformed shape (unknown key, bad type, duplicate id,
  missing limit, unknown source value) — STD-4's machine-matchable shape.

**The evaluator** — `plan(rules, rows, *, now, in_flight_ids) -> list of
{capture_id, rule_id, bytes}`, deterministic and hand-computable:

1. Eligibility: not `pinned`, not in `in_flight_ids` (rows come from the
   library, so "published" is already guaranteed — the manifest exists).
2. A rule APPLIES to a row when every present match key matches.
3. Within an applying rule: `max_age_d` selects rows with
   `now - started_at > max_age_d * 86400` (strictly older, ISO-parsed
   aware datetimes); `max_count` sorts the rule's applicable rows
   newest-first (`started_at` desc, `capture_id` desc as the tiebreak) and
   selects all but the first `max_count`; `max_bytes` keeps the
   newest-first prefix whose sum is `<= max_bytes` and selects the
   complement — precisely: if the total already fits, nothing is selected;
   otherwise the OLDEST rows are selected until the remainder fits (a
   single newest row alone above the cap is itself selected).
4. A row selected by several rules is attributed to the FIRST selecting
   rule in evaluation order (rules sorted by `id`) — the golden set is
   unambiguous.

**The recorder** — `record(root, removals, *, trigger)`: appends one JSONL
row per removal to `<root>/retention.log`
(`{"capture_id", "sha256", "rule", "at", "trigger"}`, open-append-flush per
row — the `record_evidence` pattern at serial.py:466-467), rows sorted by
`capture_id` for determinism. The log is a FILE in the root, not an index
table: it survives index rebuilds by construction. `trigger` is a closed
set: `scheduled` | `cli` | `sweep` | `delete-ui` | `delete-rest` |
`delete-mcp`. The `sha256` is the removed manifest's recorded artifact
digest (the index row's `sha256`) — the log row and the removed capture's
own record name the same bytes. Sweep rows carry `"sha256": null` honestly
(an orphan never published; there is no digest to name).

**The sweep** — `sweep_plan(root, *, now, grace_s, in_flight_ids)`: every
DIRECTORY in the root with no `manifest.json`, not any in-flight capture's
directory, and mtime older than `now - grace_s` (default 900 s,
overridable as `orphan_grace_s`). This is the home of all three disclosed
residuals: FOLD-8's zombie re-staging (a zombie still writing keeps its
mtime fresh — the grace protects it), the crash-left event dir (the I3a
addendum's id-wedge: after the grace, the root is clear and the wedged id
reusable), and crash residue generally. Sweep removals get recorder rows
(`rule: "orphan-sweep"`, `trigger: "sweep"`). The grace is an operational
constant of the host, not a protective envelope — disclosed as such, and
measured from directory mtime (same-host semantics; a root moved between
hosts re-bases mtimes, disclosed).

### 1.2 The prune paths (SW-57)

- **CLI**: `benchweave-sdk-server prune --capture-root <path>
  [--retention-rules <path>] [--dry-run] [--json]`. Root-scoped — no plugin
  project argument. Constructs `CaptureLibrary` (acquiring the root lock; a
  live host refuses the second library exactly as designed — surfaced as
  the existing `standalone_library_locked` refusal, exit 2, CLI help
  states "stop the host or use the in-host schedule"). Dry run prints the
  plan — `--json` emits `{"removals": [...], "summary": {count, bytes}}`
  machine-comparably; prune removes exactly the plan (directory + index row
  together via `library.remove`), records every removal (trigger `cli`),
  and ALSO runs the sweep. A rules-document validation refusal is exit 2
  with the prefix.
- **In-host schedule**: when `serve --retention-rules <path>` names a
  document with rules, the lifespan starts one asyncio task on the seam
  that evaluates every `interval_s` (default 86400 when rules exist and
  the key is absent), over the seam's OWN library instance (the lazy
  `_library("")` — same lock, same process), with the armed capture as
  `in_flight_ids`; removals + recorder rows (trigger `scheduled`) + the
  sweep, then ONE `retention_pruned` bus event per run (data: count, bytes,
  per-rule breakdown) — the bus stays one sequence, seam-only publisher.
  Library mutation is synchronous sqlite with no await points, so the
  scheduler cannot interleave a half-`remove`.
- **Quota warning** (edge-triggered): after each scheduled evaluation, for
  every `max_bytes` rule, publish `retention_quota` `{rule_id, used_bytes,
  cap_bytes, fraction}` when usage crosses 0.8 rising — one latch per rule
  in host state; a rule that re-drops below 0.8 and re-crosses fires again
  (crossing = rising edge), a rule already above at two consecutive
  evaluations fires once. AR-9's control pins exactly-once.

### 1.3 The storage guard (SW-58)

`serve --retention-rules <path>` with `reserve_bytes` set arms the guard.
A02 posture: the reserve is bench-commissioned configuration; a hardcoded
default reserve would impose one bench's storage policy on every bench and
is explicitly REJECTED; with no document (or no `reserve_bytes`), the guard
is inert — the same keep-everything-until-ruled parameterisation as the
rules.

- **At start** (inside `_op_capture_start`, after the bound/reservation
  computation): worst-case `W` = the effective reservation when one exists,
  else the count bound's bytes. A duration bound with NO reservation has an
  unbounded worst case — the guard cannot clear it, so it REFUSES
  `unavailable` with the `standalone_storage_reserve:` prefix naming why
  ("an unbounded capture cannot be cleared against a configured reserve;
  declare max_bytes") — missing information blocks control rather than
  defaulting (A02). When `W` is known: refuse `unavailable` (same prefix)
  when `shutil.disk_usage(root).free - W < reserve_bytes`.
- **Mid-run**: the watcher samples `shutil.disk_usage(root).free` at most
  every `_RESERVE_CHECK_S = 1.0 s` (a host scheduling constant, not a
  protective envelope — 20 Hz statvfs would be waste; a breach is caught
  within poll + 1 s). Breach = free < reserve: the host initiates a stop —
  pending reason `"reserve"`, context cancelled, and the capture
  FINALISES with `stop_reason: "reserve"`, byte_length the real staged
  bytes (nothing discarded silently — the manifest's byte_length is the
  truth). `"reserve"` joins `"stopped"`/`"bound"` as a host-initiated
  finalise reason in the LOCKED terminal table (seam.py:1784-1792): the
  ok-after-forced branch (B-F2) publishes under the host's own reason, so
  an adapter that answers ok after the reserve stop publishes
  `stop_reason: "reserve"`, never relabelled `completed`. PRD SW-58's
  "finalises with status `partial`" is pre-I3b vocabulary; the landed
  terminal model carries the same semantics as a PUBLISHED row with
  `stop_reason: "reserve"` (state `published`, honest stop reason) — this
  reconciliation is disclosed here, not silently reinterpreted.

### 1.4 The close-down (NFR-O1) and the two defect fixes

**`seam.settle_capture_for_shutdown()`**: no capture in flight → `None`.
Else: set the stop event, await the shielded watcher with `_op_capture_stop`'s
own timeout computation (verb timeout + bound grace + settle margin,
seam.py:1392-1396); on `TimeoutError` run the B-F5 escape verbatim (cancel
watcher + task, abort `stop_timeout`); return the outcome row. Exceptions
suppressed into the outcome row — shutdown completes, honestly labelled.
Wired at BOTH entries: `web.py`'s lifespan `finally` calls it BEFORE
`seam.session.close()` (and cancels the scheduler task first); the stdio
`mcp` entry wraps `server.run()` so the settle runs in a fresh loop after
run() returns, then `seam.close()`. SIGKILL is out of scope by physics —
crash residue is the sweep's territory. Reloads need no settle: the reload
guard refuses while a capture is in flight (once Finding A is fixed), so
the I3 record's "and `--authoring` reloads" clause is satisfied
STRUCTURALLY — a reload never coincides with an in-flight capture.

**Finding A — the reload guard's capture leg is inert (defect, RED-first
fix)**: `_capture_in_flight` is initialised `False` (seam.py:229), read by
`_reload_guards` (seam.py:930), and NEVER armed — the landed
`_op_capture_start` (seam.py:1243-1351) sets `self._capture` but not the
flag, and no terminal path clears it. A reload during an in-flight capture
therefore runs the quiet-close→swap under a live capture today. The
guard's own docstring (seam.py:921-922) says the flag "is the state I3's
capture_start will hold" — I3b's capture_start landed without holding it.
Fix: delete the redundant flag; the guard reads the armed state directly
(`self._capture is not None`) — one source of truth, the bad state (armed
capture + reload proceeds) becomes unrepresentable. RED arm: reload during
an in-flight capture must refuse `conflict`.

**Finding B — HTML dispatches record no surface (defect, RED-first fix)**:
every HTML-route `seam.call` site (web.py:624, 638, 728, 752, 768) omits
`surface=`, so `_SURFACE.get()` is `None` on browser dispatches and the
metadata sidecar records `surface: null` (seam.py:1227) — SW-34's "ui" tag
never lands, source-keyed retention rules can never match ui-originated
captures, and I3c's delete route would record trigger `None`. No HTML route
starts a capture today, so the defect is latent in I3b and LIVE the moment
I3c's routes dispatch. Fix: the web layer's dispatch sites pass
`surface="ui"` (the record's own I3b text: "ui"|"rest"|"mcp" supplied by
the dispatch layer). RED arm: an HTML-dispatched capture op records
surface `"ui"`. Reported to the I3b fold lanes for independent
confirmation; either landing home works — I3c carries both if I3b closes
without them.

**`capture_delete` + the recorder (SW-59, ruling 9)**: after
`library.remove`, append the recorder row — rule `"manual-delete"`,
trigger `delete-<surface>` (the dispatch surface via `_SURFACE.get()`,
defaulting `rest` when unset — the closed refusal paths already name the
surface discipline). The in-flight and pinned refusals stay as landed.

### 1.5 The library UI (SW-49)

`GET /captures` renders `templates/captures.html` over the library rows:
capture_id, started_at, format, size, surface, project, tags, pinned,
stop_reason — plus the **next retention effect** per capture, computed by
the SAME evaluator (a per-capture projection helper over `plan()`'s
components — never a second implementation): the first rule that would
select it now ("prunable now by `<rule>`"), an age rule that will select
it at a computed date ("`<rule>` at `<date>`"), a count/bytes rule that
applies ("eligible under `<rule>`"), or "kept". Filters (query params):
project, source, tag, free-text over id/notes — the closed metadata
fields. SW-49's device filter reads `metadata.json` per row at render
(the file is the authority; the index has no device column and this slice
does not widen it — disclosed). Forms: pin/unpin over the existing
catalogue rows; delete via a two-step confirm (`GET /captures/{id}/delete`
names the capture id, size and project; the POST carries CSRF and dispatches
`capture_delete` with `surface="ui"`). The page is display+forms over
landed rows — no new catalogue row, no new capability.

## 2. Root causes verified (not assumed)

- Finding A traced to the missing arming write: verified by reading the
  three sites (init 229, guard read 930, start 1243-1351) — the flag has
  no writer. This is a defect PATTERN worth naming: a guard flag whose
  docstring promises a future arming point, landed two slices later
  without the arming — the comment's promise outlived the code's truth.
- Finding B traced to the parameter default: `call(surface=None)`
  (seam.py:300) + HTML sites omitting the argument. SW-34's mechanism
  exists; the web adapter never fed it.
- The close-down composition: `await_capture` (seam.py:1373-1380) exists,
  documented for exactly this consumer, and has no production caller —
  I3b shipped the primitive and the deferral comment together
  (web.py:113-116). This slice is the promised consumer.

## 3. Precedent (proven in-tree mechanisms extended)

1. `CaptureLibrary` (I3b) — prune and the sweep read/remove through it;
   the lock's one-writer rule IS the prune-vs-host exclusion.
2. The watcher's host-initiated stop family (`stopped`/`bound`) — `reserve`
   joins it; the terminal table is extended by membership, not rewritten.
3. The B-F5 escape (seam.py:1404-1435) — the close-down reuses it verbatim.
4. `record_evidence`'s JSONL append (serial.py:466-467) — the retention
   log's write shape.
5. The lifespan/scheduler pattern: one asyncio task on host state (the
   watcher itself is the precedent, seam.py:1351), cancelled at close-down.
6. The CSRF'd HTML POST + redirect pattern (web.py:781-798, device.html) —
   the captures page's forms.
7. The catalogue→HTML dispatch over `seam.call` (surface fix rides it).
8. `standalone_library_locked` — the existing refusal the CLI prune
   surfaces; no new lock machinery.

## 4. Invariants and cross-surface impacts

- **STD-4**: two new refusal prefixes — `standalone_retention_rules_invalid:`
  and `standalone_storage_reserve:` — both `snake_case:`-prefixed
  ValueErrors/SeamError messages with per-path tests (NFR-Q4 posture); this
  is itself a Tier-3 trigger. `standalone_library_locked` reused unchanged.
- **New on-disk formats**: `retention.log` (JSONL, in the capture root —
  survives index rebuilds by construction; Tier 3). The rules document is
  a new INPUT format with a validated loader and typed refusals. The
  SQLite index schema is UNCHANGED (no `_COLUMNS` motion).
- STD-1..3/5/6, PKG-1..3, SRF-1..3, TWO-1 untouched and upheld: no
  vendored bytes, no dependency add (stdlib only), no scaffold motion, no
  packaging change, wheel target list unchanged. SDK-first landing order
  unchanged (this branch IS the SDK side; the gateway pointer is the
  train's chore).
- Obligations (docs/internal/drift-and-obligations.md): #1 CLI-visible
  behavior (`prune`, `--retention-rules`) → user_guide/plugin-sdk.qmd +
  README; #6 behavioral tests land in `tests/server/`
  (`test_retention.py` new; storage-guard and close-down arms extend
  `test_capture_lifecycle.py`); #4 not triggered (no packaging change);
  the standards tripwire expected EMPTY (verified at commit time:
  `git diff origin/main...HEAD -- standards/` plus no version strings).
- Gateway surfaces: none move (PRD 11's `bws_v1_*` set is not the vendored
  corpus; no new MCP tool — prune is CLI+schedule by SW-57/SW-59's own
  surface split).
- CI cost: no new job; the arms join the existing `sdk` lane's pytest.
  Windows legs CI-corroborated (W1): `shutil.disk_usage`, `Path.stat`
  mtime, and `os.replace` are cross-platform; the direct tests are
  POSIX-run, the CI Windows lane corroborates.

## 5. Review tier and the Step-1 keyword scan (#254 form)

**Tier 3** (SDK rubric, first-match): adds refusal paths (STD-4 surface
extension) and a new persisted on-disk format (`retention.log`) with
deletion semantics → two independent adversary lanes (standing rule).

Step-1 keyword scan (the eight keywords) over the EXPECTED diff text
(docs and code alike; estimates from §1, re-derived at review against the
real diff): `threading` 0 (no new threads — the scheduler is an asyncio
task), `asyncio` ≈ 9 (scheduler task, settle, watcher edits, tests),
`sha256` ≈ 7 (retention-log digest rows, Finding-A test, golden-set
digests), `hashlib` ≈ 2, `subprocess` 0, `migrate` 0, `recovery` 0,
`protection` 0.

## 6. Measurable proofs — pre-committed acceptance rules

Written before any measurement ran. All fixture names invented
(`wavegen_plugin`, project `wind-tunnel`); deterministic — no sampling, so
no underpowered branch exists; ambiguity in a golden set means the SPEC is
ambiguous and gets fixed, never the expectation loosened.

- **AR-9 (the exit-gate clause).** Fixture: a capture set across surfaces
  (ui/rest/mcp) with engineered `started_at` ages, per-capture
  `byte_length`s, one pinned mcp capture, one pinned member of project
  `wind-tunnel`, and the boundary cell (a max_bytes rule whose applicable
  rows sum exactly to the cap). Rules: mcp-source `max_age_d` 30;
  project `wind-tunnel` `max_count` 5; global `max_bytes` B — chosen so
  the three rules' selections OVERLAP on at least one capture (the
  attribution rule is exercised). SHIP = (a) dry-run `--json` removal set
  == a hand-computed golden set with each row's rule; (b) prune removes
  EXACTLY that set (root dirs gone, index rows gone, everything else
  intact); (c) every removal has a retention.log row whose `sha256`
  equals the removed manifest's recorded digest, one-to-one, count and
  content; (d) pinned captures appear nowhere; (e) RED controls: with a
  capture armed in flight, the dry run excludes it (and a
  fixture-poisoned plan including it fails the assertion); the quota
  event fires EXACTLY once crossing 0.8 of B (a second evaluation above
  0.8 publishes nothing further; dropping below and re-crossing fires
  again). KILL = any of (a)-(e) diverging.
- **AR-10 (storage guard).** Mocked free-space sampler
  (monkeypatched): (i) a count-bound start that would breach →
  `unavailable`, message prefixed `standalone_storage_reserve:`;
  (ii) a duration start with NO reservation under a configured reserve →
  refused with the unbounded-worst-case reason; (iii) a mid-run breach →
  the capture PUBLISHES with `stop_reason: "reserve"`, `byte_length`
  equal to the staged bytes at the stop, never `completed`; (iv) RED
  control: with the guard's configuration absent, the same starts
  proceed (inert-by-default is the parameterised posture, pinned).
  KILL = a reserve breach publishing `completed`, a silent discard
  (byte_length 0 with staged > 0), or any bare-prose refusal.
- **AR-11 (NFR-O1).** A capture in flight, lifespan exit: every event
  directory is published (manifest present) or removed; no `*.tmp`
  primaries; index consistent with the root; the outcome recorded. A
  hostile adapter that ignores the stop: the close-down completes within
  the stop timeout + margin (the B-F5 escape fires; the process exits).
  KILL = any half state, or the settle hanging past the escape window.
- **AR-12 (Finding A, RED).** Reload dispatched while a capture is in
  flight → `conflict`, the capture unaffected; the same reload after the
  capture settles proceeds. KILL/RED = any reload path that proceeds
  while `self._capture` is armed (this test is red on the branch today).
- **AR-13 (Finding B, RED).** An HTML-route dispatch records
  `surface: "ui"` in the metadata sidecar (a REST dispatch still "rest",
  MCP "mcp"). KILL = any HTML dispatch recording null.
- **AR-14 (sweep).** Three directories in a root: one crash-left orphan
  (no manifest, mtime old), one fresh orphan (no manifest, mtime now),
  one published capture. Sweep: removes exactly the old orphan (with its
  log row, `sha256: null`), keeps the fresh one (grace), never touches
  the published one. KILL = a manifest-bearing directory ever removed by
  the sweep, or a fresh orphan swept.

## 7. Top risks (each with its falsifier)

1. **The prune-vs-host lock UX** — CLI prune is refused while `serve`
   holds the root (by design, one writer). Falsifier of the design: if the
   exit gate is read to require concurrent prune, it does not — the
   clause is "dry run and prune match configured rules", both satisfiable
   sequentially; the schedule covers the running host. The refusal is
   the library's existing surface, surfaced with exit 2 and help text.
2. **max_bytes boundary semantics** — pinned to the smallest-fitting-
   newest-prefix definition (§1.1); the golden set's boundary cell
   (sum == cap → kept) is the falsifier that the implementation and the
   hand-computation agree.
3. **mtime grace vs a root moved between hosts** — mtimes re-base on
   copy; a moved root's fresh-but-old-stamped orphans could sweep early.
   Disclosed in the sweep's docstring and here; single-bench roots (the
   standalone host's model) do not move mid-grace in practice. Falsifier
   for the risk's materiality: none available without multi-host roots —
   which the one-writer lock already precludes for live use.
4. **The watcher edit touches the locked terminal table** — `"reserve"`
   joins the host-initiated family without rewriting the mapping; the
   fold-refined reason rules (B-F2's ok-after-forced) extend by
   membership. Falsifier: AR-10(iii) plus the existing lifecycle suite
   staying green (the table's every existing arm re-runs).
5. **The scheduler's library construction arms the lock for a
   capture-less host** — `serve --retention-rules` with rules takes the
   root lock at first evaluation even with zero captures. This is
   correct (the scheduler IS a writer) but changes observable behavior:
   a second `serve` over the same root now refuses where before it only
   refused on first capture op. Disclosed; the lock was always
   one-per-root by design.
6. **Windows** — CI-corroborated only (W1); POSIX direct tests + the CI
   lane. No local Windows claims.

## 8. Maintainer forks (parameters this design carries, not assumes)

- **F-3/Q13 (retention defaults)** — UNRESOLVED and deliberately not
  assumed: the engine ships keep-everything; the ruled default rules
  document (the record's recommendation: ui/rest kept until deleted, mcp
  30 days unpinned, 80% quota warning) lands as a DOCUMENT the day the
  PRD rules it — no code change. The I3 exit gate needs Q5/Q7/Q13 ruled;
  that gap is the owner's, unchanged by this slice.
- **Reserve default** — no default is shipped (A02). If the owner wants a
  shipped default reserve, that is a ruled constant in the same document,
  not a host hardcoded value.
- **The device filter's no-index-column choice** (§1.5) — if the owner
  prefers a device column in the index, that widens `_COLUMNS` (I3b's
  landed schema) and is a small follow-up; this slice reads the file.

## 9. Increment plan and deferrals

Commits on this branch (each RED-first where a proving test exists):

1. This design record.
2. `retention.py` (loader/evaluator/recorder/sweep) + CLI `prune` +
   AR-9 + AR-14.
3. Finding A + Finding B fixes (AR-12, AR-13) — one line each plus tests,
   kept as their own commit so the I3b fold lanes can cherry-pick or
   confirm independently.
4. Storage guard (AR-10).
5. Close-down + scheduler + quota event + stdio settle (AR-11).
6. Library UI + user_guide/README obligation rows + full battery +
   tripwire verification.

Deferrals (each with its home): Q13 ruled defaults (PRD ruling → a rules
document, F-3); `tag` as a rule match key (SW-55's "source tag" ambiguity
resolved to `source`+`project` per the record's own AR-9 wording — a tag
key is a future row if the owner reads SW-55 the other way); archival
tier (out of PRD scope, named by the I3 record); report-export pinning
(SW-56's second sentence rides Q7's export, I4); a `device` index column
(§8); UI live-reaction to `retention_pruned` events (the event rides the
bus; page reaction is a follow-up row).

## 10. Verdict

BUILD. Every seam exists and names this slice: `await_capture`'s
docstring reserves the close-down consumer, web.py:113-116 reserves the
settle, FOLD-8 and the I3a addendum reserve the sweep, ruling 9 reserves
the recorder, and the record's §1 I3c row + AR-9/10/11 define the
mechanism and proof. The two design-time findings (§1.4) are defects in
the landed I3b state this slice fixes RED-first — flagged to the fold
lanes for independent confirmation. No standards bytes, no new
dependency, no catalogue motion.
