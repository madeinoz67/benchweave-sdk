# Plugin-developer onboarding — design note

**Status:** Design — WS1 and WS2 ruled, builder-ready · **Tracking issue:** madeinoz67/benchweave#347
**Evidence baseline (verified 2026-10-03):** SDK `main` `64de6cf`, pyproject `0.5.0` (unreleased; latest tag `v0.4.1` at `a5bfc58`). Gateway `main` `69d4513`; `packages/sdk` is a git submodule pinned at gitlink `7d9a8ba` (= pyproject `0.4.1`, 11 commits behind the `v0.4.1` tag). `benchweave-sdk --version` prints `benchweave-sdk, version 0.5.0`. Wheel deps: `click`, `jsonschema`, `referencing`, `rfc3339-validator`, `rfc3987`, `rich`, `textual`.

## Summary

Issue #347 (parkview) names three symptoms — look-alike checkouts, a stale `packages/sdk`, and a CLAUDE.md with no usage path. The real gap is wider: there is no plain path from "I have a device" to "my plugin passes `check`". This note fixes that, not just the symptoms.

- **WS0 (shipped)** — "Which checkout do I use?" and "Using the SDK" pointers. SDK PR #84, gateway PR #351.
- **WS1 (ruled option 2)** — keep the mount; add a CI drift check (gitlink vs latest SDK tag), automated bump PRs, and an offline `doctor` for a stale installed SDK.
- **WS2 (ruled copier)** — move scaffolding to copier so a project scaffolded at N updates to N+1 with one command.
- **WS3** — Claude assets in the scaffold: a CLAUDE.md that imports an SDK-managed file, plus 3–5 skills.
- **WS4** — first-timer docs (STE100), glossary, troubleshooting, docs-as-tests.

## Why the mount stays (WS1 finding)

The mount is load-bearing, not a stale copy. The gateway binds to `packages/sdk` three ways: (a) mypy type-checks `packages/sdk/src`; (b) all 16 `tests/sdk/` modules import `benchweave_sdk` from the mounted source (`sys.path.insert`, not a wheel); (c) `make check-sdk-standards` exports the corpus into the SDK lock and refuses drift. No uv workspace or path dependency binds them. Existing CI catches *inconsistency* (gateway vs lock vs tree) but not *staleness* of the gitlink vs the latest SDK release tag, so a self-consistent old mount passes green while silently stale.

## Requirements

| ID | Requirement | Falsifier |
|---|---|---|
| R-1 | No reader mistakes `packages/sdk` for the canonical SDK | pointer present in gateway README and docs (WS0) |
| R-2 | Mount drift vs the latest SDK tag is detected in CI | the drift check fails on a stale gitlink |
| R-3 | A stale installed SDK is detected offline in a plugin project | `doctor` prints "project vX, you have vY, run Z" |
| R-4 | A project scaffolded at N updates to N+1 in one command; author files are untouched | `upgrade`; managed files changed, owned files diff empty |
| R-5 | The scaffold ships a CLAUDE.md import + skills that cannot drift from the docs | skills regenerate from one source; a CI drift check |
| R-6 | A first-timer reaches `check`-pass from the getting-started page alone | docs-as-tests CI proves it |
| R-7 | The wheel's dependency set is unchanged | installed deps identical before and after |

## Open questions

- **Q1 — bump automation:** Dependabot `gitsubmodule` vs Renovate. Recommend Dependabot first (already in both repos); Renovate is the fallback if `gitsubmodule` cannot pin a tagged submodule here.
- **Q2 — staleness surface:** a new `doctor` subcommand vs extending `check`. Recommend `doctor` — a separate, non-failing surface; `check` stays a pure conformance gate.
- **Q3 — non-Claude agents (WS3):** also emit `AGENTS.md` with CLAUDE.md importing it. Recommend yes — one body for both agent types.
- **Q4 — skill source (WS3):** generate skills from the docs vs one authored source. Recommend one authored source under the SDK with a CI drift check against the user guide, not a generator (keeps skill prose tunable).

## Increments

1. **WS1 — mount drift + bump (gateway).** CI step comparing the gitlink SHA to the SDK's latest tag; Dependabot/Renovate on `packages/sdk`.
2. **WS1b — `doctor` (SDK).** Offline scaffold-version vs installed-SDK check; network opt-in.
3. **WS2 — copier (SDK).** `template/` in the SDK repo tagged with releases; a `[scaffold]` extra (copier only, core deps unchanged); `new` wraps `copier copy` against the packaged template; `upgrade` wraps `copier update`; `adopt` writes `.copier-answers.yml` for existing projects; managed vs owned split per the STOP.
4. **WS3 — Claude assets (SDK).** CLAUDE.md import + 3–5 skills.
5. **WS4 — docs (SDK).** STE100 getting-started, which-checkout, glossary, troubleshooting; docs-as-tests CI.

Each increment lands as its own PR through the increment loop.
