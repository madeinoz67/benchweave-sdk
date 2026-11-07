# Design: scaffold CI workflow (lint + tests) — gateway issue #596

Date: 2026-11-07. Status: design only, pre-build. Author lane: increment-designer.

Tooling note: Gortex had no graph access for this checkout (daemon view_building
pending), so every citation below is from native reads of the working tree at
branch `fix/589-live-bringup-generic`, commit `8d46363`. All paths verified
against `git ls-files` (the working tree carries untracked iCloud ` 2` duplicate
files under `template/` and `tests/fixtures/`; the design ignores them — see
Risk R6).

## 0. The issue's premise, verified

The request: add a basic CI workflow (one lint job, one tests job, uv, Python
3.13) to the copier template so a scaffolded plugin project carries checks on
GitHub from its first push. Evidence base: a real plugin project's first PR
merged with an empty check rollup; its author added a local stopgap workflow
(lint job with a minimal ruff rule set, tests job with pytest on 3.13, both uv),
and the recorded lesson is that the lint job could not spawn ruff until the lint
extra was installed.

Verified facts this design builds on:

- The repository root IS the template: `copier.yml` (`_subdirectory: template`,
  `copier.yml:26`), and `template/` holds the rendered tree. There is no
  `.github` anywhere under `template/` — confirmed against tracked files.
- Packaging is automatic and presence-checked only: `pyproject.toml:96`
  force-includes `template` → `benchweave_sdk/scaffold_template/template`, and
  `hatch_build.py:18-22` (`SCAFFOLD_REQUIRED`) checks three members exist — no
  member enumeration, so a new file rides the wheel/sdist with no packaging
  change. Dotfiles ride it too (proven in-tree: `.copier-answers.yml.jinja` and
  `.claude/skills/**` render from the installed wheel — `ci.yml`'s
  installed-wheel smoke compares that render byte-for-byte against the fixture).
- The generated `pyproject.toml` (`template/pyproject.toml.jinja`) has a `test`
  extra (`benchweave-sdk=={{ sdk_version }}`, `pytest>=8.0`) and **no lint
  extra, no ruff config** — the issue's "install the lint extra" lesson
  therefore implies creating one.

## 1. Root cause, established not assumed

**1a. No workflow renders.** `template/` has no `.github/` — the gap is
absence, not breakage. Downstream consequence confirmed by the issue's own
evidence (a merged PR with no checks).

**1b. The lint-extra lesson, reproduced.** The template has no lint extra and no
ruff dependency anywhere in the generated project. A lint job that runs
`uv run ruff check .` without first installing an extra that carries ruff fails
with a missing-command error. In this design the fix has two halves: the
template gains `lint = ["ruff>=0.6"]`, and the workflow's install step runs
`uv sync --extra lint` BEFORE the ruff step (job steps are sequential; the
ordering is additionally pinned structurally — acceptance A2).

**1c. A defect the issue did not know about: the provider arm's test suite
cannot run under the generated `test` extra.** Measured in this design session
(2026-11-07, this author's measurements, commands below):

- Environment A — exactly what the current generated test extra installs:
  fresh venv, `uv pip install 'benchweave-sdk==0.24.0' 'pytest>=8.0'`, then
  pytest over each committed fixture arm with the fixture's `src` on
  PYTHONPATH:
  - base: 9/9 passed
  - ui: 10/10 passed
  - provider: **5/8 — 3 failed**, each with
    `RuntimeError: live_provider_backend_missing: install 'benchweave-sdk[server]'`
    raised from `src/benchweave_sdk_server/ftdi.py:181` (`_require_backend`,
    `ftdi.py:171-184`).
- Environment B — same but `benchweave-sdk[server]==0.24.0`: provider **8/8
  passed**.

Root cause: `_require_backend()` executes the pyftdi import unconditionally,
including on the scripted `driver_factory` path the generated suite's
shipped-double tests use (`template/tests/test_plugin.py.jinja:100-167` imports
`benchweave_sdk_server.ftdi`). pyftdi rides the SDK's `[server]` extra
(`pyproject.toml:60-65`), and the generated `test` extra installs plain
`benchweave-sdk==X`. The gap was invisible until now because the provider
project shape has never had CI, and the SDK's own suite runs the generated
provider tests inside the SDK environment (`tests/test_scaffold_copier.py:240`,
`test_the_generated_provider_suite_runs`), which CI populates with
`--extra server` — an environment-masked closure defect. Shipping the requested
tests job without fixing this ships a workflow that is red on day one for the
`--provider-transport` shape.

**1d. The template fails its own proposed lint.** Ruff over the rendered
fixtures with the minimal set this design selects (`--select E4,E7,E9,F`):

- base: clean; ui: clean;
- provider: **2 × F401** — `base64` and `example_plugin.protocol as proto`
  imported but unused in the rendered `tests/test_plugin.py`
  (`template/tests/test_plugin.py.jinja:3,12` of the provider arm).

The repo's own ruff gate cannot catch this: `pyproject.toml:130-133` excludes
`template` and `tests/fixtures/scaffold_expected` from this repository's lint.

## 2. The mechanism

### 2.1 New file: `template/.github/workflows/ci.yml` (verbatim copy, no `.jinja` suffix)

Copier renders only files ending in `.jinja` (`_templates_suffix` default);
unsuffixed members are copied verbatim — proven in-tree by `template/README.md`
and the byte-pinned `ftdi-control-provider.json`, which render byte-identical
into the fixtures. The workflow therefore needs NO suffix and NO substitution:

- nothing in it varies across the answer axes (`package_name`, `with_ui`,
  `provider_transport`, `sdk_version`, `otdp_version` — see §4);
- it contains no `${{ ... }}` GitHub expression syntax, so even a future rename
  to `.jinja` could not have its bytes eaten by a jinja render. This
  expression-free property is a stated template rule (acceptance A2 pins
  `${{` absent).

Exact bytes:

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  lint:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v7
      - name: Install uv
        uses: astral-sh/setup-uv@v10
        with:
          python-version: "3.13"
      - name: Install the lint extra
        # ruff rides the project's own lint extra; without this step ruff
        # cannot spawn (the first-run lesson, gateway issue #596).
        run: uv sync --extra lint
      - name: Lint
        run: uv run ruff check .

  tests:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7
      - name: Install uv
        uses: astral-sh/setup-uv@v10
        with:
          python-version: "3.13"
      - name: Install the test extra
        # The SDK pin in pyproject.toml [project.optional-dependencies].test is
        # the install source; no version is duplicated in this file.
        run: uv sync --extra test
      - name: Tests
        run: uv run pytest -q
```

Decisions inside that shape, each justified:

- **`uv sync` without `--locked`.** The template cannot ship a `uv.lock`: the
  pin is `{{ sdk_version }}`, substituted per render, so any committed lock
  would be stale for every project but one. The generated README already
  teaches the author to "pin dependencies with `uv lock`" — the workflow works
  whether or not the author later commits one. This is the one deliberate
  deviation from this repository's own CI shape (`.github/workflows/ci.yml:49`
  uses `--locked`), and it is forced by the template's version substitution.
- **Action major tags, not SHAs.** This repo pins SHAs for its own
  supply-chain posture; the generated workflow is a downstream-owned surface
  where SHA pinning would turn every action release into a template bump (and
  each bump into conflict markers for every author who edited their workflow —
  see §4.3). Major tags (`checkout@v7`, `setup-uv@v10`, current majors per this
  repo's pins at `ci.yml:37,42`) keep update churn near zero. Trade-off and its
  falsifier are in Risk R2.
  **Maintainer ruling 2026-11-07: major tags ACCEPTED, and this is a decided
  trade-off, not an open question.** Generated projects are author-owned; both
  actions are first-party (`actions/checkout`, `astral-sh/setup-uv`); SHA
  pinning would make every `copier update` carry churn for a threat the author
  does not control. The falsifier stays Risk R2 (a v-major breaking change
  reding every generated repo at once), and D5 is the reversal switch.
- **`permissions: contents: read`** — least privilege, mirrors the SDK's own
  workflow (`ci.yml:8-9`).
- **Triggers `push: branches: [main]` + `pull_request`** — the SDK's own shape;
  PRs are where the empty-rollup wound lived, and the initial push of a fresh
  scaffold to `main` runs both jobs once, so the rollup is non-empty from
  commit one.
- **No artifact upload.** Nothing consumes one: the merge gate reads
  `gh pr checks` rollup statuses, `pytest -q`'s log output suffices for an
  8-10 test suite, and an upload step would add an action and a retention
  policy for evidence with no reader. Deferred (§6, D4) until a consumer
  exists.

### 2.2 `template/pyproject.toml.jinja` — lint extra, pinned minimal select, provider-conditional test extra

```toml
[project.optional-dependencies]
{%- if provider_transport %}
# The generated suite's shipped driver double drives the ftdi session builder,
# which imports the pyftdi backend (benchweave-sdk's server extra) even on the
# scripted path; the serial default's suite needs neither.
test = ["benchweave-sdk[server]=={{ sdk_version }}", "pytest>=8.0"]
{%- else %}
test = ["benchweave-sdk=={{ sdk_version }}", "pytest>=8.0"]
{%- endif %}
lint = ["ruff>=0.6"]

[tool.ruff.lint]
# The minimal starter set: ruff's defaults, selected explicitly so a ruff
# upgrade cannot silently widen the gate.
select = ["E4", "E7", "E9", "F"]
```

- The `lint` extra is the issue's lesson made structural: the workflow installs
  it, ruff comes from it, and nothing else carries ruff.
- The explicit `select` freezes ruff's default set (pyflakes + the core
  pycodestyle error classes) so a future ruff default change cannot silently
  widen or narrow the generated gate. No `line-length`/`target-version`: both
  are inert with E501/UP unselected — inert config is noise.
- The provider conditional is the §1c fix at template level: each arm's CI is
  green on day one; the base/ui shapes stay dependency-light (no web stack for
  a serial demo plugin). Consumers of the pin stay correct by construction:
  `_PIN_RE` (`src/benchweave_sdk/scaffold.py:230-234`) tolerates an extras
  clause, `recorded_sdk_version` documents that tolerance
  (`scaffold.py:296-299`), so `doctor` and `adopt` read the `[server]` pin
  unchanged.
- `ruff>=0.6` mirrors the SDK dev group's floor (`pyproject.toml:110`).

### 2.3 `template/tests/test_plugin.py.jinja` — remove the two provider-arm F401s

Delete `import base64` and `from {{ package_name }} import protocol as proto`
from the `{%- if provider_transport -%}` arm (the rendered suite's two unused
imports, §1d). Byte change; flows through fixture regen.

### 2.4 `template/AI-GUIDE.md.jinja` — one clause in "Project layout"

The layout enumeration ("The generated project contains README.md, this
AI-GUIDE.md, CLAUDE.md …, tests/test_plugin.py, and src/<package>/ with …")
gains the workflow: a GitHub Actions workflow at `.github/workflows/ci.yml`
runs lint and tests on every push and pull request. Exact wording in ASD-STE100
register via the `document-writer` agent at build; no new refusal codes,
subcommands or guide headings, so the R-5b checker (`tests/test_agent_assets.py`)
is unaffected — its asset set is exactly AGENTS.md + the five skills, which this
change does not touch.

### 2.5 Fixtures — regenerate all three arms (mechanical)

`tests/fixtures/scaffold_expected/{base,ui,provider}/` each gain
`.github/workflows/ci.yml` (identical bytes) and the new-look `pyproject.toml`;
the provider arm additionally gains the `[server]` pin and loses the two
imports; all arms' AI-GUIDE gains the clause. Regeneration is the existing
mechanism: the manual procedure in `tests/test_scaffold_copier.py:12-26` (or
`make release-cut` at a version bump). `.gitattributes` already pins
`template/**` and the fixture tree to `eol=lf` (asserted by
`tests/test_scaffold_copier.py:73-75`), and `_enforce_lf` normalizes the render
(`scaffold.py:162-195`), so the YAML is LF everywhere.

### 2.6 New standing arms in `tests/test_scaffold_copier.py` (beside the R-2 arms)

1. **Workflow structure arm.** Parse the base arm's
   `.github/workflows/ci.yml` with `yaml.safe_load` (PyYAML is already a test
   dependency via copier — precedent `tests/test_scaffold_update.py:44`);
   assert: exactly jobs `{lint, tests}`; both `ubuntu-latest`; both carry
   setup-uv with `python-version: "3.13"`; in each job the `uv sync --extra
   <x>` step's index is strictly before the run step's index
   (`ruff check .` / `pytest -q`); top-level `permissions.contents == "read"`;
   triggers include `pull_request`; the raw text contains no `${{`; and the
   three arms' workflow files are byte-identical.
2. **Lint-set arm.** For each `fixture_arms()` arm, parse that arm's rendered
   `pyproject.toml` `[tool.ruff.lint].select` with `tomllib` and run
   `ruff check --select <those codes> --no-cache <arm>/src <arm>/tests` via
   subprocess; assert exit 0. The select list is READ from the rendered
   machine source, never restated — the arm cannot drift from what the
   generated CI actually runs. This is the standing regression for §1d.

### 2.7 This repo's own CI — two extensions

- `ci.yml`, "Scaffold and check a plugin end-to-end" step (all three OS lanes):
  after the existing check/check-ui lines, run the generated project's lint
  path verbatim — `cd` into the scaffolded project, `uv sync --extra lint`,
  `uv run ruff check .` (2 lines). This executes the workflow's exact command
  sequence at PR time, on every push.
- `publish.yml`, `smoke` job (ubuntu-only, the `server-smoke` precedent at
  `publish.yml:116`): after `new`, run the generated tests path against the
  just-built wheel — `UV_FIND_LINKS` pointing at the downloaded `dist` dir,
  `uv sync --extra test`, `uv run pytest -q` — for the `--with-ui` scaffold
  AND a `--provider-transport` scaffold. Pre-publish, PyPI does not carry the
  new version, so find-links is the only resolver for the pin and the exact
  `==` pin resolves to the wheel that is about to ship. This is the only place
  the tests job's full dependency closure executes against a real pin.

## 3. Precedent

- **The workflow shape extends this repo's own CI** (`setup-uv` +
  python-version 3.13 + `uv sync --extra …` + `uv run`): same skeleton, minus
  `--locked` (forced, §2.2), minus the OS matrix (the generated suite is
  pure-Python mock rehearsal; the SDK's 3-OS matrix exists to prove the SDK's
  own portability, not the plugin's).
- **The lint/settle mechanics extend the extras pattern**: `[signing]`,
  `[server]`, `[scaffold]` extras on the SDK; the generated project gains
  `lint` beside its existing `test`.
- **The conditional test extra extends the template's existing jinja
  conditionals** (`template/tests/test_plugin.py.jinja` is built from them);
  this is the first conditional in `pyproject.toml.jinja`, which is why its
  consumer-tolerance (`_PIN_RE`) was verified rather than assumed.
- **The managed-file posture** (template-owned, conflict-marked on author edit,
  refreshed by `copier update`) is the WS3 agent-asset posture
  (`docs/internal/invariants.md` SRF-1) — the workflow joins that set; it is
  deliberately NOT added to `_skip_if_exists` (`copier.yml:42`), so scaffold
  fixes propagate and author edits conflict-mark rather than silently lose
  (pinned semantics: `tests/test_scaffold_update.py` A2/A5).

## 4. The variant axes, decided from the generated shapes

1. **`package_name`** — nowhere referenced by the workflow (lint/tests operate
   on `.`). Invariant.
2. **`with_ui`** — adds UI files and one test; both jobs behave identically.
   Measured green under the plain extra (§1c: 10/10). Invariant.
3. **`provider_transport`** — the ONE axis with a real difference: the suite's
   ftdi imports require pyftdi (§1c). The workflow file itself stays invariant
   (both jobs still `uv sync --extra test`); the DIFFERENCE lives in the
   rendered `pyproject.toml` test extra (`benchweave-sdk[server]==`), which is
   the pin's own business, not the workflow's. This is the right split: the
   workflow stays byte-identical across all arms (asserted by A2), and the
   dependency closure travels with the pin that declares it.
4. **`sdk_version` / `otdp_version`** — appear only inside the rendered
   pyproject/answers, never in the workflow. Invariant.
5. **`_exclude`** (`copier.yml:33-34`) — excludes only the provider contract
   from the serial shape; `.github/` is unconditional. No interaction.

## 5. Interface consequences (SRF-1) — everything that moves

This is an interface change to scaffold output; the PR says so (obligation 2,
`docs/internal/drift-and-obligations.md`).

This repository:

| Surface | Motion |
|---|---|
| `template/.github/workflows/ci.yml` | NEW (§2.1) |
| `template/pyproject.toml.jinja` | lint extra + select + provider conditional (§2.2) |
| `template/tests/test_plugin.py.jinja` | provider arm: two unused imports removed (§2.3) |
| `template/AI-GUIDE.md.jinja` | layout clause (§2.4) |
| `tests/fixtures/scaffold_expected/{base,ui,provider}` | regenerated (§2.5) |
| `tests/test_scaffold_copier.py` | two new arms (§2.6) |
| `.github/workflows/ci.yml` (SDK's own) | end-to-end lint arm (§2.7) |
| `.github/workflows/publish.yml` | smoke: generated tests arm, ui+provider, ubuntu (§2.7) |
| `README.md` (SDK) | generated-tree diagram (~lines 118-155) gains the workflow row; five-steps step 2 (~line 40) gains a clause |
| `user_guide/plugin-sdk.qmd` | tree diagram (lines 63-85) gains the row; §1 prose gains a sentence |
| `docs/internal/invariants.md` | SRF-1 amendment (§7) |
| `docs/internal/drift-and-obligations.md` | obligation 2 surfaces + CI map rows + gateway pairing note |

Consciously unchanged: `copier.yml` (no new questions, no skip-list change),
`scaffold.py` / `scaffold_update.py` (member walks are generic; `_PIN_RE`
already tolerates extras clauses), `template/README.md` (its instruction line
stays true; the AI-GUIDE carries layout), the vendored standards tree and lock
(untouched — this is NOT a Tier-3 change in the review rubric), this repo's
ruff/mypy config (excludes already cover template and fixtures).

Main repository (pairs via TWO-1, in the pointer PR, per the in-tree comment
"an accidental one fails here" / "Re-pinned at the SDK 0.7.0 copier render"):

- `tests/sdk/test_scaffold_skills.py` — `PINNED_FILE_SET` gains
  `.github/workflows/ci.yml` (sorted between `.copier-answers.yml` and
  `AGENTS.md`). Without this edit the gateway's `sdk` lane reds at the pointer
  bump; with it, the pin keeps its shape-alarm role.
- `tests/sdk/test_presentation_cli.py:415-429` — rglob self-parity between two
  scaffolds; flows automatically, no edit.
- `tests/sdk/test_plugin_developer_skill_content.py` — schema-field pins, not
  file sets; unaffected.

Downstream: every existing plugin project gains the workflow and the lint extra
on its next `copier update` (new-file apply is clean; an author who already
hand-added a workflow at the SAME path gets conflict markers — the managed-file
posture; a different filename, the stopgap case, coexists). Existing projects'
`pyproject.toml` is skip-protected, so the extras reach new projects only —
the documented §2.2 intent.

## 6. Minimal first increment and the deferral table

The first increment is §2.1-§2.7 plus the SRF-1 amendment. Zero production-code
changes in `src/` (the template is content; the closure fix is declarative).

| # | Deferred | Carrier |
|---|---|---|
| D1 | The deep closure fix — let the scripted `driver_factory` path skip `_require_backend()` so the shipped double needs no pyftdi | **Gateway issue #597** (filed 2026-11-07, body names #596 as its carrier and states the reopen trigger). The carrier named here at design time — "the in-flight #589 lane owns `ftdi.py`" — was FALSE by build time: #589 completed all seven slices, `main` is its last merge commit, and no lane owns `ftdi.py`. When #597 lands, the provider test extra drops `[server]` (template edit + fixture regen) |
| D2 | A narrower SDK extra (e.g. `[ftdi]`) so the provider closure avoids the web stack | SDK packaging issue; needs a public-extra ruling (a new extra name is API) |
| D3 | `--locked` / committed-`uv.lock` posture for generated CI | Guide editorial pass (the guide already teaches retaining the lock); workflow changes only when a lock-shipping decision is made |
| D4 | Generated-CI extras: concurrency cancel, junitxml artifact upload, OS matrix | Template issue, when a consumer exists |
| D5 | SHA-pinning actions in the generated workflow | **Maintainer ruling 2026-11-07: ACCEPTED as a trade-off**, recorded in §2.1 — not an open question. Reversal switch if a v-major breaking change reds generated repos at once |
| D6 | Migrating the stopgap workflow on the real plugin project to the template's | Operational, author-side; next `copier update` |

## 7. Invariant impacts

- **SRF-1 (amendment).** The scaffold interface now includes: the generated
  `.github/workflows/ci.yml` (two jobs, expression-free, byte-identical across
  all arms — rendered by verbatim copy, never jinja), the `lint` extra with the
  explicitly-selected minimal ruff set, and the arm-conditional `test` extra.
  New clause worth its own sentence: **each arm's generated `test` extra must
  install everything that arm's generated suite imports** (the provider arm
  pins `benchweave-sdk[server]` because its shipped-double tests import
  `benchweave_sdk_server.ftdi`, whose backend import is unconditional). Pinned
  by §2.7's publish smoke arm at release time and disclosed as residual at PR
  time (no offline import-graph arm — executing the suite IS the honest pin).
- **STD-1..6, PKG-1/2/3, SRF-2/3/4/5, TWO-1** — unchanged in substance; PKG-2's
  template carve-out already covers the new member; TWO-1 gains the pairing
  note above (obligation 8).
- No new refusal prefixes (STD-4): the design adds no refusal path anywhere.

## 8. Pre-committed acceptance rule

The §1 measurements were design exploration against the CURRENT tree (defect
baseline). The arms below are fixed NOW, before the increment is built; the
build's RED/GREEN evidence is the measurement. Every arm names its denominator
and both kill directions.

- **A1 — shape (existing R-2 machinery).** After regen,
  `uv run pytest tests/test_scaffold_copier.py -q` is green: all 3 arms'
  renders byte-identical to fixtures, every file compared (full sets, not
  samples; base arm = 21→22 files, provider = 22→23, ui = its current set +1;
  counts read from the run, never a summary line). SHIP: green. KILL: any
  file-set or byte mismatch. INCONCLUSIVE: none (offline, deterministic).
- **A2 — workflow structure (new offline arm, §2.6.1).** Written FIRST, while
  the template still lacks the file: it must FAIL on the missing file
  (collected count > 0, red), then pass once the template lands. Mutation
  control pasted in the PR: swap the sync/run step order in a scratch copy →
  the order assertion reds; plant `${{` in a scratch copy → the
  expression-free assertion reds. SHIP: green after template lands. KILL: the
  arm passes without the template file existing (arm is broken — vacuous), or
  any structural assertion red against the landed template.
- **A3 — generated code passes the generated lint (new arm, §2.6.2).** RED
  control is in-tree TODAY: with the current provider template the arm must
  fail (the two F401s, §1d — reproduce the RED before fixing the template),
  then pass after §2.3. SHIP: 3 arms × exit 0. KILL: any ruff finding. The
  select list is read from each arm's rendered pyproject (machine source), so
  an arm that lints a different set than the generated CI runs is itself a
  kill.
- **A4 — lint job executes (ci.yml extension, §2.7).** The extended
  end-to-end step greens on ubuntu/macos/windows lanes (3 lanes, exit 0).
  SHIP: green. KILL: nonzero exit with a ruff finding or missing command — a
  real kill. INCONCLUSIVE (rerun once, then judge): failure text shows
  network/registry resolution errors (PyPI unreachable, ruff resolution) —
  that is infrastructure, not the mechanism.
- **A5 — tests job executes with a real pin (publish.yml smoke extension,
  §2.7).** Per release: 2 shapes (ui, provider), each `uv sync --extra test`
  resolves the `==` pin from find-links (the just-built wheel) and
  `uv run pytest -q` exits 0 with collected counts ≥ 10 (ui) and ≥ 8
  (provider). SHIP: both green with counts. KILL: nonzero exit, or exit 5 / 0
  collected (`no tests ran` is a FAILED check). INCONCLUSIVE: a resolution
  error naming PyPI (the pin must resolve locally via find-links) — treat as
  wiring, fix the step, rerun.
- **A6 — the issue's own wound closes (post-merge, observational).** The first
  PR on the first project scaffolded from the released template shows
  `ci / lint` and `ci / tests` in its check rollup, both reporting. Denominator:
  1 repository, 1 PR, 2 check rows. SHIP: both rows present and green on an
  untouched scaffold. KILL: empty rollup or a red job with no author change.
  This arm runs after release; it cannot gate the merge, and saying so is part
  of the rule.

CI cost: +~30s × 3 lanes at PR time (A4); +~60-90s × 1 lane per release (A5).
No new jobs, no new markers.

## 9. Top risks and their falsifiers

- **R1 — the `[server]` pin is heavy** (fastapi/fastmcp/uvicorn ride into a
  provider project's CI for a rehearsal). Falsifier/exit: D1 or D2 lands and
  the extra narrows; if the maintainer rejects the weight now, the increment
  splits (workflow for base/ui + D1 promoted) — but shipping red provider CI
  is not an option A2-A5 would pass.
- **R2 — major action tags drift** (a v8 checkout breaking change reds every
  generated repo at once). Falsifier: A6-style observation plus dependabot on
  downstream repos (which the workflow files enable). Accepted trade-off
  (§2.1); D5 is the reversal switch.
- **R3 — gateway lane reds at pointer time** if `PINNED_FILE_SET` edit misses
  the pointer PR. Falsifier: the gateway `sdk` lane itself — that red IS the
  pin working; the pairing note in the PR body is the prevention.
- **R4 — rival template work**: `origin/chore/standards-sync-450` carries 1
  commit touching `template/`/fixtures (a standards-sync regen). Falsifier:
  rebase conflicts at build time; the fixture regen is idempotent either way.
- **R5 — `uv sync` lockless resolution drift** (ruff/patch moves under a
  `>=` floor between runs). Bounded by the extras' floors and the `==` SDK
  pin; the author's committed lock (when present) governs. Falsifier: an A4/A5
  failure that pins a moving dependency — then floors tighten.
- **R6 — local-build hazard, pre-existing and out of scope**: the untracked
  iCloud ` 2` duplicates under `template/` and the fixtures ride any wheel
  built from THIS dirty working tree (the force-include is filesystem-based,
  `hatch_build.py`'s presence check cannot see tracking state). Releases build
  from clean CI checkouts, so published artifacts are safe; the design's build
  agent must `git add` the new template file and be aware locals builds here
  are not evidence. Falsifier: `git diff --stat` on the built sdist listing a
  ` 2` member.

## 10. Honest notes

- The issue's stated mechanism ("the tests job uses pytest on Python 3.13")
  is correct for the serial and UI shapes and INCOMPLETE for the provider
  shape (§1c). Correcting the issue's own picture: the workflow alone was
  never sufficient; the pin's dependency closure needed fixing too. That is
  the substance of §2.2's conditional.
- The two F401s (§1d) are a template defect this increment fixes because the
  lint it ships would otherwise fail on its own first run — found by running
  the proposed gate over the committed fixtures, not by reading.
- No production code in `src/` changes. If review wants the ftdi fix instead
  of the `[server]` pin, that is D1 promoted — a different, larger increment
  that collides with the in-flight #589 lane by design.

## 11. Build notes (2026-11-07) — deviations found on contact with the code

1. **§2.7's ci.yml lane needed a wheel, not just the two lines.** The record
   assumed `uv sync --extra lint` in the generated project resolves only the
   lint extra. It does not: **uv locks every extra on any sync**, so the
   `test` extra's `benchweave-sdk=={{ sdk_version }}` pin is resolved too.
   Measured: with the pin rewritten to `99.99.99`, `uv sync --extra lint
   --dry-run` refuses — "there is no version of benchweave-sdk==99.99.99 …
   your project's requirements are unsatisfiable". Unmitigated, that reds
   `main` for the whole window between a version-bump commit and the release
   that publishes it. The step therefore builds this checkout's wheel and
   exports `UV_FIND_LINKS` before syncing — the record's own A5 mechanism,
   applied one lane earlier. The generated **workflow** is unaffected: a
   generated project's pin always names an already-published SDK version.
2. **D1's carrier was wrong** (see the deferral table): #589 completed before
   this build; #597 now carries the reopen trigger.
3. **The A3 arm asserts the `lint` extra exists**, one line beyond §2.6.2's
   literal text. Without it the generated workflow's `uv sync --extra lint`
   fails at run time and nothing offline notices; with it, the arm reds at PR
   time instead.
4. **§2.1's `ci.yml:37,42` citation still names the right majors** after a
   dependabot merge moved `astral-sh/setup-uv` to its `v10.3.3` SHA: the
   generated workflow carries majors (`@v7`, `@v10`), and the bump did not
   change either major.
