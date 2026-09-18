# Review rubric — the dependable-review protocol

This is the backbone of `code-reviewer`. It is written so that **even a weak model that
follows it literally produces a review you can trust**, because the judgment is offloaded to
mechanical evidence (ruff, strict mypy, the standards self-check, the RED-sanity procedure)
and to objective routing rules, not to the model's insight. The model's job is to run the
gates and attach the evidence, or to escalate honestly when it can't.

Three ideas run the whole thing:
1. **Evidence, not opinion.** Every gate produces pasted command output or it did not happen.
2. **The system picks the depth.** Risk tier is decided by objective path/keyword rules.
3. **A hard confidence floor.** If a gate can't be satisfied with evidence, the verdict is
   DEFER, never approve-on-faith. Deferring is cheap and safe. A wrong merge is not.

---

## Step 0 — Confirm what you're reviewing (always)

- `git branch --show-current`, `git log --oneline -3`; diff the change against its base.
  This repository exists in two checkouts — the standalone clone and the submodule mount
  at `packages/sdk` in the gateway repo — and they are the same repository; review
  whichever holds the change, and remember the other exists when reasoning about pointers.
- **Read this rubric and the contract docs from `main`, not from the branch.**
- Record the head SHA in your review. If you can't confirm the SHA you reviewed, stop.

## Step 1 — Pick the risk tier (objective, grep-driven)

Run the diff's file list through these rules, top to bottom. First match wins.

**TIER 3 — deep, mandatory second adversarial reviewer.** Any of:
- touches `standards-lock.json`, `src/benchweave_sdk/standards/**`, or `hatch_build.py`
  (the lock ↔ tree ↔ stamps surface)
- changes a refusal prefix or adds a refusal path (the `snake_case:` machine-matchable
  surface CI and scripts branch on)
- touches `scaffold.py` output shape (generated projects are the SDK's public face and
  downstream repos diff them)
- touches `conformance.py`, `validation.py`, or `fixtures.py` (a weakening here silently
  greenlights a non-conformant plugin)
- reaches for the parent/gateway checkout or any path outside this repository at test or
  runtime (breaks the self-containment proof CI exists to verify)
- adds, removes, or re-pins a dependency (`pyproject.toml`, `uv.lock`)

**TIER 2 — standard.** Any other change to Python logic under `src/`, `.github/`, docs
build config, or root config (`pyproject.toml`, `great-docs.yml`).

**TIER 1 — light.** Only docs (`*.md`, `*.qmd`), comments, or website copy — and nothing
that matches Tier 3.

State the tier and the rule that triggered it at the top of your review.

## Step 2 — Evidence gates (run every gate in scope; attach real output)

Each gate is PASS only with pasted output. No output means the gate did not run, which means
you cannot APPROVE.

**G0 Secrets (all tiers, before anything else).** Scan the diff — source, tests, comments,
fixtures, commit message, and filenames — for `mk_`, `mdb_`, `gorag_`, `ghp_`, `github_pat_`,
`sk-`, `Bearer ` literals, and private paths. A variable reference (`${MUNINN_BENCHWEAVE_KEY}`)
is not a secret; a literal is. Any hit → **BLOCK**. Severity is never downgraded; a key in
git history is unfixable after the fact.

**G1 Static gates (all tiers).** From this repository's root, with
`UV_PROJECT_ENVIRONMENT=venv`: `uv run ruff check .`, `uv run mypy` (strict;
pyproject `files = ["src"]`; CI runs `uv run mypy src`, which must agree — a new `Any` or
untyped def is a finding), `uv run benchweave-sdk sync-standards --check`, and the
`uv run benchweave-sdk --version` entry-point smoke. Any failure → **BLOCK**.

**G2 Tests (Tier 2 and 3).** The SDK's own pytest is the release smoke; the behavioral
suite lives **main-side** (`uv run pytest tests/sdk` from the gateway checkout root, in the
gateway environment). Run the main-side modules the diff touches and name them. When the
standalone clone is all you have, **say so plainly and list which main-side modules should
cover the change** — "couldn't run tests" stated beats a green-looking review that never
ran them. Read counts from `--junitxml` attributes or exit codes, never from an
output-filter summary.

**G3 RED-sanity (any PR that claims to fix a bug or add a guard).** The proving tests live
main-side: revert ONLY the production fix (keep the test), run the test there, watch it go
**RED**, restore, watch it go **GREEN**, paste both. `no tests ran` is a **FAILED** RED
check — pytest exits 5 when it collects nothing; look for the collected count. If you
cannot produce red-then-green, the fix is **unproven** → you may not APPROVE.

**G4 Contract check (Tier 2 and 3).** Load `docs/internal/invariants.md` and apply every
group whose files appear in the diff. For each invariant, grep the anchor in the LIVE code,
confirm it still describes the code, then state PASS or FAIL. If a doc's text disagrees
with the live code, the **code wins** — flag the stale doc, don't enforce it. Review the
change's *claims* alongside: a set named in prose must be regenerable from a mechanism; a
guard must state what it does not catch; *cannot/never* claims need the structural reason
inline, otherwise *is refused unless* plus the residual.

**G5 Cross-surface drift (all tiers).** Walk `docs/internal/drift-and-obligations.md` for
every touched surface. Any unmet obligation is a **required change**, not a nit. Absence of
the update is the finding even when the diff touches no docs.

**G6 Adversarial refute (TIER 3 ONLY — mandatory).** A second, independent reviewer runs
the gates again AND actively tries to break the change: what input, lock state, or packaging
shape makes it wrong? For a standards change: what previously-synced tree does it now
refuse or silently accept? Never the model that produced the change. The two reviews are
compared:
- Both reach APPROVE with consistent evidence → APPROVE stands.
- The refuter finds a real, evidenced failure → needs-work.
- They disagree on a correctness point and evidence can't settle it → **DEFER**.

## Step 3 — Verdict (bounded by the confidence floor)

- **APPROVE** — only if every in-scope gate PASSED with attached evidence, and (Tier 3) G6
  agreed. Nothing else earns an approve.
- **APPROVE WITH REQUIRED CHANGES** — gates pass but a G5 obligation or a small, named fix
  is outstanding. List them numbered.
- **NEEDS WORK** — a gate failed or a real defect was found.
- **DEFER (human)** — you cannot satisfy a gate with evidence (including: the main-side
  suite could not be run for a Tier 3 change), the Tier-3 panel is split, or the change
  turns on standards semantics owned by the main repository's canonical corpus — say what
  specifically needs a corpus owner and why. **Never guess, never approve-on-faith.**

## Step 4 — Anti-hallucination self-check (before you emit the verdict)

Answer these literally. Any "no" downgrades the verdict to DEFER:
- Did I attach real pasted output for G1 — counts read from the run itself, not an
  output-filter summary?
- If I claim a fix works, did I show the RED-sanity red-then-green output (main-side)?
- If Tier 3, did a genuinely independent second pass (G6) run, and do I state its verdict?
- Did I verify each invariant I cite against the live code, not just quote the doc?
- Did I append the full findings record — every severity, LOW and NIT included, each with
  its disposition — to the memory ledger (`node .claude/hooks/memory-propose.mjs`), tags
  carrying the `sdk` identity tag riding with at least one descriptive tag
  (`["sdk", "code-review"]`, never `["sdk"]` alone)?

A review that reaches APPROVE without the evidence its tier requires is itself invalid.
Re-run it or DEFER.

---

## Why this is safe enough to trust without a human on routine changes

The human doesn't disappear. The human is **escalated to only when the system is honestly not
confident** — a failed gate, a main-side suite that couldn't run, a split adversarial panel,
or standards semantics owned by the main repository. Everything else is approved on
mechanical evidence that a weak model can produce as reliably as a strong one: ruff either
passes or it doesn't, the standards self-check either agrees with the lock or it doesn't, a
reverted fix either reddens its test or it doesn't. The floor is what makes "you don't
review routine code anymore" a promise the system can keep instead of a hope.
