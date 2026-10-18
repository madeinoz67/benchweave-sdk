# L10 design — issue #463 row 8: fixture-generation command exposure

**Date:** 2026-10-17
**Issue:** madeinoz67/benchweave#463 row 8 (single issue stream; SDK-side work, no
SDK-side issue by design)
**Program linkage:** classref train,
`.claude/deep-review/2026-10-14-classref-logic-analyser-design.md` §7A slot L10 / §8 row
RC-7 — the last slot of the slotted set. This record is L10's own design record; the
program record does not scope it. Siblings: L6 (#460, landed), L7 (#461, landed), L8
(#463 row 3, landed), L9 (#463 row 7, **in flight, unmerged** — §6 names the rebase).
**Verdict:** **BUILD, re-scoped — the row is real, undischarged, and smaller than it
reads.** The generation code exists (in `presentation.py`, not the fixtures module the
row names) and no command exposes it: verified on `origin/main`. But the blast is
narrower than the row implies — author fixtures have exactly one consumer (the
scaffolded project test); `preview-ui`, `serve`, `check-ui`, packaging and admission
never read them, and the scaffolded test's own assertions pass with the examples
deleted, so the author's zero-effort escape today is deleting them. The fix is one new
command, `benchweave-sdk regen-fixtures <project>`, reusing the scaffold's own generator
byte-for-byte. Design-only leg: no implementation code in this record.

---

## 1. Pre-flight (#181 R2)

- SDK `origin/main` at `3769b8b` (merge of #175 = L8 landed); `git fetch origin` run.
  Design worktree `.wt/l10-r4k9` off `origin/main`. `git worktree list` walked first:
  `.wt/l7-m4t8`, `.wt/l7b-k7v2`, `.wt/l8-qz7f`, `.wt/l8b-h2v8`, `.wt/l9-v3n8` belong to
  sibling lanes and were not touched.
- **L9 is in flight** (`.wt/l9-v3n8`, branch `feat/issue463-row7-checkpreset-firmware-optional`,
  unmerged): it edits `cli.py`'s `check-preset` block (376–422), one line of the
  plugin-ui skill template (its check-preset section), and the
  `tests/fixtures/scaffold_expected/` trees. This design edits `cli.py` (a NEW command
  block placed after `verify-ui` — a region L9 does not touch), the same skill template
  (a NEW section, disjoint lines from L9's one-line edit), and the same fixture trees
  (regeneration). **This design assumes a rebase onto a `main` that carries L9; no
  parallel merge is planned.** The fixture regeneration is sequenced LAST, after both
  lanes' code changes (L9's own adjacency note already rules this).
- Remote branches touching the planned paths: none beyond the train's own
  (`feat/issue463-row3-styleguide-discoverability` merged as #175; L9's branch above).
  No open SDK PRs at pre-flight.
- **GORTEX UNAVAILABLE TO SUBAGENT** — the probe (`mcp__gortex__read` on
  `benchweave-sdk/src/benchweave_sdk/cli.py`) refused with checkout-discovery-unavailable
  (issue #831 class: "indexer: checkout mutation lane is busy; context deadline
  exceeded"). Native tools used throughout, per the dispatching brief. Two later shell
  `grep` invocations were hook-blocked on bare symbol-shaped words and re-run with a
  regex metachar per the hook's own instruction; no graph access was granted at any
  point.
- Premise probe on the dispatch brief itself: the brief's "rows 1 to 3 and 7 are landed
  or landing as L6 through L9" is off by two slots — L6 and L7 carried rows 4 and 5
  (issues #460/#461), not rows 1–3. Rows 1–2 landed at L2/L3 (SDK #153, v0.14.0: the
  expander, the rendered-output gate, the class-descriptor scaffolding); row 3 landed
  as L8; row 7 is L9. Row 8 (this slot) is not one of the issue's three named end-state
  outcomes — it is the maintenance row, and it stands open.

## 2. What the fixtures module actually generates, and for whom (question 1, from source)

Two different "generation" facts live in this area; the row conflates them, and the
conflation matters for scope:

**A. The baseline set — `fixtures.generate_baselines` (`src/benchweave_sdk/fixtures.py:253`).**
Nine mandatory scenarios (`normal` … `request-rejected`), synthesized IN MEMORY from the
live binding catalogue on every model build, with ids reserved against author reuse
(`BASELINE_IDS`, enforced by `preview_reserved_scenario` at line 129). Because they are
derived at read time from the very catalogue they are validated against, **they cannot
go stale and need no command.** The row is not about these.

**B. The scaffolded example fixtures — `presentation._preview_fixture` /
`presentation._write_preview_examples` (`src/benchweave_sdk/presentation.py:805–895`).**
At `new --with-ui` (legacy path only — see below), the scaffold writes exactly two
files, `ui/fixtures/normal.json` (`id: example-normal`, severity `neutral`) and
`ui/fixtures/warning.json` (`id: example-warning`, severity `warning`), each a pure
function of the FIRST observation target: binding id, unit and value type come verbatim
from the catalogue target (`values = {"number": 1.0, "integer": 1, "boolean": True,
"string": "simulated"}`), and `contract_version` is stamped
`active_version("plugin-ui-preview")` at scaffold time. The same function writes the
project's `tests/test_presentation_preview.py`.

**Premise correction (row-located, L9-style):** the row says "the generation code
exists in the SDK fixtures module." It does not — neither at v0.12.0 (verified:
`git show v0.12.0:src/benchweave_sdk/presentation.py:536` already carries
`_preview_fixture`) nor on main. The example generator is scaffold-side
(`presentation.py`); `fixtures.py` carries the loader (`load_author_fixtures`), the
baseline generator (A) and the projection. The row's material claim — generation code
exists, no command exposes it — is TRUE: `_write_preview_examples` has exactly one
caller (`create_ui_resources`, the `new --with-ui` path), and nothing else in the SDK
invokes the generator. This design moves the generator to `fixtures.py` so the row's
sentence becomes true post-landing (§4).

**Who consumes author fixtures — the census that shrinks the row:**

| surface | reads `ui/fixtures/*.json`? |
|---|---|
| the scaffolded `tests/test_presentation_preview.py` | **YES — the only consumer.** `build_preview_model` → `load_author_fixtures` (`fixtures.py:422`) |
| `preview-ui` / `serve` | **no.** The nine serve-time scenarios come from the host-shipped `ScenarioAdapter` (`benchweave_sdk_server/scenarios.py`); `server/presentation.py` imports only `project_plot_views`. Author fixtures are never loaded on any serve path |
| `check-ui` / `load_validated_preview_inputs` | **no.** Validation covers presentation/manifest/catalogue; fixtures are outside the candidate (`presentation.py:493–544`) |
| `upgrade` / `scaffold_update.py` | **no.** Zero fixture handling; fixtures are derived files, not copier template members, so upgrade cannot carry them |
| `derive-ui` | writes manifest, envelope, catalogue, settings schema, presets, `class-reference.json` (`cli.py:526–536`) — **no fixtures line** |
| `migrate-ui` (L6) | re-stamps exactly three plugin-ui-family documents (`presentation.py:574+`); fixtures are plugin-ui-**preview**-family and outside its set by design |
| packaging / admission | no |

And the scaffolded test's own assertions (`presentation.py:876–891`) check
`BASELINE_IDS` coverage and the plot projection — **neither needs the example files**.
So the examples' real function is: (a) a valid, copyable format model, and (b) the
input that makes the scaffolded test exercise `load_author_fixtures`.

**The classref-path fact:** `create_ui_resources`'s class-reference branch
(`presentation.py:956–977`) returns WITHOUT calling `_write_preview_examples`. A
descriptor whose profiles match a vendored class reference scaffolds NO example
fixtures and NO preview test — the flagship classref flow has no fixtures at all. Row
8's "scaffolded examples" population is therefore exactly the legacy-path projects.

## 3. What "track catalogue edits by hand" costs (question 2)

Two independent staleness axes, both ending in the same place — the author's own pytest
red — and both fixed today only by hand-editing JSON (or deleting the files):

- **Axis A — catalogue/binding drift.** The author edits their descriptor (or re-derives
  after a reference change) → `binding-catalogue.json` changes a target id/unit/type →
  `_scenario`'s cross-check refuses: `preview_unknown_binding` / `preview_unit_mismatch`
  / `preview_type_mismatch` (`fixtures.py:133–146`). Discovery is immediate and
  self-describing (the error names the fixture path and the binding) but the FIX is
  hand-editing two JSON files whose shape the author must infer from the examples
  themselves.
- **Axis B — plugin-ui-preview contract bump.** The ACTIVE fixture schema pins
  `contract_version: {"const": "0.2.0"}` (verified in the vendored 0.2.0 schema), and
  `load_author_fixtures` validates against the ACTIVE schema only (`_fixture_schema`,
  `fixtures.py:39–61`, digest-verified). A project scaffolded before a bump carries
  stale-const fixtures and fails `preview_invalid_fixture` until every fixture file is
  hand-re-stamped. **This axis has already fired once in the wild**: the lock carries
  plugin-ui-preview 0.1.1 (retained) → 0.2.0 (active). L6's `migrate-ui` deliberately
  does not cover it — its semantics are "the version string and nothing else" over the
  three plugin-ui documents, the corpus's sanctioned migration for THAT family.

**Is there a reason generation was left unexposed?** No structural reason found. The
generator's inputs (the catalogue) are always present in any UI project; the output is
deterministic; nothing about the write is bench- or hardware-adjacent. The omission
reads as scope drift: the generator was built as a scaffold-internal helper and never
promoted. The one design constraint that IS real is ownership — the fixtures directory
is author territory (up to 128 author scenarios), so exposure must not clobber author
content (§4).

## 4. The command shape and its precedent (question 3)

Options considered against the repo's own precedents:

- **(B) fold into `derive-ui`** — rejected on structure: `derive-ui` requires a vendored
  class reference to match (`cli.py:502–506` refuses otherwise), so the ONLY projects
  that have fixtures today (legacy path) are the ONE set that cannot run the command.
  The coverage inverts. Also chained writes would muddy derive-ui's dirty-tree refusal
  posture for no gain.
- **(C) widen `migrate-ui`** — rejected: L6's semantics are a corpus-sanctioned version
  re-stamp of three plugin-ui documents; fixtures need content regeneration (axis A) in
  a different family (plugin-ui-preview), and no sanctioned migration exists for that
  family. Regeneration makes the version axis moot anyway: the generator stamps the
  active version live.
- **(A) a new subcommand — the precedent-named shape.** The repo's maintenance-command
  family is verb-noun over a project argument: `derive-ui <project>`,
  `verify-ui <project>`, `migrate-ui <envelope>…`. A fixture regenerator is exactly
  this class.

**The design: `benchweave-sdk regen-fixtures <project>`** — one positional
project-root argument (the `derive-ui`/`verify-ui` shape), zero flags, core install (no
`[server]` extra; `fixtures.py`/`presentation.py` are core), `_domain_errors` wrapped.

Mechanism (one generator, two callers — principle 9, G4):

1. **Move** `_preview_fixture` from `presentation.py` to `fixtures.py` (private name
   may stay; the scaffold's `_write_preview_examples` body-imports it — cycle-safe:
   `fixtures.py` imports `presentation` at module level, so the reverse import must be
   call-time, the same body-import posture `presentation.py:949` already uses for
   `classref`). Scaffold output is BYTE-IDENTICAL: the function and its `json.dumps(indent=2)+"\n"`
   framing do not change, only its address. The committed scaffold-expected fixture
   bytes do not move.
2. **New `fixtures.regenerate_example_fixtures(catalogue_path, fixtures_dir) ->
   RegenOutcome`** (a `MigrationOutcome`-shaped dataclass: `written: tuple[str, …]`,
   `noop: bool`, `notes: tuple[str, …]`):
   - read + parse the project's `binding-catalogue.json`;
   - select the FIRST `kind == "observation"` target in catalogue order (the loader's
     own iteration order; the scaffold's `targets[0]` for legacy projects, which build
     observation targets only) — refuse `regen_fixtures_no_observation_target:` if none;
   - compose the two documents via the moved generator (the exact scaffold arms);
   - **validate in memory before any write**: each document through the same
     per-document checks `load_author_fixtures` applies (the active digest-verified
     schema + the catalogue cross-check). Implementation is a small refactor extracting
     the per-file body of `load_author_fixtures` (`fixtures.py:226–239`) into a shared
     helper both callers use — one validation mechanism, byte-identical loader
     behavior. A generated document that would not load refuses
     `regen_fixtures_invalid_generated:` with nothing written — the
     generator/loader-drift guard;
   - **ownership guard**: for each of `normal.json` / `warning.json`, if the path
     exists and its parsed `id` is not the matching example id, refuse
     `regen_fixtures_author_content: <path>` naming the file — all-or-nothing, nothing
     written (the `migrate-ui` validate-before-write posture). Every OTHER `*.json` in
     the directory is untouched;
   - byte-compare against current content: unchanged files count toward `noop`;
     changed/absent files are written. Idempotent by construction.
3. **CLI block** after `verify-ui` (`cli.py` ~552): package-dir discovery shared with
   `derive-ui` (extract the inline `next((path for path in (project / "src").iterdir()
   …))` into a tiny `_package_dir(project)` used by both — the second use mints the
   helper). Output: written lines in green, a noop line, and the standing offline
   disclaimer sentence.

**Disclosed ownership residual (G4):** the guard does NOT catch an author who edited
an example file's values while keeping the example id — those edits are overwritten on
regen. The examples are SDK-owned synthetic content by the scaffold's own design
("generated synthetic preview examples"); author scenarios belong at their own ids,
which regen never touches. This is the scaffold's semantic, restated, not a new rule.

**New refusal paths (STD-4 snake_case family):** `regen_fixtures_no_package:`,
`regen_fixtures_no_catalogue:`, `regen_fixtures_no_observation_target:`,
`regen_fixtures_author_content:`, `regen_fixtures_invalid_generated:`.

**Mint-if-absent:** on a project with no `ui/fixtures/` directory (e.g. a classref
project), regen creates the directory and mints the two examples rather than refusing —
one rule, no directory-archaeology special case. The output discloses that the
scaffold's classref path writes no examples (so the command is the author-side way to
get them) and that wiring them into project tests is the author's choice. The SCAFFOLD
itself is unchanged on this point (D-L10-2).

## 5. Is this the right row, and is it already discharged? (question 5)

**Not discharged, and no overlap with landed rows** — each neighbour named and cleared:

- L2/L3 (rows 1–2): the expander + gate + class-descriptor scaffolding. `derive-ui`'s
  write set has no fixtures line — the derivation never touched examples.
- L6 (#460): `migrate-ui` re-stamps the three plugin-ui documents; the plugin-ui-preview
  family is outside its set by its own docstring, and its version-only semantics could
  not fix axis A anyway.
- L8 (row 3): documented `preview.css` at the three scaffold-carried surfaces. Its
  record twice pointed here — D-L8-1 ("deferred with the row-8/L10 command-exposure
  slice as its natural home") and RC-L8-3 ("verification is row 8/L10's natural
  companion (a command that computes/re-pins digests)"). **That framing conflates two
  different hand-maintained pin families**: asset `sha256` pins (manifest `assets[]`
  rows, verified at serve time by `assets.py`) versus fixture examples (this row). A
  digest-computing command would NOT regenerate fixtures, and a fixture command does
  not verify asset pins. Row call RC-L10-2 below keeps them separate.
- L9 (row 7): `check-preset` flag semantics. Disjoint.

**The honest scope reduction, stated for the PR body:** the row reads as if fixture
staleness blocks the authoring workflow. It does not block anything the SDK serves —
it reddens the author's own project test, and the author's zero-effort workaround
today is deleting the examples (the test's assertions do not need them). What the row
actually buys: the examples become a maintained format model instead of a
one-shot scaffold artifact, and axis B stops being per-file hand-re-stamping across
every legacy project on every preview-contract bump. That is worth one command; it is
not worth more machinery than §4.

## 6. Blast radius (question 4)

| surface | effect | action |
|---|---|---|
| `src/benchweave_sdk/fixtures.py` | the moved generator, `regenerate_example_fixtures`, the shared per-document validation helper | edit — **Tier-3 path by the SDK rubric's own rule** |
| `src/benchweave_sdk/presentation.py` | `_write_preview_examples` body-imports the moved generator; UI-GUIDE emitter gains one clause naming the command; `_package_dir` extraction | edit |
| `src/benchweave_sdk/cli.py` | new `regen-fixtures` command block after `verify-ui`; `_package_dir` shared with `derive-ui` | edit (disjoint region from L9's `check-preset` block; rebase-expected, §1) |
| `template/.claude/skills/benchweave-plugin-ui/SKILL.md.jinja` | new short section "Refresh the example fixtures" (~4–6 STE sentences: examples track the binding catalogue; run `benchweave-sdk regen-fixtures <project>` after catalogue edits or a plugin-ui-preview bump; the command refuses to overwrite a file whose scenario id is not the example id; author scenarios at their own ids are never touched) | edit — new section, disjoint from L9's one-line edit in the check-preset section |
| `tests/fixtures/scaffold_expected/**` | rendered mirror of the skill + UI-GUIDE changes | regenerate BOTH arms in-PR (obligation 2: scaffold output is an interface — SRF-1 disclosure in the PR body; sequence AFTER L9's regen or as the single regen covering both, never concurrently) |
| `tests/test_preview_fixtures.py` | the unit arms (§8 AR-L10-1) — the module already owns loader/projection behavior | add RED-first tests |
| `tests/test_presentation_cli.py` | the CLI arms (§8 AR-L10-2), through the Click runner — the module already owns presentation CLI behavior | add RED-first tests |
| `tests/test_agent_assets.py` | presence arms for the new citations (§8 AR-L10-3); R-5b triangulation picks up the skill's `regen-fixtures` subcommand citation automatically (registered → green) | add presence arms |
| `user_guide/plugin-sdk.qmd` | drift row 1: a new command is CLI-visible behavior → the guide must document it. A short subsection beside the migration section (§"Contract-version migration", qmd:144–159), naming the command, the two axes, and the ownership guard | edit — **ASD-STE100 register; build dispatches the `document-writer` agent** |
| README five-steps / scaffold-output paragraph (README:168) | one clause: the examples regenerate with `benchweave-sdk regen-fixtures` | edit |
| `tests/test_getting_started.py` | registration gate scans the four first-timer pages for `benchweave-sdk` mentions | no edit needed unless the pages name the command (they should not — it is not a first-timer step); stays green |
| `docs/internal/drift-and-obligations.md` row 9 | agent-asset claims: the skill's new subcommand citation triangulates against the click group (R-5b mechanism — self-policing once registered) | no doc edit; the obligation is discharged by the test arms |
| gateway repo | none — no corpus byte moves, no pointer in this slice (the SDK release + pointer ride the train's standing order, not this PR) | none |

**L9 rebase statement (per the dispatching brief):** this design's `cli.py` and
skill-template edits are line-disjoint from L9's, but both lanes regenerate the same
`scaffold_expected` trees and both touch `cli.py` at all — the build leg REBASES onto
`main`-with-L9 and re-runs the Step-1 scan on the rebased diff. No parallel merge.

## 7. Deferrals (id / deferred / home / reopen trigger)

| id | deferred | home | reopen trigger |
|----|----------|------|----------------|
| D-L10-1 | check-ui verification of declared `assets[]` pins against bytes (inherited D-L8-1; L8's RC-L8-3 named this slice its "natural companion" — declined here, §5: two different pin families) | gateway-tracker follow-up issue (L8's recorded home stands) | that issue being scheduled; or a tracker report of a green `check-ui` followed by a serve-time `standalone_preview_override_refused:` digest refusal |
| D-L10-2 | the classref scaffold path writing example fixtures + the preview test (uniformity: every `new --with-ui` project gets the example set) | the class sweep's scaffold-input ruling (first sweep design, L11 dc_psu) | the first sweep plugin whose acceptance wants the scaffolded preview test; or an owner uniformity ruling |
| D-L10-3 | an author-fixture FORMAT section in the user guide (the guide documents no fixture format today — one passing mention at qmd:195, different sense) | published-docs pass via `document-writer` | an author ask for the format; or the sweep |
| D-L10-4 | `derive-ui` chaining regen when it rewrites the catalogue | an ergonomics pass after the sweep | author feedback that the two-step (derive, then regen) is missed — the derive-ui output pointer added by this slice may answer it |
| D-L10-5 | serving author fixtures in preview/serve (they are project-test-only today) — a CAPABILITY question, out of this row's scope by construction; recorded so the command is not misread as a step toward it | plugin-ui-preview corpus | an owner/corpus request to surface authored scenarios at serve time |

**Row calls for the owner** (defaults run as recommended; redirect window open until
the first PR opens):

- **RC-L10-1 — command name `regen-fixtures`.** Alternatives: `gen-fixtures`
  (ambiguous about overwrite), `sync-fixtures` (implies byte-sync against a lock;
  regeneration is the honest verb). Recommend **ACCEPT**.
- **RC-L10-2 — fold D-L8-1 (check-ui asset-pin verification) into this slice.**
  Recommend **DEFER**: it lives in `validation.py` (assets[] semantics) and would make
  this a validator-behavior change stacked on a new command — two Tier-3 surfaces in
  one landing with no shared mechanism. L8's "natural companion" reasoning conflated
  asset digests with fixture examples (§5).
- **RC-L10-3 — make the classref scaffold write examples + preview test now.**
  Recommend **DEFER** (D-L10-2): a scaffold-behavior change beyond the row; regen
  already gives classref authors the examples on demand; uniformity is a sweep-input
  ruling.
- **RC-L10-4 — `derive-ui` output pointer** (one line in its success message:
  "regen-fixtures refreshes the example fixtures"). Recommend **ACCEPT** — one output
  line, no chaining, no flag.

## 8. Measurable proof and the pre-committed acceptance rule (written before any build)

The row is behavioural at the core (a command + a write path) with a docs rim; both
parts get machine checks. The proof is the round trip: catalogue moves → project test
red → one command → project test green, pinned at unit, CLI and registration level.

**AR-L10-1 — functional arms (new, in `tests/test_preview_fixtures.py`; denominator:
7 arms, ALL red on main — the API does not exist):**

1. `test_regen_tracks_catalogue_edits` — a catalogue with observation target `t1`
   (unit `V`); regen; rewrite the catalogue to target `t2`/unit `A`; regen again →
   both files reference `t2`/`A`, and `load_author_fixtures(dir, new_catalogue)`
   returns 2 scenarios (the round-trip arm: what regen writes, the loader accepts).
2. `test_regen_refuses_author_content_and_writes_nothing` — `normal.json` carrying
   `id: "custom"` → ValueError `regen_fixtures_author_content:` naming the path;
   `warning.json` bytes unchanged (all-or-nothing).
3. `test_regen_preserves_author_scenarios` — an extra `my-scenario.json` in the
   directory survives byte-identical and appears in no written line.
4. `test_regen_is_idempotent` — second consecutive run → `noop`, no written lines.
5. `test_regen_stamps_active_preview_contract` — seed `normal.json` with a stale
   `contract_version` (id `example-normal` kept) → after regen the stamp equals the
   lock's active plugin-ui-preview version and the file loads clean (axis B).
6. `test_regen_output_matches_scaffold_bytes` — regen over the scaffold-expected
   project's catalogue produces bytes EQUAL to the committed
   `tests/fixtures/scaffold_expected/ui/src/example_plugin/ui/fixtures/{normal,warning}.json`
   (the parity arm: scaffold and regen share one generator — the structural guarantee
   of §4 item 1).
7. `test_regen_no_observation_target_refuses` — a catalogue of non-observation targets
   → the named refusal, nothing written.

**AR-L10-2 — CLI arms (in `tests/test_presentation_cli.py`, through the Click runner):
denominator 3** — happy path exits 0 with written lines + the offline disclaimer;
author-content case exits 1 with the `regen_fixtures_author_content:` message; unknown
project path exits 2 (`Path(exists=True)`). All three red on main (`No such command
'regen-fixtures'`).

**AR-L10-3 — registration and presence arms (in `tests/test_agent_assets.py`);
denominator 3** — the skill template contains `regen-fixtures`; the committed
`tests/fixtures/scaffold_expected/ui/UI-GUIDE.md` contains `regen-fixtures`; R-5b
`test_real_assets_pass_triangulation` green (the skill's subcommand citation resolves
against the click group). Red on main: the two presence facts are absent (verified
this pass: zero `regen-fixtures` tokens in either surface).

**AR-L10-4 — no scaffold drift beyond the two prose surfaces** — the R-2 byte-parity
arms of `tests/test_scaffold_copier.py` green after the in-PR regeneration, and the
regenerated diff touches exactly the skill (both arms) and UI-GUIDE (ui arm); the
committed example-fixture BYTES are unchanged (AR-L10-1 arm 6 pins them).

**End-to-end build smoke (once, by hand at build; outputs to file, exit codes read
unpiped):** fresh `benchweave-sdk new --with-ui` into a temp dir → its pytest GREEN
(collected count recorded); rename the first observation target in the descriptor +
catalogue → its pytest RED with `preview_unknown_binding` (exit + collected count
recorded); `benchweave-sdk regen-fixtures <project>` → exit 0; its pytest GREEN again.
**This sequence is the row reduced to one command, measured.**

**Falsifiers (kill directions, run by the refute lane):**

- Point the moved generator's value map at a different literal → AR-L10-1 arm 6
  reddens (scaffold/regen divergence — the parity guarantee is load-bearing).
- Drop the ownership guard → arm 2 reddens (overwrite where the design refuses).
- Make regen skip in-memory validation and emit a document the loader rejects → arm 1
  reddens (`load_author_fixtures` refuses what regen wrote).
- Rename the command in `cli.py` only, or delete the skill section → AR-L10-3 reddens
  (registration/presence).
- Add a `--force`-style flag or chain the write into `derive-ui` → the diff review
  reddens by construction (§4 says zero flags, no chaining) — named so the refute lane
  checks the diff shape, not just the tests.
- Any scaffold-expected fixture-byte change beyond the two prose surfaces → AR-L10-4
  reddens.

**Gates:** fast lane every commit (bare `ruff check .`, fresh-cache bare `mypy`,
focused `pytest` on `tests/test_preview_fixtures.py` + `tests/test_presentation_cli.py`
+ `tests/test_agent_assets.py` + `tests/test_scaffold_copier.py`); full battery + both
standards tripwires once, immediately before push; true exit codes, junitxml counts,
never a filtered summary line.

## 9. Review tier and Step-1 keyword scan (#254) (question 7)

**Tier 3** — by the SDK rubric's own path rules, twice over: the diff touches
`fixtures.py` (named Tier-3 surface: "a weakening here silently greenlights a
non-conformant plugin" — the shared-validation refactor is exactly the kind of change
that rule exists to referee), and it **adds refusal paths** (the five
`regen_fixtures_*:` prefixes — the snake_case machine-matchable surface). Mandatory
adversarial refute (G6) before the PR; full battery before push.

**The scaffold-output rule fires, narrowly:** the slice changes scaffold output at
exactly two PROSE surfaces (the skill template and the UI-GUIDE emitter) → R-2
regeneration of both arms + SRF-1 interface disclosure in the PR body (downstream
projects diff the skill at their next `upgrade`; UI-GUIDE reaches new scaffolds only —
L8's §3 propagation table stands). The scaffold's example-fixture BYTES do not change;
AR-L10-1 arm 6 and AR-L10-4 pin that. The added prose names no digest keyword — but
the tier is already 3 by path, so the keyword question does not carry the load; the
builder re-runs the Step-1 scan on the rebased diff text regardless and records the
result here at build time.

**Standards-governor:** not engaged — no `standards/` byte moves, no lock change, no
contract-version bump (the generator READS the active version; it mints nothing).

## 10. Top risks, each with its falsifier

- **R1 — the shared-validation refactor silently loosens the loader.** The extraction
  of `load_author_fixtures`'s per-file body must be behavior-identical. Mitigation:
  the existing loader arms (`test_author_fixture_rejects_unknown_binding`,
  `test_author_fixture_rejects_wrong_unit`, the schema arms) stay untouched and green;
  the refactor is one commit, loader-only, reviewable in isolation. Falsifier: any of
  the pre-existing loader arms reddening on the refactor commit.
- **R2 — example-target selection disagrees with the scaffold's.** The scaffold uses
  `targets[0]` (legacy targets are all observations); regen uses first-observation-in-
  catalogue-order. For legacy projects these coincide; for derived catalogues they
  need not. Mitigation: the selection rule is stated (§4 item 2) and pinned by arm 6
  on the scaffold-expected corpus. Falsifier: arm 6 reddening on a derived catalogue
  in the sweep era — reopen against D-L10-2.
- **R3 — STE register drift in the published prose** (user-guide subsection, skill
  section, UI-GUIDE clause). The R-5b checker does not verify register (disclosed
  residual). Mitigation: `document-writer` dispatch for those three; the refute lane
  reads them against STE rules. Falsifier: a refute finding quoting a non-STE
  sentence.
- **R4 — reach overclaim.** The PR must not claim fixtures now ride preview/serve —
  they remain project-test-only (§2 census). Falsifier: any PR-body or release-notes
  sentence claiming serve-time fixture behavior.
- **R5 — collision with L9's regen.** Both lanes regenerate the same fixture trees.
  Mitigation: §6's sequencing rule (rebase onto L9-carrying main; one regen after both
  code changes). Falsifier: a concurrent regen producing a mechanical double-diff —
  caught by AR-L10-4's exactly-two-surfaces check.

## 11. Evidence (paths read, all this session, worktree `.wt/l10-r4k9` @ `3769b8b` unless noted)

- `src/benchweave_sdk/fixtures.py` (full): `BASELINE_IDS` 24–36; `_fixture_schema`
  39–61; `_target_index` 74–82; `_observation_value_variable` 85–108; `_scenario`
  122–174 (the cross-check refusals 133–146); `load_author_fixtures` 177–240 (the
  per-file body 226–239 = the refactor target); `generate_baselines` 253–332;
  `build_preview_model` 419–431 (the sole `load_author_fixtures` call site, 422).
- `src/benchweave_sdk/presentation.py`: `_preview_fixture` 805–835;
  `_write_preview_examples` 838–895 (the scaffolded test text 858–893; the assertions
  890–891); `_ui_targets` 898–927; `create_ui_resources` 930–1112 (classref branch
  956–977 returning before `_write_preview_examples` at 1059; the UI-GUIDE emitter
  1060–1111, fixtures lines 1068/1072, migrate-ui paragraph 1079–1081);
  `load_validated_preview_inputs` 493–544 (fixtures outside the candidate);
  `migrate_ui` 574–720 (three-document re-stamp set 653–657).
- `src/benchweave_sdk/cli.py`: command census (`new` 66, `doctor` 93, `upgrade` 183,
  `adopt` 239, `check` 276, `inventory` 304, `check-ui` 332, `check-preset` 376,
  `migrate-ui` 422, `derive-ui` 470, `verify-ui` 552, `sync-standards` 600, `package`
  689, `timestamp` 824, `submit` 854, `preview-ui` 1269); `derive-ui`'s write set
  526–536 (no fixtures) and package-dir discovery 489–493; `main()` exit mapping
  1335–1352.
- `src/benchweave_sdk/scaffold.py` 327–425 (`create_project`; UI resources delegated
  to `presentation.create_ui_resources`); `src/benchweave_sdk/scaffold_update.py`
  (zero fixture/preview handling — upgrade cannot carry fixtures).
- `src/benchweave_sdk_server/`: `scenarios.py` 1–130 (the nine baselines via the
  host-shipped ScenarioAdapter — serve never loads author fixtures);
  `presentation.py:45` (imports `project_plot_views` only); `cli.py`/`web.py`
  (grep-level: no `load_author_fixtures`/`build_preview_model` reference anywhere in
  the server package).
- `scripts/gen_classref_fixtures.py` (full): the SDK's OWN acceptance-fixture
  generator writing `tests/fixtures/classref/` — a different fixture population;
  NOT the row's "generation code" and not exposed either (correctly so: it is a
  maintainer script, not an author surface).
- Vendored schemas: `standards/plugin-ui-preview/0.2.0/fixture.schema.json`
  (`contract_version` const `0.2.0`; `id` pattern `^[a-z][a-z0-9._-]{0,63}$` — no
  `example-` reservation: the ownership guard is the loader/command's job, not the
  schema's); `standards-lock.json` (plugin-ui-preview 0.1.1 retained → 0.2.0 active —
  axis B's fired precedent).
- Tests: `tests/test_preview_fixtures.py` (arm census 92–581);
  `tests/test_presentation_cli.py` (via L9's record, arms at 359–451);
  `tests/test_agent_assets.py` (triangulation mechanism 88–171, planted arms
  185–278, `test_real_assets_pass_triangulation` 286, presence-arm precedent from
  L8); `tests/test_getting_started.py` (registration gate 749–818);
  `tests/fixtures/scaffold_expected/ui/src/example_plugin/ui/fixtures/{normal,warning}.json`.
- Author-facing surfaces: `template/.claude/skills/benchweave-plugin-ui/SKILL.md.jinja`
  (full, 76 lines — one fixtures mention, frontmatter only); `template/AI-GUIDE.md.jinja:61`
  (a different fixtures sense); `user_guide/plugin-sdk.qmd:144–159` (the migration
  section — the new subsection's neighbor), `:195` (the guide's single
  author-fixture-adjacent mention, capture-data sense); `README.md:152,168`.
- Governance: `docs/internal/review-rubric.md` (SDK tier rules — `fixtures.py` and
  refusal paths are Tier-3 triggers); `docs/internal/invariants.md:36` (STD-4);
  `docs/internal/drift-and-obligations.md` rows 1, 2, 9 and the CI map.
- Sibling records: L8
  `.claude/deep-review/2026-10-17-issue463-row3-styleguide-discoverability-design.md`
  (full — D-L8-1/RC-L8-3 pointers, presence-arm precedent, propagation table); L9
  `.wt/l9-v3n8/.claude/deep-review/2026-10-17-issue463-row7-checkpreset-usage-design.md`
  (full — in-flight cli.py/skill adjacency, regen sequencing rule, format precedent).
- Program record: `BenchWeave/.claude/deep-review/2026-10-14-classref-logic-analyser-design.md`
  §7A (851–867) and §8 row RC-7 (898); issue #463 body + comments (rows 1–2 landed at
  L2/L3 per the landing-2/3 comment; comments end at L5).
- Version archaeology: `git show v0.12.0:src/benchweave_sdk/presentation.py` (536:
  `_preview_fixture` already presentation-side at the evidence version);
  `git show v0.12.0:src/benchweave_sdk/fixtures.py` (no example writer — the row's
  module location is wrong at both versions it could attach to).

## 12. Verdict

**BUILD, as scoped in §4.** The row's location premise is wrong in both versions it
could attach to (the generator lives in `presentation.py`, not the fixtures module)
and its blast is smaller than it reads (one consumer — the project's own test; the
delete-the-examples escape hatch), but the exposure gap is real, verified live on
`origin/main`, and doubly consequential: axis A makes every catalogue edit a hand-JSON
chore, and axis B has already fired once (plugin-ui-preview 0.1.1→0.2.0) with no
command-side remedy — `migrate-ui` is plugin-ui-family by L6's own design. The fix is
one verb-noun command in the repo's established maintenance family, reusing the
scaffold's own generator byte-for-byte (pinned by the parity arm), with an ownership
guard that makes author content structurally safe. DON'T-BUILD would leave the last
row of the slotted set open and the L8-recorded pointer (D-L8-1's "row-8/L10 slice"
framing) unanswered — this record answers it by separating the two pin families the
pointer conflated, taking the fixture half, and leaving the asset-digest half at its
recorded home.

---

## Addendum — build-time corrections (2026-10-17, builder; folded before the refute)

Two premises in §8 did not survive contact with the built tree. Both corrected with
live evidence; neither changes the mechanism.

**A1 — the end-to-end smoke step as written is unreachable.** §8 says "rename the
first observation target in the descriptor + catalogue → its pytest RED with
`preview_unknown_binding`". Neither edit can produce that refusal:

- descriptor edit → `preview_invalid_presentation: digest_mismatch: envelope:
  Descriptor bytes differ` (the envelope pins the descriptor's sha256; every
  descriptor byte change reds at the digest gate first);
- catalogue-only edit → `preview_invalid_presentation: capability_mismatch:
  targets.<new>: Target exceeds descriptor capabilities` (the presentation
  validator cross-checks catalogue targets against descriptor parameters).

The reachable stale-fixture state — and the honest reading of §3's axis A — is the
COHERENT post-edit set: descriptor parameter renamed, envelope/manifest/catalogue
re-stamped (new descriptor hash, new manifest hash, bindings and target renamed in
all three), with only `ui/fixtures/*.json` left speaking the old binding. The built
smoke scripted exactly that: project pytest `1 failed, 4 passed` with
`ValueError: preview_unknown_binding: …/ui/fixtures/normal.json: voltage` →
`regen-fixtures` exit 0 → `5 passed`. Future runs of this row's smoke use the
coherent-rename form; the two-line literal form is retired.

**A2 — AR-L10-2 arm 3 was green on main by coincidence.** §8 claims all three CLI
arms are red on main. The unknown-project arm asserts exit 2 — and on main
"No such command 'regen-fixtures'" is ALSO exit 2, so the bare exit-code assertion
passed vacuously before the command existed. The built arm adds a stderr assertion
("No such command" absent, "does not exist" present) so the check pins the
path-validation refusal itself; red on main, unchanged semantics. Second vacuous
arm caught in this set today (the first was elsewhere in the train) — the pattern:
an exit-code-only assertion over a usage-error family passes for the wrong reason
whenever two failure modes share a code. Name the failure mode, not just the code.

**Build note (not a correction):** the full battery surfaced two pins §6's table
did not name — `test_registry_census`'s exact top-level click-group set (new
member re-pinned consciously) and `test_zero_literal_gate`'s two body-imports of
`_preview_fixture` (re-pointed to its moved `fixtures.py` address; assertions
untouched). Plus one mypy annotation (`seen: set[str]`) forced by the extraction's
changed inference context.
