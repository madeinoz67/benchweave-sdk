# The `sdk` job's timeout ceiling — measured, ruled, and what it does not fix

Date: 2026-11-18. Branch `fix/ci-windows-budget`. Gateway tracker issue: see the
PR body (filed on the gateway tracker per the single-issue-stream rule).

## Why this record exists

`madeinoz67/benchweave-sdk` main went red on 2026-11-09. The `ci` workflow's
`sdk (windows-latest)` job was cancelled at its own `timeout-minutes` ceiling,
mid `Installed-wheel smoke`, with no test verdict. This is a recurrence of
gateway issue #402, which was closed on 2026-10-05 with an owner redirect that
**rejected** the same ceiling bump and took `-n auto` instead.

Because the proposed change reverses a recorded owner decision, the reasoning is
written down before the code lands rather than left in a commit message.

## The measurement

`sdk (windows-latest)` job wall-clock, 89 consecutive successful `ci.yml` runs,
2026-10-26 .. 2026-11-13. Each duration read off its own Actions run page via
the jobs API (`started_at` -> `completed_at`); the denominator is the 89 runs
whose windows job concluded `success`, out of 100 `ci.yml` runs sampled.

| statistic | value |
|---|---|
| min | 7m15s |
| p25 | 10m50s |
| median | 12m22s |
| p75 | 13m21s |
| p90 | 14m30s |
| max | 14m59s |

33 of those 89 runs finished within two minutes of the 15m ceiling.

Two runs of the *same tree*, 26 minutes apart on 2026-11-09: PR #257's own
windows job passed in 9m14s; the merge commit's was killed at 15m11s. Step
timings from both logs isolate the swing to one step — the parallel pytest leg
took 8m37s in the passing run and 14m20s in the killed one, while checkout,
`uv sync`, `ruff`/`mypy` and the trailing steps were ~1m in both.

That is a 1.67x spread on identical work, which is runner throughput variance
on shared hosted runners, not a test that fails.

## What the timeout is for

`timeout-minutes` on this job exists to catch a hang, so a wedged run fails
loudly instead of sitting silent against the runner's 6h default. It is not a
performance budget — nothing in the workflow gates on wall-clock.

A hang detector has to sit above the healthy maximum with room for the observed
spread. At 15m it sits **one second** above the observed healthy maximum
(14m59s) and inside the spread for a third of all runs. It is not detecting
hangs. It is deciding which healthy push goes red.

## The ruling

**Ruling: `timeout-minutes` on the `sdk` job moves 15 -> 25.**

*Why.* The 15m value does not serve its stated purpose. The ceiling is a hang
detector; at 15m it is a lottery whose outcome is decided by runner throughput.
25m holds the entire observed spread (max 14m59s) and still cuts a hang at under
half the 6h runner default.

*What it costs if wrong.* If the Windows suite doubles again, 25m hides that
until a run exceeds 25m. That risk is not carried by the ceiling — it is carried
by the suite-cost track below, where the number is tracked as a number. The
owner's 2026-10-05 concern was that headroom hides cost; the answer to that is
that cost visibility now lives in a measurement and a tracker issue rather than
in a red job, and the measurement is reproduced in the workflow comment where
the ceiling is set.

*What this does NOT do.* It does not make the Windows lane cheaper. Unworked,
the same wall returns at 25m.

## Alternatives considered

1. **Leave the ceiling at 15m and cut the suite cost.** This is #402's literal
   position and it is not wrong about the diagnosis. It is not sufficient as the
   *only* response here: main is red now, and the cost reduction that would give
   this lane real headroom is a multi-slice project, not a fix. Taking it alone
   leaves main red until the project lands.

2. **Re-run the killed job and say no more.** The median is 12m22s against a 15m
   ceiling. A re-run passing would be luck, and the next merge rolls the same
   die. Rejected.

3. **Extract the heavy modules to a non-parallel leg, the design record section
   13 `loop` pattern.** Rejected for now on evidence: `uv build` of this
   repository's wheel measures 0.59s locally, so the per-worker wheel
   duplication that section 13 names is not the dominant cost here. The pytest
   leg is 87-95 percent of the job (4m17s ubuntu-latest, 8m37s-14m20s
   windows-latest) over 2608 test definitions of subprocess-bound work. Cutting
   that needs the per-test duration profile first, not a guessed marker.

4. **Per-OS ceiling (`matrix.os == 'windows-latest' && 25 || 15`).** Mechanically
   equivalent, more machinery. ubuntu-latest (5m16s) and macos-latest (8m18s)
   keep 4.8x and 3.0x headroom at a flat 25m, so the uniform value is correct on
   the edge cases and is one number to reason about.

## The debt this record leaves open

The Windows suite cost is real and is its own track, per #402's own
discriminator ("a second red at the ceiling means the Windows suite cost is real
and becomes its own issue"). Its shape, so far measured rather than assumed:

* `-n auto` landed this leg at 5m37s on 2026-10-05. It measures 12m22s median
  now. The parallelisation win has been consumed by suite growth.
* The work is subprocess-bound (scaffold render, CLI invocation, git plumbing).
  `-n auto` cannot shorten it, and xdist multiplies any session-scoped setup per
  worker — section 13's mechanism.
* A per-test duration profile is the next measurement, and the fix should follow
  it rather than precede it.

## What this record does not claim

* It does not claim the suite is fast enough. It claims the ceiling was not the
  right instrument for that question.
* It does not claim the 1.67x spread is fully explained. It is attributed to
  hosted-runner throughput variance on the strength of the same-tree/same-step
  comparison above; no runner telemetry was collected to prove the mechanism.
* It does not claim the numbers transfer to any other lane. Every figure is
  `sdk (windows-latest)` on this repository.
