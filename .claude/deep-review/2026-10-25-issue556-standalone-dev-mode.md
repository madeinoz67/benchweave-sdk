# Issue #556 — standalone dev mode (SDK-only): design record

Date: 2026-10-25 · Leg: "standalone dev mode" of gateway issue #556 · Branch:
`feat/556-sdk-standalone` (base `dc6e429` = benchweave-sdk 0.21.0) · SDK repo only.

The owner's chosen disambiguation: **"Developers author, derive and preview composed UIs
with no gateway at all: compositions work in the SDK standalone host path, offline, from
a plugin directory."**

## 0. The honest headline

**Most of this already exists and is already proven in-repo.** The #541 slice 1–4 arc
shipped the three-layer resolution (`catalog|composed|custom`), the composed-class pin
walk, the rendered gate, the ledger read-backs, the composition docs, and the Meridian
M-400 acceptance fixture whose A1–A4 arms run the exact loop `new → derive-ui →
verify-ui → render` on a composed+residual project (`tests/test_classref_acceptance.py`).
The publish workflow and its PR-time CI mirror already prove `preview-ui` over an
installed wheel with the `[server]` extra — but only against the scaffold **starter**.

The residual work is small and real. Four gaps, one new (small) mechanism, everything
else proof and documentation:

1. The composed loop is never proven **from the installed-SDK posture** (clean venv, no
   checkout on `sys.path`, real console scripts). Every composed proof runs the SDK from
   the checkout process.
2. The composed control is never asserted **over the spawned listener** (console script →
   serve → guard → HTTP). The PR-time/release-time wheel smokes assert banners on the
   starter's home page only; the in-suite arms use in-process ASGI.
3. Pin authoring is the loop's one recurring hand-maintenance step: every edit of a
   composed-class document invalidates the `contracts[]` digest, and the repair is a
   hand-computed sha256 plus a hand-edited descriptor row.
4. The dev-mode run-through exists as scattered sections; no single documented sequence
   takes a developer from a clean install to a previewed composed UI.

This leg is therefore **genuinely new work only at the edges** — one acceptance lane, one
pin-authoring command, one docs pass — over behavior that slice 3 already proved
in-process. Nothing here re-implements derivation; nothing touches the gateway.

## 1. What exists today (evidence, so the gap census is grounded)

- **Three-layer resolution** — `src/benchweave_sdk/classref.py:1280-1305`
  (`_derive_controls`: `composed` when the pin walk injected the row, `catalog` when a
  served/pinned catalog describes it, `custom` residual otherwise);
  `classref.py:347-583` (`_vendor_documents`: the pinned-document walk — shape
  discrimination, digest verification, conflict refusals, unapplied/ignored/empty
  disclosures); `classref.py:288-292` (`validate_composed_class`, public).
- **derive-ui** — `src/benchweave_sdk/cli.py:497-602`; writes `ui/class-reference.json`
  (the ledger) beside the derived set.
- **verify-ui (the rendered gate)** — `src/benchweave_sdk/classref_gate.py:682-994`:
  validates, derives, renders through the standalone host over in-process ASGI
  (`classref_gate_render.py:14-69`), censuses §E.1 surfaces, asserts per-action coverage
  (`classref_gate.py:435-543`), reads back the composed inventory
  (`classref_gate.py:600-679`), discloses unapplied/ignored/deferred members. CLI at
  `cli.py:605-630`.
- **preview-ui** — `cli.py:1354-1417`: an in-process alias over
  `benchweave_sdk_server.cli.serve` with `transport="mock"` pinned; parity and refusal
  behavior pinned by `tests/test_preview_shim.py` (no composed-project arm).
- **The acceptance fixture** — `tests/fixtures/classref/descriptor-m400.json` (a DAQ
  with one composed action `com.meridian.m400.burst_mode/1.0.0` pinned via
  `composed-burst.json`, and one residual action `com.meridian.m400.self_cal/1.0.0`);
  `tests/test_classref_acceptance.py:139-173` (A1 workflow), `:254-275` (A2: the
  composed control `action-burst_mode-burst_count` derives from the class's
  `input_schema`), `:315-405` (A3: the composed class survives the plugin's wheel,
  resolves and previews from the installed plugin tree), `:463-533` (A4: nothing hand
  written).
- **Installed-wheel proof, starter only** — `.github/workflows/publish.yml:66-151`
  (release-time install smoke `[scaffold]` + ubuntu `[server]` spawn smoke asserting the
  two mode banners) and `ci.yml:110-210` (the same blocks at PR time). Both drive
  `new --with-ui` and `preview-ui` on the template descriptor — no composed class, no
  residual member, no derive/verify, home page only.
- **Docs** — `user_guide/plugin-sdk.qmd:144-294` (three-layer resolution, composed-class
  authoring including the hand-written `contracts[]` pin at `:201-211`, ledger,
  verify-ui's disclosure rows); `user_guide/getting-started.qmd:178-208` (the optional
  UI section: `uv pip install 'benchweave-sdk[server]'` + `preview-ui . --no-open`).
- **Packaging** — `pyproject.toml:44-63` (`[server]` extra incl. the exact
  `benchweave-ui-html` pin), `:79-90` (wheel packages both packages + the lock + the
  copier template — an installed SDK is self-contained offline).

**Answer to the brief's question** — what can a developer NOT do today, offline,
SDK-only, holding a plugin directory with composed classes and residual members:

- They cannot get a *proven* loop: nothing anywhere demonstrates the composed loop from
  a clean installed SDK (gap 1) or over the spawned preview listener (gap 2). The loop
  is believed to work there because each half is proven separately — belief, not
  evidence, is exactly what this project refuses to ship.
- They cannot keep a pin in step with an edited class document without hand-hashing
  (gap 3).
- They cannot read one documented sequence for it (gap 4).
- Everything else — deriving composed controls, residual rendering, disclosures,
  packaging, installed verification of the vendored tree — works today and is pinned by
  tests. **No new derivation, no new schema, no gateway surface is needed.**

## 2. The mechanism

One new acceptance lane, one new small command, one docs pass:

**(a) The standalone dev-loop lane** (`tests/test_standalone_dev_loop.py`): a
session-scoped fixture builds this repo's wheel once (`uv build --wheel`), creates a
fresh venv outside the checkout, and installs `<wheel>[server,scaffold]` from it. Every
arm then drives the **installed console script** (`<venv>/bin/benchweave-sdk`) as a
subprocess against a project under `tmp_path`: scaffold with `new --with-ui` (exercising
the packaged copier template out of checkout), fill the package with the M-400 fixture
bytes (descriptor + `composed-burst.json`), then `derive-ui`, `verify-ui`, and a spawned
`preview-ui --no-open --port <free>` whose served `/pages/device-features` HTML is
fetched and asserted. A **control arm** strips only the composed pin row (after a `cp`
backup) and proves the composed surface disappears. This extends two proven mechanisms:
the in-suite `m400_wheel` fixture (`test_classref_acceptance.py:315-334`, `uv build` +
`uv pip install` inside pytest) and the CI spawn smoke's bash shape
(`publish.yml:116-151`), moved into pytest so it counts in junitxml and runs locally.

**(b) `benchweave-sdk pin-class <project> <document> [--id <pin-id>]`**: validates one
composed-class document against the vendored family schema (reusing
`validate_composed_class`), computes its sha256, and upserts the matching
`contracts[]` row in the descriptor — refusing (typed, pre-write) an invalid document
(reuses `classref_invalid_composed_class`), an `urn:otdp:`-prefixed id (a pin the walk
structurally ignores, `pin_class_otdp_namespace:`), an id/path conflict
(`pin_class_id_conflict:`), a document outside the package or reached through a symlink
(`pin_class_document_uncontained:`), and a descriptor whose current bytes are not the
canonical serialization of its parsed content (`pin_class_descriptor_not_canonical:` —
the tool never reflows an author's file). Precedent: `regen-fixtures` (issue #463 row 8)
was minted for exactly this friction class — "after an edit, one command rewrites the
generated bytes"; the gateway's `benchweave.standards pin` is the authoring-file-write
precedent. The command is deliberately NOT part of `derive-ui` (derive writes the
derived set, never the author's descriptor; the dirty-tree guard must stay
unentangled).

**(c) The docs pass** (STE100, authored via the `document-writer` agent): a single
"Standalone development loop (composed UIs)" section wiring the existing pieces into
one sequence (install line → `new --with-ui` → author class → pin → `derive-ui` →
`verify-ui` → `preview-ui` → what the page shows), the `pin-class` paragraphs in
`plugin-sdk.qmd` §composed-action-classes, and whatever per-verb reference surface the
existing CLI verbs use. `getting-started.qmd` gains the loop only if the docs-as-tests
lane (`tests/test_getting_started.py`) can execute its `sh` blocks as written — the
loop's commands are all offline after the install line, so they can.

## 3. The developer's run, end to end (what the lane proves is real)

```sh
uv venv .venv && uv pip install --python .venv 'benchweave-sdk[server,scaffold]'
.venv/bin/benchweave-sdk new acme-widget --package acme_widget_plugin --with-ui
cd acme-widget
# author src/acme_widget_plugin/widget-burst.json  (the composed class document)
.venv/bin/benchweave-sdk pin-class . src/acme_widget_plugin/widget-burst.json
.venv/bin/benchweave-sdk derive-ui .
.venv/bin/benchweave-sdk verify-ui .
.venv/bin/benchweave-sdk preview-ui . --no-open
# → "Serving acme_widget_plugin on http://127.0.0.1:8477" + bearer token line
```

What they see, concretely (pinned by the lane against the M-400 bytes):

- `derive-ui` exits 0 and prints the cannot-derive notes; `ui/class-reference.json`
  carries `composed_actions`/`composed_classes` rows and a `custom_actions` row for the
  residual member.
- `verify-ui` exits 0 with `Rendered gate clean` plus `reported deviation:` lines —
  including `custom: com.meridian.m400.self_cal/1.0.0` (provenance/disclosure on the
  REPORTED channel).
- `preview-ui` serves; `GET /pages/device-features` returns HTML containing the staged
  control `action-burst_mode-burst_count` — a control whose field set comes from the
  composed class's `input_schema` (`burst_count`, integer 1..1024): the descriptor's
  `burst_mode` action declares `input_constraints: {}`
  (`descriptor-m400.json:190-200`), so the descriptor alone cannot produce this field.
  The page also carries the `Custom device actions` section title (residual rendering)
  and all four mode-banner wordings (imported from
  `benchweave_sdk_server.presentation.mode_banner_entries`, import-compared the way
  `tests/server/test_banner.py` does).

No gateway, no registry, no network at run time; the only network is the install line.

## 4. Slice / commit plan (all on `feat/556-sdk-standalone`)

1. **Commit 1 — the standalone dev-loop lane** (`tests/test_standalone_dev_loop.py`
   + this design record committed with it, per the deep-review convention). Arms: the
   loop arm; the control arm (pin stripped via `cp`-backed descriptor edit → composed
   control and button absent from served HTML, `verify-ui` reports
   `custom, renders nothing: com.meridian.m400.burst_mode/1.0.0`); the spawn arm skips
   on Windows (`SIGINT`-exit semantics; the ubuntu CI smokes cover the spawned shape
   there) with the reason string naming that coverage. RED proof at build time is the
   control arm itself (mechanism neutralized → the assertion flips).
2. **Commit 2 — `pin-class`** (`src/benchweave_sdk/classref.py` helper +
   `src/benchweave_sdk/cli.py` verb + `tests/test_pin_class.py` + the STD-4 prefix-list
   amendment in `docs/internal/invariants.md`). Each refusal arm is written RED first.
3. **Commit 3 — docs** (document-writer agent): the run-through section, `pin-class`
   prose + reference surface, obligation-1 walk (`user_guide/plugin-sdk.qmd`, first-timer
   pages only where they cite the new verb; `tests/test_getting_started.py` and
   `tests/test_agent_assets.py` must stay green — registration checks, not new
   registrations, unless a page cites the verb).

Per-commit FAST lane (`UV_PROJECT_ENVIRONMENT=venv`): `uv run ruff check .`, fresh-cache
bare `uv run mypy` (`rm -rf .mypy_cache`), focused `uv run pytest
tests/test_standalone_dev_loop.py tests/test_pin_class.py tests/test_classref_acceptance.py
tests/test_preview_shim.py` (+ `tests/server/` for the spawn arm's neighbors). Full
battery once before push (full suite + `sync-standards --check` + both standards
tripwires as the SDK battery defines them). Counts from `--junitxml` attributes or true
exit codes only.

## 5. The Track A / Track B seams (one derivation, not two)

- **This leg adds no derivation and reads none privately.** The lane consumes the CLI
  surfaces (`derive-ui`, `verify-ui`, `preview-ui`) and the files they write. Track B's
  six-vocabulary work changes what `derive_ui` emits *inside* those surfaces; standalone
  mode consumes that output as-is.
- **No version literals.** Track B's B2 lands a `plugin-ui-class-reference` 0.5.0 family
  copy and a new schema. The lane therefore never asserts `validated_against == "0.4.0"`
  or any family literal: ledger assertions read
  `active_version("plugin-ui-class-reference")` from the running SDK and assert the
  action→class mapping content (`composed_actions` maps
  `com.meridian.m400.burst_mode/1.0.0` → `otdp.action.meridian_burst/1.0.0`;
  `composed_classes` contains that class), not exact list equality.
- **No deferral-row assertions.** Track B's B1 removes the `derivation deferred`
  disclosures (computed measurements, decoders). The lane asserts only
  composition-stable surfaces: the composed control id, the residual `custom:` row for
  `self_cal` (a plain action — no deferred vocabulary involved), the banners, the
  ledger mapping.
- **Track A** (gateway mirror) is gateway-side only; no SDK surface moves with it.

## 6. Invariant and drift impacts

- **No STD/PKG/SRF invariant changes semantics.** `pin_class_*` joins the STD-4
  enumerated refusal-prefix family — an amendment to the list in
  `docs/internal/invariants.md` (the prefixes are an API; the list is the inventory),
  landing in Commit 2. PKG-1/PKG-2 are untouched (no packaging change, no new
  dependency — `pyproject.toml` and `uv.lock` do not move). SRF-2 is unaffected (the
  lane loads through the same loader the host uses).
- **Obligation 1 fires** (CLI-visible behavior): `user_guide/plugin-sdk.qmd`, the README
  five-steps and first-timer pages where they cite commands — walked in Commit 3.
  Obligation 6: the new lane IS the named behavioral module. Obligation 8 (two-repo
  order): SDK-only; no main-side counterpart PR is required (no corpus, renderer or
  pointer motion), and the PR body says so while noting gateway issue #556 as the
  linked issue (single issue stream).
- **On-disk format/schema: none new.** The `contracts[]` row is existing descriptor
  schema; the composed-class schema is Track B's to move (0.5.0), not this leg's.
- **Surfaces that move**: `tests/` (two new modules), `src/benchweave_sdk/cli.py`,
  `src/benchweave_sdk/classref.py` (additive helper), `docs/internal/invariants.md`
  (STD-4 list), `user_guide/**`. No MCP/REST/openapi/operator-doc/gateway surface.
- **CI cost**: +1 pytest module per OS in the `sdk` job. Wheel build ~15 s + venv +
  `[server,scaffold]` install (PyPI) ~40-90 s, session-scoped once. Budgeted and
  measured by the acceptance rule below.

## 7. Tier call (rubric Step 1) and the keyword scan

Expected diff files: `tests/test_standalone_dev_loop.py` (new), `tests/test_pin_class.py`
(new), `src/benchweave_sdk/cli.py`, `src/benchweave_sdk/classref.py`,
`docs/internal/invariants.md`, `user_guide/plugin-sdk.qmd` (+ first-timer pages as
walked), this design record.

Keyword scan over the whole expected diff, docs and code alike:

- `standards-lock.json` — 0 hits. `src/benchweave_sdk/standards` — 0 hits.
  `hatch_build` — 0 hits. `scaffold.py` — 0 hits. `conformance.py` / `validation.py` /
  `fixtures.py` — 0 hits. `pyproject.toml` / `uv.lock` (dependency motion) — 0 hits.
- Refusal paths **added**: 4 (`pin_class_otdp_namespace:`, `pin_class_id_conflict:`,
  `pin_class_document_uncontained:`, `pin_class_descriptor_not_canonical:`) — plus reuse
  of `classref_invalid_composed_class`.
- Test-time paths outside the repository: yes — the lane's venv and project live under
  `tmp_path` (the letter of the Tier-3 self-containment rule; the intent analysis: the
  lane installs only this repo's wheel plus its own declared extras and reaches for no
  parent/gateway path — the same shape as the landed `m400_wheel` arms and the CI wheel
  smokes).

**Tier: 3 (maximum across slices).** Commit 2 triggers it directly (adds refusal
paths). Commit 1 is Tier 3 by the letter of the outside-repository-at-test rule
(conservative call; G6 refute is cheap). Commit 3 alone would be Tier 1. Consequence:
the mandatory independent second reviewer (G6) runs on Commits 1 and 2.

## 8. The measurable proof and the pre-committed acceptance rule

Written before any measurement ran. No timing, count or CI delta has been looked at.

**Primary metric (binary, through the real code path).** From a clean venv containing
only the built wheel's `[server,scaffold]` extras — cwd outside the checkout, no
checkout on `sys.path` — the M-400-shaped loop satisfies all of:

1. `new --with-ui` exit 0; 2. fill; 3. `derive-ui` exit 0; 4. `verify-ui` exit 0 with
`Rendered gate clean` and `reported deviation: custom: com.meridian.m400.self_cal/1.0.0`
in stdout; 5. spawned `preview-ui` serves, and `GET /pages/device-features` contains
`action-burst_mode-burst_count`, the `Custom device actions` title, and every
`mode_banner_entries(simulated=True)` wording; 6. SIGINT stops the server with exit 0.

**Control arm (the discriminator fluff cannot pass).** Same project, only the composed
pin row removed (descriptor backed up with `cp`, restored after; never `git checkout`):
`derive-ui`/`verify-ui` still exit 0, the served page no longer contains
`action-burst_mode-burst_count` nor a `burst_mode` button, and `verify-ui` reports
`custom, renders nothing: com.meridian.m400.burst_mode/1.0.0`. (The descriptor records
a different digest after the edit, so the re-derive takes the stale-overwrite path — no
`--force` involved.)

**Sample size.** The lane runs in CI on every push (3-OS matrix; the spawn arm on
POSIX) and locally 3 consecutive times before push. Ship requires 3/3 local greens, a
green CI run, and CI `sdk`-job wall-clock increase ≤ 3 min on any OS, measured against
the parent commit's CI run.

**Kill directions.**
- *Ships*: all arms green under the sample-size rule above.
- *Kills (defect, not tuning)*: (a) any arm red from the installed wheel while its
  in-suite twin passes — a real standalone-path defect; the leg's outcome becomes the
  defect report, not a workaround; (b) the control arm fails to flip — the primary
  assertion was not measuring composition; redesign the discriminator before any merge;
  (c) CI delta > 3 min on any OS — switch to the pre-named fallback chosen now: mark
  the module `loop` and append the composed fill + control grep to the existing ubuntu
  wheel-smoke bash block in `ci.yml` (no new job).
- *Underpowered, not conclusive*: local greens but the CI lane cannot complete
  (runner/PyPI flake) or the lane is skipped anywhere it should run — the evidence is
  incomplete; rerun. A skipped or errored lane counts as RED for this rule.

**RED-sanity at build time**: the control arm is the mechanism-neutralized proof for
Commit 1 (run it with the strip applied — red on the composed assertions; restore —
green; paste both). Commit 2's refusal arms are written first and shown red until the
command exists.

## 9. Top risks, each with its falsifier

- **R1 — the spawned serve path differs from the in-process render** (guard policy,
  degraded adapter load, page routing) so the composed control never serves. Falsifier:
  the spawn arm itself; if it fires, the defect is in the standalone host path and this
  leg fixes it — that IS the leg's subject.
- **R2 — wheel `[server,scaffold]` resolution fails on some OS.** Falsifier: the
  install step; mitigated by shape-precedent (the CI wheel smoke already installs
  `[server]` at PR time and `[scaffold]` in the same workflow family).
- **R3 — the control arm does not flip** (some other surface renders `burst_mode`).
  Falsifier: the control arm's absence assertions; if it renders anyway, the
  discriminator narrows to `staged_control_ids` only and the button assertion is
  dropped — a design correction, recorded here, not a silent loosening.
- **R4 — Track B lands between design and build** (0.5.0 family copy, deferral-row
  removal). Falsifier: the lane's no-literal rule (§5); any literal that breaks is a
  lane bug, not a Track B coordination problem.
- **R5 — `pin-class`'s canonical-serialization guard refuses real author files.**
  Falsifier: the unit arm feeding a non-canonical descriptor (typed refusal, nothing
  written — intended). If review finds the guard too hostile, the pre-named alternative
  is print-only mode (validate + print the row, no write); choosing it later is a
  recorded decision against this risk, not post-hoc tuning.

## 10. Scoped out with reasoning (not deferrals — the gap census says these are not gaps)

- **`check` validating `contracts[]` pins**: `derive-ui` is the very next command in
  the loop and already refuses typed (`classref_vendor_catalog_*`); a pin walk in
  `check` duplicates the walk for one command's head start.
- **A composed example in the scaffold template**: the template is a byte-pinned
  interface (SRF-1/R-2 parity); the docs section carries the example document instead.
- **Batch pinning, pin removal, vendor-catalog pinning in `pin-class`**: one document
  per call; the vendor-catalog pin is the same row shape and can follow later if the
  friction is ever measured — the composed class is the loop's new surface.
- **Gateway anything**: the leg is SDK-only by the owner's disambiguation; Track A owns
  the mirror.

## 11. Addendum (2026-10-25) — the original green measured presentation only

Lane: `feat/556-standalone-fixes`, base `5c73f5b`. This section corrects the record; it
does not rewrite it. §8's acceptance rule and the arms landed by Commit 1 were honestly
measured, and what they measured was the composed **presentation**.

**State when the original arms ran.** The M-400 project loaded DEGRADED: the loader
validated every document, then failed the adapter entry point
(`adapter_factory: None`, `load_diagnostic: standalone_plugin_entry_point:
meridian_m400_plugin:create_plugin does not name a factory inside the
meridian_m400_plugin package`). Every green arm in this leg — the loop, the control
flip, the served page — passes over that degraded load, because
`classref_gate_render.render_pages` and the spawned listener both go through
`load_plugin_project`, and §4.5 degrades rather than refuses: the composed pages render
from the derived documents whether or not an adapter exists. The lane proved the
derivation and its rendering; it did not prove the plugin.

**Two causes, both fixed in this lane.**

1. The host's entry-point rule required the module to begin with `<package>.`, rejecting
   the package-root form `<package>:create_plugin`. The frozen descriptor schema admits
   that form (its entry-point pattern has no dot requirement) and every shipped
   standards example uses it, so the rule was stricter than the contract it serves.
   `load_plugin_project` now accepts the package itself or a module beneath it
   (`module == package or module.startswith(f"{package}.")`). A genuinely foreign
   module still diagnoses — including a sibling whose name merely shares the prefix
   (`example_plugin_extra.adapter`), which pins the dot in the boundary test — and a
   string naming no factory is still refused by the descriptor schema.
2. The scaffold's package root did not export the factory: `__init__.py` was a bare
   docstring while `create_plugin` lived in `adapter.py`. Admitting the package-root
   shape without that export would only have changed the diagnostic
   (`standalone_plugin_import: ... has no attribute 'create_plugin'`) while the adapter
   still never loaded. `template/src/{{ package_name }}/__init__.py.jinja` now
   re-exports the factory from `.adapter`, and the R-2 byte-parity fixtures under
   `tests/fixtures/scaffold_expected/` were regenerated from the renderer — the two
   fixture trees differ from their predecessors only in that file.

**What now guards it.** `test_the_loop_loads_the_plugin_adapter_not_only_the_presentation`
(in `tests/test_standalone_dev_loop.py`) asserts that the spawned listener prints no
`standalone_plugin_*` diagnostic of any kind, and that the INSTALLED SDK resolves a real
factory for the same project with no diagnostic. Neutralizing either half reddens it:
restoring the docstring-only template reproduces `standalone_plugin_import: ... has no
attribute 'create_plugin'`; restoring the strict module check reproduces
`standalone_plugin_entry_point: ... does not name a factory inside the ... package`.

**What that arm does not prove, so its claim does not outrun it.** It proves factory
RESOLUTION (import plus attribute), not a live connect: the fixture descriptor declares a
Meridian M-400 while the scaffold adapter answers the SDK's synthetic identity, so a
connect raises `standalone_connect_identity_mismatch` by design. It does not cover any
transport but the scripted mock, does not judge visual correctness, and says nothing
gateway-side — unchanged from §"What this module does NOT catch".

**`test_classref_acceptance.py` A1–A4 remain presentation-only, by design.** They render
through `render_pages` over the same degraded-adapter path and assert derived documents
and page content, not a loaded plugin. A later reader must not mistake them for load
proofs. Strengthening them is a separate arm's job, not an edit to those assertions —
none of them was weakened or replaced here.

## 12. Fold wave (2026-10-25) — the refute's F1-F3

An adversarial pass over the addendum's commits confirmed the string-level rule is
airtight and found that containment was still spelling-deep, plus two weaker arms. This
section records what changed; it does not rewrite §11.

**F1 — containment is provenance.** The string rule proves the entry point NAMES a
member of the package; it cannot prove the import resolved THIS project's bytes. Three
hand-reachable shapes defeat it with no diagnostic: (a) a package directory renamed to a
frozen stdlib name (`src/os` + `os:putenv`) — the frozen finder precedes the path finder,
so the factory is the builtin; (b) a namespace-only directory named for an installed
distribution — a namespace portion never beats a later regular package; (c) a second
project's namespace-only same-named package — the loader prepends each project's `src`
and never removes it, so project two resolves project one's regular package.
`load_plugin_project` now requires the imported module's file origin to be under this
project's `src`; a failure sets the `standalone_plugin_entry_point` diagnostic and leaves
`adapter_factory` None — the existing degrade path, not a refusal. The string rule is
unchanged.

Load ordering is now deterministic as well: the project's `src` is re-prepended on every
load (it was inserted only when absent), so the project being loaded is the first path
the import searches. Without that, a module-scoped project loaded again after other
projects had prepended their own `src` resolved another project's regular package — the
same cross-project shape as (c), on a project that is healthy, which the provenance check
would otherwise degrade.

The eviction that precedes the import is now guarded against builtin and frozen modules
and cache aliases: deleting a frozen `os` from the import cache re-executes it and
replaces the module object and its `environ`, so a directory NAME could corrupt the host
even though the provenance check would then degrade the load.

What the provenance check does not catch, stated in the module docstring: it runs AFTER
the import, so a foreign module's import-time code executes before the degrade; and it
says nothing about what the plugin imports itself — that is the plugin's own trust
boundary, not the entry-point rule.

**F2 — the A5 exclusion is existence-aware.** `_skip_if_exists` protects files that
already exist, so a template release that ADDS a path under `src/**` writes it; the
pattern-only exclusion excluded it from the required footprint and asserted it untouched,
reddening on correct behaviour. Excluded-and-asserted-untouched is now limited to deltas
whose project path exists before the update; an addition under `src/**` is a real change
in the footprint. Honest limit, recorded on the arm: at every COMMITTED state the base
ancestor equals the target tree, so `changed` — and every clause derived from it — is
vacuous in CI; the fix is proven by injecting a template delta, and the standing teeth
for template motion are A1 and A3.

**F3 — the installed-SDK probe asserts callable.** `adapter_factory is not None` passes
for a non-callable module attribute; the probe now reports `loaded` only for
`callable(adapter_factory)`, matching the checkout-side arm's callable-and-openable
assertion.

All four new/repointed arms are RED before their change and green after; the RED output
is quoted in the fold commit's message.
