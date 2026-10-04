# Issue #308 — PRD 12 SDK-SHIM: `preview-ui` becomes a shim, `preview_assets` is deleted, the SRF-2 test moves, obligation 7 closes, breaking SDK 0.7.0: design record

**Date:** 2026-10-04 · **Tracker:** madeinoz67/benchweave #308 (PRD 12 epic)
**PRDs:** `docs/implementation-planning/12-gateway-web-ui-prd.md` §6 R-5/R-9/R-10, §9 Q4/Q5 (ruled)
**Trigger:** satisfied — #309 (SA-PREVIEW) closed complete 2026-10-03; `benchweave-sdk` 0.6.0 live on PyPI (the `[server]` extra shipping `benchweave_sdk_server`).
**Evidence baseline:** gateway `main` `308ce13`; SDK `main` `e762676`; SDK PR #104 (`chore/ui-html-pin-020`, OPEN, 2 files: the `[server]` extra's ui-html pin 0.1.0→0.2.0 + `uv.lock`). Every file claim below was read at these commits; citations are `file:line`.

**Placement disclosure.** This record sits gateway-side. Both repositories carry a `.claude/deep-review/` (the SDK's latest: `2026-10-03-issue347-ws4-first-timer-docs-design.md`), but the convention is tracker-driven: #309's record — SDK-heavy slices, gateway tracker — sits gateway-side, and #308's cross-repo obligations (the pointer pairing, the obligation-7 row, the device-developer guide) are gateway-owned. Gateway-side it is.

---

## 1. Problem and root cause

The author's preview is two things today:

1. **The frozen React bundle** (`src/benchweave_sdk/preview_assets/`, `renderer_version 0.1.2` at freeze commit `085b0ff`) served by a stdlib `ThreadingHTTPServer` (`preview_server.py`) behind `benchweave-sdk preview-ui <envelope> --descriptor … --resources … --catalogue …` (`benchweave-sdk/src/benchweave_sdk/cli.py:1050-1140`, `_run_preview`), with a Textual status screen (`preview_tui.py`) and a per-document JSON API (`PreviewServer`).
2. **The standalone host** (since #309): `benchweave-sdk-server serve <project>` over the `[server]` extra — mock transport, the nine descriptor-derived scenarios, the `SIMULATED — mock transport` / `STANDALONE — no gateway` banners, degraded-load rendering.

PRD 12 Q4 ruled there is no separate preview tool — the standalone host IS the preview; R-5 froze the React bundle only as a bridge with SA-PREVIEW as its recorded exit. That exit is now met. What the bridge still costs, verified in-tree:

- **Two live preview stacks** whose agreement is pinned only by gateway-side checkout-bytes tests (`tests/sdk/test_preview_{cli,server,fixtures}.py` in the gateway, each `sys.path.insert(0, packages/sdk/src)` — they exercise the SUBMODULE POINTER's bytes, not any installed distribution).
- **`textual` sits in the base dependency set** (`pyproject.toml` `dependencies`) solely for the dying TUI (`preview_tui.py:7-9` is its only import; one frameworks test besides).
- **The frozen bundle blocks its own deletion's packaging**: `hatch_build.py::_validate_preview_assets` (called from `CustomBuildHook.initialize`) demands the tree at every wheel build.
- **SRF-2's pinning lives on the wrong side** (gateway, over pointer bytes) relative to R-10's ruling ("moves to the standalone distribution and runs against the installed SDK version it depends on").

## 2. Verdict

**BUILD.** One SDK slice plus one gateway pointer motion, one train, breaking SDK release **0.7.0** (pre-1.0 breaking = minor bump; the issue-#64 precedent, "MINOR bump (tightening = breaking class)").

## 3. The mechanism

### 3.1 The shim (`benchweave_sdk/cli.py`)

`preview-ui` is re-declared as a strict mirror-subset of `serve`'s options:

```
benchweave-sdk preview-ui <PROJECT> [--host H] [--port P] [--allow-network] [--no-open] [--scenario <id>]
```

- **Transport is pinned, not a flag.** The shim always delegates with `transport="mock"` (R-9's letter). Real-hardware serving is `benchweave-sdk-server serve` directly; when I3 grows a serial transport, `preview-ui` stays mock by design (deferral D-6).
- **Delegation is in-process click**: the command body lazily does `from benchweave_sdk_server.cli import serve as _server_serve` and `ctx.invoke(_server_serve, project=project, host=…, port=…, allow_network=…, no_open=…, transport="mock", scenario=scenario)`. Body-import only — module-level would invert the core→server layering (the server already imports core at module level: `benchweave_sdk_server/cli.py:23` `from benchweave_sdk import __version__`). The body-import of a fully-loaded core is cycle-free; a test pins the import order.
- **The extras refusal is inherited, not re-probed.** On a default install `benchweave_sdk_server.cli` imports fine (its module level is extra-free by #309 slice A's design), the invocation reaches `serve`'s body, `import uvicorn` fails, and `_require_server_extra` prints `benchweave_sdk_server_extras_missing:` naming `benchweave-sdk[server]` and exits 2 — exactly R-9's required shape, one refusal code, not per-command duplicates. The helper's message gains a caller clause (`serve`/`mcp`/`preview-ui`); the existing pins (prefix + install command, `tests/server/test_cli.py:137,147,225`) hold unchanged. The shim's own `except ImportError` around the body-import covers only the mangled-install case (package bytes absent) with the same prefix, exit 2.
- **The old surface dies, loudly**: `<envelope> --descriptor --resources --catalogue --fixtures --renderer-url` are gone; click's unknown-option errors say so. No silent repurposing. The migration is the changelog's BREAKING footer.
- **Parity pin (new test)**: `preview-ui`'s declared option set equals exactly {project, host, port, allow-network, no-open, scenario}, each name/default matching `serve`'s declaration — the shim cannot drift from `serve` silently (risk R2's kill).

### 3.2 Deletions and relocations (all consumers traced)

| Piece | Disposition | Evidence |
|---|---|---|
| `src/benchweave_sdk/preview_assets/` (site + inventory) | **DELETED** | issue scope |
| `preview_server.py` | **DELETED**, two relocations: `validate_listener` and `MAX_REQUEST_BYTES` move to `benchweave_sdk_server/security.py` — their only surviving consumers are `serve` (`benchweave_sdk_server/cli.py:187`) and security's own re-export (`security.py:31`). NFR-S1's "verbatim reuse" becomes ownership (provenance note in the docstring). `PreviewServer`, `bundled_assets`, `verify_bundled_assets`, `_handler` have no other importers (traced) | grep: `validate_listener` at cli.py:1065/1067 (dies with `_run_preview`), server cli.py:187/190; `bundled_assets` only cli.py:1065/1090 |
| `preview_tui.py` | **DELETED**; `textual>=8.2,<9` leaves `[project] dependencies` (the base install SHRINKS — the disclosed breaking dependency change; PKG-1/PKG-2's no-growth basis is intact) | `textual` imports: preview_tui.py:7-9 only |
| `cli.py` `_run_preview`, `_renderer_origin`, `_renderer_target` | **DELETED** (replaced by the shim) | cli.py:1002-1140 |
| `console.py::preview_ready` | **DELETED** (sole caller dead) | console.py:66 |
| `hatch_build.py::_validate_preview_assets` + call | **DELETED** (a hook demanding a deleted tree reds every build); `publish.yml`'s "and preview assets" comment updated | hatch_build.py:24-42, initialize |
| `fixtures.py::_renderer_version` | **RE-DERIVED** from the installed SDK's own version (`importlib.metadata`, the same derivation `__init__.py` uses for `__version__` — derived, never a literal). The served document's `renderer_version` now reports the emitter's version; the React renderer's build version (0.1.2) died with the bundle. The plugin-ui-preview 0.2.0 wire schema keeps validating (the field is a required string, `preview-document.schema.json:11,24`) | fixtures.py:335-343 read `preview_assets/inventory.json` — breaks at deletion; `renderer_version` consumers today: the dying console/TUI paths + two tests being updated |
| `preview_models.py` | **KEPT, untouched** — the server imports `PlotView` (`benchweave_sdk_server/presentation.py:51`, `plots.py:29`) | |
| `presentation.load_validated_preview_inputs`, `fixtures.build_preview_model` / `generate_baselines` / `load_author_fixtures` / `project_plot_views` | **KEPT** — consumers: the server's loader (`session.py:271-276`, `presentation.py:398`) and the scaffold's generated offline conformance test (`presentation.py::_write_preview_examples` writes `tests/test_presentation_preview.py` into every scaffolded project, importing both) | |

### 3.3 The SRF-2 motion (R-10)

- **MOVE**: the gateway's `tests/sdk/test_preview_fixtures.py` eight projection arms (`test_projection_covers_the_manifest_corpus_shapes` … `test_lanes_view_projects_and_validates_against_the_wire`, lines 356-566) → the SDK repo's `tests/test_preview_fixtures.py`, schema paths re-pointed from the gateway `standards/` tree to the SDK's vendored tree (the SDK suite's existing arms already resolve that way). These arms pin `project_plot_views`, which has **no SDK-side test home today** (verified) and survives this slice.
- **DIE as redundant**: the gateway file's first eight arms — byte-equivalent duplicates of the SDK suite's existing eight.
- **STRENGTHEN**: `tests/server/test_adapter_failure.py::test_document_failures_still_refuse_startup` (the SRF-2/R-10 arm, line 44) gains a paired arm asserting agreement in BOTH directions on the same presentation mutation: `check-ui` exits non-zero AND `load_plugin_project` refuses `standalone_plugin_invalid:`. This is R-10's agreement test, living in the standalone distribution's suite, resolving `benchweave_sdk` from the synced venv (the installed dependency) — never a `sys.path` checkout.
- **INSTALLED-WHEEL PROOF** (the literal "installed SDK version"): the publish workflow's smoke gains (a) on the existing default-install matrix — `benchweave-sdk preview-ui <project>` exits 2 with prefix + install command, no traceback; (b) one ubuntu-only `server-smoke` step — a second venv with `dist/*.whl[server]`, spawn `preview-ui <scaffolded> --no-open --port`, poll `GET /` → 200 with both banners, SIGINT → exit 0.

> **[ERRATUM 2026-10-04 — review fold adv2 F1.]** The "byte-equivalent
> duplicates" claim in the DIE-as-redundant bullet above is false for 2 of
> the 8 first-arms. The gateway's
> `test_preview_model_is_built_from_the_validated_candidate` also asserts
> `[view.kind for view in model.plot_views] == ["time_series"]` over the
> real scaffolded project, and the gateway's
> `test_served_preview_document_conforms_to_wire_schema` also asserts the
> served-document plot_views trio (non-empty; `[0]["kind"] ==
> "time_series"`; `[0]["channels"][0]["color_role"] == "muted"` — the
> scaffold's declared hint surviving to the served document) plus the
> poisoned-plot schema negative (`color_role` `"critical"` must refuse).
> No SDK-side commit ever carried these four pins
> (`git log -S '== ["time_series"]' -- tests/test_preview_fixtures.py` and
> `git log -S 'poisoned_plot' -- tests/test_preview_fixtures.py` are empty
> over the SDK history; the only prior hit on the loose
> `view.kind for view in model.plot_views` token is the moved corpus-
> candidate arms, commit 55a6349 — the divergence itself). All four are
> carried into the SDK copies on `feat/issue308-sdk-shim` (this fold), so
> the §4.4 gateway deletion loses no pin. The frozen text above is
> unchanged; this bracketed note is the correction of record.

### 3.4 SDK-side docs, invariants, scaffold

- **SDK invariants**: SRF-2 amended (anchors move to the host loader + the SDK validator; pinning suite = the standalone distribution's); PKG-3 RETIRED with a closed-record rewrite (its claimed enforcement — "the `ui` job's `git -C packages/sdk diff`" — no longer exists in gateway CI either; verified absent). Drift row 6's suite list updated; row 7 rewritten to its closed form.
- **CLAUDE.md** architecture rows: the Preview subsystem row re-homes.
- **README "Local UI preview" + `user_guide/plugin-sdk.qmd` preview paragraphs** (`README.md:195-216`, `plugin-sdk.qmd:140-144`): rewritten to the shim. Published user-facing surface — **the build brief dispatches `document-writer`** (ASD-STE100 register).
- **Scaffold agent assets**: `template/.claude/skills/benchweave-plugin-ui/SKILL.md.jinja:29-50` cites the OLD command line; `template/AGENTS.md.jinja:53` the preview — rewritten to the new surface. Scaffold output changes → the R-2 byte-parity fixture (`tests/fixtures/scaffold_expected/`) regenerates; `tests/test_agent_assets.py` (R-5b triangulation) updated. The scaffold-output change is disclosed in the PR as an interface change (SRF-1 discipline; drift row 2's instruction).
- **CHANGELOG**: git-cliff renders from conventional commits — the slice's commit carries `feat!:` plus a `BREAKING CHANGE:` footer naming the command-surface change, the `[server]` requirement for `preview-ui`, and `textual`'s removal. The entry lands at the 0.7.0 release event.

## 4. The gateway motion (after the v0.7.0 tag)

One PR, the #189 version-pairing shape, landing promptly after publish (the `sdk-drift` lane reds main in the window by design — fail-closed freshness, #347):

1. `packages/sdk` gitlink → the `v0.7.0` tag's dereferenced commit (`scripts/check_sdk_submodule_drift.py` exit 0).
2. `standards/standards-manifest.json` `sdk_compatibility.sdk` 0.6.0 → 0.7.0 — CON-12's mirror duty at pointer-advance time. **Standards-byte motion**: the tripwire (`git diff origin/main...HEAD -- standards/`) reports exactly this row and nothing else; the standards-governor dispatch fires; the principal's word is the permission gate per the standing involvement check.
3. `docs/compatibility-matrix.md` re-rendered; `make check-sdk-standards` + `tests/standards/` green.
4. Gateway test deletions: `tests/sdk/test_preview_cli.py`, `test_preview_server.py`, `test_preview_fixtures.py` (SRF-2 duty moved per R-10; their mechanisms are gone at the new pin); `tests/sdk/test_cli_frameworks.py`'s `preview_ready` + Textual-lifecycle arms die, the command census keeps `preview-ui` (it remains a command); `tests/sdk/test_presentation_cli.py` survives intact (check-ui/scaffold arms — its imports all survive at 0.7.0).
5. `docs/internal/drift-and-obligations.md` obligation 7: the frozen-bundle paragraph replaced by the closed record (deleted at 0.7.0; `preview-ui` is the R-9 shim; the hatch integrity check retired with the tree). The row itself stays numbered — closed, not deleted.
6. `docs/device-developer-guide.md:368-374` (the plot/hints paragraph naming the old preview's projection+renderer): the preview sentence re-homes to the standalone host (STE100; `document-writer`).

## 5. Precedent (principle 9 — extend, don't invent)

| Piece | Proven in-tree mechanism |
|---|---|
| Extras refusal, exit 2, prefixed error | PRD 12 R-9's own pattern, landed by #309 slice A (`benchweave_sdk_server/cli.py` `_require_server_extra` + the `tests/server/test_cli.py:135-148` pins) — the shim is its second consumer |
| In-process delegation | click `ctx.invoke` over the in-tree command — the same invocation shape `tests/server/test_cli.py::test_serve_prints_the_diagnostic_and_proceeds` uses (uvicorn monkeypatched) |
| Relocation-to-owner moves | #309 slice A's move-map discipline (`git mv` + consumer re-point + a rename-completeness gate) |
| Breaking pre-1.0 release | issue #64's MINOR-for-breaking precedent; the 0.6.0 release flow (bump commit → tag → publish smoke → release-review matrix walk → PyPI read-back) |
| Version-pairing pointer PR | #189's one-merge shape (matrix + pointer + manifest + test) |
| Test-duty motion | the SDK's own drift row 6 rule — SDK behavior lives in the SDK suite; only cross-repo comparisons stay gateway-side |

New architecture introduced: **none**. The shim is a command-body alias over an existing command.

## 6. Invariant and drift impacts

- **Gateway CTL-*/STO-***: untouched — no gateway control/state code moves.
- **CON-12** unchanged: the mirror moves per its own amendment (pyproject@pin → lock → mirror).
- **CON-4/PKG-1/PKG-2** (SDK): the default dependency set SHRINKS (`textual` out); no new runtime dependency; the standards lock and vendored tree untouched (`sync-standards --check` stays green — no corpus motion).
- **SDK SRF-2/PKG-3/drift rows 6-7**: amended/retired as §3.4.
- **Zero-literal gate**: `renderer_version`'s new derivation is `importlib.metadata` — register discipline kept; counter scope unchanged.
- **Known-stale corpus prose, deliberately untouched**: the vendored plugin-ui-preview schema's description cites the deleted React decoder (`ui/src/preview/api.ts`) — already stale since G1e, frozen bytes, not this slice's to edit (D-2).

## 7. Acceptance rule — pre-committed (written before any measurement below runs)

Deterministic; a third party can execute. Both checkouts; `UV_PROJECT_ENVIRONMENT=venv`; exit codes read unpiped; counts from `--junitxml` attributes or exit codes, never an output-filter summary line.

**SDK slice**

- **A1 wheel census.** `uv build`; `unzip -l dist/*.whl` → **zero** entries under `benchweave_sdk/preview_assets/`; `preview_server.py`/`preview_tui.py` absent from the listing; `benchweave_sdk_server/` intact. RED baseline: the same command on `main` lists the preview_assets entries (count recorded in the PR body).
- **A2 default-install refusal (R-9).** Fresh venv 1: `pip install dist/*.whl`; scaffold a project (`benchweave-sdk new p --with-ui`); `benchweave-sdk preview-ui p` → **exit 2**, stderr contains `benchweave_sdk_server_extras_missing:` AND `benchweave-sdk[server]`, and does NOT contain `Traceback`.

> **[ERRATUM 2026-10-04 — review fold R4.]** A2's letter was unexecutable as
> written: the bare default install cannot run `new` — WS2 (issue #347)
> made the `[scaffold]` extra load-bearing for scaffolding after v0.6.0
> tagged, so the bullet's scaffold step refuses with `scaffold_extra_absent:`
> before preview-ui ever runs. The correction (commit e2c8279): the release
> smoke installs the wheel with `[scaffold]` (still no `[server]` — the axis
> A2 tests), and the local A2 proof used a plain existing directory; the
> refusal fires in serve's body before any project load. The frozen bullet
> text above is unchanged.
- **A3 delegation (both arms).** Fresh venv 2: `pip install 'dist/benchweave_sdk-*.whl[server]'`; spawn `benchweave-sdk preview-ui p --no-open --port <fixed>` in the background; poll `GET /` → 200 with `SIMULATED — mock transport` AND `STANDALONE — no gateway`; SIGINT → exit 0. In-process arm (suite): `uvicorn.run` monkeypatched; the invocation is recorded AND `transport == "mock"` — RED: relaxing the pin (dropping the explicit mock) fails the arm.

> **[ERRATUM 2026-10-04 — review fold R5.]** A3's banner wordings are stale
> record prose: the mode-banner rework (PRs #97/#101, after this record's
> evidence baseline and after v0.6.0) replaced them. The tree's pinned
> wordings rule — `SIMULATED PRESENTATION DATA` (mock transport only) and
> `NO GATEWAY · LOCAL PRESENTATION ONLY` (both transports), per
> tests/server/test_banner.py; commit 8e8bf78 corrected the smoke to grep
> those, and the live re-proof measured both present with SIGINT exit 0.
> The frozen bullet text above is unchanged.
- **A4 no-fallback pins.** A suite arm asserts `import benchweave_sdk.preview_server` raises `ModuleNotFoundError` (the old path is gone — the never-fallback structural pin); `grep -rn "preview_assets" src/ tests/ .github/ README.md` → **0** hits (rename-completeness, the A-R shape).
- **A5 coverage motion.** Full `uv run pytest -q --junitxml=…` exit 0; collected count = main's count − deleted arms + moved 8 + new arms, with a PR-body mapping table naming every dying arm (gateway 34 + SDK-side deletions) and its disposition (dies / dies-as-duplicate / moves / already-covered-server-side). A collected count of 0 is a FAILED gate.
- **A6 static.** Bare `uv run ruff check .` exit 0; fresh-cache (`rm -rf .mypy_cache`) bare `uv run mypy` exit 0.
- **A7 scaffold parity.** `tests/test_agent_assets.py` green; the `tests/fixtures/scaffold_expected/` diff names ONLY the agent-asset files.

**Gateway motion**

- **B1** `python3 scripts/check_sdk_submodule_drift.py` exit 0 (gitlink at `v0.7.0`).
- **B2** `make check-sdk-standards` green; `tests/standards/` green; the matrix render shows 0.7.0.
- **B3** Gateway suite green after the trio deletion (bare ruff; fresh-cache bare mypy; full battery before push).
- **B4 tripwire + governor.** `git diff origin/main...HEAD -- standards/` = exactly the `sdk_compatibility.sdk` row; result reported in the PR; the standards-governor pass attached.

**Ship it if:** A1-A7 hold on the implementing run with outputs in the PR bodies; both pushed branches' CI green; the release event publishes `v0.7.0` (the owner's call; release-review matrix walked between bump and tag); B1-B4 hold on the gateway branch; #308's exit gate is all true (R-9/R-10 met, `preview_assets` gone, obligation 7 closed, the changelog states the break).

**Kill it (the mechanism, not a test defect):** the shim cannot pin `transport="mock"` through `ctx.invoke` without re-implementing `serve`'s option parsing (the parity pin of §3.1 cannot be written); the default install cannot reach the prefixed refusal without a traceback path (the lazy-guard premise breaks); the wheel still ships `preview_assets` bytes through a packaging path A1's census misses; `build_preview_model` cannot source `renderer_version` without a version literal (the zero-literal gate conflicts) — stop and re-report rather than warping the design.

**Underpowered, not conclusive:** failures confined to pip/network/port-allocation/runner-OS behavior — fix the environment, re-run; no verdict until a clean run.

## 8. Review tier and the Step-1 keyword scan (#254)

**Both slices TIER 3** — the maximum across each slice's expected diff. Triggers: **SDK slice** — removes a dependency (`textual` out of `[project] dependencies`; `pyproject.toml` + `uv.lock`). **Gateway slice** — advances the `packages/sdk` submodule pointer; touches `standards/standards-manifest.json` (also fires the standards-governor mandate). Consequence: two independent adversarial refute lanes per slice (the 2026-09-24 retro R3 rule), deliberately.

Keyword scan over each slice's **expected diff text** (docs and code alike; deletions count). Counts measured over the current bytes of every file the slice deletes or modifies — file-level upper bounds, refined where the diff touches only part of a file:

| keyword | SDK slice | gateway slice | where |
|---|---|---|---|
| `threading` | ~4 | 0 | `preview_server.py` deletion (ThreadingHTTPServer) |
| `asyncio` | ~5 | ~2 | user-guide prose context, `test_cli_frameworks` context lines, record prose |
| `subprocess` | 0 in diff lines | 0 | `cli.py`'s 7 hits live in the untouched `submit` path |
| `sha256` | ~9 | 0 | `preview_server.py` (2), `inventory.json` (3), `hatch_build.py`'s dying function (4) |
| `hashlib` | ~5 | 0 | `preview_server.py` (2) + `hatch_build.py` (3) |
| `migrate` | 0 | 0 | none |
| `recovery` | ~2 | 0 | README/guide prose rewrites + record prose |
| `protection` | ~1 (+3 in deleted minified renderer JS) | 0 | record prose; bundled JS |

Tier 3 is hard-triggered by the dependency/pointer rules regardless of keyword presence; the scan is reported for the record's own rule.

## 9. Top risks, each with its falsifier

- **R1 — lazy-import layering hazard** (core body-imports the server package, which imports core at module level). Falsifier: A2/A3 on fresh venvs plus an explicit import-order suite arm (`import benchweave_sdk.cli`, invoke, re-import `benchweave_sdk_server.cli`) — a cycle reds immediately.
- **R2 — shim/serve surface drift** (`serve` grows flags; `preview-ui` lags). Falsifier: the §3.1 parity pin — reds the day the option sets diverge.
- **R3 — SRF-2 lying green against a stale install** (the CI suite tests the synced project; a cached wheel could differ). Falsifier: the publish-smoke arms run the literal installed wheel + A1's census. Disclosed residual: the installed-shape proof lives at release time only, not on every push.
- **R4 — the sdk-drift lane reds main between publish and pointer merge** (by design). Mitigation: release + gateway PR in one session (the coordinated-landing rule); the window is disclosed, not avoided.
- **R5 — `pyproject.toml`/`uv.lock` collision with PR #104.** Mitigation: §10's sequencing.
- **R6 — scaffold output change breaks downstream project diffs.** Mitigation: confined to the two managed agent-asset files; `upgrade`'s conflict-marker discipline; the PR states the interface change.
- **R7 — `renderer_version`'s semantic change surprises a value-pinned consumer.** Falsifier: repo-wide grep — no consumer asserts the value outside the two tests this slice updates; the change rides the BREAKING footer.

## 10. Landing order (two-repo discipline)

1. **Wait for SDK PR #104 to merge**, then branch off merged main. Both branches touch `pyproject.toml` + `uv.lock`; serializing avoids lock-regen conflicts and a double `--refresh-package` dance. Fallback if #104 stalls: stack the SDK branch on `chore/ui-html-pin-020` per PR-stack rules — tradeoff: the 0.7.0 release cut then couples to #104's review latency, and its diff view grows by the pin bump.
2. SDK branch `feat/issue308-sdk-shim`; full battery before push; SDK PR opened immediately (single issue stream — gateway #308; the PR body notes no SDK-side issue exists by design); Tier-3 refute (two lanes) before merge; merge on the full rollup (`scripts/merge-verified.sh`).
3. **Release event (the owner's call):** bump-to-0.7.0 `chore(release)` commit, the release-review matrix walk (`docs/internal/release-review-matrix.md`), tag `v0.7.0`, publish (the smoke's new arms fire here), PyPI read-back, changelog render.
4. Gateway branch (this branch): the §4 motion; PR linked to #308; governor pass; merge on the full rollup; #308 closes on the full set.

## 11. Deferrals (identifier · deferred · home · reopen trigger)

| id | deferred | home | reopen trigger |
|---|---|---|---|
| D-1 | `--authoring`/`--unattended` passthrough on `preview-ui` (authors use `benchweave-sdk-server serve` directly) | this record | an author-workflow need names the alias |
| D-2 | vendored plugin-ui-preview schema prose staleness (the deleted React decoder citation) | the gateway corpus (standards motion, never a hand edit) | the next plugin-ui-preview version increment |
| D-3 | `renderer_version`'s long-term fate as a wire field (now emitter-version; schema unchanged) | the plugin-ui-preview corpus | a 0.3.0 consideration or a second emitting consumer |
| D-4 | the SDK repo's historical PRD prose citing `preview_server.py` (`docs/prd/2026-09-27-standalone-web-ui.md`) | frozen history | never |
| D-5 | the ui-html 0.2.0 pin | SDK PR #104 | its merge (or the §10.1 fallback) |
| D-6 | hardware serving through the `preview-ui` alias (transport ≠ mock) | this record (R-9 pins mock by design) | an owner ruling; I3 grows `serve`, not the shim |

## 12. What this record does not decide

The release timing (the owner's); PRD amendments (none needed — R-5/R-9/R-10 already rule this posture, and PRD 11 was amended by #309's train); #285 (I3) scopes; the ui-html census guard (#309's D-B5 deferral, unchanged).

## 13. Owner flags (surfaced, not picked silently)

1. **The old per-document interface dies** (`preview-ui <envelope> --descriptor …` → `preview-ui <project>`). Q4-adjacent and breaking-release-sanctioned, but the owner confirms the migration wording — ad-hoc previewing of a presentation envelope outside a project layout has no successor.
2. **`renderer_version` now reports the SDK's version** — a wire-visible value change under an unchanged schema.
3. **Author-fixture scenarios and `--renderer-url` have no live-preview successor** (offline fixture validation survives via `check-ui` and the scaffold's generated test); designed loss under Q4's ruling, disclosed rather than silently dropped.
