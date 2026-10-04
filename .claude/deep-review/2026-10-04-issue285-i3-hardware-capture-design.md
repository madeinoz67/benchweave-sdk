# Issue #285 — Standalone Web UI I3: hardware and capture — design record

Date: 2026-10-04. Status: DESIGN (no code written). Repo: `benchweave-sdk`
(expected branch `feat/issue285-i3a-serial`, created from `origin/main`).
Tracking: gateway issue #285 (single issue stream); PRD 11
(`docs/implementation-planning/11-standalone-web-ui-prd.md`, Draft v0.3) is the
requirements authority; PRD 12 carries the shared-renderer rulings.

Design lane note: the dispatched worktree `.wt/i3design-9307` did not exist and
this lane's sandbox refused all git operations outside its own gateway worktree,
so the record could not be committed as the branch's first commit from here.
The record's bytes are final for review; the builder lane lands this file
verbatim as commit 1 of the slice branch. Disclosed, not silent.

## 0. Verification of premises (done before designing)

- PRD 11 read in full from the gateway checkout (post-#312 edition claimed by
  the dispatch was checked: the on-disk file is "Draft v0.3, amended
  2026-10-03"). **Q1 is ruled (2026-10-02) and Q12 is ruled (2026-10-01, landed
  as #310). Q5, Q7 and Q13 are NOT ruled** — grep for "Ruled" over the PRD
  returns only the Q1 and Q12 markers — yet the I3 exit gate requires all five
  ruled. This is a gate-blocking gap the owner must close (§7 forks).
- The I2 seams I3 extends were read in the SDK tree, not assumed:
  `catalogue.py` declares `capture_start/stop/list/get/series/annotate` and
  `artifact_read` as deferred rows; `seam.py` carries `_capture_in_flight`
  ("no capture exists until I3; the flag is the state I3's capture_start will
  hold"); `session.py`'s `PluginSession(plugin, services_factory)` mints
  services per connection and its docstring anticipates "a real transport
  (I3)"; `plots.py`'s digital-lanes skeleton says "captures begin at I3".
- The fork (`parkview/benchweave`, public; cited by the PRD as provenance) was
  read over the GitHub API: `src/benchweave/web/host.py` (386 lines: reader
  thread into a 256 KiB ring, 64 KiB transfer ceiling, 100 ms quiet-line, OTDP
  §8.1 stream grammar, private `.part`→`.bin` artifacts), `src/benchweave/
  mcp_server.py` (14 tools over `BoardManager`/`CaptureLibrary`, MCP-tagged
  captures), `plugins/adc_6ch_12bit/` (descriptor: transport `type: "serial"`,
  2,000,000 baud, `max_frame_bytes` 262; binary framed protocol, SYNC `AA 55`),
  `plugins/adc_6ch_12bit/discovery.py` (IDENTIFY probing; VID alone explicitly
  distrusted).
- `"serial"` IS a legal transport type in the vendored OTDP 0.2.2 descriptor
  schema (`$defs.serialTransport`), so the fork's descriptor shape is
  schema-compatible; the schema grants no addresses/paths — USB identity can
  only ride the settings `x-` extension-key pattern.
- The SDK user guide already ships `SerialStandaloneHost`
  (`user_guide/plugin-sdk.qmd` §"A standalone runtime around the writer",
  pinned by `tests/test_guide_serial_host.py`): the documented eight-member
  `CaptureServices` composition over `StandaloneCaptureWriter`, adapted from
  the fork, without the reader thread. This is the direct in-tree precedent.
- I2 precedent: PRs #97/#98/#101 (merged). Their design records are NOT
  committed on either repo's main (gateway tree grep for `i2|284|285` under
  `.claude/deep-review/` returns nothing) — the I2 designs live in PR bodies.
  This record therefore cites the PR bodies as the I2 design sources.
- `pyproject.toml` `[server]` extra today: fastapi, fastmcp==4.0.3, jinja2,
  benchweave-ui-html==0.1.0 (+ uvicorn). No pyserial.

## 1. Mechanism

Four slices. Each lands as its own stacked PR (SDK repo); the fourth is a
fork-repo migration PR. No slice touches `src/benchweave_sdk/` core
(`capture.py`, `interfaces.py` unchanged — the I2 tripwire pattern carries),
`standards/` bytes, or version strings.

### I3a — the serial provider backend + discovery (SW-60/61/62, NFR-O2)

New module `src/benchweave_sdk_server/serial.py`:

- `SerialLink` — generalised from the fork's class: a dedicated reader thread
  drains the transport into a bounded ring (`bytearray` + `Condition`);
  overflow drops the OLDEST bytes; `take(exact, terminator, max_bytes,
  timeout)` returns only complete receives; transport errors fault the link
  and wake every waiter; close joins the reader. The fork's constants become
  constructor configuration with the fork's values as defaults:
  `ring_capacity=256*1024`, `transfer_ceiling=64*1024`, `quiet_s=0.1`. The
  effective per-receive ceiling is `min(transfer_ceiling, descriptor
  max_frame_bytes)` — the plugin's own declared bound governs (A02 posture).
- `SerialCaptureServices` — the full eight-member `CaptureServices`
  (interfaces.py's still-unbuilt "composing runtime"; #147 deferral row 7):
  real clocks; `transfer` validating the OTDP §8.1 generic stream grammar
  (strict field sets; `eom` termination refused on serial; `exact_bytes`
  precedence; quiet-line `{"data": b""}` after `quiet_s`; unfinished receives
  stay buffered across deadlines); `record_evidence` as JSONL; and the three
  capture methods delegating to a per-capture `StandaloneCaptureWriter` —
  NOT the fork's private `.part`/`.bin` artifact path. Appends are
  block-buffered (flush at 64 KiB, finalise, abort) so a streaming adapter's
  per-frame appends cannot explode the writer's one-file-per-chunk staging;
  the manifest digest is computed by the writer over flushed bytes only.
  This is the guide's `SerialStandaloneHost` productised, with the fork's
  reader thread for the 2 Mbps class; the module docstring cites the guide
  section, which stays as the copy-into-your-project form.
- `serial_plugin_session(plugin, device_path)` — builds the `services_factory`
  for `PluginSession`; a reconnect mints a fresh link (session.py's M1-fold
  per-connection precedent).
- CLI: `serve --transport serial --device <path>` (choice widens from
  `["mock"]`; `_build_seam` is the factory point); `transport_kind="serial"`
  means the `simulated` banner does not render (SW-72 already keys on it).
- pyserial joins `[server]` only (default dependency set unchanged; PKG-1/2
  hold). The `Transport` Protocol stays injectable so tests never need a
  real port (the fork's own shape).
- Discovery (SW-62): `_op_device_discover` on serial transport enumerates
  candidate ports, filters by the descriptor's declared USB identity WHERE
  DECLARED — an `x-` extension key under `transport.settings` (e.g.
  `x-standalone-usb-vid`), the only schema-legal lane since the descriptor
  grants no addresses — then confirms each survivor by opening it and running
  the adapter's `identify`, matching manufacturer/model from the descriptor.
  The ONLY transmissions during discovery are the identify exchanges; no
  parameter write, stream start or configuration ever fires. Ports that stay
  silent or answer foreign are omitted from the result (an unconfirmed port
  is not a device). A candidate equal to the connected session's port is
  served from the session's established identity without re-probing.
  **NFR-O3 interaction caught at design time:** `web.py`'s index route calls
  `device_discover` on every GET `/`. On serial that would transmit identify
  frames on page load — refused by construction instead: GET `/` serves the
  last discovery result (host state, initially empty with a scan prompt);
  scanning is an explicit POST that calls the operation.
- NFR-O2: a faulted link stays faulted (reconnect required); the seam's
  existing `not_ready` mapping and the page's persistent refused state carry
  it with no new machinery.

### I3b — capture through the SDK writer, the SQLite index, SSE live view, MCP capture tools (SW-33/34/50/51/54, NFR-Q3)

- Catalogue flip: the six deferred capture rows become `_spec` rows with
  authored input/result schemas; `capture_start` requires exactly one of
  `count` / `duration_s` (SW-33), plus optional `max_bytes`, `project`,
  `tags`, `notes`. The seam gains a `surface` parameter ("ui"|"rest"|"mcp")
  supplied by the dispatch layer (web/rest/mcp), not by clients — SW-34's
  originating-surface tag is host knowledge. Three NEW rows beyond SW-10's
  closed 18: `capture_delete`, `capture_pin`, `capture_unpin` (SW-56/SW-59
  name pinning and an MCP `capture_delete` tool but SW-10's list omits them —
  a disclosed PRD delta, owner fork F-2 in §7).
- Capture lifecycle: `capture_start` validates the bound, refuses when a
  capture is in flight or a reload is pending, checks the storage guard
  (I3c), mints `capture_id`, arms `seam._capture_in_flight`, dispatches the
  adapter's declared capture verb (`invoke`), and the ADAPTER appends bytes
  through the composed services into the writer. The host never fabricates
  data: progress is the writer's staged byte count; completion is the
  adapter's stop/finalise or the host-side bound watchdog cancelling the
  operation context at count/duration (SW-13's bounded-operation rule).
  `capture_stop` asks the adapter to stop, then finalises; if the stop's
  outcome is UNKNOWN after dispatch (A06), the host aborts the artifact and
  records `stop_unknown` — an ambiguous capture is never published complete.
- SW-54 metadata: the composed services write `metadata.json` into the event
  directory on the writer's FIRST append for the capture (device identity and
  firmware, plugin version and descriptor digest, the configuration read
  back at start, surface, operator = local OS user, project, tags, notes).
  The core writer is untouched (it owns directory creation inside append);
  a capture that never appends has no directory and reports aborted with
  nothing on disk — honest. Notes and tags are editable (`capture_annotate`);
  pin/unpin rewrite `metadata.json` atomically. Everything rebuildable comes
  from the capture root, never only from the index.
- New module `src/benchweave_sdk_server/library.py` (the fork's name,
  deliberately): a `sqlite3` (stdlib) index over the capture root —
  captures(capture_id PK, started_at, format, byte_length, sha256, surface,
  operator, project, pinned, tags, notes) — rebuilt at startup by walking
  the root (manifest.json + metadata.json per event). The index is query
  acceleration only. A lockfile in the capture root refuses a second host
  process over the same root (the stdio `mcp` entry and `serve` must not
  become the fork's two-writers hazard; one session owner per library).
- SSE live view: `capture_started` / `capture_progress` / `capture_stopped`
  ride the EXISTING `EventBus` and `/events` stream (I2c machinery — the seam
  is the only publisher); progress is coalesced to at most one event per
  250 ms carrying staged-byte deltas (SW-26/NFR-Q3's fixed frame budget).
  SW-51: the capture is host-process state, never request state — a browser
  disconnect cannot stop it; only `capture_stop` or the bound ends it.
- `capture_series` decimates by default through `plots.decimate_minmax`
  (`columns = max_points`, default 2,000; output ≤ 2×columns, min/max
  preserved); `max_points: 0` serves raw points, refused with
  `payload_too_large` above a configured sample ceiling. `artifact_read`
  serves bounded windows over published primaries (interface-0.1.0 shape).
  Unknown ids are `not_found`, never empty (SW-33).
- MCP: `mcp.py`'s registration loop + the `_tool_handlers` drift check make
  the new tools structural; schemas pin from the catalogue verbatim
  (`_pin_all`), and the gate-F readback extends to the new rows.

### I3c — retention, storage guard, shutdown (SW-49/55/56/57/58/59, NFR-O1)

- New module `src/benchweave_sdk_server/retention.py`: a rule engine — rules
  keyed by source tag and project, each with any of `max_age_d`, `max_count`,
  `max_bytes`; evaluation order deterministic (rule id); pinned captures are
  never eligible. **Defaults await the Q13 ruling** — the engine ships
  rule-driven with default keep-everything (fork F-3).
- Pruning (SW-57): never touches an in-flight capture (checks the armed flag
  AND requires a published manifest); runs on a schedule inside the host and
  on demand via CLI (`benchweave-sdk-server prune --dry-run`); each removal
  deletes the capture directory and its index row together and appends a row
  (capture_id, manifest sha256, rule, time, trigger) to an append-only
  `captures/retention.log` JSONL — the log is a file in the root, not an
  index table, so it survives rebuilds. Crash-orphaned staging directories
  (no manifest, not in flight, older than a stated grace) are removed under
  their own named rule and logged.
- Storage guard (SW-58): `capture_start` computes the worst-case bytes from
  the bound and refuses with `unavailable` when the free-space reserve would
  be breached; a running capture that reaches the reserve stops, FINALISES
  what was captured (nothing discarded silently — the manifest's byte_length
  is the truth), and records `stop_reason: "reserve"` in metadata + index.
- NFR-O1: lifespan shutdown (and `--authoring` reloads) run a seam close-down
  that cancels capture contexts, waits the declared op timeout, finalises or
  aborts, and only then closes the session. No half-written primary is
  possible (the writer's temp+rename finalise is atomic by construction).
- Library UI (SW-49): a captures list/filter view over `capture_list` +
  metadata (size, pinned state, next retention effect), rendered through the
  shared package's table partials; deletion asks confirmation naming the
  capture; the MCP `capture_delete` takes an explicit id and refuses pinned.
  Neither path bypasses the retention log (deletion reuses the prune
  recorder).

### I3d — the fork migration PR (exit gate, fork repo)

A PR against `parkview/benchweave` deleting `src/benchweave/web/host.py`,
`src/benchweave/mcp_server.py`, and the `web/` tree that imports them
(`app.py` cannot survive its imports; `board.py`'s picker becomes
`device_discover`; `library.py` becomes the SDK index), running
`plugins/adc_6ch_12bit` under `benchweave-sdk-server serve --transport
serial`. `app.js` deletion stays I4's gate row even if it lands in the same
PR. This repo contributes the PR; the fork's bench owns the hardware
evidence (§5 evidence boundary). Not tiered in our rubric.

## 2. Precedent (proven in-tree mechanisms extended)

1. `PluginSession` + per-connection `services_factory` (`session.py`) — the
   serial factory drops in where `mock_plugin_session`'s does.
2. The guide's `SerialStandaloneHost` (`user_guide/plugin-sdk.qmd`, pinned by
   `tests/test_guide_serial_host.py`) — the documented writer+transport
   composition this productises.
3. The fork's `SerialLink`/`SerialHostServices` — the threading model being
   generalised (constants→config); its private artifact path is NOT carried.
4. `LoopingMockHost` (`transport.py`) — the transport selection seam serial
   joins; SW-70's mock fallback stays the default.
5. `EventBus` + `/events` SSE + web.py partials (I2c) — capture events ride
   the same single sequence; no new event machinery.
6. `decimate_minmax` (`plots.py`, #310's ruling) — `capture_series`
   decimation, unchanged.
7. `StandaloneCaptureWriter` (`capture.py`) — the canonical artifact path;
   core untouched.
8. The catalogue→MCP pinning + drift-check machinery (`catalogue.py`,
   `mcp.py`) — flipping rows extends REST (routes already loop CATALOGUE) and
   MCP structurally.
9. The seam's op-mutex, FOLD-E refused-event publishing, and the
   `_capture_in_flight` reload guard (I2c) — capture ops join the same
   disciplines.

## 3. Invariants and cross-surface impacts

- SDK invariants: STD-1..6, PKG-1..3, SRF-1..3, TWO-1 untouched and upheld
  (no vendored bytes; wheel target list unchanged; scaffold untouched).
  STD-4 POSTURE extended: new refusal paths are `snake_case:`-prefixed
  (`standalone_serial_*`, `standalone_capture_*`, `standalone_retention_*`)
  with per-path tests (NFR-Q4); this is itself a Tier-3 trigger.
- On-disk formats: the SQLite index + `metadata.json` + `retention.log` are
  new persisted surfaces — Tier 3; all rebuildable from the capture root.
- Packaging: pyserial in `[server]` only (Tier-3 dependency add). NFR-P4:
  Linux/macOS/Windows; Windows serial legs are CI-corroborated only (W1) —
  POSIX-testable direct tests plus the CI Windows lane.
- Standards tripwire: empty by design — no `standards/` bytes, no vendored
  edits, no version strings, no serial provider CONTRACT authored (the
  backend speaks the GENERIC §8.1 stream kinds; a custom provider grammar
  would be corpus bytes and is explicitly out of scope — SW-61 is satisfied
  by validating against the §8.1 table exactly as `MockHost` and the guide
  example do).
- SDK obligations (docs/internal/drift-and-obligations.md): #1 CLI
  (`--transport/--device`, `prune`) → user_guide + README; #4 packaging
  (pyproject extra) → wheel/README install steps; #6 behavioral tests land
  in `tests/server/`; #8 landing order — SDK commits pushed before any
  gateway pointer advance (the pointer is the train's chore, not I3's diff).
- Gateway surfaces: none move in-tree (the `bws_v1_*` tools are not the
  vendored `stg_v1` corpus; PRD 11's own tool set). PRD 11 gains the Q5/Q7/
  Q13 rulings and the SW-10 delta note when ruled (owner PR, gateway side).
- The ui-html pin is untouched by this design; D-B5's 0.2.0 pin bump may
  ride a PR in this train when ui-html publishes (rider, not designed here).

## 4. Review tier and the Step-1 keyword scan (#254 form)

Tier per slice, SDK rubric (docs/internal/review-rubric.md): **I3a Tier 3**
(adds a dependency; adds refusal paths), **I3b Tier 3** (adds refusal paths;
new persisted format), **I3c Tier 3** (refusal paths; deletion semantics),
I3d fork-side. Maximum tier across slices: **Tier 3** → two independent
adversary lanes per slice (standing rule).

Step-1 keyword scan (the gateway rubric's eight keywords) over the EXPECTED
diff text of I3a+I3b+I3c (docs and code alike; estimates from the mechanism
above, to be re-derived at review against the real diff):
`threading` ≈ 8 (SerialLink reader thread + tests), `asyncio` ≈ 14 (capture
task, watchdog, tests), `sha256` ≈ 10 (manifest/retention-log/metadata
digests), `hashlib` ≈ 3, `subprocess` 0, `migrate` 0, `recovery` 0,
`protection` 0. Under the gateway rules the keyword hits alone put every
slice in the deep lane; under the SDK's own path rules the Tier-3 triggers
are the dependency add and the refusal-path additions, as stated above.

## 5. Measurable proofs — pre-committed acceptance rules

Written before any measurement ran. All fixtures use invented names; the
byte-rate class is the fork's published line rate (2 Mbaud ≈ 250 KiB/s), the
only hardware numbers this design borrows, cited as fork provenance.

- **AR-1 (I3a, conformance parity).** The scripted-exchange cells that
  exercise `MockHost` (exact-match transactions, §8.1 field-set refusals,
  quiet-line answer, deadline/cancel behaviour, short-write faulting) are
  re-instantiated over `SerialCaptureServices` with an in-process loopback
  `Transport` (no pyserial in tests) and pass; the same cells against
  `MockHost` stay green (one suite, two backends). RED control: a
  field-set-validation arm (an extra-field transaction must be refused
  BEFORE any byte is written — the loopback records writes and must show
  zero). Ship: all cells green both backends. Kill: any cell green on Mock
  and red on serial, or any write recorded for a refused transaction.
- **AR-2 (I3a, structural flatness — the CI-able half of NFR-Q3).** A
  10-second soak at ≥200 KiB/s through link→services→writer asserts: ring
  length ≤ capacity at every checkpoint; staged bytes == appended bytes
  (checksum); staging chunk-file count ≤ total/64 KiB + 1 (block buffering);
  after finalise, staging is gone and the manifest digest matches. Ship: all
  four hold. Kill: any bound breached or digest mismatch.
- **AR-3 (I3a/NFR-Q3, the 10-minute claim — throwaway harness, never
  committed, never CI; numbers recorded on the issue per the one-off
  benchmark rule).** Synthetic framed producer at ≥200 KiB/s for 600 s into
  the full path under a tmp capture root; process RSS sampled every 60 s
  (rows r1..r10). FLAT = every r2..r10 ≤ 1.10 × r1. KILL = any sample >
  1.25 × r1, or a least-squares slope over the ten samples whose 10-min
  extrapolation exceeds +25% of r1. UNDERPOWERED = samples vary >5%
  band with no monotone trend → one re-run at 900 s; a second ambiguous run
  is INCONCLUSIVE (measurement underpowered), never a pass. Evidence
  boundary: this proves the HOST at the fork's rate class on a loopback; it
  is not a real-hardware claim. The exit gate's on-hardware clause is the
  fork migration's evidence (I3d), owner-ruled.
- **AR-4 (I3a, discovery honesty).** Loopback fixture with four candidates:
  two answering identify with descriptor-matching identity, one foreign, one
  silent. `device_discover` returns exactly the two; the write log shows
  only identify frames reached any port; GET `/` transmitted nothing (last-
  result cache). Ship/Kill as written.
- **AR-5 (I3b, end-to-end capture).** Fixture plugin (invented name) whose
  adapter streams N scripted frames through `artifact_append`:
  start(bound=count) → list shows it in flight → bound completes → manifest
  published under the tmp root → `capture_get` digest == sha256(primary) →
  `capture_series(max_points=500)` returns ≤1000 points CONTAINING the raw
  series' true min and max (decimation property, not payload echo). RED
  controls: second `capture_start` while in flight → `conflict`;
  `capture_series` on an unknown id → `not_found`; a capture with zero
  appends publishes nothing.
- **AR-6 (I3b, rebuildable index).** After building a capture set with
  mixed pins/tags/notes, delete the SQLite file and restart: the rebuilt
  list/get state is identical. RED control: hand-strip `pinned` from one
  `metadata.json` → rebuild reports that capture unpinned (the file, not
  the index, is authoritative).
- **AR-7 (I3b, SW-51).** With the SSE stream attached, start a capture and
  disconnect the HTTP client mid-capture: the capture continues (a second
  stream observes progress to completion; the manifest exists). RED control:
  the test fails any implementation that ties the capture task to the
  request lifecycle.
- **AR-8 (I3b, A06 honesty).** An adapter whose stop returns
  `status: "unknown"` after dispatch: `capture_stop` surfaces the ambiguity
  (details carry the envelope's `dispatch_state` verbatim), the artifact is
  aborted, the index row records `stop_unknown`. RED control: no path may
  mark such a capture finalised-complete.
- **AR-9 (I3c, exit-gate retention clause).** A capture set across surfaces
  with engineered ages/counts/sizes; rules: mcp-source max_age 30d unpinned,
  project-P max_count 5, global max_bytes B. DRY RUN lists exactly a
  hand-computed golden set, each row naming its rule; PRUNE removes exactly
  that set; every removal has a `retention.log` row whose sha256 equals the
  removed manifest's digest (count and content match); pinned captures
  appear nowhere. RED controls: an in-flight capture is never in the set;
  the quota warning fires exactly once crossing 80% of B.
- **AR-10 (I3c, storage guard).** Mocked free-space reader: a bound that
  would breach the reserve → `unavailable` at start; a capture reaching the
  reserve mid-run stops, finalises with `stop_reason: "reserve"`,
  `byte_length` > 0 and equal to staged bytes.
- **AR-11 (I3c, NFR-O1).** Start a capture, terminate the app (lifespan
  exit): every event dir is either published (manifest present) or removed;
  no `.tmp` primaries; index consistent with the root.

## 6. Top risks (each with its falsifier)

1. **The 10-minute flat-memory claim is not ours to make on hardware.**
   Falsifier of the design: if AR-3's loopback run at the rate class shows
   growth, the host itself is unbounded and the slice is not shippable
   regardless of hardware. If loopback is flat but the fork's hardware run
   is not, the residual is device-driver-side (pyserial buffering), owned by
   the migration PR, not this design.
2. **Writer staging-file counts at extreme append rates.** Block buffering
   bounds files at bytes/64 KiB (~2.4k files for 150 MB) — workable but
   heavy; the durable fix is a core-writer single-staging-file API (deferred
   D-4). Falsifier: AR-2's chunk-count arm.
3. **Two processes over one capture root** (`serve` + stdio `mcp`): the
   lockfile refuses the second; Q5's eventual proxy ruling (F-1) removes the
   temptation entirely. Falsifier: a test that opens two library objects and
   asserts the second refuses.
4. **The catalogue extension (delete/pin/unpin) contradicts SW-10's closed
   18** — a PRD delta needing the owner's word (F-2). If refused, pin/delete
   drop to UI+CLI-only and SW-59's MCP tool is withdrawn with the PRD.
5. **Q5/Q7/Q13 unruled while the exit gate requires them ruled** — the gate
   cannot close on text that does not exist. Falsifier: the §0 grep.
6. **Discovery probing writes identify frames** — NFR-O3-safe only because
   scanning is an explicit POST and GET `/` serves cached state; a future
   route that calls discover on render re-opens the violation. Pinned by
   AR-4's GET-transmits-nothing arm.
7. **SSE bus growth**: capture_progress is cadence-bounded (250 ms), but the
   I2c bus never evicts — long-lived hosts accumulate rows. Existing
   property, disclosed; not widened by I3 beyond the cadence bound.
8. **Windows serial behaviour is CI-corroborated only** (W1): POSIX direct
   tests + the CI Windows leg; no local Windows claims.

## 7. Maintainer forks (decisions this design needs from the owner)

- **F-1 (Q5, stdio MCP transport).** Recommend option 2 (stdio shim proxies
  a running HTTP host; one session owner per device) with option 1 as
  fallback. I3 ships the lockfile guard either way; the ruling gates the
  exit gate, not the slices.
- **F-2 (SW-10 delta).** Approve `capture_delete`/`capture_pin`/
  `capture_unpin` as catalogue rows 19–21 (SW-56/SW-59 name the capabilities
  but SW-10's list omits them), or rule them UI+CLI-only.
- **F-3 (Q13, retention defaults).** Recommend option 2 (ui/rest kept until
  deleted; mcp 30 days unpinned; 80% quota warning). The engine ships
  rule-driven with keep-everything defaults until ruled.
- **F-4 (Q7, capture export).** Recommend manifest-primary + CSV as a
  rendering under `renderings/` (the writer already carries the concept).
  The ruling gates the gate, not I3b.
- **F-5 (evidence boundary).** Rule whether the exit gate's on-hardware
   clause closes on the fork migration PR's posted evidence plus our AR-3
   loopback numbers, or requires an in-repo hardware run (not claimable
   here).

## 8. Slice table and deferrals

| Slice | Ships | Defers (home) |
| --- | --- | --- |
| I3a serial+discovery | serial.py, session/CLI wiring, pyserial extra, conformance cells, AR-1..4 | provider contracts for custom kinds (never — generic §8.1 only); measurement profiles (upstream issue, PRD §10-4); DPS-150 second-adapter run (I4) |
| I3b capture+index+SSE+MCP | catalogue flip + 3 new rows, library.py, metadata sidecar, SSE events, bws_v1_capture_*, artifact_read, AR-5..8 | CSV export rendering (Q7 → I4); digital-lanes live rendering over captures (I4); writer single-file staging API (D-4, gateway tracker issue to be filed); Q5 stdio proxy (F-1) |
| I3c retention+guards | retention.py, prune CLI + schedule, retention.log, storage guard, NFR-O1 close-down, library UI, AR-9..11 | Q13 defaults (F-3 — engine ships keep-everything); archival-tier ideas (out of PRD scope) |
| I3d fork migration | fork PR deleting host.py/mcp_server.py + web/ tree, ADC under the standalone host | app.js deletion (I4 gate); Analyse/report features (I4, SW-52/53); hardware evidence (F-5) |

Deferral homes: gateway tracker issues to be filed for D-4 (writer staging
API) and the Q5/Q7/Q13 ruling reminders; everything else lands in PRD 11's
own increment rows (I4) or upstream issues already named by the PRD.

## 9. DON'T-BUILD verdict

Not a don't-build: every seam I3 needs exists and names I3 (deferred
catalogue rows; the armed `_capture_in_flight` flag; the "captures begin at
I3" disclosure; the guide's worked example; the fork's proven pattern). Two
embedded DON'T-BUILD calls ARE taken: no custom serial provider contract
(corpus bytes; generic §8.1 kinds suffice), and no measurement profiles
(upstream contract gap). The premise verified; the one gate-blocking
premise failure is the missing Q5/Q7/Q13 rulings (§0, §7).

## Addendum (2026-10-04, refute fold) — capture_max_bytes semantics and the
## parity ruling

Dated addendum; sections 0–9 above stay frozen as written. This documents
what the two-lane refute fold (lanes A+B, same day) CHANGED about the
mechanisms §1 described, so the record and the code agree.

capture_max_bytes: the WRITER is the reservation's authority. The
StandaloneCaptureWriter enforces the reservation at every flush and at
finalise. The services layer's append guard is a conservative buffer-path
refusal only (an un-staged span larger than the whole reservation, refused
before buffering); it is not the reservation's enforcement point. A
refused capture is CLEANABLE: the writer attaches before any check that
can refuse, the buffer retires only on the writer's acceptance, and a
services-level abort removes an un-finalised capture's event directory
(gated on the writer's own manifest.json publication marker), so the
capture_id is reusable after the abort. The flushed accounting moves only
on the writer's acceptance, so refusal messages name true counts and a
refused flush loses no bytes. §1's original tail-crossing description —
"the last flush refuses" — stays true; the fold added the property that
mattered: the refusal leaves the capture abortable and the id reusable.

Parity ruling (FOLD-D, decided by the documented surface): the guide's
SerialStandaloneHost example (user_guide/plugin-sdk.qmd, section "A
standalone runtime around the writer") mandates bytes-only data on the
serial surface (`isinstance(data, bytes)` strict), so the serial backend
stays strict. MockHost's whole-dict equality accepts a bytearray where
bytes were scripted — that leniency is a DISCLOSED two-backend divergence
(asserted and pinned in the instantiated conformance cell set); a future
mock tightening flips that cell deliberately. The mock's other transmit
discipline DID move to the real backend: the serial services now enforce
dispatch markers (ConformanceError on an unmarked stream_send or
stream_exchange), matching MockHost. The guide's example itself does not
enforce markers — it stays the copy-into-your-project floor; the
productised backend adds the discipline. Deferral: the guide's example is
not updated in this fold.


## Addendum (2026-10-04, fold-refute wave)

- An adapter that transmits without a dispatch marker is omitted from serial
  discovery (fail-closed, AR-4) — now with a logged warning naming the port
  and the conformance refusal, not a silent empty result (fold-refute 1).
- The writer enforces the reservation at every append; the addendum's earlier
  "at every flush and at finalise" named a check that does not exist at
  finalise (fold-refute 4).
- capture-id reuse after abort is a same-process guarantee; a crash-left
  event directory reserves the id until the capture root is cleared — the
  orphan sweep belongs to I3c (fold-refute 3).
