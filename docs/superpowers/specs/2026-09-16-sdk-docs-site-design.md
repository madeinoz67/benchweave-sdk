# BenchWeave SDK Documentation Site — Design

**Date:** 2026-09-16
**Status:** Approved design (brainstorm session, principal-ratified)
**Scope:** `madeinoz67/benchweave-sdk` — work executed in the `packages/sdk` submodule checkout
**Planning doc:** local-untracked per repo convention; force-added at close-out only.

## Context

The SDK repository (public, hatch, Python >=3.13, package `benchweave-sdk` v0.0.2, CLI `benchweave-sdk`) ships `README.md` and `docs/plugin-sdk.md` but has no generated docs site. Tags v0.0.1/v0.0.2 exist with GitHub releases; the 0.1.0 standards reset landed on main after v0.0.2, so main currently leads the newest tag — the normal state for a pre-1.0 SDK.

Principal requirements: docs **versioned by SDK release** (old versions stay referenceable forever), plus a **`dev` version tracking main**, guarded so it is never mistaken for a citable release.

Verified environment facts (2026-09-16):

- `great-docs` CLI installed (`~/.local/bin/great-docs`); Quarto 1.9.37 local.
- Great Docs ships native multi-version docs (`--versions 0.3,dev`, `--latest-only`; versioned builds from tags), `setup-github-pages` workflow generation (auto-detects uv from `uv.lock`, Python from `requires-python`, uses Quarto's official action), and `great-docs ci` PR-preview helpers.
- Repo is PUBLIC → GitHub Pages available. One-time enable needed (Source: GitHub Actions): `gh api -X POST repos/madeinoz67/benchweave-sdk/pages -F build_type=workflow`.
- Existing tags: v0.0.1, v0.0.2.

## Goal (ideal state)

A published, versioned documentation site for `benchweave-sdk` on GitHub Pages where:

1. Every SDK release tag has a browsable docs version; old versions never disappear.
2. A `dev` version tracks main, clearly labeled unreleased, never the site default.
3. Landing/default = latest stable tag.
4. Content set: landing (README), plugin authoring guide, API reference (auto), CLI reference, changelog, `llms.txt`.
5. Docs build is CI-gated: a docs build failure fails CI.
6. New versions appear through the normal main-push deploy; no extra manual steps per release.

Each claim is browser-falsifiable (switcher lists all versions; old version URL resolves; dev labeled; landing = stable).

## Decisions

| Fork | Decision | Why |
|------|----------|-----|
| Toolchain | Great Docs | Installed skill family; native versioning; pattern reusable for the main repo later |
| Hosting | GitHub Pages via generated workflow | Zero infra; repo already public |
| Versioning | Native tag-keyed multi-version + `dev` | Exact match to "versioned by SDK release, old versions still referenced" |
| Content | Full standard set | Nothing hand-maintained beyond the guide that already exists |
| Deploy trigger | Stock main-push | A release cut bumps the version on main anyway → the version appears with the release; add a tag trigger later only if the lag matters |
| Repo flow | Working branch → PR → merge in SDK repo, then pointer advance on main repo | Standing branch + two-repo discipline directives |

## Components

### 1. Site init & config

- `great-docs init` at the submodule root; `great-docs.yml` carries site identity and the banner asset (`docs/assets/benchweave-sdk-banner.png`).
- No gate changes from content: ruff already excludes `docs/`; mypy `files = ["src"]`.

### 2. Content mapping

- **Landing:** README.md as home page content.
- **Guide:** `docs/plugin-sdk.md` becomes the user-guide section (write-user-guide conventions; executable cells where useful).
- **API reference:** auto-discovered exports of `benchweave_sdk`; `great-docs scan` previews coverage; thin docstrings improved via revise-docstrings conventions where the reference would otherwise be empty.
- **CLI reference:** click command tree (CLI: `benchweave-sdk`).
- **Changelog:** rendered from `CHANGELOG.md`; git-cliff remains the single source (never hand-edited).
- **`llms.txt`:** generated agent-context file.

### 3. Versioning semantics

- Versions = git tags (v0.0.1, v0.0.2, …) + `dev` (main).
- Every deploy rebuilds all versions from tags → self-healing; old versions always present.
- Landing = latest stable tag.
- `dev` labeled "unreleased" in the version switcher plus a page-level marker if Great Docs supports it natively; otherwise a minimal config/template tweak. Verified during implementation, not assumed.
- `dev` is explicitly non-citable; tagged versions are the citable surface.

### 4. CI & deploy

- `great-docs setup-github-pages` generates the workflow (uv + Python 3.13 + Quarto action auto-detected). The generated file is a reviewed starting point, not gospel: build on PR + main push, deploy on main push, `great-docs ci` preview hints on PRs.
- One-time Pages enable via `gh api` (above).
- Docs build failure fails the workflow (strict build gate).

### 5. Guard-first hygiene

- Extend `.gitignore` with the ephemeral `great-docs/` build directory (plus any freeze/cache dirs the tool creates — names confirmed at init) BEFORE the config/workflow commit. Standing rule: never commit tool-generated files.

### 6. Repo plumbing & sequencing

- Work happens in the `packages/sdk` submodule checkout (own ledger/hooks per the split discipline).
- Branch: `feat/docs-site` (working-branch directive; no direct main commits).
- Sequence: gitignore guard → init/config/content → local build + verify → workflow → PR → code-reviewer review (docs-coverage duty applies) → merge/push → pointer advance on main repo → enable Pages → first live deploy → live verification.

## Verification (falsifiers)

- **Local:** `great-docs build` exit 0; `great-docs preview` site Interceptor-browser-checked — switcher lists v0.0.1, v0.0.2, dev; old-version pages resolve; dev carries the unreleased label; landing = stable; all six content surfaces render.
- **CI:** PR workflow green including the docs job.
- **Live:** Pages URL serves; versioned paths (`/0.0.2/`, later tags) resolve; switcher works; `llms.txt` fetches (curl 200).
- **Negative:** a deliberately broken docs page fails CI (observed in PR, or trusted from the strict gate).

## Non-goals

- Main BenchWeave repo docs site — separate later cycle; this design is the reusable seed.
- Custom theming beyond banner/identity; PDF/epub; search tuning beyond native.
- Tag-triggered deploy (revisit only if release-to-docs lag ever matters).
- Redirect scaffolding (new site, no legacy URLs); multi-language.

## Defaults taken (principal may override)

- README as landing content.
- Deploy on main push only.
- `dev` included from day one with unreleased labeling.
