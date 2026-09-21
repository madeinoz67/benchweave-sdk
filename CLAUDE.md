@AGENTS.md

## MANDATORY: Use Gortex MCP tools instead of Read/Grep/Glob

A Gortex daemon is configured machine-wide. Whenever you operate on indexed source, you
MUST prefer graph queries over file reads. Hook posture is configurable; follow every
Gortex hook instruction even when raw `Read` / `Grep` / `Glob` remain callable.

Calibration: the graph narrows scope, it does not replace reading the implementation. For
the symbol you are about to change or depend on, read its full body with
`read(target:{symbol:…})` or `read(operation:"file", …)` — never act on a one-line summary
alone, and be deliberate with behavior-critical code (standards-sync digests and refusal
paths, scaffold output, packaging): read the real implementation, no compressed bodies.
The full per-tool catalog and workflow load via `tools/list` at session start; until this
checkout is tracked, fall back to `Read` and say so — do not start a daemon.

### Edit routing — which write path applies

One decision point, not a per-edit judgment call. The mandate binds the main
session's own edits, not only dispatched agents.

| Situation | Path |
|---|---|
| File indexed, primary checkout | `mcp__gortex__edit` — `change(operation:"impact")` before, `change(operation:"detect")` after; signatures also `verify` |
| Linked worktree overlay | gortex single-file edit when freshness reports `exact: true` with `actual_view` naming the worktree; otherwise native Edit, and the bypass names the caveat |
| Branch-new / untracked file | native Write; visible to the graph after the next index pass |
| Generated files (`src/benchweave_sdk/preview_assets/`, `CHANGELOG_AUTO.md`, `.docs-assembly/`, `site/`, vendored standards trees) | never hand-edited — regenerated via their tool |

Every native bypass states which row covers it. Guessing `pytest -k` filters is
the anti-pattern this table replaces — `change(operation:"tests")` names the files.

---

This file governs how AI agents work in this repo: what the SDK *is*, the principles that
must never be violated, and how to write and review changes that fit the project. The
deep reference lives in `docs/internal/` — this file is the index and the non-negotiables.

## 1. What the plugin SDK is

The **BenchWeave plugin SDK** is the offline authoring and conformance tooling for OTDP
device plugins: scaffolding (`new`), conformance checks (`check`, `check-ui`,
`check-preset`), registry metadata help (`inventory`), the standards sync
(`sync-standards`), and the preview surfaces (`preview-ui`). Python 3.13, `uv`, hatchling,
strict mypy. Its one-line promise is load-bearing — every change is measured against it:

> **A plugin developer authors, checks and previews a conformant plugin on a machine that
> has never seen the gateway checkout — and what the SDK accepts is what the gateway
> accepts.**

The clauses map to real machinery:

- **authors, checks and previews** → `scaffold.py` (the generated project is the public
  face), `conformance.py`/`validation.py`/`fixtures.py` (the offline standards), the
  preview suite (`preview_server.py`, `presentation.py`, `preview_assets/`).
- **never seen the gateway checkout** → self-containment: CI checks out with no submodules
  and never reads the parent repository; the wheel packages `src/benchweave_sdk` only.
- **what the SDK accepts is what the gateway accepts** → the vendored standards corpus,
  sha256-pinned by `standards-lock.json`, stamps and all three check lanes in agreement.

If a change makes the SDK behave less like this — a conformance rule that weakens
silently, a scaffold that generates what `check` rejects, a preview that disagrees with
`check-ui`, a path that reaches for the parent checkout — it is wrong even if the suite
passes.

### Architecture map

| Subsystem | Files | What it owns |
|---|---|---|
| CLI | `src/benchweave_sdk/cli.py` | The command surface (`new`, `check*`, `inventory`, `sync-standards`, `preview-ui`) |
| Scaffold | `src/benchweave_sdk/scaffold.py` | Generated plugin projects, AI-GUIDE text, the pinned SDK-version test extra |
| Conformance | `conformance.py`, `validation.py`, `fixtures.py`, `testing.py` | The offline encoding of the gateway's load-time standards |
| Standards sync | `standards_sync.py`, `standards-lock.json`, `src/benchweave_sdk/standards/` | Lock ↔ vendored tree ↔ stamps; refusal prefixes; the three check lanes |
| Preview | `preview_server.py`, `preview_models.py`, `preview_tui.py`, `presentation.py`, `preview_assets/` | Plugin-ui rendering against the vendored contracts; agreement with `check-ui` |
| Packaging | `pyproject.toml`, `hatch_build.py` | Wheel/sdist contents; vendored-tree verification before packaging |

Reference docs: `docs/internal/invariants.md` (STD/PKG/SRF/TWO),
`docs/internal/review-rubric.md` (the gated review protocol),
`docs/internal/drift-and-obligations.md` (cross-surface obligations + the CI map).

## 2. Core principles (the lens for every change)

1. **Lock ↔ tree ↔ stamps (STD-1).** Every vendored file is lock-recorded by sha256 or
   stamped; anything else is drift. The lock is what makes "vendored" mean pinned rather
   than copied.
2. **Normative content never changes here first (STD-5, TWO-1).** Hand-editing vendored
   bytes is wrong regardless of quality; the change belongs in the main repository's
   canonical corpus, re-exported and re-synced with a version increment.
3. **The refusal prefixes are the contract (STD-4).** Every refusal path raises a
   `snake_case:`-prefixed `ValueError`; CI and scripts branch on them. Error text is an
   API.
4. **Self-containment is a proof, not a preference (PKG-1).** Nothing at test or runtime
   reaches for the parent gateway checkout — the submodule mount makes parent paths exist
   on a developer machine and not in CI, so the breakage hides exactly where it matters.
5. **Scaffold output is an interface (SRF-1).** Downstream plugin repositories diff
   generated projects; shape changes are interface changes. The generated runtime has no
   dependency on this SDK.
6. **Preview ↔ check-ui agreement (SRF-2).** A preview that renders what the conformance
   check rejects (or the reverse) trains plugin authors to ship what the gateway will
   refuse.
7. **Conformance weakens silently (SRF-3).** Compare every rule against the vendored
   standard text, never against memory of what it says.
8. **Pin the observable wire, not the source schema.** Serve-time layers normalize;
   the emitted form is the contract.
9. **The behavioral suite lives here (`tests/`); cross-repo properties are proven
   main-side.** "Couldn't run tests" stated plainly beats a green-looking review that
   never ran them; name the modules that cover the change.
10. **Minimal, reviewable increments referencing their design (the `increment` skill).**
    Design records are committed (`.claude/deep-review/`) so pre-committed acceptance
    rules are provably pre-committed.
11. **Honest negative results are first-class.** A killed idea on measured evidence is a
    real result.
12. **Claim discipline (`docs/internal/review-rubric.md` G4).** A set named in prose is
    regenerable from a mechanism; a guard states what it does not catch; every number
    carries its denominator and says whose measurement it is.

## 3. How we work

**Verify, don't assume.** For any non-trivial change:

1. **Confirm the commit you're on.** Diff against `main` before asserting what the code
   does; remember the second checkout (the submodule mount in the gateway repo) exists.
   Work happens on working branches — never commit to `main` directly.
2. **Run the real gates, not the diff**: from this repo's root, with
   `UV_PROJECT_ENVIRONMENT=venv` — `uv run ruff check .`, `uv run mypy` (strict;
   `files = ["src"]`; CI's `uv run mypy src` must agree), `uv run benchweave-sdk
   sync-standards --check`, and the `benchweave-sdk --version` smoke. Then the suite
   (`uv run pytest -q` here; `uv run pytest tests/sdk` from the gateway checkout when a
   property that compares the SDK with the gateway moved) for the touched modules —
   read counts from the raw run, never from an output-filter summary line.
3. **RED-sanity-check bug fixes.** Run it where the proving test lives (here, or
   main-side for a cross-repo property): revert only the fix,
   watch the test fail, restore, watch it pass. `no tests ran` is a FAILED check (pytest
   exits 5 when it collects nothing) — look for the collected count.
4. **Walk the obligations.** `docs/internal/drift-and-obligations.md` is the list; the
   path-shaped ones additionally warn via `.claude/hooks/drift-guard.mjs` (marked 🪝 in
   that doc) — a reminder, not a gate, and no substitute for walking the list.

## 4. This repository is public

Measure on real plugin projects, sync histories, and benches; **never name them**.

- Refer to a measurement corpus as **"a real plugin project"** or **"a real bench"**.
  Keep the numbers; drop the name.
- Use invented names in fixtures and examples — not a real author, client, repository URL,
  or package name that identifies its owner.
- No client, tenant, or employer identifiers; no pricing or commercial terms.
- If a design record can't make its point without those, it isn't publishable —
  `.claude/deep-review/README.md` has the triage rule and the `private/` convention.

Git history is forever and a scrub of the tip is not a scrub. Getting it right before the
commit is the only version of this that works.

---

## The code-review agent

`.claude/agents/code-reviewer.md` is the repo's resident reviewer — correctness, the
hard invariants (`docs/internal/invariants.md`), and cross-surface drift, with its own
verify-build-test protocol. Use it (or the `/code-review` skill) when reviewing a change,
and proactively before opening a PR. It routes by what the diff touches and follows
`docs/internal/review-rubric.md` as the authority. Behavioral tests live here (`tests/`);
the modules that compare the SDK with the gateway stay main-side (`tests/sdk/` in the
gateway checkout), and the reviewer says when it could not run one a change needed.

---

## Attribution

Do not add "Generated with Claude" / Anthropic attribution to any PR body, commit message,
issue, or code comment.
