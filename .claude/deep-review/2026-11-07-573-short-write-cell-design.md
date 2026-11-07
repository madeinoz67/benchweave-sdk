# Gateway issue #573 — the short-write rehearsal cell: DON'T-BUILD the corpus arm

**Date:** 2026-11-07
**Scope:** gateway issue #573, "mock transport: let a scripted corpus rehearse the
short-write refusal". The filed scope is a third scripted-corpus failure cell — a
sibling of the replay journal's `recorded_failure: "timeout"` — whose acceptance reads
"The cell raises the same refusal class as the serial path. Fixed means one
scripted-corpus test exercises an adapter's recovery against that refusal." This
record settles whether to build it, and specifies the one residual the issue's own
acceptance leaves unmet.

**Verdict up front:** **DON'T-BUILD the corpus arm.** The issue's premise — "the mock
has no cell that produces the same refusal" — was false on `main` four hours before the
issue was filed: `ScriptedFtdiDriver.short_writes` (commit `4f67d37`, landed 2026-10-28
06:10Z) is a shipped mock cell that drives the production short-write refusal
byte-identically, not merely class-identically. What a third `recorded_failure` arm
would buy is message fidelity in a declarative document, and no consumer in either
repository branches on that message — the adapter-visible contract is the exception
CLASS (§1). The cost is a widened closed set, changed published refusal text on two
lanes, and a semantic reinterpretation of a recorded field (§2). The only genuinely
unmet clause is the issue's "Fixed means" test, and that is a ~20-line test-only
sibling of an existing pin (§3) — no production bytes.

**Triage:** PUBLIC. No person, client, bench, serial, commercial term, or one-install
operational specifics below; file:line citations and public issue numbers only.

---

## 0. Grounding — what was verified, against which bytes

Worktree at `1d26497` (= `origin/main` at design time). All citations are from this
tree; the issue's own anchors were re-located, and both are stale:

- The issue anchors the refusal at `serial.py:753-754` — it now sits at
  `src/benchweave_sdk_server/serial.py:866-869`
  (`f"{self._write_label} write reported {sent} of {len(data)} bytes"`, raised as
  `ConnectionError`), inside the write stage of `transfer` (`serial.py:854-869`),
  after the dispatch-marker check and before any receive. `_write_label` is
  `"serial"` (`serial.py:775`) on the serial transport and `"ftdi"`
  (`ftdi.py:1117`) on the ftdi transport — one shared refusal, two labels.
- The issue anchors the mock's exact-match at `transport.py:306-327` (`_send_frame`) —
  dead; the exact-match now lives in `ScriptedFtdiDriver.write_data`
  (`ftdi.py:967-986`) and `ReplayHost._match_send` (`replay.py:1161`).

The issue's timeline, verified from git (this is the decisive evidence):

| Event | When (UTC) | Evidence |
|---|---|---|
| Issue's anchor commit `39043cc` | 2026-10-26 10:41 | `git log -1 39043cc` — merge of #220 |
| `short_writes` + its pin land (`4f67d37`, #568) | **2026-10-28 06:10** | `git log -1 4f67d37`; `git merge-base --is-ancestor 39043cc 4f67d37` → the anchor does NOT contain `short_writes` |
| Issue #573 filed | **2026-10-28 10:03** | `createdAt` from the tracker |

The filer examined a main state two days stale; the rehearsal cell they asked for had
landed on main four hours before the issue existed. `4f67d37` also landed the pinning
test `tests/server/test_ftdi.py:1475-1500`
(`test_the_short_write_refusal_names_the_ftdi_transport`), which asserts
`ConnectionError, match="ftdi write reported 4 of 8"` through the real services layer.

The four load-bearing pins were run on this tree (raw tail, this author's run):

```
$ uv run pytest tests/server/test_ftdi.py::test_the_short_write_refusal_names_the_ftdi_transport \
    tests/server/test_ftdi.py::test_metric_c7_midconversation_fault_maps_not_ready_no_retry \
    tests/server/test_mock_provider.py::test_recorded_failure_scripts_the_ladders_outcome \
    tests/server/test_replay.py::test_recorded_failure_timeout_replays_the_timeout -q
....                                                                     [100%]
4 passed in 0.52s
```

Static gates were not run: this branch changes no production bytes (the record is the
first commit; the proposed residual is a test). Say-so recorded per the honest-negative
rule.

## 1. The settle-question — what a third arm would buy that `"connection"` does not

**Emission (production).** The refusal fires at the write stage of
`WriterBackedCaptureServices.transfer` (`serial.py:854-869`) for every send-bearing
kind, with `sent is not None and sent != len(data)` as the trigger (a `None` count is
pyserial's no-count ports — the guide listing at `user_guide/plugin-sdk.qmd:746-769`
teaches this, refusal at 765-766).

**Consumption — every consumer branches on the class.** The adapter-visible contract of
a transport failure is the exception class, at every layer:

- The seam maps `except (TimeoutError, ConnectionError)` → `not_ready`
  (`seam.py:781-784`, `seam.py:4096-4099`); the message rides verbatim into the
  diagnostic string and nothing matches on it.
- The fault latch keys on the fault, not the message (`test_ftdi.py:1468`
  "previously faulted"; the recorder's latch at `ftdi.py:1833`).
- The gateway checkout has ZERO code consumers of `recorded_failure` and none of
  "write reported" (git grep over the gateway tree; the only hit is a design record's
  prose). The closed set is SDK-side only.

**The two scripted postures that exist today:**

1. **Declarative, class-parity:** `recorded_failure: "connection"` on a
   `stream_exchange` row raises `ConnectionError` — the same class the issue's
   acceptance asks for — from both scripted surfaces: the replay host
   (`replay.py:1167-1172`) and the mock provider corpus compile through MockHost's
   Exception slot (`session.py:588-593`). Different message ("the recorded exchange
   lost its connection after the send"), different stage claim (post-send), identical
   adapter-visible outcome: `not_ready`, latched, no retry.
2. **Imperative, byte-identical:** `ScriptedFtdiDriver.short_writes`
   (`ftdi.py:815`, branch at `ftdi.py:982-986` — "the services layer's own
   short-count refusal judges it") is a SHIPPED mock cell — the class docstring says
   "mock parity rides in the slice as a SHIPPED component, not a test helper" — whose
   script rows ARE the #564 journal row shape. It does not re-stage the refusal in a
   mock layer; it produces the production refusal itself, message included, and
   `test_ftdi.py:1475` pins exactly that.

**Therefore:** the only thing a third `recorded_failure` arm adds over (1) is the
message text, and over (2) is declarative spelling. Message fidelity has no consumer
(§1, consumption), and declarative spelling has no behavioral delta. The filed scope
buys nothing an adapter can observe. The row should close on the evidence.

## 2. The refused option — every reader of the closed set, and the refusal-text delta

Recorded for the re-opener: this is what widening `("timeout", "connection")`
(`replay.py:354`) actually costs. Every reader:

| Reader | Site | What widening moves |
|---|---|---|
| The set + its member-naming refusal | `replay.py:353-359` (shared validator) | refusal text names both members — a third member changes the published string on BOTH lanes below |
| Provider-dialect compile (same validator) | `session.py:548` (`standalone_vectors_row_shape`) | same message text, second lane |
| Receive-row consumption | `replay.py:1128-1141` | new arm needs a branch + its own message |
| Exchange-row consumption | `replay.py:1167-1176` | same |
| Mock compile Exception slot | `session.py:582-599` | same |
| Send-row refusal ("applies to receive rows, not sends") | `replay.py:532-536` | a WRITE-stage arm's natural row is `stream_send`; admitting it breaks this rule, or the arm rides receive-bearing rows where its stage claim is wrong — either the rule or the arm is dishonest |
| Provider-row refusal | `replay.py:367-371` | unchanged, restated for completeness |
| Live recorder emitters | `ftdi.py:1783`, `ftdi.py:1797` | the recorder can NEVER emit a short write — `ftdi.py:1820-1834`: "a failed, short or never-started send records nothing (it never went out whole)" |
| Docstrings | `replay.py:38-44`, `session.py:496-503`, `ftdi.py:1648-1654`, `ftdi.py:1771-1775` | all name the closed family |
| Tests | `test_replay.py:593`, `:1095-1106`; `test_ftdi.py:1015-1017`, `:1359-1361`; `test_mock_provider.py:255-301`, `:304-320` | the family's pins; none pins the member-naming string itself (verified: no test matches "is not a recorded outcome"), so the text change would land silently |

Differential matrix (which existing inputs change, and in which direction):

| Input | Today | With a third arm | Delta |
|---|---|---|---|
| `"timeout"` receive/exchange row | loads; serves `TimeoutError` | loads; serves `TimeoutError` | byte-identical |
| `"connection"` receive/exchange row | loads; serves `ConnectionError` | loads | byte-identical |
| `"connection"` on a `stream_send` row | refuses (send-row rule) | must still refuse, or the rule and its message change | rule text moves |
| unknown value e.g. `"weird"` | refuses `'…is not a recorded outcome this format carries ("timeout" or "connection")'` | refuses with a three-member list | **published refusal text changes on two lanes, unpinned by any test** |
| a `stream_exchange` row with the new arm | refuses (not a member) | loads; the row's `data` field changes meaning from "bytes that went out whole" (the recorder only emits a connection row when `stream.completed`, `ftdi.py:1829-1832`) to "bytes attempted" | **one key, two meanings, keyed on a sibling field** |

The last two rows are the honesty contradiction that kills the option on its own: the
key is named `recorded_failure` and its module contract is "the recorded outcome stays
the recorded outcome" (`replay.py:38-44`). No recording can ever produce this arm; it
would be an authored-only outcome inside a format whose entire value is that journals
are frozen evidence of what the device did. The refused option is also **Tier 3** by
the review rubric ("changes a refusal prefix or adds a refusal path" — the
member-naming refusal and the send-row rule both move).

## 3. The residual — the issue's "Fixed means" clause, as a test-only micro-slice

What exists: the services-level pin (`test_ftdi.py:1475-1500`), the adapter-recovery
SHAPE for a scripted fault — C7, `test_metric_c7_midconversation_fault_maps_not_ready_
no_retry` (`test_ftdi.py:764-789`), which wires the full seam, flips
`driver.fault_writes`, and asserts `code == "not_ready"` with `write_calls +1` (one
bounded attempt, no host retry) — and the mock latch arm
(`test_mock_provider.py:255-301`). What does NOT exist: that recovery shape driven
against the short-write refusal specifically. That is the only unmet clause of the
issue's own acceptance, and it needs no production change.

**The slice:** ONE test beside C7 in `tests/server/test_ftdi.py`, identical wiring,
with `driver.short_writes = True` instead of `fault_writes`, over a send whose frame
exceeds 4 bytes (the knob's floor, `ftdi.py:982`), asserting (a) `SeamError` with
`code == "not_ready"`, (b) the diagnostic carries `"write reported 4 of"`, (c)
`driver.write_calls` increases by exactly 1. Expected diff: a single test function, no
`src/` bytes, no docs movement.

**Pre-committed acceptance rule** (committed here before any run of the new test; the
RED control has never been executed):

- **SHIP if** — knob-on leg: `not_ready` + `"write reported 4 of"` in the diagnostic +
  `write_calls` delta exactly 1. RED control: neutralize ONLY the short-count branch
  (`ftdi.py:982-986` returns the full count; `cp` backup, never the shared stash) →
  the test FAILS with `DID NOT RAISE` (the call succeeds, no `SeamError`); restore →
  GREEN with the collected count visible.
- **KILL if** — the RED control stays green: the test was never testing the short
  write; the slice is withdrawn, not patched until green.
- **UNDERPOWERED if** — the knob-on leg cannot reach `not_ready` because the witness
  op's frame is ≤ 4 bytes: the measurement shape is wrong, choose a longer frame and
  re-run; do not conclude anything about the value.

**Falsifier for the DON'T-BUILD verdict itself:** an adapter observed branching on the
"write reported" MESSAGE (fragile text-matching) would make the fidelity gap
behavioral. That is the reopen trigger in §7, row 3.

## 4. Invariant, standards and drift impact

- **DON'T-BUILD:** no invariant moves. STD-4's prefix set is untouched (the closed set
  is a VALUE domain inside `replay_journal_row_shape`/`standalone_vectors_row_shape`
  refusals, not a new prefix — but its member-naming TEXT is the landed surface §2
  prices). PKG-1, SRF-1/2/3, TWO-1: untouched.
- **The vendored standards tree and the lock DO NOT move either way.** This row is
  SDK-side tooling and tests, not normative content: nothing here edits
  `src/benchweave_sdk/standards/` or `standards-lock.json`, and even the refused
  option would have been code + tests only. No standards bump, no Tier 3 lock surface.
- **The residual slice:** adds no refusal path; tests-only. `docs/internal/
  drift-and-obligations.md` has no rows naming the replay/mock surfaces (verified by
  grep — zero hits for replay/mock/journal/recorded_failure), so no obligation moves.
- **TWO-1:** no SDK push is proposed from this design pass (report-only); the record
  itself is the branch's first commit so pre-commitment is provable from git log.

## 5. Review tier and the keyword scan

- This record: docs-only — **Tier 1** by the rubric's path rules.
- The refused corpus arm: **Tier 3** ("changes a refusal prefix or adds a refusal
  path" — §2's delta matrix is the evidence).
- The residual slice: tests-only — Tier 1 by the letter (nothing under `src/`); run
  `tests/server/test_ftdi.py` regardless, raw counts.
- **G0-style keyword scan run over the expected diff text** (this record, and the
  single test function §3 specifies): scanned for `mk_`, `mdb_`, `gorag_`, `ghp_`,
  `github_pat_`, `sk-`, `Bearer ` literals, and private paths — no hits. Invented or
  no fixture names; no person, client, bench, or employer identifiers.

## 6. Top risks, ranked

1. **The closure evidence ages** — someone re-reads #573's directive ("add a cell")
   without the timeline and re-opens the build. Mitigation: the issue closure must
   cite §0's timeline and the `4f67d37` SHA. Falsified only by §3's falsifier.
2. **The serve side of `recorded_failure: "connection"` is unpinned** (found during
   grounding: `replay.py:1167-1172` and `session.py:588-593` have no direct test —
   the nearest pins are the timeout siblings sharing the same if/else, and the LIVE
   connection arm at `test_ftdi.py:1373`). If that consumption drifts, nothing reds.
   Deferral §7 row 2.
3. **Anchors filed off stale main** — #573 is the second row this month whose anchors
   postdate merged work (both its anchors are dead). Process risk: pre-flight
   (#181 R2) exists and was skipped at filing.
4. **The micro-slice's witness-op coupling** — C7's `parameter_read` witness must send
   a frame > 4 bytes for the knob to arm; if the fixture's frame is shorter the test
   silently tests nothing (the UNDERPOWERED arm of §3's rule exists for this).

## 7. Deferral table

| # | Deferred | Home | Reason | Reopen trigger (observable) |
|---|---|---|---|---|
| 1 | The C7-sibling seam test (§3's spec) | gateway issue #573 — this record §3 IS the spec | whether the issue's "Fixed means" clause is honored literally or C7 + `test_ftdi.py:1475` are accepted as already covering the behaviour is a maintainer decision, not a design one | the issue stays open until that decision is recorded on it |
| 2 | Serve-side pin for `recorded_failure: "connection"` | this table (a ~15-line sibling of `test_replay.py:593` and a mock-compile arm) | the arm serves from two sites with no direct pin; nothing reds if its class or message drifts | any diff touching `replay.py:1128-1176` (the failure raise sites) or `session.py:582-599` (the mock-compile Exception slot) |
| 3 | Declarative short-write scripting for document-only corpora | this table | zero behavioural delta over `"connection"` (the class is the contract, §1); the recorder can never emit it (§2) | an adapter observed matching the "write reported" message text, or a guide promise of document-only write-stage failure cells |

## 8. What could not be checked

- The gateway's behavioral suite was not run (no cross-repo property compares
  failure-row messages; the gateway tree was grepped, not executed). Main-side modules
  that would cover a hypothetical message-drift change: none exist — that absence is
  itself part of the §1 evidence.
- muninn recall is not available in this dispatch context; the durable finding is
  proposed through the memory ledger hook instead (tags `sdk`, `design`).
