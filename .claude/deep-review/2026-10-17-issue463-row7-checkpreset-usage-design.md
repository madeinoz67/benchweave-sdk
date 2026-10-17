# L9 design — issue #463 row 7: `check-preset` usage errors

**Date:** 2026-10-17
**Issue:** madeinoz67/benchweave#463 row 7 (single issue stream; SDK-side work, no
SDK-side issue by design)
**Program linkage:** classref train,
`.claude/deep-review/2026-10-14-classref-logic-analyser-design.md` §7A slot L9 / §8 row
RC-7. This record is L9's own design record; the program record does not scope it.
Siblings: L6 (#460, landed), L7 (#461, landed), L8 (#463 row 3, in flight — §5 names the
adjacency).
**Verdict:** **BUILD, re-scoped — with the row's premise corrected.** The row's literal
claim ("a call without them reads as preset failure, not as a usage error") is false,
measured at both the evidence version (v0.12.0) and current `origin/main`: omitting
either flag is already a first-class click usage error, exit 2, before any validation
runs (§2). What survives of the row is a real, adjacent defect the premise was pointing
at: `--firmware` is `required=True` on `check-preset` while every other surface —
`check-ui`, the SDK API, the plugin-ui gate, the standalone server authoring helper —
treats firmware `None` as a first-class value (the #444 commissioned posture), and the
CLI flag forecloses that designed posture. The fix is one CLI-surface change: make
`--firmware` optional on `check-preset`. `--settings-schema` stays required (§4.3).
Design-only leg: no implementation code in this record.

---

## 1. Pre-flight (#181 R2)

- SDK checkout `main` at `5784959`; `git fetch origin` run. Design worktree
  `.wt/l9-v3n8` off `origin/main` at `7e7337e` (post-#461/#496 merges). `git worktree
  list` walked before any work; `.wt/l7-*`, `.wt/l7b-*`, `.wt/l8-qz7f`, `.wt/l8b-h2v8`
  belong to live sibling lanes and were not touched. `cli.py` is this lane's alone
  (L8 owns the UI-GUIDE emitter and templates); the one adjacent file both lanes'
  fixtures live near is named in §5.
- Remote branches touching the planned paths (`src/benchweave_sdk/cli.py`,
  `template/.claude/skills/benchweave-plugin-ui/SKILL.md.jinja`,
  `tests/fixtures/scaffold_expected/**`, `tests/test_presentation_cli.py`): none beyond
  the train's own landed lanes (`feat/issue460-migrate-ui`,
  `feat/issue463-row3-styleguide-discoverability` — L8's, in flight) and
  `fix/issue461-upgrade-content-boundary` (landed as #174). No open SDK PRs at
  pre-flight (`gh pr list --repo madeinoz67/benchweave-sdk --state open` returned
  empty). No rival design on the check-preset surface.
- L8's design record (`2026-10-17-issue463-row3-styleguide-discoverability-design.md`)
  exists only in the unpushed `.wt/l8*` worktrees; per the dispatching brief it was not
  read and is not relied on. The dispatch brief's claim that
  `docs/internal/drift-and-obligations.md` row 9 cites `check-preset` does not hold in
  either repo's committed drift doc (checked both); the obligations that DO bite are
  named in §5.
- GORTEX UNAVAILABLE TO SUBAGENT — the probe (`read` on a repo-prefixed path) refused
  with checkout-discovery-unavailable (issue #831 class). Native tools used throughout,
  per the dispatching brief. One later `grep` was hook-blocked and re-run with a
  regex-metachar pattern; no graph access was granted at any point.

## 2. What the command actually does today (traced, then measured)

**Trace.** `check-preset` (`src/benchweave_sdk/cli.py:376-422`) declares
`--descriptor`, `--settings-schema` and `--firmware` each `required=True`. Click
enforces required-ness at **parse time**, before the command body — and therefore
before `_domain_errors` (which wraps only `ValueError/OSError/RuntimeError` raised
inside the body) and before any `validate_preset` call. A missing flag can never reach
the report renderer; there is no code path from omission to a preset-validation
finding. This shape is not new: the command's introducing commit `7b27a31` (argparse,
in v0.12.0) declared the same three options `required=True`, and the click migration
`e3b277c` (also in v0.12.0) preserved them.

**Measurement** (both run in this design session, output to file, exit code read
unpiped per the evidence rules):

| run | output | exit |
|---|---|---|
| v0.12.0, omit `--settings-schema` | `Usage: …` / `Error: Missing option '--settings-schema'.` | 2 |
| origin/main `7e7337e`, omit `--firmware` | `Usage: …` / `Error: Missing option '--firmware'.` | 2 |

So the row's diagnosis is wrong in both versions it could attach to: the omission case
is a usage error — the exact class the row asks for — and has been since the command
existed. The issue's evidence section cites fresh-scaffold serving at 0.12.0 for the
inventory generally; row 7 carries no run evidence of its own, and the observed
record here is that the claim does not reproduce.

**What the row may have been reaching at.** Two nearby real behaviors, both traced:

1. **The flag burden itself.** The row's first clause — "`check-preset` requires
   `--settings-schema` and `--firmware`" — is true and is a genuine authoring burden
   under one policy: for a `firmware_policy: "commissioned"` descriptor the descriptor
   declares no firmware list, so an agent cannot ground `--firmware` in anything
   independent — it can only echo a value from the preset's own authored
   `supported_firmware` list. That is circular attestation; the designed honest input
   is `None`.
2. **A supplied-but-wrong value DOES read as preset failure.** At 0.12.0 (pre-#444
   gate), a commissioned-descriptor author who did supply `--firmware` hit gate
   conjunct 3 and got `incompatible_firmware` + exit 1 — a preset failure for a call
   the flags were "correctly" supplied to. #444 fixed the gate (landed in the plugin-ui
   versions current main serves); the CLI's required-ness was left untouched by that
   fix.

## 3. The class distinction is already settled — and correctly (design question 4)

The CLI has a convention, it is click's, and it is applied consistently:

- **exit 2 = usage error**: click's `UsageError` family (`MissingParameter`,
  `BadParameter`) fires at parse time; `main()` (`cli.py:1335-1353`,
  `standalone_mode=False`) returns `exc.exit_code`. The convention is not accidental —
  `preview-ui`'s `--scenario` shim deliberately raises `BadParameter` to match "exit 2,
  the same usage-error family serve's Choice produces" (`cli.py:1321-1327`), and the
  `[server]`-extras refusal also exits 2.
- **exit 1 = validation/runtime failure**: `_render_report` raises
  `click.ClickException("Presentation validation failed.")` when `report.valid` is
  false (`cli.py:312-330`); `_domain_errors` maps the STD-4 snake_case refusal
  `ValueError`s to `ClickException` the same way.

**STD-4 is not engaged.** STD-4 (`docs/internal/invariants.md:36-66`) governs the
snake_case refusal prefixes on semantic refusals — a different family from parse-time
usage errors. A missing option should not borrow a validation prefix, and no new
prefix is needed: click's own error is the usage-error contract here. Introducing an
STD-4 prefix for a missing flag would be a contract change with no consumer. This
design adds no refusal path and no prefix.

**One class question the fix does have to answer** (§4.2): under `listed` policy an
omitted `--firmware` post-change produces `incompatible_firmware` + exit 1 —
validation class, not usage. That is correct, and the reason is structural: post-#444,
`None` is a meaningful *value* (the "cannot be decided from the descriptor" offline
posture), not a missing argument. An invocation that omits an optional, meaningful
value is well-formed; the undecidable judgment it yields is a finding, not a usage
error. The gate already says exactly this (Rule 2,
`standards/plugin-ui/contracts.py:285-293`), pinned at API level by
`test_listed_policy_missing_firmware_refuses` and
`test_commissioned_policy_admits_missing_firmware`
(`tests/test_presentation_cli.py:384-451`).

## 4. The decision

### 4.1 Make `--firmware` optional on `check-preset` — default `None`

Evidence, each item verified this session:

- **The gate admits `None` by design.** Post-#444 Rule 2: `firmware is None` is
  admissible exactly under `commissioned` policy (the honest offline posture; the
  apply-time established-firmware gate governs). Rule 3 keeps a descriptor-declared
  list enforced even under commissioned (None is not a member).
- **Every surface except this CLI treats `None` as first-class.** The SDK API types it
  (`presentation.validate_preset(..., firmware: str | None)`); the API tests exercise
  it (`test_presentation_cli.py:384`, `tests/test_classref_effective.py:122` passes
  `firmware=None`); `check-ui`'s `--firmware` is optional (`cli.py:50`); the
  standalone server's `preset_check` resolves "explicit → session-established →
  descriptor-declared" (`benchweave_sdk_server/authoring.py`); the gateway composes
  with `supported_firmware[0]` else `None` (#444 record §1.2). `check-preset` is the
  odd surface out, and its `required=True` makes the #444-designed posture
  **unreachable from the CLI** — a commissioned-policy author cannot validate
  structurally without naming a firmware the descriptor never declares.
- **#444 left the door open at exactly this address.** Its deferral D3
  ("`check-ui --firmware` convenience resolution… Home: SDK CLI. Reopen: author
  ergonomics feedback; the `None` posture already validates structurally") names the
  SDK CLI as the home for firmware-flag ergonomics. This design is that deferral's
  `check-preset`-side sibling, on the classref-train author-ergonomics trigger the
  train itself supplies (row 7 IS the author-ergonomics feedback).
- **A02 is not amended.** `None` derives nothing and assumes nothing — it asserts the
  absence of an offline-decidable firmware judgment, which is the evidence-honest
  input for a commissioned descriptor. Commissioning values remain authored; A12's
  scaffold-refusal line is untouched (its test already runs at `firmware=None`).

### 4.2 Semantics after the change

| invocation | commissioned policy | listed policy |
|---|---|---|
| `--firmware v` supplied | unchanged: gate Rules 1+2+3 as today | unchanged |
| omitted (`None`) | passes the firmware gate (Rules 1–3 all skip or admit); schema/hash/settings checks proceed; exit 0 with the envelope note when otherwise valid | `incompatible_firmware` finding, exit 1 — the "cannot decide offline" verdict |

The pass message and note path (`resolve_preset_action`) are unchanged. No gate byte
moves; no vendored file moves; **no plugin-ui version bump** — the flag is SDK CLI
surface, not the vendored validator.

### 4.3 `--settings-schema` stays required — the row's "should it be required at all" question, answered no-change

Discovery/defaulting is impossible or worse, structurally:

- **The preset document cannot name the file.** Its `settings_schema` reference
  carries a URN `id` and the schema's `sha256` — no path
  (`tests/fixtures/setpoint_plugin/.../presets/steady.json`; enforced at
  `contracts.py:308-311`). A URN is not a filesystem location; there is nothing to
  discover from.
- **Two scaffold conventions coexist.** Base scaffold:
  `src/<package>/config/settings.schema.json` (README:172). With-UI derived layout:
  `ui/settings/configure.schema.json` (`classref.py:531`). Any single default is the
  wrong path for the other convention's projects.
- **A wrong default fails closed but misleadingly.** The sha256 pin means a
  discovered-wrong schema can never silently validate — it fails the hash check as a
  validation finding, exit 1. That is precisely the row's complaint transposed: a
  file-resolution mistake dressed as a preset failure. The missing-option usage error
  (exit 2, naming the flag) is the strictly better failure shape, and it already
  exists.

Revisit only if the corpus ever lets a preset carry its schema's path (a preset
contract change — plugin-ui's home, not the CLI's).

## 5. Blast radius (design question 3)

| surface | effect | action |
|---|---|---|
| `src/benchweave_sdk/cli.py` `check-preset` | the option and signature (`firmware: str \| None`) | edit (this lane's file alone) |
| `template/.claude/skills/benchweave-plugin-ui/SKILL.md.jinja:32-35` | documents `--firmware <version>` as unqualified | one-line edit: mark optional + one clause for the commissioned posture |
| `tests/fixtures/scaffold_expected/{base,ui}/.claude/skills/benchweave-plugin-ui/SKILL.md` | rendered mirror of the template | regenerate (obligation 2: scaffold output is an interface — say so in the PR) |
| `tests/test_presentation_cli.py` | the #444 section (lines 359-451) is the home for the new CLI arms | add RED-first tests (§7) |
| `tests/test_agent_assets.py` | triangulates subcommand names, not flags | no edit expected; must stay green (AR-5) |
| README.md:172/209, `AI-GUIDE.md`, `UI-GUIDE.md`, getting-started walkthrough, troubleshooting | name `check-preset` without flag detail (or are check-ui walkthroughs) | no change |
| plugin-ui corpus READMEs (gateway, digest-frozen, all versions) | example invokes WITH `--firmware 1.0.0` | stays valid — an example may supply an optional flag; no corpus motion |
| gateway vendored `contracts.py` twin | not touched (no gate change) | none |
| standalone server `preset_check` | already optional-resolution semantics | none |
| SDK `docs/internal/invariants.md` STD-4 | no new refusal path/prefix | none |

**L8 adjacency (dispatcher note):** L8b owns scaffold-docs surfaces in flight. The
files this design touches are disjoint from UI-GUIDE/AI-GUIDE, but both lanes'
changes land in the same `tests/fixtures/scaffold_expected/` trees — sequence the two
lanes' fixture regenerations (regenerate after both code changes are in, or regenerate
twice accepting a mechanical second diff), never concurrently in one tree.

**Exit codes / refusal text:** no existing exit code or message changes for any
invocation that names all flags today. The only behavior change is the omission case
moving from exit 2 (missing option) to running the validation. Nothing downstream
keys on `check-preset`'s omission exit code (grep over both repos: the command is
cited by name in docs/skills/tests only; the drift docs' check-preset citation claimed
in the dispatch brief does not exist in either committed drift doc).

## 6. Minimal first slice

1. `cli.py`: `@click.option("--firmware")` on `check-preset` (drop `required=True`),
   signature `firmware: str | None`, help text gains the None posture ("omit to
   validate structurally; under the listed policy a firmware value is required to
   judge compatibility"). Pass-through to `validate_preset` — no other code change;
   the API already types `str | None`.
2. RED-first tests in `test_presentation_cli.py`'s #444 section, through the CLI
   runner (the existing arms are API-level only): commissioned + omission → exit 0
   (RED today: exit 2); listed + omission → exit 1 with `incompatible_firmware`; both
   policies + supplied `--firmware` → byte-identical to today; `--settings-schema`
   omission → still exit 2 `Missing option '--settings-schema'.`
3. Template skill line + fixture regeneration (§5), one line.

## 7. Acceptance rule (pre-committed) and falsifier

Written before any build. `$SDK` = the built checkout's `benchweave-sdk` entry point;
fixtures = the #444 commissioned/listed pairs already in `test_presentation_cli.py`,
materialised as files for the CLI arms.

- **AR-1 (RED on main, green post-change):** `check-preset <commissioned preset>
  --descriptor <commissioned descriptor> --settings-schema <schema>` (no `--firmware`)
  exits **0** and prints `Offline presentation checks passed`. On `origin/main`
  `7e7337e` the same command exits **2** with `Error: Missing option '--firmware'.`
  (captured this session; the RED is the usage gate itself).
- **AR-2:** the same omission against a **listed**-policy project exits **1** with an
  `incompatible_firmware` finding row.
- **AR-3 (the row's requested behavior stays):** `check-preset <preset> --descriptor
  <d>` (no `--settings-schema`) exits **2** with `Error: Missing option
  '--settings-schema'.` — byte-identical to today.
- **AR-4 (no regression):** with `--firmware` supplied, exit code and full output are
  identical pre/post change for both policies (4/4 pinned arms).
- **AR-5:** `tests/test_agent_assets.py` green; the scaffold-fixture diff is exactly
  the one skill line in each of the two fixture trees.
- **Falsifier:** any AR observed otherwise; any `check-ui` firmware-semantics change
  in the same diff; any new snake_case refusal prefix in the diff (STD-4 breach); a
  plugin-ui version bump appearing in the diff (would mean the slice leaked into the
  vendored gate — wrong by construction).

## 8. Deferrals (each with home + reopen trigger)

- **D1 — a default/discovered `--settings-schema`.** Rejected on structure (§4.3),
  deferred as a corpus question. Home: plugin-ui corpus (only a preset-carried schema
  path could make discovery sound, and that is a preset-contract change). Reopen: a
  corpus/owner request to carry the schema path in the preset document, or the class
  sweep (L11–L21) minting a third schema location that forces a unification ruling.
- **D2 — user-guide prose for the None posture.** The skill (agent-facing) and
  `--help` carry it from the slice; the human guide's check-preset text is link-only
  today. Home: `user_guide/plugin-sdk.qmd` via the `document-writer` agent (STE
  register). Reopen: author ergonomics feedback — the same trigger family as #444's
  D3.
- **D3 — #444's own D3 (check-ui convenience resolution).** Untouched here; stays
  deferred at its original home and trigger.

## 9. Review tier and Step-1 keyword scan (#254)

Design-time call: **Tier 2.** The expected diff touches no `standards/` path, adds no
`sha256`/`hashlib`-bearing code (a value passes through; no digest computation is
added or moved), advances no submodule pointer, and introduces no new refusal path.
The template/fixture change is an interface change under obligation 2 and is disclosed
as such. The builder re-runs the Step-1 keyword scan over the actual diff text per the
rubric; if the fixture regeneration surfaces digest literals in diff context, that is
fixture bytes moving, not digest-bearing logic, and the scan records it as such.

## 10. Evidence (paths read, all this session)

- `src/benchweave_sdk/cli.py` (worktree `.wt/l9-v3n8` @ `7e7337e`): command
  definition 376-422; `_domain_errors` 29-37; `_presentation_options` 40-57;
  `_render_report` 312-330; `--scenario` shim 1295-1353.
- `src/benchweave_sdk/presentation.py` 255-340 (`validate_preset`,
  `resolve_preset_action` — both `firmware: str | None`).
- `src/benchweave_sdk/standards/plugin-ui/contracts.py` 283-311 (the post-#444 gate,
  Rules 1-3, and the settings-schema sha256 pin).
- `tests/test_presentation_cli.py` 359-451 (the #444 API-level arms);
  `tests/test_classref_effective.py:122` (A12 arm at `firmware=None`);
  `tests/test_agent_assets.py` (triangulation mechanism — subcommands, not flags);
  `tests/test_cli_frameworks.py:14`, `tests/test_registry_census.py:91`
  (name-registration only).
- `template/.claude/skills/benchweave-plugin-ui/SKILL.md.jinja` 32-35;
  `tests/fixtures/scaffold_expected/{base,ui}/.claude/skills/benchweave-plugin-ui/SKILL.md`;
  `tests/fixtures/scaffold_expected/{base,ui}/AI-GUIDE.md`;
  `tests/fixtures/scaffold_expected/ui/UI-GUIDE.md`;
  `tests/fixtures/setpoint_plugin/src/setpoint_demo/config/presets/steady.json`.
- `README.md` 172, 209; `user_guide/plugin-sdk.qmd` 142; `user_guide/getting-started.qmd`
  178-205; `user_guide/troubleshooting.qmd` 62-71.
- Gateway repo (read-only): `standards/plugin-ui/{0.1.0,0.2.0,0.3.1,0.4.0}/README.md`
  (check-preset example + lane-1 prose);
  `docs/internal/drift-and-obligations.md` (no check-preset row — premise of the
  dispatch brief corrected);
  `.claude/deep-review/2026-10-12-issue444-commissioned-preset-firmware-design.md`
  (§1.2 surface table, §4 deferrals D1-D5);
  `.claude/deep-review/2026-10-14-classref-logic-analyser-design.md` §7A/§8;
  `.claude/deep-review/2026-10-17-issue460-ui-contract-migration-design.md` (format
  precedent).
- `docs/internal/invariants.md` 25-66 (STD-2/3/4/5);
  `docs/internal/drift-and-obligations.md` obligations 1-2 (guide registration,
  scaffold interface).
- Measured runs: v0.12.0 via `git archive` extraction (`/tmp/bw-012-l9`), main via
  the worktree venv — outputs `/tmp/l9-out-012.txt`, `/tmp/l9-out-main-fw.txt`, exit
  codes 2/2 read unpiped.
- Git history: `7b27a31` (introduction, argparse, required), `e3b277c` (click
  migration), tag ancestry verified (`7b27a31` and `e3b277c` both ancestors of
  `v0.12.0`).
