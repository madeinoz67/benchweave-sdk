# Issue #566 — the scaffold's wire-discipline half (rows 8 to 11)

**Date:** 2026-10-26
**Scope:** the SDK-side half of gateway issue #566 — the four cross-functional
rows the #562 wire-truth train produced (counter integrity, paced polling,
completion-gated success, golden hardware vectors), landed as scaffold helpers,
guide rules and one host-side gate. The plugin rows stay on #562; this record
does not design them.
**Verdict up front:** BUILD, with one framing correction. Rows 8-10 are
generalisations of three inline mechanisms a hardware probe proved (the
LogicPort plugin's `feat/562-wire-truth` branch, commits `a6fd5da`,
`cacb563`, `30e9dd7`); row 11 is the mechanism WITHOUT the capture — the
recorded bytes themselves await a hardware session and this record says so.
The brief's claim that scaffold templates live under
`src/benchweave_sdk_server/templates/` is wrong: that directory is the
server's UI HTML. The scaffold is the copier template at the repository root
(`copier.yml` + `template/`, issue #347 WS2), and everything here lands there.

---

## 0. Grounding

Read this session at SDK `origin/feat/562-provider-replay` = `580dab6` (the
issue #564 branch, this lane's base — the guide and README edits queue behind
it), and the plugin branch `feat/562-wire-truth` at `30e9dd7`.

- The plugin's `_advance_counter` (adapter.py, `a6fd5da`) records a
  `counter_gap` evidence entry then raises `ValueError` naming expected and
  saw. It has NO wrap handling: the counter is `data[2]` of the reply frame
  (protocol.py `parse_reply`) — one byte — so the 0xFF→0x00 roll reads as a
  gap after 256 exchanges. The general helper fixes this with an optional
  `modulus`; the inline version stays as the plugin row's problem.
- The paced poll (`cacb563`) is one `asyncio.sleep(FREQ_POLL_INTERVAL_MIN_MS
  / 1000)` inside the attempt-bounded loop; the pre-fix loop never slept,
  which on hardware exhausted the attempt budget before the device's
  ~119 ms application timer ever answered — the systematic false timeout.
- The completion gate (`30e9dd7`) turns a DONE-less FPGA pass into
  `DEVICE_REJECTED` with an uncertain outcome — ok with `done: false` was a
  real defect, not a style choice.
- The vectors format authority is `benchweave_sdk_server/session.py::
  vectors_script` (issue #394): closed vocabularies for
  `transaction_dialect` and `encoding`, per-row refusals with the
  `standalone_vectors_*:` family, surfaced as the typed `not_ready` connect
  mapping. The file-level `evidence` key existed in the seeded
  `vectors.json` but nothing read it — decorative until this change.
- The scaffold's constraint set (invariants SRF-1): the generated plugin
  runtime has NO dependency on this SDK (relative imports or stdlib only);
  plugin TESTS import `benchweave_sdk` through the generated test extra
  (`benchweave-sdk==<version>` + pytest — core only, no server package).
  Any helper an ADAPTER calls must therefore ship inside the plugin package;
  any check a plugin TEST runs must live in core.

## 1. Where each row landed

| Row | Mechanism | Surface |
|---|---|---|
| 8 | `CommandCounter` + `CounterGapError` | `template/src/<pkg>/wire.py` (new template module) |
| 9 | `paced_poll` + the guide rule | same module + `AI-GUIDE` + user guide "Poll cadence" |
| 10 | `require_completion` + `CompletionUnassertedError` + the rule | same module + guides |
| 11 | `validate_vectors_evidence` + the loader hook + the seeded invariant test | `src/benchweave_sdk/vectors.py` (new core module), `session.py`, `template/tests/test_plugin.py` + guides |

Why the helpers ship as template bytes and not SDK code: the gateway loader
rule above. A template module is the only placement where every scaffolded
plugin gets them without an SDK dependency; the cost (existing plugins do
not receive them through `upgrade` — `src/**` is skip-listed in `copier.yml`)
is the copy-never-overwrite protection working as designed and is disclosed
here.

Why row 11's validator lives in core while its consumer is the server: the
seeded plugin test must import it (`benchweave_sdk.vectors`), and plugin
tests cannot reach `benchweave_sdk_server`. One mechanism, two consumers —
the loader wraps its `ValueError` into the `PluginLoadError` the connect
seam types as `not_ready`.

## 2. The design decisions worth defending

1. **The wrap modulus (row 8).** `CommandCounter(modulus=256)` for a counter
   byte; `modulus=None` (the default) keeps strict `+1`. The inline version's
   latent roll defect is pinned by test both ways: with a modulus the roll
   passes, without it the roll refuses. Refusal names expected (wrap-aware),
   observed and the exchange index, and awaits an optional `record` evidence
   hook BEFORE raising — the plugin's record-then-raise order.
2. **The pacer owns the loop (row 9).** A helper that only computes the next
   deadline leaves the defect shape representable (a loop that forgets to
   call it). `paced_poll` does the read, the wait, and the deadline check;
   the interval cannot go unread because there is no loop beside it. The
   guide rule still carries the weight for code that does not use the
   helper: "a declared interval that no loop reads is a defect."
3. **Completion refusal is a RuntimeError, not a ValueError (row 10).** A
   silent completion is a device verdict, not a malformed response; the
   adapter catches it explicitly and picks its own failure code (the plugin
   used `DEVICE_REJECTED`, uncertain). Uncaught it maps to the adapter's
   RuntimeError arm — never ok.
4. **The evidence vocabulary is closed and asymmetric (row 11).**
   `"synthetic"` (default when absent) or `"hardware"`, at file level and per
   row; a hardware row needs a `recorded` object with a non-empty `when`
   (the capture moment — the one field a builder cannot supply truthfully).
   Overstatement refuses (hardware label, no recorded rows; hardware row, no
   `recorded`); understatement passes (a synthetic-labelled file with one
   properly-recorded row claims less than it holds). The refusal family is
   `standalone_vectors_evidence_unknown:` / `standalone_vectors_evidence_unrecorded:`,
   matching the issue #394 families so connect diagnostics stay uniform.
5. **The honesty bound of the gate.** The check proves a hardware CLAIM comes
   with recorded provenance; it cannot prove the provenance is true — a
   forged `recorded` object passes. The anti-circularity property (bytes no
   builder can produce) belongs to the capture workflow; this mechanism
   enforces the declaration discipline and the bound is stated in the
   validator's docstring, the AI-GUIDE rule and the user guide paragraph.

## 3. Acceptance (pre-committed)

- Every new behavior RED-first: the three SDK-side modules and the rendered
  project's suite were run before implementation and failed for the missing
  mechanism (ModuleNotFoundError / FileNotFoundError / DID NOT RAISE), then
  green after — evidence in the lane report.
- The R-2 fixture parity arms green after regeneration; the fixture diff is
  exactly `wire.py` (both arms) + `test_plugin.py` (both arms) +
  `AI-GUIDE.md` (both arms) — nothing else moves.
- The additive bound: a vectors file with one properly-recorded hardware row
  still connects and operates (pinned); the scaffold's own synthetic file
  still passes (the seeded invariant test IS that pin, in every generated
  project).
- Gates: ruff clean, bare mypy clean from a fresh cache, full suite green
  with junit counts from the XML.

## 4. Deferrals

- **The capture itself (row 11's substance).** No hand-recorded bytes exist
  for any plugin yet; the slot, the gate, the seeded test and the rules are
  the mechanism. The capture lands with the plugin's hardware session (the
  #562 plugin rows) or a follow-up there; this issue's mechanism half is
  complete without it.
- **Existing plugins do not receive `wire.py`.** The copier skip list
  protects `src/**` on update by design; carrying the helpers to already-
  scaffolded plugins is an author-side copy, disclosed in the guide by the
  module's location.
- **No `_pace_wait`-style standalone wait helper.** The lane brief described
  one; the loop-owning helper subsumes it (a standalone wait re-opens the
  skip-the-pace defect). Deviation from the brief's framing, on the evidence
  in §2.2.
