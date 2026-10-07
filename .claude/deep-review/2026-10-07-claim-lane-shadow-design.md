# Shadow-mode claim-conformance lane (design record)

Date: 2026-10-07
Status: design pre-committed before any lane code was written.
Tier: **Tier-2** — repo tooling (`scripts/` + `tests/`) only. No control-path
bytes, no standards bytes, no packaging changes. The lane judges; it never
gates. Shadow semantics are structural (see the shadow law), not a policy
statement that could later be flipped by editing a threshold.

## 1. The problem

The SDK's published prose (README, `user_guide/plugin-sdk.qmd`) asserts
behavior. Tests pin much of it, but nothing connects the two at the sentence
level: a doc sentence can drift from the code while every test stays green,
because no test is bound to the sentence, and no review re-reads the sentence
against executed behavior.

Judging doc claims is also a place where the obvious approach is measurably
wrong. That was tested before this design was written.

## 2. The evidence base (the experiment)

A TypeSafe System One experiment (model `jev-1.13.0`) ran on this repository's
real claims, with a 12-pair answer key built from this week's adversarial-review
ground truth:

- **v1 — claim + code excerpt:** 42% accuracy on the 12-pair key. Worse than
  chance. The model's own decidable flag correctly marked the low-decidability
  misses — the input shape, not the model, was the defect.
- **v2 — claim + executed behavioral trace** (neutral observation sentences
  from probes): **12/12**. False claims scored 0.02–0.04; true claims scored
  0.74–0.98; zero overlap between the bands.
- **Control A — mismatched pairing** (a true claim judged against a false
  trace): 0.03/0.03. Judgment anchors on the evidence, not on the claim's
  plausibility.
- **Control B — ambiguity** (a trace that does not settle the claim): one
  mid-band 0.57 result. A two-threshold DEAD BAND is required; a single cut
  would launder that case into a confident verdict.

**The lane's law, from that evidence:** claims are judged against executed
traces, never code excerpts. Every design decision below follows from it.

## 3. The mechanism

Four pieces, one concern each:

1. **The manifest** (`CLAIMS` in `scripts/claim_lane.py`): rows of
   `{id, claim, probe}`. `claim` is a doc sentence quoted verbatim from
   current `main`'s README or `user_guide/plugin-sdk.qmd`. `probe` names a
   pytest node id in `tests/test_claim_probes.py`. The manifest is data, not
   configuration — the seed corpus is part of this increment.
2. **The probes** (`tests/test_claim_probes.py`): one pytest cell per row,
   marker `claim_probe`, exercising the REAL behavior over the existing test
   doubles (loopback ports, scaffolded plugin projects, temp capture roots).
   Each cell emits a **trace artifact**: a JSON file
   `{claim_id, observations: [...]}` where every observation is a neutral
   past-tense sentence describing what was observed. Observations never state
   whether the behavior matches the claim — that is the judge's job, and
   verdict words inside the trace would be leakage (the experiment's neutral
   trace shape is what produced the 0.02–0.04 / 0.74–0.98 separation).
3. **The judge client**: a stdlib-urllib function `(state, questions) ->
   answers` against `POST https://api.typesafe.ai/v1/systemone`, Bearer
   authorization read from the `TYPESAFE_API_KEY` environment variable,
   model `jev-latest`, 429/529 exponential backoff, 60 s timeout. The client
   is injectable (a parameter defaulting to the real one) so the runner's
   tests are offline and deterministic. The key is read from the environment
   only — never a default, never logged, never written into any artifact.
4. **The runner** (`python scripts/claim_lane.py`): validate manifest → run
   the probe cells (`pytest -m claim_probe`, artifact root wired) → judge
   each (claim, trace) pair with the conformance question → classify →
   write `.claim-lane/report.json` (per-row `claim_id, claim, verdict, noul,
   model, tokens`, plus totals) and a human summary to stdout.

### The dead band

`classify(noul)`: `>= 0.70` → `conforming`; `<= 0.30` → `non_conforming`;
between → `insufficient_evidence`. The 0.57 ambiguity control is what the
middle band exists to catch: a trace that does not settle its claim reports
as insufficient evidence, never as a confident verdict on either side.

### The shadow law

The runner's exit code is 0 for ANY verdict distribution, including all
`non_conforming`. Nonzero exit is reserved for hard setup errors: a malformed
manifest, or probe failures (no trace → nothing to judge — the one case where
continuing would fabricate evidence). A missing `TYPESAFE_API_KEY` runs the
probes, writes the report with a skip notice, and exits 0. This is pinned by
test, not by convention (AR-6).

## 4. Seed corpus (10 rows)

All sentences verbatim from current `main` docs; all probeable against real
behavior already pinned by existing tests:

| id | source | sentence (abbreviated here; full text in the manifest) |
|----|--------|--------------------------------------------------------|
| `scan-hint-filter` | README, server extra | "Discovery opens candidate ports and asks each for its identity, filtered by the descriptor's declared USB hint ... where declared." |
| `scan-unparseable-hint` | README, server extra | "An unparseable declared hint refuses the scan and names the value." |
| `capture-abort-id-reuse` | README, server extra | "The abort removes the event directory, so you can reuse the capture id in the same process." |
| `capture-crash-reserved` | README, server extra | "A capture left behind by a crash keeps its id reserved." |
| `capture-reservation-crossing` | README, server extra | "The writer refuses an append that crosses the reservation at each append." |
| `negotiated-bauds-validation` | plugin-sdk.qmd §reconfigure | "A malformed value stops the build with a clear error." (with its preceding sentence for context) |
| `negotiated-switch-undeclared` | plugin-sdk.qmd §reconfigure | "Without the declaration, every switch refuses." |
| `capture-empty-refused` | plugin-sdk.qmd §capture | "The writer refuses a capture that appended nothing." |
| `capture-waveform-length` | plugin-sdk.qmd §capture | "It also refuses a `waveform_f64le` capture whose byte length is not `sample_count` × 8, as the gateway refuses that too." |
| `capture-env-dir-empty` | plugin-sdk.qmd §capture | "The writer also refuses a `BENCHWEAVE_CAPTURE_DIR` that is set but empty or whitespace-only." |

## 5. Acceptance rules (pre-committed)

- **AR-1** dead-band edges unit-pinned: 0.30 → `non_conforming`, 0.31 →
  `insufficient_evidence`, 0.69 → `insufficient_evidence`, 0.70 →
  `conforming`.
- **AR-2** manifest rows validated: unique ids, non-empty claims, every
  named probe exists in the probe file.
- **AR-3** trace artifacts schema-validated: `claim_id` present, ≥ 1
  observation, neutral tense, no verdict leakage (a deliberately bad
  observation set is rejected by the schema test).
- **AR-4** fake-client runner tests: conforming / non-conforming /
  insufficient rows each produced; report row shape pinned.
- **AR-5** missing key ⇒ skip report, exit 0.
- **AR-6** SHADOW: a `non_conforming` verdict never fails the run (pinned by
  test — the offline RED control doubles as this pin).
- **AR-7** the key never appears in any artifact, log, or commit: a test
  greps the report and the artifact tree for the environment value.
- **AR-8** seed corpus ≥ 8 real main-tree claims; all probes green; the
  offline RED control (a deliberately contradicting trace fed through the
  fake client) reports `non_conforming`.

## 6. Deferrals (with homes)

- **CI wiring + where reports post** — needs the shadow-run cadence decided
  first; home: a follow-up gateway issue once cadence is ruled.
- **Dead-band tuning on a bigger labeled corpus** — the 0.30/0.70 cuts come
  from one 12-pair session; home: this design record's §7 caveats, revisited
  when a labeled corpus of ≥ 50 pairs exists.
- **The gateway-repo port** — the lane is SDK-local by design; home: gateway
  tracker when the SDK lane has produced shadow data.
- **The auto-label Choice tool** — not needed while the corpus is small;
  home: same follow-up as dead-band tuning.
- **A gating (non-shadow) variant** — explicitly gated on the principal's
  ruling after shadow data accrues; no code is written toward it in this
  increment.

## 7. Standing caveats

These are why the lane ships in shadow mode:

- The calibration set is **12 pairs**, built from one week's adversarial
  ground truth.
- The judge evidence is from **one model** (`jev-1.13.0`; the lane calls
  `jev-latest`).
- The thresholds (0.30 / 0.70) derive from **one session's data**.

Any of these could move the bands. Shadow mode makes that harmless: the
report is data, not a verdict, until a human reads it.

## 8. Top risks

- **Verdict leakage into traces** — an observation that says "as documented"
  would hand the judge the answer. Mitigated structurally: the schema test
  rejects observation sets carrying verdict vocabulary (AR-3).
- **Key leakage into artifacts** — the runner handles the key only inside
  the client function; AR-7 greps every artifact it produced.
- **The lane quietly becoming a gate** — someone wires the exit code to CI
  and shadow dies. Mitigated: the exit code is structurally 0 for verdicts
  (AR-6), and the README section states the shadow semantics; a future
  gating variant is a separate, ruled increment.
- **Corpus rot** — doc sentences move and the manifest quotes drift stale.
  Mitigated: rows are quoted verbatim; a moved sentence fails the manifest's
  own review the next time a human edits it. (A doc-quote linter is not
  built here; noted as part of the CI-wiring deferral's home.)

## 9. Addendum — fold 1 (2026-10-07: refuted, then folded)

The refute wave after the first live runs executed three MEDIUMs and two
rides against this design as shipped. This addendum appends the honest
reframing each one forced; the sections above are frozen bytes and stand
as written (the pre-refute record).

**F3 — AR-3's claim, reframed.** The vocabulary check is
ACCIDENTAL-LEAK PROTECTION, not a gate: the refuter admitted 13 of 13
paraphrase bypasses ("as the README specifies", "konform", "符合",
"c0nforms", "did not differ", numeric leaks), and live, one leading
sentence on a false trace bought +0.31 noul and flipped a verdict off
non_conforming. The load-bearing refusal is now the STRUCTURAL gate
added in the fold: every observation must be a past-tense event sentence
— it opens with an event (a leading-token ban on conclusion/concession
openers), carries no causal marker (because/therefore/which-means/
proves-that class) and no evaluation marker (as-expected, in-line-with,
negated comparatives, correct/expected/should-have), and contains a
past-tense event verb (a regular -ed form or a closed irregular set).
Matching normalizes NFKC + casefold + a leet digit fold, and the verdict
vocabulary gained translation companions. Measured false-positive rate
against the shipped corpus: 0 of 31 observations (pinned by the
all-ten-probe schema cell). The judge-side anchoring instruction ("rest
the answer only on observed_behavior") is the demonstrated backstop —
on led false evidence it held 0.34, not 0.9. Residual, disclosed: the
gate is heuristic; a paraphrase that reads as a past-tense event while
asserting the verdict can still pass it, which is why the anchoring
backstop and the shadow posture remain load-bearing.

**F1 — stale evidence.** The traces directory is cleared at run start:
a skipped or failed probe can no longer have its prior-run artifact
judged as fresh evidence (the refuter executed exactly that laundering).

**F2 — the exit contract.** The documented contract (0 for verdicts, 2
for setup errors) admits no third value: response bodies parse
defensively (an HTML 502 behind a proxy is `(502, None)`, not a raw
JSONDecodeError traceback), every report/directory failure path is
guarded to exit 2, and verdicts already earned are preserved — printed
in the summary, and carried in a partial report whose `error` field
names the failure — before any failure returns.

**F5 — untrusted bodies.** Error text never interpolates a raw response
body: detail passes through a redactor (bearer-shaped and token-shaped
runs stripped) and a 120-character truncation. The refuter executed a
401 body echoing the Authorization header onto stderr through
`{payload!r}`; that path is closed and pinned.

**F4 — the lane's own phrasing (ride).** The reservation probe's fourth
observation was reworded from a causal clause ("was refused because its
100 bytes would carry the staged total past...") to the cold-numbers
past-tense form; the refuter measured the causal phrasing worth ~0.12
noul of leading on top of an already-conforming trace.

**Rides from the refuter's nulls chunk (same fold commit).**
(a) The lane module now rides CI's type gate: `[tool.mypy] files` gained
`scripts/claim_lane.py` (per-file — the older scripts predate strict
typing and stay outside), and CI's lint step is now bare `uv run mypy`
(config-driven), because the explicit `mypy src` argument silently
overrode the file list the config declares.
(b) `classify` refuses to mint verdicts from out-of-domain scores: -1
used to read as confidently non-conforming and 1.5 as confidently
conforming; every score outside [0, 1] (NaN included) now REFUSES with
a `ClaimLaneError` naming the violation, which routes through the F2
machinery as an infrastructure failure — partial report, error field
naming it, exit 2. Resolution history, recorded because both shapes
were built: a dead-band clamp (out-of-domain lands in
`insufficient_evidence`) was tried first and ruled the weaker call —
it launders a broken judge into a soft verdict row instead of
surfacing as the named hard error it is. The skip pseudo-verdict is
now counted in totals (`skipped`), never silently unbucketed.
(c) scan-hint-filter's fourth observation was reworded to what the
cell's assert pins ("both identified as example_device") — the prior
"identity fields the descriptor declares" phrasing claimed more than
the assertion proved, per ROW 3's cold-phrasing law.
