# Design — issue #476 (and #475 residual): make Build Docs END when the work is done

Date: 2026-10-19 · Repo: benchweave-sdk · Branch: `designer-475-docs-exit-path` (off `origin/main` @ `b0d398c`, which carries `61f0302`) · Tracker issues: gateway #475, #476 (single issue stream; SDK-side work)

**Verdict: BUILD.** The evidence establishes that the direct child (`great-docs`) itself never
exits after printing its completion banner, so no "reap survivors after normal exit" variant can
work and waiting out the #475 bound is a real, measured cost. The mechanism below ends the step
on the tool's own work-done signal. The one thing this design cannot give is a pinned root cause
inside great-docs' interpreter shutdown on CI — that is named upstream, with everything we did
establish (and the honest negative result) recorded in §2.

---

## 1. The measured problem

Fleet evidence (cancelled SDK run `38758274375`, job `116502421567`, branch
`fix/lock-anchor-test-neutral`):

- `15:14:22.588` — last log line: great-docs' completion banner
  (`[OK] Build complete … 🎉 Site ready → … great-docs/_site`).
- `15:14:22` → `15:20:16` — 5m54s of silence; no `[assemble]` line.
- `15:20:16.676` — `##[error]The operation was canceled.` (human cancel, ahead of the 900s bound).
- At cancel the runner terminated orphan processes: `uv`, `python`, `great-docs`,
  `python3.13`, `python3.13`.

Decoding the tree: `uv` → `python` (the assemble script) → `great-docs` (the direct child of our
`run()`) → two `python3.13` grandchildren. **The direct child was alive at cancel.** The banner
names `great-docs/_site`, which is only the in-process multi-version build's output
(`scripts/assemble_docs_site.py` main step 1: `great-docs build --versions v0.0.1,v0.0.2,dev` —
the only two tags without `great-docs.yml` at their ref, verified this session). If `run()` had
returned, the next log line would have been `[assemble] isolated build: --branch v0.0.3 …`
(`isolated_build()` logs before every `--from-repo` build). Its absence means the `subprocess.run`
never returned: **the child printed its final banner and did not exit.** Ten further cancelled
runs exist across 2026-10-15 → 2026-10-17 (intermittent).

Issue #476's "runs 20x slower than its build" is the same defect: ~6 minutes of post-work silence
against a ~2–3 minute build (see the local measurement below).

`61f0302` (on `main`, ancestor of `b0d398c`, verified) already added: `log()` flush,
`run(..., stream=)` opt-out of capture, `GIT_TIMEOUT=60`, `GREAT_DOCS_TIMEOUT=900`,
`GIT_HTTP_LOW_SPEED_*`, `timeout-minutes: 45`. That bounds the hang — a recurrence now burns up
to 900s per great-docs invocation and then reds the lane. Issues #475/#476 remain open because
the step still *waits out a bound* instead of *ending when the work is done*.

## 2. Root cause status — established vs named-upstream

Established this session (all against great-docs 0.17.0, the version pinned in
`.github/workflows/docs.yml`):

1. **The child never exits.** Fleet orphan list (above). This kills the "child exits, grandchildren
   hold the pipe" shape (`killpg`-after-normal-exit alone cannot fix what we observed) and it also
   means capture-vs-stream is not the discriminator: with `stream=True` the parent blocks in
   `proc.wait()`, with capture it would block in `communicate()` — either way, on a live child.
2. **great-docs 0.17.0 has no post-banner blocking path in its own code.** Read every
   `threading.Thread(` site (three — all `daemon=True`: `_versioned_build.py:1428`, `:1469`,
   `core.py:15825`), every `Popen` site (three — all followed by `wait()`: `_versioned_build.py:1401`,
   `:1457`, `core.py:15759`), every executor (two, both inside `with` blocks:
   `_versioned_build.py:1528`, `:1548`), and no `atexit` registrations. The banner
   (`_build_log.py:814–833`, `[OK] … Build complete … Site ready`, flushed per line by
   `_safe_stream_write(..., flush=True)`) is emitted by `log.footer(...)`, which is the **final
   statement of `build()`** (`core.py:16389–16393`; the single-version arm `core.py:16507–16513`)
   — after it there is only `os.chdir` in a `finally` and the return up through click. So the
   hang-after-banner lives in **interpreter shutdown or a platform/library interaction** (Linux,
   Python 3.13, uv venv), not in build logic.
3. **Honest negative result (A11): the hang does not reproduce on this Mac.** The identical
   invocation — `great-docs build --versions v0.0.1,v0.0.2,dev`, pipx-installed 0.17.0
   (Python 3.14, Quarto 1.9.37) — ran in a clean worktree, printed the same banner
   (`[OK] Build complete — 21/19 steps (9 skipped, 1 warning)` / `Total time: 2m 20.1s` /
   `Site ready (1 warning) → …/great-docs/_site`) and **exited cleanly** (2m20s total).
   The defect is CI-environment-specific and intermittent; the upstream mechanism (shutdown-join
   vs lingering jupyter-kernel/resource-tracker children — the two `python3.13` orphans) cannot be
   pinned from here and is **named upstream**, to be filed as a great-docs issue with this
   record's evidence.

What this means for the fix: our parent-side contract must stop being "the step ends when the
child process exits" and become "the step ends when the tool says the work is done" — the
completion banner is the tool's own last act, and the artifact checks downstream
(`bucket_source()`, `verify_tree()`) already carry the evidence that the work is real.

## 3. The mechanism

One extension of the existing `run()` helper in `scripts/assemble_docs_site.py` (the `61f0302`
shape — extend it, do not add a parallel helper):

**`run(cmd, *, cwd=None, timeout=None, stream=False, done_marker=False, grace=30.0)`** — when
`done_marker` is set (only the two great-docs call sites use it), instead of
`subprocess.run(...)`:

1. `proc = subprocess.Popen(cmd, cwd=cwd, start_new_session=True, stdout=PIPE,
   stderr=STDOUT, text=True, bufsize=1)` — the child becomes its own session/process-group
   leader. This is what later makes `killpg` safe: today great-docs shares OUR process group, so
   a group kill from the timeout path would signal the assemble script itself. setsid first,
   group-kill second — the two are inseparable.
2. A daemon reader thread forwards every line to `sys.stdout` (flushed) so CI keeps the live
   build output #475 fought for, and records the first sight of either completion marker:
   - OK marker: regex `\[OK\] Build complete` **and** a subsequent `Site ready` line
     (both inside the one banner box; conjunction kills false positives from any single quoted
     string).
   - FAIL marker: regex `\[FAIL\] Build failed` (checked first).
3. The main loop polls `proc.wait(timeout=0.5)`; four endings, all loud:
   - **E1 — child exits on its own** (the normal case, and the only case seen locally): its real
     exit code is honored exactly as today. No reclamation, zero grace cost.
   - **E2 — OK marker seen, child keeps running** (the observed CI shape): after `grace` (default
     30s) send SIGTERM to the child's process group (reaps great-docs AND the lingering
     `python3.13` grandchildren), escalate to SIGKILL after 10s, then return success with a
     disclosure log line: `[assemble] great-docs banner seen; process reclaimed after {n}s —
     exit code masked by reclamation`. The masked code is honest because the tool's own last
     word was success AND the artifact checks downstream still gate the step.
   - **E3 — FAIL marker seen, child keeps running**: same reclamation, then
     `SystemExit(f"command failed (banner): {cmd}")` — a loud failure, code unavailable,
     disclosed.
   - **E4 — no marker, child never exits** (a mid-build wedge, not the observed class): the
     existing outer `timeout` (`GREAT_DOCS_TIMEOUT=900`) fires, now with group SIGTERM/SIGKILL
     before the `SystemExit` that names the command — today's `TimeoutExpired` path kills only
     the direct child and leaks the grandchildren to the runner.
4. Call-site changes, exactly two: `isolated_build()` and main()'s in-process build add
   `done_marker=True` (both already pass `stream=True`, which the guarded path supersedes — it
   forwards rather than inherits). Git helpers (`release_tags`, `guard_dest`) are unchanged: no
   banner, plain timeout.

`run()` keeps returning `str` (guarded path returns `""` — its callers ignore stdout). The module
docstring's subprocess-bounds paragraph gains two sentences naming the marker contract and its
version pin (see R1/R2).

### Why not the alternatives

- **`killpg` after normal child exit only** (lead's candidate 2): contradicted by the orphan
  list — the child does NOT exit. Would fix only a shape we have not observed.
- **Accept the bound (DON'T-BUILD variant)**: leaves each recurrence burning up to 15 minutes
  per great-docs invocation × up to 22 invocations per assembly, and #476's complaint stands.
  The bound stays as backstop E4, not as the primary path.

## 4. Precedent

- `run()` itself (`61f0302`) — this extends its loud-failure, named-command, timeout-bounded
  shape with a session guard. No new architecture.
- Daemon-reader-thread + pipe forwarding is great-docs' own in-process pattern
  (`_versioned_build.py:1418–1433`) — vendor precedent for the read shape, not invented here.
- Scripts-test precedent: `tests/test_release_cut.py` tests `scripts/release_cut.py`; the new
  test module follows that import pattern for `scripts/assemble_docs_site.py`.

## 5. Minimal first increment — scope and deferrals

**Scope (one RED→GREEN slice, one commit):**
1. `scripts/assemble_docs_site.py`: the `run()` extension above, the two call sites, docstring
   notes. ~70 lines.
2. `tests/test_assemble_run_guard.py`: fake-child harness (a tiny inline python child via
   `sys.executable -c`) that reproduces the CI shape — prints the exact 0.17.0 banner bytes, then
   sleeps forever holding two sleeping grandchildren. Tests (all with grace/timeout scaled to
   seconds): (a) marker+hang child → success within `grace + 5s`, and the child's process group
   is empty afterwards; (b) normal-exit child → success, no reclamation log, real exit code
   honored; (c) fail-banner child → `SystemExit` naming the command; (d) the marker regexes match
   the literal 0.17.0 banner text captured in §2 (drift tripwire). Runtime ≈ 10–15s.
3. This design record.

**Explicit deferrals (each with its owner surface):**
- **Gateway-repo twin port** — `BenchWeave/scripts/assemble_docs_site.py` has the same exposure
  and worse: its `run()` captures with **no timeout** (line ~173) and its docs workflow's
  build-docs job has **no `timeout-minutes`**, so a recurrence there hangs toward the runner's
  6h default. Port the guarded runner + the #475 bounds as its own slice with its own RED; do
  not smuggle it into this SDK commit.
- **Upstream great-docs issue** — file with §2's evidence (banner-then-no-exit on
  Linux/py3.13, orphan list, clean macOS/py3.14 run). External action; maintainer files it.
- Root-cause chase inside CPython/great-docs shutdown — stays upstream (§2.3).
- Marker-watching for git helpers — none exists; plain timeout is correct for them.
- Any artifact-verification addition — `bucket_source()` / `verify_tree()` already gate the
  artifacts downstream; the runner does not learn about artifacts.

## 6. Invariant and drift impacts

- **Hard invariants: none touched, none gained.** The change is CI/docs tooling in the SDK repo;
  no CTL/STO/CON/REG surface is within reach (checked against
  `docs/internal/invariants.md` — no anchor names the docs assembly's subprocess handling; the
  website-stamp machinery (CON-8 class) is the gateway script's concern and is untouched).
  Governing instincts only: A06 (banner ≠ process exit — evidence over assertion, and the
  masked exit code is disclosed, with artifact checks still gating) and A11 (the §2.3 negative
  result is published, not buried).
- **Surfaces that move:** SDK `scripts/assemble_docs_site.py` + one new test module. **No
  `.github/workflows/docs.yml` change** — the mechanism is script-only; `timeout-minutes: 45`
  and the env stay as the outer frame; the great-docs 0.17.0 pin is unchanged (the marker
  contract is version-pinned to it, exactly like the markup workarounds named in that workflow
  comment).
- **On-disk format/schema: none** — not a Tier-3 trigger by the format rule.
- **SDK drift obligations:** `packages/sdk/docs/internal/drift-and-obligations.md` has one
  docs-workflow CI-map row ("this repository's docs.yml: the docs site builds from this
  repository's content") — still true; no obligation row names the assemble script's internals.
- **CI cost:** one new pytest module (~15s) in the SDK suite; ruff covers `scripts/`
  (`uv run ruff check .`); **mypy unchanged** — `[tool.mypy] files = ["src",
  "scripts/claim_lane.py"]` deliberately excludes the older scripts, and this design keeps that
  boundary rather than widening the strict gate in a CI-fix slice.

## 7. Review tier and Step-1 keyword scan (#254)

**Tier 3** (mandatory adversarial refute). Path rules would say Tier 2 (`scripts/`), but the
keyword rule fires first-match on diff *text*: the expected diff (code + test + comments)
contains `subprocess` and `threading`. Expected counts over the whole expected diff (the review
re-derives; a deviation is a finding, not a retune): `subprocess` ≥ 10, `threading` ~3–5,
`asyncio` 0, `sha256` 0, `hashlib` 0, `migrate` 0, `recovery` 0, `protection` 0. No
`standards/`, no schema, no dependency change, no submodule pointer.

## 8. Acceptance rule — pre-committed before any harness run

Primary proof is local and mechanism-level (the CI defect itself does not reproduce locally —
§2.3 — so the field rule is the follow-through, not the primary). Numbers below were fixed
before the harness exists. Grace and timeout are parameters; the production defaults are 30s
grace / 10s TERM→KILL / 900s outer bound.

**GREEN — mechanism present.** In the SDK worktree, `uv run pytest tests/test_assemble_run_guard.py`:
1. Fake child (exact 0.17.0 banner bytes, then never exits, holding 2 grandchildren), grace=3s,
   timeout=60s: runner returns SUCCESS; module wall time < 25s (marker→reclaim ≤ 3+10s, plus
   slack); after return, `os.killpg(child_pgid, 0)` raises `ProcessLookupError` (group empty —
   no orphans). 3 trials, all pass.
2. Real-tool companion: `run([great-docs, build, --versions v0.0.1,v0.0.2,dev], done_marker=True,
   grace=30, timeout=900)` against the real checkout — exits via E1 in ≈ the build's own time
   (measured baseline 2m20s; accept < 6m), returns success, and the reclamation log is ABSENT
   (proves the normal path pays no grace). `great-docs/_site` populated.
3. Fake fail-banner child: `SystemExit` whose message names the command.

**RED control — mechanism disabled (G3 procedure, review-time).** Revert only the mechanism
(pass `done_marker=False` at the call site / or stub the marker regexes empty), keep the harness;
rerun test 1 with timeout=20s: the runner must NOT return quickly — elapsed ≥ 18s, outcome is
the named-timeout `SystemExit`, and ≥ 1 grandchild is still alive at return (today's orphan-leak
shape). That red-then-green pair is the proof the effect is the mechanism, not luck.

**Field rule (post-merge observation, pre-committed).** Over the SDK repo's next 20 Build Docs
runs (pushes + PRs): PASS = zero runs exhibiting the #476 signature — banner as the last
assemble-step line with the step not ending within 120s of it. KILL = ≥ 1 occurrence (reopen
#476; the likely cause is marker drift or a new hang class — E4's log names which). UNDERPOWERED
(fail the measurement, not the fix) = the window closes with < 10 runs that completed an
in-process multi-version build — then the field rule rolls forward unchanged rather than
declaring victory. **Reopen trigger independent of the field rule:** any future bump of the
great-docs pin in `docs.yml` re-opens the marker contract (re-derive the banner regexes and the
post-banner tail — R1/R2) exactly as the markup workarounds move with that pin.

## 9. Top risks (each with its falsifier)

- **R1 Marker drift** — a future great-docs changes the banner text → E2 never fires, behavior
  degrades to today's bounded wait (E4). Falsifier: test (d) pins the regexes against the literal
  0.17.0 banner; the workflow's pin comment already couples workarounds to the version.
- **R2 Real work after the banner in a future version** — grace would truncate it. Today the
  banner is provably `build()`'s final statement (core.py:16391/16507); falsifier: re-read the
  tail on any pin bump (the §8 reopen trigger).
- **R3 False-positive marker** — build output quoting the banner strings. Mitigated by the
  two-string conjunction inside one box; falsifier: grep the built tree's echoed output for both
  literals — if both ever co-occur in normal progress output, tighten to the boxed line form.
- **R4 setsid changes child behavior** (signal handling, tty detection). CI is already non-tty
  and non-interactive; falsifier: acceptance run 2 (the real tool through the guarded runner).
- **R5 The hang class moves pre-banner** — a mid-build wedge is untouched by this increment and
  still rides E4's 900s. Scope boundary, stated; the E4 log names the phase, so a pre-banner
  recurrence is diagnosable, not invisible.
- **R6 SIGTERM ignored by a grandchild** — escalation to SIGKILL after 10s; if even SIGKILL
  leaves group members (unreapable zombie ≠ alive — `killpg(0)` counts only the living), the
  E2/E4 endings report it loudly instead of hanging.

## 10. Issue disposition

- **#476**: closed by this increment — the step ends at work-done (E2) instead of at a bound.
- **#475**: its already-landed bound is demoted to backstop (E4) with the group-reclaim
  improvement; closable with this increment, reopen trigger as §8.
- **Gateway twin**: follow-up issue (deferral 1) — exposure quantified in §5.

---

## Addendum 2026-10-19 (fold wave) — the refute lanes' corrections, folded

The body above is the frozen design record; this addendum carries what the two refute
lanes established against the increment as first built, and what changed. The §8
acceptance rule's field rule and reopen trigger are unchanged.

- **F1 (HIGH, lane A) — the single-marker premise was wrong for `--from-repo`.** §3's
  "the completion banner is the tool's own last act" is true only for the in-process
  site. In a `--from-repo` run the watched banner is the INNER build's, and the outer
  process still has the copytree into `--output-dir`, its own "Site built successfully"
  line, and the temp-clone rmtree ahead of it (great_docs/core.py:16717/16734/16736/
  16739-16742). A grace-sized reclaim there kills a healthy build mid-copy and returns
  success over truncated output (lane A reproduced at 1337/3000 files with index.html
  present — `bucket_source()` passes, `verify_tree()` is existence-only). Fixed with
  per-call-site markers: `done_marker="inproc"` keeps the banner-box conjunction;
  `done_marker="isolated"` watches only the outer "Site built successfully" line. The
  inner banner AND the inner FAIL line are ignored on the isolated kind (an inner
  failure exits non-zero → E1, or hangs → E4 — both loud).
- **F2 (HIGH, lane A) — the suite reds windows-latest deterministically.** CPython on
  Windows ignores `start_new_session`, `os.getpgrp` does not exist, and 4 of 6 arms
  red on every run. Fixed: `@POSIX_ONLY` skipif (the repo's test_lifecycle convention)
  on the process-group arms; `_reclaim_group` refuses loudly on win32 with the
  platform named. Production exposure nil (docs.yml is ubuntu-only).
- **F3 (MED, lane A) — "FAIL outranks OK" was false as implemented.** Both deadlines
  were sight-time + grace, so the earlier-sighted marker won; lane A captured OK at
  +0.05s, FAIL at +2.5s, grace 6.0 → success with the FAIL never gated. Fixed: a
  sighted FAIL prohibits E2 outright; the loop waits out the fail grace and ends E3.
- **F4 (MED, lane B) — the tripwire was tautological and the FAIL literal wrong.**
  Both sides of the §5.2(d) check were in-repo constants, so a pin bump moved neither
  (demonstrated: both sides doctored together → the old arm stays green); the FAIL
  literal `[FAIL] Build failed — …` is a shape the tool never emits (real non-tty
  form, `_build_log.py:802`: `[FAIL] Build failed at Step {n} - {title}`). Fixed:
  byte-capture fixtures of two real 0.17.0 runs (in-process banner; the --from-repo
  tail) under `tests/fixtures/`, a fixture-driven arm, the real FAIL shape, and the
  docs.yml pin comment now names the markers and fixtures as pin-coupled.
- **F5 (LOW/NIT, lane B).** (a) `RECLAIM_PROBE_DRAIN_S=2.0` now documents lane B's
  measurement (macOS zombie window 1–4ms over 8 trials) and the ~500x margin; the
  test drains with the same constant. (b) `_reclaim_group` reaps the leader at both
  bail-outs — on macOS a zombie leader answers `os.getpgid` with ESRCH, so the entry
  guard used to return silently, stranding our own zombie (whose group then probes
  EPERM), and the sibling race (leader dying between getpgid and killpg) logged a
  false survivor warning. Committed arm pins the strand; the micro-race itself is not
  deterministically constructible and rides lane B's capture.
- **Out of fold (accepted residuals, noted):** a head-only hang rides E4 to the 900s
  bound (scope boundary, unchanged); the banner conjunction is defeatable by any
  stream carrying both substrings in order — no 0.17.0 producer exists beyond F1's
  inner banner, which the per-call-site kinds now ignore; `run(done_marker=…,
  timeout=None)` can never end — both call sites pass `GREAT_DOCS_TIMEOUT`, and the
  docstring says so.
- **Verification gotchas this wave:** on macOS a signal-0 probe over freshly orphaned
  zombies answers EPERM, not ESRCH (already folded pre-wave), `os.getpgid` on a zombie
  raises ESRCH, and a same-length sabotage restored within the same wall-clock second
  keeps a stale `.pyc` (second-resolution mtime + size validation) — clear `__pycache__`
  after any RED-neutralization that rewrites source in place.

---

## Addendum 2026-10-19 (second) — the reclaim bound is a property, not a number

PR #181's ubuntu leg (run 39209775675) reddened `test_fail_banner_hang_…` at its
"group empty" assertion under `-n auto` load, while the same arm passed on macOS,
Windows and locally. The lead's diagnosis (the drain constant is an idle-machine
measurement used as a wall-clock bound) is correct — and the probe found three
sibling defects under it, so the fix is the contract, not the number:

1. **The emptiness probe guessed from one sample.** `killpg(0)` success was read as
   "alive, done" — but on Linux a reap-pending zombie answers success exactly like a
   live member (on macOS it answers EPERM). The EPERM drain only ever covered the
   macOS shape. Now both outcomes mean members-may-remain: reclamation WAITS FOR THE
   PROPERTY (group empty — no members, not even zombies) and returns the moment it
   holds.
2. **Escalation was keyed to the leader, not the group.** The SIGTERM→SIGKILL ladder
   broke on `proc.wait()` — the leader's exit — so a SIGTERM-ignoring member was
   never SIGKILLed at all. The RED captured a WARNING claiming "still has member
   processes after SIGKILL" when no SIGKILL had been sent — the log named a
   mechanism event that did not happen. Now SIGTERM gets `RECLAIM_TERM_TO_KILL_S` of
   politeness, then the whole group gets SIGKILL, then the wait.
3. **The arm asserted an instant, not a property.** `_group_is_empty` sampled once
   (draining only the macOS window); its contract is "the group is empty AFTERWARDS".
   It now polls to a bounded deadline — the same wait-for-ESRCH semantics as the
   mechanism.
4. **pgid by construction.** `start_new_session=True` makes the child its own group
   leader, so the group is its pid; the `getpgid` probe is gone (on macOS it answers
   ESRCH for a zombie leader and would strand the grandchildren), and the leader is
   reaped inside the wait loop (`proc.poll()`).
5. **The constant is a disclosure ceiling.** `RECLAIM_PROBE_DRAIN_S = 2.0` (lane B's
   1–4ms idle-macOS measurement) is retired; `RECLAIM_GROUP_DEADLINE_S = 30.0` bounds
   how long a group may outlive the reclaim signals before the R6 warning names what
   remains. SIGKILL delivery is immediate; the residual is orphan reap latency
   (init/launchd scheduling — unbounded in principle), so no finite number can be an
   accuracy bound — only a ceiling on waiting, and the wait returns as soon as the
   property holds. The warning text now names "the reclaim signals" and the ceiling,
   matching the mechanism exactly.

RED: `test_reclaim_kills_a_sigterm_ignoring_grandchild` (a grandchild with
`SIGTERM` ignored — the deterministic extreme of the CI load shape) against the
pre-fix code: `AssertionError: a SIGTERM-ignoring grandchild survived reclamation`,
with the captured output showing the false "after SIGKILL" warning. GREEN: 12/12.
