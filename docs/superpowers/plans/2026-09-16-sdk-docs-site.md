# BenchWeave SDK Docs Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a versioned Great Docs site for `benchweave-sdk` on GitHub Pages — versions keyed to release tags, `dev` tracking main, full standard content set, CI-gated builds.

**Architecture:** Great Docs CLI (Quarto-based, already installed machine-wide) generates the site from `great-docs.yml` in the SDK submodule root. Its native multi-version support builds one docs version per git tag plus `dev`; every main-push deploy rebuilds all versions, so old versions never disappear. A tool-generated GitHub Actions workflow builds on PR/push and deploys to Pages on main push.

**Tech Stack:** great-docs CLI (`~/.local/bin/great-docs`), Quarto 1.9.37, uv, GitHub Actions + Pages.

**Spec:** `docs/superpowers/specs/2026-09-16-sdk-docs-site-design.md` (approved 2026-09-16).

## Global Constraints

- ALL work in the SDK submodule checkout: `/Users/seaton/Documents/src/BenchWeave/packages/sdk`. Every command below runs from there unless stated.
- EVERY `uv` invocation sets `UV_PROJECT_ENVIRONMENT=venv` (non-dot venv repo rule; without it uv silently creates a stray `.venv/`).
- Gates must pass before every commit, with `set -o pipefail`: `uv run ruff check .` → 0 findings; `uv run mypy` → clean (bare command, config-driven); `uv run pytest -q` → 0 failed.
- Gortex-first on indexed source: read `src/**` via `mcp__gortex__read` (repo-prefixed paths), mutate via `mcp__gortex__edit` when practical; subagent dispatches must carry the Gortex mandate in the prompt.
- Never commit tool-generated artifacts: the `great-docs/` build dir, freeze caches, `wiki/`, `docs/architecture/`, `CHANGELOG_AUTO.md` (last three already guarded).
- Conventional commits (`feat:`, `docs:`, `chore:`, `ci:`). One logical slice per commit.
- Branch `feat/docs-site` off `origin/main`; no direct commits to main.
- Two-repo order: SDK submodule commits push to `madeinoz67/benchweave-sdk` FIRST; only then does the main repo advance its submodule pointer.
- `docs/superpowers/` is gitignored — spec/plan stay local-untracked until close-out force-add.
- Version semantics (spec): landing = latest stable tag; `dev` labeled unreleased; tags are the citable surface.
- No tests are written for pure docs/config changes — the verification cycle is the build gate + gates above. Any `src/**` change (docstring pass) keeps the existing suite green.

---

### Task 1: Working branch

**Files:** none (git only).

- [ ] **Step 1: Base the branch on the remote tip**

```bash
cd /Users/seaton/Documents/src/BenchWeave/packages/sdk
git fetch origin
git checkout -b feat/docs-site origin/main
```

Expected: clean checkout, branch created. If `git status` shows dirt, STOP and report — do not stash-and-continue (submodule reset history: unpushed source fixes have been lost that way).

- [ ] **Step 2: Confirm baseline gates**

```bash
set -o pipefail
UV_PROJECT_ENVIRONMENT=venv uv run ruff check . && UV_PROJECT_ENVIRONMENT=venv uv run mypy && UV_PROJECT_ENVIRONMENT=venv uv run --extra test pytest -q
```

Expected: ruff 0 findings, mypy clean, pytest 0 failed. If the baseline is red, STOP and report — docs work must not absorb a pre-existing failure.

---

### Task 2: Init, config, ignore guard, first build

**Files:**
- Create: `great-docs.yml` (tool-generated, then edited)
- Modify: `.gitignore` (tool-appended `great-docs/` guard — verify, don't hand-write)

**Interfaces:**
- Produces: a `great-docs.yml` whose build yields `great-docs/_site/` with multi-version + dev configured (Tasks 3–6, 9 depend on this).

- [ ] **Step 1: Run init**

```bash
great-docs init
```

Expected: creates `great-docs.yml` with discovered `benchweave_sdk` exports, appends the build-dir guard to `.gitignore`, detects docstring style. Refuses only if `great-docs.yml` already exists (it must not — fresh start).

- [ ] **Step 2: Verify the ignore guard is in place BEFORE anything builds**

```bash
git check-ignore -v great-docs/ && grep -n "great-docs" .gitignore
```

Expected: a match. If `init` did not add it, append `great-docs/` to `.gitignore` by hand in this step (guard-first rule: the guard precedes any wiring commit).

- [ ] **Step 3: Align the config**

Open `great-docs.yml` (the generated file documents every key with comments — read them, then set). Required end state:

- Site identity: title **BenchWeave SDK**, repository `madeinoz67/benchweave-sdk`.
- Docs dir: `docs/` (where `plugin-sdk.md` and `assets/benchweave-sdk-banner.png` live).
- Banner/logo asset: `docs/assets/benchweave-sdk-banner.png`.
- Multi-version documentation: **enabled**, versions from tags, `dev` bucket for main.
- Landing/default version: latest stable tag (NOT dev).
- Changelog page sourced from `CHANGELOG.md`.
- CLI reference for the `benchweave-sdk` entry point.
- `llms.txt` generation: on.

- [ ] **Step 4: Preview API discovery coverage**

```bash
great-docs scan -v
```

Expected: lists the public modules (`cli`, `scaffold`, `fixtures`, `validation`, `conformance`, `packaging`, `presentation`, `preview_server`, `preview_tui`, `standards_sync`, `testing`, …) with exports. Note any module with zero discovered exports — that list feeds Task 4.

- [ ] **Step 5: First build**

```bash
great-docs build
```

Expected: exit 0, `great-docs/_site/` created. Version list should include `v0.0.1`, `v0.0.2` and `dev` (if versions are missing, the multi-version keys in Step 3 are wrong — fix before proceeding).

- [ ] **Step 6: Gates + commit**

```bash
set -o pipefail
UV_PROJECT_ENVIRONMENT=venv uv run ruff check . && UV_PROJECT_ENVIRONMENT=venv uv run mypy && UV_PROJECT_ENVIRONMENT=venv uv run --extra test pytest -q
git status --porcelain   # MUST NOT list great-docs/ or _site artifacts
git add great-docs.yml .gitignore
git commit -m "feat(docs): great-docs site config with tag-keyed multi-version + dev"
```

Expected: clean status apart from staged files; commit lands.

---

### Task 3: Landing + user guide content

**Files:**
- Create: `docs/index.qmd` (or the landing page the config expects — follow what `great-docs.yml` generated/`init` scaffolded)
- Create: `docs/guide/plugin-sdk.qmd` — migration of `docs/plugin-sdk.md`
- Modify: `docs/plugin-sdk.md` — remains the source of truth until migration verified, then deleted in this task's final step

**Interfaces:**
- Consumes: Task 2 config (docs dir, navigation).
- Produces: rendered landing + guide sections in the built site (Tasks 6, 9 verify).

- [ ] **Step 1: Build the landing page from README content**

Create the landing page as Quarto markdown. Frontmatter + intro from `README.md`: what the SDK is (offline authoring + conformance tools for BenchWeave OTDP device plugins), install (`pip install benchweave-sdk` / uv), the CLI one-liner, banner image, links into the guide, API reference, CLI reference, changelog. Keep it a landing — summary and doors, not the full README dump.

- [ ] **Step 2: Migrate the plugin guide**

Move `docs/plugin-sdk.md` content into the guide page structure (frontmatter, section headings, cross-references to the API reference where the guide currently names symbols inline). Fix any absolute links that pointed outside the repo — they become plain external links. Guide prose stays the author's content: restructure, do not rewrite.

- [ ] **Step 3: Rebuild + navigate**

```bash
great-docs build
```

Expected: exit 0; landing and guide appear in nav for every version.

- [ ] **Step 4: Remove the superseded source**

```bash
git rm docs/plugin-sdk.md
```

Only after Step 3 confirms the guide renders. If other files reference `docs/plugin-sdk.md`, update them (`grep -rn "plugin-sdk.md" --include="*.md" --include="*.yml" --include="*.qmd" .` first).

- [ ] **Step 5: Gates + commit**

```bash
set -o pipefail
UV_PROJECT_ENVIRONMENT=venv uv run ruff check . && UV_PROJECT_ENVIRONMENT=venv uv run mypy && UV_PROJECT_ENVIRONMENT=venv uv run --extra test pytest -q
git add docs/ great-docs.yml
git commit -m "docs: landing page + plugin authoring guide migrated into the site"
```

---

### Task 4: API/CLI reference quality pass

**Files:**
- Modify: `src/benchweave_sdk/*.py` — docstrings ONLY where `great-docs scan` found exported symbols with missing/empty docstrings

**Interfaces:**
- Consumes: Task 2 Step 4's thin-symbol list.
- Produces: reference pages that render with real docstrings.

- [ ] **Step 1: Enumerate thin symbols**

```bash
great-docs scan -v
```

List every exported class/function whose docstring is absent or one-liner-empty. That list is the task scope — nothing else in `src/` changes.

- [ ] **Step 2: Write the docstrings**

Style: whatever `init` detected (numpy/google — check `great-docs.yml`). Each docstring: one-line summary, params/returns where non-trivial, an example for the top-usage symbols (`scaffold`, `fixtures`, `validation` at minimum). Gortex-first: read each target via `mcp__gortex__read` before editing; edits are docstring-only — no signature or behavior changes.

- [ ] **Step 3: Rebuild + verify reference populated**

```bash
great-docs build
```

Expected: exit 0; API reference pages show the new docstrings (spot-check via `_site` HTML or `great-docs preview`).

- [ ] **Step 4: Full gates (src changed — all of them) + commit**

```bash
set -o pipefail
UV_PROJECT_ENVIRONMENT=venv uv run ruff check . && UV_PROJECT_ENVIRONMENT=venv uv run mypy && UV_PROJECT_ENVIRONMENT=venv uv run --extra test pytest -q
git add src/
git commit -m "docs(api): docstrings for exported SDK symbols surfaced by the reference build"
```

---

### Task 5: Pages CI workflow

**Files:**
- Create: `.github/workflows/docs.yml` (tool-generated, then reviewed/adjusted)

**Interfaces:**
- Consumes: Task 2 config.
- Produces: CI builds docs on PR + push, deploys to Pages on main push (Tasks 7, 9 depend).

- [ ] **Step 1: Generate the workflow**

```bash
great-docs setup-github-pages --package-manager uv
```

Expected: writes a workflow file (Python auto-detected 3.13 from `requires-python`; uv detected from `uv.lock`). Note: CI runners don't need `UV_PROJECT_ENVIRONMENT` — the non-dot venv is a local-machine convention; leave the generated install steps as-is unless they fail.

- [ ] **Step 2: Review the generated file against these acceptance criteria**

Read `.github/workflows/docs.yml` in full. It MUST: build docs on pull_request and push(main); deploy to Pages only on push(main); use `actions/configure-pages` + Quarto's official action (or the tool's documented equivalent); run `great-docs build` such that a docs failure fails the job (no `continue-on-error` on the build step); deploy via `actions/deploy-pages`. Adjust minimally if any criterion misses. Add `permissions: contents: read, pages: write, id-token: write` at workflow level if absent (Pages deploy requires it).

- [ ] **Step 3: YAML sanity**

```bash
UV_PROJECT_ENVIRONMENT=venv uv run python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/docs.yml'))" && echo YAML-OK
```

Expected: `YAML-OK`.

- [ ] **Step 4: Gates + commit**

```bash
set -o pipefail
UV_PROJECT_ENVIRONMENT=venv uv run ruff check . && UV_PROJECT_ENVIRONMENT=venv uv run mypy && UV_PROJECT_ENVIRONMENT=venv uv run --extra test pytest -q
git add .github/workflows/docs.yml
git commit -m "ci(docs): build docs on PR/push, deploy versioned site to Pages on main"
```

---

### Task 6: Local end-to-end verification (MAIN SESSION — Interceptor required)

**Files:** none created; findings may modify Tasks 2–5 outputs.

**Interfaces:**
- Consumes: everything built so far.

- [ ] **Step 1: Full multi-version build**

```bash
great-docs build
```

Expected: exit 0; all of `v0.0.1`, `v0.0.2`, `dev` built.

- [ ] **Step 2: Preview server**

```bash
great-docs preview
```

Keep running; note the local URL.

- [ ] **Step 3: Interceptor browser check (real Chrome)**

Using the Interceptor skill against the preview URL, verify and screenshot each:

1. Landing loads and defaults to the **latest stable tag** (not dev).
2. Version switcher lists `v0.0.1`, `v0.0.2`, `dev`.
3. Navigating to the `v0.0.1` version renders its pages (old version reachable).
4. `dev` carries an "unreleased" label (switcher and/or page banner). If Great Docs has no native marker, add the minimal config/template tweak here and rebuild — this is the spec's labeled fallback.
5. All six content surfaces render: landing, guide, API reference, CLI reference, changelog, `llms.txt` (fetch `llms.txt` via curl too).
6. Banner renders; no broken asset links (browser console clean of 404s).

- [ ] **Step 4: Fix findings, rebuild, re-verify; commit any changes**

```bash
set -o pipefail
UV_PROJECT_ENVIRONMENT=venv uv run ruff check . && UV_PROJECT_ENVIRONMENT=venv uv run mypy && UV_PROJECT_ENVIRONMENT=venv uv run --extra test pytest -q
git add -A ':!great-docs'
git commit -m "docs: verification fixes from local multi-version browser check"
```

(Skip the commit if nothing changed.)

---

### Task 7: PR, review, merge

**Files:** none new (process task).

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/docs-site
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create -R madeinoz67/benchweave-sdk --base main --head feat/docs-site \
  --title "feat: versioned docs site (Great Docs + Pages)" \
  --body "Implements docs/superpowers/specs/2026-09-16-sdk-docs-site-design.md (local-untracked spec). Tag-keyed multi-version + dev; landing=stable; full content set; CI-gated build; Pages deploy on main. Local browser verification passed (Task 6)."
```

- [ ] **Step 3: Code-reviewer pass**

Dispatch the repo's `code-reviewer` agent on the PR (docs-coverage duty applies: it checks not only diffs that touch docs but changes that should have). Fix findings per standing severity flow (CRITICAL/HIGH fixed; LOW/NIT held as a numbered table for row calls). Findings land as follow-up commits on the branch.

- [ ] **Step 4: CI green, then merge**

```bash
gh pr checks && gh pr merge --squash --delete-branch
```

Expected: all checks green (including the new docs job); squash merge to `origin/main`.

---

### Task 8: Main-repo pointer advance

**Files:** none in the SDK; the main repo's submodule pointer.

- [ ] **Step 1: Advance the pointer**

```bash
cd /Users/seaton/Documents/src/BenchWeave
git pull --ff-only
cd packages/sdk && git checkout main && git pull --ff-only && git checkout feat/docs-site 2>/dev/null || true
cd /Users/seaton/Documents/src/BenchWeave
git add packages/sdk
git commit -m "chore: advance SDK pointer — versioned docs site"
git push
```

Note: pointer advances on main are established practice (see `72fd21a`); this is the sanctioned exception to the branch rule. Push of the main repo is the trusted-repo standing carve-out.

---

### Task 9: Enable Pages + first live deploy + verification

**Files:** none (repo settings + live checks).

- [ ] **Step 1: Enable Pages with the Actions source**

```bash
gh api -X POST repos/madeinoz67/benchweave-sdk/pages -F build_type=workflow
```

Expected: 201 with the pages config. (If the repo already has Pages configured, `gh api -X PATCH ... -F build_type=workflow` instead.)

- [ ] **Step 2: Trigger + watch the first deploy**

```bash
gh workflow run docs.yml -R madeinoz67/benchweave-sdk --ref main 2>/dev/null || gh run rerun --failed -R madeinoz67/benchweave-sdk $(gh run list -R madeinoz67/benchweave-sdk --workflow docs.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch -R madeinoz67/benchweave-sdk $(gh run list -R madeinoz67/benchweave-sdk --workflow docs.yml --limit 1 --json databaseId --jq '.[0].databaseId')
```

Expected: deploy job succeeds. If the workflow only triggers on push, push an empty commit to main (`git commit --allow-empty -m "ci: trigger first docs deploy" && git push` from the SDK repo — AFTER merging, on main).

- [ ] **Step 3: Live verification**

```bash
curl -s -o /dev/null -w "%{http_code}" https://madeinoz67.github.io/benchweave-sdk/          # 200
curl -s -o /dev/null -w "%{http_code}" https://madeinoz67.github.io/benchweave-sdk/0.0.2/    # 200
curl -s -o /dev/null -w "%{http_code}" https://madeinoz67.github.io/benchweave-sdk/llms.txt  # 200
```

Expected: all 200 (path shapes may differ by tool convention — discover the real version-path shape from the deployed sitemap/nav if 404, then re-verify). Then one Interceptor pass on the live URL: switcher works, old version resolves, dev labeled, landing = stable.

---

### Task 10: Close-out

**Files:**
- Modify: git index (force-add spec + plan)

- [ ] **Step 1: Force-add the landed-work docs**

```bash
cd /Users/seaton/Documents/src/BenchWeave/packages/sdk
git add -f docs/superpowers/specs/2026-09-16-sdk-docs-site-design.md docs/superpowers/plans/2026-09-16-sdk-docs-site.md
git commit -m "docs: close-out — land docs-site spec and plan"
git push
```

Then advance the main-repo pointer again (Task 8 pattern).

- [ ] **Step 2: Memory proposals**

Propose to the ledger (per repo protocol): the real version-path shape Pages served, any Great Docs config gotchas discovered (native dev-labeling yes/no, freeze-cache dir names), and the workflow adjustments that were needed. Tags: `sdk`, `docs-site`, plus at least one descriptive tag.

---

## Addendum B — true per-tag snapshots (principal ruling 2026-09-16, Option 2)

The native in-process multi-version build is symbol-set-true but renders page content (docstrings/members) from the current tree (controller-verified against tool source + built buckets). Ruling: content fidelity wins.

- CI builds each tag in isolation: `great-docs build --from-repo https://github.com/madeinoz67/benchweave-sdk.git --branch <tag> --output-dir site/v/<tag>`; latest stable additionally to site root; main (dev) to `site/v/dev`.
- Pre-site tags v0.0.1/v0.0.2 have no `great-docs.yml` at their refs and cannot be built by `--from-repo`: they remain native in-process buckets (correct symbol sets, current docstrings — disclosed approximation) with the version-warning banner ON, until superseded by the first post-site release. Dropping them entirely is the alternative; default = keep.
- The version list in `great-docs.yml` stays static and complete so every per-tag build's switcher lists all versions.
- Verify in Task 5: package importability inside `--from-repo` isolated venvs (likely solved); favicon/cairosvg availability in those venvs (fallback: post-generate favicons from `docs/assets/logo.svg` as a CI step and copy into each bucket); absolute-link/site_url rooting across the assembled tree.
- Task 6 verification gains: per-tag content spot-check (a docstring added after tag T must NOT appear in v/<T>/).

## Addendum A — public site + theming (principal directive 2026-09-16, mid-run)

Design sources (committed toplevel repo `dadb07f`): `docs/internal/public-site-styleguide.html` (design system incl. explicit "Great Docs mapping" section) and `docs/internal/public-site-mockup.html` (public site: panels home/standards/guides/sdk). These are the authoritative design; the styleguide's Logo section already overrode the Task 3 logo fix (hand-authored `docs/assets/logo.svg` hexagon+weave mark, Trace Amber #C6790A + blue strands, never a raster crop).

### Task 11: Great Docs theming (execute after Task 5, before Task 6)

**Files:** Modify `great-docs.yml` only (mapping section: "themes entirely through great-docs.yml — no custom CSS required").

Exact keys from the styleguide's mapping table (verbatim values):
- `accent_color`: `{ light: "#C6790A", dark: "#FFB020" }`
- `navbar_color`: `{ light: "#EEF1F0", dark: "#1B2027" }` — flat color, NOT a preset gradient (none match Trace Amber)
- `display_name`: `"BenchWeave"`
- `logo`: the Task-3-fix `docs/assets/logo.svg` (auto-generates favicons)
- `include_in_header`: the same Google Fonts links the styleguide uses (Space Grotesk, IBM Plex Sans, IBM Plex Mono) + one line of custom SCSS to apply them

Verify: rebuild, all three versions render with the theme; fonts load (browser network check in Task 6).

### Task 12: Static public website (execute after Task 11, before Task 6)

**Files:** Create `website/` in the SDK repo (static HTML/CSS from the mockup, no build chain) — content: the four mockup panels (home, standards, guides, sdk) as static pages or one page with anchors, per the mockup's own structure; tokens and components copied from the styleguide; `assets/logo.svg` shared with the docs.

**Open fork (default taken):** one Pages site per repo — static site serves at the root URL and the versioned docs live under `/docs/` (great-docs re-rooted via site_url/base config). If great-docs 0.17.0 proves unable to serve multi-version under a subpath, fall back to: docs stay at root and the static site's home panel becomes the great-docs landing page (themed), losing the standalone site. Resolve the fork by local experiment before building the site pages.

Deployment: Task 5's workflow (and Task 9's live check) extended to publish static site + docs in one Pages artifact.

### Task 6 scope (amended)

Interceptor verification now also covers: themed docs (accent/navbar/fonts across light+dark), static site pages render per mockup, logo mark renders in navbar + favicon, both surfaces on one Pages URL family.

## Self-Review

**Spec coverage:** versioned-by-release (T2 config + T6/T9 verify) ✅ · dev + guards (T2, T6.4, T9) ✅ · landing=stable (T2, T6.1) ✅ · six content surfaces (T2/T3/T4 + T6.5) ✅ · CI-gated build (T5 + T7.4) ✅ · versions appear via main-push (T5, T9.2) ✅ · guard-first (T2.2) ✅ · two-repo plumbing (T7→T8, T10) ✅ · falsifiers (T6, T9.3) ✅ · non-goals respected (no tag trigger, no theming) ✅.

**Placeholder scan:** config keys are set by intent with the generated file's own documented comments as the key reference (tool-contract, not hand-wave); every command, path, and expected outcome is concrete. No TBDs.

**Type consistency:** no code signatures introduced; docstring-only `src` changes are style-checked against `great-docs.yml`'s detected style. File names consistent across tasks (`docs.yml`, `feat/docs-site`, `great-docs.yml`).
