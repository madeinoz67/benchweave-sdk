# Issue #385 — the device-addition surface: bind connection_key to a physical endpoint — design record

Date: 2026-10-04. Status: DESIGN (no code written). Repo: `benchweave-sdk`
(the slice branch lands on top of merged I3a, `origin/main` `8fb178e`; this
record is written in the design worktree `.wt/i3design-9307` whose `src/` and
`tests/` are byte-identical to that merge — `git diff f427a15 origin/main --
src/ tests/` is empty). Tracking: gateway issue #385, labelled `sdk`, an I3
sub-slice under #285 (owner triage comment: adopted, human-in-the-loop
default, both discriminators carried, standalone-first to be named). PRD 11
(`docs/implementation-planning/11-standalone-web-ui-prd.md`, Draft v0.3) is
the requirements authority; companions #386 (PRD §5 vid/pid wording vs the
descriptor schema) and #387 (no unique ID in IDENTIFY_RSP) bound the space.

Design-lane note: this is a read-only design pass. The record is NOT
committed from here; the orchestrator lands it as the slice branch's first
commit, byte-for-byte (the I3 record's own disclosed pattern).

## 0. Verification of premises (done before designing)

Every claim below was read in the merged-I3a tree, not assumed:

- **`connection_key` IS the standalone's device id.** `LoadedPlugin.device_id`
  is `str(transport.get("connection_key") or self.package)`
  (`src/benchweave_sdk_server/session.py`, the `device_id` property). Every
  device-addressed operation (`device_connect`, `parameter_read`, …) addresses
  it. "Bind the connection_key to an endpoint" and "bind the device this host
  serves" are therefore one act, not two.
- **The endpoint today exists only as a CLI string.** `_build_seam`'s serial
  branch (`cli.py`) requires `--device <path>` (refusal
  `standalone_transport_serial_device_required`) and passes it to
  `serial_plugin_session(plugin, device, open_port=...)`, whose factory
  closure bakes the path in at session construction (`serial.py`). Nothing
  persists it; a restart re-types it.
- **Discovery cannot name an endpoint.** `_device_row` (`serial.py`) builds
  `_DEVICE_SUMMARY` rows `{id, manufacturer, model, transport,
  connection_key}` — no port path, no USB serial. With two identical boards
  the scan returns TWO IDENTICAL ROWS (pinned today:
  `test_ar4_discovery_returns_exactly_the_two_matching_candidates` asserts
  `[row["id"] ...] == ["example_device", "example_device"]`). The operator
  cannot act on the result; `device_connect` takes only `device_id`, which is
  the same string for both.
- **The seam's connected-port short-circuit never fires from the CLI.**
  `StandaloneSeam.__init__` takes `serial_device_path`, and `_op_device_discover`
  passes it as `connected_device` so a connected port is served from its
  established identity without re-probing — but `cli.py`'s serial branch
  constructs the seam WITHOUT `serial_device_path` (or `serial_ports`); only
  the tests thread it (`test_serial_discovery.py::_serial_app`). A re-scan
  while connected, from a real `serve`, re-opens the live session's port and
  runs identify against it concurrently with the session's own link — two
  readers on one port. A landed gap this design closes structurally (the
  binding becomes the one source of the effective path; §1.4).
- **A stale open is typed in embryo but message-poor.** `PluginSession.connect`
  wraps any factory/`open` exception as `RuntimeError("standalone_plugin_connect:
  SerialException: …")`, which `_op_device_connect` maps to `not_ready` — so a
  missing port is not a 500, but it surfaces as a raw pyserial string with no
  stale-binding semantics and no re-pick path.
- **The gateway's `transport-settings.json` is identity-only BY SCHEMA, and
  that is a standing obligation, not an oversight.** `TRANSPORT_SETTINGS_SCHEMA`
  (`gateway src/benchweave/control/provider_settings.py`) binds
  `connection_key → provider_id` with `additionalProperties: false` and no
  field able to carry a path; drift-and-obligations row 16 routes any endpoint
  request to "the deferred execution-standard commissioning shape … reopen
  trigger: the first provider implementation". The gateway runtime opens no
  serial ports today. Issue #385's gap statement quotes this surface as
  motivation; the fix is NOT an edit there.
- **The descriptor grants no addresses** (OTDP `serialTransport`; "Addresses/
  paths/credentials are not granted by this descriptor") — I3a's
  `x-standalone-usb-vid`/`-pid` extension keys remain the only schema-legal
  descriptor lane, and #386 recommends (a) PRD wording to match the schema:
  probe-by-IDENTIFY + operator selection of the endpoint. This design is that
  recommendation realised; it touches no descriptor schema bytes.
- **The fork's provenance** (public, cited by the PRD): `discovery.py`'s
  `AdcBoard(device, serial, info)` rows carry port path AND USB serial
  (`port.serial_number or ""`); `BoardManager.connect(device)` takes the path
  the operator picked; `serial_for_device` maps path → USB serial via
  `comports()`. The fork's answer was port-path-keyed pick-per-connect, never
  persisted, USB serial as a best-effort label. pyserial's `ListPortInfo`
  carries `.serial_number` (None when the device descriptor has no iSerial) —
  the in-tree `CandidatePort` double does not model it yet (§1.2 extends it).
- **The state-location precedent**: SDK-core `capture_root()` (Decision 9) —
  explicit argument over `BENCHWEAVE_CAPTURE_DIR` over `captures/` under the
  CWD, refusing roots inside the installed package tree. The standalone's
  only persisted state today follows exactly this family.
- **The host-side-mutation precedent**: scenario select (I2 D-B1) is a
  `POST /devices/{id}/scenario` ROUTE calling `scenario.select()` directly —
  "host state, not a catalogue op", CSRF'd, never on the wire contract.

## 1. Mechanism

One slice, one stacked PR on the SDK repo, an internal commit ladder. All of
it extends landed I3a mechanisms; no new dependency, no new thread, no
standards bytes, no descriptor edits, no `src/benchweave_sdk/` core motion.

### 1.1 The binding store — `src/benchweave_sdk_server/binding.py`

A new module owning ONE document: `device-bindings.json`, resolved by
`bindings_path()` in `capture_root()`'s exact family — an explicit argument
(CLI `--bindings <path>`; seam constructor arg for tests) over the
`BENCHWEAVE_STANDALONE_BINDINGS` environment variable over
`device-bindings.json` under the current working directory — refusing a
resolved path inside the installed package tree (same words, same posture as
`capture_root`; the standalone's state files are one family).

The document (schema in gateway source style — closed-world,
`additionalProperties: false` throughout, every string pattern-constrained;
jsonschema-validated at load):

```json
{
  "config_version": "1",
  "bindings": [
    {
      "connection_key": "adc_board",
      "plugin_package": "adc_6ch_12bit",
      "transport": "serial",
      "endpoint_kind": "usb_serial",
      "usb_serial": "A1B2C3",
      "vid": "1a86",
      "pid": "7523",
      "port_path": "/dev/match-b",
      "identity": {"manufacturer": "…", "model": "…", "firmware": "…"},
      "bound_at": "2026-10-04T09:00:00Z",
      "bound_via": "ui"
    }
  ]
}
```

- `endpoint_kind` ∈ `"usb_serial" | "port_path"` — the discriminator the
  bench's own evidence supported at pick time (§1.3). `usb_serial`/`vid`/`pid`
  are nullable (present iff `endpoint_kind` is `usb_serial`; `vid`/`pid` ride
  as resolution conjuncts and provenance). `port_path` is always the path
  observed at bind (provenance for `usb_serial` rows, the key for
  `port_path` rows). `identity` is the identify answer the scan confirmed —
  the row is the operator's pick WITH its evidence.
- Rows are unique by `(plugin_package, connection_key)`; a duplicate refuses
  at load (`standalone_binding_schema:`), never last-wins. Loading is exact-
  byte `json.loads` with a 1 MiB cap and typed refusals
  (`standalone_binding_unreadable:`, `standalone_binding_schema:`) — refused
  at SEAM CONSTRUCTION (serve exit 2 with the prefix, the
  `standalone_plugin_invalid:` shape), never a mid-request traceback.
- Writes are atomic: temp file in the same directory, `os.replace`, fsync of
  the file before the rename (the writer's finalise discipline, minus the
  manifest — this is operator state, not evidence, so NO digest machinery).
- **Not the gateway's `transport-settings.json` shape, deliberately.** That
  document is administrator ADMISSION (which provider contract serves a key);
  this one is the operator's INSTANCE pick (which physical thing). Different
  acts, different documents; conflating them would put endpoint carriage one
  schema-edit away from the gateway surface obligation 16 keeps closed. When
  the gateway's deferred commissioning shape is reopened (first provider
  runtime implementation), THIS row — discriminator, staleness semantics,
  provenance fields — is the promotion candidate (flagged §6, not designed).

### 1.2 Discovery rows carry endpoints — `serial.py` + `catalogue.py`

- `_device_row` gains `port_path` (string) and `usb_serial`
  (`["string","null"]`), sourced from the port object:
  `_port_name(port)` and `getattr(port, "serial_number", None)`. The mock
  branch's single row emits `null`/`null` (the mock has no endpoint — honest
  null, never a fake path). `_DEVICE_SUMMARY` (`catalogue.py`) gains both
  fields, required, nullable — one row shape across transports. This is a
  wire-visible change to a SERVED operation's result schema: REST and MCP pin
  from the catalogue automatically (`_pin_all`, the gate-F readback), no
  vendored bytes, no new tool.
- `CandidatePort` (test double) grows `serial_number: str | None = None`,
  modelling `ListPortInfo`. The connected-port short-circuit's row is served
  with the CONNECTED port's path (the resolver's last resolution, §1.4) — the
  operator sees which physical row their session is on.

### 1.3 The discriminator — chosen at bind time, carried in the row

`bind_device(port_path)` (§1.4) cross-checks the pick against the CURRENT
confirmed discovery cache and chooses:

- **`usb_serial`** when the picked candidate has a non-null serial AND no
  OTHER confirmed candidate in the same scan carries the same serial —
  instance-stable across re-enumeration (unplug/replug at a new path still
  resolves).
- **`port_path`** otherwise (null serial, or a duplicate serial among the
  confirmed candidates — the ambiguity the CH343G-class open fact anticipates;
  the issue's unmeasured fact stays unmeasured, and the mechanism works under
  both outcomes — the on-hardware `list_ports` measurement rides the fork
  migration lane, the same evidence boundary as AR-3's on-hardware clause).

The store therefore RECORDS which identity strategy this bench's evidence
supported — the discriminator is data, not code-path guesswork, and a bench
whose bridges report distinct serials gets path-independent rebinding on
exactly that evidence.

### 1.4 Resolution — the seam owns a resolver, not a path

- `serial_plugin_session` generalises: `device_path: str` becomes
  `endpoint: Callable[[], str] | str` — a string wraps as a constant resolver
  (the `--device` headless form, byte-compatible with every existing test),
  and the binding-backed resolver is a closure over the store. The factory
  reads the resolver AT CONNECT TIME (the late-bound `mock_plugin_session`
  precedent — the mock factory reads `session.plugin` at connect; this
  factory reads the binding at connect, so a rebind changes the next
  connection's port).
- The resolver object exposes `last_resolution: str | None` — the path the
  live session actually opened. `_op_device_discover` passes THAT as
  `connected_device` (retiring the never-CLI-set `serial_device_path`
  constructor arg; its two test call sites move to the resolver — net
  deletion of a parallel source of truth, and the CLI re-scan-while-connected
  double-open of §0 closes structurally).
- Resolution algorithm (`binding.py::resolve`, pure over the store + an
  enumeration — enumeration is a read-only OS query that opens NO port and
  transmits NOTHING, so NFR-O3's write-bar is untouched):
  1. `--device` present → the constant resolver; the store is not consulted
     and NOT modified (AR-G). Precedence: explicit flag over stored binding.
  2. No row for `(plugin_package, connection_key)` → `BindingAbsent` —
     `device_connect` refuses `not_ready`, reason `binding_absent`, naming
     the connection_key and pointing at the scan-and-pick flow. Serve still
     STARTS in this state (§1.6) — the refusal is connect-time, not
     startup-time, because the UI must render to let the operator pick.
  3. `usb_serial` row → enumerate; the port whose
     `(serial_number, vid, pid)` matches the row's conjuncts resolves to its
     CURRENT path. Zero matches → `BindingStale` (`not_ready`, reason
     `binding_stale`, naming the missing serial + re-pick pointer). TWO OR
     MORE matches → `BindingStale` as well — ambiguity is staleness, never a
     guess.
  4. `port_path` row → resolve to the stored path; a fresh enumeration
     distinguishes the honest failures BEFORE opening: path absent from
     enumeration → `BindingStale` naming it; path present but the open
     refuses → the existing `standalone_plugin_connect:` wrap → `not_ready`
     with the OS message. **No silent fallback to any surviving same-class
     candidate — ever** (the other confirmed port receives zero bytes; AR-B).
- Stale/absent refusals render on the device page through the existing
  render-the-refusal idiom (the M1 fold) with an explicit "scan and re-pick"
  action beside them.

### 1.5 The operator flow — routes over seam methods, D-B1's shape

`bind`/`unbind` are **host-side routes, NOT catalogue operations** — the
scenario-select precedent (D-B1: "host state, not a catalogue op"). Reasons
this is the right fork, not the lazy one: the pick is the operator's
human-in-the-loop act (the issue's own default), and a bind exposed on
REST/MCP would let a bearer-holding agent silently move the physical endpoint
subsequent writes hit — a trust-relevant act the UI-only, CSRF'd route keeps
with the human. Consequence: NO new catalogue rows, no MCP schema motion, no
SW-10 delta fork — the closed 18 stay closed.

- `POST /devices/{device_id}/bind` (CSRF via the existing `CsrfGuard` +
  `hx-headers`, exactly the discover form's shape): form field `port_path`.
  The seam: refuses `conflict` while connected (a live session must never
  have its physical endpoint swapped underneath it — staging, plots and the
  observation ring all address it; the disconnect-first refusal is the
  connect-time conflict guard's sibling); cross-checks the pick against the
  confirmed discovery cache — a path NOT in the cache refuses
  `invalid_request` (`standalone_binding_pick_unconfirmed:`), so a hand-crafted
  form cannot bind an unconfirmed or foreign port; chooses the discriminator
  (§1.3); writes the store atomically; publishes `device_bound` on the
  existing EventBus; redirects to the device page. Binding transmits NOTHING
  (the identify exchange happened at scan time; bind only records).
- `POST /devices/{device_id}/unbind` (CSRF'd): removes the row, publishes
  `device_unbound`, refuses `conflict` while connected.
- The index page's discovery panel becomes the candidates table → pick flow:
  each confirmed row shows port path, USB serial (or "—" when null),
  manufacturer/model, and a Bind button; the bound row (when a binding
  exists) renders the bound marker — endpoint kind, path, serial, `bound_at`
  — with Unbind. The unbound serial host renders the pick prompt in place of
  today's inert list (the scan prompt's existing wording extends).

### 1.6 The CLI posture — serial without `--device` serves the pick flow

`--transport serial` WITHOUT `--device` no longer refuses: the seam starts
binding-pending and the UI drives the pick (§1.4 case 2). The refusal
`standalone_transport_serial_device_required` RETIRES (its tests move to the
new posture: serve starts, `device_connect` refuses `binding_absent`). With
`--device`, everything behaves as I3a shipped (the headless/scripted form;
documented as the binding-bypass). `--bindings <path>` joins the flags. The
stdio `mcp` entry stays mock-only (Q5/F-1's lane, untouched).

### 1.7 What this design does NOT build (embedded DON'T-BUILD calls)

- No gateway motion: `provider_settings.py` is untouched; the endpoint-
  carriage question there is obligation 16's deferred commissioning row with
  its own reopen trigger (§6).
- No descriptor schema motion: no standard vid/pid on `serialTransport`
  (#386's option (b) rejected here as there — the `x-` keys stay the only
  descriptor lane, and this design needs only the pick, not a class filter).
- No third discriminator: firmware self-ID (#387) stays device-side and
  optional; if it ever ships, its outcome is a new `endpoint_kind` value and
  a stronger resolver arm — the store's vocabulary admits it without motion.
- No N-way concurrent serving: the host stays one-session (SW-04). "1..N
  identical devices" means the binding is INSTANCE-CORRECT when N are plugged
  in (the pick binds the right one; AR-A), not N simultaneous sessions. The
  store's `bindings[]` map shape already admits a multi-session future
  without motion (deferral D-2).

## 2. Minimal first increment and deferrals

**The slice ships as ONE stacked PR** (the acceptance rules span store and
UI; the UI without the store is inert and the store without the UI is a
hand-edited file) with an internal commit ladder in the I3a style:
(1) `binding.py` store + schema + atomic write + resolver, pure-function
tests; (2) discovery-row endpoint fields + `CandidatePort.serial_number` +
catalogue/mock-row motion; (3) session resolver generalisation + seam
bind/unbind/resolve + the `serial_device_path` retirement; (4) routes +
templates + CSRF arms; (5) CLI posture + `--bindings`; (6) docs
(user_guide + README).

Deferrals, each with its home:

- **D-1 Gateway endpoint commissioning** (obligation 16's deferred row):
  promote this row's shape into the execution-standard commissioning surface
  when the first provider runtime implementation fires the reopen trigger.
  Home: the gateway tracker (a note on #385's close, cross-referenced to
  obligation 16).
- **D-2 Multi-session hosts** (N devices served concurrently): home: a PRD
  follow-on issue under #282 (filed at close; the store shape admits it).
- **D-3 The CH343G serial-number measurement**: run `list_ports` with N
  boards on the bench; record distinct/blank/duplicate on #385. Home: the
  fork-migration lane (I3d)'s hardware-evidence window; fixtures carry both
  outcomes until then.
- **D-4 An agent-readable binding surface** (`binding_get` as a read-only
  catalogue row) if an MCP consumer ever needs to SEE the binding: home: this
  issue's follow-ups; deliberately absent now (bind/unbind are route-only by
  §1.5's trust argument; reads can join when a consumer exists).
- **D-5 Non-serial endpoint kinds** (usbtmc &c.): home: the transport that
  first needs it; `transport` is recorded in the row for exactly this.
- **D-6 #386's PRD §5 wording edit** (gateway-side PRD text to match the
  schema): adjacent lane, already filed; this design is consistent with its
  recommendation (a) and changes no PRD bytes itself.

## 3. Invariants and cross-surface impacts

- **Tier 3** under the SDK rubric: a new persisted format
  (`device-bindings.json`) and new refusal paths. No dependency add; no
  `src/benchweave_sdk/` core bytes; wheel target list unchanged (PKG-1/2/3
  hold); scaffold untouched.
- **STD-4 posture extended**: new prefixed refusals
  `standalone_binding_schema:`, `standalone_binding_unreadable:`,
  `standalone_binding_pick_unconfirmed:`, plus the connect-time reasons
  (`binding_absent`, `binding_stale` — `not_ready` details, reusing the
  EXISTING error-code vocabulary: `not_ready`/`conflict`/`invalid_request`;
  no new codes, so `errors.py` is untouched). Per-path tests, NFR-Q4 shape.
- **Wire-visible**: `_DEVICE_SUMMARY` +2 nullable fields — the `device_discover`
  result schema on REST and MCP moves; both pin from the catalogue
  automatically; the parity gate and gate-F readback extend to the new
  fields. Disclosed as a result-schema widening (additive, nullable) — not
  contract-versioned (the standalone catalogue carries no version
  negotiation; `host_info` discloses `sdk_version`).
- **Behavior change**: serial serve without `--device` starts (was: exit 2);
  `standalone_transport_serial_device_required` retires. SDK obligations
  (drift-and-obligations): #1 CLI (`--bindings`, the new posture) →
  user_guide + README in the same PR; #6 behavioural tests land in
  `tests/server/`; #8 landing order — SDK commits pushed before any gateway
  pointer advance (the pointer is the train's chore, not this diff).
- **Gateway surfaces: none move.** The `bws_v1_*` tool set is not the
  vendored `stg_v1` corpus (the I3 record §3's own note); no `standards/`
  bytes, no vendored edits, no version strings, no interface-0.1.0 surface
  touched. **Standards tripwire: empty by design and by verification.**
- **CI cost**: zero new jobs; the suite grows ~14 tests in `tests/server/`
  (store, resolver, discovery-row, bind/unbind routes, CSRF, CLI posture,
  NFR-O3 arms) riding the existing `pytest` lanes. Windows: the store and
  resolver are pure Python + `pathlib`; port-path strings are data — W1
  (CI-corroborated) posture, POSIX-direct tests carry the logic.

## 4. Review tier and the Step-1 keyword scan (#254 form)

**Tier 3** (path rules: new persisted format; refusal-path additions). Two
independent adversary lanes per the standing rule. Step-1 keyword scan over
the EXPECTED diff text (docs and code alike; to be re-derived at review):

`threading` 0 (no new threads — the resolver is synchronous enumeration),
`asyncio` ≈ 6 (route handlers + seam methods), `subprocess` 0, `sha256` 0
(no digest machinery on operator state), `hashlib` 0, `migrate` 0,
`recovery` 0, `protection` 0. The keyword scan alone would not force the
deep lane; the persisted-format path rule does — stated so the tier call is
the rule's, not the scan's.

## 5. Measurable proofs — pre-committed acceptance rules

Written before any measurement ran. All fixtures are loopback doubles over
injected `SerialPortHooks` (the AR-4 fixture's own shape — no pyserial in
tests); invented names only; deterministic, so power analysis is N/A — each
arm's kill condition is behavioural, and every RED control names the
mechanism it neutralises.

- **AR-A (instance-keyed binding — THE core claim).** Fixture: two
  confirmed candidates, identical vid/pid and identity answer, distinct
  ports A=`/dev/match-a`, B=`/dev/match-b`, distinct serials. Scan →
  bind B → connect. SHIP: B's write log carries exactly the establishment
  exchange; A's write log is EMPTY; the store row's `port_path` is B. KILL:
  any frame on A, or a connect that opened A. RED control: neutralise the
  resolver to the constant-A form (the pre-slice behaviour) — the arm must
  fail by catching frames on A.
- **AR-B (the discriminator, both ways).** (i) Distinct-serials fixture →
  the row is `usb_serial`-keyed; re-enumerate with B's serial at
  `/dev/moved-b` → connect resolves to `/dev/moved-b` (path independence).
  (ii) Duplicate-serials fixture (both candidates serial `"X"`, or both
  null) → bind stores `port_path`-keyed; move the device to `/dev/moved-b`
  → connect refuses `not_ready`/`binding_stale` naming the stale path, and
  the OTHER same-class confirmed port receives ZERO writes (no fallback).
  KILL: either arm resolving through the wrong key, or any write to an
  unbound candidate.
- **AR-C (stale refusal honesty).** `usb_serial`-keyed row whose serial is
  absent from a fresh enumeration → connect refuses BEFORE any port open
  (the injected `opened` list stays empty); refusal is `not_ready`, reason
  `binding_stale`, naming the serial; the page renders the re-pick action.
- **AR-D (pick integrity).** `POST /devices/{id}/bind` with a `port_path`
  not in the confirmed cache → `invalid_request` with
  `standalone_binding_pick_unconfirmed:`; the store file's bytes are
  UNCHANGED (compared before/after). Bind while connected → `conflict`,
  bytes unchanged.
- **AR-E (NFR-O3 posture).** After a binding exists: GET `/` and the device
  page transmit nothing (all write logs unchanged); bind/unbind are POST-only
  (GET on the routes 405s); a bind POST without the CSRF header → 403 from
  the existing `CsrfGuard` (one arm proves the guard covers the new route).
- **AR-F (store honesty).** A planted malformed `device-bindings.json`
  refuses seam construction with `standalone_binding_schema:` (serve exit 2,
  no traceback); a duplicate `(package, connection_key)` row refuses at
  load; unbind leaves a valid document; a leftover `.tmp` from a killed
  write is inert (next write replaces it; load ignores it).
- **AR-G (precedence).** With a stored binding to A and `--device /dev/x`
  passed: connect opens `/dev/x` only, and the store file is byte-unchanged
  by the whole run.
- **AR-H (reload interplay).** Bind, then a confirmed plugin reload
  (`reload_plugin`): the binding survives (row present), reconnect resolves
  through it, and the reloaded plugin's connection establishment lands on the
  bound port (late-bound factory proof).
- **AR-I (the §0 CLI gap closes).** A seam built through `_build_seam`
  (the CLI path) with a connected serial session: a re-scan does NOT re-open
  or transmit on the connected port (the connected row is served from
  `last_resolution`; the `opened` list gains nothing for it). RED control:
  the pre-slice seam shape must fail this arm — it is the test that pins the
  retired-`serial_device_path` migration.

## 6. Top risks (each with its falsifier)

1. **Port-path churn on path-keyed benches** (replug ⇒ re-pick) makes the
   feature feel brittle. Falsifier: D-3's measurement — if CH343G-class
   bridges report distinct serials, `usb_serial` keying dominates and churn
   is rare; if they do not, the churn is PHYSICAL (the devices are
   indistinguishable) and the honest refusal is the correct floor, the
   fork's pick-per-connect made persistent.
2. **Synthetic/duplicated USB serials** (docks, some hubs) silently defeat
   serial keying. Covered at BIND time (duplicate-among-confirmed ⇒ path
   keying) and at RESOLVE time (≥2 matches ⇒ stale, never guess); falsifier:
   AR-B(ii) and a resolve-time duplicate arm.
3. **The result-schema widening breaks a consumer pinned to the old
   `_DEVICE_SUMMARY`.** The consumers are the UI, the parity suite and the
   gate-F readback — all move in the same PR; an external consumer would be
   additive-null-tolerant by JSON semantics. Falsifier: the full suite.
4. **Route-only bind is later wanted by agents** (headless rebind). Accepted
   by design (the trust argument, §1.5); the exit is D-4, an owner fork, not
   a schema accident.
5. **The store's CWD default surprises an operator serving from varying
   directories.** The accepted `capture_root` posture (Decision 9) with the
   same explicit/env overrides; the README names it. Falsifier: none needed —
   disclosed, not hidden.
6. **Serialisation with the in-flight I3b lane** (same seam/session files).
   The triage already rules the build queues behind I3b; the design changes
   `_op_device_discover` and the session factory signature — the rebase cost
   is bounded and named (commit ladder ordered so store/resolver land before
   the seam touch).

## 7. Maintainer forks (decisions this design needs from the owner)

- **F-385-1 (route-only bind).** Approve bind/unbind as host-side routes
  (D-B1 precedent, no catalogue/MCP exposure) — recommended; the alternative
  (catalogue rows 19+21's SW-10-delta class) is available but hands a
  bearer-holding agent silent endpoint moves.
- **F-385-2 (the CLI posture flip).** Approve retiring
  `standalone_transport_serial_device_required` (serial serve starts
  binding-pending; `--device` stays as the headless bypass) — recommended;
  the alternative keeps the refusal when no binding AND no `--device` exist,
  which blocks the UI-first flow this issue exists to build.

## 8. Repo-split answer (the dispatch's question 1, stated plainly)

**Standalone-first; the binding surface lives entirely in the SDK repo**
(`src/benchweave_sdk_server/{binding.py,serial.py,session.py,seam.py,
web.py,cli.py,catalogue.py}` + `templates/index.html` + `tests/server/`).
**The gateway is affected in ZERO bytes.** Its `provider_settings.py`
implements a different resolution (connection_key → provider CONTRACT, an
admission act) that is endpoint-free by standing obligation (drift-and-
obligations row 16), whose endpoint question is deferred to the
execution-standard commissioning shape with a named reopen trigger — the
first provider runtime implementation. This design does not cross that
boundary; it BUILDS the proven shape (discriminator, staleness semantics,
provenance row) that the reopen will want to promote, and records that
pointer as D-1. No interface-0.1.0 surface is touched; the standalone's own
catalogue (`bws_v1_*`, PRD 11's tool set, not the vendored corpus) carries
the one wire-visible widening (§3).

## 9. DON'T-BUILD verdict

Not a don't-build: the gap is verified in landed code (two indistinguishable
discovery rows; an unpersisted CLI-only endpoint; a short-circuit arg the CLI
never sets), every mechanism it needs exists and names its extension point
(the late-bound factory, the D-B1 route shape, `capture_root`'s resolution
family, the AR-4 fixture), and both outcomes of the open hardware fact are
carried by data, not branches. Four embedded DON'T-BUILD calls are taken
(§1.7): no gateway motion, no descriptor schema motion, no third
discriminator, no N-way concurrent serving. The two forks that need the
owner's word are F-385-1 and F-385-2.
