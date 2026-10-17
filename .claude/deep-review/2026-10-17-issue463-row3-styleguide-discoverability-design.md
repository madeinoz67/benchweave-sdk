# L8 — issue #463 row 3: custom-styleguide discoverability (design record)

Program record: `BenchWeave/.claude/deep-review/2026-10-14-classref-logic-analyser-design.md`
§7A slot L8 = §8 row RC-7 (D-8): "#463 row 3 (custom-styleguide discoverability)".
Gateway issue #463 row 3: "The custom local styleguide is undiscoverable. The
`preview.css` override (assets module: fixed asset name, 64 KB cap, digest pin,
refusal prefix) appears in no plugin-facing document. `UI-GUIDE.md`, `AI-GUIDE.md`
and the plugin-ui skill have zero mentions." End state (issue Request): "the
styleguide override is documented where authors read."

Design branch: `design/l8-issue463-styleguide-docs` (worktree `.wt/l8-qz7f`).
Design only — no implementation code in this landing's design pass.

## 1. Pre-flight (#181 R2)

- `git fetch origin` run. SDK `origin/main` at `5784959` (merge of #173; L6's
  `feat/issue460-migrate-ui` merged at `908acce`; L7's content-boundary fix
  `5613864` also on main).
- Remote branches touching the paths this design changes (`template/**`,
  `src/benchweave_sdk/presentation.py`, `tests/test_agent_assets.py`,
  `tests/fixtures/scaffold_expected/**`): none. The only live remote branch,
  `origin/fix/issue461-upgrade-content-boundary`, is BEHIND main (its diff vs
  main is the #496 agent-pin files only). Its LOCAL design-tree counterpart
  (`.wt/l7-m4t8`, `6136240`) touches `cli.py`, `scaffold.py`,
  `scaffold_update.py`, `tests/test_scaffold_update.py`,
  `user_guide/plugin-sdk.qmd` — no overlap with this slice's paths except the
  user guide, which this design does NOT change (see §6 RC-L8-2).
- Gateway repo (`madeinoz67/benchweave`): zero open PRs. Recent merges: #497
  (agent pins), #495/#494 (row-12 timing arms), dependabot batch. No rival
  docs/styleguide work in flight.
- Gortex: probed once per dispatch mandate — `mcp__gortex__read` on
  `benchweave-sdk/src/benchweave_sdk_server/assets.py` returned the checkout
  discovery error (issue #831 class). GORTEX UNAVAILABLE TO SUBAGENT; all
  evidence below is native reads.

## 2. The mechanism, verified from source (not from the row)

`src/benchweave_sdk_server/assets.py` (standalone checkout, main):

- Fixed asset name: `PREVIEW_OVERRIDE_ASSET = "preview.css"` (line 47). A
  manifest `assets[]` row is matched on `asset.get("path")` EXACTLY equal to
  this name (`preview_override_bytes`, line 103).
- Size cap: `PREVIEW_OVERRIDE_MAX_BYTES = 64 * 1024` — 64 **KiB** (line 50),
  not "64 KB" as the row says; the refusal text and the user guide both say
  KiB. Oversize refuses (lines 111–115).
- Digest pin: the **manifest row's own `sha256`**, re-verified against the
  bytes on disk at serve time (lines 116–121). This is not a host-side digest
  list — it is the plugin-ui manifest schema's pin (`ui-manifest.schema.json`
  `$defs/asset` requires `id`/`path`/`sha256`, `additionalProperties: false`)
  re-checked on every render and every asset fetch. The docstring notes a
  wrong-shaped `sha256` cannot reach this comparison (load-time schema
  refuses it first).
- Refusal prefix: `PREVIEW_OVERRIDE_REFUSED = "standalone_preview_override_refused:"`
  (line 54). Three refusal cases, each naming `preview.css` and the reason:
  unreadable, exceeds the 64 KiB cap, bytes differ from the manifest pin.
- Serving shape (`web.py`): the override route is its ONLY serve point
  (lines 2196–2210); refusal answers 403 plain-text carrying the prefix;
  undeclared answers 404. Pages link the override only when the bytes verify
  at render time; a REFUSED override is visible as the marker attribute
  `data-bw-override-refused` on the html element while the default tokens
  render (`_preview_override_state`, lines 741–755, fold F3 — no silent
  no-op). The override loads AFTER the token stylesheets, so it wins at equal
  CSS specificity (user guide states the (0,2,0) lanes-figure example).
- Scope: preview-host-only. The gateway never reads a plugin's asset tree.

Every refusal names the file it wants and why. Once an override is DECLARED,
every failure mode is self-describing. The block is upstream of that: nothing
an author or their agent reads at the point of work says the feature exists.

## 3. Surface census — where authors actually read

| Surface | Carried by | Override mention today | Reaches existing projects via |
|---|---|---|---|
| `UI-GUIDE.md` (project root, `--with-ui`) | `presentation.py:1060–1095` emitter (`create_ui_resources`) | generic `assets/` tree line only | **nothing** — written once at `new --with-ui`; neither `upgrade` (copier) nor `derive-ui` rewrites it |
| `AI-GUIDE.md` | `template/AI-GUIDE.md.jinja` | generic "declared assets" sentence (line 23) | `upgrade` (copier template member, not skip-listed) |
| plugin-ui skill | `template/.claude/skills/benchweave-plugin-ui/SKILL.md.jinja` | zero | `upgrade` (managed footer says so) |
| User guide | `user_guide/plugin-sdk.qmd:169–203`, section "The plugin stylesheet override (preview.css)" | **complete** — row shape, cap, refusal, cascade/specificity, theme, marker | published site |
| README | line 283 | one paragraph (row shape) | README |
| CLI help | `cli.py` preview-ui command | none (appropriate — usage help, not feature docs) | — |
| plugin-ui 0.4.0 schema | `ui-manifest.schema.json` | generic `assets[]`; no `preview.css` semantics | — |

**Correction to the row's summary.** "Appears in no plugin-facing document" is
false as written: commit `c08bf04` (2026-10-13, "docs(preview): document the
local override, theme parity, and waveform-first page") landed the full
user-guide section and the README paragraph — one day before the issue was
directed, and it is in v0.12.0, the version the issue cites. The issue's own
evidence section scoped its grep correctly to the three scaffold-carried
surfaces, and there the zero-mention claim is true (re-verified on main: zero
`preview.css` tokens in the UI-GUIDE emitter string, the AI-GUIDE template,
and the plugin-ui skill template).

So the real defect is narrower and sharper than the row: **the published
documentation exists and is thorough, but the three surfaces open at the point
of work — the project's UI-GUIDE.md, AI-GUIDE.md, and the plugin-ui skill the
author's agent loads — are silent, and nothing in them points to the published
section.** The skill's only pointer is `section "Local UI preview (simulated)"`
(qmd:138); the override docs sit 31 lines deeper as its subsection (qmd:169),
and the skill gives no signal the subsection exists. A fact documented only
where the author is not looking is the bug restated — the row already knew
this; the census says the fix is routing, not writing.

## 4. Is the row documented-only? (mechanical check)

- Serve-time refusals name file + reason; the refused state is marked on the
  page. Not a block.
- `check-ui` is asset-blind: `src/benchweave_sdk/validation.py` contains zero
  asset handling — a declared `assets[]` row passes `check-ui` whether or not
  `preview.css` exists or the pin is right; the author's first feedback is the
  serve-time refusal. This is a real gap, but it is a VERIFICATION gap that
  bites only AFTER discovery — it does not block discovering the feature.
  Deferred (D-L8-1) with the row-8/L10 command-exposure slice as its natural
  home.
- No command computes the digest for the author (hand `sha256sum`); the
  guide's example shows the row shape but not the command. Friction, not a
  block; deferred (D-L8-2).

**Verdict: the row is documented-only.** No mechanical fix is required to
unblock discovery; the mechanical surroundings (self-describing refusals,
visible marker) are honest once the feature is found.

## 5. Scope decision — scaffold-output change, published-docs change, or both

- **Published-docs change: nothing to build.** `c08bf04` already shipped the
  complete section. Building more published docs adds nothing an author reads
  at the point of work. (Optional one-sentence digest-HOW: RC-L8-2, recommend
  defer.)
- **Scaffold-output change: this is the slice.** UI-GUIDE.md emitter +
  AI-GUIDE template + plugin-ui skill template gain the mention, wired by
  citation to the already-complete published section.

What the scaffold-output route costs, paid once:

1. **SRF-1 interface change.** Drift row 2: the generated tree changes; the PR
   body must disclose it as an interface change. Downstream diff scope is
   asymmetric and must be stated in the PR: existing projects diff AI-GUIDE.md
   and the five skills at their next `benchweave-sdk upgrade`; UI-GUIDE.md
   changes reach NEW scaffolds only (no refresh path exists — §3 table).
2. **R-2 fixture regen**, both arms, in-PR (the sdk lane's byte-parity test
   renders the current tree and compares; a template/emitter change without
   the regen reddens). Procedure: the manual procedure documented in
   `tests/test_scaffold_copier.py`'s docstring, including the
   `_expected_answers` canonical-pin rewrite for the answers file.
3. **R-5b posture change.** The plugin-ui skill currently sits in
   `CODE_FREE_SKILLS` (`tests/test_agent_assets.py:74–78`). Citing the refusal
   prefix in the skill is a code citation, which the checker then verifies
   against BOTH halves — and both halves exist today: the string literal in
   `assets.py:54` (the anchored source regex `[\"']code:` matches the literal
   that begins with the prefix) and the backticked
   `` `standalone_preview_override_refused:` `` at `user_guide/plugin-sdk.qmd:185`.
   The set's own comment names this move: "adding a code citation to one of
   these skills is a deliberate design change that updates this set
   consciously." L8 is that deliberate change. The §2.2 rationale (the
   plugin-ui lane refuses through the schema/validator surface) predates the
   override surface, whose refusal IS a named prefix — the rationale never
   covered it. Net effect: the existing triangulation mechanism starts PINNING
   the skill↔source↔guide wiring at test time, for free.
4. **Tier 3 review** (Step-1 keyword scan): the prose names `sha256` by
   construction → mandatory adversarial refute + full battery.

Why all three scaffold surfaces and not just the skill: the three surfaces are
the author's, the agent's, and the project-guide's view of the same fact. One
fixture regen pays for all three; splitting them across landings pays the
SRF-1 disclosure cycle three times for no isolation benefit (no behavior rides
on the prose).

## 6. The minimal first slice

**In scope:**

1. `src/benchweave_sdk/presentation.py` UI-GUIDE emitter (lines 1060–1095):
   one short STE paragraph after the existing manifest-asset-paths sentence
   ("Manifest asset paths are relative to ui/..."). Facts it must carry: a
   manifest `assets[]` row with `path` exactly `preview.css`; the row's
   `sha256` pin re-verified at serve time; the 64 KiB cap; preview-host-only
   (the gateway never serves it); the refusal prefix
   `standalone_preview_override_refused:` and the page marker
   `data-bw-override-refused`; pointer to the user-guide section "The plugin
   stylesheet override (preview.css)".
2. `template/AI-GUIDE.md.jinja`: one sentence in the existing with-ui assets
   paragraph (lines 20–27, already conditional-framed "With --with-ui..."):
   a stylesheet named `preview.css` restyles the preview pages; see UI-GUIDE.md
   and the user-guide section. No new jinja conditional.
3. `template/.claude/skills/benchweave-plugin-ui/SKILL.md.jinja`: a short
   section "Restyle the preview pages (optional)" carrying: the manifest row
   shape (`path` exactly `preview.css`, `sha256` pin), the 64 KiB cap, the
   refusal prefix as a cited code, and the heading citation
   `section "The plugin stylesheet override (preview.css)"`. Capped at the
   five facts + two citations (~6–8 STE sentences) — skills are agent-loaded;
   size is a cost.
4. `tests/test_agent_assets.py`: remove the plugin-ui skill from
   `CODE_FREE_SKILLS` (with the conscious-change comment updated); add the
   three presence arms of AR-L8-1.
5. Fixture regen, both arms, per the documented procedure; PR body discloses
   the SRF-1 interface change and the downstream-diff scope (§5 item 1).
6. **Register:** the three surfaces are published into author projects —
   ASD-STE100 register applies; the build leg dispatches the `document-writer`
   agent for the prose. This design record stays engineering register.

**Row calls for the owner** (defaults run as recommended; redirect window open
until the first PR opens):

- **RC-L8-1 — fold L6's D5 into this slice.** L6 deferred "the generated
  UI-GUIDE.md naming `migrate-ui`" with reopen trigger "the next
  scaffold-output slice". L8 is that slice; the fold costs one sentence and
  zero extra regen, and refusing it costs a second full SRF-1 cycle later.
  Recommend **FOLD** (UI-GUIDE's version-artifacts sentence gains the
  `benchweave-sdk migrate-ui` name; the command is registered, so nothing
  reddens). If declined, D5 stays with its recorded home and trigger.
- **RC-L8-2 — user-guide digest-HOW sentence** (name `sha256sum` /
  `shasum -a 256` in §"The plugin stylesheet override"). Recommend **DEFER**
  (D-L8-2): the published side is complete for the row's end state; the
  sentence is usability polish on a surface this slice does not otherwise
  touch (and L7's tree has uncommitted work in that file — a collision risk
  with no offsetting need).
- **RC-L8-3 — fold check-ui asset-pin verification (D-L8-1) now.** Recommend
  **DEFER**: row 3 is discovery; verification is row 8/L10's natural companion
  (a command that computes/re-pins digests), and folding it would grow a docs
  slice into a validator change.

**Out of scope by construction:** any `assets.py`/`web.py` behavior change;
any schema change; any user-guide/README change (unless RC-L8-2 is accepted);
any check-ui behavior; any UI-GUIDE refresh mechanism for existing projects
(noted as a structural fact in §3, not repairable by this row).

## 7. Deferrals (id / deferred / home / reopen trigger)

| id | deferred | home | reopen trigger |
|----|----------|------|----------------|
| D-L8-1 | `check-ui` verification of declared `assets[]` pins against bytes (today check-ui is asset-blind: a wrong pin passes offline and refuses only at serve) | follow-up issue on the gateway tracker, or fold into L10 (row 8, fixture/command exposure) when that design runs | a tracker report of a green `check-ui` followed by a serve-time `standalone_preview_override_refused:` digest refusal; or L10's design pass |
| D-L8-2 | the digest-computation command in the user-guide override section | same follow-up issue, or the next published-docs pass | an author ask on the tracker for how to compute the pin; or D-L8-1's slice (its verification output would state it) |
| D-L8-3 | a refresh path for UI-GUIDE.md in EXISTING projects (no mechanism writes it after `new --with-ui`; skill + AI-GUIDE mentions do propagate via `upgrade`) | follow-up issue (its own design — candidates: upgrade-time rewrite, or fold into the UI-GUIDE into the copier template) | an upgrading author reporting the old UI-GUIDE lacking the override docs; or the next scaffold-refresh design |
| D-L8-4 | L6's D5, ONLY IF RC-L8-1 is declined | unchanged (L6's recorded home and trigger) | L6's trigger, unchanged |

## 8. Invariant and cross-surface impacts

- **SRF-1**: fixture regen + PR-body interface disclosure; `.copier-answers.yml`
  itself unchanged (no answers-shape edit; the regen rewrites `_commit` to the
  canonical pin per the documented procedure).
- **SDK drift row 1 (CLI-visible behavior)**: NOT triggered — no command, flag,
  or output shape changes. (RC-L8-1's fold names an EXISTING registered command
  in generated prose; no CLI surface moves.)
- **SDK drift row 2 (scaffold output)**: fully walked — template, emitter,
  fixture, disclosure (§5).
- **SDK drift row 9 (agent-asset claims)**: the new citations activate R-5b
  for the plugin-ui skill; `CODE_FREE_SKILLS` shrinks by one, consciously; the
  checker's disclosed residuals (register, gloss accuracy) unchanged — review
  keeps those.
- **STD-4**: untouched — the slice CITES an existing refusal prefix; it mints
  nothing.
- **SRF-2, STD-1, STD-5, TWO-1**: untouched. No release is cut by this slice;
  when the train next cuts an SDK version, the standing order (SDK PR → merge
  → release-cut → gateway pointer) applies unchanged, and `make release-cut`
  performs the fixture regen mechanically at that point (occurrence-validated).
- **CI cost**: new arms ride the existing `sdk` lane (offline, unit-level); no
  new lane.

## 9. Review tier

**Tier 3** — Step-1 keyword rule: the expected diff text contains `sha256`
(the prose and the test arms name the pin) by construction. Mandatory
adversarial refute (G6) before the PR; full battery before push. No Tier-3
path rule fires (no `standards/` byte, no persisted-format surface, no schema
file) — the tier buys the refute, which is what a cross-surface prose change
wants anyway.

## 10. Measurable proof and the pre-committed acceptance rule

The proof is the registration the issue explicitly asked for ("a test
asserting the generated guide mentions the asset name and the cap... a
registration test that fails when the sentence is dropped"), made real on this
tree, with denominators and both kill directions.

**AR-L8-1 — presence arms (new, in `tests/test_agent_assets.py`; it already
owns agent-asset content obligations and reads TEMPLATE + FIXTURES):**

1. `test_plugin_ui_skill_documents_the_preview_override` — the skill template
   contains all of: `preview.css`, `64 KiB`, `sha256`, the backticked
   `` `standalone_preview_override_refused:` ``, and the heading citation
   `section "The plugin stylesheet override (preview.css)"`.
2. `test_ui_guide_documents_the_preview_override` — the `ui` arm's committed
   fixture `tests/fixtures/scaffold_expected/ui/UI-GUIDE.md` contains
   `preview.css`, `64 KiB`, and `sha256` (R-2 parity carries the same
   assertion to the emitter by construction).
3. `test_ai_guide_names_the_preview_override` — BOTH arms' `AI-GUIDE.md`
   fixtures contain `preview.css`.

- **RED (denominator: 3 arms)**: all three fail on today's main — verified in
  this design pass: zero `preview.css` tokens in the emitter string, the
  AI-GUIDE template, and the plugin-ui skill template. The build shows the
  three REDs before writing prose (docs-row RED-sanity: the collected count is
  3, not a silent `no tests ran`).
- **GREEN**: prose + regen turns all three green.

**AR-L8-2 — triangulation (existing mechanism, extended by the set change):**
`test_real_assets_pass_triangulation` and `test_prose_refusal_skills_cite_no_codes`
(with plugin-ui removed from `CODE_FREE_SKILLS`) stay green — the skill's new
code and heading citations resolve at test time against `assets.py:54`'s
string literal and `plugin-sdk.qmd`'s backticked prefix (line 185) and heading
(line 169), both re-verified present in this pass.

**AR-L8-3 — parity (existing):** the R-2 arms of `tests/test_scaffold_copier.py`
green after the in-PR regen.

**Falsifiers (kill directions, run by the refute lane):**

- Delete the added paragraph from any of the three surfaces → that surface's
  AR-L8-1 arm reddens (and R-2 reddens on emitter/fixture skew).
- Rename the prefix string in `assets.py` OR retitle qmd §169 → AR-L8-2
  reddens naming the asset and the missing half.
- Re-add plugin-ui to `CODE_FREE_SKILLS` without removing the citation →
  `test_prose_refusal_skills_cite_no_codes` reddens (the set change cannot
  silently revert).

**Build smoke (once, by hand at build):** fresh `new --with-ui` into a temp
dir; `grep -c preview.css` ≥ 1 on the generated UI-GUIDE.md, AI-GUIDE.md, and
`.claude/skills/benchweave-plugin-ui/SKILL.md` — the same fact the arms then
pin forever.

**Gates:** fast lane (bare `ruff check .`, fresh-cache bare `mypy`, focused
`pytest` on `tests/test_agent_assets.py` + `tests/test_scaffold_copier.py` +
the touched modules) every commit; full battery + both standards tripwires
once, immediately before push; true exit codes, junitxml counts.

## 11. Top risks, each with its falsifier

- **R1 — STE register drift in the generated prose.** The R-5b checker does
  NOT verify register (its disclosed residual). Mitigation: document-writer
  dispatch (§6 item 6); the refute lane reads the diff against STE rules.
  Falsifier: a refute finding quoting a non-STE sentence.
- **R2 — R-5b anchor shape.** The code-citation source check requires the code
  at a string-literal start; `assets.py:54`'s literal begins with the prefix,
  so it matches today. If someone later builds the message by concatenation,
  the anchor breaks. Falsifier: mutate `assets.py:54` to a concatenation in
  the refute pass and observe AR-L8-2 redden — the breakage is loud, not
  silent (that is the A-F2 fold's design).
- **R3 — fixture regen mid-version produces answers-file skew** (the render
  stamps `_commit: v{__version__}` of the dev tree). Mitigation: the
  documented `_expected_answers` rewrite procedure. Falsifier: R-2 reddening
  on the answers bytes is exactly the catch.
- **R4 — skill bloat.** The section is capped at the five facts + two
  citations. Falsifier: `wc -l` on the skill diff exceeding ~12 added lines
  reddens review, not CI — named here so the refute lane checks it.
- **R5 — reach overclaim.** The end state must not be claimed as "all
  projects now document the override": UI-GUIDE reaches new scaffolds only
  (D-L8-3). The PR body states the propagation table (§3) verbatim.
  Falsifier: any PR-body or release-notes sentence claiming existing-project
  UI-GUIDE coverage.

## 12. Verdict

**BUILD, as scoped in §6.** The row's literal claim is already half-false
(the published side shipped in v0.12.0, `c08bf04`) — but the issue's end
state, "documented where authors read," is genuinely unmet at the three
surfaces open at the point of work, and no mechanical fix is needed to unblock
discovery. The slice is three prose insertions riding one SRF-1 cycle, an
R-5b set change that converts the existing triangulation checker into the
row's permanent registration mechanism, and a pre-committed, three-arm
RED→GREEN proof with named falsifiers. DON'T-BUILD would leave the row's end
state unmet and the issue's grep true forever; the cost ledger (one interface
disclosure, one fixture regen) is the minimum any fix of this row can pay.
