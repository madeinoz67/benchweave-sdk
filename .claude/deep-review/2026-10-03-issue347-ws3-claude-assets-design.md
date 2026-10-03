# WS3 design — Claude assets in the scaffolded plugin project (issue #347, increment 4)

Status: DESIGN, builder-ready. Tracking: madeinoz67/benchweave#347 (WS3). Ruled upstream by the
onboarding design note (`docs/prd/2026-10-03-issue347-plugin-onboarding.md`, branch
`docs/issue347-onboarding-design`): R-5 ("the scaffold ships a CLAUDE.md import + skills that
cannot drift from the docs"), Q3 (emit `AGENTS.md`; CLAUDE.md imports it — recommended yes),
Q4 (one authored source under the SDK + a CI drift check, NOT a generator). This record adopts
all three rulings; nothing here re-opens them.

**Build-order dependency: WS3 stacks on WS2** (branch `feat/issue347-ws2-copier`, the copier
template). The asset files are template members; the WS2 managed-vs-owned split is the surface
they ride. If WS2's template shape moved under it, WS3 adapts the carrier (template files vs
string constants) without changing this design's content or checks.

---

## 1. Premise, verified against the code and the harness

What exists today (`src/benchweave_sdk/scaffold.py`, read in full at `main` `d23505e`):

- The generated project has **no repo-level harness integration at all**: no `AGENTS.md`, no
  `.claude/` tree. The owned `CLAUDE_MD` seed carries Commands / Where-things-are / Safety
  rails as static strings; the seeded skills live INSIDE the wheel package
  (`src/<pkg>/skills/develop-plugin`, `drive-device` — registry-role `skill` payload content,
  a different audience from harness-discovered skills).
- Nothing anywhere machine-checks the factual claims in generated guidance. The AI-GUIDE,
  CLAUDE.md and seeded skills cite commands (`benchweave-sdk check`, `inventory`) that no test
  verifies against the CLI, and the main-side content pins (`tests/sdk/test_scaffold_skills.py`,
  `tests/sdk/test_plugin_developer_skill_content.py`) pin BYTES, not facts. A renamed
  subcommand or refusal code would leave every generated project's guidance silently stale.
  That staleness gap is the defect WS3 closes; R-5 is its falsifier.

Verified facts the design stands on:

1. **Claude Code import syntax, current and live-proven in-tree.** The import form is a line
   beginning `@` followed by a path relative to the importing file (or absolute):
   `@AGENTS.md`. BOTH BenchWeave repositories use exactly this today — the gateway repo's
   `CLAUDE.md` is line-for-line `@AGENTS.md` plus notes, and this SDK repo's own `CLAUDE.md`
   begins `@AGENTS.md` (read this session; both resolve — their content loads into every
   session here). Claude Code does **not** follow transitive imports, so the SDK-managed body
   must itself contain no `@`-imports: its doc pointers are plain paths and URLs.
   The alternative carrier `@.claude/benchweave-sdk.md` (a hidden-path import) is valid
   syntax but rejected below (§2.1).
2. **Harness skill discovery** is `.claude/skills/<name>/SKILL.md` with `name` + `description`
   frontmatter — the exact shape the seeded skills already use, so the asset skills follow a
   proven in-tree format.
3. **The real diagnostic surface is mixed, and the assets must respect the mix.** STD-4
   (`docs/internal/invariants.md`) pins the `snake_case:` refusal-prefix contract for the
   standards/validation/provider lanes: the six transport-provider-lane codes
   (`version_not_served:`/`retired_identifier:` are real served-set refusals in `served.py`
   that the guide documents, but they sit OUTSIDE STD-4's enumerated list — fold F4
   correction of this record's original wording), `signing_extra_absent:` (`publishing.py:1161`),
   `status_present:` (README, registry), `benchweave_sdk_server_extras_missing:` (server
   extra), `served_set_drift:`/`vendored_digest_mismatch:` (drift doc §5). The `doctor`
   command (WS1b, merged) refuses with `project_directory_not_found:` / `project_not_a_directory:`
   (`cli.py::doctor_command`); `recorded_sdk_version` raises `pyproject_unreadable:`
   (`scaffold.py`). **But `capture.py`'s refusals are PROSE** ("capture root inside the
   installed package tree is refused: …", "BENCHWEAVE_CAPTURE_DIR is set but empty…",
   `capture.py::capture_root` and the writer methods) — the capture surface does not carry
   STD-4 codes. A skills author who "knows" the SDK's discipline would invent codes there.
   The design forbids that (§2.3) and the drift check makes invention impossible (§4).
4. **Command inventory is derivable at test time**: `from benchweave_sdk.cli import cli` and
   the click group's registered commands — the established pattern (13 test modules import the
   group; `tests/test_cli_frameworks.py::test_sdk_exposes_click_command_group`). The five-step
   workflow's canonical names live in README §Five steps (install → `new` → `check` → `build`
   → `inventory`) and this repo's CLAUDE.md "Using the SDK" (a WS0 artifact).
5. **Register obligation**: generated guide text is published documentation → ASD-STE100
   Simplified Technical English, authored via the `document-writer` agent (this repo's
   CLAUDE.md, "Documentation register (ASD-STE100)"). The asset prose is therefore a
   document-writer leg inside the build; the design record, tests and invariants keep the
   engineering register.

### Root cause of the gap (traced, not assumed)

The scaffold predates the harness-asset question: guidance grew as string constants
(`AI_GUIDE`, `CLAUDE_MD`, seeded skills) whose only quality mechanism was byte-pinning.
Byte-pinning proves stability, not correctness — it freezes staleness in. With WS2 making
generated content updatable, the missing half is a managed carrier plus a fact-level check
against machine sources. WS3 is that half; it does not touch the seeded package skills
(§6, deferral 3).

---

## 2. The mechanism

### 2.1 Carrier decision: one managed `AGENTS.md` at the project root

New template members (WS2 tree; `.jinja` only where a token is used):

```
template/AGENTS.md                                            # MANAGED body ({{ sdk_version }})
template/CLAUDE.md.jinja                                      # OWNED seed, MODIFIED (see below)
template/.claude/skills/benchweave-plugin-workflow/SKILL.md.jinja
template/.claude/skills/benchweave-descriptor/SKILL.md.jinja
template/.claude/skills/benchweave-plugin-ui/SKILL.md.jinja
template/.claude/skills/benchweave-adapter-testing/SKILL.md.jinja
template/.claude/skills/benchweave-capture/SKILL.md.jinja
```

`AGENTS.md` at the root is the one managed body (Q3's ruling), and the owned `CLAUDE.md` seed
imports it. The rendered seed:

```markdown
# Agent notes — the {{ package_name }} plugin project

@AGENTS.md

## This file is yours

`AGENTS.md` above is SDK-managed (upgraded by `benchweave-sdk upgrade`). Keep your
project-specific notes here; they never block an upgrade.
```

Usage-first ordering is satisfied structurally: the import line sits directly under the title,
so a session sees the five-step workflow before anything else. The seed drops the old static
Commands / Safety-rails text (those facts move to the managed body and skills, where they are
drift-checked) and keeps nothing but identity + import + author space.

Why not `@.claude/benchweave-sdk.md` (the hidden-path alternative): valid syntax, but it
serves only Claude Code, while Q3's purpose is one body for all agent types — non-Claude
agents read `AGENTS.md` natively and never read `.claude/`. Two carriers would also mean two
bodies to keep honest. The `benchweave-*` skills stay under `.claude/skills/` because skill
discovery IS harness-specific; the BODY is shared, the INVOCATION surface is per-harness.
Both-repo precedent (`@AGENTS.md` line 1) is the exact shape being generated.

`AGENTS.md` is managed (NOT in `_skip_if_exists`): untouched authors get refreshed guidance on
`upgrade`; an author who edits it gets copier's loud conflict markers — never silent loss
(WS2 spike table). The seeded `CLAUDE.md` remains owned (WS2's ruling stands; an update that
overwrote author notes would be harmful by construction).

`AGENTS.md` structure (final prose by document-writer, STE100; the skeleton is the contract):

1. Header: managed-file notice — "Maintained by benchweave-sdk {{ sdk_version }};
   `benchweave-sdk upgrade` refreshes this file; edits conflict loudly", plus the one-line
   instruction that Claude Code sessions get it via CLAUDE.md's import (already present in
   projects scaffolded at/after this release).
2. **Usage — the five-step workflow** (README-canonical names, in-project perspective):
   environment + `doctor` → facts/prompts (AI-GUIDE.md) → checks (`pytest`, `check`, UI
   checks when presentation exists) → independent review → build/inventory/owner approval.
   Exact commands, generic paths as `src/{{ package_name }}/…`.
3. The skills index: one line each, naming what `.claude/skills/benchweave-*` covers.
4. Safety rails: synthetic posture (no hardware contact, flashing, energising; publish
   nothing without owner authority; preview success is not admission).
5. Doc pointers: the versioned rendered guide URL and the AI-GUIDE/UI-GUIDE paths. Plain
   references only — no `@`-imports (non-transitive).

### 2.2 The five SDK-managed skills

Each SKILL.md: `name`/`description` frontmatter (description = when to invoke, imperative);
"When to use"; the real commands with real flags; real codes only where the surface has codes
(§1.3); a "Read the docs" pointer; the managed footer with `{{ sdk_version }}`. Skills
ROUTE — they name and point, they do not re-teach (single-source rule, §3).

| Skill | Covers | Real codes it may cite (all verified) |
|---|---|---|
| `benchweave-plugin-workflow` | The five-step loop as commands: `doctor` (a report, never a failure), `pytest`, `check` (the gate), `uv build`, `inventory`, `upgrade`/`adopt` pointers; exit-code semantics | `project_directory_not_found:`, `project_not_a_directory:` — cite only if the guide documents them by then (§4 rule); otherwise behavior-only |
| `benchweave-descriptor` | Descriptor authoring: per-pin validation (the descriptor's own `otdp_version` answers), capabilities ≡ operations keys, honest partial-check scope (S01/S02/S04, not all S/C/M), transport-provider pins | `version_not_served:`, `retired_identifier:`, the six `provider_*` codes |
| `benchweave-plugin-ui` | `check-ui` / `check-preset` / `preview-ui` with real flags; resource-root and symlink rules; loopback posture; `SIMULATED PRESENTATION DATA`; preview ≠ admission | none today (the plugin-ui lane refuses through the schema/validator surface, not named prefixes — describe behavior, cite no codes) |
| `benchweave-adapter-testing` | `MockHost`/`MockContext` exact-exchange patterns; `check_operation`/`check_lifecycle` and their wall-clock bounds; dispatch-before-transmit; uncertain-outcome preservation; what mocks do not prove | none (module APIs, not refusal paths) |
| `benchweave-capture` | `StandaloneCaptureWriter`: root precedence (argument > `BENCHWEAVE_CAPTURE_DIR` > `./captures`), the package-tree refusal, declared-format set, sample_count×8 rule, G2/G3 not applied standalone, no auto-ingest | **none — the capture surface refuses in prose (§1.3). The skill describes refusals by behavior and quotes no code-shaped tokens.** |

Five, not fewer: each maps 1:1 to a distinct user-guide surface with its own command set and
error surface; folding capture into adapter-testing would fuse two unrelated audiences (unit
test doubles vs bench scripts). Five, not more: the set exhausts the teammate-broached topics
without a "tips" skill. Naming: `benchweave-` prefix is disjoint from seeded package-skill
names by construction (seeded names always end `-plugin-development`/`-device-operation`;
`RESERVED_PACKAGE_NAMES` blocks the packages that could collide).

### 2.3 Authoring rules that make the drift check honest

- **Codes**: cite a `snake_case:` code only inside backticks with the trailing colon
  (`` `version_not_served:` ``) — the citation convention the checker parses. Cite a code
  only where BOTH the SDK source and the user guide carry it (triangulation, §4). Never
  invent, never paraphrase a code into existence, never cite codes for prose-refusal surfaces.
- **Commands**: every `benchweave-sdk <subcommand>` mention must name a subcommand the click
  group registers at test time.
- **Docs**: every guide pointer names a heading that exists verbatim in
  `user_guide/plugin-sdk.qmd`.
- **Version**: the only version literal is the `{{ sdk_version }}` token — never a typed
  number, so a render can never ship a stale stamp.
- **Register**: STE100 via document-writer; no client/device/serial names (repo is public).

### 2.4 Managed/owned interaction (extends the WS2 split)

- **Managed (added)**: `AGENTS.md`, `.claude/skills/benchweave-*/**`. Update semantics are
  WS2's: unchanged ⇒ refreshed; author-edited ⇒ conflict markers, loud, resolvable.
  Author-added files (own skills, own notes) match no template path and are never touched.
- **Owned (unchanged set)**: `CLAUDE.md` — its SEED changes (import + slim-down), reaching
  new projects only, exactly like every WS2 owned seed ("template fixes to seeds reach new
  projects only; that is the intended semantics").
- **Pre-existing projects (the honest residual)**: `adopt` + `upgrade` delivers the managed
  body and skills, but the one-line `@AGENTS.md` import lives in the OWNED `CLAUDE.md`, so
  pre-WS3 projects add it by hand. The managed header says exactly that. A `doctor` arm that
  reports a missing import is a named deferral (§6.4), not silent.
- **Adopt collision**: a project with a hand-made `AGENTS.md` hits the loud conflict path on
  first upgrade (template-added vs dest-modified) — safe failure direction, documented in
  `adopt`'s disclosure; no new code in this slice.
- **The wheel is untouched**: `packages = ["src/<package>"]` — `AGENTS.md` and `.claude/` sit
  outside it, exactly like today's root `CLAUDE.md` (registry role `documentation` IF a
  publisher ever ships them; default is dev tooling that does not ship).

---

## 3. Single source: authored assets + machine reconciliation (Q4 adopted, generator rejected)

**One authored source = the asset files themselves, authored once in this repository's
template, versioned with the template.** The user guide stays the authored HUMAN source; the
assets are authored AGENT sources. Facts unavoidably appear in both — so the design does not
pretend single-carriage; it makes dual-carriage checkable:

- Every code cited in an asset must exist in SDK source AND in the user guide
  (asset ⊆ source ∩ guide). A code renamed upstream, or dropped from the guide, reddens the
  asset that still cites it.
- Every cited subcommand must be registered in the click group AT TEST TIME — no committed
  list to go stale.
- Every cited guide heading must exist verbatim in `user_guide/plugin-sdk.qmd`.

**Generator rejected** (docs → skills generation): skill prose needs tuning that human-facing
prose does not (voice, imperative brevity, citation conventions, harness-specific
description lines); a generator couples two audiences through a build step whose output
nobody reviews, and its failure mode is the same staleness it promised to remove — now hidden
inside a pipeline. The drift check gets R-5's invariant without the coupling. Precedent for
authored-artifact-checked-against-machine-source: PKG-3's renderer-freshness diff gate and
`make check-sdk-standards` (committed artifact vs regeneration), and
`tests/test_registry_census.py::test_the_census_detects_a_planted_command` (a checker that
must catch planted violations, permanently).

Meaning-drift residual, disclosed: the check proves a cited code EXISTS in source and guide,
not that the skill's one-line gloss matches the guide's definition. Mitigation is the §2.3
authoring rule (glosses minimal; the guide owns definitions) plus review. The guard does not
catch prose paraphrase drift — stated here so nobody claims it does.

---

## 4. The R-5 acceptance rule (pre-committed BEFORE any implementation number is looked at)

One new test module, `tests/test_agent_assets.py`, in the existing `sdk` CI lane (no new
job). It reads the asset files from the template tree in-repo (unrendered; tokens are
inert to the checks — `{{ package_name }}` never appears in a subcommand position).

**R-5a — asset integrity (exhaustive).** The WS2 R-2 render fixture grows exactly six files
(1 `AGENTS.md` + 5 `SKILL.md`), byte-pinned, both `with_ui` arms. Any other tree delta is a
failure. (Rides WS2's existing parity test; the fixture update is deliberate and shown in the
PR.)

**R-5b — drift triangulation (exhaustive over every citation in every asset file).**
For every backticked `` `code:` `` citation in `template/AGENTS.md` and the five skills:
assert `code:` occurs in the concatenated source of `src/benchweave_sdk/` and
`src/benchweave_sdk_server/`, AND occurs in `user_guide/plugin-sdk.qmd`. For every
`benchweave-sdk <sub>` mention: assert `<sub>` ∈ the click group's registered commands
(imported at test time) ∪ {"registry"}. For every cited guide heading: assert the heading
line exists verbatim in the qmd.

**R-5c — planted-violation arms (PERMANENT, the control fluff cannot pass).** The module
contains three arms that feed the checker deliberately-broken asset copies and assert each
is caught: (i) a fake `` `not_a_real_code:` `` citation; (ii) a `benchweave-sdk frobnicate`
mention; (iii) a pointer to a heading that does not exist. A checker that passes a planted
violation is itself broken — these arms run in CI on every push, not once in a PR demo.

**R-5d — update propagation.** WS2's R-4 protocol assertions extend verbatim to the new
managed set: after `upgrade`, `AGENTS.md` and the five skills byte-equal the template@target
render (A1), the author-edited `CLAUDE.md` is byte-identical to the author state (A2), and
the file set equals expected exactly (A5).

**RED discipline for the build:** R-5b's arms are written FIRST and demonstrated failing
against a checker stub that accepts everything (proof the arms bite); then the checker is
implemented and the real assets pass. Additionally, one live RED on R-5d: author-edit a
managed skill before `upgrade` and show conflict markers appear (not clobber) — reverting to
seeded-template behavior would silently pass otherwise.

**Ships iff** R-5a–d hold with the arms demonstrated, in both `with_ui` arms, in this
repository's CI (Windows included — string checks are platform-blind, and the render/update
legs ride WS2's already-cross-platform lanes).
**Killed if** any planted-violation arm passes (the checker is decorative — fix or kill),
any real citation fails triangulation (the asset or the guide is lying — fix the asset, or
re-sync the guide deliberately with the docs owner), any owned file differs by one byte
after `upgrade`, or the render fixture cannot be made byte-exact (that file's generation
stays out of the template — same rule as WS2 risk 1).
**Inconclusive, not pass:** if the click group cannot be imported in the test environment,
or the template render leg cannot run, the lane is HELD — a green run with the check skipped
is a failed run.

Denominators: "every citation" = the complete set matched by the three citation regexes over
the six asset files (the test asserts the set is non-empty per file, so a reformatted-away
citation convention cannot silently empty a check class).

---

## 5. Invariant, drift and tier impacts

- **SRF-1 — AMENDED.** The generated tree gains six root/`.claude` files, outside
  `src/<package>/`, never in the plugin wheel; the generated runtime keeps zero SDK
  dependency. The AI-GUIDE clauses are untouched. Downstream full-tree diffs see six added
  files (R-5a pins the exact set).
- **PKG-2 — AMENDED (wording).** WS2's record says "the template tree contains none of them"
  (`.claude/` etc.) — WS3 makes that clause stale: the wheel now CONTAINS
  `benchweave_sdk/scaffold_template/template/.claude/…` and `template/AGENTS.md` as PRODUCT
  content. The invariant's exclusion is rescoped to the SDK repository's own agent config at
  its repo-root locations; template-borne scaffold content is explicitly carved out. The
  hatch presence check and sdist list gain nothing new (WS2 already includes the template).
- **STD-4 — NOT extended.** No new refusal paths; the drift test is a test, not a refusal
  surface. (Discovered and disclosed: `capture.py` predates the prefix discipline — its
  refusals are prose. Not fixed here; §6.5.)
- **TWO-1 — held.** SDK-only PR. At pointer advance, the gateway's scaffold-content pins
  (`tests/sdk/test_scaffold_skills.py`, `tests/sdk/test_plugin_developer_skill_content.py`)
  see the new tree; updating those expectations is the pointer PR's business, never gateway
  bytes moving first.
- **Obligations walk (G5)**: drift-and-obligations row 2 (scaffold output) gains the agent
  assets in its enumerated surfaces; a NEW row obligates asset factual claims to the R-5b
  check (the check IS the obligation's mechanism); CI-map `sdk` row gains the drift module.
  README (five-steps step 3 + tree diagram) and `user_guide/plugin-sdk.qmd` (generated-tree
  description) mention the assets. `docs/internal/invariants.md` takes the SRF-1/PKG-2
  amendments. Release-review matrix: no change — `{{ sdk_version }}` is a render token, not
  a repo version-bearing surface.
- **On-disk format/schema:** yes — the generated project tree (interface per SRF-1). Part of
  why this is Tier 3.
- **CI cost:** zero new lanes. One test module in `sdk` (string scans + a click import —
  milliseconds); R-5a/R-5d ride WS2's existing parity/update lanes; no dependency changes
  (`pyproject.toml` untouched — no Tier-3 dependency trigger, Tier 3 stands on the scaffold
  rule alone).

**Review tier: 3.** Trigger (this repo's rubric, Step 1): "touches `scaffold.py` output
shape" — post-WS2 the template IS the output shape. G6 second adversarial reviewer
mandatory; per the standing two-lane Tier-3 retro rule, two independent adversary lanes.

**Step-1 keyword scan (#254 discipline) over the expected diff text** (six template assets,
the CLAUDE.md seed, `tests/test_agent_assets.py`, the R-2/R-4 fixture deltas, the three docs
files, README/qmd lines): `threading` 0, `asyncio` 0, `subprocess` 0, `sha256` 0 (assets say
"hash rows", deferring the literal to `inventory`'s own help), `hashlib` 0, `migrate` 0
(assets say "move-to", the guide's term), `recovery` 0, `protection` 0. All zeros by word
choice, re-derived at review over the actual diff. Tier 3 stands on the path rule alone; the
keyword lane adds nothing.

---

## 6. Minimal FIRST slice, and the deferrals

**In (one PR, SDK repo, stacked on WS2):** the seven template files above; the modified
`CLAUDE.md` seed; `tests/test_agent_assets.py` (R-5b arms first, RED-then-GREEN); the R-2
fixture extension (R-5a) and R-4 assertion extension (R-5d); the three docs/internal files;
README five-steps + tree-diagram lines and the qmd generated-tree paragraph (document-writer
leg, STE100); this design record as first commit on the branch.

**Deferred, each with its home:**

1. **`doctor` reporting a missing `@AGENTS.md` import / stale managed assets** in
   pre-WS3-upgraded projects — natural follow-up under #347; the managed header carries the
   manual instruction meanwhile.
2. **`adopt` refusing or reconciling a hand-made `AGENTS.md`** (beyond the loud conflict
   path) — follow-up under #347 if real projects hit it.
3. **Rehoming/consolidating the seeded package skills** (`src/<pkg>/skills/`) against the
   managed set — a registry-role/content decision (they are wheel payload, `skill` role);
   a separate design pass under #347 if wanted. WS3 only documents the boundary: seeded =
   plugin-specific, distributable; managed = SDK-generic, repo-level tooling.
4. **Conditional skill membership** (e.g. plugin-ui skill only with `--with-ui`) — rejected
   for this slice: unconditional keeps the file set deterministic and the workflow simpler;
   recorded as a possible follow-up.
5. **Snake_casing the capture surface's refusals** (bringing `capture.py` under STD-4) —
   out of scope; a standalone SDK change with its own STD-4 CI implications. Named here so
   the prose-refusal constraint (§1.3) is traceable.
6. **Non-Claude skill discovery surfaces** (e.g. agent-agnostic skill manifests) — none
   exist to target today; revisit when a real consumer asks.

---

## 7. Precedent

- **Managed/owned split and the template carrier**: WS2 — this design only adds members.
- **`@AGENTS.md` import**: both BenchWeave repos' own CLAUDE.md, line 1 — the exact rendered
  shape, proven live.
- **Authored artifact checked against machine source**: PKG-3 renderer-freshness;
  `make check-sdk-standards`; `tests/test_registry_census.py`'s planted-command arm (the
  permanent RED-control pattern R-5c copies).
- **Skill file shape**: the scaffold's own seeded skills (frontmatter name/description).
- **Command-set derivation at test time**: 13 existing test modules importing the click
  group; `test_sdk_exposes_click_command_group`.
- **Register discipline for generated guide text**: the repo's ASD-STE100 documentation
  register and `document-writer` agent.

Nothing invents architecture: every mechanism is a member or a check shaped like one that
already holds in this tree.

---

## 8. Top risks, each with its falsifier

1. **Claude Code import semantics drift** (harness is external). Falsifier/containment: the
   bytes are pinned by R-5a regardless; degradation is graceful (AGENTS.md is directly
   readable; non-Claude agents never depended on the import). If imports stopped resolving,
   the five skills still carry the workflow — the import is convenience, not the carrier of
   record.
2. **Copier dot-directory rendering** (`.claude/` tree). WS2 proved dotFILES, not
   dot-directories. Falsifier: R-5a red during the build; if copier cannot render the
   subtree, that is a WS2-mechanism finding escalated to the WS2 lane, not worked around
   here.
3. **The drift check rots into existence-only** (passes codes whose meanings diverged).
   Containment: the guide-triangulation half (§4) means a code dropped from the guide
   reddens; meaning drift inside glosses remains review's job — disclosed in §3.
4. **Asset prose drifts in register or over-promises** (STE100, safety language).
   Falsifier: the document-writer leg plus review; the checker does not verify register
   (stated).
5. **Context bloat**: five skills auto-list their descriptions per session. Containment:
   description lines are when-to-use only; bodies load on invocation. Acceptable at five;
   R-5a's exact-set assertion keeps growth deliberate.
6. **Pre-WS3 projects never add the import** and quietly miss the body. Disclosed (§2.4);
   deferral 1 (`doctor` arm) is the close-out; the managed header instructs meanwhile.
7. **Gateway content pins redden at pointer advance** — expected TWO-1 friction, named here
   so the pointer PR treats it as the discipline working, not a regression.

No hard blocker found. **BUILD.**
