# WS4 design — first-timer documentation and docs-as-tests (issue #347, increment 5)

Status: DESIGN, builder-ready. Tracking: madeinoz67/benchweave#347 (WS4, the last workstream).
Ruled upstream by the onboarding design note (`docs/prd/2026-10-03-issue347-plugin-onboarding.md`,
branch `docs/issue347-onboarding-design`): R-6 — "A first-timer reaches `check`-pass from the
getting-started page alone; docs-as-tests CI proves it" — plus the standing R-7 constraint
(the wheel's dependency set is unchanged; WS4 adds no dependency). This record adopts both;
nothing here re-opens them.

**Build-order dependency: WS4 stacks on WS3** (branch `feat/issue347-ws3-claude-assets`, which
itself stacks on WS2's `feat/issue347-ws2-copier`). The getting-started page's install line
carries WS2's `[scaffold]` extra, and its "what you should see" tree includes WS3's `AGENTS.md`
and managed skills. If either sibling's shape moves, the page's content adapts; the acceptance
mechanism (§4) does not.

---

## 1. Premise, verified by execution — the cold-start gap log

Method: this design did not assume the docs' defects; it hit them. A fresh directory, a fresh
venv, the published SDK from PyPI (release 0.6.0), and only two authorities: the README
"Five steps" and `user_guide/plugin-sdk.qmd`. No repository knowledge. Executed end to end on
2026-10-03. Every row below names the doc location that failed, what a first-timer expected
versus saw, and what would have fixed it. The gap log is the requirements source for §2.

| # | Where the doc failed | Expected vs saw | Fix |
|---|---|---|---|
| G1 | README "Five steps" step 1: `uv pip install benchweave-sdk`, no environment step before it | Install succeeds; instead `error: No virtual environment found; run uv venv` — the error message taught the next command, not the docs. The user guide §1 has `uv venv --python 3.13` only inside the checkout-contributor path; its PyPI path (`pip install benchweave-sdk`) has the same hole (`pip` into what? PEP 668 blocks system pip on many machines) | Getting-started step 0 creates the environment before any install |
| G2 | Nowhere in five steps or guide §1: how to verify the install worked, or what a correct result looks like at any step | `benchweave-sdk --version` exists but only inside the WS0 "Which checkout" section, which a first-timer following five steps has not reached | Every numbered step gets a "you should see" line (the R-6 column that is empty today) |
| G3 | `new plugins/acme/model100` run from `/tmp/...` prints `Created synthetic plugin at /private/tmp/...` | The typed path and the reported path differ; the symlink-canonicalization note lives only in README "Directory structure" prose | "You should see" shows the canonicalized path; troubleshooting carries the row |
| G4 | Five steps step 4: "Install the plugin with its test dependencies. Run the plugin tests." — no command for either verb; the extra name `test` had to be found by opening the generated `pyproject.toml`; `uv pip install -e '.[test]'` appears only in the guide's checkout-build path | Two of the five steps' verbs have no command form in the doc a first-timer follows | The page gives the exact commands (highest-impact gap for R-6) |
| G5 | Five steps step 4: "Record all applicable S01–S18, C01–C12 and M01–M14 obligations" | S/C/M are never expanded or linked at point of use; the first-timer cannot tell whether they block the first check-pass (they do not) | Glossary entry + point-of-use pointer; the page says plainly that none are needed to reach first check-pass |
| G6 | Five steps step 5: "`benchweave-sdk inventory` helps generate hashes" — no argument given | Bare `inventory` errors (`Missing argument 'DIRECTORY'`, usage text). The guide names `<prepared-bundle-directory>` but never defines "prepared bundle"; `dist/` was a guess that happened to work | The page shows `benchweave-sdk inventory dist/` with the expected output shape |
| G7 | `benchweave-sdk --help` reveals `package` and `submit` — the actual release commands | Five steps step 5 narrates release in prose and never names them; the first-timer finishing step 5 cannot see the next concrete command | The page's "where next" section names them with a not-needed-for-check-pass framing |
| G8 | In the generated project, `uv run pytest` resolves its own interpreter and deps (Homebrew 3.14, pytest 9.0.2) and fails `ModuleNotFoundError: No module named 'benchweave_sdk'` even though `-e '.[test]'` was installed into the project's `.venv` | A uv-native first-timer WILL try `uv run`; the docs never mention it (every command is activation-based) | The page teaches one path (activated venv); troubleshooting carries the `uv run` row (use the activated environment, or `--extra test`) |
| G9 | A pre-existing `uv tool install` of the SDK on the same machine was an older release (`doctor` missing: `Error: No such command 'doctor'`) | Install channels drift silently; the WS0 sections say how to CHECK versions, not how to UPGRADE a tool install (`uv tool upgrade benchweave-sdk`) | Troubleshooting row |
| G10 | Five steps order: step 3 "replace the synthetic protocol" precedes step 4 "run the checks" | The fastest confidence loop is check-passing the SYNTHETIC plugin first (the guide itself: "A pass of its tests demonstrates that the tools work"). The steps' narrative order buries the runnable loop | The page runs the checks on the synthetic plugin immediately (that IS R-6), then points to AI-GUIDE prompt 2 |
| G11 | No exit-code semantics stated for `check`/`pytest` anywhere a first-timer reads | Minor; matters for anyone scripting or wiring CI | One line in the page ("a pass exits 0") |
| G12 | README's `check-ui` example carries `--firmware 1.0.0` unexplained | Where does 1.0.0 come from? (The synthetic descriptor declares it.) | The page's UI section keeps the flag and says where it comes from |

What worked, for the record: `new`, `check`, `doctor`, `uv build`, `check-ui`, and `preview-ui
--no-open` all behaved as documented once the missing commands were reconstructed; PyPI 0.6.0
is current; the generated `pytest` run passes 4/4 in ~0.2s.

### Root cause (traced, not assumed)

The five steps were written as a **reader's summary** for someone who already has Python
packaging fluency: three of its verbs have no command form (G1, G4, G6), no step states what a
correct result looks like (G2), and its ordering optimizes the narrative ("replace the
protocol") over the runnable loop (G10). The missing commands exist — but scattered in the
guide's checkout-contributor path, which is not the first-timer's path. And structurally:
**nothing anywhere executes the docs as written.** CI proves the CLI works (the
scaffold-and-check and installed-wheel-smoke steps in `ci.yml` run the same commands), but the
sentences a first-timer follows have never been run as a script, so their gaps could not
surface. New prose alone would reproduce the defect class with fresh sentences. WS4 therefore
ships the pages AND the execution proof together; §2.3 is not a nice-to-have attached to docs,
it is the mechanism that makes R-6 falsifiable.

---

## 2. The mechanism

### 2.1 Four new pages under `user_guide/` (STE100, document-writer leg)

All four are authored in ASD-STE100 by the `document-writer` agent (this repo's CLAUDE.md,
"Documentation register"), under the rulebook already established by issues #352/#353: sentence
length 20/25, active voice, no slashes as connectives, no gerunds as nouns, warnings before
steps, one term per thing, technical names exempt (7.1), accuracy over rule (7.3), approved-word
candidates flagged never claimed. New pages use American spellings (the ASD-STE100 dictionary's
convention); the repo-wide UK/US settlement is a deferral (§6.3) because it touches prose this
slice does not rewrite. **No version literals in any new page** — the `index.qmd` discipline
("This page does not claim a version"); enforced mechanically (§2.3).

**`user_guide/getting-started.qmd`** — the R-6 page. Numbered steps, each with the exact
command, "you should see", and "if you do not see this" (a link into troubleshooting):

- Step 0 — prerequisites (Python 3.13+, how to install `uv`), create an environment
  (`uv venv`), activate (macOS/Linux and Windows forms both shown).
- Step 1 — install the SDK with the scaffold extra (`uv pip install 'benchweave-sdk[scaffold]'`
  post-WS2) and verify (`benchweave-sdk --version`).
- Step 2 — `benchweave-sdk new plugins/acme/model100 --package benchweave_acme_model100`; what
  you should see (the two-line created message, with the canonicalized-path behavior of G3);
  a MINIMAL tree diagram (load-bearing files only: `pyproject.toml`, `src/<pkg>/` with
  `adapter.py`/`protocol.py`/`descriptor.json`, `tests/`, `AI-GUIDE.md`, `CLAUDE.md`,
  `AGENTS.md`, `.claude/skills/` — the WS3 shape).
- Step 3 — `cd plugins/acme/model100`; `uv pip install -e '.[test]'`; `pytest`. Expected: the
  last line says `passed` (the count is the generated tests' count — no number in prose, so the
  page cannot go stale when the scaffold grows tests).
- Step 4 — `benchweave-sdk check src/benchweave_acme_model100/descriptor.json`; the one-line
  pass message; what a pass means and does not mean (honest partial scope, pointer to the
  guide's per-pin section); "a pass exits 0" (G11).
- Step 5 — `uv build` (you should see: two files under `dist/`); `benchweave-sdk inventory
  dist/` (you should see: one JSON row per built file — no hashes quoted in prose).
- Step 6 — `benchweave-sdk doctor` (scaffold pin matches the installed SDK).
- Step 7 — where next: replace the synthetic protocol (AI-GUIDE.md prompt 2 — G10's ordering
  made explicit), the optional UI section below, the which-checkout page, the glossary, the
  full plugin developer guide, and the release commands by NAME (`package`, `submit`) with the
  framing that none are needed to reach first check-pass (G5, G7).
- Optional UI section — a second `new --with-ui` project; `check-ui` with the five flags
  verbatim (the `--firmware 1.0.0` provenance explained, G12); `preview-ui --no-open` with its
  serves-until-you-interrupt posture and how to stop it.

**Authoring rule that makes the page testable:** every fenced ```sh``` block in
getting-started.qmd is part of ONE executed sequence, in document order. Illustrative output
and non-runnable snippets use ```text``` blocks. The page contains no `sh` block that CI does
not run (§2.3 relies on this).

**`user_guide/which-checkout.qmd`** — WS0's README section expanded: the look-alike-checkouts
table (standalone SDK repo = canonical; gateway `packages/sdk` = integration mount, can lag),
what the mount is for, the three version-check commands (`grep '^version' pyproject.toml`,
`git describe --tags`, `benchweave-sdk --version`), and `uv tool upgrade` for the stale-tool
case (G9). The README's WS0 section slims to two lines linking here (it keeps the one-paragraph
answer; the page carries the detail).

**`user_guide/glossary.qmd`** — one term, one definition, alphabetized: adapter; binding
catalogue; capture; descriptor; gateway vs standalone (`[server]` extra) vs preview; import
package vs plugin project; prepared bundle; preset; presentation; synthetic protocol/plugin;
and the check-family one-liners (`check`, `check-ui`, `check-preset`, `doctor`, `inventory`).
The S01–S18/C01–C12/M01–M14 obligation families get one entry each, defined by pointer to the
vendored standards and the main repository's device developer guide (G5) — the glossary does
not restate the obligations. Every glossary term that names a CLI subcommand is
registration-checked (§2.3).

**`user_guide/troubleshooting.qmd`** — symptom/cause/fix rows, seeded from the gap log:
the no-venv error (G1); the `/private/tmp` path (G3); `uv run pytest` ModuleNotFoundError
(G8); the stale tool install (G9); inventory's missing argument (G6); check-ui's firmware
value (G12); preview-ui stop behavior. Each fix is a command that exists. The page grows
reactively in later slices; slice 1 ships exactly the gap-log rows plus nothing speculative.

### 2.2 Navigation and landing — usage first everywhere a first-timer lands

- **`great-docs.yml` `user_guide:` list** (explicit on purpose; only listed pages render): a
  new first section `Get started` containing `getting-started.qmd`, `which-checkout.qmd`,
  `glossary.qmd`, `troubleshooting.qmd`, then the existing `Plugin development` section with
  `plugin-sdk.qmd`. **Set `homepage: user_guide`** — great-docs' documented option: "the first
  user-guide page becomes the landing page." The docs site's front door becomes the runnable
  path, not the overview. The builder verifies the flip with a local
  `scripts/assemble_docs_site.py` run before opening the PR (the assembled versioned buckets
  must render the new pages in both the release and dev buckets).
- **`README.md`** — Five steps gains a first line: new here? the getting-started page walks
  these steps with full commands and expected output (rendered-guide URL). Section reorder to
  put usage before orientation: title paragraph → Installation → Five steps (+link) →
  Documentation → Which checkout → Community → Directory structure → (rest unchanged). The
  moved sections are moved, not rewritten — the existing prose keeps its register; its STE100
  rewrite is the #353 follow-on, not this slice.
- **`CLAUDE.md`** — the WS0 "Using the SDK" section extends its pointer: the getting-started
  page (repo path + rendered URL) alongside the README anchor. (WS0 already made this file
  usage-first; no reorder needed.)
- **`index.qmd`** — the Documentation list gains the getting-started page as its FIRST item;
  the Quick start paragraph links it.

### 2.3 Docs-as-tests: `tests/test_getting_started.py` (where R-6 lives)

One new test module in the existing `sdk` CI lane — **no new job, no new dependency** (uv,
pytest, stdlib `subprocess` only; R-7 holds). It runs in the default
`uv run pytest -q -m "not browser"` collection on all three OS lanes.

**Extraction.** Parse `user_guide/getting-started.qmd`, collect every fenced ```sh``` block in
document order (the `test_guide_serial_host.py` precedent — that module extracts and executes
the guide's Python example precisely so "the example cannot drift"; this is its shell cousin).
Assert the extracted sequence is non-empty per step-section (a reformatted-away block cannot
silently empty a step) and that the total is at least 8 blocks — the page's shape is part of
the contract; dropping below reddens with a named message, not a shrunk run.

**Two declared translations, and only two.** The page is written for a first-timer on their
machine; CI runs it against THIS tree. The gap between those two worlds is closed by exactly:

- **T1 — the install line.** The page's literal `uv pip install 'benchweave-sdk[scaffold]'`
  becomes a direct-reference install of the locally built wheel with the same extra set
  (`uv build` in the SDK checkout first; PEP 508 `name[extra] @ file://…`). This is the
  ci.yml installed-wheel-smoke pattern (wheel → fresh venv → `new` → `check`) with the page,
  not a hand-copied script, as the command source. The substitution asserts it matched exactly
  once; a reworded install line reddens with `getting_started_install_line_not_found:` — the
  page and the translation move together or the lane says so.
- **T2 — activation lines.** `source .venv/bin/activate` (and the PowerShell/batch forms) are
  not spawned; the harness applies the two environment effects activation itself has: set
  `VIRTUAL_ENV` and prepend the venv's `bin`/`Scripts` directory to `PATH`. This keeps the
  module genuinely cross-OS (no bash, no shell=True — each remaining line is shlex-split and
  run with `subprocess.run(shell=False)`, per the ci.yml bash-everywhere lesson carried into
  Python).

Every other line runs **verbatim**. A line the harness does not recognize — new syntax, a
typo, a deliberately fancy construct — aborts with `getting_started_unrecognized_line:` and
fails the lane. Nothing is silently skipped (explicit configuration is never silently
substituted; a doc the harness quietly half-runs would be a worse lie than today's unrun docs).

**Execution and assertions.** Lines run in order with a persistent working directory (`cd`
lines carry state). Asserted: every command exits 0; the `pytest` line's summary contains
`passed` and the run collected more than zero tests; `check` exits 0; `uv build` leaves a
wheel and an sdist under `dist/`; `inventory` emits parseable JSON with at least two rows
carrying the `path`/`bytes`/`sha256` keys (key-shape only — no byte or hash values, so passing
tests never depend on content churn); `doctor` exits 0. The UI section's blocks execute too
(second `new --with-ui` project; `check-ui` with its flags verbatim).

**preview-ui is verified, not executed** — it serves until interrupted by design, and the
release-smoke precedent deliberately stays away from it. Its command line is checked by
registration: every `benchweave-sdk <subcommand>` mention anywhere in the four new pages must
name a subcommand the click group registers at test time (the WS3 R-5b rule, reused), and
`preview-ui`'s cited flags must exist on that command. The same registration check covers
`which-checkout`, `glossary`, and `troubleshooting`, whose commands are failure-path examples
a green run cannot execute.

**Version-literal zero over prose.** The module asserts a bare-semver regex finds zero hits in
the four new pages and in the README's diff lines. `count_version_literals.py` scopes its gate
to executable code (AST, docstrings excluded); prose is outside it, so this module owns the
prose half — the per-release docs buckets cannot ship a page naming a version that aged out.

**Planted-violation arms (permanent).** Three doctored copies of the page are fed through the
same extractor/executor in throwaway directories, and each MUST redden: (i) a
`benchweave-sdk frobnicate` line; (ii) `check --bogus-flag`; (iii) `check` against a
descriptor path that does not exist. The arms are cheap (each fails at its first command) and
run on every push — a checker that passes a planted violation is itself broken (the
`test_registry_census.py` planted-command pattern, and WS3's R-5c).

### 2.4 What this slice is not

No CLI changes. No scaffold changes. No rewrite of existing README/guide prose (STE100 for
existing surfaces is the #353 rewrite pass). No release walkthrough (the registry docs own
`package`/`submit`; this page names and points). No new dependency, job, or lane.

---

## 3. Single source and the boundary with siblings

Four documents touch the five-step workflow after this slice; each has one job and they
cross-link instead of copying:

| Surface | Audience | Owned content |
|---|---|---|
| `user_guide/getting-started.qmd` | first-timer, pre-project | the runnable sequence + expected output |
| README "Five steps" | scanner | the five-verb summary + link |
| `user_guide/plugin-sdk.qmd` | developer, in-project | the depth (per-pin standards, transport providers, capture, release) |
| WS3's generated `AGENTS.md` | agent, inside a scaffolded project | the in-project command loop |

The page duplicates only commands — and its commands are machine-pinned by §2.3, so the
duplication cannot silently diverge from the CLI. The tree diagram stays minimal precisely to
avoid a third full-tree copy (README and the guide keep theirs; the page names only what the
steps touch). Version claims stay where they are (README's baseline sentence, the guide's
version paragraph); the new pages claim none.

---

## 4. The R-6 acceptance rule (pre-committed before any implementation number is looked at)

**Ships iff ALL of:**

1. **Sequence green.** `tests/test_getting_started.py` executes the getting-started page's
   full extracted sequence (both the mainline and the UI section) with exit 0 and all §2.3
   assertions, in the existing `sdk` lane, on **3 of 3** OS lanes (ubuntu, macos, windows).
2. **Arms red.** All three planted-violation arms redden, demonstrated in the PR (and
   permanent afterwards).
3. **Registration clean.** Every CLI mention across the four pages names a registered
   subcommand; `preview-ui`'s cited flags exist.
4. **Prose literal-free.** Zero bare-semver hits in the four new pages and the README delta.
5. **Translations exactly two.** The module's substitution count for T1 is exactly one per
   run; the unrecognized-line abort exists and is demonstrated once in the PR (a deliberately
   malformed page copy reddens).
6. **Docs build.** `docs.yml`'s assemble renders the new pages and the landing flip
   (`homepage: user_guide`) in a local assemble run; the versioned buckets build.

**Killed if:** any planted arm passes (the checker is decorative — fix or kill); the sequence
redens on any OS lane for a cause the page itself caused (wrong command, wrong flag, wrong
path — as opposed to an environment fault, below); more than the two declared translations
prove necessary (the page's shape is wrong for machine execution — redesign, don't patch);
the landing flip breaks the assembled site with no clean fallback.

**Inconclusive — HOLD, not pass:** the sequence could not run for environment reasons on a
lane (wheel build failure, network-dependent resolution of the `[scaffold]`/test extras,
interpreter availability). A lane skipped is a lane failed; a green run with the module
deselected is a failed run. If exactly one OS lane is environment-faulted, the slice holds at
3-of-3 unmet and the fault is fixed or the lane's exclusion is a NEW named decision — never a
silent matrix shrink.

**RED discipline for the build:** the arms and the unrecognized-line abort are written FIRST
and demonstrated failing against a stub that accepts everything (proof they bite); then the
extractor/executor lands and the real page goes green. One additional live RED: edit the real
page's `check` command (drop the descriptor argument), show the lane red, restore, show green.

Denominators: "the sequence" = every ```sh``` block of `user_guide/getting-started.qmd`
(asserted ≥ 8 blocks); "the four pages" = getting-started, which-checkout, glossary,
troubleshooting; "3 of 3" = the ci.yml `sdk` matrix as it exists at build time.

---

## 5. Invariant, drift and tier impacts

- **`docs/internal/invariants.md` (this repo): no amendment required.** STD-1/STD-5 (vendored
  bytes): untouched. PKG-1 (self-containment): the module runs only this repo's wheel and
  public commands — no parent-checkout reach. PKG-2: no packaging change. SRF-1: no scaffold
  change. STD-4: the module's aborts use snake_case prefixes (`getting_started_*:`) consistent
  with the discipline; they are test-harness markers, not new CLI refusal paths — no invariant
  motion.
- **`docs/internal/drift-and-obligations.md` (this repo): one edit.** Row 1 (CLI-visible
  behavior) gains the getting-started page and `tests/test_getting_started.py` in its
  enumerated surfaces — a CLI change now knows the page moves with it or the lane reds. Row 6
  (behavioral suite) lists the module. No new row needed; the mechanism IS row 1's.
- **`docs/internal/release-review-matrix.md`: no motion.** No new version-bearing surface —
  the zero-literal rule (§2.3) enforces the pages' non-bearing posture mechanically.
- **Gateway bytes: none.** SDK-only PR; the pointer advance later is routine. The gateway's
  scaffold-content pins are untouched (no scaffold change).
- **On-disk format or schema: none** — the Tier-3 persisted-format rule does not trigger.
- **CI cost: no new jobs or lanes.** One module on the existing 3-OS `sdk` matrix; estimated
  +60–90 s per OS (a wheel build, two scaffolds, two venv installs — measured at build time;
  the estimate is this record's, the first measurement is the builder's). The `sdk` job's
  15-minute timeout has ample headroom. The docs lane renders four more small pages (seconds).
- **Standards-governor: not dispatched.** The diff touches no `standards/` bytes, no vendored
  tree, no plugin contract locks; the zero-literal rule keeps standard-version strings out of
  the diff by construction. The review re-derives this.
- **Review tier: 3 — by the keyword rule, not a path rule.** No Tier-3 path matches (no
  contracts, no state, no registry, no fixture lattice, no dependency change, no submodule
  pointer). The expected diff text carries the Tier-3 keywords `subprocess` and `sha256`:
  the test module's `subprocess` import and ~10–15 `subprocess.run` call sites, and `sha256`
  1–3 times (the inventory row-key assertions and the page's shown output keys). Per the
  rubric's keyword-rule interplay, text that carries the keyword buys the deep lane — honest
  here, since the module IS new executable code that CI will trust. The standing two-lane
  Tier-3 adversary rule applies.
- **Step-1 keyword scan (#254) over the expected diff** (four qmd pages, README/CLAUDE.md/
  index.qmd/great-docs.yml edits, `tests/test_getting_started.py`, the two drift-doc row
  edits, this record — the record itself contains the words in this paragraph, as WS3's did):
  `threading` 0, `asyncio` 0, `subprocess` 12 (est.), `sha256` 2 (est.), `hashlib` 0,
  `migrate` 0, `recovery` 0, `protection` 0 — the page and glossary prose deliberately say
  "checks" and "safe stop", never the protective vocabulary. Counts re-derived at review over
  the actual diff; estimates are declared as estimates.

---

## 6. Minimal FIRST slice, and the deferrals

**In (one PR, SDK repo, stacked on `feat/issue347-ws3-claude-assets`):** the four
`user_guide/` pages (document-writer leg, STE100); the `great-docs.yml` nav + `homepage`
change; the README link + section reorder; the CLAUDE.md and `index.qmd` pointer lines;
`tests/test_getting_started.py` (arms first, RED-then-GREEN per §4); the drift-doc row edits;
this design record as the first commit on the branch.

**Deferred, each with its home:**

1. **STE100 rewrite of EXISTING prose** (README bulk, guide, moved sections) — the #353
   findings table is the checklist; a follow-on increment under #347. This slice's moved
   sections are moved verbatim.
2. **Executing `preview-ui` in CI** — needs an interrupt/timeout harness around a
   serves-forever command; its own small design if wanted. Registration covers flag honesty
   meanwhile.
3. **Repo-wide UK/US spelling settlement** — new pages are American (ASD-STE100 dictionary
   convention); settling the existing corpus is the docs owner's call (it touches every
   published surface at once). Flagged to the maintainer with this record.
4. **Troubleshooting growth beyond the gap-log rows** — reactive rows under #347 as real
   first-timers report; the page's row shape is the template.
5. **Release-path walkthrough** (`package`/`submit`) — the registry documentation owns it;
   this page points. A walkthrough page is a separate increment if asked.
6. **Lane-time split** (ubuntu-full, others light) — only if the measured per-OS cost exceeds
   2 minutes; a named decision at that point, never a silent matrix shrink.
7. **Executing the troubleshooting page's failure-path commands** — failure injection is a
   different mechanism (each row's symptom must be REPRODUCED then fixed); separate design.
8. **`uv run --extra test` as an alternative taught path** — the page teaches one path only;
   the `uv run` row in troubleshooting covers the deviation (G8).

---

## 7. Precedent

- **Executing a guide's code against the real thing:** `tests/test_guide_serial_host.py` —
  extracts the user guide's serial-host example and drives a freshly scaffolded plugin through
  it "so the example cannot drift". WS4 is its shell-sequence generalization.
- **Docs reconciled against machine truth:** `tests/test_docs_reference.py` (great-docs.yml
  reference list ↔ importable public names); WS3's R-5b citation triangulation.
- **Wheel → fresh venv → `new` → `check` in CI:** the ci.yml installed-wheel-smoke step and
  the scaffold-and-check step — T1 is this pattern with the page as the command source.
- **Planted-violation arms permanent in CI:** `tests/test_registry_census.py`'s planted
  command; WS3's R-5c.
- **STE100 method:** issues #352/#353 — the rule set, the dictionary-candidate discipline,
  and the accuracy-over-rule clause the document-writer applies.
- **No-version-claim pages:** `index.qmd`'s own discipline, now enforced for the new pages.
- **Landing-page option:** great-docs.yml's documented `homepage: user_guide` ("the first
  user-guide page becomes the landing page").

Nothing invents architecture: the pages ride the existing qmd pipeline and nav list; the
checker rides the existing test lane; every check shape already holds somewhere in this tree.

---

## 8. Top risks, each with its falsifier

1. **The extractor rots into existence-only** (formatting changes silently empty the check).
   Falsifier: the ≥8-block floor, the per-step non-empty assertions, and three permanent
   planted arms — any of which reddens on rot.
2. **Translation drift** (the page rewords its install line; the swap goes stale). Falsifier:
   exactly-once substitution assertion + `getting_started_install_line_not_found:` — a reword
   REDS until the translation follows, which is the page and the harness moving together.
3. **The landing flip breaks the assembled site** (bucket assembly has its own nav handling).
   Falsifier: the builder's local `assemble_docs_site.py` run before the PR. Recorded
   fallback: keep `homepage: index` and put the getting-started link at the very top of
   `index.qmd` — a named fallback decision, not a silent one.
4. **Stack slippage** (WS2/WS3 land later or reshape). The page's content adapts (install
   line, tree); if WS4 must land first, the install line and tree revert to current-main
   shape and a small follow-up realigns — the docs-as-test reds on mismatch, which is the
   discipline working.
5. **Lane time exceeds estimate.** Falsifier: the build's own measurement; deferral 6's
   2-minute threshold decides.
6. **STE register quality** (the test checks commands, not language). Containment: the
   document-writer leg plus review; stated here so nobody claims the module covers register.
7. **Activation emulation diverges from real activation** (uv changes VIRTUAL_ENV discovery).
   Falsifier: the sequence reds at the install step. Containment: uv is pinned in CI by
   setup-uv; the two effects (VIRTUAL_ENV, PATH) are activation's entire contract with uv.
8. **Expected-output prose goes stale** (counts, hashes, paths quoted in the page). Falsifier:
   the zero-count/no-literal authoring rules plus key-shape-only assertions — the page quotes
   shapes, never values.

No hard blocker found. **BUILD.**
