# Design: scaffold CI workflow (lint + tests) — gateway issue #596

Date: 2026-11-07. Status: design only, pre-build. Author lane: increment-designer.

Provenance note. A first draft of this record was written against the stale
branch `fix/589-live-bringup-generic` at `8d46363` (and briefly, wrongly,
filed in that checkout; removed). Its anchors' staleness was bounded by diff,
then every anchor was RE-READ at `origin/main ff87c76` in the worktree
`.worktrees/design-596-c4d2` (branch `design-596`), and every §1 measurement
below was run from that worktree against a wheel built from it. Two diff
commands agree on the boundary: over the code/doc surfaces
(`template/ copier.yml hatch_build.py scaffold.py ftdi.py serial.py
test_scaffold_copier.py test_scaffold_update.py ci.yml publish.yml
pyproject.toml README.md user_guide/plugin-sdk.qmd docs/internal/*`) the
template surface is byte-identical and `ftdi.py` (+653), `serial.py` (+68),
the internal docs, the guide and `ci.yml` moved — all re-anchored below; over
the template/fixture surface (`template/ copier.yml hatch_build.py
pyproject.toml tests/test_agent_assets.py tests/test_getting_started.py
tests/test_scaffold_update.py tests/test_hatch_scaffold_template.py
tests/fixtures/`) exactly ONE line differs — root `pyproject.toml`'s
unrelated `live_ftdi` pytest marker entry. The first round's tool runs
churned `.ruff_cache`/`.pytest_cache` in the stale checkout (disclosed; the
linted fixtures and installed-wheel measurements were byte-identical there,
and all second-round evidence is from the worktree). A 496-line first draft
of this record is what the builder lane committed as `b47b342` on
`build-596` — that text is SUPERSEDED by this document. Gortex had no graph
access for this checkout; all reads are native.

## 0. The issue's premise and the reference implementation

The request: add a basic CI workflow (one lint job, one tests job, uv, Python
3.13) to the copier template so a scaffolded plugin project carries checks on
GitHub from its first push. Evidence base: a real plugin project (unnamed per
the public-repo rule) whose first PR merged with an empty check rollup; its
author added a stopgap workflow, and recorded the lesson that the lint job
could not spawn ruff until the lint extra was installed.

**The reference implementation** — the working workflow from that project,
clean-read from the real repository — is field evidence with one verbatim RED
and one GREEN run:

- RED run (job `lint`): `error: Failed to spawn: ruff / cause: No such file or
  directory (os error 2)` — **exit code 2**. Root cause: bare `uv run ruff`
  installs the project WITHOUT extras, and ruff lives only in the lint extra.
- The fix was one line: `uv run --extra lint ruff check .` (GREEN run).
  **Their stated ordering law: the extra must be named on the SAME command
  line that spawns the tool.** A separate `uv sync --extra lint` before a bare
  `uv run ruff` also works; bare `uv run ruff` after nothing is the trap.
- Their file: jobs `lint` and `tests`, checkout@v4, setup-uv@v5 (floating),
  `uv python install 3.13`; lint `uv run --extra lint ruff check .`; tests
  `uv sync --extra test` then `uv run pytest -q`; push to main + pull_request.
- Their ruff config: `select = ["E4", "E7", "E9", "F"]`, `line-length = 100`,
  `target-version = "py313"`, `extend-exclude = ["docs"]`. Their SDK pin:
  `benchweave-sdk[scaffold,server]==<version>`, once, inside the test extra;
  the workflow never repeats a version.

Facts of ours, verified at `ff87c76` (both of the lead's load-bearing checks
re-confirmed from this worktree, not on anyone's say-so):

- The repository root IS the template: `copier.yml` (`_subdirectory: template`,
  `copier.yml:26`), `template/` holds the rendered tree — 22 tracked files,
  **zero `.github` members**.
- Packaging is automatic and presence-checked only: `pyproject.toml`'s
  force-include maps `template` into the wheel;
  `hatch_build.py::SCAFFOLD_REQUIRED` checks three members exist — no member
  enumeration, so a new file rides the wheel/sdist with no packaging change.
  Dotfiles ride it (`.copier-answers.yml.jinja` and `.claude/skills/**` render
  from the installed wheel — proven by `ci.yml`'s installed-wheel smoke
  comparing that render byte-for-byte against the fixture).
- `template/pyproject.toml.jinja` has **no `[tool.ruff]` section and no `lint`
  extra**. Its only extra is
  `test = ["benchweave-sdk=={{ sdk_version }}", "pytest>=8.0"]`. So the
  reference's one-line fix would fail in our generated project today: there is
  no `lint` extra to name. The issue is therefore not "add a workflow file" but
  "make the generated project capable of running the workflow".

## 1. Root causes, established on main's bytes

**1a. No workflow renders.** Absence, not breakage; the downstream consequence
is the issue's own evidence (a merged PR with no checks).

**1b. No lint surface exists to install.** No `lint` extra, no ruff dependency,
no `[tool.ruff]`. `uv run --extra lint ruff check .` against a project
generated by the current template fails at uv's "extra not defined" usage
error (exit 2) before ruff is ever consulted.

**1c. The births-red trap — locally corroborated.** The reference measured 37
findings from ruff 0.17.4 with NO explicit `select` on their never-linted
tree. Corroboration on OUR pristine scaffold (this worktree, ruff 0.17.3,
`--isolated`, base fixture): **3 × I001 unsorted-imports** — ruff 0.17's
default select is wider than the historical E4/E7/E9/F (it includes isort).
A template that ships ruff without an explicit rule set makes every generated
project red at birth. The explicit select is mandatory, not cosmetic.

**1d. The template fails the minimal lint it should ship.** Ruff
`--select E4,E7,E9,F` over the committed fixtures (this worktree): base clean,
ui clean, provider **2 × F401** — `base64` and `example_plugin.protocol as
proto` imported but unused in the rendered provider `tests/test_plugin.py`
(`template/tests/test_plugin.py.jinja` provider arm, import lines 2 and 11 of
the rendered file). The repo's own gate cannot catch this: root
`pyproject.toml`'s ruff `extend-exclude` covers `template` and
`tests/fixtures/scaffold_expected`.

**1e. The provider arm's test suite cannot run under the generated test
extra.** Measured against a wheel BUILT FROM THIS WORKTREE (`uv build`,
main's bytes), installing exactly what the current extra declares
(`benchweave-sdk==0.24.0` + pytest) and running each committed fixture arm
with its `src` on PYTHONPATH:

| Arm | plain pin (current template) | with `[server]` |
|---|---|---|
| base | 9/9 passed | — |
| ui | 10/10 passed | — |
| provider | **5/8 — 3 failed** | 8/8 passed |

The three failures are `RuntimeError: live_provider_backend_missing:` raised
by `_require_backend()` (`src/benchweave_sdk_server/ftdi.py:171-207`). On
main, `verify_ftdi_plugin` (`ftdi.py:1556`) calls `_require_backend()`
unconditionally (`ftdi.py:1570`) — deliberately ordered after the contract
checks ("a missing extra is a deployment error and must never mask a contract
refusal") — and `ftdi_plugin_session` (`ftdi.py:2066`) runs that verify inside
its per-connection `factory` for the scripted `driver_factory` path too:
`session.rehearsal = driver_factory is not None` (`ftdi.py:2135`) only MARKS
the session, it does not skip the backend check. pyftdi rides the SDK's
`[server]` extra. The gap was invisible because the provider shape has never
had CI, and the SDK's own suite runs the generated provider tests inside the
SDK environment (`tests/test_scaffold_copier.py`,
`test_the_generated_provider_suite_runs`), which CI populates with
`--extra server`. An environment-masked closure defect: shipping the requested
tests job without fixing it ships CI that is red on day one for
`--provider-transport` projects.

## 2. The mechanism

### 2.1 New file: `template/.github/workflows/ci.yml` (verbatim copy, no `.jinja` suffix)

Copier renders only files ending in `.jinja`; unsuffixed members are copied
verbatim — proven in-tree by `template/README.md` and the byte-pinned
`ftdi-control-provider.json`. The workflow needs no suffix and no
substitution: nothing in it varies across the answer axes (§4), and it is kept
entirely free of `${{ ... }}` GitHub expression syntax so that even a future
suffix rename could not have its bytes eaten by a jinja render. Exact bytes:

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
      - name: Lint
        # The extra rides the SAME command line that spawns ruff: a bare
        # `uv run ruff` installs no extras and ruff cannot spawn (the
        # first-run lesson, gateway issue #596 — exit 2, not findings).
        run: uv run --extra lint ruff check .

  tests:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7
      - name: Install uv
        uses: astral-sh/setup-uv@v10
        with:
          python-version: "3.13"
      - name: Tests
        # The same law: the extra is named where the tool spawns.
        run: uv run --extra test pytest -q
```

Where this follows the reference and where it deliberately does not:

- **Adopted from the reference, as the load-bearing choice**: the extra named
  on the same command line that spawns the tool, in BOTH jobs. This is the
  field-proven fix shape (their RED→GREEN) and it makes the ordering failure
  structurally hard: the extra and the spawn are one token apart, not two
  steps apart. The tests job uses the single-line `uv run --extra test
  pytest -q` rather than their sync-then-run pair — their green run proves
  both forms work, but one law stated one way in both jobs is what the
  structural arm (A2) can pin, and it is one step fewer.
- **Action versions**: current majors (`checkout@v7`, `setup-uv@v10`, per this
  repo's own pinned `# v7.0.1` / `# v10.3.2` comments) rather than the
  reference's v4/v5 — those are that repository's age, not a choice. Still
  major tags, not SHAs: a downstream-owned surface where SHA pinning would
  turn every action release into a template bump, and every bump into
  conflict markers for authors who edited their workflow (§4.3). The
  trade-off and its reversal switch stay open as D5.
- **`python-version: "3.13"` via the setup-uv input** instead of their
  separate `uv python install 3.13` step — one fewer step, same effect,
  proven in this repo's own CI on three OS lanes.
- **`permissions: contents: read` and timeouts** — additions; least privilege
  and bounded runs, matching this repo's own workflow. The reference has
  neither (a gap they flagged, not a choice to inherit).
- **No artifact upload, no concurrency group** — nothing consumes an artifact
  (the merge gate reads check-rollup statuses; `pytest -q` log output covers
  an 8-10 test suite), and redundant runs cost minutes, not correctness.
  Both deferred (D4) until a consumer or a cost problem exists.

### 2.2 `template/pyproject.toml.jinja` — lint extra, explicit select, provider-conditional test extra

```toml
[project.optional-dependencies]
{%- if provider_transport %}
# The generated suite's shipped driver double drives the ftdi session builder,
# which verifies the pinned contract through the pyftdi backend (the SDK's
# server extra) even on the scripted path; the serial default needs neither.
test = ["benchweave-sdk[server]=={{ sdk_version }}", "pytest>=8.0"]
{%- else %}
test = ["benchweave-sdk=={{ sdk_version }}", "pytest>=8.0"]
{%- endif %}
lint = ["ruff>=0.6"]

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
# The minimal starter set, pinned explicitly: ruff 0.17's DEFAULT select is
# wider (isort included — 3 I001 findings on the pristine scaffold), so an
# unconfigured ruff makes every generated project red at birth.
select = ["E4", "E7", "E9", "F"]
```

- The `lint` extra is the issue's lesson made structural, and it is an
  **extra, not a `[dependency-groups]` dev group** — the one alternative the
  reference raised. Decided against the dev group: the generated README's own
  documented install is extra-based (`uv pip install -e '.[test]'`), and
  `uv pip` cannot install PEP 735 dependency groups — a dev-group ruff would
  be uninstallable through the path the scaffold itself teaches; extras also
  serve pip-based authors. The footgun the dev group would remove is instead
  closed structurally: the workflow names the extra on the spawn line, and A2
  pins that no bare `uv run <tool>` step exists.
- `select` matches the reference's minimal set verbatim; measured 0 findings
  on base and ui, and 2 fixable F401 on provider (fixed in §2.3).
- `line-length = 100` and `target-version = "py313"` are carried, and the
  carry is LOAD-BEARING, not cosmetic. Both keys are inert under the minimal
  select (no E501 and no UP rules selected — nothing reads either value
  today). Measured on the rendered fixture code: lines longer than 88 exist
  in every arm (base 13, ui 13, provider 8) and lines longer than 100 in
  none (`awk 'length > N'` per arm), and `ruff --select E --line-length 100`
  returns 0 E501. So an author who widens the select to full E inherits a
  sane bound and stays green; WITHOUT the key they inherit ruff's default 88
  and birth red from the scaffold's own bytes. Do not remove these keys as
  "inert", and do not lower the length below 100 — the >88 counts are the
  measured reason both hold.
- **`extend-exclude = ["docs"]` is NOT carried.** The reference excludes
  `docs` because THEIR repository carries author-added docs with one-liner
  helper scripts; our scaffold generates no `docs/` tree. Copying the
  exclusion would exclude nothing and teach authors a rule they did not need.
- The provider conditional is the §1e fix at template level: each arm's CI is
  green on day one while base/ui stay dependency-light (no web stack for a
  serial demo plugin). Pin consumers stay correct by construction:
  `_PIN_RE` (`src/benchweave_sdk/scaffold.py:230-234`) tolerates an extras
  clause and `recorded_sdk_version` documents that tolerance
  (`scaffold.py:296-299`), so `doctor` and `adopt` read the `[server]` pin
  unchanged.
- **Why our pin differs from the reference's `[scaffold,server]`, settled with
  evidence rather than copied**: their pin is a hand-widened dev convenience —
  `scaffold` serves their `upgrade`-time copier use, `server` their live
  serve/replay work; neither is a need of the GENERATED suite for the serial
  shape (measured 9/9 and 10/10 on the bare pin). The template ships the
  measured minimal per-arm closure: `[server]` where the suite provably needs
  it (provider), bare elsewhere. The issue's law — the pin in the project
  `pyproject.toml` is the install source for the test extra — holds exactly;
  an extras clause on the pin does not duplicate a version anywhere (the
  workflow names no version).
- `ruff>=0.6` mirrors the SDK dev group's floor.

### 2.3 `template/tests/test_plugin.py.jinja` — remove the two provider-arm F401s

Delete `import base64` and `from {{ package_name }} import protocol as proto`
from the provider arm. Byte change; flows through fixture regen.

### 2.4 `template/AI-GUIDE.md.jinja` — one clause in "Project layout"

The layout enumeration gains the workflow: a GitHub Actions workflow at
`.github/workflows/ci.yml` runs lint and tests on every push and pull request.
Wording in ASD-STE100 register via the `document-writer` agent at build; no
new refusal codes, subcommands or guide headings, so the R-5b checker
(`tests/test_agent_assets.py`) is unaffected — its asset set is exactly
AGENTS.md plus the five skills, none of which this change touches.

### 2.5 Fixtures — regenerate all three arms (mechanical)

`tests/fixtures/scaffold_expected/{base,ui,provider}/` each gain
`.github/workflows/ci.yml` (identical bytes) and the new-look
`pyproject.toml`; provider additionally gains the `[server]` pin and loses the
two imports; all arms' AI-GUIDE gains the clause. Regeneration is the existing
mechanism (the manual procedure in `tests/test_scaffold_copier.py`'s
docstring, or `make release-cut` at a version bump). `.gitattributes` already
pins `template/**` and the fixture tree to `eol=lf` (asserted by
`test_line_endings_are_pinned_lf_for_the_scaffold_surfaces`), and
`_enforce_lf` normalizes the render, so the YAML is LF everywhere.

### 2.6 New standing arms in `tests/test_scaffold_copier.py` (beside the R-2 arms)

1. **Workflow structure arm.** Parse the base arm's
   `.github/workflows/ci.yml` with `yaml.safe_load` (PyYAML is already a test
   dependency via copier — precedent `tests/test_scaffold_update.py`);
   assert: exactly jobs `{lint, tests}`; both `ubuntu-latest`; both carry
   setup-uv with `python-version: "3.13"`; **in each job, the single run step
   names the `--extra` token on the same command line that spawns the tool
   (`uv run --extra lint ruff check .` / `uv run --extra test pytest -q`), and
   no bare `uv run <tool>` step exists anywhere** — the ordering law as a
   structural property, not a step-index coincidence; top-level
   `permissions.contents == "read"`; triggers include `pull_request`; the raw
   text contains no `${{`; the three arms' workflow files are byte-identical.
2. **Lint-set arm.** For each `fixture_arms()` arm, parse that arm's rendered
   `pyproject.toml` `[tool.ruff.lint].select` with `tomllib` and run
   `ruff check --select <those codes> --no-cache <arm>/src <arm>/tests`;
   assert exit 0. The select list is READ from the rendered machine source,
   never restated — the arm cannot drift from what the generated CI runs.

### 2.7 This repo's own CI — the execution arms, both at PR time

- `ci.yml`, "Scaffold and check a plugin end-to-end" step (`ci.yml:113`, all
  three OS lanes): after the existing check/check-ui lines, run the generated
  lint path verbatim — `cd` into the scaffolded project,
  `uv run --extra lint ruff check .` (2 lines). This executes the workflow's
  exact lint command at PR time on every push.
- `ci.yml`, "Installed-wheel smoke" step (the one that builds `smoke-dist`):
  after the fixture-parity block, ubuntu-only (the `server-smoke` gate
  precedent, `publish.yml:123`'s sibling in `ci.yml`), run the generated
  TESTS path with the pin resolving against the just-built wheel — for the
  `--with-ui` scaffold AND a fresh `--provider-transport` scaffold:
  `cd` in, `UV_FIND_LINKS="$PWD/smoke-dist" uv run --extra test pytest -q`.
  Pre-release, PyPI does not carry the dev version, so find-links is the only
  resolver for the `==` pin — the exact generated tests job runs against the
  wheel that is about to ship, at PR time, not release time (no release is
  scheduled; release policy 2026-11-07 — parking the proof at a release gate
  would park it indefinitely). **No `publish.yml` change.**
- Same step, the EARNED-PIN negative control (the R-5c planted-violation
  pattern, in CI): scaffold a third project with `--provider-transport`,
  strip `[server]` from its rendered pin (one `sed` inside the step — a
  deliberate mutation of the generated project, the only variable under
  test), and run the same `UV_FIND_LINKS=... uv run --extra test pytest -q`.
  This run MUST FAIL, with `live_provider_backend_missing` in its output
  (assert: nonzero exit AND the refusal text present). The arm is green when
  the failure occurs; it REDS when the stripped pin goes green — which is
  exactly the day the `[server]` pin becomes unearned (D1 landing) and the
  template must narrow. Without this leg, a heavy pin would ship on import
  -chain reasoning alone and byte-parity could never catch it.

## 3. Precedent

- The workflow extends this repo's own CI skeleton (setup-uv + python 3.13 +
  `uv run`), with the reference implementation's field-proven command form as
  the one load-bearing adoption (§2.1).
- The lint extra extends the existing extras pattern (`[signing]`,
  `[server]`, `[scaffold]` on the SDK; `test` on the generated project).
- The conditional test extra extends the template's existing jinja
  conditionals (`template/tests/test_plugin.py.jinja` is built from them);
  this is the first conditional in `pyproject.toml.jinja`, which is why its
  consumer-tolerance (`_PIN_RE`) was verified rather than assumed.
- The managed-file posture (template-owned, conflict-marked on author edit,
  refreshed by `copier update`) is the WS3 agent-asset posture (SRF-1); the
  workflow joins that set and is deliberately NOT added to `_skip_if_exists`
  (`copier.yml:42`), so scaffold fixes propagate and author edits
  conflict-mark rather than silently lose (pinned by the update lane's
  A2/A5 arms in `tests/test_scaffold_update.py`).

## 4. The variant axes, decided from the generated shapes

1. **`package_name`** — nowhere referenced by the workflow. Invariant.
2. **`with_ui`** — adds UI files and one test; measured green under the plain
   extra (10/10, §1e). Invariant.
3. **`provider_transport`** — the one real difference: the suite's ftdi
   imports require pyftdi (§1e). The workflow file stays invariant; the
   difference lives in the rendered `pyproject.toml` pin, which is where a
   dependency closure belongs. The workflow stays byte-identical across all
   arms (asserted by A2).
4. **`sdk_version` / `otdp_version`** — appear only inside the rendered
   pyproject/answers. Invariant.
5. **`_exclude`** (`copier.yml:33-34`) — excludes only the provider contract
   from the serial shape; `.github/` is unconditional. No interaction.

## 5. Interface consequences (SRF-1) — everything that moves

**This is a Tier-3 increment in the review rubric** — not because the vendored
tree or lock moves (they do not; no standards machinery is in play), but
because scaffold output is an interface and this motion is a shape change:
the build runs two independent refute lanes plus the mechanism critic, and
the PR says "interface change" in those words (obligation 2,
`docs/internal/drift-and-obligations.md:18`).

This repository:

| Surface | Motion |
|---|---|
| `template/.github/workflows/ci.yml` | NEW (§2.1) |
| `template/pyproject.toml.jinja` | lint extra + ruff config + provider conditional (§2.2) |
| `template/tests/test_plugin.py.jinja` | provider arm: two unused imports removed (§2.3) |
| `template/AI-GUIDE.md.jinja` | layout clause (§2.4) |
| `tests/fixtures/scaffold_expected/{base,ui,provider}` | regenerated (§2.5) |
| `tests/test_scaffold_copier.py` | two new arms (§2.6) |
| `.github/workflows/ci.yml` (SDK's own) | end-to-end lint arm + installed-wheel tests arm (§2.7) |
| `README.md` (SDK) | generated-tree diagram (rows at `README.md:122-126`) gains the workflow row; five-steps step 2 gains a clause |
| `user_guide/plugin-sdk.qmd` | tree diagram (`user_guide/plugin-sdk.qmd:66-82`) gains the row; §1 prose gains a sentence |
| `docs/internal/invariants.md` | SRF-1 amendment (§7; anchor `invariants.md:206`) |
| `docs/internal/drift-and-obligations.md` | obligation 2 surfaces + CI map rows + gateway pairing note |

Consciously unchanged: `copier.yml`, `scaffold.py` / `scaffold_update.py`,
`template/README.md`, `publish.yml`, the vendored standards tree and lock.

Verified unaffected (walked so the enumeration is complete, not just the
movers): `tests/test_release_cut.py` — the release-cut regen path it pins is
occurrence-validated for version substitutions, and this change adds no
version literal anywhere (the workflow, the lint extra and the ruff config
carry none; the fixture pyproject's only version literal remains the
substituted SDK pin); `tests/test_agent_assets.py` — its asset set is exactly
AGENTS.md plus the five skills, and its fixture arms enumerate from the
directory, so the new fixture member flows; `tests/test_getting_started.py` —
it executes getting-started.qmd's shell blocks, and this change's guide
motion is plugin-sdk.qmd prose/diagram only.

Main repository (pairs via TWO-1, in the pointer PR):

- `tests/sdk/test_scaffold_skills.py` — `PINNED_FILE_SET` (line 31) gains
  `.github/workflows/ci.yml`. Without this edit the gateway's `sdk` lane reds
  at the pointer bump; the file's own comment says a deliberate shape change
  edits the pin in the same change.
- `tests/sdk/test_presentation_cli.py` — rglob self-parity between two
  scaffolds; flows automatically.
- `tests/sdk/test_plugin_developer_skill_content.py` — schema-field pins, not
  file sets; unaffected.

Downstream: existing plugin projects gain the workflow and lint extra on
their next `copier update` (new-file apply is clean; an author who
hand-added a workflow at the same path gets conflict markers; the stopgap
file's different name coexists). Existing projects' `pyproject.toml` is
skip-protected, so the extras reach new projects only — the documented §2.2
intent.

## 6. Minimal first increment and the deferral table

The first increment is §2.1-§2.7 plus the SRF-1 amendment. Zero
production-code changes in `src/` (the template is content; the closure fix
is declarative).

| # | Deferred | Carrier |
|---|---|---|
| D1 | The deep closure fix — skip the backend deployment check on the injected `driver_factory` path (`session.rehearsal` already marks it) so the shipped double needs no pyftdi | Gateway issue on `ftdi.py::verify_ftdi_plugin`; if it lands, the provider test extra drops `[server]` (template edit + fixture regen). Deliberately NOT bundled here: it is SDK runtime behavior with its own refute surface, not scaffold content |
| D2 | A narrower SDK extra (e.g. `[ftdi]`) so the provider closure avoids the web stack | SDK packaging issue; a new public extra name is API and needs a ruling |
| D3 | `--locked` / committed-`uv.lock` posture for generated CI | Guide editorial pass; the workflow works with or without a committed lock today |
| D4 | Generated-CI extras: concurrency cancel group, junitxml artifact upload, OS matrix | Template issue, when a consumer or cost problem exists |
| D5 | SHA-pinning the actions in the generated workflow | Maintainer ruling on the §2.1 trade-off |
| D6 | Migrating the reference project's stopgap to the template file | Author-side, next `copier update` |
| D7 | `scaffold` extra on generated pins (for `upgrade`-time copier in-project) — the reference carries it; our measured closure does not need it | Revisit if the guide starts teaching in-project `upgrade` runs against the project venv |

## 7. Invariant impacts

- **SRF-1 (amendment, anchor `docs/internal/invariants.md:206`).** The
  scaffold interface now includes: the generated `.github/workflows/ci.yml`
  (two jobs, expression-free, byte-identical across all arms — rendered by
  verbatim copy, never jinja), the `lint` extra with the explicitly selected
  minimal ruff set, and the arm-conditional `test` extra. New clause: **each
  arm's generated `test` extra must install everything that arm's generated
  suite imports** (the provider arm pins `benchweave-sdk[server]` because its
  shipped-double tests import the ftdi session builder, whose contract
  verification imports pyftdi unconditionally). Pinned by §2.7's
  installed-wheel tests arm at PR time.
- **STD-1..6, PKG-1/2/3, SRF-2/3, TWO-1** — unchanged in substance; PKG-2's
  template carve-out already covers the new member; TWO-1 gains the pairing
  note (obligation 8).
- No new refusal prefixes (STD-4): the design adds no refusal path anywhere.

## 8. Pre-committed acceptance rule

The §1 measurements were design exploration against the current tree (defect
baseline, run by this lane, 2026-11-07, against a wheel built from `ff87c76`).
The arms below are fixed now, before the increment is built. Every arm names
its denominator and both kill directions. **Exit-code law throughout: exit 0
is green; exit 1 is findings; exit 2 is the tooling class — uv usage error,
undefined extra, or spawn failure — and NEVER counts as "ruff ran and found
things"** (the reference's RED exited 2).

- **A0 — the headline: a freshly generated project passes its own workflow.
  RED baseline first, against the CURRENT template**: scaffold a project per
  arm (base, ui, provider) and run the two job commands exactly as the
  workflow will (`uv run --extra lint ruff check .`;
  `uv run --extra test pytest -q`). Expected RED, measured: lint fails on
  EVERY arm (no `lint` extra: uv usage error, exit 2); tests fail on provider
  (5/8, `live_provider_backend_missing`) and PASS on base (9/9) and ui
  (10/10) — the lead's brief said "both jobs fail"; that is true of provider
  and of lint everywhere, and honestly not of base/ui tests, which pass today
  and must keep passing. **GREEN, after the increment**: both commands exit 0
  on all three arms, lint with 0 findings. Denominator: 3 arms × 2 commands.
  KILL: any command exiting nonzero on the fixed template, or the RED
  baseline not reproducing (which kills the measurement, not the build —
  re-derive before proceeding). INCONCLUSIVE: resolver/network errors naming
  an index — rerun once.
- **A1 — shape (existing R-2 machinery).** After regen,
  `uv run pytest tests/test_scaffold_copier.py -q` green: all 3 arms'
  renders byte-identical to fixtures, every file compared. SHIP: green.
  KILL: any file-set or byte mismatch. Deterministic, offline.
- **A2 — workflow structure (new offline arm, §2.6.1), written RED-first.**
  Written before the template file exists: it must fail on the missing file,
  then pass once the template lands. It pins the ordering LAW as structure:
  the `--extra` token and the tool spawn share one command line, and no bare
  `uv run <tool>` step exists. Mutation controls pasted in the PR: strip
  `--extra lint` from the workflow in a scratch copy → arm reds; reorder into
  sync-then-bare-run in a scratch copy → arm reds; plant `${{` → arm reds.
  KILL: the arm passing with the template file absent (vacuous arm), or any
  assertion red against the landed template.
- **A3 — generated code passes the generated lint (new arm, §2.6.2).** RED
  exists in-tree today: with the current provider template the arm fails (the
  two F401s, §1d) — reproduce the RED before fixing the template, then green
  after §2.3. Denominator: 3 arms × exit 0. KILL: any finding. The select is
  read from each arm's rendered pyproject — an arm checking a different set
  than the generated CI runs is itself a kill.
- **A4 — lint job executes (ci.yml end-to-end extension).** Green on
  ubuntu/macos/windows lanes; the step's ruff run exits 0. KILL: exit 1
  (findings — real) or exit 2 (tooling/install class — real, and precisely
  the reference's trap recurring). INCONCLUSIVE: network/resolution error
  text naming an index — infrastructure, rerun once.
- **A5 — tests job executes with a real pin (ci.yml installed-wheel arm,
  ubuntu-only).** Per push: 2 shapes (ui, provider), each
  `UV_FIND_LINKS=smoke-dist uv run --extra test pytest -q` exits 0 with
  collected counts ≥ 10 (ui) and ≥ 8 (provider). SHIP: both green with
  counts read from the raw output. KILL: nonzero exit, or exit 5 / 0
  collected (`no tests ran` is a FAILED check). INCONCLUSIVE: resolution
  errors naming PyPI (the pin must resolve via find-links) — fix the wiring,
  rerun.
- **A6 — the issue's own wound closes (post-merge, observational).** The
  first PR on the first project scaffolded from the released template shows
  `ci / lint` and `ci / tests` in its check rollup, both green on an untouched
  scaffold. Denominator: 1 repository, 1 PR, 2 check rows. KILL: empty rollup
  or a red job with no author change. Cannot gate the merge; saying so is
  part of the rule. (Given the no-release policy, this arm waits for the next
  tag — A0/A5 are the pre-merge truth.)
- **A7 — the `[server]` pin is EARNED, proven by execution in both
  directions at PR time (§2.7's negative control).** The `[server]` claim
  must not ship on import-chain reasoning alone. Three legs, one step:
  (i) RED leg — a provider scaffold with `[server]` STRIPPED from its pin
  (the only mutated variable): `uv run --extra test pytest -q` must exit
  nonzero with `live_provider_backend_missing` in the output; expected
  failing shape at design time: 3 of 8 tests fail, 5 pass. This leg is a
  STANDING EXPECTED-FAILURE control (the R-5c planted-violation pattern): the
  CI step asserts the failure occurs — if the stripped pin ever goes GREEN,
  this arm reds and the template pin must narrow to bare (that is D1
  landing, and the arm is the detector). (ii) GREEN leg — the as-rendered
  provider project (pin carries `[server]`): same command, exit 0, collected
  count ≥ 8. (iii) Narrowness legs — base and ui as-rendered (bare pins)
  must be green WITHOUT `[server]` (A0's GREEN already covers them; this arm
  names them as part of the same proof: the conditional is narrow, not a
  blanket weight increase). Denominators: 4 scaffolded projects × 1 pytest
  run each, per push. KILL (ship-blocking): leg (i) green without `[server]`
  (pin unearned — drop it to `benchweave-sdk=={{ sdk_version }}` and re-cut
  this record's §2.2); leg (ii) red WITH `[server]` (the closure claim is
  wrong in the other direction); leg (iii) red (the bare pin regressed).
  INCONCLUSIVE: resolver/network errors naming an index — rerun once. The
  design-time first run of this arm (already measured: provider plain 5/8
  with the refusal ×3, provider `[server]` 8/8, base 9/9, ui 10/10 — §1e)
  is the one-time RED/GREEN capture for the PR body.

CI cost: +~30s × 3 lanes (A4); +~90-120s × 1 lane (A5 + A7's fourth
scaffold). No new jobs, no new markers, no publish.yml motion.

## 9. Top risks and their falsifiers

- **R1 — the `[server]` pin is heavy** (fastapi/fastmcp/uvicorn ride into a
  provider project's CI for a rehearsal). Exit: D1 or D2 lands and the extra
  narrows. If the maintainer rejects the weight now, the honest split is
  workflow-for-base/ui plus D1 promoted — shipping red provider CI is not an
  outcome A0 tolerates.
- **R2 — major action tags drift** (a breaking major reds every generated repo
  at once). Falsifier: A6-style observation plus downstream dependabot (which
  the workflow files enable). D5 is the reversal switch.
- **R3 — gateway lane reds at pointer time** if the `PINNED_FILE_SET` edit
  misses the pointer PR. The red IS the pin working; the pairing note in the
  PR body is the prevention.
- **R4 — `uv run` lockless resolution drift** (ruff/patch moves under a `>=`
  floor). Bounded by floors and the `==` SDK pin; the author's committed lock
  governs when present. Falsifier: an A4/A5 failure pinning a moved
  dependency — then floors tighten.
- **R5 — ruff's default set widens again**: harmless to generated projects
  (select is explicit and frozen); the SDK repo's own gate is unaffected
  (template/fixtures excluded). Falsifier: A3 red from a rule OUTSIDE the
  selected codes — that would mean the select stopped being honored; treat as
  a tool regression, not a finding.
- **R6 — local-build hazard (pre-existing, out of scope)**: the main checkout
  carries untracked iCloud ` 2` duplicates under `template/` and the
  fixtures; hatch's force-include is filesystem-based, so a wheel built from
  that dirty tree ships them. Releases build from clean CI checkouts. Build
  from the worktree (this record's provenance note) or a clean checkout;
  local main-checkout builds are not evidence.

## 10. Honest notes

- What the reference settled: the command form (extra on the spawn line), the
  exit-2 failure class, the mandatory explicit select, the minimal set's
  exact codes, and that a sync-then-run tests job also works. What it could
  not settle and this design measured for itself: whether OUR template's
  suites run under OUR generated pin per arm (§1e matrix), and that our
  pristine scaffold births red under ruff 0.17 defaults (§1c).
- The issue's mechanism statement ("the tests job uses pytest on Python 3.13")
  is correct for serial/ui and incomplete for provider (§1e) — the workflow
  alone was never sufficient; the pin's dependency closure needed fixing too.
- The two F401s (§1d) are a template defect this increment fixes because the
  lint it ships would otherwise fail its own first run.
- No production code in `src/` changes. If review prefers the ftdi fix over
  the `[server]` pin, that is D1 promoted — a different increment with its
  own refute surface, and it changes SDK runtime behavior for every consumer
  of `verify_ftdi_plugin`, not just the scaffold.

## Maintainer rulings, 2026-11-07

Append-only. Three items §2/§6/§9 present as maintainer calls are DECIDED
(team-lead adjudication, 2026-11-07); a reviewer reading an open question
where a decision exists would re-open a settled argument, so this section
closes them. The body above is not rewritten — where a ruling supersedes a
body row, the ruling wins and names the row.

1. **The `[server]` weight — DECIDED: the provider-conditional pin stands
   (§2.2).** Green CI on day one is the entire point of issue #596; a heavier
   test extra for one arm is the cheaper wrong. This closes risk R1's
   "maintainer rejects the weight" branch. D1 stays open as the deep fix with
   its own carrier (a gateway issue on `ftdi.py::verify_ftdi_plugin`), and
   its reopen trigger stands as written: when D1 lands, the provider pin
   drops back to the bare `benchweave-sdk==` form with a template edit plus
   fixture regen — and §2.7's A7 negative control is the detector that fires
   first (the stripped-pin run going green). D2 (a narrower extra) stays an
   idea with no current carrier.

2. **SHA vs major action tags — DECIDED: major tags (§2.1); D5 is closed by
   this ruling.** This is a trade-off accepted, not overlooked: generated
   projects are author-owned repositories, the two actions are first-party
   (`actions/checkout`, `astral-sh/setup-uv`), and SHA pinning would make
   every `copier update` carry churn against a threat the generated project's
   owner does not control. The losing side, recorded so the decision is
   auditable: SHA pinning is the harder security posture, a security-conscious
   author may prefer it, and nothing in the scaffold stops an author from
   hand-pinning SHAs in their own repository after generation.

3. **The lead's own baseline claim was WRONG and the correction is
   accepted.** "Both jobs fail at baseline" does not hold: only LINT fails on
   every arm, and it fails as a tooling error (uv usage error, exit 2 — there
   is no `lint` extra to name), never as findings. Provider tests fail 5/8
   (`live_provider_backend_missing` ×3). Base tests pass 9/9 and ui 10/10
   today. A0's framing — those passes are a baseline that must not regress —
   is the authoritative one, and it is what the build works to.

4. **The dev-group rejection is structural, not stylistic (recording §2.2's
   reasoning at ruling weight, because a future reviewer will "simplify" the
   `lint` extra back to a `[dependency-groups]` dev group without it).**
   `uv pip` cannot install PEP 735 dependency groups, and the generated
   README's documented install path is `uv pip install -e '.[test]'` — a
   ruff carried in a dev group would be uninstallable through the very
   command the scaffold itself teaches. That is why the extra stands, and why
   the same-command-line law (`uv run --extra lint ruff check .`, pinned by
   A2) closes the footgun the dev group would have removed: the extra is
   named on the spawn line, structurally, in the one file the author never
   has to write.

## Build note — A0 and A7 landed (2026-11-07)

Append-only. This records the implementation of §8's two remaining execution
arms and the measurements taken while landing them. Measured under pytest
9.1.1 in the build worktree (`origin/main` carries 9.2.0, so the merged-result
re-run stays owed).

**Carrier.** Both arms are one ubuntu-only step in `ci.yml`, immediately after
the installed-wheel smoke (which builds `smoke-dist`, the `UV_FIND_LINKS`
source): "Generated workflow — A0 green legs and A7 earned-[server] control".
§2.7 said "same step" for the control; a separate adjacent step is the
functional equivalent, because a `matrix.os` guard cannot live inside a shared
`run:` block and duplicating the whole smoke step to carry it would be worse.
The four scaffolded projects are base, ui, provider, and provider-stripped.

**A0's RED baseline, re-measured against the pre-fix template** (`5af5292`,
wheel built from that tree; denominator 3 arms × 2 job commands):

| Arm | lint job | tests job |
|---|---|---|
| base | `uv sync --extra lint` → **exit 2**, `Extra \`lint\` is not defined` | `9 passed`, exit 0 |
| ui | same → **exit 2** | `10 passed`, exit 0 |
| provider | same → **exit 2** | `3 failed, 5 passed`, exit 1, `live_provider_backend_missing` ×3 |

So the honest baseline is 3 red lint legs (all tooling class, never findings),
one red tests leg (findings), and two green tests legs that must not regress —
exactly ruling 3, not "both jobs fail".

**A0 GREEN, post-fix template** (wheel built from the build head): 6/6
commands exit 0; lint prints `All checks passed!` on all three arms; tests are
9 / 10 / 8 passed. The step asserts those floors so an exit-5 "collected
nothing" cannot pass as green.

**A7 measured.** As-rendered provider: exit 0, 8 passed. Base and ui on their
bare pins: exit 0, 9 and 10 passed (the conditional is narrow). Stripped pin
(the `sed` mutation and nothing else): exit 1, `3 failed, 5 passed`,
`live_provider_backend_missing` present — the design-time expectation holds
exactly.

**Step-logic mutation controls** (the extracted `run:` block executed
verbatim, with only the repo-root scaffold binary substituted for `uv run`):

- Neutralize the strip → the control runs the as-rendered (green) provider
  project → step exits 1 with "the [server]-stripped provider suite PASSED …
  narrow the generated test extra". This is the D1-detector direction, proven.
- Undefined extra in a green leg → step exits 1 naming `exit 2 (tooling
  class: uv usage/spawn/undefined extra)`, never "findings".
- Undefined extra in the control's sync → step exits 1 naming the tooling
  class rather than accepting the failure as the expected refusal.
- Point `UV_FIND_LINKS` at an existing but empty directory → the syncs
  succeed from PyPI and the step exits 1 with "uv.lock does not resolve
  benchweave-sdk from <smoke-dist> — this leg would exercise PyPI's bytes,
  not the wheel under test."

**Resolver provenance — a measured correction to §2.7's premise.** §2.7 says
"pre-release, PyPI does not carry the dev version, so find-links is the only
resolver". That does not hold while the dev version EQUALS the latest
published release, and that is this branch's situation: PyPI serves
`benchweave-sdk==0.24.0` (uploaded 2026-11-06T08:19Z), which is exactly this
branch's version. Measured on four fresh project trees:

- With no lock present, uv prefers the `--find-links` flat index and installs
  the wheel under test — verified by hashing the installed
  `benchweave_sdk_server/ftdi.py` against the built wheel (`957e53ec…`,
  96,483 bytes) rather than trusting the log.
- `uv sync` writes a `uv.lock` recording the WINNING index. A lock written by
  an earlier sync that ran without `UV_FIND_LINKS` pins
  `source = { registry = "https://pypi.org/simple" }`, and every later sync
  in that project honours it — installing PyPI's 0.24.0 (`3759c7ae…` in the
  installed file, 68,844 bytes, an older `ftdi.py`).
- Location, pin shape and the dist directory are NOT the discriminator (each
  was cross-tested); the lock is.

The step therefore exports `UV_FIND_LINKS` before any sync and asserts the
lock's source after each one. Consequence worth naming: the first RED-baseline
pass taken for this record was contaminated exactly this way (a `uv sync
--extra lint` that ran before the export wrote a PyPI-sourced lock, and the
tests leg then ran the published wheel). The RED table above is the CLEAN
re-measurement from fresh scaffolds, where all three pre-fix arms installed
the pre-fix wheel — the outcome was identical in both passes, which is why the
contamination was worth chasing rather than waving through.

**Deviation found in the landed generator (not introduced here).** §2.1
specified the single-line `uv run --extra lint ruff check .` form; the
committed `template/.github/workflows/ci.yml` (and its fixtures) uses the
two-step `uv sync --extra lint` then `uv run ruff check .` form, and A2 pins
that shape. A0 runs the commands as the template actually ships them. Both
forms are field-proven (the reference's own green run used sync-then-run);
the record's §2.1 text is left as written and this note is the correction of
record. The drift map and SRF-1 previously claimed the pin was executed by a
`publish.yml` generated-tests smoke; that block was reverted by the maintainer
corrections, and both documents now name this `ci.yml` step instead.
