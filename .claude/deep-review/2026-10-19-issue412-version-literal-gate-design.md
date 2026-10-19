# Issue #412 — the SDK prose version-literal census (design record)

Date: 2026-10-19. Tree measured: gateway `origin/main` at `b905b19a`, submodule
pin `9e0449e` (the v0.16.0 phase-2 registration commit). All file:line cites
below are at that state.

**Verdict: BUILD** — as a **scope-and-register widening of the existing
`count_version_literals` family in the SDK twin**, not a new gate, and **not
tree-wide**. The one-sentence mechanism: the SDK twin
(`packages/sdk/scripts/count_version_literals.py`) gains a second scan class —
a prose scan over the SDK's release-managed prose surfaces (`website/**`,
`README.md`, `index.qmd`, `user_guide/**/*.qmd`) using the gateway docs scope's
committed prose matcher, gated by per-file site-count pins plus a pinned
scanned-file census, with the `website/index.html` expectation **derived** from
`great-docs.yml`'s versions map so a clean release train never reddens.

## 0. What this record corrects in the issue's own scope claim

The issue says "the web/docs surface has no literal gate at all". Measured,
that is true for **the SDK repository only**. The gateway's `website/` tree has
carried a zero-literal ban since issue #188 (invariants CON-13):
`tests/contract/test_website_stamps.py:122` `test_source_carries_no_version_literals`
refuses any three-component literal anywhere under `website/` plus `index.qmd`
(the class-11 source set, fold F2), and it runs in the gateway `ci.yml` `gates`
job's full unmarked suite. Verified by planting the issue's own shape 1 in a
gateway worktree: the test fails naming `website/upgrade-guide.html:3:0.7.1`.
Both of the issue's proven shapes reproduce **only** against the SDK repo —
which is also the only reading consistent with the issue's own evidence ("the
registered `website/index.html`" is registered by `DECLARED_SURFACES` in the
SDK's `scripts/release_cut.py`; `--verify` is that script's mode; "cut exit 0"
is `make release-cut`, an SDK-repo target). This design therefore targets the
SDK prose surface; the gateway website needs nothing and gets nothing.

## 1. Root cause, traced and verified

The defect is a file-set hole in the version-literal census family plus a
registered-patterns-only release validator:

1. **The SDK twin's scan set stops at code trees.**
   `packages/sdk/scripts/count_version_literals.py:445` `SOURCE_ROOTS` is
   exactly `(src/benchweave_sdk, src/benchweave_sdk_server)`; its own
   denominator block (docstring, "DENOMINATOR BOUNDARY") declares
   `website/`, `README.md` and the rest outside. Verified: with both issue
   shapes planted, the bare run exits 0 — `sdk executable version literals: 0
   outside register (7 sites, 48 files scanned ...)` — the plants are in files
   it never opens.
2. **Release-cut validates registered occurrences only.**
   `packages/sdk/scripts/release_cut.py:88` `DECLARED_SURFACES` enumerates the
   version-bearing surfaces the transaction owns; its `substitution` patterns
   are five literal shapes (`version = "{v}"` in pyproject/uv.lock, the README
   `SDK {v}, OTDP` stamp, the website `</span> SDK {v} ·` hero and
   `Compatibility: SDK {v} against` tagline, the lock anchor).
   `validate_occurrences` (`release_cut.py:275`) checks exactly those patterns;
   `apply_substitutions` (`:297`) rewrites them. A file not in the enumeration,
   or a sentence matching no pattern, is invisible by construction. Verified:
   with both plants present, `release-cut --verify`'s failure list (run in a
   tree whose environmental preconditions fail) never names either plant — its
   checks are the pattern counts, the lock anchor, and the staged phase-2
   patch, nothing else. In a properly staged release-PR tree every one of those
   passes with the plants present — the issue's harness-replay finding.
3. **CI runs only the twin.** `packages/sdk/.github/workflows/ci.yml:85`
   ("Version-literal zero gate") runs the bare twin command on `push: main`
   and `pull_request` — src-only today, so the release PR is gated over a scan
   that does not open the prose files.
4. **The #408 census is a walked checklist**, not a scanner: the
   release-review matrix confirms its registered rows (README stamp, hero,
   tagline) and the test surfaces; no row enumerates what is *outside* the
   register.

So: nothing between the twin's two `SOURCE_ROOTS` and release-cut's five
patterns ever asks "does a version-shaped literal exist on the SDK prose
surface that no mechanism owns?" That is the hole this increment closes.

## 2. The measured census (my measurement, 2026-10-19, at the pin)

Applying the gateway's committed prose matcher `PATTERN_DOCS`
(`scripts/standards/count_version_literals.py:471` — the gateway docs scope's
own regex, v/V-prefixed three-component with dev/rc/alpha/beta suffixes,
anchored against dotted quads) to the SDK tree:

| Surface | Sites | Composition |
|---|---|---|
| `website/index.html` | 55 | 12 static claim sites (hero 2 at :66, vendored-standards badge row 7 at :443-449, tagline 2 at :451, one example at :428) + 43 selector/history sites (:342-363) mirroring `great-docs.yml`'s `versions:` map |
| `website/assets/*` | 0 | 3 files, clean |
| `README.md` | 4 | baseline stamp 2 at :5, `--firmware 1.0.0` example at :194, a `plugin-ui/0.3.0` doc link at :209 |
| `user_guide/plugin-sdk.qmd` | 8 | "current SDK" claim 3 at :9, pinned-descriptor examples 4 at :115, provider-contract example 1 at :127 |
| `user_guide/getting-started.qmd` | 1 | `--firmware 1.0.0` at :190 (inside an `sh` fence) |
| `index.qmd` | 1 | "OTDP 0.2.2 ... are the baseline" at :5 |
| `user_guide/` other 3 pages | 0 | clean |
| `great-docs.yml` | 71 | out of scope (release machinery; the derivation source) |
| `CHANGELOG.md` | 128 | out of scope (tool-generated history) |
| `docs/**` | 279 | out of scope (internal history records + local-untracked planning docs) |
| gateway root-level md (README, CONTRIBUTING, SECURITY, SUPPORT, CODE_OF_CONDUCT) + `index.qmd` | 0 | clean today — the gateway-side residual (deferral G1) |

**The defect class has already shipped.** Six live claims on the SDK prose
surface disagree with their machine authorities today, every gate green (mine,
against `standards-lock.json` actives and `pyproject.toml` at the pin):

1. `website/index.html:444` — registry badge `0.1.2`; lock active registry `0.1.3`
2. `website/index.html:446` — interface badge `0.1.0`; lock active interface `0.1.1`
3. `website/index.html:447` — plugin-ui badge `0.3.1`; lock active plugin-ui `0.4.0`
4. `website/index.html:449` — plugin-ui-class-reference badge `0.1.0`; lock active `0.2.0`
5. `index.qmd:5` — "OTDP 0.2.2 ... baseline"; lock active otdp `0.2.3`
6. `user_guide/plugin-sdk.qmd:9` — "The current SDK is `benchweave-sdk` 0.15.0";
   pyproject/lock `0.16.0`

The hero, tagline and README stamp stayed current because release-cut moves
them; the badge row, the landing page and the guide rotted because **no
mechanism owns them** — the exact closing clause of gateway
`docs/internal/drift-and-obligations.md` obligation 18 ("register it here with
its motion mechanism"). Note precisely: these six are **value drift**
(count-neutral in-place substitutions) — the count-pinned gate below does
*not* catch that class; it catches the issue's two **new-site** shapes. The
value-drift class is fixed editorially by rider R1 at land time and its
machine closure is deferral V1. One further observation for the maintainer:
`plugin-sdk.qmd:9`'s "registry 0.1.3" agrees with the lock — the disagreement
is between the *website badge* (0.1.2) and everything else, resolving in the
guide's favor.

A design-decisive census fact: the issue's planted value `0.7.1` **is a real
past release** (`website/index.html:352`, selector row). Any value-set
allowlist ("a literal is fine if its value is a known release or the current
pin") passes shape 2 by construction. Only **site counting** catches both
shapes; that is why the register below pins per-file site counts, not value
sets.

## 3. The mechanism

All primary changes land in the SDK repo. Exact sites:

**`packages/sdk/scripts/count_version_literals.py`** (the twin):

- A new module-level `PATTERN_DOCS`, **copied verbatim** from the gateway copy
  (`scripts/standards/count_version_literals.py:471`) with its explanatory
  comment, placed **outside** the shared counter region (the region spans
  lines 101-400 today and is byte-pinned against the gateway copy by the
  gateway parity test; see §6 for why it does not move inside the region in
  this increment, and deferral H1 for when it does). The twin's docstring
  names the gateway copy as the prose matcher's authority — the obligation-22
  shape.
- `_prose_files()` — the enumerative surface set, gateway `_docs_files()`
  (`scripts/standards/count_version_literals.py:721`) as the precedent:
  every file under `website/` (assets included — the class-11 rule), plus
  `README.md`, `index.qmd`, and every `*.qmd` under `user_guide/`. The set is
  an **enumerated allowlist of surfaces, not a tree walk**, so
  local-untracked planning trees (`docs/superpowers/`) and the excluded
  classes (`CHANGELOG.md`, `docs/**`, `great-docs.yml`,
  `pyproject.toml`/`uv.lock`/`standards-lock.json`, `template/`, `.github/`,
  `scripts/`) are outside the denominator by construction, each named in the
  docstring with its reason (the gateway DENOMINATOR BOUNDARY discipline). If
  the set is ever widened onto `docs/`, the named-exclusion constants must
  list `docs/superpowers` (gateway precedent `DOCS_EXCLUDED_DIRS`).
- `count_prose_sites()` — the per-line `PATTERN_DOCS` scan (the body is the
  gateway docs scope's scan, ported): one row per match, `{file, line,
  pattern: "PROSE", text}`.
- `PROSE_REGISTER: dict[str, tuple[str, int]]` — per-file `(reason,
  expected_sites)`, the twin's existing register semantics (`:408` REGISTER
  keeps its shape; the prose rows are a second constant, register SEMANTICS
  unchanged). Rows at land time (post-riders): `website/index.html` handled by
  derivation (below); `README.md`; `user_guide/plugin-sdk.qmd`;
  `user_guide/getting-started.qmd`; `index.qmd` — each reason naming its
  motion mechanism ("release-cut occurrence-validated substitution",
  "authored example, cross-pinned by tests/test_getting_started.py's firmware
  arm", "pinned-descriptor pedagogy", or, after R1, "versionless claim").
- **The derived expectation** for `website/index.html`: expected sites
  `= 2 * release_count + PROSE_INDEX_STATIC` where `release_count` is parsed
  from `great-docs.yml`'s `versions:` map (stdlib-only, line-anchored on
  uncommented `- tag: vX.Y.Z` rows) and `PROSE_INDEX_STATIC = 11` (12 static
  claim sites, minus 1 because the current release's selector row carries one
  occurrence where older rows carry two). At the pin: 2×22 + 11 = 55,
  matching the census exactly. Consequences, both verified against the
  release machinery's shape: a **cut** moves hero/tagline values in place —
  count-neutral, no gate motion; the **phase-2 tag patch** adds one versions
  row to `great-docs.yml` and its selector rows to the HTML — the derived
  expectation reads the new map length and still holds. A clean release train
  never reddens; `release_cut.py` is **not modified** by this increment. A
  template redesign changes the multiplicity — the gate reds loudly, the fix
  is a one-constant edit (a visible register diff).
- `main()` gains the prose leg in the **default bare invocation** (exit
  contract unchanged: 0 hold, 1 any violation or refusal; `--json` gains the
  prose rows). Violation text, the gateway message shape:
  `unregistered prose literal: <path>:<line> [PROSE] <text> — derive it,
  register it with reason and expected_sites, or update the census`.
- A pinned **scanned-file census** (the gateway snapshot's `file_count`
  discipline): the prose file-set count is a committed constant; any new or
  removed file in the surface set reds even when it carries zero literals —
  the issue's shape 1 caught *before* the plant writes a version at all.

**`packages/sdk/tests/test_zero_literal_gate.py`** — a new `TestProseScope`
class using the file's existing scratch-tree machinery (copy the twin into a
scratch repo, copy real surface files, run `sys.executable` on it via the
existing helpers): exactly **7 arms**, enumerated in §9.

**Riders (content fixes, R1)** — `website/index.html` badge row (:444, :446,
:447, :449), `index.qmd:5`, `user_guide/plugin-sdk.qmd:9`: each claim brought
into agreement with its machine authority, by either carrying the active value
or carrying no version. The wording choice (stamp the active vs reword
versionless) is the maintainer's; the design's rule is only that no
current-tense claim keeps a version no mechanism moves — for "the current SDK
is X" the versionless form is preferred precisely because nothing will move a
hand-stamped X at the next cut (risk R4).

**Docs riders (R2)** — the SDK's `docs/internal/drift-and-obligations.md`
surface-inventory row gains the prose surfaces with their motion mechanisms;
gateway `docs/internal/drift-and-obligations.md` obligation 18 gains the SDK
prose rows (the inventory already reaches cross-repo, cf. its plugin-lock row)
and obligation 22 is annotated: the prose matcher's authority is the gateway
copy; no shared-region change rode this increment; H1 schedules the fold.

**Gateway repo: no counter change in this increment.** Its docs scope already
gates `docs/`; its website is CON-13/T2-gated; its `sdk` scope question is
deferral G2.

## 4. The first increment, and what it defers

The increment (SDK repo, one PR; then a gateway docs-only PR or the same
train):

1. Twin: prose scan class + `PROSE_REGISTER` + derivation + census + bare-run
   wiring (no CI yaml change needed — the step at `ci.yml:85` already runs the
   bare command on every PR and push, which is what gates the release PR;
   standalone runs are the same command).
2. `TestProseScope` — 7 arms.
3. R1 riders (six claims; count-neutral except any versionless rewording —
   final counts pinned at land time from the built tree).
4. R2 docs riders (both repos' drift docs).
5. The design record committed before any measurement (this document).

**Deferrals** (each row: id / deferred / home / reopen trigger, per the
deferral-row contract in `.claude/deep-review/README.md`):

| id | deferred | home | reopen trigger |
|---|---|---|---|
| V1 | value pins or derived-value arms for registered prose sites (the count-neutral in-place drift class — the six measured claims' machine closure) | follow-on issue #412 (this tracker) | the next release-review walk or lock-bump arc that records a prose claim disagreeing with `standards-lock.json`'s actives — the class measured 2026-10-19 at `9e0449e` (six sites) |
| V2 | SDK-site stamp tokenisation (the CON-13 end-state for `sdk.benchweave.dev`; rejected for increment 1 because 43 of the 55 index.html sites are release-history data a zero-literal ban cannot absorb) | follow-on issue #412 | the owner's explicit call for site stamp derivation, or the first post-R1 value drift observed on the served SDK site (a walk record or site diff naming it) |
| G1 | gateway root-level md file-set widening (clean today, measured; a future claim there is the same defect class gateway-side) | follow-on issue #412 | a three-component version claim landing on a gateway root-level md surface, observed in a release-review walk or the version-surface census |
| G2 | gateway `sdk`-scope prose re-check at pointer bumps (the two-sided mirror) | follow-on issue #412 | an SDK PR observed merged with the prose leg failing or absent (a red or missing "Version-literal zero gate" step on a merged SDK PR) |
| H1 | fold `PATTERN_DOCS` into the shared counter region in both copies | documentation in this record; carrier = the next gateway pointer PR | the next SDK release cut's gateway pointer PR (the natural carrier) |
| T1 | `template/` (copier scaffold) literal coverage | follow-on issue #412 | a template edit whose rendered scaffold carries a new three-component literal reaching the byte-parity fixtures (the regen arm's diff) |

## 5. Precedent (why no new architecture)

- **The gateway docs scope (VR-24)** — a committed prose matcher over a named
  file set with exact bounds and a pinned census: the mechanism being ported,
  battery included (`TestDocsRatchet`, the IP-fragment arm). This increment is
  that scope's shape on the SDK's surfaces with register pins instead of a
  snapshot, because the SDK's literals legitimately move every release
  (below).
- **The twin's own scope-extension precedent** — issue #309 slice A grew
  `SOURCE_ROOTS` from one root to two when the server host folded in; this
  increment grows its surface class the same way, in the same file.
- **The register with teeth (#221 §1.3)** — per-file exact expectations whose
  edits are visible editorial diffs; the anti-laundering posture is inherited
  wholesale.
- **Derived expectations from committed state (#269 §2's DERIVED policy
  facts)** — the `great-docs.yml` selector-count derivation is the same class:
  the bound is computed from the file that owns the fact.
- **Register pins, not a snapshot** — the gateway's docs ratchet refuses
  growth *and* shrinkage against a JSON baseline; on the SDK surface that
  model reddens twice per cut (in-place value motion changes the per-literal
  map) and once per tag (phase-2 growth), coupling the gate into
  `release_cut.py`'s transaction and its `phase2_wrong_file_set` refusal.
  Count pins are cut-neutral and, with the derivation, tag-neutral. The
  snapshot model remains right for the gateway's docs tree, whose literals are
  claims that should not move; the SDK's are claims a machine moves.

**Why not the issue's "tree-wide" alternative:** measured tree-wide, the
allowlist would have to absorb 279 internal-history + 128 generated-changelog
literals before catching a single plant — a blanket-absorbing register, the
defect the issue itself warns against. The enumerative surface set keeps the
denominator honest.

## 6. The twin-sync obligation, answered explicitly

**This design touches scope and register rows only — not the definition
block, not register semantics.** The shared region (twin lines 101-400) is
byte-untouched; obligation 22's mechanical trigger ("a change to either
copy's definition block or register SEMANTICS re-syncs the other in the same
work") does not fire. The prose matcher is a repo-local scan class whose
authority the twin's docstring names, exactly as the row's prose-level duty
requires, and H1 folds it into the shared region at the next pointer PR.

Why not fold it now: the gateway parity test
(`tests/standards/test_zero_literal_gate.py` `TestSharedRegionParity`)
compares the gateway region against the **submodule at the gitlink**. The
gitlink tracks release tags only (the sdk-drift law), so a gateway-side
region fold landing before the next pointer PR would compare new-region
gateway bytes against old-region submodule bytes and red every gateway PR in
the window. Folding inside the pointer PR is green by construction. That
ordering constraint is measured from the workflow wiring, not assumed — and
it is why the region stays untouched in this increment. Named residual until
H1: the two `PATTERN_DOCS` copies can drift cross-repo; the pattern-pin arm
(below) pins the twin's copy to a committed literal, the gateway copy is
pinned by its own docs-scope battery, and the cross-repo identity remains the
human duty obligation 22 already carries.

**Does the SDK need the same scope as the gateway?** The widening lands
SDK-side only: the gateway copy's docs scope already covers its docs tree,
and the gateway website carries the stricter zero-literal ban. The gateway's
`sdk` scope mirror is G2.

## 7. Invariant and cross-surface impacts; CI cost

- **No CTL/STO/CON/REG text changes.** CON-13 is untouched (its subject is
  the gateway site; the SDK site's tokenisation is V2). No new invariant: the
  governing rule already exists — obligation 18's closing clause ("a new
  version-bearing literal anywhere is a defect — make it a derived surface or
  register it here with its motion mechanism; enforcement is the counting
  script's REGISTER") — and this increment makes it mechanically true for the
  SDK prose set. Obligations 18 and 22 gain amendments (R2).
- **On-disk formats/schemas: none.** The register is code; no persisted format
  changes — consistent with the Tier-2 call in §8.
- **Surfaces that move:** the twin script + its battery; three prose content
  files (R1); both repos' drift docs (R2); the SDK `ci.yml` step needs no
  change (comment-only touch optional). The MCP/REST/CLI/operator-doc/
	device-developer/vendored-standards/fixture-lattice/SDK-repo-pointer
  surfaces are untouched by this diff; the next pointer PR (H1's carrier) is a
  separate future PR and is recorded here only so its Tier-3-by-pointer-rule
  status surprises no one.
- **CI cost: negligible.** Zero new lanes; the existing SDK "Version-literal
  zero gate" step scans ~12 additional small files, stdlib-only, well under a
  second, on the three OS legs it already runs.

## 8. Review tier and the Step-1 keyword scan

- **Slice A (SDK repo): TIER 2.** First matching rule: any other change to
  production or test code under `scripts/` and `tests/` (the web-copy and
  docs files alone would be Tier 1; scripts/tests lift the slice).
- **Slice B (gateway repo, docs-only): TIER 1** (drift-doc rows + this
  record; no code).
- **Maximum across slices: Tier 2.**
- **Step-1 keyword scan (#254)** over the whole expected diff of both slices,
  docs and code alike: the eight Tier-3 keywords of
  `docs/internal/review-rubric.md` Step 1 were scanned — **8 keywords, 0
  occurrences each**. The keyword list is deliberately not reproduced in this
  record: reproducing it would carry the words into this record's own diff
  text and self-fire the text rule (the rubric's own intended behavior). Any
  nonzero occurrence would be listed here with its word and count. The
  projection assumes the new arms reuse the battery's existing runner helpers
  rather than spawning the counter through a fresh OS-process call — a
  build-time deviation that introduces the one word would flip the slice to
  Tier 3 by first match, which is acceptable and must then be re-stated in
  the PR, not hidden.
- **Standards-governor mandate (#69): required for slice A.** Rider R1's diff
  carries standard-version strings (badge values move to the lock's actives).
  The governor dispatch is a mandatory pre-merge pass; a review that never
  ran it is a skipped gate.
- **Ordering:** the gateway docs PR (R2's gateway half) lands after the SDK PR
  merges (risk R5); the SDK PR body notes the single-tracker issue per the
  standing rule.

## 9. The measurable proof — pre-committed acceptance rule

Written before any post-build number is looked at. Deterministic gate: the
"effect" is binary detection of the issue's two shapes; no sampling inference
is claimed; the power clause is the INCONCLUSIVE branch. Commands run from
the SDK repo root on a full copy of the built tree (`cp -R` the SDK checkout
to a scratch dir — the battery's existing scratch shape):

**AR-1 (detection — the issue's own repro, n = 2 shapes):**
- plant-1: create `website/upgrade-guide.html` containing the sentence
  `Requires SDK 0.7.1 or later.` → `python3 scripts/count_version_literals.py`
  exits **1** and its output names `website/upgrade-guide.html:1`;
- plant-2: add the sentence `Works with SDK 0.7.1 gateways.` inside
  `website/index.html`'s hero → exits **1** naming `website/index.html:<line>`;
- clean: both removed → exits **0**.

**AR-2 (RED control):** with ONLY the prose scan disabled (the prose leg's
invocation removed; register, census constant and everything else intact),
the two plant arms in `TestProseScope` **FAIL** (pytest exit non-zero,
collected count > 0 — `no tests ran` is a failed check); restored, they pass.
A test that passes both ways proves nothing.

**AR-3 (suite):** `uv run pytest tests/test_zero_literal_gate.py --junitxml=...`
shows the exactly-7 `TestProseScope` arms collected and passed —
1 planted-new-file, 2 planted-unpatterned-sentence, 3 clean-head-hold,
4 removed-site (shrinkage), 5 selector-derivation-tracks-the-versions-map,
6 prose-pattern-matches-the-authority-literal (mutation arm), 7
scanned-file-census-pinned. Counts read from the junitxml attributes, never a
summary line.

**AR-4 (riders):** the six named claims no longer disagree with
`standards-lock.json`'s actives or `pyproject.toml` — each carries the active
value or no version.

**SHIP iff AR-1..AR-4 all hold in one recorded run.**
**KILL if** any planted shape exits 0; or the clean tree exits 1; or AR-2's
arms pass with the mechanism disabled; or the register was established
absorbing any known-stale claim (AR-4 unmet — the blanket-absorbing register
is the failure this rule exists to prevent).
**INCONCLUSIVE (underpowered, not conclusive) if** the scratch tree failed to
carry the real file set (a surface path the counter keys on absent, or the
census arm counted a harness artifact) — the run then measured the harness,
not the gate; rebuild the copy from the full SDK tree and re-run before any
verdict.

## 10. Top risks, each with what would falsify the design

1. **Derivation fragility** — `2 × release_count + 11` breaks if the selector
   row template changes. Falsifier: the next tag commit reds on a clean-intent
   phase-2 patch. Mitigation: the violation names the derived expectation and
   its constants; the fix is a one-constant visible edit. The design is
   falsified if the multiplicity is not stable across the next release —
   measured then; arm 5 pins the current shape.
2. **Register absorption** — a count bump mutes the gate. Falsifier: a landed
   register edit raising a count without a reason naming a mechanism. Carried
   by review, the gateway register's own posture; AR-4 blocks the
   known-stale-absorption variant at land time.
3. **Cross-repo matcher drift** until H1. Falsifier: a semantic regex change
   in one copy only. Arm 6 pins the twin's copy to a committed literal; the
   residual is named (§6).
4. **Rider rot** — a hand-stamped "current SDK is 0.16.0" ages out at the
   next cut. Falsifier: the next cut leaves it stale (V1's class). Mitigation:
   R1's wording rule prefers versionless for current-tense claims.
5. **Landing order** — gateway docs rows landing before the SDK gate exists
   would promise an unenforced rule. Ordering stated in §8; a violation is a
   review finding, not a defect of the mechanism.
6. **The parity window** (§6) — a premature gateway-side region fold reds the
   parity lane fail-closed. H1 exists to prevent it; the red is the sync
   obligation working, not a gate bug.

## 11. Decisions taken (the five open questions, answered)

1. **Scope widening plus a register — not a new gate.** The family, the
   register semantics, the CI step and the battery all exist; the increment
   adds a scan class and rows to them. A standalone tree-wide counter was
   considered and rejected on the measured denominator (§5).
2. **What counts as a literal on these surfaces:** `PATTERN_DOCS`, the
   gateway docs scope's committed prose definition, verbatim — same kind of
   surface (prose claims), one definition in the family, already
   battery-pinned. The AST walk does not apply (no code to walk); site
   counting is per-line matches, and **counts, not value sets**, because the
   issue's own planted value is a real past release (§2).
3. **False-positive posture:** historical literals are absorbed by per-file
   count pins (deliberately not per-literal pins — §5's release-motion
   arithmetic); an entry is added by a `PROSE_REGISTER` or census-constant
   edit — a visible diff carrying a reason; blanket absorption is stopped by
   the count pins (a new site needs a bump), the census (a new file needs a
   bump), AR-4 (known-stale claims may not be absorbed at land time), and
   review (the residual, same as the gateway).
4. **Where it runs:** the SDK `ci.yml` `sdk` job's "Version-literal zero
   gate" step — already present at `:85`, already bare-invoked on
   `push: main` and `pull_request`, all three OS legs; the release PR is a
   `pull_request`, so it is gated with zero wiring change. Standalone: the
   same bare command.
5. **`docs/superpowers`** (local-untracked in both repos): outside the scan
   set by construction — the set enumerates surfaces, it does not walk the
   tree; any future widening onto `docs/` must add the named exclusion
   constants (gateway precedent).
