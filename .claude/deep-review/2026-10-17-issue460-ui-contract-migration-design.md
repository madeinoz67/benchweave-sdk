# L6 design — issue #460: upgrade does not migrate plugin-ui contract artifacts

**Date:** 2026-10-17
**Issue:** madeinoz67/benchweave#460 (single issue stream; SDK-side work, no SDK-side
issue by design)
**Program linkage:** classref train, `.claude/deep-review/2026-10-14-classref-logic-analyser-design.md`
§7A slot L6 / §8 row RC-7. This record is L6's own design record; the program record does
not scope it. L7 (#461, the same upgrade run's venv/symlink damage) is a sibling leg with
its own record; §5 names the adjacency.
**Verdict:** BUILD, scoped — a new `migrate-ui` command (the reporter's option 1) plus
remediation pointers at the two failure surfaces (option 3, folded in as guidance). Option
2 (upgrade performs the migration) is rejected on posture grounds; §5 carries the evidence.
The migration semantics are **re-stamp + hash repair**, not re-derivation. Design-only leg:
no implementation code in this record.

---

## 1. Pre-flight (#181 R2)

- SDK checkout `main` at `fca9c41` (v0.15.0, the L5 input trio release); `git fetch origin`
  run; working tree clean. Design worktree `.wt/l6-k3r9` off `origin/main` at `0e16d25`.
- Remote branches touching the planned paths (`src/benchweave_sdk/presentation.py`,
  `cli.py`, `scaffold_update.py`, tests, user guide): none open. The classref-surface
  branches (`feat/l5-sdk-widening`, `feat/classref-sdk-f9m4`, `feat/classref-l2-expander`)
  are the train's own landed L2–L5 lanes. Open SDK PRs #158–#165 are all dependabot/CI
  chores (setup-uv, codeql, fastmcp, artifact actions).
- Sibling gateway repo (`madeinoz67/benchweave`): open PRs #480–#487 all dependabot
  chores; the recent merges #474/#477/#478/#479 are this train's L4/L5 landings. No rival
  design or in-flight work on the upgrade/migration surface.
- GORTEX UNAVAILABLE TO SUBAGENT — the probe (`read` on a repo-prefixed path) refused
  with checkout-discovery-unavailable (issue #831 class). Native tools used throughout,
  per the dispatching brief.

## 2. Root cause (traced, not assumed)

Two structural gaps, both verified in the code:

**Gap 1 — the upgrade path and the artifact-generation path are disjoint by design.**

- The plugin-ui contract artifacts are NOT template content. `create_project`
  (`src/benchweave_sdk/scaffold.py:291-389`) renders only the copier template;
  `template/src/{{package_name}}/` carries `adapter.py`, `descriptor.json`, `protocol.py`,
  `vectors.json`, `protocol.md`, skills — no `presentation.json`, no `ui/`, no
  `binding-catalogue.json`. The docstring at `scaffold.py:309-312` is explicit: the UI
  resources are "derived from the descriptor's exact bytes by
  `presentation.create_ui_resources` after the project lands — SDK code, deliberately not
  template content." The CLI invokes it post-render (`cli.py:78-86`, `new --with-ui`).
- Even if the template carried them, the update could not write them: `copier.yml`
  declares `_skip_if_exists: [pyproject.toml, README.md, CLAUDE.md, tests/**, src/**]` —
  the entire `src/**` subtree is author-protected so the 3-way merge "could not push
  template bytes over real device code" (the globstar note in `copier.yml` is
  load-bearing, pinned by `test_skip_list_is_load_bearing_on_update`). The artifacts live
  under `src/<pkg>/`.
- `upgrade_project` (`src/benchweave_sdk/scaffold_update.py:139-251`) is `copier.run_update`
  pinned to `v{__version__}` plus two protections (skip-protected restore, conflict-marker
  report). Nothing in it reads `contract_version` or any presentation document. So when
  the lock's active plugin-ui moves between SDK releases, the template refresh completes
  green and the artifacts keep their generation-time stamps — the reporter's observation,
  exactly.

**Gap 2 — the stamps are lock-derived at generation time, and the validator is
single-version with a hash chain.**

- All three documents are stamped at generation with
  `active_version("plugin-ui")` — "derived, never stated"
  (`presentation.py:764-785`); the preview fixtures are stamped
  `active_version("plugin-ui-preview")` (`presentation.py:545`).
- The vendored validator accepts exactly one version: `_checked_document`
  (`src/benchweave_sdk/standards/plugin-ui/contracts.py:368-380`) refuses any document
  whose `contract_version` differs from the literal `"0.4.0"` with
  `unsupported_version`. The envelope gate runs first
  (`contracts.py:740`), which is why the reporter's failure surfaced as
  `preview_invalid_presentation: unsupported_version: presentation-envelope`
  (raised at `presentation.py:530-532` — the path both `check-ui` and the generated
  conformance test `tests/test_presentation_preview.py` go through).
- The envelope carries the byte hash of the manifest
  (`presentation.py:779`), enforced at `contracts.py:397` (`_resource` →
  `digest_mismatch`). A hand version bump on the manifest therefore requires recomputing
  sha256 and editing the envelope — the manual step the reporter calls "easy to do wrong."

**The version history that makes this a live defect class** (read from the release tags'
`standards-lock.json`):

| SDK | plugin-ui active | plugin-ui-preview active | plugin-ui-class-reference active |
|-----|------------------|--------------------------|----------------------------------|
| v0.10.0 | 0.3.0 | 0.2.0 | — |
| v0.11.0 – v0.14.0 | 0.3.1 | 0.2.0 | 0.1.0 (from v0.13.0) |
| v0.15.0 (current) | **0.4.0** | 0.2.0 | **0.2.0** |

The reporter's case was a patch bump (0.3.0 → 0.3.1 across v0.10.0→v0.12.0). Today the
same defect is a minor bump: any project last touched at ≤ v0.14.0 carries plugin-ui
0.3.1 against an SDK that serves 0.4.0 only, and class-conformant projects additionally
carry plugin-ui-class-reference 0.1.0 against 0.2.0.

**What the corpus says a migration means.** `standards/plugin-ui/0.4.0/MIGRATION.md`
(gateway repo, the canonical corpus this SDK syncs from) is decisive for both bumps this
design must cover: the 0.4.0 schemas are "0.3.1 byte-copies re-stamped 0.4.0 — `$id`,
`contract_version` consts and titles; the cross-schema `$ref` URLs re-stamp with them
(the 0.3.0→0.3.1 shape, verified by sorted-key diff to be version strings only)", and
"Re-stamp 0.3.1 pins to 0.4.0: the documents are 0.4.0-valid except `contract_version`
... no previously-valid 0.3.1 document becomes invalid under its own frozen schema."
So the sanctioned migration for the plugin-ui family is a **version re-stamp plus the
envelope hash repair** — no content transformation. That is precisely what this design
builds, and it is why re-derivation is NOT the semantics (re-derivation also resets
author content; see §5).

## 3. The mechanism — `benchweave-sdk migrate-ui`

A new function `migrate_ui(...)` in `src/benchweave_sdk/presentation.py` (beside
`create_ui_resources`, `check_ui`, `load_validated_preview_inputs` — the module that owns
these documents, their reads and their validator plumbing), wired as a new CLI command
`migrate-ui` in `cli.py` with **check-ui's option shape** (`envelope` argument +
`_presentation_options`: `--descriptor`, `--resources`, `--catalogue`, `--firmware`,
`--feature`, `--panel`). The manifest is located from the envelope itself
(`resource_root` + `manifest.path` under the resources root) — the same resolution
`_load_ui_candidate` (`presentation.py:378-426`) performs; no path guessing.

Algorithm, in order:

1. **Load.** Read envelope, descriptor, catalogue through `presentation.read_file`
   (bounded, symlink-refusing — the strict walk at `presentation.py:125-158`); resolve and
   read the manifest the same way; load the manifest's declared assets as
   `_load_ui_candidate` does (they ride the validation set unchanged — the migration
   never touches asset bytes).
2. **Read the stamps.** Parse each of the three documents; read each top-level
   `contract_version`. Target = `active_version("plugin-ui")` — derived from the lock,
   never a literal (the stamp rule at `presentation.py:765-768`).
3. **Case table** (first match wins):
   - any version orders ABOVE the target (tuple compare, `served._tuple`) → refuse
     `migrate_ui_ahead:` — the installed SDK cannot validate documents newer than its
     lock; remediation is installing the newer SDK. Never a downgrade write (the
     `derive_move_to` downgrade-honesty precedent, `served.py:228-280`).
   - any document unparseable, or missing a string `contract_version` → refuse
     `migrate_ui_version_absent:` naming the file.
   - all three already at the target → **no-op success**, exit 0, report
     `already at plugin-ui <target>` — idempotent by construction (§6).
   - otherwise (behind, or mixed — including the reporter's own half-hand-migrated
     intermediate state) → migrate.
4. **Compose new bytes by targeted byte substitution, not re-dump.** On each document's
   raw bytes, replace `("contract_version"\s*:\s*")<old>(")` with the target version.
   This preserves author formatting exactly (key order, spacing, trailing newline) —
   the manifest is author-editable content under a protected tree; the migration's diff
   must be the version string and nothing else. If the parsed value exists but the byte
   pattern cannot be located (exotic escaping), refuse
   `migrate_ui_stamp_unlocatable:` naming the file — never re-serialize as a fallback.
5. **Repair the hash chain.** The envelope's `manifest.sha256` becomes
   `sha256(<new manifest bytes>)` — same targeted-substitution discipline on the envelope
   bytes (old hex → new hex). This is requirement (2) of the issue, mechanized.
6. **Validate the new set IN MEMORY, before any write.** Call
   `validate_presentation` (the same vendored validator `check-ui` runs — SRF-2's one
   gate) with the NEW envelope bytes, the loaded descriptor bytes, the resources dict
   with the manifest bytes replaced, and the NEW catalogue parsed. Invalid → refuse
   `migrate_ui_invalid_after_stamp:` listing the findings — nothing written
   (all-or-nothing). The message does not claim the findings pre-date the migration; it
   says the re-stamped set does not validate and the reported findings need changes the
   re-stamp does not make (a future schema-narrowing bump would land here — correctly).
7. **Write + report.** Write only the files whose bytes changed (`write_bytes`, LF, the
   same canonical paths already read). Report per file: `migrated <relpath>:
   plugin-ui <old> -> <new>`; for the envelope when only the hash moved, additionally
   `manifest hash repaired`. Requirement (3) of the issue: the report names every changed
   file. Output closes with the review-and-commit line (the `derive-ui` posture —
   no git-state requirement on this command; disclosed residual: three sequential writes
   are not atomic, same as `derive-ui`; the author's VCS is the recovery).
8. **Classref-family advisory (detection only).** If `ui/class-reference.json` exists
   under the resources root and its `contract_version` orders below
   `active_version("plugin-ui-class-reference")`, print a yellow pointer: re-derive with
   `benchweave-sdk derive-ui --force` (author overlays survive in
   `ui/manifest.overrides.json`; `contract_version` is expander-owned/protected at
   `classref.py:1636`). The classref re-stamp itself is deferred (D2, §7); embedded
   classref-stamped extension blocks (`classref.py:1200` puts the layout block inside
   the catalogue's `extensions`) are deliberately not parsed by this slice.

Refusal prefixes (STD-4 discipline, snake_case, machine-matchable):
`migrate_ui_ahead:`, `migrate_ui_version_absent:`, `migrate_ui_stamp_unlocatable:`,
`migrate_ui_invalid_after_stamp:`. Success output is advisory prose + per-file lines.

**#461 adjacency (L7), stated per the brief.** L6 and L7 share the `upgrade` surface but
not a mechanism, and this design keeps it that way. The migration's file discovery is
envelope-driven — no project-tree walk, no `rglob`, so it cannot enter `venv/` by
construction; every read goes through the symlink-refusing `read_file`, and writes go to
the exact canonical paths those reads resolved. The upgrade staleness notice (§4) reads
at most the three named artifact paths under one package directory — again no walk. L7
owns fixing `upgrade_project`'s own `rglob` scan and conflict-marker write; the only
thing L6 borrows is the discipline. If the maintainer prefers one shared
"never walk ignored trees / never write through symlinks" helper, that belongs to L7's
record, not this slice.

## 4. The pointers (option 3, folded in as guidance)

- **`check-ui`.** When the report carries a finding with code `unsupported_version` on
  one of `presentation-envelope` / `ui-manifest` / `binding-catalogue`, the report
  renderer (`_render_report`, `cli.py:251-264`) appends one remediation line naming
  `migrate-ui` with the concrete command shape. This is where an author lands when the
  staleness came from any path (not just `upgrade`).
- **`upgrade`.** After the template refresh and the restore/conflict report, the CLI
  layer (not `upgrade_project` — its 2-tuple contract and its test suite stay pinned)
  locates the package directory the way `derive-ui` does, reads at most the three
  artifacts, and when any is behind the active prints a yellow notice:
  `plugin-ui contract artifacts at <old> (active <new>): run 'benchweave-sdk migrate-ui
  …' after committing this upgrade.` Expected read/parse failures print nothing — the
  notice is advisory, `check-ui` remains the authority (disclosed residual: a project
  whose artifacts do not parse gets no notice; its next check still refuses loudly).

## 5. Why option 1+3 and not option 2 — the recommendation, with evidence

The reporter prefers option 2 (`upgrade` does the migration) on the grounds that "the SDK
already generates `ui/manifest.json` and the fixtures at scaffold time, so the same code
can move them to the active version at upgrade time." The premise is true
(`create_ui_resources`, `presentation.py:661-827`) but the inference fails on three
grounds, each code-anchored:

1. **The "same code" is re-derivation, and re-derivation resets author content.**
   `create_ui_resources` derives the manifest from the descriptor's current bytes. The
   manifest is author-editable after scaffolding (pages, plots, assets; the UI-GUIDE
   teaches the layout and tells the author to keep hashes aligned). Running the generator
   again at upgrade time would overwrite those edits. The class-conformant path needed a
   whole overrides mechanism (`ui/manifest.overrides.json`, `compose_manifest` with
   protected fields, `classref.py:1629-1648`) precisely because generation output is not
   author-stable. Option 2 done "with the same code" is a content reset riding inside a
   template refresh.
2. **Writing into `src/**` from inside `upgrade` inverts the skip-protection posture.**
   `copier.yml` protects `src/**` so nothing but the author writes there; every existing
   SDK write into that tree (`derive-ui`) is an explicit, separately-invoked command. It
   also couples two failure domains: a project whose re-stamp must refuse (drifted
   descriptor, §7 D1) would fail its upgrade AFTER `run_update` already wrote the
   template half of the change — the exact interleaving the one-command-per-concern
   posture avoids.
3. **The failure the reporter hit is not detection-limited, it is repair-limited.**
   Option 3 alone leaves the hash repair manual — the part called "easy to do wrong."
   The minimal honest composition is: a command that repairs (option 1), plus pointers
   at both surfaces where the staleness becomes visible (option 3). The reporter
   explicitly accepts option 1 "if `upgrade` must stay minimal."

What `upgrade` does gain is the §4 staleness notice — detection, not migration — so the
author is told at the moment the versions diverge, not at the next failed check.

## 6. Idempotency, already-active, ahead-of-active (the asked question)

- **Idempotent: yes, by construction.** The byte substitution fires only on an
  old-version pattern; a second run finds all three at the target and writes nothing.
  The no-op control (§10) pins zero bytes changed.
- **Already at active: a no-op success** (exit 0, one line). Safe to run in scripts and
  CI; running it "unnecessarily" is never an error.
- **Ahead of the active: refused, never downgraded.** A project stamped above the
  installed SDK's active (author on an older SDK, project touched by a newer one) gets
  `migrate_ui_ahead:` with the "install the newer SDK" remediation. Writing the artifacts
  DOWN to the SDK's active would produce documents the newer SDK that authored them no
  longer validates — the dishonest direction (same reasoning as `derive_move_to`'s
  downgrade marking).
- **Mixed versions: migrate all three**, reporting each file's from→to — the command
  finishes the half-done hand migration (the reporter's own intermediate state) rather
  than refusing it.

## 7. The minimal first slice and its deferrals

**In scope (the slice):**

- `presentation.migrate_ui(...)` + the `migrate-ui` CLI command (§3).
- The `check-ui` remediation line and the `upgrade` staleness notice (§4).
- Tests: a new `tests/test_migrate_ui.py` carrying the RED/GREEN fixture, the controls
  and the refusal arms (§10); the remediation-line arm in `tests/test_presentation_cli.py`;
  the notice arm in the CLI test lane (`tests/test_cli_frameworks.py` or
  `test_scaffold_update.py`'s CLI section — builder's call, both exist).
- Docs: `user_guide/plugin-sdk.qmd` (the command + the migration story),
  README five-steps mention only if the flow's shape wants it. Every `benchweave-sdk`
  mention across the four guide pages is registration-checked by
  `tests/test_getting_started.py` (SDK drift row 1) — naming the command there reddens
  nothing as long as the command exists.

**Deferrals** (id / deferred / home / reopen trigger, per the deferral-row contract):

| id | deferred | home | reopen trigger |
|----|----------|------|----------------|
| D1 | `descriptor_sha256` repair for drifted descriptors (migrate-ui refuses with the digest finding and points at re-derivation instead) | follow-on issue on the gateway tracker | a real migrate-ui run refusing with `migrate_ui_invalid_after_stamp:` on a descriptor digest finding, reported on the tracker |
| D2 | classref-family re-stamp (`ui/class-reference.json` and the catalogue's embedded `extensions` layout block at `classref.py:1200`); today's pointer is `derive-ui --force` | follow-on issue | a class-conformant project reporting a classref-family version refusal after a clean migrate-ui (observable: `classref_layout_invalid` or the declaration's version refusal on the tracker) |
| D3 | plugin-ui-preview fixture migration (fixtures stamped `active_version("plugin-ui-preview")`, `presentation.py:545`; active stable at 0.2.0 since ≤ v0.10.0) | follow-on issue | the SDK lock's plugin-ui-preview active row moves (observable: a `standards-lock.json` diff whose plugin-ui-preview row changes active) |
| D4 | `derive-ui` dirty-tree guard's version-blindness (an untouched-but-version-stale manifest trips `derive_ui_dirty_tree`; the guard compares against the CURRENT derivation's hash, `cli.py:393-400`) | follow-on issue | a tracker report of `derive_ui_dirty_tree` on an unedited manifest, or D2's slice picking it up |
| D5 | the generated `UI-GUIDE.md` naming `migrate-ui` (an SRF-1 scaffold-output interface change: R-2 fixture regen + downstream diff disclosure) | follow-on issue or the next scaffold-output change | the next scaffold-output slice, or a tracker ask for the guide to name the command |

Not in scope by construction: any change to `upgrade_project`'s own walk or write
behavior (L7's), any vendored-bytes or lock change (STD-1/STD-5 untouched), any
scaffold-template change (SRF-1 untouched — D5 is the only scaffold-adjacent piece and
it is deferred).

## 8. Invariant and cross-surface impacts

- **STD-4** (refusal prefixes are the contract): four new `migrate_ui_*:` prefixes;
  documented in the module docstring and the user guide, refused-arity pinned by tests.
- **SRF-2** (host-loader ↔ check-ui agreement): no amendment needed — the design's
  alignment claim rides it. The migration validates through the same vendored
  `validate_presentation` that `check-ui` and the preview host's
  `load_validated_preview_inputs` use, so "migrate-ui accepted" and "check-ui accepts"
  are one gate, not two judgments that could drift.
- **SRF-1**: not touched — no scaffold-output change in this slice (D5 deferred;
  `tests/fixtures/scaffold_expected/` unchanged).
- **STD-1 / STD-5 / TWO-1**: no vendored bytes, no lock rows, no stamps change. Landing
  per TWO-1: SDK PR → merge → `make release-cut` → gateway pointer PR (issue #408
  order). **No main-side counterpart is needed**: the gateway's admission validates
  presentation attachments against its own corpus, whose plugin-ui active is already
  0.4.0 (PR #479); a re-stamped set this SDK accepts, the gateway accepts.
- **SDK drift rows walked**: row 1 (CLI-visible behavior → `user_guide/plugin-sdk.qmd`,
  README five-steps, first-timer pages; `test_getting_started.py` registration) — in
  scope above; row 2 (scaffold output) — not touched; row 6 (behavioral tests live here;
  the new module is named) — in scope; row 8 (two-repo landing order) — statement above;
  row 9 (agent-asset claims) — no forced change (the obligation binds CITED subcommands;
  citing `migrate-ui` in a managed skill is optional and deferred with D5).
- **On-disk formats / schemas:** none changed. No JSON Schema file, no lock format, no
  scaffold fixture. (Tier-3 is triggered by keywords, not by a format change — §9.)
- **CI cost:** the new tests ride the existing `sdk` lane (unit-level, offline, no
  network, no copier interaction); the docs site rebuilds via `docs.yml` as usual. No
  new lane, no new job.

## 9. Review tier and the Step-1 keyword scan (#254)

**Tier 3** — the maximum across this slice, triggered by the Step-1 keyword rule
(`docs/internal/review-rubric.md`, gateway authority, applied per the train's standing
practice): the expected diff text contains `sha256`, `hashlib` and `migrate` by
construction — the mechanism is a hash repair on a command named `migrate-ui`. Tier 3
buys the mandatory adversarial refute (G6) and the full battery. No Tier-3 path rule
fires (no `standards/` byte, no persisted-format surface, no schema file, no
dependency change, no submodule pointer inside this slice — the pointer advance is the
separate landing step per TWO-1).

**Standards-governor mandate (#69):** the expected diff writes plugin-ui version
literals into test fixtures and reads active-version strings — dispatch the
standards-governor as a pre-merge pass. Cheap and correct here; over-dispatch is the
safe direction.

**Keyword scan over the expected diff text** (the enumerated files below; the review
re-derives both the tier and the counts — these are the design-time counts over the
planned diff, stated per #254):

Expected diff files: `src/benchweave_sdk/presentation.py`, `src/benchweave_sdk/cli.py`,
`tests/test_migrate_ui.py` (new), `tests/test_presentation_cli.py`,
`tests/test_cli_frameworks.py`, `user_guide/plugin-sdk.qmd`, `README.md` (five-steps
sentence only if the flow wants it).

| keyword | expected count | where |
|---------|----------------|-------|
| `migrate` | ~35 | command name, refusal prefixes, tests, guide |
| `sha256` | ~10 | hash recompute, envelope field name, test assertions, guide |
| `hashlib` | ~3 | the one `hashlib.sha256` call + tests' expected-value computation |
| `subprocess` | 0 | no shell-outs (reads via `read_file`, writes via `Path`) |
| `threading` / `asyncio` | 0 | synchronous command |
| `recovery` | 0 | — |
| `protection` | 0 | — |

## 10. Measurable proof and the pre-committed acceptance rule

**The fixture — coherent-stale, not version-swapped.** The RED fixture must be the
byte-shape a v0.10.0-era project actually had: all three documents at plugin-ui 0.3.0
AND the envelope hash matching those 0.3.0 manifest bytes. (A naive hand-edit that only
swaps version strings produces a `digest_mismatch` fixture — a different failure than
the issue reports.) The test helper builds it by the exact inverse of the migration:
targeted down-substitution of the version in all three, then the envelope hash over the
downgraded manifest. Constructed from a fresh `new --with-ui` scaffold with the current
SDK — no old SDK checkout needed.

**Proof arms:**

1. **RED (pre-existence):** on the coherent-stale fixture, the generated
   `tests/test_presentation_preview.py` FAILS with
   `preview_invalid_presentation: unsupported_version: presentation-envelope` (the
   reporter's string), and `check-ui` exits nonzero with the same finding. This is the
   issue reproduced mechanically, before any fix exists.
2. **GREEN:** one `migrate-ui` run on the fixture → the same suite passes (collected ≥ 1,
   0 failed), `check` and `check-ui` exit 0. Exactly 3 files changed, each reported.
   Zero manual edits anywhere in between.
3. **Controls (the parts fluff cannot pass):**
   - **no-op control:** on a fresh at-active project, tree hashes before/after a
     `migrate-ui` run are identical and the command exits 0 — idempotency and
     already-active, pinned as bytes not prose.
   - **canary control:** a hand-added manifest page (author content) survives the
     migration deep-equal — proves re-stamp, not re-derivation.
   - **ahead control:** trio hand-set to a version above active → `migrate_ui_ahead:`,
     zero writes (tree hashes identical).
   - **refusal control:** descriptor edited after scaffold (descriptor drift) →
     `migrate_ui_invalid_after_stamp:` with the digest finding, zero writes (tree
     hashes identical) — all-or-nothing pinned.
   - **stamp-unlocatable control:** a manifest whose version value is
     unicode-escaped → typed refusal, zero writes.

**Pre-committed acceptance rule** (written before any implementation runs):

- **SHIP when**, on the coherent-stale 0.3.0 fixture against the current lock
  (plugin-ui 0.4.0): (a) `migrate-ui` reports exactly three changed files with
  from→to 0.3.0→0.4.0; (b) the post-state passes the generated pytest suite
  (collected count ≥ 1, failures 0), `check`, and `check-ui`, with zero manual edits;
  (c) the canary page survives deep-equal; (d) the no-op control changes zero bytes;
  (e) each refusal arm refuses with its typed prefix and zero writes.
- **KILL when:** the post-stamp validation refuses on the coherent-stale fixture with a
  finding that a HAND-migrated copy of the same fixture equally triggers — i.e. the
  reporter's manual repair also fails. That falsifies the corpus note's "documents are
  0.4.0-valid except `contract_version`" for this document shape, and the design moves
  to derivation semantics (which changes the author-content story and reopens the
  option-2 question).
- **UNDERPOWERED, not conclusive, when:** the only constructible stale fixture is the
  synthetic one (no real ≤ v0.10.0 project is in hand to test against). Then the ship
  claim rests on the synthetic shape plus the corpus's sorted-key-diff basis; a
  real-project confirmation is recorded as a follow-up observation, and the acceptance
  stands (GREEN on synthetic) with that disclosure — it does not flip to KILL on the
  absence of a real corpus.

## 11. Top risks, each with its falsifier

- **R1 — a future plugin-ui bump changes schema shape, not just version strings.**
  The re-stamp then produces version-honest but schema-invalid documents; the pre-write
  validation refuses (the safe direction) and the command's promise narrows to "refuse
  loudly with findings." Falsified if a bump ships where a hand re-stamp passes but
  migrate-ui's validation refuses — that would be a validator-path bug, not a semantics
  gap.
- **R2 — the targeted byte substitution misses real-world formatting** (exotic
  escaping, unusual spacing): surfaces as `migrate_ui_stamp_unlocatable:`. Falsified by
  a real project whose bytes the pattern cannot locate while `check-ui` accepts the
  document — then widen the pattern (or take the re-dump with a formatting-change
  disclosure) as an addendum.
- **R3 — the upgrade notice's package-dir heuristic** (first directory under `src/`,
  the `derive-ui` shape) misfires on unusual layouts: prints nothing or names the wrong
  package. Advisory only; falsified by a real layout where the notice names a wrong
  path — then scope the notice to an explicit path argument or drop it.
- **R4 — authors expect option 2** and file "upgrade still leaves the artifacts stale"
  despite the notice. Falsified by tracker traffic showing the notice is missed in
  practice — that evidence reopens option 2, with the ordering constraint
  (migrate BEFORE `run_update`, refuse-fast) stated in advance here.
- **R5 — concurrent edits during the command** (editor holding a file open): no
  locking, same posture as `derive-ui`; out of scope.

## 12. Verdict

BUILD, as scoped. The defect is real and reproduced mechanically (the RED fixture is
the issue's own failure string); the mechanism extends proven in-tree pieces
(`read_file`'s strict walk, `validate_presentation` as the one gate, the `-ui` command
family, STD-4 prefixes); the corpus itself sanctions the re-stamp semantics for both
version deltas this design must cover; the proof is measurable with controls that fluff
cannot pass; and the deferrals each carry a home and an observable reopen trigger. No
DON'T-BUILD grounds exist — the one genuinely open question (option 2 vs option 1+3) is
decided on code-anchored posture grounds in §5, with the reopen condition (R4) stated.

**Maintainer decisions requested:** (1) the command name — `migrate-ui` recommended
over the reporter's `regenerate` because the semantics are version re-stamp + hash
repair, not regeneration, and `derive-ui` already owns regeneration; (2) whether the
`upgrade` staleness notice (§4) is wanted at all in this slice or belongs with L7's
upgrade overhaul; (3) D1's appetite — whether descriptor-hash repair should ride a
later slice or stay a refusal with a pointer.
