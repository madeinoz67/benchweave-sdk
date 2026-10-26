# Issue #562 work item 3 — the FTDI transport-provider contract and the replay transport

**Date:** 2026-10-26
**Scope:** the SDK-side generic half of gateway issue #562 (the LogicPort plugin's
eight-lane review, work item 3): the FTDI transport-provider contract and a replay
transport that serves recorded captures. The plugin-side truth fixes are another
lane (`fix/562-machine-truth`); this record does not design them.
**Verdict up front:** BUILD — but not what the issue's phrasing suggests. The
provider-contract *mechanism* already exists end to end (schema, descriptor
declaration, SDK offline validation, gateway admission). What does not exist is
(1) an FTDI contract *instance*, (2) any host that serves provider transactions,
and (3) a replay input that is not derived from the plugin's own builders. All
three are buildable on in-tree precedent with zero standards motion.

---

## 0. Grounding — what was verified, against which bytes

Every claim below was read this session at SDK `origin/main` = `80e8315` (v0.22.0)
and gateway `origin/main` = `493e6612` (post-#561). Line numbers are from those
commits.

1. **The provider-contract mechanism is fully landed.**
   - Corpus: `standards/otdp/0.2.4/otdp-transport-provider.schema.json`
     (contract_version const `0.1.0`; `feature_id` constrained to
     `otdp.transport.<name>/<semver>`, name segment `[a-z][a-z0-9-]*` — hyphens,
     no underscores); `standards/otdp/0.2.4/transport-providers.md` (the rules:
     §2 declaration, §3 grammar extends the §8.1 table, §6 two-tier review,
     §7 offline boundary); exemplar
     `standards/otdp/0.2.4/examples/reference-provider.json`
     (`otdp.transport.reference-hid/1.0.0`).
   - Descriptor: the vendored `otdp-device-descriptor.schema.json`
     `$defs.customTransport` already carries the optional `provider` object
     `{feature_id, id, path, sha256}` (present since the 0.2.x line; verified in
     the SDK's vendored 0.2.4 copy at
     `src/benchweave_sdk/standards/otdp/0.2.4/otdp-device-descriptor.schema.json`).
   - SDK offline lane: `src/benchweave_sdk/validation.py:568`
     `validate_transport_provider` (grammar meta-validation, kind uniqueness,
     reserved-seven disjointness, the three identity equalities) and
     `validation.py:663` `verify_provider_pin` (descriptor-relative strict
     no-follow resolution, bounded read, hash, JSON, schema, declaration
     agreement). Pinned by `tests/test_transport_providers.py` (the reference
     contract passes; grammar faults refuse).
   - Gateway commissioned lane: `src/benchweave/control/documents.py` provider
     rows and `src/benchweave/control/provider_settings.py`
     (`transport-settings.json`: `admitted[]` contract triples +
     `connections[]` connection_key→provider_id, identity-only by schema) —
     invariants CON-1's 2026-09-23 amendment and CON-10's #147 increment-3
     amendment. Nothing here moves.
2. **No host serves provider transactions.** The SDK's two standalone backends
   refuse every non-§8.1 transaction kind by construction:
   `src/benchweave_sdk_server/serial.py:66-70` (`_FIELDS` admits only
   `stream_send`/`stream_receive`/`stream_exchange`) and
   `src/benchweave_sdk_server/transport.py:377-381` (`ValueError: not a section
   8.1 stream transaction`). The #562 reviewer's anchors check out (their
   line numbers were taken against a slightly different tree; the refusal sites
   are these).
3. **The dialect is one kind with an op discriminator.**
   `logicport-plugin/src/logicport_plugin/protocol.py:42` (`DIALECT_KIND =
   "ftdi_control"`) and `protocol.py:647-711` (`ftdi_control(op, **params)` plus
   seven constructors: `reset_device`, `set_timeouts`, `set_latency`,
   `set_baud`, `purge`, `set_bitmode`, `read_pins`). The adapter reaches the
   device ONLY through these and the two generic stream kinds
   (`adapter.py:578-721`: `stream_send` for frames, `stream_receive` with
   `exact_bytes` for replies). **Seven control ops + two stream kinds = the
   nine operation kinds finding 1 prices.** `descriptor.json:25-31` declares
   `transport.type: "custom"` with line 29 disclosing "ftdi_control dialect
   pending a pinned transport-provider contract" — the exact site this work
   retires.
4. **The rehearsal today is circular and hardware-gated.** The mock derives its
   script from `vectors.json` (`session.py:340-384` `mock_exchanges`), which the
   #562 verdict records as generated from `protocol.py`'s builders; the one
   end-to-end test (`test_plugin.py:353`
   `test_configure_fpga_full_pass_real_bitstream`) skips without
   `LOGICPORT_CCF`. Hardware evidence today (LogicPort-Protocol.md §8/§9):
   init accepted (latency 4, baud 460800), the full FPGA loader chain
   (purge/bitmode/pin polls/1,057,840 bytes/DONE), and exactly one 4-byte
   post-config response (`E0 E0 E0 E0`). No sample byte was ever read on
   hardware.
5. **The replay precedent exists.** `session.py:398-461` `_cycle_plan`
   (minimal-period cycle derivation), `session.py:187-198` `FrameRow`,
   `transport.py:127` `ByteStreamMockHost` (demand-driven frame host over
   `WriterBackedCaptureServices`, `serial.py:412`, with the shared
   `_stream_receive_bounds` ladder and `assert_complete` exhaustion checks).
   `scenarios.py` is the host-shipped-adapter precedent for a new transport
   mode; `cli.py:140-290` `_build_seam` is the single transport-selection
   point; `transport_kind` flows into every seam state surface
   (`seam.py:493`, `:864`, `:1694`) and the mode banner
   (`web.py:702`, `presentation.py:157`).
6. **The in-flight train.** Gateway PRs are empty at design time; the #560 lane
   is building the plugin-ui-class-reference 0.5.0→0.6.0 bump in
   `BenchWeave/.wt/issue560-gw-4b81` (stacked on merged #561), with the SDK sync
   + 0.23.0 cut and then a pointer PR to follow. The SDK #560 lane
   (`benchweave-sdk/.wt/issue560-layout-7f3c`) carries the RED suite only.

---

## 1. The provider contract half — author the instance, do not touch the mechanism

**Mechanism.** Author `ftdi-control-provider.json`, a transport-provider contract
document against the pinned schema, and declare it in the plugin descriptor:

- `id`: `urn:otdp:transport-provider:ftdi-control:1.0.0`
- `feature_id`: `otdp.transport.ftdi-control/1.0.0` (hyphen name segment — the
  schema's name pattern admits hyphens only; the transaction KIND stays
  snake_case `ftdi_control`)
- `transport_kind`: `ftdi_control`
- `transaction_grammar`: ONE entry, `kind: "ftdi_control"`, whose
  `request_schema` is a Draft 2020-12 `oneOf` over the seven op objects
  (`{kind: const, op: const reset_device|set_timeouts|set_latency|set_baud|
  purge|set_bitmode|read_pins, ...params, additionalProperties: false}` per
  branch, params exactly as `protocol.py:661-711` types them), `result_schema`
  an empty-object maxProperties 0 for actuation ops and `{data: base64,
  minLength 1, maxLength 1}` for `read_pins`, `limits` provider-defined
  (`{"read_pins_max_bytes": 1, "bitmode_mask_range": [0, 255], ...}`).
  **One kind with an op discriminator, not seven kinds**: the plugin's builders
  already speak this shape byte-for-byte (`protocol.py:658`), so the plugin owes
  zero builder motion, and the issue itself names "the `ftdi_control` dialect"
  as one thing. The grammar extends the §8.1 table (the two stream kinds the
  adapter also uses are generic-table kinds; the grammar neither declares nor
  shadows them — transport-providers §3).
- `security_scope`: `commissioned_connection` (the closed enum's only value).
- `host_requirements`: summary naming host-side FTDI-class access (libftdi or
  D2XX semantics) over the commissioned device; `native_libraries` empty for
  the replay lane (a future live executor names `pyftdi`/`libftdi 1.5` with
  exact versions — the record layer ships before the executor, so the
  requirement text says what the *contract* demands, and the replay host is an
  executor that needs none of it).
- `approval`: category `protocol`, `result: "partial"` — deliberately. Direct
  hardware exercise exists for `set_latency`, `set_baud` (§8), `set_bitmode`,
  `read_pins`, `purge(rx)` (§9 loader chain); `reset_device`, `set_timeouts`,
  `purge(tx)` rest on the static-analysis record (§3.4/§4).
  `limitations` names that split AND that the register/command decode above
  the transport (page bits, register map) is outside this contract's evidence.
  This is the #562 finding-8 discipline (record over claims) applied to the
  approval block; the falsification session (work item 2) is the reopen path to
  `passed`.

**Where it lives.** The instance travels in the plugin package
(`logicport_plugin/ftdi-control-provider.json`, pinned descriptor-relative per
transport-providers §2 — "a plugin and its pinned contract travel one package").
For the ecosystem half, the SDK banks a canonical byte-identical copy at
`src/benchweave_sdk/providers/ftdi-control-1.0.0.json` (a NEW data directory,
deliberately outside the vendored `standards/` tree so `make
check-sdk-standards` and the corpus-pin machinery are untouched) plus a
user-guide section: any FTDI-class plugin copies the canonical bytes into its
package and pins them. Provider instances are "deliberately versioned
elsewhere" (GOVERNANCE §Deliberately versioned elsewhere; transport-providers
§1) — **no corpus bytes move, no standard bumps, no standards-governor lane.**

**What the descriptor owes** (plugin tree, coordinated with the machine-truth
lane — see §5): add the `provider` object, add
`otdp.transport.ftdi-control/1.0.0` to `required_features` (S04), and RETIRE the
"pending a pinned transport-provider contract" note at `descriptor.json:29`
(the `protocol_reference` string stays, minus the pending clause). Validation
already exists on both lanes (`verify_provider_pin` offline; the gateway's
`provider_not_admitted:` row will refuse commissioned use until an operator
admits the contract in `transport-settings.json` — correct and untouched).

**Why generic.** All seven ops are the D2XX/libftdi *common* surface (the
function table in LogicPort-Protocol.md §1 is FTDI's, not Intronix's). Nothing
in the contract mentions LogicPort: the dialect's parameters (baud, latency,
masks) are transaction payloads. Any FTDI-based instrument — including the
second Intronix PID the record names — pins the same contract. The
LogicPort-specific knowledge (opcodes, register map, bitstream) stays in the
plugin.

---

## 2. The replay transport half — a third standalone transport that serves a recorded journal

**Mechanism.** A new SDK module `src/benchweave_sdk_server/replay.py` providing
`ReplayHost(WriterBackedCaptureServices, MockHost)` — `ByteStreamMockHost`'s
sibling — plus a journal loader, wired as a third `_build_seam` branch:
`benchweave-sdk-server serve --transport replay --replay <journal.json>`
(`cli.py:312-317` grows the choice; `transport_kind="replay"`).

**The journal** (the recorded capture; SDK-defined, provider-generic, JSON,
LF-terminated rows not required):

```json
{
  "journal_version": "1",
  "recorded": {"started_at": "<ISO-8601>", "source": "live_probe",
                "operator_note": "<optional>"},
  "provider": {"feature_id": "otdp.transport.ftdi-control/1.0.0",
                "id": "urn:otdp:transport-provider:ftdi-control:1.0.0",
                "sha256": "<digest of the pinned contract bytes>"},
  "rows": [
    {"name": "init-1",
     "transaction": {"kind": "ftdi_control", "op": "set_baud", "baud": 460800},
     "response": {}},
    {"name": "pin-1",
     "transaction": {"kind": "ftdi_control", "op": "read_pins"},
     "response": {"data": "<base64 one byte>"}},
    {"name": "c2-status",
     "transaction": {"kind": "stream_send", "data": "<hex>", ...},
     "response": {}},
    {"name": "status-reply",
     "transaction": {"kind": "stream_receive", "max_bytes": 4,
                      "termination": "lf", "exact_bytes": 4},
     "response": {"data": "<hex E0E0E0E0>"}},
    {"name": "bitstream-chunk-1",
     "transaction": {"kind": "stream_send", "data_sha256": "<digest>",
                      "byte_length": 10000},
     "response": {}},
    {"name": "early-timeout",
     "transaction": {"kind": "stream_receive", "max_bytes": 3, ...},
     "recorded_failure": "timeout"}
  ]
}
```

- `recorded` is evidence metadata: carried into the serve banner and capture
  sidecar, never re-served as a live timestamp.
- `provider.sha256` must equal the digest of the contract the SERVED plugin's
  descriptor pins — a journal recorded against a different contract revision
  refuses at load (`replay_journal_provider_mismatch:`).
- Provider transactions validate against the plugin's pinned grammar
  (`verify_provider_pin` at session construction; then each row's transaction
  against the admitted grammar — transport-providers §3: "the host validates
  provider transactions against the admitted contract's grammar, never against
  the generic table"). Stream rows validate through the existing shared
  `_FIELDS`/`_stream_receive_bounds` (`serial.py:92-116`) — no new frozenset,
  obligation 17 untouched.
- **Bulk rows.** `stream_send` rows ≥ 4096 bytes MUST carry `data_sha256` +
  `byte_length` instead of inline data; the match rule hashes the outgoing
  bytes and compares. Without this, the loader chain alone (106 chunks ×
  10,000 bytes) produces a ~2.1 MB journal against the SDK's 256 KiB
  bounded-read convention (`validation.py` `INPUT_BYTE_LIMIT`). This is the one
  place "exact match" means "exact digest" — sha256 + length over ≥ 4096-byte
  payloads; stated as such in the module contract. Journal file bound: 1 MiB.

**Serving rules** (the `ByteStreamMockHost` ladder, extended):

1. Load-time: parse, verify the provider triple against the descriptor pin,
   validate every row (typed `replay_journal_*:` refusals; a refused journal
   leaves the conversation untouched, exactly as a refused transaction does).
2. Demand-driven, real clocks (`LoopingMockHost`'s `monotonic`/`utc_now`
   overrides): deadlines expire on live time; replay serves on the HOST clock.
   Recorded timestamps are never re-served — a reading stamped during replay is
   stamped at replay time, and the run is labeled replay (below), so nothing
   claims record-time observation.
3. Exact-match discipline: a provider row matches on the full transaction dict
   (MockHost's exact-dict posture); a stream row on request bytes or digest.
   **A mismatch is a `ConformanceError` naming the row** — this is the
   anti-circularity property: a journal recorded from hardware makes the
   plugin's builders reproduce the recorded wire bytes or fail loudly, which
   `vectors.json` (builder-generated) can never do.
4. `recorded_failure` rows replay the recorded failure honestly: a `timeout`
   row answers the receive with the backend's retained-partial `TimeoutError`
   posture, not a fabricated frame. The §8 log's "no response within 1.5 s"
   stays a no-response.
5. Cycle: `_cycle_plan`'s minimal-period derivation over row identity (the
   transaction dict for provider rows; request/response bytes for stream rows),
   restored rotated-to-phase on request-bearing consumption, response-only
   rows released once per cycle, `plays` exposed — all inherited semantics.
   No derivable cycle → honest exhaustion (`cycles=1` is the RED control).
6. The dispatch-marker ladder unchanged (`transport.py:383-424`): grammar →
   bounds → payload → liveness → closed → dispatch marker → serve. A transmit
   without `mark_dispatch_started` is a `ConformanceError`; a failure after
   dispatch keeps the adapter's dispatch-state honesty (REG-2) — the host never
   fabricates, never retries.
7. Capture members over `WriterBackedCaptureServices` with a host-stamped
   sidecar: `configure_capture` composes `config.transport = "replay"` and
   `config.replay_journal = {sha256, recorded_at}` into the sidecar metadata —
   the effective-reservation precedent (`serial.py` `configure_capture`,
   B-F3's "the durable evidence names what the writer enforces").

**Honesty requirements** (the brief's list, each with its mechanism):

- *Timestamps*: host clock at replay time; recording timestamps ride the
  banner/sidecar as evidence. No surface serves a recorded time as observed.
- *`dispatch_state`*: the adapter owns it; the host's only contributions are
  never-fabricate and never-retry (rules 3-4, 6).
- *The UNKNOWN case*: a recorded timeout replays as the backend's
  retained-partial TimeoutError (rule 4) — ambiguity in the recording stays
  ambiguity on the wire (A06). Replay invents no certainty the recording lacks.
- *Duplicate suppression*: sits at the gateway boundary (A06); the standalone
  host has no duplicate-suppression surface and adds none. Named, not changed.
- *The launder guard*: `transport_kind="replay"` flows into every seam state
  surface (`seam.py:493/:864/:1694`); the mode banner (`presentation.py:157`)
  gains a replay arm distinct from both the mock's `simulated` banner and the
  live banner — recorded-evidence replay is neither simulation nor live
  hardware (`web.py:702`'s `simulated` predicate must not classify replay as
  live). Banner copy goes through the `document-writer` agent (the docs
  register rule).

**The invariant it must not break:** A06 as pinned SDK-side by REG-2
(dispatch-state honesty — "the ambiguity is preserved, not laundered into a
clean answer") and the conformance discipline (`ConformanceError`, exhaustion
honesty). The replay honesty rules pin as `replay.py`'s module contract + its
test suite — the `serial.py` precedent (its laws live in module contracts
pinned by tests, not in `docs/internal/invariants.md`, whose anchors are all
gateway `src/benchweave/` paths; no invariants.md motion).

**Acceptance-scenario bound ("zero page bits decode").** The v1 acceptance
journal carries ONLY exchanges with direct hardware evidence: the §4 init
chain, the §9 loader chain, the one C2 status read. It contains no
sample-plane exchange — none exists in hardware evidence — so satisfying the
acceptance scenario via replay depends on zero page-bits decode (the unproven
decomposition, `protocol.py:341-358`, is not exercised by any row). When the
falsification session (work item 2) records sample-plane reads, those rows join
the journal and the replay then PINS the page bits (a wrong decomposition
mismatches the recorded C2 frames — §3's exact-match). The transport work is
landable and acceptable today precisely because its acceptance bound excludes
the open decode question.

---

## 3. What is generic, what the plugin owes

| Part | Generic (SDK/corpus) | LogicPort-specific (plugin) |
|---|---|---|
| Contract schema + rules | corpus, exists | — |
| FTDI contract instance | canonical copy banked in SDK | pinned copy + `approval` evidence citing the RE record |
| Journal format + `ReplayHost` | SDK, new | — |
| Journal conversion (`tools/journal_from_log.py`, C-tool logs → rows) | — | plugin tree |
| The acceptance journal itself | — | plugin tree (evidence) |
| Builder conformance to the journal | — | plugin (the builders must reproduce recorded bytes) |
| Live FTDI executor | deferred (§6) | — |
| Commissioned admission | gateway, exists, unused until an operator admits the contract | operator act |

---

## 4. Sequencing against the in-flight train

- **Same train or after it:** AFTER. The #560/#556 train owns the SDK repo's
  next release vehicle (the plugin-ui-class-reference 0.6.0 sync + 0.23.0 cut +
  pointer PR). This work shares no corpus bytes with it; interleaving an
  unrelated feature into a release-cut train adds merge risk to an urgent line.
  SDK slices land as their own PR(s) basing on `main` after the 0.23.0 cut
  merges (the #69 stack rule if timing overlaps).
- **Same standard or a different one:** NEITHER — no standards bytes move. The
  contract instance and journals are "deliberately versioned elsewhere"
  (GOVERNANCE; transport-providers §1). The rule that does bind is obligation
  15's #147 pairing constraint, and it is satisfied trivially: no corpus change
  rides, so no sync-window question exists.
- **SDK version motion if both ride one release:** they do not both ride one
  release by default — 0.23.0 is the classref train's; this work targets
  **0.24.0** (MINOR: new serve capability, additive). If the owner orders one
  vehicle, the mechanics permit it (no bump interaction), at the cost of
  coupling an urgent fix train to a feature — not recommended.
- **Plugin-tree coordination:** the descriptor edit collides with the
  machine-truth lane's descriptor edits (F1/F3, in flight on
  `fix/562-machine-truth`). The provider object lands AFTER that branch merges,
  or as one combined descriptor edit owned by that lane. The contract file
  itself is collision-free (new file).
- **Immediate, train-independent work:** the contract document, the conversion
  tool, and journal authoring validate TODAY against SDK 0.22.0's shipped
  `validate_transport_provider`/`verify_provider_pin`; only the `serve
  --transport replay` leg needs the new SDK code.

---

## 5. Slice plan — landing order, RED proof, acceptance, gates

**Slice 1 — SDK: the replay transport** (`feat/562-replay-transport`, SDK repo,
rides 0.24.0)
- New `src/benchweave_sdk_server/replay.py` (`ReplayHost` + journal loader),
  `cli.py` choice + `--replay`, seam/banner/sidecar arms, tests
  (`tests/server/test_replay.py` + a fixture plugin declaring the corpus's
  `reference-hid` provider and a fixture journal — the generic proof needs no
  LogicPort dependency).
- **RED:** on `origin/main`, serving a provider-declaring plugin whose adapter
  issues `{"kind": "ftdi_control", ...}` fails — `transport.py:377-381`'s
  "not a section 8.1 stream transaction". The new test captures that refusal;
  GREEN only with the mechanism.
- **Acceptance:** §7's Metrics A (fixture form), B, C.
- **Gates:** FAST lane per commit (bare ruff, fresh-cache bare mypy, focused
  pytest) + full battery before push + `tests/faults/` not applicable (no
  gateway `state/`/`control/` motion); G6 adversarial refute (Tier 3).

**Slice 2 — plugin: the FTDI contract + declaration + journals** (plugin tree,
after `fix/562-machine-truth` merges)
- `ftdi-control-provider.json` (approval `partial` per §1),
  `tools/journal_from_log.py`, the §4/§9-derived acceptance journal, the
  descriptor provider object + `required_features` + note retirement, the
  replay acceptance test (CI-runnable: init/status/resync rows with fixture
  journals; operator-local with `LOGICPORT_CCF`: the full loader chain — the
  adapter reads the real CCF from disk to build the bytes it sends, so the
  wire-side rehearsal needs the file locally; the skip stays honest and now
  names the journal as the wire authority).
- **RED:** the plugin suite's provider-declaration test fails on the current
  descriptor (no provider object → `verify_provider_pin` returns None vs the
  new expectation) and the replay acceptance test fails without slice 1's SDK
  (against installed 0.22.0).
- **Gates:** the plugin's own uv suite (full), RED-sanity on both new tests;
  Tier-3-rigor review by convention (the repo rubric governs the two BenchWeave
  repos; this lane adopts the same discipline voluntarily).

**Slice 3 — SDK: bank the canonical contract** (`feat/562-ftdi-contract`, SDK
repo, rides 0.24.0 with slice 1 or immediately after)
- `src/benchweave_sdk/providers/ftdi-control-1.0.0.json` (byte-identical to the
  plugin's pinned copy — pinned equal by test), user-guide section
  (`user_guide/plugin-sdk.qmd`), README CLI row for `--transport replay`.
- **RED:** the byte-equality test fails until the canonical copy exists.
- **Gates:** FAST lane + battery.

Deferred (§6): live executor, gateway commissioned runtime, scaffold wiring,
sample-plane journals, dataset-lane marker.

---

## 6. Deferrals — each with home and reopen trigger

1. **The live FTDI executor** (pyftdi over the `[server]` extra — the pyserial
   precedent at `pyproject.toml`). Home: SDK follow-up. Trigger: the
   falsification session's outcomes (work item 2) + the first commissioned
   bring-up. This deferment is also obligation 16's boundary: the replay
   executor adds NO endpoint/secret surface, so the "first provider
   implementation" reopen of the gateway's transport-settings shape is NOT
   fired by this design; the live executor IS that trigger and carries its own
   gateway-side design (USB identity vs the identity-only settings schema).
2. **The gateway commissioned provider runtime** (transport-settings admission
   exists; the executor + grant seam do not). Home: gateway repo, out of this
   work item by the issue's own split.
3. **Sample-plane journal rows** (page-bits-dependent exchanges). Trigger: work
   item 2's recordings.
4. **Dataset-lane replay marker.** No `DatasetServices` implementation ships in
   the SDK yet (`interfaces.py:163-166`); when it does, its manifests carry the
   transport identity. Trigger: that implementation.
5. **Scaffold/copier wiring for provider-declaring plugins.** Trigger: the
   second FTDI plugin (YAGNI until then).

---

## 7. Pre-committed acceptance rule

Written before any measurement ran. The mechanism is deterministic conformance,
so the rule is all-or-nothing over enumerated arms, not a statistical effect.

**Metric A — the replay serves the recorded conversation.** A fixture journal
of ≥ 20 non-digest rows (the fixture-plugin form in slice 1; the LogicPort
acceptance journal in slice 2, expected ≈ 120 rows of which ≈ 106 are digest
rows) replays to completion through the standalone host: every operation
envelope returns `status: "ok"`, `assert_complete()` passes, zero
`ConformanceError`.
**Metric B — the journal pins the builders (the anti-circularity control).**
Six single-point mutations of the plugin's transport-relevant code, each must
make the replay fail loudly: (B1) `wire_address` mask change — the page-bits
wrongness simulation; (B2) `INIT_BAUD` change; (B3) `BITBANG_MASK_FPGA`
change; (B4) `FPGA_PULSE_START` byte change; (B5) `decode_pin_byte` inversion —
fails the scenario's decoded-status assertion, not the transport; (B6)
`RESYNC_MARKER` change. 6/6 must fail, each naming the offending row (or, for
B5, the assertion).
**Metric C — the honesty arms.** (C1) every seam state surface reports
`transport: "replay"`; (C2) the mode banner's replay disclosure differs from
both the mock-simulated and the live banners (string-pinned); (C3) the capture
sidecar carries `config.transport` + the journal digest; (C4) a journal whose
`provider.sha256` disagrees with the descriptor pin refuses
`replay_journal_provider_mismatch:`; (C5) a receive past the recording's end
with bounded cycles fails honestly (quiet line / retained-partial
`TimeoutError` per the bounds), never a fabricated byte.

**Ship direction:** A, B (6/6), and C all pass.
**Kill direction:** any B mutation replays clean (the journal does not pin the
builders — the increment's core claim is false; kill the design, not the test);
any C arm fails (an honesty surface is missing — blocker, code-fixable, but the
ship claim is dead until it holds).
**Underpowered direction:** A fails on an unmutated, correctly converted
journal — the RECORDING is insufficient evidence (diagnose by the first
mismatched row; the falsification session re-records). This indicts the
journal, not the mechanism: B and C remain interpretable independently.
**Denominators:** B's denominator is 6 mutations; A's is the journal's row
count (stamped in the journal file); C's is 5 arms. All measurements are this
lane's, on this machine, deterministic.

---

## 8. Risks, ranked, with falsifiers

1. **Replay launders recorded evidence as live** (A06). Falsified by C1-C3;
   the residual is human: an operator screenshotting past the banner. The
   acceptance claim's wording is bounded — "the plugin reproduces the recorded
   conversation", never "the device works".
2. **A fabricated journal passes as hardware evidence.** The journal's
   `recorded.source` is author-asserted; the host cannot distinguish a real
   capture from an invented one (the conversion tool is trusted tooling).
   DISCLOSED RESIDUAL, not closable machine-side: provenance lives in the RE
   record, the plugin's `provenance` block, and the operator's approval;
   journals cite their source logs by digest.
3. **Cycle restoration serves stale rows as fresh observations.** Inherited
   from the byte-stream mock (the guide's two-full-cycles capture rule);
   mitigated by the exposed `plays` counter and the banner. Falsifier: a test
   asserting `plays` increments and the row identity holds across restores.
4. **Digest-form bulk rows weaken exact-match.** sha256 + length over ≥ 4096
   bytes; collision infeasible; the row also pins `byte_length`. Negligible,
   stated in the module contract.
5. **One-kind-with-op-discriminator grammar ages poorly** (a future FTDI
   plugin wanting per-op kinds). The grammar is versioned; kinds are additive
   in a 1.1.0 instance. Low.
6. **Train or lane collision.** §4's sequencing rules; the descriptor-edit
   ordering is the one live collision (machine-truth lane).
7. **`transport_kind="replay"` mishandled by serial-specific UI arms**
   (`web.py:792-829` branch on serial). C1/C2 pin the replay surfaces; a
   missed arm is a C-arm failure, not silent.

---

## 9. Review tier and the Step-1 keyword scan (#254)

**Tier: 3 (maximum across slices).**
- Slice 1 (SDK): Tier 3 — the expected diff text carries `sha256` and
  `hashlib` (journal digest + provider-pin verification) and `asyncio` (the
  async transfer path/tests); new JSON machinery validated against embedded
  JSON Schemas (the grammar subschemas the loader meta-validates through).
- Slice 2 (plugin tree): outside the two-repo rubric; adopted Tier-3 rigor
  (RED + second pass). Its expected diff carries `sha256` (the descriptor pin).
- Slice 3 (SDK): Tier 3 — `sha256` (the digest-equality test and docs), a JSON
  document carrying embedded schemas.

**Keyword scan** (the rubric's eight, run mechanically over this record's
§1/§2/§5 expected-diff inventory — the mechanism descriptions, code shapes,
and test arms the diff will carry; the review re-derives the scan over the
real diff):

| Keyword | Measured count over the expected-diff inventory | Source in the expected diff |
|---|---|---|
| `sha256` | 6 | the journal/provider digest sites the mechanism names (§1 pin, §2 `provider.sha256`, `data_sha256`, C3/C4 arms) |
| `hashlib` | 0 | the inventory names no import site; the real diff's `replay.py` will carry one |
| `asyncio` | 0 | the inventory names no import site; the real diff's tests may carry one |
| `threading` | 0 | demand-driven host; no reader thread |
| `subprocess` | 0 | — |
| `migrate` | 0 | — |
| `recovery` | 0 | — |
| `protection` | 0 | absent from the inventory; keep it out of the diff text |

Scan method: `re.findall` over the record's §1+§2+§5 text (the mechanism and
slice descriptions the diff will implement), run 2026-10-26 after the record
was written; the counts above are that run's output. The REAL diff's counts
will differ (higher on `sha256`/`hashlib` where code and tests repeat the
sites); the review re-derives the scan over the real diff, and the tier is
settled by the `sha256` trigger under either count.

Three Tier-3 keyword triggers (`sha256`, `hashlib`, `asyncio`) — first-match
Tier 3 regardless of path rules; the path rules independently reach Tier 3 for
slices 1 and 3 (JSON-Schema-adjacent files). **Standards-governor: NOT
triggered** — no `standards/` bytes, no vendored-tree motion, no
standard-version strings, no submodule pointer inside the slices themselves
(the pointer advance is the standing release-train discipline, not this
design's diff).

---

## 10. Open decisions for the maintainer

1. **Vehicle:** confirm 0.24.0 after the classref train (recommended) vs
   riding 0.23.0.
2. **Canonical home:** `src/benchweave_sdk/providers/` as a data directory
   outside the vendored-standards comparison — confirm, and confirm the
   instance version string stays OUTSIDE the version-bearing-surface register
   (obligation 18) as instance data, like plugin payload.
3. **Journal bound:** 1 MiB file cap with digest-form rows ≥ 4096 bytes —
   confirm or adjust.
4. **Slice-2 branch ownership:** its own plugin branch vs folding the provider
   edit into `fix/562-machine-truth`'s descriptor commit.
5. **Grammar shape:** one `ftdi_control` kind with the op discriminator
   (plugin-verbatim; recommended) vs seven per-op kinds.
