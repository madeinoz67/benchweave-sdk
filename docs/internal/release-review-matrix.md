# Release-review matrix — every surface a version bump can leave stale

> The instrument the release review walks, per issue #117. Each row is a
> version-bearing surface, the machine source that outranks it, and what stale
> looks like. Run the matrix between "code merged" and "tag pushed" — after the
> bump commit exists, before the tag is cut. Every row records its result
> (updated / correct-as-is / n-a), including empty results; an empty contributor
> window is a recorded result, not a skipped step.

| # | Surface | Machine truth | Stale pattern |
|---|---------|---------------|---------------|
| 1 | README version stamp (baseline line) | `pyproject.toml` `version` | previous release number |
| 1b | User-guide "current SDK" sentence (`user_guide/plugin-sdk.qmd` intro; the wheel filename is a glob since #102) | `pyproject.toml` `version` | previous release number (observed live two releases late behind the docs deploy lag) |
| 2 | Website hero status line (`website/index.html`, hero badges) | `pyproject.toml` + the standards lock's ACTIVE otdp row (`OTDP_VERSION` / `ADAPTER_API_VERSION` derive lazily from it — `__init__.py`'s `__getattr__`, #215; multi-row lock: the active row governs, never "the one row") | previous SDK number, OTDP number behind the active row |
| 3 | Website docs-version selector (options + `(latest)` label) — TWO surfaces: the `website/index.html` static selector AND the `great-docs.yml` `versions` list (retro 2026-09-25 R3: a phase-2 that edits only the yml fails CI Docs — the verifier reads the static selector's label) | `great-docs.yml` `versions` list + `website/index.html` selector options + git tags | previous `(latest)` label on either surface, missing prior-release option |
| 4 | Website compatibility tagline | `standards-lock.json` `compatibility.main_project` floor + the release's tested pair | previous SDK number against the gateway floor |
| 5 | Website standards badges (interface / plugin-ui / plugin-ui-preview) | `standards-lock.json` `standards[]` — the ACTIVE row per id (`"active": true`; the multi-row lock carries yanked and non-active versions beside it, #215 — the active row governs the badges, never "the one row per id") | badge behind the active vendored contract version |
| 6 | `great-docs.yml` `versions` list | git tags | new tag absent, previous release still `latest: true` |
| 7 | Contributor window | `git log <prev-tag>..HEAD --format='%an'` minus bots and the owner | unacknowledged new human contributors; empty window = recorded result |
| 8 | Gateway `uv.lock` SDK pin (cross-repo) | the released SDK version | pin behind the release; moves on the gateway's next gateway-side lock run — a note, not a blocker |
| 9 | Served-set bump class (issue #203 slice 1, owner Q8) | `standards-lock.json` rows + `dependency_policy` mirror vs the PREVIOUS lock | one SDK version covering two served sets: a carried-set change on an unchanged range that is not a PATCH-class bump, or a declared-range change that is not MINOR at least — the sync itself refuses `sdk_bump_class_invalid:`, and the gateway's `benchweave.standards check` refuses the lock↔manifest disagreement (`served_set_drift:` / `policy_mirror_drift:`) |

## Test surfaces (issue #408 S4)

Version-bearing TEST surfaces — the same walk, the same file (a sibling
census file would be a second instrument to forget):

| # | Surface | Machine truth | Motion / classification |
|---|---------|---------------|------------------------|
| T1 | `tests/fixtures/scaffold_expected/base/**` | the `create_project` render at the pinned version | release-cut regen step (R-2); tripwire = the byte-parity suite |
| T2 | `tests/fixtures/scaffold_expected/ui/**` | the `create_project(with_ui=True)` + `create_ui_resources` render | same |
| T2b | `tests/fixtures/scaffold_expected/provider/**` | the `create_project(provider_transport=True)` render (row f; NO `create_ui_resources` — the shapes are mutually exclusive) | same |
| T3 | `tests/test_scaffold_copier.py` | consumes T1/T2; its docstring carries the regen procedure | the docstring moves only when the procedure changes — it now points at `make release-cut` as the procedure |
| T4 | `tests/test_scaffold_update.py` synthetic `v0.8.0` tags | scratch-repo fixtures fabricating "some released tag" | **inert by design** — no bump motion; the row exists so the walk never wonders (the honest-negative row) |
| T5 | Version literals in tracked tests that name the CURRENT release number — `tests/test_standards_verify.py` is the lock-anchor carrier (issue #473) | `pyproject.toml` `version`, which the test derives instead of restating (`tests/test_standards_verify.py::test_train_sync_lock_anchor_moves_with_pyproject`) | **derived by construction — a literal here is a defect, not a motion.** The v0.14.0 release stamped the lock anchor and left this test asserting 0.13.0; SDK main was red on all three operating systems until #154 (the literal) and #155 (the derived form). Scenario literals naming OTHER versions are inert and stay: the fixture-lock tables in `tests/test_dependency_serving.py`, T4's synthetic tags. Census at 0.23.0 (2026-10-26, owner's measurement, both quote styles): 0 of 155 tracked `tests/*.py` files name the current version. Enforcement, and its edge, stated so the walk does not assume more than exists: `test_release_cut.py::test_matrix_test_surfaces_match_the_registry` refuses a DOUBLE-QUOTED current-version literal in the anchor carrier and nothing else — another test file, a single-quoted or constructed form, slips past it, and the zero-mode counter (`scripts/count_version_literals.py`) scopes `src/benchweave_sdk/` and `src/benchweave_sdk_server/` only. The walk covers what the gate does not. |

Closing clause (mirrors the gateway's obligation 18): a new bump-sensitive
TEST surface is a defect — register it here AND in `DECLARED_SURFACES`
(`scripts/release_cut.py`), or make it derived. The registry is the
enforcement: an unregistered bump-sensitive surface is by construction one
release-cut does not sweep (the mutation arms in the design record's §9
prove the tripwire catches exactly that).

## The ordering constraint (row 6 is a pre-tag step)

The registration of the new version in `great-docs.yml` must land **before
the tag is cut**, not after: the docs assembly builds each version's bucket
from that version's own tag, and filters the tag's own versions list against
the requested version. A tag whose list does not contain itself builds zero
versions and fails (observed: v0.0.4 cut before its registration; the Build
Docs job failed with `Multi-version build: 0 version(s)` until the tag was
re-pointed onto the registration commit). v0.0.3 got this right by four
minutes; the review exists so the next release does not depend on luck.

## How the rows resolve

- Prose defers to the machine source in the middle column; when they disagree,
  fix the prose, never the machine source.
- Rows 1–6 are SDK-repo surfaces, edited in the release-review PR that also
  carries this matrix's result table. Row 7 runs `git log` against the two
  tags; row 8 is a recorded note unless the pin is materially misleading.
- Post-release verification (after the pipeline): PyPI JSON API shows the new
  version with wheel + sdist; the docs site shows the new bucket in the
  selector; the release body is the git-cliff notes.

The gateway can adopt this skill/matrix pair when its own releases need the same gate.

## Result record — v0.1.0 (2026-09-22)

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated → SDK 0.1.0 |
| 2 | Website hero status | updated — 2 stamps → SDK 0.1.0; OTDP 0.2.0 / adapter API 1.1 correct-as-is against `__init__.py` |
| 3 | Docs selector | updated — v0.1.0 (latest); v0.0.4 prior option added |
| 4 | Compatibility tagline | updated — SDK 0.1.0 against main project `>=0.1.0` (lock floor unchanged) |
| 5 | Standards badges | updated — registry 0.1.0→0.1.1, plugin-ui-preview 0.1.0→0.1.1 vs lock; interface 0.1.0 / plugin-ui 0.2.0 / execution 0.1.0 correct-as-is; otdp 0.2.0 also correct-as-is at that point but UNCHECKED — the row's list omitted otdp entirely, the miss #147's RedTeam EN-6 caught at the website badge; the instrument now enumerates all six standards (otdp, registry, interface, plugin-ui, execution, plugin-ui-preview) against the lock |
| 6 | great-docs versions | updated — v0.1.0 `latest: true` registered before the tag; v0.0.4 demoted |
| 7 | Contributor window `v0.0.4..HEAD` | platima — 35 commits, new human contributor; acknowledged in the tag message and release notes |
| 8 | Gateway `uv.lock` pin | note — moves on the gateway's next lock run, as designed |

Note: `standards-lock.json` `compatibility.sdk` still reads 0.0.4. The field is
written by the sync machinery and read by no gate (the matrix rows use the
`main_project` floor and `standards[].version`); it self-corrects at the next
standards sync. Recorded, not blocking.

## Result record — v0.8.0 (2026-10-05)

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated → SDK 0.8.0 (OTDP 0.2.2 / adapter API 1.1 correct-as-is) |
| 1b | User-guide "current SDK" sentence | n-a — no version-stamped sentence found in `docs/` this release (the wheel filename is a glob since #102); recorded result, not a skipped step |
| 2 | Website hero status | updated — SDK 0.7.1 → 0.8.0; OTDP 0.2.2 / adapter API 1.1 correct-as-is against the lock's active otdp row |
| 3 | Docs selector | WALKED TWO-PHASE — phase 1 (this PR): no edit; the selector stays consistent with the current tag set (v0.7.1 latest). Phase 2 rides the tag commit, pushed with the tag in one action: v0.8.0 (latest) + v0.7.1 prior option on both surfaces. |
| 4 | Compatibility tagline | updated — SDK 0.8.0 against main project `>=0.1.0` (lock floor unchanged; `compatibility.sdk` moved 0.7.1 → 0.8.0 in this PR — the lock-anchor ritual, the #189 pairing shape) |
| 5 | Standards badges | correct-as-is — all six match the lock's ACTIVE rows (otdp 0.2.2, registry 0.1.2, execution 0.2.0, interface 0.1.0, plugin-ui 0.3.0, plugin-ui-preview 0.2.0); no standards motion since v0.7.1 (`git diff v0.7.1..HEAD -- standards-lock.json --stat` empty) |
| 6 | `great-docs.yml` versions | PHASE-2 PLAN — the tag commit registers v0.8.0 `latest: true` and demotes v0.7.1 (the ordering constraint: a tag missing itself fails the docs build) |
| 7 | Contributor window `v0.7.1..HEAD` | empty — every one of the 16 commits in the window is the owner (Stephen Eaton); no bots. Recorded result. |
| 8 | Gateway `uv.lock` SDK pin | recorded note — moves at the gateway's next lock run; the gateway pairing for this release rides gateway #406 (its submodule pointer re-points at the tag) |
| 9 | Served-set bump class | n-a — no served-set motion in the window: the lock is byte-identical to v0.7.1's apart from `compatibility.sdk` (the certified-version field); neither stale pattern can fire. |

MINOR class: the window carries new user-visible features (I3b capture lifecycle / SQLite library / SSE capture events, #110; the serial reader ring default 256→512 KiB re-sized for the 3 Mbps class, #119) — not a patch window.

## Lineage (why this exists)

Found by the v0.0.4 release review (issue #117): the README stamp was re-staled
by the very release that fixed it one release earlier, the website status line
carried an OTDP 0.1.0 vs machine-constant 0.2.0 drift nobody had caught, the
plugin-ui badge was two contract versions behind the lock, and the docs
selector lacked the prior-release option. Principal directives 2026-09-20:
the bump triggers a release review (docs sweep + contributor acknowledgment),
the checklist is a matrix in `docs/internal`, and a skill walks it.

## Result record — v0.2.0 (2026-09-24)

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated → SDK 0.2.0 (OTDP 0.2.2 / adapter API 1.1 correct-as-is) |
| 2 | Website hero status | updated — two stale stamps: SDK 0.1.0 → 0.2.0, OTDP 0.2.1 → 0.2.2 (against `__init__.py`) |
| 3 | Docs selector | WALKED TWO-PHASE — the assembled-site verifier (`verify_tree`) requires every advertised option to have an assembled bucket AND the `(latest)` label to equal the latest release tag; both are structurally unmeetable before the tag exists (constraint found by this walk). Phase 1 (this PR): selector stays at v0.1.0 (latest), consistent with the current tag set. Phase 2 (the tag commit, pushed with the tag in one action): v0.2.0 (latest) + v0.1.0 prior option. |
| 4 | Compatibility tagline | updated — SDK 0.2.0 against main project `>=0.1.0` (lock floor unchanged) |
| 5 | Standards badges | updated — otdp badge 0.2.1 → 0.2.2 (behind `standards-lock.json`); registry / execution / interface / plugin-ui / plugin-ui-preview correct-as-is |
| 6 | `great-docs.yml` versions | updated — v0.2.0 registered `latest: true` PRE-TAG; v0.1.0 retained as prior |
| 7 | Contributor window | NEW human contributor since v0.1.0: **Platima** — acknowledged in the CHANGELOG Contributors section and the release notes/tag record. Excluded: `benchweave-changelog[bot]` (bot), the owner (madeinoz67 / Stephen Eaton). |
| 8 | Gateway `uv.lock` SDK pin | recorded note, not a blocker: the gateway's pin and its `sdk_compatibility` mirror move together at its next pointer advance (the AR-6 pairing constraint). `standards-lock.json` `compatibility.sdk` stayed 0.1.0 at this release. **[Corrected 2026-09-24, gateway #187 fork ruling (a):** the field is the SDK version this lock state is *certified for* — the sync writer regenerates it (`_write_vendored` stamps pyproject's version), so a package release moves it via a standards sync, never "untouched by a package-version bump"; the provenance rationale recorded here was overruled and is the origin of the #187 drift. The gateway's ground-truth anchor now reds at pointer-advance time if the pairing is stale.**]** |

## Result record — v0.3.0 (2026-09-25)

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated → SDK 0.3.0 (OTDP 0.2.2 / adapter API 1.1 correct-as-is against `__init__.py`) |
| 2 | Website hero status | updated — SDK 0.2.0 → 0.3.0; OTDP 0.2.2 / adapter API 1.1 correct-as-is against `__init__.py` |
| 3 | Docs selector | WALKED TWO-PHASE (the v0.2.0 learning, unchanged) — phase 1 (this PR): no edit; the selector stays consistent with the current tag set (v0.2.0 latest). Phase 2 rides the tag commit, pushed with the tag in one action: v0.3.0 (latest) + v0.2.0 prior option in `great-docs.yml` `versions` and the website selector. |
| 4 | Compatibility tagline | updated — SDK 0.3.0 against main project `>=0.1.0` (lock floor unchanged) |
| 5 | Standards badges | updated — execution badge 0.1.0 → 0.2.0 (the #176 execution-corpus promotion landed in the lock via PR #53); otdp 0.2.2 / registry 0.1.1 / interface 0.1.0 / plugin-ui 0.2.0 / plugin-ui-preview 0.1.1 correct-as-is against `standards-lock.json` (all six enumerated against the lock) |
| 6 | `great-docs.yml` versions | PHASE-2 PLAN — no edit in this PR; the tag commit registers v0.3.0 `latest: true` with v0.2.0 demoted to prior, pushed with the tag in one action (the ordering constraint above). |
| 7 | Contributor window `v0.2.0..HEAD` | Platima again (1 commit — the #52 docs-guide follow-up), already acknowledged at v0.2.0; excluded: `benchweave-changelog[bot]` (bot) and the owner (madeinoz67 / Stephen Eaton). Acknowledgment this release: the rendered CHANGELOG 0.3.0 Contributors section (cliff.toml Contributors template; the publish.yml changelog job runs git-cliff-action with GITHUB_TOKEN so it renders @mentions) + the tag message at the owner's word. |
| 8 | Gateway `uv.lock` SDK pin | recorded note — the gateway pairing PR (`chore/sdk-030-pairing`) moves the manifest mirror `sdk_compatibility.sdk` → 0.3.0, regenerates the rendered matrix, and advances the submodule pointer to this release; the gateway's own `uv.lock` pin moves at its next gateway-side lock run. Unlike v0.2.0, `standards-lock.json` `compatibility.sdk` moves 0.2.0 → 0.3.0 in THIS release via the standards sync (the certified-version field, the #187 fork (a) ruling) — the #189 pairing shape. |

## Result record — v0.3.1 (2026-09-27)

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | correct-as-is — SDK 0.3.1 stamped with the #215 fold and independently re-proven at the fold tip |
| 2 | Website hero status | updated — SDK 0.3.0 → 0.3.1; OTDP 0.2.2 / adapter API 1.1 correct-as-is against the lock's active otdp row |
| 3 | Docs selector | WALKED TWO-PHASE — phase 1 (this commit): no edit; the selector stays consistent with the current tag set (v0.3.0 latest). Phase 2 rides the tag commit, pushed with the tag in one action: v0.3.1 (latest) + v0.3.0 prior option on both surfaces. |
| 4 | Compatibility tagline | updated — SDK 0.3.1 against main project `>=0.1.0` (lock floor unchanged; `compatibility.sdk` already 0.3.1 via the sync, the #189 pairing shape) |
| 5 | Standards badges | correct-as-is — all six match the lock's ACTIVE rows (otdp 0.2.2, registry 0.1.1, execution 0.2.0, interface 0.1.0, plugin-ui 0.2.0, plugin-ui-preview 0.1.1) |
| 6 | `great-docs.yml` versions | PHASE-2 PLAN — the tag commit registers v0.3.1 `latest: true` and demotes v0.3.0 (the ordering constraint: a tag missing itself fails the docs build) |
| 7 | Contributor window `v0.3.0..HEAD` | Platima — 1 commit in the window (already acknowledged at v0.2.0/v0.3.0, named again per that precedent); excluded: `benchweave-changelog[bot]` (bot) and the owner. Acknowledgment lands in the tag message (the permanent record) and the rendered release notes. |
| 8 | Gateway `uv.lock` SDK pin | recorded note — the gateway pairing landed with gateway #234 (`sdk_compatibility` mirror + submodule pointer at 0.3.1); the gateway's own `uv.lock` pin moves at its next gateway-side lock run. Gateway #237 (Windows separator/CRLF batch + `retention_policy` SyntaxWarning) rides this release train from the gateway side. |
| 9 | Served-set bump class | correct-as-is — PATCH for a carried-set growth inside unchanged declared ranges (6 → 11 carried rows); `sdk_bump_class_invalid:` enforces and is mutation-pinned; the gateway check lanes are green at the pairing |

## Result record — v0.4.1 (2026-10-02)

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated → SDK 0.4.1 (OTDP 0.2.2 / adapter API 1.1 correct-as-is) |
| 2 | Website hero status | updated → SDK 0.3.1 → 0.4.1; OTDP 0.2.2 / adapter API 1.1 correct-as-is |
| 3 | Docs selector | WALKED TWO-PHASE — phase 2 rides the tag commit (v0.4.1 latest + v0.3.1 prior) |
| 4 | Compatibility tagline | updated → SDK 0.4.1 against main project >=0.1.0 (floor unchanged) |
| 5 | Standards badges | updated → registry 0.1.1→0.1.2, plugin-ui 0.2.0→0.3.0, plugin-ui-preview 0.1.1→0.2.0; otdp 0.2.2 / execution 0.2.0 / interface 0.1.0 correct-as-is |
| 6 | `great-docs.yml` versions | PHASE-2 — tag commit registers v0.4.1 latest:true, demotes v0.3.1 |
| 7 | Contributor window `v0.3.1..HEAD` | empty — owner + dependabot[bot] + benchweave-changelog[bot] only; recorded result |
| 8 | Gateway `uv.lock` SDK pin | recorded note — moves at the gateway's next lock run |
| 9 | Served-set bump class | MINOR — digital_lanes plugin-ui 0.2.0→0.3.0 (declared-range change) + registry 0.1.2 active-row motion; `sdk_bump_class_invalid:` passed |

## Result record — v0.6.0 (2026-10-03)

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated → SDK 0.6.0 — the stamped number was 0.5.0, the dev-window number that never shipped as a tag; OTDP 0.2.2 / adapter API 1.1 correct-as-is against the lock-derived constants |
| 2 | Website hero status | updated — SDK 0.5.0 → 0.6.0 (the same never-shipped dev-window number); OTDP 0.2.2 / adapter API 1.1 correct-as-is against the lock's active otdp row and the vendored descriptor const (`__init__.py` lazy derivation) |
| 3 | Docs selector | WALKED TWO-PHASE — phase 1 (this branch): no edit; the selector stays consistent with the current tag set (v0.4.1 latest). Phase 2 rides the tag commit, pushed with the tag in one action: v0.6.0 (latest) + v0.4.1 prior option on both surfaces. |
| 4 | Compatibility tagline | updated — SDK 0.4.1 → 0.6.0 against main project `>=0.1.0` (lock floor unchanged; `compatibility.sdk` already 0.6.0 via the #359 re-anchor, the #189 pairing shape) |
| 5 | Standards badges | correct-as-is — all six match the lock's ACTIVE rows (otdp 0.2.2, registry 0.1.2, execution 0.2.0, interface 0.1.0, plugin-ui 0.3.0, plugin-ui-preview 0.2.0) |
| 6 | `great-docs.yml` versions | PHASE-2 PLAN — the tag commit registers v0.6.0 `latest: true` and demotes v0.4.1 (the ordering constraint: a tag missing itself fails the docs build) |
| 7 | Contributor window `v0.4.1..HEAD` | empty — every author in the window is the owner (`sort -u` over `%an <%ae>` resolves to one entry); not even the changelog bot (the v0.4.1 changelog commit 714eab4 is owner-authored, not the app's). Recorded result. |
| 8 | Gateway `uv.lock` SDK pin | recorded note — the gateway's pin and submodule pointer sit at the 0.4.1-era tree until its next pointer advance (its `packages/sdk/README.md` still stamps SDK 0.4.1); they move together per the AR-6 pairing |
| 9 | Served-set bump class | n-a — no served-set motion in the window: carried rows (12), active rows and declared ranges are identical to v0.4.1's lock; only `compatibility.sdk` moved (the certified-version field). Neither stale pattern of this row can fire; the bump class is unconstrained by the sync. |

## Result record — v0.9.0 (2026-10-07)

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated → SDK 0.9.0 by release-cut (occurrence-validated) |
| 1b | User-guide "current SDK" sentence | walk confirms — n-a or updated; the wheel filename is a glob since #102 |
| 2 | Website hero status | updated — SDK 0.9.0 by release-cut (occurrence-validated); OTDP / adapter-API stamps the walk confirms against the lock's active rows |
| 3 | Docs selector | PHASE-2 — patch staged at `.release/phase2-v0.9.0.patch`; the tag commit applies it (registration precedes the tag) |
| 4 | Compatibility tagline | updated — SDK 0.9.0 against the main-repository floor by release-cut (occurrence-validated) |
| 5 | Standards badges | walk confirms — all seven match the lock's ACTIVE rows |
| 6 | great-docs.yml versions | PHASE-2 — the tag commit applies the staged patch (the ordering constraint) |
| 7 | Contributor window `v0.8.0..HEAD` | 71 commits in the window — human authors other than the operator/bots: none; the walk acknowledges new human contributors and records an empty window as a result |
| 8 | Gateway uv.lock SDK pin | recorded note — moves at the gateway's next lock run / pointer advance |
| 9 | Served-set bump class | n-a — no served-set motion in the window: standards-lock.json is identical to v0.8.0's apart from compatibility.sdk (the certified-version field) |

## Result record — v0.10.0 (2026-10-12)

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated → SDK 0.10.0 by release-cut (occurrence-validated) |
| 1b | User-guide "current SDK" sentence | updated BY THE WALK — the guide still stamped 0.7.1 (three releases stale, this row's own documented lag pattern); corrected to 0.10.0 in the release commit |
| 2 | Website hero status | confirmed — SDK 0.10.0 by release-cut (occurrence-validated); OTDP 0.2.2 / adapter API 1.1 confirmed against the lock's active otdp row |
| 3 | Docs selector | PHASE-2 — patch staged at `.release/phase2-v0.10.0.patch` (1018 B, verified present); the tag commit applies it (registration precedes the tag) |
| 4 | Compatibility tagline | confirmed — SDK 0.10.0 against the main-repository floor `>=0.1.0`; the lock anchor moved `compatibility.sdk` → 0.10.0 (the lock-anchor ritual, the #189 pairing shape) |
| 5 | Standards badges | confirmed correct-as-is — all six match the lock's ACTIVE rows (otdp 0.2.2, registry 0.1.2, execution 0.2.0, interface 0.1.0, plugin-ui 0.3.0, plugin-ui-preview 0.2.0); zero committed lock motion in the window |
| 6 | great-docs.yml versions | PHASE-2 — the tag commit applies the staged patch (the ordering constraint) |
| 7 | Contributor window `v0.9.0..HEAD` | empty — the 80-commit window resolves to the owner (madeinoz67 / Stephen Eaton, one human) and dependabot[bot]; no new human contributors; recorded result |
| 8 | Gateway uv.lock SDK pin | recorded note — moves at the gateway's next lock run / pointer advance |
| 9 | Served-set bump class | n-a — `git diff v0.9.0..HEAD -- standards-lock.json` is empty (zero committed lock motion); only the staged `compatibility.sdk` anchor moves with this release |

Test surfaces: T1/T2 confirmed by the byte-parity suite at the staged tree (34/0/0, junitxml); T3's docstring already names `make release-cut` as the procedure (no motion); T4 inert by design.

## Result record — v0.11.1 (2026-10-13)

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated → SDK 0.11.1 by release-cut (occurrence-validated) |
| 1b | User-guide "current SDK" sentence | walk confirms — n-a or updated; the wheel filename is a glob since #102 |
| 2 | Website hero status | updated — SDK 0.11.1 by release-cut (occurrence-validated); OTDP / adapter-API stamps the walk confirms against the lock's active rows |
| 3 | Docs selector | PHASE-2 — patch staged at `.release/phase2-v0.11.1.patch`; the tag commit applies it (registration precedes the tag) |
| 4 | Compatibility tagline | updated — SDK 0.11.1 against the main-repository floor by release-cut (occurrence-validated) |
| 5 | Standards badges | walk confirms — all seven match the lock's ACTIVE rows |
| 6 | great-docs.yml versions | PHASE-2 — the tag commit applies the staged patch (the ordering constraint) |
| 7 | Contributor window `v0.11.0..HEAD` | 5 commits in the window — human authors other than the operator/bots: none; the walk acknowledges new human contributors and records an empty window as a result |
| 8 | Gateway uv.lock SDK pin | recorded note — moves at the gateway's next lock run / pointer advance |
| 9 | Served-set bump class | SERVED-SET MOTION in the window — the class is asserted by the sync machinery (sdk_bump_class_invalid:); the walk records it; release-cut refuses to guess a class (D7) |

## Result record — v0.13.0 (2026-10-15)

The bump rode the mechanically-coupled sync PR (#152 — release-cut's assert_increment refuses a same-version re-cut, so the full transaction never ran pre-bump); this walk performed the stamp substitutions the transaction would have made, occurrence-by-occurrence. Walk finding, recorded: no v0.12.0 result block exists in this matrix — the 0.12.0 registration commit (b7f8881) touched .release/plan.json only; noted, not backfilled (a record for a walk that did not happen would be fabricated).

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated BY THE WALK → SDK 0.13.0 (was 0.12.0) |
| 1b | User-guide "current SDK" sentence | updated BY THE WALK → 0.13.0 / OTDP 0.2.3 / registry 0.1.3 — the row's own lag pattern again: the sentence sat three releases stale (0.10.0 / 0.2.2 / 0.1.2), last corrected at v0.10.0 |
| 2 | Website hero status | updated BY THE WALK → SDK 0.13.0 · OTDP 0.2.3 · adapter API 1.1 (confirmed against the lock's active otdp row) |
| 3 | Docs selector | PHASE-2 — patch staged at `.release/phase2-v0.13.0.patch` (both selector surfaces: latest option + demoted prior); the tag commit applies it (registration precedes the tag) |
| 4 | Compatibility tagline | updated BY THE WALK → SDK 0.13.0 against the main-repository floor `>=0.1.0` (lock compatibility.main_project unchanged) |
| 5 | Standards badges | updated BY THE WALK — plugin-ui 0.3.0 → 0.3.1 (stale since the 0.12.0 era), plugin-ui-class-reference 0.1.0 ADDED (seventh family); interface 0.1.0 and plugin-ui-preview 0.2.0 correct-as-is; all seven now match the lock's ACTIVE rows |
| 6 | great-docs.yml versions | PHASE-2 — the tag commit applies the staged patch (the ordering constraint) |
| 7 | Contributor window `v0.12.0..HEAD` | 3 commits in the window — human authors other than the operator/bots: none (madeinoz67 / Stephen Eaton + benchweave-changelog[bot]); empty window recorded as a result |
| 8 | Gateway uv.lock SDK pin | recorded note — moves at the gateway pointer-pairing landing (this train's Landing 1/3 event) |
| 9 | Served-set bump class | SERVED-SET MOTION — MINOR: plugin-ui-class-reference 0.1.0 added (pure ADD, 15th lock row, no refusals; asserted by the sync machinery's bump-class judgment in PR #152) |

Test surfaces: T1/T2 — the fixtures were regenerated in-arc by the sync PR (release_cut.regenerate_fixtures at 0.13.0); T3 docstring names `make release-cut` (no motion); T4 inert by design.

## Result record — v0.14.0 (2026-10-15)

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated → SDK 0.14.0 by release-cut (occurrence-validated) |
| 1b | User-guide "current SDK" sentence | walk confirms — n-a or updated; the wheel filename is a glob since #102 |
| 2 | Website hero status | updated — SDK 0.14.0 by release-cut (occurrence-validated); OTDP / adapter-API stamps the walk confirms against the lock's active rows |
| 3 | Docs selector | PHASE-2 — patch staged at `.release/phase2-v0.14.0.patch`; the tag commit applies it (registration precedes the tag) |
| 4 | Compatibility tagline | updated — SDK 0.14.0 against the main-repository floor by release-cut (occurrence-validated) |
| 5 | Standards badges | walk confirms — all seven match the lock's ACTIVE rows |
| 6 | great-docs.yml versions | PHASE-2 — the tag commit applies the staged patch (the ordering constraint) |
| 7 | Contributor window `v0.13.0..HEAD` | 36 commits in the window — human authors other than the operator/bots: none; the walk acknowledges new human contributors and records an empty window as a result |
| 8 | Gateway uv.lock SDK pin | recorded note — moves at the gateway's next lock run / pointer advance |
| 9 | Served-set bump class | n-a — no served-set motion in the window: standards-lock.json is identical to v0.13.0's apart from compatibility.sdk (the certified-version field) |

## Result record — v0.15.0 (2026-10-16)

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated → SDK 0.15.0 by release-cut (occurrence-validated) |
| 1b | User-guide "current SDK" sentence | walk confirms — n-a or updated; the wheel filename is a glob since #102 |
| 2 | Website hero status | updated — SDK 0.15.0 by release-cut (occurrence-validated); OTDP / adapter-API stamps the walk confirms against the lock's active rows |
| 3 | Docs selector | PHASE-2 — patch staged at `.release/phase2-v0.15.0.patch`; the tag commit applies it (registration precedes the tag) |
| 4 | Compatibility tagline | updated — SDK 0.15.0 against the main-repository floor by release-cut (occurrence-validated) |
| 5 | Standards badges | walk confirms — enumerate all six against the lock's ACTIVE rows |
| 6 | great-docs.yml versions | PHASE-2 — the tag commit applies the staged patch (the ordering constraint) |
| 7 | Contributor window `v0.14.0..HEAD` | 14 commits in the window — human authors other than the operator/bots: none; the walk acknowledges new human contributors and records an empty window as a result |
| 8 | Gateway uv.lock SDK pin | recorded note — moves at the gateway's next lock run / pointer advance |
| 9 | Served-set bump class | SERVED-SET MOTION in the window — the class is asserted by the sync machinery (sdk_bump_class_invalid:); the walk records it; release-cut refuses to guess a class (D7) |

## Result record — v0.16.0 (2026-10-19)

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated → SDK 0.16.0 by release-cut (occurrence-validated) |
| 1b | User-guide "current SDK" sentence | walk confirms — n-a or updated; the wheel filename is a glob since #102 |
| 2 | Website hero status | updated — SDK 0.16.0 by release-cut (occurrence-validated); OTDP / adapter-API stamps the walk confirms against the lock's active rows |
| 3 | Docs selector | PHASE-2 — patch staged at `.release/phase2-v0.16.0.patch`; the tag commit applies it (registration precedes the tag) |
| 4 | Compatibility tagline | updated — SDK 0.16.0 against the main-repository floor by release-cut (occurrence-validated) |
| 5 | Standards badges | walk confirms — enumerate all six against the lock's ACTIVE rows |
| 5-corr | Standards badges | CORRECTION (2026-10-19, append-only — the row above is untouched; issue #412): at the pin this walk certified (`9e0449e`) four of the seven badges were stale against the lock's ACTIVE rows — registry 0.1.2 vs 0.1.3, interface 0.1.0 vs 0.1.1, plugin-ui 0.3.1 vs 0.4.0, plugin-ui-class-reference 0.1.0 vs 0.2.0 — and "six" understates the set: seven families since v0.13.0. The #412 R1 riders brought the badge row to the actives; the prose gate (`scripts/count_version_literals.py`) pins the surface's site counts thereafter. |
| 6 | great-docs.yml versions | PHASE-2 — the tag commit applies the staged patch (the ordering constraint) |
| 7 | Contributor window `v0.15.0..HEAD` | 50 commits in the window — human authors other than the operator/bots: none; the walk acknowledges new human contributors and records an empty window as a result |
| 8 | Gateway uv.lock SDK pin | recorded note — moves at the gateway's next lock run / pointer advance |
| 9 | Served-set bump class | SERVED-SET MOTION in the window — the class is asserted by the sync machinery (sdk_bump_class_invalid:); the walk records it; release-cut refuses to guess a class (D7) |

## Result record — v0.17.0 (2026-10-21)

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated → SDK 0.17.0 by release-cut (occurrence-validated) |
| 1b | User-guide "current SDK" sentence | walk confirms — n-a or updated; the wheel filename is a glob since #102 |
| 2 | Website hero status | updated — SDK 0.17.0 by release-cut (occurrence-validated); OTDP / adapter-API stamps the walk confirms against the lock's active rows |
| 3 | Docs selector | PHASE-2 — patch staged at `.release/phase2-v0.17.0.patch`; the tag commit applies it (registration precedes the tag) |
| 4 | Compatibility tagline | updated — SDK 0.17.0 against the main-repository floor by release-cut (occurrence-validated) |
| 5 | Standards badges | walk confirms — enumerate all six against the lock's ACTIVE rows |
| 6 | great-docs.yml versions | PHASE-2 — the tag commit applies the staged patch (the ordering constraint) |
| 7 | Contributor window `v0.16.0..HEAD` | 30 commits in the window — human authors other than the operator/bots: none; the walk acknowledges new human contributors and records an empty window as a result |
| 8 | Gateway uv.lock SDK pin | recorded note — moves at the gateway's next lock run / pointer advance |
| 9 | Served-set bump class | SERVED-SET MOTION in the window — the class is asserted by the sync machinery (sdk_bump_class_invalid:); the walk records it; release-cut refuses to guess a class (D7) |

## Result record — v0.18.0 (2026-10-21)

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated → SDK 0.18.0 by release-cut (occurrence-validated) |
| 1b | User-guide "current SDK" sentence | walk confirms — n-a or updated; the wheel filename is a glob since #102 |
| 2 | Website hero status | updated — SDK 0.18.0 by release-cut (occurrence-validated); OTDP / adapter-API stamps the walk confirms against the lock's active rows |
| 3 | Docs selector | PHASE-2 — patch staged at `.release/phase2-v0.18.0.patch`; the tag commit applies it (registration precedes the tag) |
| 4 | Compatibility tagline | updated — SDK 0.18.0 against the main-repository floor by release-cut (occurrence-validated) |
| 5 | Standards badges | walk confirms — enumerate all six against the lock's ACTIVE rows |
| 6 | great-docs.yml versions | PHASE-2 — the tag commit applies the staged patch (the ordering constraint) |
| 7 | Contributor window `v0.17.0..HEAD` | 3 commits in the window — human authors other than the operator/bots: none; the walk acknowledges new human contributors and records an empty window as a result |
| 8 | Gateway uv.lock SDK pin | recorded note — moves at the gateway's next lock run / pointer advance |
| 9 | Served-set bump class | n-a — no served-set motion in the window: standards-lock.json is identical to v0.17.0's apart from compatibility.sdk (the certified-version field) |

## Result record — v0.19.0 (2026-10-22)

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated → SDK 0.19.0 by release-cut (occurrence-validated) |
| 1b | User-guide "current SDK" sentence | walk confirms — n-a or updated; the wheel filename is a glob since #102 |
| 2 | Website hero status | updated — SDK 0.19.0 by release-cut (occurrence-validated); OTDP / adapter-API stamps the walk confirms against the lock's active rows |
| 3 | Docs selector | PHASE-2 — patch staged at `.release/phase2-v0.19.0.patch`; the tag commit applies it (registration precedes the tag; the same patch moves the zero-literal gate battery's three anchors, #524) |
| 4 | Compatibility tagline | updated — SDK 0.19.0 against the main-repository floor by release-cut (occurrence-validated) |
| 5 | Standards badges | walk confirms — enumerate all six against the lock's ACTIVE rows |
| 6 | great-docs.yml versions | PHASE-2 — the tag commit applies the staged patch (the ordering constraint) |
| 7 | Contributor window `v0.18.0..HEAD` | 18 commits in the window — human authors other than the operator/bots: none; the walk acknowledges new human contributors and records an empty window as a result |
| 8 | Gateway uv.lock SDK pin | recorded note — moves at the gateway's next lock run / pointer advance |
| 9 | Served-set bump class | SERVED-SET MOTION in the window — the class is asserted by the sync machinery (sdk_bump_class_invalid:); the walk records it; release-cut refuses to guess a class (D7) |

## Result record — v0.22.0 (2026-10-26)

The bump rode the standards-sync PR (#208) that vendored `plugin-ui-class-reference`
0.5.0; release-cut's `assert_increment` refuses a same-version re-cut, so the cut
transaction could not run end to end (the v0.13.0 precedent). The walk performed
the substitution surfaces occurrence-by-occurrence, regenerated the fixtures through
`release_cut.regenerate_fixtures`, and staged the phase-2 patch with
`release_cut.py --phase2-only`; `release-cut --verify` was green on the pre-tag tree.
The walk found the bump itself had left three version-bearing prose surfaces stale
(README, website hero, website tagline) plus two standards stamps (website OTDP, the
class-reference badge) and the guide's OTDP sentence — all corrected here against
their machine sources.

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated BY THE WALK → SDK 0.22.0 (pyproject was already 0.22.0 from #208; the README still stamped 0.21.0). OTDP 0.2.4 / adapter API 1.1 correct-as-is against the lock's active otdp row and the derived constant |
| 1b | User-guide "current SDK" sentence | updated BY THE WALK → OTDP 0.2.4 (was 0.2.3, this row's own documented lag pattern). The sentence carries no SDK number (versionless by the R1 rider; the wheel filename is a glob since #102) |
| 2 | Website hero status | updated BY THE WALK — two stale stamps: SDK 0.21.0 → 0.22.0 and OTDP 0.2.3 → 0.2.4. Adapter API 1.1 confirmed against `__init__.py`'s derived constant (`ADAPTER_API_VERSION`, read from the 0.2.4 descriptor) |
| 3 | Docs selector | PHASE-2 — patch staged at `.release/phase2-v0.22.0.patch` (both selector surfaces: latest option + demoted prior); the tag commit applies it (registration precedes the tag; the same patch moves the zero-literal gate battery's anchors, #524). `release-cut --verify` confirmed the patch applies and is byte-equal to `build_phase2`'s recomputation |
| 4 | Compatibility tagline | updated BY THE WALK → SDK 0.22.0 against the main-repository floor `>=0.1.0` (unchanged). `standards-lock.json` `compatibility.sdk` already 0.22.0 from the sync (the #189 pairing shape) |
| 5 | Standards badges | updated BY THE WALK — two stale of seven: otdp 0.2.3 → 0.2.4 and plugin-ui-class-reference 0.2.0 → 0.5.0 (the 0.5.0 vendoring in #208; the badge had been stale across two releases). registry 0.1.3, execution 0.2.0, interface 0.1.1, plugin-ui 0.4.0, plugin-ui-preview 0.2.0 correct-as-is. All seven enumerated against the lock's ACTIVE rows |
| 6 | `great-docs.yml` versions | PHASE-2 — the tag commit applies the staged patch (the ordering constraint: a tag missing itself fails the docs build) |
| 7 | Contributor window `v0.21.0..HEAD` | 55 commits in the window — human authors other than the operator/bots: none (owner + `dependabot[bot]` + `benchweave-changelog[bot]` only); empty window recorded as a result |
| 8 | Gateway uv.lock SDK pin | recorded note — moves at the gateway's next lock run / the pointer PR that pairs this release |
| 9 | Served-set bump class | SERVED-SET MOTION in the window — `plugin-ui-class-reference` 0.4.0 → 0.5.0 (a new active row and the new `composed-member-declaration.schema.json`); MINOR, matching this release's number. The class was asserted by the sync machinery (`sdk_bump_class_invalid:`) in #208; the walk records it |

Test surfaces: T1/T2 regenerated through `release_cut.regenerate_fixtures` at the
staged tree — byte-identical to the committed fixtures (`git status` empty for
`tests/fixtures/scaffold_expected`), which already carried 0.22.0 from #208. T3's
docstring already names `make release-cut` as the procedure (no motion). T4 inert
by design.

## Result record — v0.21.0 (2026-10-24)

| # | Surface | Result |
|---|---------|--------|
| 1 | README stamp | updated → SDK 0.21.0 by release-cut (occurrence-validated) |
| 1b | User-guide "current SDK" sentence | walk confirms — n-a or updated; the wheel filename is a glob since #102 |
| 2 | Website hero status | updated — SDK 0.21.0 by release-cut (occurrence-validated); OTDP / adapter-API stamps the walk confirms against the lock's active rows |
| 3 | Docs selector | PHASE-2 — patch staged at `.release/phase2-v0.21.0.patch`; the tag commit applies it (registration precedes the tag; the same patch moves the zero-literal gate battery's three anchors, #524) |
| 4 | Compatibility tagline | updated — SDK 0.21.0 against the main-repository floor by release-cut (occurrence-validated) |
| 5 | Standards badges | walk confirms — enumerate all six against the lock's ACTIVE rows |
| 6 | great-docs.yml versions | PHASE-2 — the tag commit applies the staged patch (the ordering constraint) |
| 7 | Contributor window `v0.19.0..HEAD` | 25 commits in the window — human authors other than the operator/bots: none; the walk acknowledges new human contributors and records an empty window as a result |
| 8 | Gateway uv.lock SDK pin | recorded note — moves at the gateway's next lock run / pointer advance |
| 9 | Served-set bump class | SERVED-SET MOTION in the window — the class is asserted by the sync machinery (sdk_bump_class_invalid:); the walk records it; release-cut refuses to guess a class (D7) |
