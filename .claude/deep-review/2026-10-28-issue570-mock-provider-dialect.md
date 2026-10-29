# Issue #570 — the mock provider dialect (`transaction_dialect: "provider"`)

**Date:** 2026-10-28
**Scope:** the third vectors dialect and the scaffold corpus that feeds it (gateway
issue #570, scope 2 + the scaffold half of scope 1 and all of scope 3): a
provider plugin rehearses its full bring-up under `--transport mock` with no
hardware and no journal, from a `vectors.json` its own scaffold emits. The
driver double (`ScriptedFtdiDriver`, #568 §3) stays exactly where it is; the
guide learns the division of proof between the two rehearsals and replay.
**Verdict up front:** BUILD — and the reviewer's counter-claim is RIGHT: this
is a compile and a dialect name over proven machinery, not an architectural
fork. The #568 record's §3 premise ("a `MockHost` script cannot express a
bitmode call") is refuted by the code this repository already ships; what
survives of §3 is the *fidelity* claim (a mock dialect does not exercise the
executor ladder), which this design keeps as the stated division of proof
rather than an argument against building. The owner ruling ("add the
dialect") is served, not re-litigated.

**Triage:** PUBLIC. No person, client, bench, serial, commercial term, or
one-install operational specifics below; file:line citations and public issue
numbers only. Same register as the #568/#564 records this continues.

---

## 0. Grounding — what was verified, against which bytes

Every code claim below was read this session at `9c0a8a0` (the fold tip of
`feat/568-live-provider-transport`, the branch this slice builds on). Line
numbers are from that commit. Issue #570 was read live over `gh` (no
comments yet); the SDK tracker has no open PR and no rival `#570` branch
(pre-flight #181 R2, clean).

1. **The dialect vocabulary is an extension point with a precedent of being
   extended.** `session.py:181` `_DIALECTS = ("stream_exchange",
   "send_receive")` — `send_receive` was itself ADDED by issue #394 (the
   constant's own comment, `session.py:177-180`). Dialect validation at
   `session.py:280-285`; selection in `mock_transport_factory`
   (`session.py:474-504`), which already lazy-imports its hosts
   (`session.py:488`) — the lazy-import precedent this design reuses.
2. **The plain mock host matches arbitrary transaction dicts exactly, with no
   kind gate.** `MockHost.transfer` (`benchweave_sdk/testing.py:176-226`):
   dispatch-marker check (`:213-216`), honest exhaustion (`:217-218`), then
   `if transaction != expected: raise ConformanceError` (`:219-221`) —
   whole-dict equality, bytes included. `LoopingMockHost`
   (`transport.py:41-124`) adds the recycle and the real clock and inherits
   that matching unchanged. The `_FIELDS` gate lives ONLY in
   `ByteStreamMockHost.transfer` (`transport.py:377-381`) and in the serial
   backend — a provider transaction under the exchange host refuses by
   MISMATCH, not by gate.
3. **The #564 journal row shape is the proven provider-row vocabulary.**
   `replay.py:311-411` `_load_row`: a row is `{"name", "transaction",
   "response"}`; `kind in grammar` takes the provider arm (`:348-402`) whose
   comment states the design fact this record rules on — *"the full
   transaction dict is the match identity (MockHost's exact-dict posture)"*
   (`:349-351`) — validating transaction AND response against the pinned
   grammar and b64-decoding byte-valued fields to ABI form; `kind in _FIELDS`
   takes the shared stream arm (`:404-405`); anything else refuses
   `replay_journal_kind:` (`:407-411`).
4. **The scripted driver's rows are the same shape.** `ScriptedFtdiDriver`'s
   docstring names it (`ftdi.py:300-301`) and `_parse_row` enforces it
   (`ftdi.py:340-414`): control rows carry `transaction.op`, stream rows the
   §8.1 kinds with hex data. The committed synthetic bring-up fixture
   (`tests/fixtures/ftdi_control_plugin/src/ftdi_control_demo/bring-up-journal.json`)
   is 9 rows in exactly that vocabulary: six control ops, one
   `stream_send` (hex chunk), one `read_pins`, one `stream_exchange`
   (bounds inside the transaction, hex reply).
5. **The executor ladder is real and is NOT under the mock.**
   `FtdiCaptureServices.transfer` (`ftdi.py:691-794`): grammar-first refusal
   (`:604-624`), declared-limits enforcement (`:645-685`), closed posture +
   fault latch (`:726-732`), busy guard (`:739-744`), dispatch marker
   (`:748-749`), op-table dispatch (`:751-759`), one-attempt driver call
   (`:763-769`), result validation (`:775-793`). In mock mode the services
   object IS the host (`mock_plugin_session`, `session.py:702-722`) — none of
   that ladder sits between the adapter and the script.
6. **The cycle machinery exists twice over, shareable.** `_replay_cycle_plan`
   (`replay.py:581-611`) derives (establishment, unit, rotate) over
   `ReplayRow` identity, with the no-unit fallback `(1, None, 0)` — a
   RECORDING plays once (`ReplayHost._recycle_if_armed` returns early on an
   empty cycle); `_cycle_plan` (`session.py:408-471`) is the FrameRow twin
   whose fallback is the whole tail — a MOCK recycles ambiguous corpora (the
   docstrings state the split: `replay.py:584-590`). `LoopingMockHost` takes
   `establishment` (`transport.py:75`) and cycles its whole tail.
7. **The replay module imports the session module at module level**
   (`replay.py:91-92`), so `session.py` cannot import `replay.py` at module
   level — the provider compile must lazy-import inside the function (the
   `session.py:488` precedent).
8. **The scaffold currently refuses the corpus by exclusion.**
   `copier.yml:33-34`: `_exclude` drops `vectors.json` when
   `provider_transport` is true (the comment at `:12-17` and `:26-32` states
   the #568 §3 rationale verbatim). The provider branch of the generated
   suite (`template/tests/test_plugin.py.jinja:1-137`) builds its script from
   the package's own protocol builders (`_script()`, `:15-34`) and drives the
   driver double (`:47-61`); it generates no vectors tests. The serial
   branch generates the evidence test and the walk-order test (`:287-306`).
9. **The no-vectors load refusal is execution-pinned.** `test_ftdi.py:690-695`
   (the #568 C5 arm): `mock_plugin_session(load_plugin_project(FIXTURE_ROOT))`
   → `connect()` refuses with `"vectors.json"` in the message — "a provider
   plugin has no mock script — the honest load refusal". The B1 mock arm
   (`test_ftdi.py:179-189`) pins `ByteStreamMockHost`'s `_FIELDS` gate
   directly. Both are the arms this slice's owner ruling narrows (§7).
10. **The evidence validator is dialect-agnostic; the walk validator is
    byte-shaped.** `validate_vectors_evidence` (`vectors.py:72-139`) judges
    only `evidence`/`recorded` keys and runs before dialect selection
    (`session.py:276-279`); provider rows can carry the same claim keys.
    `validate_vectors_walk_order` (`vectors.py:293-375`) drives the adapter
    over `_WalkDouble` (`:155-209`), which matches on `transaction["data"]`
    bytes and raises `vectors_walk_order_unwalkable` for any other transfer
    shape — a provider transaction is unwalkable by construction.
11. **The honesty surfaces classify by `transport_kind` alone.**
    `web.py:702` `simulated = seam.transport_kind == "mock"`; the banner is
    built from `simulated`/`replay` flags only — a provider-dialect mock
    session renders the simulated banner with zero presentation changes (the
    #568 record §0.5 verified the same fact for the live kind).
12. **The guide sentences this slice rewrites.** `user_guide/plugin-sdk.qmd`:
    `:361` ("writes no `vectors.json` (the mock cannot rehearse control
    operations)"), `:497` ("which of the two transaction dialects"), `:519`
    (demand order), `:527` (the three-cycle authoring rule), `:529` (what the
    mock can and cannot rehearse), `:569` (when to prefer the journal).

---

## 1. The ruling this design serves — §3's claim, tested against the code

The #568 record §3 argued: *"a `MockHost` script speaks transactions, and the
mock's two dialects are stream-shaped by construction; a bitmode call is not
a transaction shape a vectors script can carry — it is a device-boundary
act"* — and concluded that teaching `--transport mock` a third dialect
"would fork the script surface".

The reviewer's counter: `ScriptedFtdiDriver`'s script rows ARE provider rows
in the #564 journal row shape that `replay.py` already compiles and
validates, so a scripted dialect may be a small extension.

**The counter is right, on three independent pieces of shipped evidence.**
(a) A bitmode call IS a transaction at the services boundary —
`{"kind": "ftdi_control", "op": "set_bitmode", "mask": 15, "mode": 64}` with
response `{}` — and the #564 journal carries exactly that row (fixture row
"bitmode"). (b) The journal's provider arm already uses "MockHost's
exact-dict posture" as its match identity (`replay.py:349-351`) — the claim
that a MockHost script cannot express the row is refuted by the comment in
the module that ships both. (c) The dialect vocabulary was extended once
already (#394 added `send_receive`); the extension point is proven, not
invented. The §3 premise conflated two boundaries: at the DRIVER boundary a
bitmode call is a method call on hardware, and a vectors dialect cannot
carry that — but the mock never sees the driver boundary; it sees the
transaction boundary, where the row is a dict the exchange host already
matches.

**What survives of §3 is the fidelity claim, and it survives as design
content, not as an argument against building.** A mock dialect matches at
the transaction boundary, so it does not exercise `FtdiCaptureServices`'
ladder — grammar-first refusal, declared limits, the busy guard, op-table
dispatch, result validation, the fault latch, the `SerialLink` receive
ladder. The driver double does (it sits one boundary down, under the real
services). That difference is the division of proof §3 states, and this
design keeps it verbatim (§3 of this record): both mechanisms ship, each
proves what it proves, and the guide says which to reach for.

The committed #568 record is frozen history and is not retrofitted; this
record's §7 carries the amendments its arms need, under the owner ruling
that add the dialect.

---

## 2. The mechanism

### 2.1 The dialect and the document

`_DIALECTS` grows to `("stream_exchange", "send_receive", "provider")`
(`session.py:181`). The provider dialect's `vectors.json`:

```json
{
  "evidence": "synthetic",
  "transaction_dialect": "provider",
  "exchanges": [
    {"name": "reset",    "transaction": {"kind": "ftdi_control", "op": "reset_device"}, "response": {}},
    {"name": "bitmode",  "transaction": {"kind": "ftdi_control", "op": "set_bitmode", "mask": 15, "mode": 64}, "response": {}},
    {"name": "pins-idle","transaction": {"kind": "ftdi_control", "op": "read_pins"}, "response": {"data": "AA=="}},
    {"name": "bitstream","transaction": {"kind": "stream_send", "data": "deadbeefcafebabe"}, "response": {}},
    {"name": "status",   "transaction": {"kind": "stream_exchange", "data": "55a1", "max_bytes": 8, "termination": "lf", "exact_bytes": 4},
                              "response": {"data": "c200015a"}}
  ]
}
```

The row shape is the #564 journal row shape, unchanged — `{"name",
"transaction", "response"}` — with the journal's own payload spellings: hex
for §8.1 stream `data`, base64 for the grammar's byte-valued fields. The
name **"provider"** names the conversation family it scripts (the codebase's
own vocabulary: "provider kinds", the scaffold's `provider_transport`
flag); it admits the pinned grammar's provider kinds AND the §8.1 stream
kinds in one document, because a provider plugin's bring-up is
provider+stream by nature (the fixture's 9 rows are exactly that mix — the
journal's own row vocabulary, not a mix of dialects).

### 2.2 The compile (`session.py`, provider arm)

`vectors_script`'s front half (file read at `session.py:267-268`, evidence
validation `:276-279`, dialect extraction `:280-285`) is factored out as the
shared entry; the stream row loop stays put for the two stream dialects. A
new `provider_script(plugin) -> tuple[list[tuple[dict, dict]], int]` compiles
the provider dialect:

1. **Pin and grammar.** `verify_provider_pin(plugin.descriptor, path)`
   (`benchweave_sdk.validation`) — `None` refuses
   `standalone_vectors_provider_unpinned:` (a provider-dialect corpus
   requires a pinned contract; wrapped to `PluginLoadError`, the connect
   seam's typed `not_ready`, the `:276-279` plumbing). `_grammar(pinned)`
   (lazy import from `.replay`, the `session.py:488` precedent — replay
   imports session at module level, `replay.py:92`, so this import MUST be
   function-level).
2. **Rows.** `replay.py:_load_row` gains a `code` parameter (default
   `"replay_journal_row_shape"` — every existing raise interpolates it; the
   journal lane's message pins are byte-identical by construction). The
   provider arm calls it with `code="standalone_vectors_row_shape"` so the
   refusals name the vectors document, never "journal". One validator, two
   documents — the anti-drift rule `vectors.py`'s own docstring states ("a
   host that disagrees with the plugin's own test would train authors to
   ship what the gate accepts by luck").
3. **Exchanges.** Each `ReplayRow` maps to one MockHost exchange: provider
   rows `(row.expected, dict(row.result))`; stream send/exchange/receive
   rows `(row.expected, {"data": row.response})` (a `stream_send`'s journal
   response is `{}` → the empty dict; the ABI-form decode is `_load_row`'s
   own).
4. **Establishment.** `establishment, _unit, _rotate = _replay_cycle_plan(rows)`
   (`replay.py:581-611`, reused verbatim — the rows ARE `ReplayRow`s);
   return the establishment. `_rotate` is deliberately not consumed:
   `LoopingMockHost` cycles its WHOLE tail in captured order, which already
   replays a mid-unit tail at its captured phase; unit-head restore with
   rotation is the `send_receive` dialect's refinement (§8, bound D4).

`mock_transport_factory` (`session.py:474-504`) gains the dispatch: dialect
`"provider"` → `LoopingMockHost(exchanges, establishment=establishment)`.
**No new host class. No change to `LoopingMockHost`, `ByteStreamMockHost`,
or `MockHost`.** The plain exchange host already matches arbitrary
transaction dicts exactly (`testing.py:219-221`), already enforces the
dispatch marker for non-receive kinds (`:213-216` — a control op IS a
transmit, the same discipline `FtdiCaptureServices` enforces at
`ftdi.py:748-749`), and already refuses mismatch and exhaustion with
`ConformanceError` naming both sides.

### 2.3 What the recycle postures mean (mock vs replay, restated)

A corpus that proves a repeating unit (e.g. the status poll authored three
times — the guide's own three-cycle rule, `user_guide/plugin-sdk.qmd:527`)
derives that unit's boundary and recycles it: sustained mock serving works.
A corpus with no derivable unit gets `_replay_cycle_plan`'s `(1, None, 0)`
fallback; `LoopingMockHost` then cycles the whole tail after row 1 — the
MOCK's own ambiguous-corpus rule, exactly the split `replay.py:584-590`
documents (a mock may recycle an ambiguous corpus; a RECORDING that cannot
prove periodicity plays once and exhausts honestly). That difference is a
named, guide-stated property of the two surfaces, not an accident.

---

## 3. The division of proof — what each mechanism proves

| Mechanism | Boundary | Proves | Does not prove |
|---|---|---|---|
| Mock dialect (`--transport mock`) | transaction (the adapter's `transfer` dicts) | The adapter's conversation SHAPE: the right transactions, right order, right params, right bounds; correct handling of each scripted result; envelope discipline (dispatch marker, exhaustion, mismatch refusal) | The executor ladder (grammar refusal, declared limits, busy guard, op dispatch, result validation, fault latch); receive-outcome computation (responses are scripted, the `stream_exchange` dialect's own fidelity class); anything about a device |
| Driver double (generated test, `ftdi_plugin_session` + `ScriptedFtdiDriver`) | driver call (one below the services) | The PRODUCTION path: grammar validation, feature gate, limits, busy guard, dispatch marker, op-table dispatch, result validation, the real `SerialLink` receive ladder over `FtdiStreamAdapter`, the capture sidecar — everything but USB | Anything about a device; the transport serving surface (it is in-process) |
| Replay (`--transport replay` + journal) | transaction, over RECORDED rows | The conversation against evidence with provenance (recorded_at, journal sha256 in the sidecar), pinned to the recorded contract revision | Device behavior (it is a recording); the executor ladder (same as mock) |
| Live (`--transport ftdi` + device) | the device | The device itself | — (out of scope here; #568) |

**When a plugin author reaches for which** (the guide text, §6): iterate on
the adapter and protocol builders against the mock (fastest, the default
transport, no journal needed); prove the executor path with the generated
driver-double test (it runs in the emitted suite on every `pytest`); answer
"what did the device actually do" with a recorded journal on replay; prove
the device with `--transport ftdi`. The mock and the double consume ONE
document (§4) so they cannot drift apart.

---

## 4. The scaffold

- **`copier.yml`**: the `_exclude` entry becomes `{% if not provider_transport
  %}ftdi-control-provider.json{% endif %}` — the provider shape now renders
  BOTH the pinned contract and `vectors.json`; the comments at `:12-17` and
  `:26-32` are rewritten to the owner-ruled posture (they currently state the
  superseded §3 rationale). The serial default is unchanged.
- **`template/src/{{package_name}}/vectors.json.jinja`** gains the provider
  branch: `transaction_dialect: "provider"`, `evidence: "synthetic"`, and the
  bring-up rows (the same conversation the generated `_script()` builds
  today: reset, purge-rx, latency, baud, bitmode, pins-idle, bitstream,
  pins-done, then the status poll authored three times so the derived unit
  sustains mock serving — `protocol.py.jinja:26-99`'s constants are the
  literal source: `"AA=="`/`"gA=="` pins, `deadbeefcafebabe`, `55a1`/
  `c200015a`).
- **`template/tests/test_plugin.py.jinja`**, provider branch: `_script()`
  becomes a read of the plugin's OWN `vectors.json` `exchanges` (one
  document; the driver-double test's role is unchanged — it now consumes the
  corpus instead of hand-built rows, so the corpus and the rehearsal cannot
  drift). Two new generated tests:
  - `test_bring_up_rehearses_on_the_mock`: `mock_plugin_session(
    load_plugin_project(project))` → connect → read `line_status` →
    `status: "ok"`, value `0x5A`; then assert `session.services`' recorded
    `transfers` equal the corpus transactions in order (the exact-dict
    consumption trace) and `assert_complete()` (no orphan rows).
  - `test_vectors_evidence_claims_carry_recorded_bytes` (the serial branch's
    own test, lifted verbatim — the anti-circularity invariant now that the
    shape carries a corpus).
  The walk-order test is NOT generated for the provider branch (§8, D1).
- **The emitted tree ships no journal file** — the #570 acceptance's "no
  journal" clause is a property of the scaffold output, pinned by the
  fixture lattice (`tests/fixtures/scaffold_expected/provider/` gains the
  vectors file and the two tests; byte-parity as usual).

---

## 5. Honesty (A06) — the four states and their naming surfaces

- **The banner discloses by construction.** A provider-dialect session runs
  under `transport_kind == "mock"` → the SIMULATED banner (`web.py:702`;
  `presentation.py` builds from `simulated`/`replay` only). No presentation
  change exists to make. **No sidecar field is needed**: `LoopingMockHost`
  has no capture members (the plain exchange host's own posture — capture on
  a mock session is the capture-services refusal, #569's domain), so there
  is no sidecar to stamp; unlike replay (sidecar `transport: "replay"` +
  journal sha256 + recorded_at) and ftdi (sidecar `transport: "ftdi"` +
  provider digest), the mock's evidence claim lives in the corpus's own
  `evidence` vocabulary — synthetic by default, claiming nothing.
- **What a reader can tell apart, on which surface.** (1) Scripted mock
  rehearsal: `transport: "mock"` on every state surface, SIMULATED banner,
  corpus is `vectors.json` (`evidence: synthetic` unless hand-recorded). (2)
  Driver-boundary rehearsal: not a served session — no banner; in-process,
  in the emitted suite; disclosed by the double's own docstring and the
  corpus's synthetic claim. (3) Replay: `transport: "replay"`, REPLAY
  banner, sidecar carries the journal digest and recorded_at. (4) Live:
  `transport: "ftdi"`, LIVE banner, sidecar carries the contract digest.
  The provider dialect adds NO new surface that could blur these: it reuses
  the mock's existing names.
- **Diagnostics never claim recording.** The mock's refusals are MockHost's
  own (`Expected {...}, got {...}`, `Unexpected transfer: no scripted
  exchange remains`) — no "recording" language, which is precisely why the
  provider dialect does NOT serve through `ReplayHost` (its messages say
  "the recording expects...", a lie for a synthetic corpus, and its sidecar
  names replay). The compile's refusals say `standalone_vectors_*:` and
  name the file, never "journal".

---

## 6. Refusal discipline and the grammar ruling

- **Mismatch refuses in the mock's existing manner** (the issue's own
  wording): exact-dict `ConformanceError` naming expected and got
  (`testing.py:219-221`); exhaustion refuses honestly (`:217-218`). A
  transaction of a kind that is neither grammar-admitted nor §8.1 refuses
  the same way — the exchange host's manner, same as the `stream_exchange`
  dialect today (the explicit `_FIELDS` ValueError gate is the byte-stream
  host's manner, untouched).
- **One file, one dialect.** A journal-shaped row under a stream dialect
  refuses `standalone_vectors_row_unscriptable:` (response-only under
  `stream_exchange`, `session.py:339-345`); a stream-shaped
  (`request`/`response` payload) row under `provider` refuses at
  `_load_row`'s transaction-is-not-an-object arm. Within `provider`,
  provider rows and §8.1 stream rows are BOTH admitted — that is the
  journal's row vocabulary, the bring-up's own shape, not a dialect mix.
- **`encoding` refuses if present under `provider`** (file or row level):
  the provider rows spell their own payload forms (hex for §8.1 data,
  base64 for grammar b64 fields — the journal's spelling), so an `encoding`
  key would be a silent no-op. Typed refusal in the
  `standalone_vectors_*` family, naming the incompatibility. (Flippable to
  ignore-and-document — §13.)
- **The grammar ruling (issue question 7): the mock validates the CORPUS at
  load; the executor validates the TRANSACTION at dispatch; the mock does
  NOT re-validate at match.** Load-time: every provider row's transaction
  AND response validate against the pinned contract's grammar through the
  shared `_load_row` (replay's own two-sided validation,
  `replay.py:363-375`) — a rehearsal may not rehearse a conversation the
  pinned grammar forbids; the script is honest by construction, and the
  refusal is the typed load refusal (connect `not_ready`), never a served
  lie. Match-time: the exact-dict match against a load-validated expected
  dict makes transfer-time grammar checking redundant by transitivity (an
  adapter transaction that matches a validated expected IS
  grammar-valid; one that differs refuses the mismatch), and a second
  grammar ladder inside the mock would be a drift surface — two validators
  to keep in sync, the exact anti-pattern `vectors.py`'s docstring names.
  The executor's grammar-first refusal stays the executor's job and stays
  proven by the driver-boundary rehearsal and the #568 B-arms.
- **A `recorded_failure` row under `provider` refuses** (typed, naming the
  bound) — failure scripting is deferred (§8, D2) and the driver double's
  `fault_writes`/`fault_reads` cover fault rehearsal meanwhile.

---

## 7. Cross-slice impacts — the #568 amendments (stated, not silent)

The owner ruling narrows two landed #568 arms. Both amendments
STRENGTHEN the pinned posture; neither deletes a refusal.

1. **C5's second half** (`test_ftdi.py:690-695`, "a provider plugin has no
   mock script"). After this slice the `ftdi_control_plugin` fixture gains a
   provider-dialect `vectors.json` (§8 of the test plan), so its connect
   succeeds. The amended arm pins THREE refusals where it pinned one:
   (i) `ByteStreamMockHost` still refuses provider kinds (unchanged, the
   first half); (ii) a provider plugin whose vectors.json declares a STREAM
   dialect refuses at load — its rows cannot script control ops (the
   compile-level refusal); (iii) a provider plugin with NO vectors.json
   still refuses the honest load refusal naming vectors.json (constructed
   in-test from the fixture minus the corpus). The mirror arm
   (unpinned-on-ftdi) is untouched.
2. **B1's mock arm** (`test_ftdi.py:179-189`) and the #568 record's
   `transport.py:377-381` citation: UNCHANGED and still passing — this
   design does not touch `ByteStreamMockHost` or its `_FIELDS` gate; the
   stream dialects keep refusing provider kinds exactly as pinned. What
   changes is the record-level claim "the plain mock refuses provider
   kinds" → "the plain mock's STREAM DIALECTS refuse provider kinds; the
   provider dialect serves them from a grammar-validated corpus".
3. **The record chain**: the #568 record is frozen history. This record's
   §1 and §7 are the amendment of record; the guide sentences citing the
   old posture (`plugin-sdk.qmd:361`) are rewritten by this slice's build.

A third-order impact: the fixture's two documents (`bring-up-journal.json`
and the new `vectors.json`) carry the same conversation. A parity guard
test pins them equal (name/kind/params/data, order) — one conversation,
two documents, three consumers (double, mock, replay-lane validation).

---

## 8. Named bounds and reopen triggers

Nothing #570 names is parked — scope 1 (scaffold corpus), scope 2 (the
dialect), scope 3 (guide) all land here. These are capability bounds of the
designed dialect, each with its reopen trigger:

| Bound | What does not ship | Reopen trigger |
|---|---|---|
| D1 | Walk-order rehearsal for provider corpora (`_WalkDouble` is byte-shaped; a provider transaction is unwalkable by construction, `vectors.py:187-189`) | the first provider plugin whose descriptor walk has enough readable parameters that row-to-parameter mapping needs its own check |
| D2 | Failure rows in provider corpora (`recorded_failure` → a scripted exception, MockHost's Exception-response slot) | the first corpus that needs a scripted failure outcome (the double's fault flags cover fault rehearsal meanwhile) |
| D3 | Computed receive outcomes for provider corpora's stream rows (the `ByteStreamMockHost` ladder) — responses are scripted, the `stream_exchange` dialect's own fidelity class | the first provider plugin whose stream receives need quiet-line/terminator-outcome fidelity ON the mock (the driver double's real `SerialLink` provides it in the emitted suite) |
| D4 | Mid-unit phase rotation (`_replay_cycle_plan`'s rotate) — the whole tail recycles in captured order | a hardware-recorded provider corpus ending mid-unit where phase continuity matters |
| D5 | A byte bound for provider corpora (the stream dialects carry none; journals carry the 1 MiB limit) | the first corpus large enough to matter |

---

## 9. Invariants, drift obligations, CI

- **Invariants:** no CTL/STO/CON/REG motion — the SDK invariants doc carries
  no vectors/mock row (verified this session), and the gateway invariants
  do not govern the SDK's standalone surface. The A06-relevant postures are
  restated, not new: simulated banner by construction (§5); never-fabricate
  (scripted responses are labelled synthetic evidence; refusals never claim
  recording); no laundering (the mock's surfaces never name replay or ftdi).
- **Obligations walked** (`docs/internal/drift-and-obligations.md`): the
  scaffold lattice row — `tests/fixtures/scaffold_expected/provider/` and
  the R-2 byte-parity arms move with the template; the guide row —
  `user_guide/plugin-sdk.qmd` `:361/:497/:519/:527/:529/:569` and the
  README's transports paragraph (checked at build: it is updated only if it
  names the dialect count); the agent-asset row — `template/AGENTS.md.jinja`
  and kin are checked for rehearsal wording at build; `test_getting_started`
  and `test_agent_assets` keep passing untouched (the pedagogy pages are
  judged-not-touched unless they name the dialect count — checked at build).
  Operator-facing prose legs dispatch the `document-writer` agent (the STE
  register rule).
- **Standards:** none — the standards corpus carries no vectors schema
  (verified: no `vectors.json`/`transaction_dialect` hit under
  `standards/`). No version-literal motion. One SDK PR, no gateway commit,
  no submodule pointer, no dependency change.
- **CI cost:** negligible — the `scaffold-and-check` lane runs two more
  generated tests; no new lane; the provider grammar compile at connect is
  replay's own per-reconnect posture.

---

## 10. Pre-committed acceptance rule

Written before any measurement ran. All arms are deterministic conformance;
every measurement is this lane's on this machine unless named otherwise
(CI's scaffold-and-check lane reproduces A independently). The sentence
this rule serves, from issue #570: *"A provider plugin rehearses a full
sequence against the mock with no hardware and no journal."*

**Metric A — the sentence, by execution.**
- **A1 (the scaffold emits the corpus):** `benchweave-sdk new
  --provider-transport <tmp>/demo` emits `src/<pkg>/vectors.json` declaring
  `transaction_dialect: "provider"` with ≥ 9 journal-shaped rows (≥ 6
  provider control rows including both `read_pins`, ≥ 1 `stream_send`, ≥ 1
  `stream_exchange`, the status poll authored 3×); the emitted tree contains
  NO journal file (`*journal*.json` glob empty) and names no hardware.
- **A2 (the emitted suite passes, including the mock rehearsal):** `uv run
  pytest` in the emitted project exits 0 with collected count ≥ 7 (the
  provider branch's existing 5 + the mock-rehearsal test + the evidence
  test), where `test_bring_up_rehearses_on_the_mock` connects
  `mock_plugin_session(load_plugin_project(project))`, reads `line_status`
  → `status: "ok"`, value `0x5A`, asserts the recorded `transfers` equal the
  corpus transactions in order, and `assert_complete()`s.
- **A3 (the serve surface loads it):** `_build_seam(<project>,
  transport="mock")` constructs and a connect establishes identity — the
  default transport, the author's first reach, with no hardware and no
  journal anywhere in the tree.

**Metric B — the RED controls (single-point reversions at the build head;
each MUST redden its named arm — a `no tests ran` collection is a FAILED
arm, not evidence; 5/5 required).**
- **B1:** revert the dialect dispatch to the two stream names → A2's mock
  test refuses `standalone_vectors_dialect_unknown:` at connect → reddens.
- **B2:** neutralize the provider-arm row validation (skip the shared
  validator) → the doctored-corpus arm (a vectors row violating the pinned
  grammar, e.g. a `read_pins` response carrying a non-base64 `data`) must
  refuse at load; neutralized it loads → reddens.
- **B3:** neutralize exact-dict matching (match on `op`, ignore params) →
  the doctored-corpus arm (vectors `set_baud` 57600 against the adapter's
  115200) must `ConformanceError`; neutralized, the rehearsal "passes" a
  wrong conversation → reddens.
- **B4:** revert the copier exclusion (provider excludes vectors.json
  again) → A1 fails: no corpus emitted → reddens.
- **B5:** drop the establishment pass (hardwire `establishment=1`) → the
  sustained-poll arm (a 4th `line_status` read beyond the three authored
  polls must still serve from the recycled unit) reddens.

**Metric C — cross-slice integrity (all must pass; 4/4).**
- **C1:** the #568 B1 mock arm passes UNCHANGED (`ByteStreamMockHost`'s
  `_FIELDS` gate is untouched).
- **C2:** the amended C5 pins its three refusals (§7.1) plus the unchanged
  unpinned-on-ftdi mirror arm.
- **C3:** the parity guard: the fixture's journal rows and its vectors
  exchanges carry the same conversation, pinned equal.
- **C4:** the honesty surfaces: a provider-dialect mock session renders the
  SIMULATED banner (string-pinned against `presentation.py`'s fixture
  literals) and reports `transport: "mock"` on the state surfaces; no
  provider-dialect mock surface carries "replay" or a journal digest.

**Ship direction:** A (A1–A3) + B (5/5, each with RED evidence in the commit
message) + C (4/4) green under the FAST lane at every commit and the full
battery before push.

**Kill directions.** *Kill the slice:* any B arm cannot be reddened by its
single-point reversion (the mechanism is inert or the measurement is
gameable); or the emitted suite passes with the dialect reverted (B1's
control direction — the acceptance sentence is then being satisfied by
something other than the mock dialect). *The measurement is underpowered,
not conclusive:* an arm that cannot be authored honestly (e.g. B5's
observable turns out unobservable for the demo's consumption pattern) is
RE-STATED with a different observable — never weakened; if no observable
exists, that is a recorded design finding, not a silent arm-drop.

---

## 11. Risks, ranked, with falsifiers

- **R1 — exact-dict bounds mismatch (highest).** The adapter's stream
  transactions must equal the corpus rows WHOLE-DICT, bounds included; a
  builder that computes `max_bytes` from the descriptor while the corpus
  hardcodes it mismatches forever. *Falsified by:* A2 reddening with a
  mismatch naming the bounds. *Mitigation:* the scaffold authors the corpus
  from the same constants the builders use (`protocol.py.jinja:26-99`), and
  the generated test pins the agreement on every run — drift reddens both
  rehearsals.
- **R2 — import cycle.** `session.py` cannot import `replay.py` at module
  level (`replay.py:92`). *Falsified by:* ImportError at first provider
  connect. *Mitigation:* the function-level lazy import (the
  `session.py:488` precedent), called out in §2.2.
- **R3 — the C5 amendment reads as post-hoc weakening.** *Falsified by:*
  review. *Mitigation:* the amendment pins three refusals where one was
  (§7.1) and cites the owner ruling; nothing that refused before serves
  silently now — the no-corpus and stream-dialect refusals remain pinned.
- **R4 — `_load_row`'s `code` parameter churns the journal lane.**
  *Falsified by:* any replay-suite red. *Mitigation:* the parameter defaults
  to today's literal; the journal lane's messages are byte-identical.
- **R5 — the transitivity argument has a hole** (a matching transaction
  that is somehow grammar-invalid). *Falsified by:* constructing one — an
  expected dict built by the load-validated `_load_row` provider arm whose
  equal is rejected by the same validator. None exists by construction; B2
  pins the validator's presence. If a hole is ever found, the fix is
  match-time validation, and §6's ruling flips with it.
- **R6 — connect-path cost** (grammar compile per connect). *Falsified by:*
  a measurable connect regression. *Mitigation:* replay's own
  per-reconnect posture; 9-row corpora pay microseconds.

---

## 12. Review tier and the Step-1 keyword scan (#254)

**Tier 3** under this repository's rubric (`docs/internal/review-rubric.md`
Step 1), two rules firing: **"changes a refusal prefix or adds a refusal
path"** (new `standalone_vectors_*` refusal paths — the provider-arm row
refusals, the unpinned-corpus refusal, the `encoding`-under-provider
refusal, the `recorded_failure`-under-provider refusal, and the
dialect-enumeration message text) and **"touches scaffold output shape"**
(the provider scaffold gains `vectors.json` and two generated tests —
generated projects are the SDK's public face). The G6 adversarial refute
lane is therefore mandatory for the build.

**Keyword scan over the expected diff** (files: `session.py`, `replay.py`,
`copier.yml`, `template/src/*/vectors.json.jinja`,
`template/tests/test_plugin.py.jinja`,
`tests/fixtures/scaffold_expected/provider/**`, `tests/server/test_ftdi.py`
amendments, new `tests/server/test_mock_provider.py`,
`tests/fixtures/ftdi_control_plugin/**/vectors.json`,
`user_guide/plugin-sdk.qmd`, `README.md`):

| Keyword | Count | Where |
|---|---|---|
| `asyncio` | ≥ 4 | new/extended tests (`asyncio.run` arms) — also Tier-3 under the gateway keyword list |
| `threading` | 0 | — |
| `subprocess` | 0 | — |
| `sha256` | 0 | the compile delegates to `verify_provider_pin`/`_grammar`; no digest literals enter the diff |
| `hashlib` | 0 | — |
| `migrate` | 0 | — |
| `recovery` | 0 | — |
| `protection` | 0 | — |

No `standards/` path, no JSON Schema, no `validation.py`/`conformance.py`/
`fixtures.py`, no `pyproject.toml`/`uv.lock`, no parent-checkout reach, no
submodule pointer (this is the SDK repository's own PR).

---

## 13. Open decisions for the maintainer

1. **`encoding` under `provider`: refuse (designed) or ignore-and-document.**
   Refusing is stricter (STD-4 posture: a meaningless key is surfaced, not
   silently swallowed); ignoring is gentler on hand-edits. Designed: refuse.
   Flippable at build with one test arm either way.
2. **The fixture placement.** The design adds `vectors.json` to
   `ftdi_control_plugin` (one provider fixture, both rehearsal documents, a
   parity guard pinning them equal) and amends C5 accordingly. The
   alternative — a second, mock-only fixture — keeps every #568 arm
   byte-identical but leaves two provider fixtures free to drift. Designed:
   one fixture, amended arm. Flip cost: small, before build starts.
3. **The dialect name.** `"provider"` (designed). Alternatives weighed:
   `"provider_script"` (longer, no clearer), `"journal_rows"` (names the row
   shape but implies recording — dishonest for a synthetic corpus). Nothing
   pins the name yet; free until the scaffold emits it.
4. **Whether the README's transports paragraph needs the dialect sentence**
   — decided at build by reading the paragraph; the obligation row already
   covers it either way.
