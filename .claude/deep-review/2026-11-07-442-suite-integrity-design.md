# Issue #442 — order-dependent fixture loss and a serial capture leak: design

- **Date:** 2026-11-07
- **Branch:** `design-442`, cut from `origin/main` at `228cd30`
- **Issue:** gateway tracker #442 (`sdk`)
- **Tier:** Tier 2 by `docs/internal/review-rubric.md` §Step 1 — the only proposed edit is
  `tests/conftest.py` plus one probe module; nothing on the list matches (no lock, no
  vendored bytes, no refusal prefix, no scaffold output shape, no `conformance.py` /
  `validation.py` / `fixtures.py`, no dependency motion, nothing reaching outside the
  repository).
- **Status:** design only. No production code.

---

## 0. Verdict, up front

The issue names two defects and its first comment adds a third. **All three are already
gone from `origin/main`**, and the first one does not reproduce on any tree this design
could reach — including the two trees the issue names.

| # | Claim | Verdict |
|---|---|---|
| 1 | Order-dependent fixture loss: `tests/server/test_capture_lifecycle.py` → `tests/test_zero_literal_gate.py` → any other `tests/server/` module → "fixture not found" | **NOT REPRODUCED.** Five orders/trees, zero errors. Also architecturally implausible (see §3). |
| 2 | A serial serving test writes `captures/operator-action-token.json` into the repo working directory | **REAL, ALREADY FIXED** by `203442d` (merged `a14d7d4`), 88 minutes *before* the issue was filed. RED and GREEN both reproduced here (§2). |
| 3 | (issue comment) `tests/test_dependency_serving.py` tampers the committed vendored schema from two unserialised tests | **ALREADY FIXED** by `8ad2876` in the same PR (#141); both arms now copy the tree and tamper the copy (`tests/test_dependency_serving.py:193`). |

The one thing worth building is **not** a fix: it is a guard, because defect 2's repair is
a per-test convention with nothing enforcing it (§4). That slice is recommended, optional,
and its acceptance rule is pre-committed in §7.

---

## 1. Reproduction evidence

Environment: this worktree, `UV_PROJECT_ENVIRONMENT=venv`, `pytest 9.2.0`, Python 3.13,
`uv sync --locked --extra test --extra server --extra scaffold`. Every run below is serial
(no `-n`) unless stated. Counts are read from the raw run, not a filter summary.

| Run | Tree | Command order | Result | `git status` after |
|---|---|---|---|---|
| A | `origin/main` `228cd30` | `test_capture_lifecycle.py` → `test_zero_literal_gate.py` → `test_mcp.py` | **101 passed**, 57.81 s, exit 0 | clean |
| B | `origin/main` | A's pair, then the whole `tests/server/` directory | **1638 passed, 1 skipped**, 457.47 s, exit 0 | clean, no `captures/` |
| D | `origin/main` | reversed: `test_mcp.py` → `test_capture_lifecycle.py` → `test_zero_literal_gate.py` | **101 passed**, 60.08 s, exit 0 | clean |
| E | `5d67b86` — the pre-shim `main` tree (2026-10-10, the tree the issue says reproduces) | reported order | **86 passed**, 38.64 s, exit 0 | clean |
| F | `7a21cff` — the shim branch head (`feat/issue440-q5-shim`) | reported order | **86 passed**, 37.86 s, exit 0 | clean |
| G | `203442d^` = `76c85cb` (pre-fix) | the single node `tests/server/test_serial_session.py::test_cli_transport_serial_serves_binding_pending` | **2 passed, 2.15 s** — and **`./captures/operator-action-token.json` left in the repository cwd** | dirty (the leaked file) |
| H | `origin/main` | the same node | **2 passed**, 1.43 s | clean, no artifact |
| I | `origin/main` | CI shape: `-m "not browser and not timing and not loop and not live_ftdi" -n auto` | **3033 passed, 6 skipped**, 138.02 s, exit 0 | clean, no `captures/` |

Note on the issue's own paths: there is no `tests/server/test_zero_literal_gate.py`; the
module is `tests/test_zero_literal_gate.py`. Run with the path as written and pytest exits
4 (`file or directory not found`) before collecting anything.

Run I matters beyond leak-checking: it is the baseline the guard's "no false positive" arm
is measured against, and it is clean — **no test in the suite writes into the working tree
today** (confirmed independently by reading every `REPO / …` write site in `tests/`; all of
them are reads or `copytree` *sources*).

### What the negative means for #1

Five runs, four orders, three trees, two pytest invocation shapes, ~1900 test executions
in the failing configuration per run — and not one fixture error. The claim is not
reproducible at the detail level it was filed at (the third module was named only as "any
other module in `tests/server/`"; 1638 of them ran).

This is a **killed row, not a failed investigation** — and it changes the severity of the
row. See §3 for why fixture loss cannot do what the issue says it can do.

---

## 2. Defect 2: the write path, established

Not "tests should use `tmp_path`" — the actual chain:

1. **The default.** `src/benchweave_sdk/capture.py:91` —
   `root = Path(from_environment) if from_environment else Path.cwd() / "captures"`.
   Decision 9's documented precedence, and it is correct behaviour for a CLI: the capture
   root follows the operator's working directory.
2. **Who reaches it.** `src/benchweave_sdk_server/cli.py:746` — `serve` delivers the
   operator-action token to the capture-root family only for `transport in ("serial",
   "ftdi")`, *before* `uvicorn.run` is reached (`cli.py:751`).
3. **The write.** `src/benchweave_sdk_server/cli.py:96` — `path.write_text(...)`, 187 bytes
   of `{pid, operator_action_token, url}`.
4. **The trigger.** `tests/server/test_serial_session.py::test_cli_transport_serial_serves_binding_pending`
   (two parametrisations) invoked `serve … --transport serial --no-open` through
   `CliRunner` in-process, with a sentinel parked at `uvicorn.run`. An in-process
   `CliRunner` invoke inherits the pytest process's cwd — the repository root — so
   `Path.cwd()` in step 1 is the checkout.
5. **Why it was silent.** The test passed. The delivered file was never asserted on, never
   read back by anything in the suite (every read is rooted at `tmp_path`:
   `tests/server/test_cli.py:251,286,403,432`), and `captures/` is not in `.gitignore`, so
   it also left a dirty checkout for the next run to wonder about.
6. **The repair.** `203442d` ("#427 fold row 2") added `tmp_path` to that arm and
   `monkeypatch.chdir(tmp_path)` (`tests/server/test_serial_session.py:163`), matching the
   convention `_serve_output` already used (`tests/server/test_cli.py:214-224`). Merged as
   `a14d7d4` at 11:17 UTC on 2026-10-10; the issue was filed at 12:45 UTC the same day.

### Severity, stated plainly (the brief asked)

**The leaked file never affected an outcome.** Nothing consumes it, so it could not make a
red look green or the reverse. It is a hygiene defect and a developer-checkout pollutant,
not a measurement-integrity defect — with one future-facing caveat: a stale
`captures/operator-action-token.json` sits exactly where the *next* run of any test that
resolves the capture root from the cwd would find it. That is how it becomes a measurement
defect, and it is the reason a guard is still worth its ten lines.

The remaining sweep confirms the fix is complete: the only three other `serve
--transport serial` invocations (`tests/server/test_cli.py:238,267,450`) all go through
`_serve_output`, which chdirs; the `ftdi` deliveries are reached only through `_build_seam`
(no CLI serve), so no token write occurs. Run I above is the empirical close.

---

## 3. Why defect 1 cannot do what the issue says it does

Two independent reasons the report should be corrected rather than implemented:

1. **pytest resolves conftest fixtures at collection, before any test body runs.**
   `tests/server/conftest.py` is imported once, at collector start-up. A test body later in
   the session cannot unregister a fixture from that module's `FixtureManager`; the only
   way a conftest fixture goes missing is the conftest *failing to import*, which surfaces
   as `ImportError while loading conftest` at start-up, not as a per-test
   `fixture '<name>' not found` on the third module. The symptom named and the mechanism
   implied do not fit together.
2. **Fixture loss is loud, never silent.** A missing fixture is an `ERROR` at setup and
   the test does not run. Even if the report were true, it could only turn a *green suite
   red* — it cannot "make a red look green". The brief's fear (a lost fixture silently
   validating the wrong bytes) requires a fixture that *resolves to different bytes*, which
   is a different defect class and is covered here by different machinery: the vendored
   tree is digest-pinned (`standards-lock.json`), and scaffold goldens are byte-compared
   (`tests/fixtures/scaffold_expected`, R-2).

What could produce the reported symptom, if it happened at all: a run whose collected
third module sat under a *different rootdir ancestry* than the conftest that defines its
fixtures (the second-checkout / submodule-mount hazard `AGENTS.md` warns about), or an
explicit `--confcutdir` above `tests/server/`. Both are invocation errors, and neither is
reachable from the command in the issue. Since I cannot reproduce it, I do not design
against a guess.

**Falsifier for this section:** a run of the reported order on any tree where the third
module's fixtures fail to resolve while `tests/server/conftest.py`'s import succeeds. If
that is ever produced, this analysis is wrong and defect 1 reopens with that transcript.

---

## 4. The slice: one guard, extending the proven one

### Mechanism

Extend the existing suite-wide write guard rather than adding machinery beside it.
`tests/conftest.py:62` (`_the_committed_tree_is_never_written`) already wraps the four
write vectors — `Path.write_bytes`, `Path.write_text`, `Path.open` with a
write-capable mode, and the `open` builtin with a write-capable mode — and refuses
*before* delegating, so no byte lands. Today its predicate (`_is_tree_path`,
`tests/conftest.py:47`) matches only the vendored standards tree.

The change: a second, narrower predicate on the same hook, refusing any resolved path
**inside the repository working tree**, with the repository's own scratch directories
exempted:

```
refuse if resolved is under REPO
   and not under REPO/.pytest_cache
```

Order of checks matters — the vendored-tree refusal keeps firing first, so every existing
pinned message and probe (`tests/test_tree_guard.py`, `tests/server/test_tree_guard_reach.py`)
is untouched. The new refusal is a second `AssertionError` whose message names the path and
the remedy ("resolve your root under `tmp_path`").

Three lines of configuration, one predicate, one message. No new module, no new CI job, no
production code, no change to `capture_root()` (Decision 9's fallback stays exactly as it
is — the CLI behaviour is correct; it is the *tests* that must not inherit it).

### Why not the alternatives

- **Make the leak impossible instead of guarded** — e.g. an autouse fixture that sets
  `BENCHWEAVE_CAPTURE_DIR` for every test. Rejected: that is silent substitution of
  explicit configuration, it hides the behaviour under test (Decision 9's precedence),
  and it turns a leak into an invisible no-op instead of a red.
- **Session-end `git status` snapshot diff** — catches leftovers of *any* vector including
  the unhooked ones. Rejected as the first slice: it cannot name the offending test, it is
  racy across concurrent workers sharing one checkout, and it is blind to paths covered by
  `.gitignore` (the exact failure mode that bit `captures/`-class artefacts elsewhere).
  It is a reasonable second slice if the write-vector guard ever proves too narrow — noted
  as a deferral, not built.
- **A harness-wide `tmp_path` refactor** — the brief asked for the smallest change that
  removes the non-determinism. There is no non-determinism left to remove; only the
  regression surface to pin.

### Precedent

`tests/conftest.py:62` (#427) is the precedent, and it is a *proven* one: it was built
after a write-by-pass matrix showed the original narrow guard silent on `write_text`,
`open("w")`, `os.replace`, `shutil.copyfile`, subprocess writes and symlink swaps; its
hooked vectors are pinned by `tests/test_tree_guard.py` and proved to reach descendants by
`tests/server/test_tree_guard_reach.py`. This slice adds one predicate to that guard, in
the same shape, with the same refusal-before-write posture, and extends the same probe
family. No new architecture.

### Deferrals (explicit)

- **No change for defect 1.** No mechanism found; nothing to build. Closes with §1/§3.
- **No change for defect 3.** Fixed at `8ad2876`; nothing to do.
- **No production change.** `capture_root()`'s cwd fallback, `cli.py`'s token delivery,
  and Decision 9's precedence are all untouched.
- **No `captures/` entry in `.gitignore`.** Deliberately rejected: ignoring the directory
  would hide exactly the artefact class the guard exists to surface.
- **The unhooked vectors stay unhooked.** `os.replace`/`os.rename`, `os.open` descriptors,
  `shutil.copyfile`'s sendfile fast path, subprocess writes and symlink swaps remain
  outside the guard, exactly as `tests/conftest.py:77` already discloses. Extending that
  set is a separate change with its own probe rows.
- **No Windows/older-pytest reproduction hunt for defect 1.** Reopen trigger below.

---

## 5. Cross-surface impact

- **Modules that consume the fixtures at risk** (defect 1's blast radius, had it been
  real): every module under `tests/server/` — 1638 tests in run B — through the eleven
  fixtures in `tests/server/conftest.py` (`starter_project`, `plugin`, `mock_host`,
  `seam`, `seam_from`, `policy`, `app`, `client`, `app_client_factory`,
  `lanes_project_builder`, `invoke_project_builder`). Run B executes all of them in the
  contaminated order and they all resolve.
- **Byte-pinned scaffold fixtures: not at risk, and not touched.** The R-2 goldens under
  `tests/fixtures/scaffold_expected/` are consumed from `tests/test_scaffold_copier.py`,
  `tests/test_scaffold_create.py` and `tests/test_preview_fixtures.py:742` — none of which
  uses a `tests/server/conftest.py` fixture. A lost `starter_project` could not corrupt a
  golden comparison; it would simply fail to run.
- **The vendored standards tree: read-only in the loading path.** `tests/server/conftest.py`'s
  `lanes_project_builder` reads `src/benchweave_sdk/standards/otdp/0.2.0/examples/class-daq.json`
  for contract rows; the suite-wide guard already refuses any write to that tree.
- **CLI / user guide / README / scaffold output / AI-GUIDE / standards lock / wheel / sdist
  / main-repo behavioural suite:** **none move.** No user-visible surface changes, no
  vendored bytes, no lock, no packaging change, no cross-repo property. The proposed edit
  is test-harness only.
- **CI cost:** zero new jobs. The guard adds one `Path.resolve()` per hooked *write* (the
  `_writes(mode)` gate runs first, so reads pay nothing) — unmeasurable against run I's
  138 s. The "no false positive" arm re-uses the existing suite invocation.

---

## 6. Invariants, drift, and obligations

- **Invariants:** no STD/PKG/SRF/TWO row changes. Nothing here touches the lock, the
  vendored tree, refusal prefixes, scaffold shape, conformance, packaging, or the two-repo
  discipline. This is suite hygiene; the nearest anchor is prose, not an invariant — the
  guard's G4 "NOT CAUGHT" list at `tests/conftest.py:77`, which the slice must keep
  truthful (the new predicate does not change that list; it changes *which paths* the
  already-hooked vectors refuse).
- **Drift/obligations:** row 6 (SDK behavioural changes). No new module is required, so
  no row moves; the probe rows land in `tests/test_tree_guard.py`, whose docstring
  generalises from "the committed-tree guard's trip probes" to the working-tree guard's.
- **Claim discipline (G4):** the guard states what it does not catch, and the record says
  its denominator. The "no false positive" claim is `3033 passed, 6 skipped` on this
  worktree at the slice head — whose measurement it is: this checkout, this machine.

---

## 7. Pre-committed acceptance rule

Written before any guard code exists and before any post-change number is looked at. All
arms are named; every number carries its denominator.

### Arms

**A1 — the guard fires on the new vector (synthetic probe).**
A probe in `tests/test_tree_guard.py` writes `REPO / "#442-guard-probe.tmp"` through each
already-hooked vector and requires `AssertionError` matching `repository working tree`,
plus `assert not target.exists()` in a `finally` cleanup.
- *Denominator:* 4 vectors (the four hooked write vectors).
- *Mutation that must redden it:* delete the repo predicate from `_refuse`. Expected red:
  no `AssertionError` is raised and the probe file lands.

**A2 — no false positive across the suite.**
`uv run pytest -q -m "not browser and not timing and not loop and not live_ftdi" -n auto`
with the guard armed: **0 failed, 0 errors**, and `git status --porcelain -uall` empty
afterwards.
- *Denominator:* the full collected count at the slice head (baseline: 3033 passed,
  6 skipped — run I).
- *Mutation that must redden it:* the same repo predicate change cannot be measured here;
  this arm is the control for the slice's blast radius, not for its mechanism.

**A3 — the actual historical leak reddens (end-to-end regression control).**
Take `tests/server/test_serial_session.py::test_cli_transport_serial_serves_binding_pending`
and delete `monkeypatch.chdir(tmp_path)` (restore the pre-`203442d` shape). With the guard
armed the arm must fail, and the failure must name
`…/captures/operator-action-token.json`.
- *Denominator:* 2 tests (both parametrisations: `absent`, `explicitly-empty`).
- *Green control:* the same node, unmutated, passes and leaves no artefact in the
  working tree (baseline: run H, 2 passed, clean).
- *Mutation that must redden the RED control itself:* remove the guard's repo predicate →
  the mutated arm passes again **and** leaves the file — which is the proof the guard, not
  the test, is what caught it.

### Decision rule

- **Ships** if A1 reds on its mutation, A2 is green with the quoted counts, A3 reds on its
  mutation naming the path, and A3's green control passes with a clean tree.
- **Killed** if A3's mutated run leaves the artefact **without** reddening — that means the
  guard misses the very vector it was built for, and shipping it would be a false claim.
- **Underpowered, not conclusive** — do not ship, report — if A2 reds on a path a test
  writes on purpose (the guard's scope is wrong, not the suite), or if A3 reds for a reason
  that does not name the artefact path (assertion was incidental rather than causal).
  In that case the fallback is the session-end `git status` guard (§4), re-designed with its
  own pre-committed rule rather than patched in under this one.

---

## 8. Top risks, each with its falsifier

1. **False positives break the suite for a legitimate future repo write.** A test that
   deliberately mutates a tracked file to prove a guard would now be refused.
   *Falsifier:* any red in A2 naming a path a test writes on purpose. Mitigation at build
   time: the exemption list is exactly `.pytest_cache` — anything else needs an explicit,
   visible opt-out, never a quiet widening.
2. **The guard shadows a real defect by refusing a write the SDK is supposed to make.**
   *Falsifier:* A2 red where the write is SDK behaviour, not a test artefact (for example a
   `capture_root` refusal arm aimed at a repo path).
3. **Over-claim.** "No test writes into the working tree" is true for *this* suite today,
   proved by run I plus a read of every `REPO / …` write site — not a theorem about future
   tests, and not a statement about the unhooked vectors.
   *Falsifier:* a future test that writes into the tree and passes because it used
   `os.replace`.
4. **The guard is not what fixed the leak.** The fix is `203442d`, five weeks earlier. If a
   reviewer reads this record as "the leak was live until we guarded it", that is wrong:
   the guard pins a *repaired* leak, and A3's mutation is the only thing that demonstrates
   that.
   *Falsifier:* run G's transcript above — the RED is at `203442d^`, not at slice head.

---

## 9. What the maintainer must decide

1. **Close or narrow the issue.** Defects 2 and 3 are fixed and defect 1 does not
   reproduce. Three rows of the issue as written are not buildable; the evidence is §1–§3.
2. **Whether the guard is worth having at all.** It is ~10 lines and one probe family. The
   honest case against: the leak is already fixed by convention, no outcome was ever
   corrupted, and the guard is coverage for a class that has only fired once. The honest
   case for: that once cost five weeks of polluted checkouts and was found by accident, the
   fix is a convention nobody enforces, and this repository's own doctrine treats leaked
   suite state as a first-class defect (#427 built the whole existing guard on exactly that
   reasoning).
3. **Whether the session-end `git status` guard should be the shape instead** if the
   maintainer's risk appetite prefers breadth (all vectors) over attribution (names the
   test). This record recommends the write-vector shape and defers the other.
4. **The reopen trigger for defect 1:** any CI red matching `fixture … not found` under
   `tests/server/`, on any OS or pytest version, reopens it with that transcript — this
   design's negative is bounded to the trees and orders in §1, and this machine.
