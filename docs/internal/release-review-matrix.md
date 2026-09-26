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
| 2 | Website hero status line (`website/index.html`, hero badges) | `pyproject.toml` + `OTDP_VERSION` / `ADAPTER_API_VERSION` in `src/benchweave_sdk/__init__.py` | previous SDK number, OTDP number behind the constant |
| 3 | Website docs-version selector (options + `(latest)` label) — TWO surfaces: the `website/index.html` static selector AND the `great-docs.yml` `versions` list (retro 2026-09-25 R3: a phase-2 that edits only the yml fails CI Docs — the verifier reads the static selector's label) | `great-docs.yml` `versions` list + `website/index.html` selector options + git tags | previous `(latest)` label on either surface, missing prior-release option |
| 4 | Website compatibility tagline | `standards-lock.json` `compatibility.main_project` floor + the release's tested pair | previous SDK number against the gateway floor |
| 5 | Website standards badges (interface / plugin-ui / plugin-ui-preview) | `standards-lock.json` `standards[].version` per id | badge behind the vendored contract version |
| 6 | `great-docs.yml` `versions` list | git tags | new tag absent, previous release still `latest: true` |
| 7 | Contributor window | `git log <prev-tag>..HEAD --format='%an'` minus bots and the owner | unacknowledged new human contributors; empty window = recorded result |
| 8 | Gateway `uv.lock` SDK pin (cross-repo) | the released SDK version | pin behind the release; moves on the gateway's next gateway-side lock run — a note, not a blocker |
| 9 | Served-set bump class (issue #203 slice 1, owner Q8) | `standards-lock.json` rows + `dependency_policy` mirror vs the PREVIOUS lock | one SDK version covering two served sets: a carried-set change on an unchanged range that is not a PATCH-class bump, or a declared-range change that is not MINOR at least — the sync itself refuses `sdk_bump_class_invalid:`, and the gateway's `benchweave.standards check` refuses the lock↔manifest disagreement (`served_set_drift:` / `policy_mirror_drift:`) |

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
