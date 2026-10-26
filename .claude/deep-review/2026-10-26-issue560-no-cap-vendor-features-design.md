# Issue #560 — no cap on vendor features: the layout grammar's cardinality bounds go

Gateway issue [#560](https://github.com/madeinoz67/benchweave/issues/560), label `sdk`.
Design record, 2026-10-26. Status: complete design, build in flight on the gateway lane
(see §10 — this record endorses the in-flight motion and names three folds).

Owner directive (binding, overrides the issue's two options where they conflict):
**"there should be no cap/limit on vendor features."** The outcome is structural — a
device with an arbitrary number of real vendor features derives — not a bigger magic
number.

## 0. Design-time tier call (#254)

**Tier 3**, by three independent Step-1 rules (`docs/internal/review-rubric.md:30-45`):
the diff touches `standards/` (corpus + both manifests), touches JSON Schema files, and
advances the `packages/sdk` submodule pointer. The standards-governor mandate applies
regardless of tier (rubric :91-95).

**Step-1 keyword scan over the expected diff text** (both repos' expected diffs, docs and
code alike, per the #254 rule — counts are estimates over the diff as specified in §9,
to be re-run over the real diff at review):

| Keyword | Expected count | Source |
|---|---|---|
| `sha256` | ≈ 28 | 12 corpus-manifest rows + 12 SDK lock rows (digests), plus test asserts |
| `migrate` | 1 | `tests/test_migrate_ui.py` family-literal sweep |
| `threading` / `asyncio` / `subprocess` / `hashlib` / `recovery` / `protection` | 0 | nothing in the expected diff |

Tier 3 stands on the path rules alone; the keyword rule (`sha256`) agrees.

## 1. The reproduced refusal (captured on origin/main this session)

Environment: SDK worktree `.wt/issue560-layout-7f3c` at `80e8315` = `origin/main` =
**v0.22.0**, vendored family **0.5.0** active (`standards-lock.json` row verified).
Reproduction: an ad-hoc scratch script (outside both repos, not retained) driving the
real `derive_ui` path over the acceptance fixture
`tests/fixtures/classref/descriptor-m400.json` (invented names) extended with a
digest-pinned synthetic vendor catalog (`org.example.corvus`, layer 1), N operations × 3
numeric fields each, contracts pin beside the descriptor.

The overflowing array is the **`children` array of the `device-features-section`** — the
MAIN derived section of the device-features page (`src/benchweave_sdk/classref.py:4068-4076`).
Each L2 vendor operation contributes F staging rows (`_staging_nodes`, :3939) plus one
button row (:4010-4014): one row per field, one row per button — the issue's census.

Boundary walk (deterministic, three fields per op, m400 base contributes `burst_mode`'s
2 rows to the same section):

| Ops added | children in `device-features-section` | Result |
|---|---|---|
| 3 | 14 | DERIVED CLEAN |
| 4 | 18 | REFUSED |
| 5 | 22 | REFUSED |
| 6 | 26 | REFUSED |

Verbatim refusal (N=4; the issue's own 25-row report is the same message shape):

```
classref_layout_invalid: the expander's derived block violates the family schema:
[{'binding_id': 'burst_mode', 'kind': 'numeric', 'field': 'burst_count'}, …
{'binding_id': 'op_4', 'kind': 'numeric', 'field': 'value_3'},
{'binding_id': 'op_4', 'kind': 'button'}] is too long
```

Parsed array: exactly 18 entries — 13 `numeric` + 5 `button`. The message is jsonschema's
`maxItems` failure text; the raising site is the expander's internal-consistency arm H2
(`classref.py:4129-4140`), which validates the emitted block against the vendored
`layout.schema.json` — the block's only validation authority (`classref.py:211-214`).
The binding constraint is `layout.schema.json` line 95:
`$defs.section.properties.children.maxItems = 16` (0.5.0 tree,
`src/benchweave_sdk/standards/plugin-ui-class-reference/0.5.0/layout.schema.json`).

The CUSTOM section (`{page_id}-custom`, `classref.py:4084-4090`) is a second, independent
16-capped `children` array — an uncatalogued (custom-resolution) vendor surface overflows
there instead. Same fix covers both.

**The 0.21.0 contrast, corrected.** The issue says 0.21.0 "wrote no layouts block". Not
quite: v0.21.0's `_build_layout` also emitted the block and carried the same H2 validation
arm (verified: `git show v0.21.0:src/benchweave_sdk/classref.py` — the arm and the
emission site are present; my repro against a v0.21.0 source extract REFUSES the same
descriptor with a 33-entry array — pre-W8-fold staging emitted more rows per op). What
0.22.0 added is the composed-member injection — `_inject_composed_members`
(`classref.py:2242`) does not exist in v0.21.0 — which now derives controls for
member/vendor surfaces onto the device-features page. The evidence device's features went
from "not derived, therefore under the cap" to "derived, therefore 25 rows". The defect is
the cap (present since the founding design's "≤64 nodes per page" aspiration,
`.claude/deep-review/2026-10-14-classref-logic-analyser-design.md:448`), newly REACHED by
real devices because #556 derives more real features. Reverting the emission would
un-derive real features — the wrong fix. The cap goes.

## 2. The full cap census

Every ceiling a large vendor-features surface can hit, in the order the derivation meets
them. "Goes" = removed by this bump; "stays" = remains, with the reason.

### 2.1 The layout grammar (layout.schema.json, 0.5.0 file)

| Bound | file:line (0.5.0 schema) | Fate |
|---|---|---|
| `pages.maxItems 16` | :19 | **Goes** (recommended; §5.2) |
| `sections.maxItems 16` (per page) | :54 | **Goes** (recommended; §5.2) |
| `children.maxItems 16` — section | :95 | **Goes** — the refusal |
| `children.maxItems 16` — nested_section | :155 | **Goes** (same motion) |
| `children.maxItems 16` — deep_section | :215 | **Goes** (same motion) |
| `plot_index.maximum 15` | :315 | Stays — a page's plot placement count, a data shape, not a vendor-feature entry |
| text `maxLength 512`, span ≤12, id/title ≤256 | :27-36, :87-91 | Stay — per-node shape bounds, not cardinality |
| Description prose declaring the bounds | :5 | **Moves** (rewritten prose) |

### 2.2 The declaration schemas (same family, same bump)

| Bound | file:line | Fate |
|---|---|---|
| `members.maxItems 64` | `composed-member-declaration.schema.json:27` | **Goes** (recommended; §5.2) — a member IS a vendor feature surface unit |
| `claims.maxItems 64` (member) | `composed-member-declaration.schema.json:98` | **Goes** (recommended) |
| `host_supplied.maxItems 16` (member) | `composed-member-declaration.schema.json:115` | **Goes** (recommended) — an entry ceiling on one feature's fields |
| `claims.maxItems 64` (composed action class) | `composed-action-class.schema.json` (`properties.claims`) | **Goes** (recommended) |
| `host_supplied.maxItems 16` (reference `$defs.slot`) | `class-reference.schema.json` `$defs.slot.oneOf[1]` | **Goes** (recommended) — mirror symmetry with the declaration |

### 2.3 Corpus-authoring bounds (stay; not vendor-entry ceilings)

`class-reference.schema.json`: `slots.maxProperties 64`, `pages.maxItems 64`,
`layouts.maxItems 16`, `cannot_derive.maxItems 64`, `expect.components.maxProperties 64`,
`expect.controls.maxProperties 256`, `forbid.maxItems 64`, `component_expect.attribute.maxProperties 16`,
`must_not_be_wrapped_by.maxItems 16`. These bound what WE author in class documents; the
derived deviation ledger is deliberately ungoverned ("No schema governs this document's
key set", `classref.py:4509-4511`), and member slots inject into the in-memory merged
reference, never into a corpus document. They stay. Named residual: `layouts.maxItems 16`
(authored layout pages per class) sits oddly beside `pages.maxItems 64` — pre-existing
tension, not this slice's.

### 2.4 Data-shape ceilings adjacent but out of scope (stay; censused honestly)

- `_LANE_CEILING = 64` (`classref.py:39`) — digital lanes per plot; refuses
  `classref_lane_ceiling` (`classref.py:2233-2236`); page-join drop-and-disclose at 64
  (`classref.py:3376-3381`, REPORT at :3691). Anchored to the **plugin-ui** family's
  `ui-manifest.schema.json` `$defs.plot` (a different standard), pinned equal by
  `test_scope_b1_the_series_ceiling_matches_the_manifest_schema`
  (`tests/test_classref_acceptance.py:1177-1211`).
- `_PLOT_SERIES_CEILING = 16` (`classref.py:46`) — analog plot y-series, same anchor.
- `plot_index ≤ 15` — per-page plot count (§2.1).

A vendor device with >64 digital channels still refuses `classref_lane_ceiling`
(`tests/test_classref_expand.py:110-112`). Channels and series are PLOT DATA shapes, not
vendor-feature entries; the directive's letter does not reach them. Flagged for the
maintainer: if "no cap" is meant to reach channel counts, that is a plugin-ui-family bump
and a separate train.

### 2.5 Gate, renderer, preview, console — no cardinality caps exist

- The SDK gate census (`classref_gate.py:155-180`) counts §E.1 components from served
  HTML; `_assert_expect` (:218-316) compares against the class documents' `expect` rows —
  count-exactness per named surface, no node ceiling. The daq class's rows are
  capture-scoped (`button … per_page capture`, `{n_run_actions}`) — vendor extras on
  device-features are invisible to them; `mode-banner per_page '*'` counts one per page
  regardless of children; `panel {n_pages}` counts pages. Verified shape, not assumption.
- The renderer composes per node in a loop — `web.py:_layout_region` (:454-569) and
  `presentation.py:_layout_sections` (:393-405) — no count limits anywhere.
- The gateway read-time validator `validate_layout_block`
  (`src/benchweave/presentation/classref.py:2655-2671`) and its caller
  `_layout_invalid_finding` (`src/benchweave/interfaces/ui_presentation.py:456-472`)
  enforce the same schema bytes from the canonical corpus — they widen in lockstep with
  the bump, no code change needed.
- The declared "per-page node ceiling of 64 … gate-time census" (0.5.0 README normative
  section; schema description :5) has **no mechanical implementation** — searched SDK and
  gateway src+tests: no literal 64 node census exists. It is the founding design's stated
  bound expressed through the expect machinery. The prose moves; nothing else does.
- Practical size bounds that remain (transport/asset, not entry ceilings):
  `MAX_REQUEST_BYTES = 64 KiB` (`security.py:34`), `TRANSFER_CEILING 64 KiB`
  (`session.py:162`), `read_file` 16/64 MiB caps (`presentation.py:543,1257`),
  `PREVIEW_OVERRIDE_MAX_BYTES` (`assets.py:50`). These cap BYTES on the wire, not entries.

### 2.6 Residual that is NOT a cap (named so it is not "discovered later")

The pooled expect arm (`classref_gate.py:298-315`): a class row with no `per_page` (e.g.
daq's `data-table count 1`) sums across ALL pages. A vendor action that derives an L3
data-table on device-features would trip `classref_gate_excess` — a census-exactness
property, not an entry ceiling (it reds equally at 2 tables under 16 children). The
evidence shape is L1/L2 (no data-tables); the acceptance fixtures use L1/L2 ops. Recorded
as the known trigger condition, out of this slice.

## 3. Root cause

The layout grammar's per-array `maxItems 16` (three depths) was the founding design's
bound ("bounded: ≤64 nodes per page, depth ≤3", 2026-10-14 record :448), implemented as
16-per-array in 0.1.0 and re-stamped unchanged through 0.5.0. It was never reachable by a
real device until #556's composed-member mechanism derived vendor member controls onto
the device-features page (SDK 0.22.0). The derivation is correct behavior — the features
are real; the bound is the defect. Secondary cause: the same 16/64 constants were copied
into the declaration schemas as `members 64 / claims 64 / host_supplied 16`, mirroring the
reference's own `slots.maxProperties 64` (0.5.0 README :437-438) — so a large vendor
surface that escapes the layout cap would refuse next at the declaration schema.

## 4. The mechanism

**One governed MINOR bump of `plugin-ui-class-reference`: 0.5.0 → 0.6.0**, copy-never-move.
The vendored/canonical schema bytes are the single authority all three validators read
(SDK derive-time H2, gateway read-time, gateway derive-mirror), so moving the bytes moves
every enforcement point in lockstep. No expander code change is required for the no-cap
outcome: the expander already emits one row per control; it merely stops being refused.

Change class under `standards/GOVERNANCE.md` :37-51: **breaking-machine-change row → MINOR
at least.** Removing cardinality bounds widens the accepted document set — the family's
own precedent prices a vocabulary widening as MINOR (0.2.0→0.3.0 plot.kind enum). PATCH
("additive machine errata … new optional field, nothing removed or retyped") does not
describe removing constraint keywords from existing arrays. Highest-class-in-batch rule:
the batch (children/pages/sections caps + declaration caps + prose) is all one widening
class → one MINOR bump, 0.6.0.

Bytes that move in 0.6.0 (all edits in the copy; 0.5.0 stays digest-frozen):

1. `layout.schema.json` — delete `maxItems` at §2.1's five cardinality sites
   (children ×3 always; pages + sections per §5.2 decision); rewrite `$id`, `title`,
   `contract_version` const, and the `description` bounds prose (the no-ceiling statement:
   cardinality is not a vocabulary bound; density is a renderer concern).
2. `composed-member-declaration.schema.json` — delete `members.maxItems`, `claims.maxItems`,
   `host_supplied.maxItems` (keep `minItems 1` where present); description prose updated.
3. `composed-action-class.schema.json` — delete `claims.maxItems`; re-stamp.
4. `class-reference.schema.json` — delete `$defs.slot` `host_supplied.maxItems`; re-stamp.
5. Eight `class-*.json` — re-stamp only (the `contract_version` line; zero content change).
6. `README.md` — title; a new from-predecessor note (0.5.0 → 0.6.0, MINOR: the
   cardinality-bound removal, the owner ruling cited, what stays); the normative Bounds
   section rewritten (drop "16 sections/16 children/64 census"; state the no-entry-ceiling
   rule and the per-node shape bounds that remain); the members-64 justification prose
   (0.5.0 README :437-438) rewritten to name the lifted caps.

What the design rejects: **dense packing** (issue request 1). The grammar has no container
node — `control` is a leaf with at most one `field` (`layout.schema.json:238-267`); the
issue's premise "the layout grammar already admits field rows [one entry per action with
the fields inside]" is incorrect. Packing would require a NEW node kind (vocabulary
addition, renderer support, gate census keys) — a larger standards motion than removing
the caps, and a renderer-contract change — to solve a problem the cap removal makes
nonexistent. Density/pagination stays what it is today: a host-side rendering concern
(§7).

**No new architecture.** The precedent is the family's own bump machinery, exercised
three times (0.3.0, 0.4.0, 0.5.0 — each a copy + re-stamp + repin + served-range widen +
cross-constraints row; the 0.5.0 from-predecessor note is the exact mechanical template),
plus the OTDP 0.2.3→0.2.4 corpus-motion shape (a corpus bump alone flipping gate arms,
with frozen-predecessor verification).

## 5. Scope decisions

### 5.1 Settled (the directive's core)

The `children` caps at all three depths go. The in-flight gateway tree already does this.
Endorsed.

### 5.2 The maintainer's two scope calls (my recommendation: remove; the in-flight lane kept them)

(a) **Layout `pages ≤16` and `sections ≤16`.** The in-flight 0.6.0 description keeps them
("a vendor feature surface adds children … never pages or sections"). That rationale is
true for vendor features but false for composition: members may only place on pages the
composed reference already declares (`classref.py:747-753` refuses otherwise), but
multi-class devices CONCATENATE page templates (merged pages: 2-3 per class today, 23
total across the eight; `class-reference.schema.json` allows 64 per class) — a device
composing six classes carries ~17 pages and refuses at the same `classref_layout_invalid`
site with zero vendor features involved. Since the marginal cost is two deleted keywords
inside the same bumped file, remove them: a grammar that admits 10,000 children but 16
pages is a relocated cap, not a removed one.

(b) **The declaration caps (`members 64`, `claims 64`, `host_supplied 16` ×2, class
`claims 64`).** These are entry ceilings on the vendor-features surface in the
directive's own terms — a 65-member device refuses at the declaration schema after the
layout fix lands, exactly the "later refusal" this design is required to preclude. Remove
in the same bump (one bump per standard per train; same widening class). The 0.5.0
README's justification (members mirror `slots.maxProperties 64`) inverts when the cap
goes; the prose moves with it.

If the owner prefers the narrow scope, the train lands without (a)/(b) and each becomes a
named follow-up refusal — but then the directive is only partially delivered, and this
record says so plainly.

## 6. Invariant and cross-surface impact

Invariants (`docs/internal/invariants.md`): **no new invariant, no amendment.** The
existing machinery governs the motion end to end — CON-7 (rows move only through repin),
CON-8 (corpus identity block), CON-11 (reports — N/A: plugin-ui-class-reference has no
validation-report suite; its check lane is
`tests/architecture/test_plugin_ui_class_reference_contracts.py`), CON-12 (matrix a pure
function of committed state), CON-13 (website stamps), R-2/CON-10 amendment (multi-version
serving: 0.5.0 stays retained and served; the pin lattice resolves consumers
digest-verified). The no-cap property itself is pinned three ways that do not depend on
AI judgement (A04-compatible): the schema bytes (re-adding a cap is a visible breaking
corpus change under governor review), the RED→GREEN tests (§8), and the README normative
prose. No CTL/STO invariant is touched — this is presentation/standards surface only.

Obligations (`docs/internal/drift-and-obligations.md`, by number): 6 (corpus bytes →
corpus-manifest rows + `make check-sdk-standards` green), 7 (the sdk pointer: gitlink +
`.gitmodules` pin in the SAME commit; `sdk-drift` lane), 12 (ui-html renderer surface:
`packages/ui-html/src/benchweave_ui_html/classref.py` corpus-path literals move; drift
guards re-render; no renderer change), 13 (N/A above), 18 (the version-bearing-surface
inventory — the sweep), 20 (executable-version-literal zero gate), 21 (the carried set:
lock rows + served range), 30 (device-class table reads the ACTIVE family).

The version-literal sweep (in-arc, same PR; discriminating FAMILY literals from
coincidental version strings — `tests/test_cli_doctor.py`'s `0.5.0`s are SDK-version test
data and DO NOT move):

- Gateway: `standards/corpus-manifest.json` (+12 rows, `source` = the 0.5.0 paths),
  `standards/standards-manifest.json` (active row, normative paths, `supersedes 0.5.0`,
  released date; `sdk_compatibility` mirror at pointer time), `standards/cross-constraints.json`
  (+1 row naming 0.6.0), `docs/compatibility-matrix.md` (derived re-render),
  `src/benchweave/presentation/classref.py` (`FOUNDING_FAMILY_VERSION` + docstring),
  `tests/architecture/test_plugin_ui_class_reference_contracts.py`, 
  `tests/presentation/test_classref_derive.py` + the `fixture-*-manifest.json`
  layout-block `contract_version` re-stamps, `tests/unit/test_check_sdk_submodule_drift.py`,
  `tests/interfaces_ui/test_ui_presentation.py`, the eight `tests/ui_html/test_classref_*.py`,
  `packages/ui-html/src/benchweave_ui_html/classref.py` (corpus paths),
  `scripts/standards/count_version_literals.py` (the census tool's own pins),
  `docs/internal/ui-styleguide.md`, `docs/develop-your-device.md` (active/served pair),
  website stamps, `.gitmodules` (pointer leg).
- SDK: vendored `0.6.0/` tree + `_GENERATED.txt` stamps (24), `standards-lock.json`
  (12 new rows + active markers + served range `>=0.1.0,<0.6.0` → `<0.7.0`),
  `tests/test_standards_verify.py` (the 0.6.0 train row beside 0.5.0's), the classref
  member tests' family literals, `tests/test_migrate_ui.py`, `classref.py` comment
  references; `scaffold.py`/`test_cli_doctor.py` literals are SDK-version data and stay.

Renderer honesty (the brief's direct question): with the caps gone, a 300-child section
renders 300 controls stacked in one span-12 panel — the host CSS-grid wraps rows and the
page grows long. Nothing breaks; nothing paginates (the grammar has no paging
vocabulary, and none is needed for no-cap). Density, grouping and pagination are host
rendering concerns and can be adopted later WITHOUT standards motion (a grouped node
kind would be motion; a denser grid is not). The gate renders and censuses at any count
(in-process; response size grows with the page; the 64 KiB REQUEST cap does not gate
served pages).

## 7. What breaks if a section grows without bound — answered

Nothing structural: validators are O(n) over arrays; the renderer loops per node; the
gate censuses per component. The costs are (i) long pages (UX, host's to solve), (ii)
proportionally larger manifests/ledgers (byte-level asset limits apply, §2.5 — a
practical bound in the hundreds-of-KB range, reached only by absurd surfaces), (iii) the
loss of a schema-rejectable "obviously broken" oversized block — accepted by the owner's
directive, with the digest-pinned admission path unchanged (a hostile block must still be
admitted by the operator who pinned it).

## 8. Measurable proof — PRE-COMMITTED acceptance rule

Written before any after-measurement runs. All derivations are deterministic (byte-stable
by project property), so the "sample" is the fixture set, not a variance study: the
pinned N=25 evidence-scale fixture, the N=100 scale arm, the N∈{3,4} boundary pair, the
6-class composition arm, the 65-member declaration arm, one ablation, one permutation.

**RED (already captured, §1):** on v0.22.0/0.5.0, N=4 (18 children) refuses with the
verbatim `classref_layout_invalid` message; N=3 (14) derives. The issue's own corpus: 25
rows, same site.

**Ship rule — the after-measurement must show ALL of:**
1. N=25 fixture (evidence scale): `derive-ui` exits 0; the device-features main section
   carries exactly the computed children (numeric + button rows, count stated by the
   test, not `>16`); the layout block validates against the active family schema;
   `verify-ui` exits 0 ("Rendered gate clean"); the rendered device-features page's
   census contains every op's button and every field's staged control id.
2. Scale arm N=100 (≈402 children): derives and verifies green. This arm exists to trip
   ANY count-bound downstream the census missed — it is the non-gameable control.
3. Composition arm: a six-profile descriptor derives; the layout block carries >16 pages.
4. Declaration arm (scope §5.2b accepted): a 65-member declaration validates and derives.
5. Ablation: with ONLY the vendored layout schema reverted to 0.5.0 bytes in a scratch
   tree (code untouched), the N=25 fixture REFUSES again — the schema bytes are the
   binding agent, not an accidental code path.
6. Permutation: the fixture's op order shuffled; the derived children multiset and count
   are identical (sorted-by-urn derivation — the count cannot be gamed by ordering).

**Kill directions:** (K1) N=25 still refuses any `classref_*` after the 0.6.0 bytes are
active → the mechanism is wrong or a cap was missed; fix in-train or kill. (K2) `verify-ui`
reds on N=25 (a gate census refuses the vendor extras) → a downstream count-exactness arm
bit (§2.6 shape); fix the expect scoping in-train or kill — a green derive alone does NOT
ship this. (K3) N=100 refuses or the render path degrades (a byte/size limit trips) →
record the discovered practical bound honestly and surface to the maintainer; do not
silently lower N.
**Underpowered clause:** if the ablation (5) still derives N=25 — the schema was never the
binding agent — the measurement proves nothing; halt and re-derive the root cause before
any further claim.

## 9. Slice plan — ONE train, no deferrals

G-5 pacing is SATISFIED on main as of this morning: PR #561 merged 2026-10-26T01:02Z
(merge `bfc5e197`); main carries canonical 0.5.0 and the SDK pointer at v0.22.0
(gitlink `0d4b44d`, pin `v0.22.0`), so a tree whose lock carries the predecessor exists —
the 0.6.0 commit may arrive on main now. (The dispatch brief's "PR #561 is OPEN" premise
was true at dispatch and is stale; this design states the current ordering.)

Landing order (the #556/#561 shape, inverted only in that the corpus motion is ours):

1. **Gateway leg A — the corpus motion.** Branch off `origin/main`: the 0.6.0 tree
   (§4), README, corpus-manifest rows (repin only), standards-manifest, cross-constraints
   row, the in-arc sweep (§6), the gateway RED→GREEN tests (the >16-children derive arm,
   the composition arm, the declaration arm, the fixture re-stamps). FAST lane at every
   commit; full battery + both standards tripwires + `benchweave.standards check` +
   `matrix --check` before push; standards-governor review; PR open with the design
   record attached. May merge on its own gates (G-5 satisfied) — but see leg C ordering.
2. **SDK leg B — vendored sync + the RED proof.** Branch off SDK `origin/main`
   (`80e8315`): export the bundle from the leg-A branch, sync into the vendored tree,
   lock rows + served range `<0.7.0`, stamps, SDK in-arc tests, the pinned synthetic
   fixtures (invented names) with RED evidence in the commit message (the §1 capture is
   the template), the scale/permutation/ablation arms. SDK PR opened IMMEDIATELY
   (stacked base if another SDK branch is in flight), own CI, full battery.
3. **SDK release cut** — `make release-cut VERSION=0.23.0` (MINOR: the served set grows;
   one SDK version never covers two served sets, #166), release-review matrix walk.
4. **Gateway leg C — pointer + pin.** Gitlink to v0.23.0 and `.gitmodules` pin in the
   SAME commit, `sdk_compatibility` mirror + matrix re-render + website stamps;
   `sdk-drift` lane green. Either its own PR stacked on leg A, or folded into leg A's PR
   if the SDK release is cut before leg A merges (the #561 one-PR shape). Per #408:
   SDK PRs merge → release cut → the pointer PR. 
5. Merge bottom-up, full rollup reads zero fail zero pending (`scripts/merge-verified.sh`),
   fold worktrees, close #560 after the LAST merge in either repo, and re-derive the
   evidence descriptor on the released SDK as the field after-proof.

Release implications: SDK **v0.23.0** (MINOR). ui-html: tree changes ride the gateway PR;
**no ui-html release is implied** (no renderer change). Nothing in this train is
structurally unlandable; the only open calls are §5.2(a)/(b), which are scope decisions,
not blockers — and if the owner takes the narrow scope the train still lands complete
with the residual named.

## 10. The in-flight gateway lane (endorsement + folds)

The gateway worktree `BenchWeave/.wt/issue560-gw-4b81` (uncommitted, on main) already
carries: the 0.6.0 tree with the three `children` caps removed and the description
rewritten, the manifest rows, `FOUNDING_FAMILY_VERSION = "0.6.0"`, and test sweeps.
**Endorsed** — the mechanism matches this design. Three folds before it can merge:

- **F1 (required):** the 0.6.0 `README.md` is still the unedited 0.5.0 copy (title,
  no from-predecessor note, stale normative Bounds). §4 item 6.
- **F2 (the §5.2 calls):** pages/sections caps and the declaration caps are currently
  KEPT; this record recommends removal. Maintainer's word decides; either way the record
  and the README must agree with the bytes.
- **F3 (required):** corpus-manifest rows must carry the `source` edges and move only
  through `benchweave.standards repin` (CON-7), with the frozen-predecessor verification
  (the 0.5.0 rows untouched) stated in the PR.

## 11. Risks, ranked (each with its RED-provable guard)

1. **A downstream count bound the census missed** (some 16/64 in render/gate/console).
   Guard: acceptance arm 2 (N=100) — any cardinality bound anywhere in the path trips it;
   RED-visible as a typed refusal or render failure.
2. **Scope under-delivery** — the declaration caps (or pages cap) left in place turn this
   fix into the next refusal (65 members; 6-class compose). Guard: arms 3 and 4; the
   refusal reproduces today on main and is pinned RED.
3. **Twin drift, pre-existing and named, not fixed here:** the gateway's derive mirror
   `_build_layout` (`src/benchweave/presentation/classref.py:1457-1593`) lacks the SDK's
   H2 self-validation arm (the gateway validates one call later, read-time,
   `ui_presentation.py:469`). Not a cap; the bump moves both validators regardless.
   Falsifier: the gateway read-time test with a 25-child block (`test_ui_presentation.py`
   gains the arm) — passes after the bump, reds on 0.5.0 corpus.
4. **Unbounded-array abuse** (a hostile million-child block): admission is digest-pinned
   and operator-chosen; byte-level limits (§2.5) bound the wire. Residual accepted and
   named. Falsifier: none needed — no safety claim is made; this is presentation.
5. **Bump-train collision** (another train bumps this family first): re-copy from the new
   predecessor, never stack (GOVERNANCE bump minimization). Guard: the pre-flight
   fetch/branch check at leg A branch-cut (CLAUDE.md §3.6).

## 12. Sources read this session (all claims grounded)

SDK worktree `80e8315` (= origin/main = v0.22.0): `classref.py` (:39-87, :211-261,
:3951-4198, :4433-4521, :735-789, :2162-2242), `classref_gate.py` (:150-320),
`classref_gate_render.py`, `served.py`, `standards_sync.py`, `validation.py` (site only),
`benchweave_sdk_server/web.py` (:440-569), `.../presentation.py` (:393-405), the 0.5.0
family schemas (all bounds enumerated), v0.21.0 source extract (emission + H2 verified),
`tests/fixtures/classref/*`, the classref test modules cited. Gateway `origin/main`
(255a6a6d → 493e6612 post-fetch, #561 MERGED): `GOVERNANCE.md`, `invariants.md`,
`review-rubric.md`, `drift-and-obligations.md`, `smart-test-gateway-decisions.md`
(A02/A04/A06/A12/A13), the 0.4.0/0.5.0 canonical READMEs, `presentation/classref.py`
(:1457-1593, :2655-2671), `interfaces/ui_presentation.py` (:390-472),
`tests/ui_html/classref_census.py`, the manifest/cross-constraints trees, PR #561 state.
Gortex graph access was unavailable this session (checkout discovery pending); every read
above is a native tool read. MuninnDB was down (socket errors); no memory was read or
written.
