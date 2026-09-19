---
name: increment
description: The repeatable build loop the plugin SDK holds itself to — design, build RED-first (proving tests main-side), independently vet, adversarially refute, MEASURE real value on real data, then PR/CI/land. Use for any non-trivial feature or fix ("build X", "add Y", "next increment"). Encodes the discipline that keeps us shipping real, measured value instead of smoke-and-mirrors.
---

# increment — the SDK build loop

This is the loop that ships qualified tooling: design before code, RED before GREEN,
refute before PR, measurement before merge. The north star: **the offline authoring and
conformance tooling a plugin developer can trust — scaffold, check, sync, preview, each
doing exactly what the vendored standards say, on a machine that has never seen the
gateway checkout.** The bar for every increment: **self-contained, standards-exact,
measured — no smoke-and-mirrors, no claims about gateway behavior the main-side suite
hasn't proven.**

## When to use

Any non-trivial feature or fix. For a one-line mechanical edit, just do it. For anything
that touches the standards sync, the scaffold, conformance rules, packaging, or the CLI,
run the loop.

## The non-negotiable principles (the lens)

1. **Measure, don't claim.** Every increment ships with a before/after on real data
   (generated projects, sync histories, wheel contents) that quantifies value. "It works"
   is not a result; "40/40 golden projects regenerate byte-identical after the change,
   where the old scaffold drifted on 3" is. If you can't measure it, you don't understand
   it yet.
2. **Defer-if-buggy over ship-to-hit-a-milestone.** If a refute pass finds a real defect
   you can't cleanly fix, ship the clean core and DEFER the broken part to a
   properly-designed increment. Name the deferral in the PR.
3. **Honest negative results are first-class.** If the measurement shows no meaningful
   value, or a gate can't be cleared, HOLD and report — don't dress up noise. A killed
   idea is a real result.
4. **Never trust a sub-agent's "green."** Independently re-run ruff, mypy,
   `sync-standards --check` and the main-side suite yourself, and read the counts from
   the run, not from a summary line.
5. **Minimal, reviewable increments referencing their design.** No sprawling PRs. Name
   what you defer. Design docs live in `.claude/deep-review/` — committed artifacts, so
   pre-committed acceptance rules are provably pre-committed (see its README for the
   public/private triage rule).
6. **The tool encodes the standard; it never reinterprets it.** Behavior is pinned
   against the vendored corpus text, not against memory of what the standard says; the
   observable emitted wire is what gets pinned, not what the source schema claims; and
   normative content never changes here first — it arrives as a re-sync with a version
   increment.

## The loop

1. **Design.** Spawn the `increment-designer` agent grounded in the REAL code and the
   vendored standards text. It must deliver: the mechanism, the minimal first-increment
   scope with explicit deferrals, precedent from proven in-tree mechanisms, invariant
   impacts, the MEASURABLE proof with a pre-committed acceptance rule, and top risks.
   DON'T-BUILD is an accepted outcome.
2. **Decide.** Read the design. Surface any genuine product-behavior fork to the owner;
   otherwise pick the defensible default and proceed. For a contested call, run the
   `panel` skill.
3. **Build, RED-first.** The `increment-builder` agent works in a fresh worktree off
   `origin/main` (`UV_PROJECT_ENVIRONMENT=venv`), writing its proving tests main-side
   (`tests/sdk/` in the gateway checkout). For every behavior change: write the test,
   show it FAILS without the code, then implement.
4. **Vet (you, independently).** `uv run ruff check .`, `uv run mypy` (strict;
   `files = ["src"]`), `uv run benchweave-sdk sync-standards --check`, the
   `benchweave-sdk --version` smoke — then the main-side suite for the touched modules.
   RED-check the key guards discriminate (toggle off → fail) using a `cp` backup, NEVER
   `git checkout` on files with uncommitted work.
5. **Adversarial refute.** Spawn the `adversary` agent with a REFUTE mandate. **Tier-3
   per the review rubric (standards lock / vendored tree / `hatch_build.py`, refusal
   prefixes, scaffold output shape, conformance weakenings, parent-checkout reach,
   dependencies) → the refute pass is mandatory.** For anything moving a digest rule,
   version bound, compatibility note, schema normalization, or scaffold template, also
   run the `mechanism-critic`. Reconcile: both clean → stands; a real evidenced defect →
   fix it; a genuine correctness split → DEFER to the owner. Fix every real finding,
   with RED-proven guards.
6. **Measure — the acceptance gate.** The `bench-measurer` agent proves real value on
   real data with a NON-GAMEABLE test. Prefer a control that fluff can't pass: a RED
   check (mechanism disabled → effect gone), a golden-project diff, or a
   permutation/shuffle null. Report the number.
7. **Land.** PR into `main` (working branches only — never commit to `main` directly),
   title + body naming what shipped + what's deferred, referencing the design — and
   **every deferral in the body must cite an open issue, created at PR-open time if
   absent; an orphan deferral blocks the merge** (main #69). Multiple PRs from one
   work use **PR stacks**: dependent PRs open with base = the predecessor's branch;
   merge bottom-up, retargeting successors to `main`. **A work is complete only when
   every PR it raised — in both repos, when it spans them — is merged.** Watch CI
   to green (`gh pr checks --watch`). Merge when all-green and authorized; otherwise hand
   off. If a gate is red or a finding is unfixed, HOLD and report — do not merge.

## Contributor PRs

Don't bounce nitpicks back to a strong contributor, especially after multiple
round-trips. Either adjust their branch yourself (`maintainerCanModify=true`: merge
`main` INTO their branch, resolve, push — a merge commit, not a force-push) or merge and
do a small follow-up PR. Still hold the bar (Tier-3 refute, CI green).

## Golden projects and the main-side suite

Prove scaffold and conformance behavior against pinned golden projects and the vendored
corpus before claiming anything about the gateway — and remember the behavioral proof
lives main-side (`tests/sdk/` in the gateway checkout). "Couldn't run the main-side
suite" stated plainly beats a green-looking review that never ran it. A change that
expects a main-side counterpart (corpus re-sync, renderer rebuild, pointer advance)
names that counterpart in its PR.

## Surface-aware parallelism (main #69)

Parallel increments only across DISJOINT surfaces. Increments sharing a surface —
this repo's `main`, the vendored standards tree (which changes only via
`sync-standards` from the main repo), or the preview assets — serialize on it by
design: the second parks at review-complete and rebases onto the merged predecessor
exactly once. Before any push: **merge-result pre-check** — CI tests your branch +
current `origin/main`, not your base; simulate the merge and run sibling lanes when
a shared surface moved. GOVERNANCE.md and the loop/rubric prose live main-side
only — they are NOT part of the vendored set and do not sync; the authoritative
text is the main repo's.

## Pipelining

While one increment's build/refute runs, design the next (agents notify on completion).
Keep the owner's roadmap and any contributor backlog both advancing. Run several loops in
sequence for a big push; stay in the loop between them.
