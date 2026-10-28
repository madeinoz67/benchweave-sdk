# Issue #568 — the live FTDI provider transport (`--transport ftdi`)

**Date:** 2026-10-28
**Scope:** the SDK-side live executor for transport-provider transactions (gateway
issue #568): a third standalone transport that opens an FTDI-class USB device,
serves the pinned contract's provider kinds against the real hardware API, and
serves the generic §8.1 stream kinds over the same device's data pipe. The
plugin-side adapter work stays on #562; recorded replay is #564 and is not
touched.
**Verdict up front:** BUILD — option 2 (a third transport), exactly as the issue
recommends. **Amended 2026-10-28** (same day, before any measurement ran) to
conform to the tracker ruling `issuecomment-6459863366`: mock parity rides in
this slice (§3), hardware proof is deferred and unclaimed (§6, §8), one
follow-on issue only (§7); the four-lane verification-matrix comment the
ruling answered was itself re-verified row by row (§0.11), not adopted. The code makes option 1 worse than the issue's prose says: mixing
provider kinds into `serial.py` is not merely against the refute wave's pinned
separation, it is structurally contaminating, because the §8.1 field set is one
shared definition consumed by the serial backend, the mock, and replay
(§1). The third transport costs one new module plus one CLI branch, and every
load-bearing piece of it — grammar compile, pin verification, the serving
ladder, the seam wiring, the mode banner — has a proven in-tree precedent this
design extends rather than invents.

**Triage:** PUBLIC. No person, client, bench name, serial, commercial term, or
one-install operational specifics below; hardware provenance already public in
the tracker is cited as provenance only. Same register as the #562/#564 record
this continues.

---

## 0. Grounding — what was verified, against which bytes

Every code claim below was read this session at SDK `origin/main` = `39043cc`
(v0.23.0, the merge of #567's lane). Line numbers are from that commit. The
tracker was read live over `gh` (issues #562 and #568, all 17 #562 comments).

1. **The split the issue names is real and three-sided.**
   - `src/benchweave_sdk_server/serial.py:11` — the module docstring's own
     claim, "no custom serial provider grammar exists on this backend".
   - `src/benchweave_sdk_server/serial.py:65-70` — `_FIELDS` admits only
     `stream_send`/`stream_receive`/`stream_exchange`.
   - `src/benchweave_sdk_server/serial.py:728-732` — the live backend's
     refusal: `kind not in _FIELDS or set(transaction) != _FIELDS[kind]` →
     `ValueError("not a section 8.1 stream transaction: ...")`.
   - `src/benchweave_sdk_server/transport.py:377-381` — the byte-stream mock
     refuses through the SAME imported `_FIELDS` (`transport.py:37`).
   - `src/benchweave_sdk_server/replay.py:345` — the accepting line: a journal
     row whose `kind` is in the pinned grammar's compiled kinds is a provider
     row, served (`replay.py:1087-1099`).
2. **The contract instance exists and is complete.**
   `src/benchweave_sdk/providers/ftdi-control-1.0.0.json`: one grammar kind
   `ftdi_control` with the seven-op `oneOf` discriminator
   (`reset_device`, `set_timeouts`, `set_latency`, `set_baud`, `purge`,
   `set_bitmode`, `read_pins`), `read_pins` result exactly one base64 byte
   (`:81-105`), `security_scope: commissioned_connection`
   (`:116`), and `host_requirements` whose summary reads "No filesystem paths,
   no process spawning, no network endpoints" with `native_libraries: []`
   (`:117-121`).
3. **The replay lane already built the reusable half.** Grammar compile
   (`replay.py:206-222` `_grammar` + `:195-203` `GrammarEntry` + `:156-192`
   `_base64_props`), pin-and-digest
   (`replay.py:606-621` `_pinned_contract` → `validation.py:748-908`
   `verify_provider_pin`), per-transaction grammar-first refusal
   (`replay.py:966-985` `_validate_provider`), the connect-time re-verify of
   the CURRENT plugin's pin (`replay.py:1115-1162` `replay_plugin_session`,
   the factory at `:1134-1153`), and the capture sidecar that names the
   transport (`replay.py:822-845`).
4. **The serial lane already built the live half.** The injectable transport
   surface (`serial.py:119-132` `Transport`, "injectable so tests never need a
   real port"), the reader-thread link with the full receive ladder
   (`serial.py:135-409` `SerialLink`; `take`'s exact/terminator/quiet-line/
   retained-partial semantics at `:283-356`), the live services class
   (`serial.py:632-764` `SerialCaptureServices`; the ladder order in
   `transfer`'s docstring at `:723-727`, dispatch-marker enforcement
   `:739-746`), the link-control busy guard over `receive_depth`
   (`serial.py:916-926`), the closed-session posture (`:766-773`, `:897-901`),
   and the lazy-import missing-dependency refusal
   (`serial.py:1039-1050` `open_serial_port` →
   `standalone_serial_pyserial_missing:` with the `[server]`-extra install
   hint).
5. **The seam accepts a new transport kind without motion.** `StandaloneSeam`
   takes `transport_kind: str` freely (`seam.py:212-222`); the serial-only
   arms branch on `== "serial"` (`seam.py:224`, `:367`, `:507`;
   `web.py:796`, `:811`, `:833`, `:1580`) and a new kind simply does not enter
   them. The mode banner classifies by exclusion:
   `web.py:702` `simulated = seam.transport_kind == "mock"`, and
   `presentation.py:154-184` builds the banner from `simulated`/`replay` flags
   only — a third live kind renders the live banner with **zero** presentation
   changes. `transport_kind` already flows into every state surface
   (`seam.py:494`, `:876`, `:1706`).
6. **CLI transport selection is one function with a hoisted guard block.**
   `cli.py:140-340` `_build_seam`; the flag-agreement guards
   (`cli.py:209-247`: `--replay` replay-only `:216-231`, `--device`
   serial-only `:232-238`, `--bindings` serial-only `:239-247`) run before any
   branch builds — the refute fold's F2, which exists precisely so a flag
   disagreement never resolves toward the live device; the choice set at
   `cli.py:364`; serve's fail-fast precedent (a refused journal is exit 2
   before any port binds, `cli.py:307-320`).
7. **Connect-time failure mapping is typed end to end.** A factory exception
   is wrapped `RuntimeError("standalone_plugin_connect: …")`
   (`session.py:860-867`); the seam maps `RuntimeError` → `not_ready` carrying
   the message, `TimeoutError`/`ConnectionError` → `not_ready`,
   `ConformanceError` → `unavailable` (`seam.py:604-630`). The closed
   `ERROR_CODES` set (`errors.py:26-36`) needs no new member.
8. **The dependency is new.** `pyftdi`/`pyusb`: zero hits in `uv.lock`;
   `pyproject.toml:44-63` is the `[server]` extra, with pyserial's own
   precedent comment at `:57-59` ("pyserial rides the server extra ONLY — the
   default install never gains it").
9. **The fixture precedent.** `tests/fixtures/replay_hid_plugin/` is a full
   provider-declaring fixture plugin (`transport.type: "custom"` + the
   `provider` object with `feature_id`/`id`/`path`/`sha256`, pinned
   descriptor-relative; `required_features` carrying the provider feature;
   `otdp_version: 0.2.4`), driven by `tests/server/test_replay.py` through
   both direct session construction and `_build_seam`.
10. **The tracker gap is closed.** #562's SDK-labelled rows: row 1 is this
    lane (contract + replay landed as #564; the live executor is #568);
    rows 12-15 landed as #566/#567 (`39043cc`); rows 2, 4, 5, 6, 7, 8-11, 16
    remain open SDK/standards rows with their own homes ("a separate issue,
    on owner word") — **none of them is the live provider transport**, so no
    sibling lane collides with this work. Rows 5 (short-write guide note) and
    6 (worktree path note) touch the same user guide file; different sections,
    coordination note only.

11. **The 2026-10-28 tracker inputs: a four-lane verification matrix comment
    (03:20:19Z) and a binding ruling (issuecomment-6459863366).** Every matrix
    row this design relies on was re-verified in the source this session, not
    adopted from the comment: the live-provider GAP (`serial.py:728-732`,
    `transport.py:377-381`, replay accepts journal-admitted kinds only at
    `replay.py:345`); the capture-services duck-check
    (`seam.py:1737-1748` — `callable(getattr(services, name))` over
    `configure_capture`/`capture_progress`/`artifact_finalise`) against the
    Protocol set (`interfaces.py:59-110` `HostServices` declares
    `monotonic`/`utc_now`/`transfer`/`close_transport`/`record_evidence` only;
    `CaptureServices` at `:114-152` adds the three artifact members and does
    NOT declare `configure_capture`/`capture_progress`); and the scaffold gap
    (`src/benchweave_sdk/cli.py:66-71` — `new` carries no transport variant;
    `copier.yml` carries no transport knob). Two corrections to the matrix's
    framing: (a) the "non-stream services absent from HostServices" row is a
    fact about the Protocol set but not a wall for this design — the seven
    control ops are TRANSACTIONS over `transfer()` (the corpus's own
    grammar-extends-the-table design), not Protocol members, so live dispatch
    needs no `interfaces.py` motion; (b) the capture duck-check PASSES on
    this transport (`WriterBackedCaptureServices` implements all three
    members, `serial.py:450`/`:481`/`:577`, and `FtdiCaptureServices`
    inherits them), so that gap is separable from this slice — §1.5. The
    ruling binds four things into the design: option 2 stands; **mock parity
    rides in this issue** (§3, rewritten); **hardware proof is deferred and
    unclaimed** (§6, §8, §9.1, rewritten); **one follow-on issue only**
    (capture services, §7 restructured) with the scaffold variant carried as
    a deferral-table row.

**Inference, not verified this session (flagged):** the pyftdi API surface
(the `ftdi_sio`-class call names, and that `import pyftdi` succeeds without a
system libusb while `open` fails without one) — pyftdi is not installed in
this venv and was not imported; the build verifies both. Everything else above
was read in the source this session. The `transport-providers.md` corpus rules
are cited through the #562 design record and the schema's own description
(`otdp-transport-provider.schema.json`: "The host validates provider
transactions against the admitted contract's grammar, never against the
generic table"); the rules doc itself is not in the SDK's vendored tree
(machine-checkable schemas only) and the local gateway checkout is stale past
0.2.3.

---

## 1. The home decision — option 2, scored against the code

**Option 1 (inside the serial backend) is structurally contaminating, not just
aesthetically wrong.** `_FIELDS` (`serial.py:65-70`) is not the serial
backend's private vocabulary — it is the ONE shared §8.1 definition imported by
the mock (`transport.py:37`) and by replay's row loader (`replay.py:89`, whose
`_RECEIVE_FIELDS` comment states the discipline outright: "one definition
family; no second frozenset"). Admitting `ftdi_control` into serial's grammar
would change what every §8.1 surface on all three hosts accepts, or else fork
the definition family the repo just finished unifying. The refute wave's F2
(a serial transport told to replay refuses; `cli.py:209-215`'s comment block)
pinned the same principle one mode over: one transport, one grammar.

**Option 2's real cost is one module and one branch.** The seam, the banner,
the state surfaces and the error vocabulary all admit a fourth `transport_kind`
string with no motion (§0.5, §0.7). What is genuinely new — the FTDI device
executor — is new under either option.

**No cleaner third shape exists in-tree.** The two-mode precedent
(serial = live wire, replay = recorded wire) is exactly the shape this extends
to three: `ftdi` = live provider wire. Nothing in the code suggests a
fourth surface (e.g. a provider-agnostic executor registry) earns its keep
with exactly one provider family in existence — deferred (§7, row e).

### 1.5 The capture-services gap is real, and separable from this slice

The matrix's fourth GAP is verified: the seam duck-checks
`configure_capture`/`capture_progress`/`artifact_finalise` at
`seam.py:1737-1748` and refuses `unavailable` when the connected services
lack them, while the Protocol set declares the first two nowhere
(`interfaces.py:59-152`). A plugin author composing their own services object
cannot know the host will demand these members — that is the real defect, and
it is the ONE follow-on issue this slice files (§7): declare the capture
lifecycle members on `CaptureServices` and refuse typed when a transport's
services lack them.

It does not wall THIS slice, on evidence: `FtdiCaptureServices` inherits all
three duck-checked members from `WriterBackedCaptureServices`
(`serial.py:450` `configure_capture`, `:481` `capture_progress`, `:577`
`artifact_finalise`), so a capture started over the ftdi transport passes the
check through the inherited implementation — the same object the adapter
appends through (the per-connection services retention, `session.py:779-783`).
The follow-up issue is about DECLARED surface and typed refusal for
non-capturing hosts, not about any missing behavior on this transport.

---

## 2. The mechanism

New module `src/benchweave_sdk_server/ftdi.py`, the replay/serial composition.
CLI: `benchweave-sdk-server serve <project> --transport ftdi --device
<ftdi-url>` (the URL is pyftdi's device selector spelling, e.g.
`ftdi://::0x0403:0x6001/1`; the descriptor's `connection_key` stays the logical
identity, exactly as a serial `--device` path relates to its
`connection_key`).

### 2.1 The driver protocol (the hardware boundary, injectable)

```python
class FtdiDriver(Protocol):
    def reset_device(self) -> None: ...
    def set_timeouts(self, read_ms: int, write_ms: int) -> None: ...
    def set_latency(self, ms: int) -> None: ...
    def set_baud(self, baud: int) -> None: ...
    def purge(self, queue: str) -> None: ...          # "tx" | "rx"
    def set_bitmode(self, mask: int, mode: int) -> None: ...
    def read_pins(self) -> int: ...
    def write_data(self, data: bytes) -> int: ...
    def read_data(self, size: int) -> bytes: ...
    def close(self) -> None: ...
```

This is `serial.py:119-132`'s `Transport` posture one level up: the ten calls
the seven contract ops plus the data pipe need, nothing else, injectable so
tests never need a device. `open_ftdi(url)` is the only function that imports
pyftdi (lazy, function-local, `# type: ignore[import-untyped]` — the
`open_serial_port` precedent `serial.py:1044-1050`), maps an `ImportError` to
`live_provider_backend_missing:` and any open failure to
`live_provider_device_unavailable:` naming the exception class (absent,
permission-denied, busy, and no-libusb-backend are all this one refusal — the
class and message carry which).

The op dispatch table `_OPS` maps each contract op to its driver call:
`{"reset_device": [], "set_timeouts": ["read_ms", "write_ms"], …,
"set_bitmode": ["mask", "mode"], "read_pins": []}`. The table is the
executor's declared vocabulary, the load-time probe's input (§2.4), and the
runtime dispatch's authority.

### 2.2 The stream path — `SerialLink` reused verbatim

`FtdiStreamAdapter` presents pyserial's `write`/`read`/`close` surface over
the driver's `write_data`/`read_data`/`close`: `write` returns the sent count
(short counts propagate — the backend's own short-count refusal,
`serial.py:753-754`, judges them); `read` returns what is buffered and sleeps
a small idle quantum when the pipe is empty (mirroring pyserial's
`timeout=0.05` pacing at `serial.py:1069`, so `SerialLink`'s reader thread
does not hot-spin — §9.3); `close` closes the driver, the one device handle.

The stream kinds then ride **`SerialLink(FtdiStreamAdapter(driver))`** with no
new ring, no new receive ladder: the quiet line, terminator search, retained
partial, drain-then-refuse-on-close are inherited (`serial.py:283-356`).

### 2.3 The services class — `FtdiCaptureServices(SerialCaptureServices)`

Constructor: `(link, driver, grammar, *, max_frame_bytes, capture_root,
capture_max_bytes)`, `reconfigurator=None` — link control degrades loudly to
its typed not-configured refusal (`serial.py:873-877`) and `link_state`
answers `None` (`serial.py:823-826`), which is correct: on this transport a
baud change is a provider transaction (`set_baud`), not a link-control swap.
Capture members, clocks, evidence recording and `close_transport` are all
inherited.

`transfer(transaction, context)` — the ladder, replay's dispatch grafted in
front of serial's:

1. **Grammar.** `kind in grammar` (the compiled pinned grammar) → the
   provider path (2). Not a provider kind → `await
   super().transfer(transaction, context)` — the parent's own grammar gate
   (`serial.py:728-732`) refuses anything that is neither a provider kind nor
   a §8.1 stream transaction, unchanged.
2. **Provider path, grammar-first** (`replay.py:966-985` verbatim in shape):
   validate the transaction (ABI form, bytes→base64 for the contract's
   declared byte fields) against the admitted `request_schema` → refuse
   `live_provider_transaction_grammar:` before any state change.
3. **Closed check.** The link's `is_closed` → `ConnectionError` (the
   closed-session posture `serial.py:766-773`; the driver shares the link's
   close path, §2.2).
4. **Busy guard.** `link.receive_depth > 0` → refuse
   `live_provider_line_busy:` — the #407 guard (`serial.py:916-926`) one mode
   over: a control op that changes line semantics (bitmode, baud, purge)
   under a parked receive would corrupt the very bytes the receive is waiting
   on. Uniform over all control ops for the first slice (§11.3 offers the
   per-op relaxation).
5. **Liveness + dispatch marker.** `_live(context)` and the
   `context.dispatched` check (`serial.py:739-746`): a control transmit is a
   transmit.
6. **Dispatch.** `op = transaction["op"]`; outside `_OPS` → refuse
   `live_provider_op_unknown:` (the version-skew belt, §5). Map params by the
   table, one `asyncio.to_thread` call into the driver, **one bounded
   attempt, never a retry** (A06).
7. **Result validation.** For `read_pins`, wrap the returned byte and
   validate against the admitted `result_schema` (base64 document form) → a
   device answer outside the contract refuses
   `live_provider_result_grammar:`. Actuation ops return `{}` — transport
   acceptance carries no device meaning (the contract's own result-schema
   wording, `ftdi-control-1.0.0.json:87`). Driver exceptions map to
   `ConnectionError` naming the class (the faulted-link posture: a faulted
   driver stays faulted, reconnect required).

`configure_capture` override (the `ReplayHost` precedent
`replay.py:822-845`): compose `config.transport = "ftdi"` and
`config.provider = {feature_id, sha256}` (the pinned contract's digest) into
the sidecar metadata — the durable evidence names what served, and a capture
made over the live provider transport names the contract revision that
governed its wire grammar.

### 2.4 Digest pinning and the served set

Serve construction and every reconnect run, in order (all in the factory, the
late-bound CURRENT-plugin shape of `replay_plugin_session`
`replay.py:1134-1153`):

1. `_pinned_contract(session.plugin)` — imported from `replay.py` (the
   private-name cross-module import is the in-tree idiom: `replay.py:89`
   imports `_FIELDS` and `_stream_receive_bounds` from `.serial`). None →
   `live_provider_plugin_unpinned:`; a bad pin raises the check lane's own
   `provider_*:` refusals (`validation.py:748-908`), which ride out
   unchanged.
2. **Feature gate.** `pinned["feature_id"]` must be
   `otdp.transport.ftdi-control/<semver>` → else
   `live_provider_feature_unsupported:`. The executor's approval basis is the
   banked FTDI common-surface contract (`src/benchweave_sdk/providers/
   ftdi-control-1.0.0.json`); serving an unreviewed lookalike feature would
   launder that approval onto foreign semantics.
3. **Grammar probe.** Compile the grammar (`_grammar`, `replay.py:206-222`)
   and validate one minimal conforming payload per op in `_OPS` (each probe
   payload is authored beside the table) against its `request_schema`. Any
   rejection → `live_provider_contract_unsupported:` naming the op. This is
   the structural "which provider ids it serves" answer: the feature gate
   binds identity; the probe binds surface; together, the executor serves
   exactly the FTDI common control surface the pinned grammar declares.
4. The digest itself is pinned by the descriptor's `provider.sha256` —
   `verify_provider_pin` already refuses a mismatched digest at both serve
   construction and reconnect (`provider_contract_hash_mismatch:`); this
   design adds no second digest mechanism.

`ftdi_plugin_session(plugin, url, *, driver_factory=None, capture_root=None,
capture_max_bytes=None) -> PluginSession` — the factory opens the device per
connection (a fresh conversation per connect, the M1-fold law
`serial.py:1221-1227`), `driver_factory` being the injection axis for tests.

### 2.5 The refusal family (STD-4 surface, all `ValueError` with prefix)

`live_provider_plugin_unpinned:`, `live_provider_backend_missing:`,
`live_provider_device_unavailable:`, `live_provider_feature_unsupported:`,
`live_provider_contract_unsupported:`, `live_provider_transaction_grammar:`,
`live_provider_result_grammar:`, `live_provider_op_unknown:`,
`live_provider_line_busy:` — plus two CLI guard rows in the existing
`standalone_transport_*` family (`--transport ftdi` without `--device`;
`--device` on a non-live transport, the amended guard). Every prefix names its
resolving action in the message, the `shim.py` precedent. Over the seam these
surface as today: build-time refusals exit 2 with the message
(`cli.py:313-320`'s shape); connect-time refusals ride the existing
not_ready/unavailable mapping (`seam.py:604-630`) with the prefix preserved
in the message. No `SeamError` code motion.

---

## 3. Mock parity — the scripted control double, IN THIS SLICE (2026-10-28 ruling)

The issue's acceptance line — "the same plugin rehearses that sequence
against the mock with no hardware attached" — rides in this issue, not a
follow-on row: no hardware is present on this machine, so a scripted double
at the device boundary is the only way to exercise the control sequence, and
the ruling binds it here. The mechanism:

- **`ScriptedFtdiDriver` ships product-side in `ftdi.py`** — a committed,
  documented `FtdiDriver` double, not a test-internal fake. Its constructor
  takes a script of provider rows (op + params + scripted result, the exact
  row shape the #564 journal carries); each driver call records itself and
  answers from the script, refusing on exhaustion or an unexpected call
  (`ConformanceError` naming the call — the exact-match discipline, one
  boundary down). Stream data answers come from the same script's byte rows,
  so `FtdiStreamAdapter`/`SerialLink` rehearsal rides the double too.
- **The rehearsal runs the PRODUCTION path end to end:**
  `ftdi_plugin_session(plugin, url, driver_factory=lambda:
  ScriptedFtdiDriver(script))` mints real `FtdiCaptureServices` over the
  double — grammar validation, feature gate, op probe, busy guard, dispatch
  marker, table dispatch, result validation, the `SerialLink` receive ladder,
  capture sidecar: everything but the USB boundary is the shipped code. This
  is the serial lane's own injectability posture (`serial.py:119-132`),
  promoted from a test convenience to the slice's named rehearsal mechanism.
- **The double's script is the recorded journal.** The acceptance script is
  DERIVED from the provider rows of the #564 replay acceptance journal (op +
  params + order), so the rehearsal and the recorded hardware evidence
  consume one document and cannot drift: if the journal's conversation and
  the double's rehearsal ever disagree, the parity test reddens. The
  rehearsal proves something about the live path because both read the same
  evidence through the same ladder.
- **Why a driver-boundary double, not a MockHost arm:** a `MockHost` script
  speaks transactions, and the mock's two dialects are stream-shaped by
  construction (`session.py:181` `_DIALECTS`); a bitmode call is not a
  transaction shape a vectors script can carry — it is a device-boundary
  act. "The mock" for a driver-backed transport is therefore the double AT
  the driver boundary, driven through the production services; teaching
  `--transport mock` a third dialect would fork the script surface instead
  (and is the scaffold/mock-parity row's carrier question, §7 row f). The
  plain mock keeps refusing provider kinds — pinned from this slice's side
  too (C5), the untouched honesty posture.
- **The operator-facing recorded rehearsal stays replay** (existing, #564):
  a journal replays through `serve --transport replay` with its own banner
  and sidecar discipline. The double is the developer/plugin-facing
  rehearsal; replay is the operator-facing one; neither claims to be the
  other.

---

## 4. CLI wiring and guide surfaces

`cli.py`: the choice grows to `["mock", "serial", "replay", "ftdi"]`
(`cli.py:364`); `_build_seam` gains the branch beside replay's
(`cli.py:307-330`): hoisted-guard pass → `_load` → build-time pin
verification + feature gate + grammar probe (fail fast, echo + exit 2, the
journal precedent) → `StandaloneSeam(ftdi_plugin_session(plugin, device),
transport_kind="ftdi", …)`. `--device` widens to the two live transports
(the guard at `cli.py:232` becomes `transport not in ("serial", "ftdi")`, help
updated: it names the constant endpoint of a live transport — a port path on
serial, an FTDI URL on ftdi); `--replay` and `--bindings` keep refusing on
ftdi through the existing guards. A new guard row refuses
`--transport ftdi` without `--device` (the replay-needs-journal shape
`cli.py:225-231`): this transport has no binding store and no discovery in
the first slice, so the URL is the only endpoint source.

**Guide surfaces (obligations 1, 4, 6):** `user_guide/plugin-sdk.qmd` (the
transports passage around `:447-551` gains the ftdi paragraph: what the URL
is, that control transactions are the pinned contract's ops, the missing-extra
and absent-device refusals, and the parity rule); `README.md` (the transport
paragraph around `:224-243` gains the ftdi sentence, pyftdi named beside
pyserial's install sentence `:227`); the getting-started four pages are
judged-not-touched (no pedagogy change; `test_getting_started`'s
registration check keeps passing untouched). Operator-facing prose goes
through the `document-writer` agent (the docs register rule). No
version-literal motion (obligation 10): the new prose names no three-component
version of our artifacts.

---

## 5. Honesty under failure (A06)

| Failure | What the wire sees |
|---|---|
| pyftdi missing | `live_provider_backend_missing:` at serve construction (exit 2, install hint naming `[server]`); a second lazy-import check at connect for robustness |
| Device absent / busy / permission / no libusb backend | `live_provider_device_unavailable:` naming the exception class, at connect; seam answers `not_ready` — one attempt, no scan, no retry |
| Plugin declares no provider | `live_provider_plugin_unpinned:` at serve construction — a stream plugin cannot silently land on this transport |
| Wrong contract (feature or grammar) | `live_provider_feature_unsupported:` / `live_provider_contract_unsupported:` at serve construction and reconnect — the re-pin-a-different-contract reconnect refuses exactly as replay's does (`replay.py:1141-1153`) |
| Device unplugged mid-session | the next driver call faults → `ConnectionError` → `not_ready`; a faulted driver stays faulted; a parked stream receive wakes through the link's fault path (`serial.py:312-315`); no retry, reconnect mints a fresh conversation |
| Device answers garbage | `live_provider_result_grammar:` — the live device is untrusted against its own pinned contract |
| Deadline / cancellation | `TimeoutError` posture; a stream partial stays buffered; a control op is discrete — it completed or it raised, and the envelope says which. `dispatch_state` stays the adapter's own honesty; this host contributes never-fabricate and never-retry, the replay module contract's posture |
| A 1.1.0 grammar adds an eighth op | the probe still passes (the seven validate), the eighth op arrives, `live_provider_op_unknown:` refuses it at runtime — the disclosed version-skew posture: this executor predates the op; upgrade the SDK. What the guard does not catch: a 1.1.0 op whose NAME collides with a 1.0.0 op but whose params differ — the grammar-first refusal catches param drift, the probe does not; the contract's semver discipline owns that seam |

Never, on any path: a silent fall back to replay, or a no-op that reports ok.

---

## 6. What is generic, what the plugin owes

| Part | Generic (SDK) | Plugin |
|---|---|---|
| Driver protocol + op table + probe | new, `ftdi.py` | — |
| Live services + session + CLI branch | new, `ftdi.py`/`cli.py` | — |
| pyftdi in `[server]` extra | `pyproject.toml` | — |
| Fixture plugin pinning the banked contract bytes | new fixture (byte-equal to `src/benchweave_sdk/providers/ftdi-control-1.0.0.json`, the slice-3 pin-by-test precedent) | — |
| The descriptor's provider pin | — | exists (#564 slice 2) |
| The bring-up wire sequence (which ops, which order) | — | the adapter's builders, already rehearsed against the journal |
| The live-device acceptance session | — | **deferred and unclaimed in this slice** (§8): closure = one real-bench run through `serve --transport ftdi`, its evidence recorded then |

**The live-device leg is deferred and unclaimed.** Nothing in this slice
exercises the seven control calls against a device, and neither this record
nor the PR body may be written so a reader concludes otherwise. What this
slice claims: the ladder serves the contract, proven against the scripted
double whose script IS the recorded conversation. What it does not claim:
that the device answers. The closure condition is explicit — one real-bench
run through `serve --transport ftdi` completing the bring-up conversation,
its evidence recorded then (the observed op sequence beside the double's),
at which point the issue's first acceptance bullet closes on that evidence.

---

## 7. Deferrals — one follow-on issue, the rest rows (per the 2026-10-28 ruling)

**The one follow-on issue, filed at PR-open time (at most one per PR):**

- **Capture-services declaration** — `interfaces.py`: declare the capture
  lifecycle members (`configure_capture`, `capture_progress`) on
  `CaptureServices` beside the artifact members, and a named typed refusal
  when a connected transport's services lack any member the seam
  duck-checks today (`seam.py:1737-1748`'s anonymous `unavailable` becomes
  a prefixed refusal). Verified separable from this slice (§1.5): the ftdi
  transport inherits all three members and passes the check unchanged.
  Reopen trigger: this slice's PR opens the issue; it does not gate the
  merge.

**Deferral rows (carrier = this record's table, no issue filed; each names
its reopen trigger):**

| Row | Deferred | Reopen trigger |
|---|---|---|
| a | FTDI discovery + binding-store integration (the #385 endpoint model for USB URLs; scan/pick/bind UI arms) | the first bench with more than one FTDI device to pick from |
| b | Live journal recording (`--record` emitting a #564-format journal from a live session) — the recording helper the falsification session wants | the next falsification session, or the live-device closure run (§6), whichever comes first |
| c | The contract's `native_libraries` naming (pyftdi/libftdi with exact versions — a 1.1.0 contract revision; the schema treats host_requirements as review surface, not runtime gate, so this is disclosure, not enforcement) | the first commissioned bring-up review |
| d | The gateway commissioned provider runtime (executor + grant seam, gateway-side) | unchanged from the #562 design's deferral 2 — gateway-side design of its own |
| e | A provider-agnostic executor registry (non-FTDI provider families on one transport) | the second provider family in existence |
| f | The scaffold variant for a custom transport (`new` emits serial-stream only — verified: `src/benchweave_sdk/cli.py:66-71` carries no transport variant, `copier.yml` no knob), and with it the question whether mock rehearsal of provider kinds grows a third vectors dialect instead of the driver-boundary double | the second plugin authored FROM the scaffold that declares a provider pin |
| g | MPSSE / multi-interface FTDI shapes beyond interface A of the FT232 class | a plugin whose device needs it names the URL shape |
| h | Serial-link control (baud renegotiation via `reconfigure_link`) on the ftdi transport — not wanted: `set_baud` is a provider transaction here; the not-configured refusal is the correct permanent posture | a plugin that needs a mid-session line reset outside the contract's ops |

---

## 8. Pre-committed acceptance rule

Written before any measurement ran; amended 2026-10-28 (same day, still
before any measurement) to conform to the ruling — the amendment tightened
the negative control (B1) and moved the hardware leg OUT of the ship
direction; no arm was weakened. All arms are deterministic conformance; all
measurements are this lane's, on this machine, through the scripted double —
whose measurement they are is stated per arm. **No arm exercises a device.**

**Metric A — the bring-up over the scripted double (this lane's
measurement).** A fixture plugin pinning the banked `ftdi-control-1.0.0`
bytes, driven through `ftdi_plugin_session` with `ScriptedFtdiDriver` over
the journal-derived script, completes the recorded bring-up conversation
(the init chain: reset/purge/latency/baud/bitmode/pin poll; then a
bitstream-chunk `stream_send` and the DONE-gating `read_pins`; then one
status `stream_exchange` — the #564 acceptance journal's provider+stream
shape): every operation envelope `status: "ok"`, and the double's recorded
op-call sequence equals the journal's provider rows exactly (op, params,
order — the parity assertion). Zero `ConformanceError`.

**Metric B — the RED controls (each must fail loudly; 6/6).** Single-point
reversions/mutations of the production mechanism, each reddening its named
test:
- B1 — **the negative control, three transports wide:** the SAME
  provider-kind transaction (`ftdi_control` `set_baud`), issued at
  `origin/main` AND with the ftdi dispatch reverted, is refused everywhere
  the new mechanism does not serve it: on serial (`serial.py:728-732`, the
  §8.1 refusal — a provider plugin cannot silently land on serial); on the
  mock (`transport.py:377-381` — the untouched stream-only dialects); and on
  replay when the served plugin's pinned grammar does not admit the kind
  (`replay.py:404-408` `replay_journal_kind` — the reference-hid fixture
  plugin is the ready-made wrong-grammar control). Only `--transport ftdi`
  dispatches it. A passing mock run is NOT this control; the refusals are.
- B2: revert the op dispatch table's `set_bitmode` entry → the bitmode
  transaction refuses `live_provider_op_unknown:` (not a silent skip);
- B3: revert the busy guard → a control op under a parked receive must be
  refused; with the guard reverted the parked-receive test reddens;
- B4: revert the result validation → a double answering two bytes for
  `read_pins` must refuse `live_provider_result_grammar:`;
- B5: revert the feature gate → the reference-hid fixture plugin (an
  admitted contract, wrong feature) on `--transport ftdi` must refuse
  `live_provider_feature_unsupported:` rather than serve;
- B6: delete the availability refusal and return a fabricated ok → the
  absent-device test reddens: the refusal must name
  `live_provider_device_unavailable:`. This arm runs the REAL pyftdi import
  path with no device attached — an honest live-import arm CI can run; it
  proves the import-and-refuse path, not device behavior.

**Metric C — the honesty arms (all must pass; 7).**
- C1: every seam state surface reports `transport: "ftdi"`;
- C2: the mode banner renders the LIVE shape — no `simulated` row, no replay
  row — string-pinned against `presentation.py`'s fixture literals;
- C3: the capture sidecar carries `config.transport = "ftdi"` and the
  provider digest;
- C4: `--transport ftdi` without `--device` refuses typed exit 2; `--replay`
  and `--bindings` refuse on ftdi through the existing guards — the guard
  family stays intact, one flag one meaning (`cli.py:209-247`), `--device`
  widened to the two live transports only;
- C5: `--transport mock` still refuses provider kinds (the untouched
  refusal, pinned from the ftdi side too — a stream plugin must equally not
  silently land on ftdi: an unpinned plugin on `--transport ftdi` refuses
  `live_provider_plugin_unpinned:` at serve construction, the same arm);
- C6: an unpinning of the plugin descriptor (provider object removed) on a
  live session's reconnect refuses `live_provider_plugin_unpinned:` — the
  reload-and-reconnect re-verify, replay's `replay.py:1141-1153` posture;
- C7: a mid-conversation driver fault maps to `ConnectionError` → seam
  `not_ready`, and the double records exactly one call (no retry).

**Ship direction:** A, B (6/6) and C (7/7) pass. Nothing else ships the
slice. **The issue's first acceptance bullet — the live-device bring-up —
stays OPEN and UNCLAIMED**: this record and the PR body both say so, and
name the closure condition (§6: one real-bench run, evidence recorded then).
**Kill direction:** any B mutation passes clean — the executor is not pinned
to its contract, the increment's core claim is false; kill the design, not
the test. Any C arm fails — an honesty surface is missing; blocker, the ship
claim is dead until it holds.
**Underpowered direction:** A fails on an unmutated, journal-derived script →
the SCRIPT or the journal conversion is wrong evidence, not the mechanism
(diagnose by the first divergent op; the journal is the arbiter); B1's
replay control failing would mean the reference-hid grammar admits
`ftdi_control` — a fixture bug, re-derive the control. **Denominators:** B =
6 mutations; C = 7 arms; A's denominator is the script's provider-row count
(stamped in the journal the script derives from). Whose measurement: this
lane's, this machine, deterministic, double-driven — with B6's import path
the only live-environment arm, and it proves a refusal, never a device
answer.

---

## 9. Risks, ranked, with falsifiers

1. **The double proves the ladder, not pyftdi — and this slice claims
   exactly that, no more.** `open_ftdi`'s device mapping is exercised only
   by the import-and-refuse arm (B6); no device is touched and no device
   behavior is claimed anywhere in this slice (§6, §8 — the ruling's bound).
   DISCLOSED RESIDUAL, permanent until the closure run: the real pyftdi call
   mapping is unproven. Mitigation: the parity rule (one evidence document
   through one ladder) plus the named closure condition. Falsifier: the
   real-bench run itself, whenever it runs.
2. **A control op under a parked receive corrupts the ring.** The uniform
   busy guard (§2.3 step 4) is the mitigation; B3 is its proof. Residual: a
   receive and a control op dispatched in the same event-loop tick can pass
   under the guard — the disclosed window is #407's own
   (`serial.py:239-251`, bounded at worker-start, not dispatch).
3. **`FtdiStreamAdapter` hot-spins or stalls** — pyftdi's read semantics
   differ from pyserial's timed read. Mitigation: the idle quantum (§2.2);
   falsifier: a timing-marked soak asserting the reader's CPU share stays
   bounded on a quiet line (the `timing` marker partition exists for this
   class). Inference until pyftdi is imported in the build (§0 flag).
4. **pyftdi untyped under strict mypy / API drift.** The Protocol isolates
   the import to one function; `type: ignore[import-untyped]` is the
   pyserial precedent. Falsifier: `uv run mypy` on a fresh cache, the FAST
   lane's own gate.
5. **Version skew (a 1.1.0 grammar's eighth op, or an op redefined).**
   Runtime `live_provider_op_unknown:` + grammar-first refusal; §5 states
   what the pair does not catch. Low.
6. **Lane collision.** None in the tracker (§0.10); the guide-file overlap
   with #562 rows 5/6 is section-level. The two-repo order is the standard
   TWO-1 flow; no corpus bytes move, so no sync-window question.

---

## 10. Review tier and the Step-1 keyword scan (#254)

**Tier: 3**, two independent triggers, either sufficient:
- *adds a dependency* — pyftdi joins `pyproject.toml` `[server]` and
  `uv.lock` (the rubric's Tier-3 path rule);
- *adds refusal paths* — the `live_provider_*:` family extends the STD-4
  machine-matchable prefix surface (STD-4's own note: the prefixes are an API
  even though they live in error text).

No standards-governor trigger: no `standards/` bytes, no vendored-tree
motion, no version strings inside the slice. G6 adversarial refute is
mandatory at review; the two-repo landing order (SDK PR → gateway pointer at
release) is the standing discipline.

**Keyword scan** — `re.findall` over this record's §2-§8 (the mechanism,
slice, and acceptance text the diff will implement). The scan below is the
ACTUAL run's output over the amended record text (2026-10-28, re-run after
the ruling conformance pass; an earlier draft of this table carried
estimates, which the first run replaced). The review re-derives the scan
over the real diff, whose counts will be higher on `sha256` (the pin-digest
sites repeat in code and tests) and `hashlib`/`asyncio` (import sites the
record text does not spell):

| Keyword | Measured over §2-§8 | Source in the expected diff |
|---|---|---|
| `sha256` | 2 | §2.4's digest pinning, §2.3's sidecar; the real diff's provider-pin and sidecar tests multiply the sites |
| `hashlib` | 0 | no new import site named — the digest computation rides `_pinned_contract`; the real diff's tests may carry one |
| `asyncio` | 1 | the `asyncio.to_thread` driver call; the real diff's session tests import it |
| `threading` | 0 | the reader thread is inherited via `SerialLink`, not named in new code |
| `subprocess` | 0 | rejected boundary (§0.2's contract text); keep it out of the diff |
| `migrate` | 0 | — |
| `recovery` | 0 | — |
| `protection` | 0 | absent; keep it out of the diff text |

`sha256` alone settles Tier 3 under first-match; the path rules reach it
independently (pyproject/uv.lock, refusal prefixes).

---

## 11. Open decisions for the maintainer

(Ruled 2026-10-28 and therefore NOT open here: option 2 stands; mock parity
rides in this slice; hardware proof deferred and unclaimed; one follow-on
issue only — capture services; the scaffold variant a deferral row. The
ruling is recorded in §0.11 and conformed to throughout.)

1. **pyftdi pin shape:** floor (`pyftdi>=0.56`) recommended over exact —
   unlike `benchweave-ui-html` (a corpus twin needing exact), pyftdi is a
   driver; confirm.
2. **`--device` reuse vs a new `--ftdi <url>` flag:** reuse recommended (one
   amended guard row, the flag already means "the constant endpoint of a live
   transport"); confirm.
3. **The busy guard's scope:** uniform over all control ops (recommended,
   §2.3 step 4) vs per-op (allow `read_pins` under a parked receive).
4. **Vehicle:** the next minor alongside the replay lane (both post-0.23.0
   on main) vs its own — recommended: one vehicle, the replay contract and
   its executor belong to one release story.

**Maintainer rulings, 2026-10-28 — all four recommendations adopted.** These
are decisions, not options; the refute pass reads them as settled:

1. pyftdi ships as a bounded range `pyftdi>=0.56,<1`, mirroring pyserial's
   shape (`>=3.5,<4`) rather than the corpus-twin exact pin. The upper bound
   is the API-drift fence; a patch release must not need a code change.
2. `--device` is reused for both live transports. One flag, one meaning: the
   constant endpoint of a live transport. The guard row is amended, not
   duplicated, and `--replay`/`--bindings` keep refusing on ftdi.
3. The busy guard is uniform over all control ops. `read_pins` is not
   exempted: one posture is easier to state, test and hold than two.
4. One vehicle: v0.24.0, carrying this executor alongside the replay lane.
   The version bump and release cut are a separate leg — this slice does not
   bump `pyproject.toml`. The hardware leg's scheduling is ruled too: the
   slice lands on A/B/C; the bench evidence document gates the ISSUE's
   closure, not the merge, and until it exists the live-device acceptance is
   open and unclaimed in both this record and the PR body.
