# Design record — gateway issue #589: live bring-up, generic device admission (rev 7)

Date: 2026-11-06. Branch: `fix/589-live-bringup-generic` (from `origin/main`). This record
is the slice's first commit. **Revision 2** — the issue grew from two defects to nine
(three comments landed mid-design; one defect was withdrawn with evidence), the principal
issued a standing generality directive ("flexible for all types of devices, not just the
logicport" — stated three times), and the device is now ATTACHED on the live bench, so
live proof is available. Rev 1 covered defects 1–2; rev 2 covered the full set, added
the generality gate, and re-planned the work as a PR STACK. The pin-divergence question
closed in this sequence — included (rev 2), removed on challenge (rev 3), restored on the
team-lead's census retraction (rev 4) — and **revision 5 records the maintainer's FINAL
ruling: the divergence is REMOVED; the resolver MATCHES the gateway.** What decides it is
the SEAM census, not the objection: no classref test constructs a host seam, and every
catalog-invalid non-OTDP row of the 45-entry census sits under `tests/fixtures/classref/`
(check-lane fixtures only) — so the hard arm refuses exactly what the gateway refuses and
breaks nothing in this suite; parity ("what the SDK accepts is what the gateway accepts")
beats the convenience argument, which was the census's right evidence used for the wrong
conclusion. Rev 5 keeps rev 4's other rulings: D8 MITIGATED not PREVENTED (§3.2), the
discovery boundary named (§2.2), PR-5 separate, the source note, and the plugin-side
diagnosis as rev 3 sharpened it (wrong document SHAPE, not missing fields; one document,
not two). **Revision 6 folds the refute lanes' wave** (the team-lead's instruction called
this "rev 5" — the wave landed after rev 5's divergence removal had already been
applied, so the numbering here runs one ahead; same document). The wave's eleven
items: (1) the pin-skip stays OUT, now with lane 2's decisive property — the pin's
`id` is plugin-chosen, so any URN-keyed skip is a gate the plugin operates (§3.1);
(2) the post-dispatch RESULT gates are served — closed `{action_id, result}`
envelope, echo, `output_schema` (§3.1); (3) bare-VID enumerates through the pyusb
vendor scan, since `find_all`'s None-pid is broken (§2.2); (4) the emitted
selector's `%d` is the 1-based control-interface index and the scan emits ONE
SELECTOR PER INTERFACE (§2.2); (5) exception types pinned per prefix at the seam
boundary (§2.2); (6) numeric-serial round-trip — the fallback reuses the
selector's own serial, never drops it (§2.2); (7) four MEDIUMs: enumeration cache
(`nocache=True`), resolution-class gating of the fallback, close-on-failure
reinstated, malformed selectors get their own prefix; (8) reload resolves the
incoming contracts BEFORE the session swap; (9) four LOW one-liners (§2.2);
(10) the per-action contract ruling revised — `timeout_ms` and `retry=never` stay,
invented `side_effect`/`cancellable` behaviour dropped, strictness disclosed
(§3.2); (11) PR-2 must not claim invoke unblocks bring-up — the data path closes
in PR-3 (§7). **Revision 7 re-opened the record after a THIRD refute lane ran against rev 6's
own bytes** (the lane was dispatched to verify the folds, and it found the folds faithful
while finding three things the folds had not reached). Rev 6 was frozen and the build had
started; this revision supersedes it and the builder was re-pointed. Seven folds:
(1) the generality gate's four rules are rewritten — the `stop` rule widens to ALL quoted
positions because the measured fact is that `src/` contains ZERO quoted `stop` today, so
the dict-key carve-out protected nothing and cost the `== "stop"` value-position hole (§0.3);
(2) device literals gate on the CLASS (hex `{1,8}`), not this device's spellings, since
`0xdc49` and sub-4-hex `0xfa3` both passed the rev 6 rules (§0.3); (3) the false claim that
the vendored `standards/` tree has no `.py` is replaced — it has exactly one,
`plugin-ui/contracts.py`, lock-recorded — and the exclusion becomes LOCK-DERIVED and
counted, so a corpus sync changes an assertion instead of reddening a gate the SDK cannot
fix (§0.3); (4) `PROVIDER_EXECUTORS`' exemption is counted like every other exemption
(§0.3); (5) the selector grammar is rewritten to parse uniquely — `[:/]` as a VID/PID
separator made `0403/dc48/2` two-parse, so the separator is colon-only and `/N` is the
sole interface spelling (§2.2); (6) §7's blanket "every refusal a prefixed `ValueError`"
contradicted §2.2's three connect-boundary `RuntimeError` pins and would have transcribed
the wrong invariant into `invariants.md` (§7); (7) `add_custom_product`'s containment
widensto the MEASURED effect — registration contaminates `Ftdi.PRODUCT_IDS` so a later
joker-URL enumeration sees the pair, and pyftdi 0.57.2 has NO `del_custom_product`, so the
fold is a save/restore of the class table in a `finally` with an arm (§2.2, §9 R4). Plus
the principal's host-admission RULING (§4, verified on #589 at 2026-11-06T12:24:22Z) and
three one-clause corrections (bare-VID boundary, `%d` prose, table-gate signatures pin the
exception TYPE not its message). **FROZEN.**

Triage: PUBLIC. Mechanisms, invariants and measurements only. The plugin this was measured
against is "a real plugin project"; its vendor, package name, repository URL and the
device's descriptor-carried serial are absent. The VID/PID pair `0x0403:0xdc48` appears in
THIS RECORD's evidence sections (generic USB hardware identifiers, the same class the user
guide prints) but — by gate, not by discipline — nowhere in `src/`.

Tooling note: the Gortex MCP server was unavailable for this session (checkout discovery
failed; no graph access granted). All reads were `Read`/`grep`/`sed`. No daemon started, no
tracking changed.

Sources, and which half is first-hand: this SDK checkout was read DIRECTLY (every
`src/` claim above was verified against the tree); the gateway checkout was read
directly where cited, READ ONLY for reference semantics (`otdp_bridge.py`,
`registry/otdp_contracts.py`, `registry/otdp_loading.py`, `content/dataset_services.py`);
the real plugin project READ ONLY as measurement corpus; the issue's comments were
RELAYED by the team-lead (extracts and summaries — including the fifth comment that
widened D8, the retraction, and the fixture census); the live-bench measurements (the
0.9 ms read, the serial readback, the `find_all` shapes) are the team-lead's,
re-verified here against pyftdi source where they touch library behaviour. Finding
text was relayed; every `src/` claim was verified against the tree — a later reviewer
should know which half is which. PKG-1 is unchanged: nothing in any PR reads the
gateway checkout at test or runtime.

The red team may still be filing. §8 names the seams where a new defect attaches — a new
row slots into the stack without redesign.

---

## 0. The standing property: DEVICE-GENERIC and ACTION-GENERIC, by gate

The principal's directive, made a structural property rather than a comment:

1. **The FTDI binding serves any FTDI-class device** — arbitrary VID/PID (OEM-rebranded
   included), multi-interface devices with an explicit, operator-visible interface choice,
   twins sharing one VID/PID (refused, never guessed), devices with and without iSerial,
   and bare VID/PID selectors. No device identity literal in `src/`. The
   `ProviderExecutor` registry (`ftdi.py:861-933`) is the precedent: the transport's
   machinery is family-agnostic and a second provider family plugs in by registering an
   executor — the selector ladder must be the same shape.
2. **The action surface serves whatever the descriptor declares.** The host dispatches on
   the descriptor's `actions` map and the pinned catalog's compiled registry — data, never
   `src/` vocabulary. The descriptor's `binding: {kind: "adapter", key: "…"}` is the only
   binding kind the vendored descriptor schema admits today (checked:
   `otdp-device-descriptor.schema.json` `properties.actions.additionalProperties.properties.binding`
   has `kind: {const: "adapter"}` — a non-adapter kind is schema-invalid and unreachable
   here); the host dispatches `invoke` with `action_id` = the map key and treats `key` as
   the adapter's own routing token it already consumes. If the corpus ever admits another
   kind, the host's `invoke` handler is the single switch point (§8 seam S3).
3. **Generality is a GATE that fails closed** — `tests/test_generality_gate.py`, landed
   with PR-1 (where the device literals actually live), in the spirit of
   `test_zero_literal_gate.py` / `scripts/count_version_literals.py`:

   - **Scope.** Every `.py` under `src/`, both packages. The vendored tree is excluded by
     LOCK MEMBERSHIP, not by assertion: the excluded set is exactly the paths
     `standards-lock.json` records, and the gate asserts
     `lock_excluded_files == <the lock's own file count>`. Rev 6 claimed the vendored
     `standards/` tree "has no `.py`" — **false, and refute-proven**: it contains exactly
     one, `plugin-ui/contracts.py`, which is lock-recorded and scanned by a naive `.py`
     glob. The lock-derived exclusion is what makes the difference: a corpus sync that
     vendors a second `.py` moves an asserted number instead of reddening a gate the SDK
     cannot fix. The banked `providers/*.json` are contract documents, excluded by
     extension.
   - **Device identity, gated as a CLASS.** FAILS on any `0x[0-9a-fA-F]{1,8}` hex literal
     under `src/` — one to eight digits, so a near-miss PID (`0xdc49`) and a sub-4-hex
     value (`0xfa3`) both redden, where rev 6's `{4}` rule passed them. Excepted: inside
     the `PROVIDER_EXECUTORS` registration block (located by symbol, not line number), and
     the committed allowlist of bit-mode masks, each entry carrying a comment naming why.
     The block is the sanctioned family configuration — the one place a family's identity
     may live; the ftdi family's vendor id already sits there beside `_FEATURE_PREFIX`.
   - **This device's own literals stay denied as a regression layer**, separate from the
     class rule and honest about being narrower: `0x0403`, `0xdc48`, `53305982`,
     `logicport` (case-insensitive). If anyone ever hardcodes our device, this reddens;
     the class rule above is what catches hardcoding anyone's.
   - **Action names, ALL quoted positions.** FAILS on `configure_fpga`, `set_trigger`,
     `set_trigger_position`, `read_samples`, `resync` and `stop` as quoted strings
     anywhere (`["']name["']`), dict key, comparison value, or argument. Rev 6 restricted
     `stop` to dict-key position and justified it by claiming that was "the only way
     `src/` could name the plugin's action" — **refute-disproved and measured here**:
     `grep` finds ZERO quoted `stop` in `src/` today, so the carve-out suppressed nothing
     while leaving `if action_id == "stop":` and `.get("stop")` invisible. Bare words
     (`stop_event`, `.stop()`) are unquoted identifiers no rule touches. Zero expected
     suppressions, unchanged by the widening.
   - **Denominator printed and asserted** (review-rubric G4): the gate reports
     `files_scanned`, `literals_examined`, `allowlisted_entries`, `block_exempted_literals`
     and `lock_excluded_files`, and asserts each against its committed value. Rev 6 left
     the `PROVIDER_EXECUTORS` exemption uncounted — an escape hatch with no denominator —
     so rev 7 counts the in-block literal set too: growth inside the sanctioned block is a
     red test, not a quieter exemption.
   - **Why this cannot be trivially satisfied while staying device-specific — and the
     honest residual.** The gate catches LITERALS, not computations: `int("0403", 16)`
     or a config default smuggles a constant past it. Nothing syntactic catches that.
     The defense is two-layer and the residual is named: (a) structurally, no
     device-specific value NEEDS to exist — the selector comes from the operator, the
     binding store, or the pinned contract, so a hidden constant has no consumer; (b)
     behaviourally, the archetype matrix (§6) exercises ≥3 distinct device shapes through
     the same code path, so a path that only works for one shape reddens an acceptance
     arm even when the gate is blind. If someone reintroduces a special case behind a
     computed constant AND it matters behaviourally, layer (b) is what catches it; if it
     does not matter behaviourally, it is dead code the complexity ratchet flags. **A
     second residual is now explicit rather than papered over:** a DECIMAL device identity
     is not gated as a class. Rev 6 listed the two decimals this device happens to have
     (`1027`, `56392`), which is device-specificness wearing a generality rule's clothes,
     and gating all decimal literals instead cannot distinguish a USB id from a timeout, a
     buffer size or a baud rate. Decimal identities join the computed-constant residual
     above, with the archetype matrix as the behavioural backstop; the named-literal
     denylist still covers our own device's serial.

**FOLD-WAVE CORRECTIONS TO THIS SECTION (2026-11-06, post-rev-7), appended not
rewritten:**

- **The denominator sentence above ("asserts each against its committed value") is
  amended by fold F.** `files_scanned` and `literals_examined` assert FLOORS now, not
  equality: equality reddened every later PR by existing — the PR-1 fold wave's own
  source edits moved `literals_examined` 17487 → 17533 with zero findings, the live
  demonstration — and a gate that reddens on unrelated work earns exemptions and then
  gets weakened. `allowlisted_entries` and `block_exemptions` remain EXACT (a growing
  exemption is the thing to fight; a floor could never catch one). A floor still reddens
  on a narrowed scan, which is the pin's stated purpose.
- **Fold E amends the class rule's detector.** The `0x[0-9a-fA-F]{1,8}` spelling above
  was one spelling of one value: `0XDC49` (uppercase prefix), `0x000000dc49` (padding
  past the digit cap) and `0xdc_49` (PEP-515 underscore) are legal literals the regex
  passed, planted with `findings=0` by refute lane 2. Detection is now spelling-agnostic
  from the tokenize stream — a hex NUMBER token by what it IS, not by one spelling.
- **Fold I amends the regression layer.** The OEM pid is substring-banned as bare
  `dc48` (pair, prefixed and padded spellings all contain it), and the family vendor id
  is denied as a string by EXACT value only: `'0403'` and `'0x0403'` passed as bare
  string constants while the int values were denied, but the `--device` help and the
  guide legally print the vendor id inside example sentences that name the FAMILY every
  FTDI device shares — a substring rule would redden documentation.
- **A third residual, named (fold H): NON-`.py` DATA FILES under `src/` are invisible
  to the gate.** A `src/**/devices.json` carrying a full identity (vid/pid/serial as
  text) is caught by nothing and moves no denominator — the scope bullet above says
  `.py` and names the banked `providers/*.json` exclusion, but not this. Deliberately
  not scanned in the fold wave: a text-substring sweep over data formats needs its own
  false-positive discipline per format (JSON keys, YAML tags, encodings), the banked
  contract documents are digest-pinned where they live, and the selector never reads a
  device identity from a data file — the operator, the binding store or the pinned
  contract supply it, so a planted data-file identity has no consumer (the same
  structural defense the computed-constant residual names). If a future family ever
  loads identity defaults from a data file, this residual is the row to close first.

---

## 1. Defect ledger — nine red-team defects, two found by other means, one withdrawn, every row carried by a named carrier

| # | Defect | Status | Evidence (read, not inherited) | PR |
|---|---|---|---|---|
| D1 | FTDI binding cannot resolve the device URL | **Real blocker, mechanism final** | §2 below; three independent faults in `_pyftdi_enumerate_urls` + pyftdi's `PRODUCT_IDS` table gate, live-measured | PR-1 |
| D2 | Standalone host serves no custom actions | **Real blocker** | `catalogue.py` 23 names, no `invoke`; adapter side done in the plugin | PR-2 |
| D3 | Live read blocks for the full USB timeout | **WITHDRAWN with evidence** | Live bench: `read_data(4096)` → `b''` in 0.9 ms at timeouts 5000/5000; `read_data_bytes` has two fast exits (software-buffer hit; one bulk read returning short) and libusb completes on the first short transfer; the FTDI chip always answers bulk IN with ≥2 modem-status bytes within the latency timer. The full 5000 ms is reachable only when the device returns nothing at all — and then pyftdi raises `FtdiError` (an exception, not a silent wait). The filing session accepted this and rewrote its comment to lead with the withdrawal. Surviving LOW clean-up (folded into PR-1): `FtdiStreamAdapter`'s docstring (`ftdi.py:495-505`) describes a read pacing the driver does not perform as stated, and `_READ_CHUNK = 4096` deserves a look against a largest-reply of 2052 B — a docstring truthing + one constant review, NO timeout-tuning fix. NOTE: the red team's class table lists D3 as reaching "every FTDI class device" — that row inherits the refuted 5-second premise and does NOT re-admit the defect by scope inflation. | (withdrawn; LOW row in PR-1) |
| D4 | No path to admit device data: `dataset_id` never minted, no dataset services | **Real blocker** | `HostOperationContext.dataset_id` declared (`session.py:964`) and assigned nowhere; no `DatasetServices` implementation in `benchweave_sdk_server` (the protocol ships honest-no-implementation, `tests/test_dataset_services.py`); the plugin's fetch action refuses without `context.dataset_id` | PR-3 |
| D5 | Display path admits only `waveform_f64le` — and `raw_binary` is the DEFAULT the display refuses | **Real blocker, worse than filed** | `analysis.py:249-256` (`standalone_report_format_unsupported:`), `seam.py:2291-2297` (`capture_series` sibling refusal); meanwhile `_FORMATS` admits both (`catalogue.py:270`), `format` defaults to `raw_binary` at `catalogue.py:304`, `mcp.py:99` and `seam.py:1878`, and `_BYTES_PER_SAMPLE`/`_PRIMARY_SUFFIXES`/finalise all handle it. A caller who omits `format` — the most common path — gets a capture the display refuses: a self-contradiction in the SDK | PR-4 |
| D6 | `capture_start`'s invoke fallback passes capture arguments verbatim; the adapter needs `{action_id, input}` | **Real blocker (the fallback is dead code that lies)** | `_resolve_capture_verb` (`seam.py:1758-1772`) falls back to `invoke`; `begin_verb` (`session.py:1167`) passes arguments verbatim; no generic source for the `action_id` exists in the descriptor | PR-3 |
| D7 | No capture verb, no artifact members, inline snapshot never admitted, `capture_stop` never stops the device | **Real blocker in its data half; moot in its capture half under the dataset model** | §5: with D4's dataset admission, an invoke-only plugin's data path is invoke→dataset; the streaming-capture members belong to plugins that declare a capture verb | PR-3 (+ seam S2) |
| D8 | `reset` verb unreachable; widened: an action's declared parameter range admits work its verb budget forbids | **Real (two rows)** | `verb_timeout_ms` (`session.py:1054-1060`) reads only `operations[verb].timeout_ms` — grep across `benchweave_sdk_server` finds ZERO reads of `actions[`, `side_effect`, `cancellable`, `"retry"`; the plugin's `attempts` max 20 × 22.96 s/slot breaches the 60 s invoke budget with nothing to catch it | PR-2 |
| D9 | Declared descriptor surfaces the host ignores | **Real, split across PRs** | unread: `actions`' four behavioural fields (PR-2), `identify` returning `None` for `serial`/`firmware` where `_IDENTITY_RESULT` (`catalogue.py:164-178`) requires strings (PR-2), `required_features`, `read_policy.side_effect`, `profiles` (PR-5), `channels` (cross-checked in PR-3's dataset validation), `contracts` (read from PR-2) | PR-2/3/5 |
| **D10** | **The GATEWAY requires `dataset_publish`; the standard now says the host admits on result.** Created by the principal's ruling (verified #589 `2026-11-06T12:24:22Z`), not filed by the red team — the ruling's own "what follows" row says the gateway stops requiring it | **Real, and it lives in the OTHER repository** | `otdp_bridge.py:1462-1479` returns `InvalidInvokeResult` unless the action published; the plugin declares host-admission (`adapter.py:1216-1217`) and does not change. The SDK side closes in PR-3; the gateway side needs its own PR on `madeinoz67/benchweave` | **GW-1 (gateway repo)**, opened at PR-3's open time; until it merges, the divergence is DISCLOSED in the three places the ruling names (§4): this record, `host_info`, and the refusal text |

| **D11** | **A CARRIER defect, not a content defect: the slice's first commit carried four-revisions-stale bytes under a message claiming a later revision.** The drafting agent regenerated the design record from its own context instead of copying the frozen file, so it committed 704 lines of rev 2 — before the generality gate, the nine-defect ledger and the PR stack existed — while the message said rev 5 | **FIXED before any code was accepted** | `git show HEAD:…design.md \| wc -l` → 704 and title `(rev 2)` against a "rev 5" message; amended to the frozen rev 7 (958 lines). Caught by reading the committed artifact, not by any gate: **every gate planned for this slice would have passed it** | PR-1 (its first commit, amended) |

**Every row has a carrier, and D10 is the one that is not in this repository.** It is
recorded here rather than left implicit because the ruling permits an interim disclosure
and a disclosure is only honest if it is a scheduled row with a named owner. PR-3 must
not close while GW-1 is unopened. **GW-1 is a NAMED carrier WITHOUT an owner as of this
revision**: the standing carve-out for working the principal's designated repo covers
issues on one named repo, and that field is unpopulated in both sessions' operational
rules, so neither session may authorise an outward-facing gateway write on its own
judgement. D10 is surfaced to the principal with GW-1 ready to fire.

**D11 is the row this record exists to make embarrassing.** A design record's whole
function is proving the acceptance rules were pre-committed; one that silently omits
three revisions of itself satisfies the form and defeats the purpose, and it is
indistinguishable from an honest stale commit until someone diffs the bytes. It is
recorded as a carrier defect — the artefact carrying the rules was wrong, not the rules —
because that is the class the process review should walk, and it outranks any single
content finding from the refute lanes in consequence.

The red team's framing, quoted for the rationale: **"Five defects found on one instrument
is a plugin problem. Five defects that four of nine device classes share is an SDK design
problem."** (Vocabulary corrected below — the "nine" are transport types — but the
argument stands and matches the principal's directive: these are host-side gaps, and the
repairs belong in the host.)

**Denominator correction, adopted:** the red team's fourth comment calls
`lan_scpi, usbtmc, uart_scpi, uart_json, serial, can, i2c, spi, custom` "nine device
classes". Verified against the vendored schema: those are `transport.type` enum values
(`otdp-device-descriptor.schema.json`, transport properties + conditional branches). The
device-class surface is the profile catalog: the vendored `device-profile-catalog.json`
carries **12 profiles** (`otdp.dc_psu` … `otdp.vna`, counted) and the class archetypes
live under `standards/otdp/0.2.4/examples/class-*.json` (13 files including
`class-action-vectors`). This record uses the 12 profiles / `class-*` names as the class
denominator; no PR body says "nine device classes".

---

## 2. PR-1 — Defect 1: the device-generic FTDI selector (file: `benchweave_sdk_server/ftdi.py`)

### 2.1 Root cause, final

**pyftdi 0.57.2's URL path searches only the static `Ftdi.PRODUCT_IDS` table**
(`ftdi.py:57-90` — seven official FTDI PIDs; an OEM PID is absent). `UsbTools
.enumerate_candidates` (`usbtools.py:399-405`) builds its entire USB search set by
iterating that table; the URL's parsed product is a POST-filter (`usbtools.py:412`),
never part of the search. The device is never queried: candidates come back empty and
every URL form dies "No USB device matches URL" — or, serial-bearing form, with the
misleading "No USB device with S/N …" because the serial pre-check (`:407-408`) runs
against the same table-gated enumeration. The URL parser itself is fine. The fourth
failing form, `ftdi://ftdi:0x0403:0xdc48/1`, ADDITIONALLY misparses: a 3-component
netloc is `[vendor][product][serial]`, so it reads vendor `0x0403`, product `0x0403`,
serial `0xdc48` — unfixable by registration and documented, not silently supported.
The grammar is `ftdi://[vendor:[product:[serial|index]]]/interface` and the record's
docs leg states it.

**The SDK's enumeration has never worked, on any host, any device — three independent
faults in one function** (`_pyftdi_enumerate_urls`, `ftdi.py:1351-1364`):
1. `UsbTools.find_all([(0x0403, None)])` — a `None` PID matches nothing (live-measured:
   `[]` on the bench with the device attached);
2. `[0]` on the empty result → `IndexError`;
3. were it non-empty, `[0]` is one `(descriptor, interface_count)` pair and
   `for url, _ in found` unpacks the 7-field `UsbDeviceDescriptor` → `ValueError`.
Plus `0x0403` hard-coded — alone a generality-gate violation. The function is REPLACED,
not patched.

**Interface semantics, from source, with the coercion trap** (`ftdi.py:2024-2031`):
pyftdi's interface argument is 1-BASED (`_set_interface` does `config[(ifnum-1, 0)]`;
`interface=1` selects USB interface 0 — this device's only interface, and the issue's
working call). `/0` is SILENTLY COERCED to 1 (`ftdi.py:2026-2027`, undocumented);
`/2` on a 1-interface device parses clean and fails LATE as `FtdiError('No such FTDI
port: 2')` (`ftdi.py:543-545`); negative fails with a different type. The selector
validates `1 <= port <= ifcount` at ITS OWN boundary (`ifcount` = the int in each
`find_all` row, `usbtools.py:96`), refuses `0` explicitly with the allowed range named,
and delegates nothing to pyftdi's late, split, lying-by-coercion guards. `find_all` is
one entry per physical device PLUS an interface count — never a per-interface listing;
no selector logic may assume otherwise.

**Duplicate devices: never first-match-wins.** `Ftdi().open(vid, pid)` with no
serial/index resolves via `list(devs)[0]` over a SET — nondeterministic ordering
(observed picking address 9 before address 3 on the bench). The URL path refuses
ambiguity; the selector must too: >1 match without a serial refuses typed, demanding a
serial.

**Serial readback settled on hardware:** `usb.util.get_string(dev, dev.iSerialNumber)`
returns exactly the descriptor-carried string at the device's bus/address — the serial
pyftdi would compare IS the reported serial; the serial form failed for the table-gate
reason only.

**CORRECTION (fold wave, 2026-11-06, post-rev-7): the sentence above this paragraph
overstates the ladder — "delegates nothing to pyftdi's late guards" was false for the
URL arm.** Refute lane 1 measured it: `ftdi://0x0403:0xdc48/2` answered
`device_unavailable` ("URL attempt: FtdiError") while `0403:dc48/2` answered the typed
`interface_out_of_range` ("1..1") — one operator mistake, two spellings, two causes,
because pyftdi's late interface guard fired inside `open_from_url` before the ladder's
own range check could run. §2.2's mechanism is the authority and the code now follows
it exactly: the URL arm's failure gate is TYPE-based on BOTH resolution classes
(`UsbToolsError` OR `FtdiError` — the late interface guard is pre-claim, so routing it
to the enumerated path cannot smuggle a claim retry), and the enumerated path re-types
the failure with its own `1 <= port <= ifcount` check, so both spellings of a bad port
now refuse identically. A claim/busy/permission failure still arrives as pyusb's
`USBError`, wears neither class, and refuses immediately — §2.2's carve-out is intact.

### 2.2 Mechanism

**Selector grammar** (the `--device` value on `--transport ftdi`, and the binding's
`ftdi_url`): two forms. URL form (`ftdi://…`) — passed through `open_from_url` FIRST
(unchanged incumbent path for standard-PID devices and explicit `/N` interface choice).
VID/PID form — **colon is the VID/PID separator and `/N` is the ONLY interface
spelling**, so every accepted string has exactly one parse:
`^(0x)?[0-9a-fA-F]{1,4}:(0x)?[0-9a-fA-F]{1,4}(:[A-Za-z0-9._-]{1,64})?(/[0-9]{1,2})?$`
— e.g. `0403:dc48`, `0403:dc48:53305982`, `0403:dc48/2`, `0403:dc48:53305982/2`, with
the interface suffix defaulting to 1 and the serial carrying no separator charset of its
own. Rev 6's `(0x)?[0-9a-f]{1,4}[:/](0x)?[0-9a-f]{1,4}` also accepted `/` as the VID/PID
separator while `/N` was a suffix, which made `0403/dc48/2` two-parse; it also failed to
express the `[:serial]` and suffix components in the same paragraph that introduced them,
and offered `@N` as a second spelling for one concept. Both are gone — one separator, one
suffix, bounded serial charset (refute-fold). A bare-VID form —
`^(0x)?[0-9a-fA-F]{1,4}$` — which CANNOT enumerate through `find_all`
(`[(vid, None)]` returns `[]`, §2.1's fault 1), so a bare-VID selector resolves
through the executor's pyusb vendor scan, the same scan auto-discovery uses
(fold-wave item 3: a documented selector form that always refuses is worse than
none). Serials are carried VERBATIM, numeric included, and the fallback reuses the
SAME parsed serial the URL form used — a serial the URL's resolution refused can
never be silently dropped to let the fallback open that device anyway (fold-wave
item 6, lane 1's round-trip case). One pure parser
(`_parse_ftdi_selector → FtdiSelector`, frozen dataclass) owns the grammar, and an
unparseable selector refuses `live_provider_selector_malformed:` naming the input
and the expected forms (fold-wave item 7d — the wrong-cause sin §2.1 forbids, never
`device_unavailable`); the CLI `--device` help and the guide document BOTH forms,
the 1-based interface numbering, and the hex-only number base (below).

**The resolution ladder** (replaces `open_ftdi`'s single `open_from_url`):
```
1. backend seam  _backend() -> (Ftdi, UsbTools)   # the ONE import site, test-injectable
2. selector      _parse_ftdi_selector(url)        # typed refusal on unparseable input
3. URL form:     try ftdi.open_from_url(url)      # incumbent, one attempt
                 except -> record exception class, fall to 4
4. enumerated fallback (VID/PID form, or a RESOLUTION-CLASS URL failure —
   the URL attempt's failure class is inspected: the fallback runs for the
   table-gate's signatures (no-device-matches / no-such-device /
   serial-not-found), and NEVER for busy, permission or claim failures, which
   refuse immediately under the incumbent prefix — retrying a USB claim on a
   busy device is the retry the one-attempt law forbids, amended honestly here
   rather than smuggled through a broad `except` [fold-wave item 7b]. **The gate
   matches on exception TYPE, never message text** (refute-fold): `UsbToolsError`
   is the resolution-class signal and falls through to the fallback, while a
   `USBError` carrying a claim/busy/permission signature refuses at once. pyftdi
   rewords its prose between releases; a message-matched gate would go quiet
   without failing):
       found = UsbTools.find_all([(vid, pid)], nocache=True)   # table-free;
               # nocache because UsbTools.UsbDevices caches until flush_cache —
               # a long-lived host would see phantom devices after an unplug
               # and miss a re-plug [item 7a]. A bare-VID selector enumerates
               # the pyusb vendor scan instead (find_all's None-pid is broken).
       serial filter ALWAYS when the selector carries one — never dropped [item 6]
       0 matches  -> live_provider_device_unavailable: (names selector, the URL
                     attempt's exception class when there was one, and
                     "enumeration found 0 matching device(s)")
       >1, no serial -> live_provider_device_ambiguous: (names selector, count, and
                     every candidate "vid:pid:serial" — the operator picks)
       port out of 1..ifcount (or 0) -> live_provider_interface_out_of_range:
                     (names selector, port, and the device's ifcount)
       exactly 1   -> ftdi.open(vid, pid, interface=port, serial=sn); any
                     exception -> close the device first (the incumbent's
                     close-on-failure, ftdi.py:260-261, reinstated [item 7c] —
                     pyftdi sets `_usb_dev` before the claim can fail, so
                     without the close step 4 can leak a half-open claim) then
                     refuse live_provider_device_unavailable: (selector + class)
5. return _PyftiDriver(ftdi)                      # unchanged
```

**Exception types, per prefix, pinned at the seam boundary** (fold-wave item 5):
`live_provider_device_ambiguous:` and
`live_provider_interface_out_of_range:` raise **`RuntimeError`** — the incumbent
`live_provider_device_unavailable:`'s own deliberate posture (`ftdi.py:252-253`),
because inside `PluginSession.connect`'s factory call a `RuntimeError` passes
through unwrapped and maps `not_ready` with the message verbatim, while any other
type arrives as `standalone_plugin_connect: ValueError:` with the prefix buried
in the wrapper. `live_provider_selector_malformed:` likewise `RuntimeError`
(connect-time). The `profile_contract_*` family raises **`ValueError`** at
CONSTRUCTION and at reload — the `verify_ftdi_plugin` precedent the CLI catches
for exit 2 — and at reload it fires BEFORE the session swap (§3.1), so it can
never escape as an untyped mid-request 500. A boundary arm pins the type of
every prefix where the seam meets it.
Still ONE bounded open attempt on the resolved device, zero retries of a failed OPEN
(A06); selector RESOLUTION may enumerate once. The B6 pin's "no scan" docstring wording
amends with this record (the prefix assertion keeps holding; on a device-less machine the
ladder answers `device_unavailable` naming "enumeration found 0 matching device(s)" —
strictly more diagnostic than the bare exception class). The F6 faulted-driver latch and
the busy guard are untouched.

**`add_custom_product` — evaluated and CONTAINED, not preferred.** It is the native
remedy for the URL path (`ftdi.py:424-442`, its own docstring: "required for opening
FTDI device with non-standard VID/PID USB identifiers"). Rejected as the primary
mechanism because: it mutates `Ftdi.PRODUCT_IDS` as CLASS-LEVEL process-global state (a
fresh `Ftdi` sees a prior registration); it is not thread-safe (check-then-insert with
no lock, while `enumerate_candidates` iterates the table outside any lock — a concurrent
registration can crash an UNRELATED URL parse with dict-changed-during-iteration);
re-registering the same PID raises `ValueError` (the reconnect trap); and no public API
removes it. The `find_all` + direct-`open` ladder mutates nothing. `add_custom_product`
survives in exactly one contained role: the URL-form passthrough registers the SELECTOR'S
OWN parsed pair immediately before `open_from_url`, once per resolve, guarded by a
membership check first (idempotent; the reconnect trap defused), and the registration is
disclosed in the refusal text when the URL attempt still fails.

**But rev 6's containment claim was too narrow, and refute measured why.** "No
registration ever happens for a device the operator did not name" is true and irrelevant:
the leak is the EFFECT, not the act. `add_custom_product` inserts into
`Ftdi.PRODUCT_IDS[vid]` — class-level, process-global, insert-only — and pyftdi **0.57.2
has no `del_custom_product`** (verified against the installed wheel; `add_custom_product`
is the only member that touches the table). So after ONE resolve, `Ftdi.list_devices(
"ftdi:///1")` — a joker URL naming nothing — returns the OEM device, and every later
enumeration in-process includes the pair in its search set: irreversible, and on a mixed
bench a previously-working joker URL starts refusing "2 USB devices match". The fold is a
save/restore around the resolve, in a `finally`:

```python
saved = OrderedDict(Ftdi.PRODUCT_IDS[vid]) if vid in Ftdi.PRODUCT_IDS else None
try:    ...register + open_from_url...
finally:
    if saved is None: Ftdi.PRODUCT_IDS.pop(vid, None)
    else:             Ftdi.PRODUCT_IDS[vid] = saved      # restore, not merge
```
**The copy is load-bearing:** the per-vid table is an `OrderedDict` mutated IN PLACE, so
`PRODUCT_IDS.get(vid)` returns the live object and a save without `OrderedDict(...)` would
restore the post-registration state and prove nothing. The arm asserts the restoration
directly — after a resolve, `Ftdi.list_devices("ftdi:///1")` must not name the pair, and a
second resolve of the same OEM device must still succeed (the restore must not cost the
feature it protects). The concurrency residual stands and is unchanged: the
check-then-insert is still unlocked, which is why this path is contained to one resolve
rather than preferred.


**Enumeration replacement** (`_pyftdi_enumerate_urls` → `_ftdi_scan_selectors`): the
family's scan set comes from the `ProviderExecutor` registry — the executor gains
`vendor_ids: tuple[int, …]` (the ftdi family registers FTDI's vendor id there, beside
`_FEATURE_PREFIX`; this is the gate's sanctioned block). Enumeration walks the vendors
via a pyusb-level `usb.core.find` (pyftdi's tables are never consulted — that is the
point), and emits OUR canonical selector `ftdi://0x%04x:0x%04x/%d` (+ `:serial`
before the interface when the device reports one). **`%d` is pinned (fold-wave
item 4): it is the 1-BASED CONTROL-INTERFACE INDEX, and the scan emits ONE
SELECTOR PER INTERFACE, `1..ifcount`** (`ifcount` = the int in each `find_all`
row, `max(bNumInterfaces)`) — so an FT2232H or FT4232H, the common multi-port
parts, lists every port as an independently pickable selector, and
`ftdi://…/1` always means the first interface, which is the control port. The
defect being replaced emitted `/ifcount` — and on a 2-port part `/2` is a real,
openable port, so the failure was never "out of range": it silently named the
WRONG port. (Rev 6 wrote that `/2` "points past the control surface", which
mis-states the mechanism; refute-proven.) Every emitted selector is openable by
BOTH ladder arms (standard PIDs via `open_from_url`, OEM PIDs via the fallback).

**Fold-wave LOW rows (item 9, one sentence each):** the selector grammar is HEX
throughout (`0x`-prefixed or bare hex; never decimal — pyftdi's own URL grammar
parses bare digits as decimal via `to_int`, and keeping the two bases disjoint is
why the docs state both); `profile_contract_*` sits one word from
`provider_contract_*` deliberately — the same pins under the same discipline,
and the kinship is the point; empty `ftdi://::` netloc components mean
unspecified exactly as pyftdi reads them, and our parser treats them identically
and says so; and seam CONSTRUCTION asserts every implemented catalogue row has
its `_op_<name>` handler method — the MCP equality assertion pins only the MCP
dict, while the seam's `getattr` (seam.py:441) would fail at call time and
escape `SeamError` — one line, one arm. Honest scope, stated — with the maintainer ruling that names the
boundary: **any device remains openable by an operator-supplied selector; only
AUTO-DISCOVERY is family-scoped.** That sentence is exact for FULLY-QUALIFIED
`vid:pid` selectors, which resolve by direct open and never consult the registry.
One clause makes it exact for the bare-VID form too (refute-fold, LOW): a bare-VID
selector resolves through the registered-vendor scan, so a bare VID naming an
unregistered vendor refuses `0 matching` — the operator must qualify it with a
`pid`. Raw pyusb-wide discovery was considered and
REJECTED: it would buy automatic visibility of unregistered vendors at the cost of
the family registry — which is the anti-laundering gate and the stronger story. A
device on a vendor no executor registers stays out of the pick flow until an operator
names it by selector; that is the family-registry model, not a per-device special
case, and the boundary sentence appears verbatim in the `--device` help text so an
operator can SEE that operation is device-generic even where discovery convenience
is family-scoped.
`FtdiDeviceHooks`, `FtdiEndpoint`, `ftdi_plugin_session`, `ScriptedFtdiDriver` keep their
signatures — the corrected default flows through discovery, binding resolution and the
pick flow unchanged (`discover_ftdi_devices`, `_confirm_ftdi_by_identify`,
`resolve_endpoint` consume the hooks).

**Diagnostics:** every refusal names the selector tried AND the enumeration result; the
wrong-cause `(no USB backend, or a busy bus)` text is gone. `open_ftdi`'s docstring
example `ftdi://::0x0403:0x6001/1` is corrected — that form parses as bus/address and
can never match.

**New refusal prefixes (STD-4 additions):** `live_provider_device_ambiguous:`,
`live_provider_interface_out_of_range:`.

**CORRECTION (fold wave, 2026-11-06, post-rev-7): the URL-form passthrough above is
amended in two places — the grammar narrows and the attempt URL is canonicalised.**
Refute lane 1 live-reproduced, twice, that pyftdi's `enumerate_candidates` runs
`to_int` on the third netloc component and treats a value ≤ 255 as a **0-based device
index**, never a serial (`:1` selects the first candidate, `:2` the second), so the URL
form could OPEN A DIFFERENT DEVICE while the colon form correctly refused; the fake's
serial-semantics model was exactly what kept the suite blind to it. Two folds:

- **Fold A (grammar + net), priority corrected by lane 1's raw probe: the parse-time
  refusal is the PRIMARY layer; the post-open verification is defence in depth.** The
  probe measured three behaviours — `:1/1` opened `candidates[0]` (wrong serial),
  `:00000000/1` opened `candidates[0]` the same way (`to_int` = 0), and `:007/1`
  (`to_int` = 7 → index 6) happened to MISS the candidate list and fell to the
  fallback, which refused correctly — so the wrong opens occur only when the index
  lands inside the candidate list, and `:007`'s "reasonable" behaviour was an accident
  of the bench's candidate count, not a property of the selector (with eight
  candidates it opens `candidates[6]`; it refuses at parse now, one step earlier than
  the old fallback refusal, same ambiguity class). Two reasons the refusal, not the
  verification, carries the property: an explicit index SKIPS pyftdi's own
  ">N USB devices match" ambiguity refusal, and on a twins bench where both units
  report the SAME serial the verification is blind — the opened device's serial equals
  the selector's because both units carry it — so the wrong unit is claimed with no
  ambiguity check anywhere in the path. Both layers shipped: a URL-form serial that is
  a bare number of value ≤ 255 is refused at the parse boundary
  (`live_provider_selector_malformed:` naming the index reading and the colon-form
  remedy, which resolves through the serial-filtering fallback); and spellings
  `to_int` still misreads past that set (a unit suffix such as `2B`) meet the net —
  after `open_from_url` succeeds with a serial-bearing selector, the ladder VERIFIES
  the opened device's serial (`Ftdi._usb_dev.serial_number`); on mismatch it closes
  the device and treats the failure as resolution-class, falling through to the
  enumerated fallback whose serial filter resolves what the selector names. The net
  arm drove the wrong-device open on a fake that now models pyftdi's index semantics —
  a green arm against the serial-semantics fake proved nothing, which is how the
  defect survived rev 7.
- **Fold D (canonical attempt URL).** The URL handed to pyftdi is BUILT from the parsed
  ints with explicit `0x%04x` spellings; the raw operator string no longer crosses the
  seam. pyftdi's `to_int` reads BARE digits as decimal, so `ftdi://123:456/1` — which
  this grammar parses as 0x123/0x456 — would have handed pyftdi decimal 123/456. A
  spelling the parser cannot reduce (named vendor, bus/address) still passes through
  unchanged.

### 2.3 PR-1 proof

Fake-`_backend` unit arms (no hardware, no pyftdi in the SDK venv) + the generality gate
+ the D3 LOW clean-up (docstring truthing, `_READ_CHUNK` review against the
largest-reply bound — changed only if the review says so, with the reason) + a LIVE
bench leg, marker-partitioned (`live_ftdi`, CI deselects; the browser/timing partition
is the precedent): scan lists the attached device as a canonical selector; connect over
the VID/PID selector opens, identify answers. The fake backend reproduces the
table-gate miniature (`open_from_url` raises for the OEM PID; `find_all`/`open`
succeed) — the issue in miniature, no hardware.

---

## 3. PR-2 — Defects 2, 8, 9(action half): the invoke operation, honouring the per-action contract

### 3.1 The operation (D2)

New catalogue row 24 `invoke` (disclosed delta beyond SW-10's closed 18 and rows 19-23,
the fork recorded here): input = the vendored runtime schema's invoke branch
(`otdp-runtime.schema.json` `$defs/operationRequest` invoke: `{action_id: string
minLength 1, input: object}`, closed) plus `device_id`; result = the CLOSED invoke envelope —
`_object({"action_id": {"type": "string", "minLength": 1}, "result": {"type":
"object"}}, ["action_id", "result"])`, the vendored `operationResult` invoke branch
made the served shape (`data` = exactly `{action_id, result}`, both required,
`additionalProperties: false`). Rev 2–4 served an open `{"type": "object"}` and
claimed "the pass-through rule governs" — that claim was FALSE (fold-wave item 2),
and it would have read the same if it were true; the envelope, the echo and the
output-schema gate below are the honest shape. REST route automatic
(`web.py` iterates the catalogue); MCP handler in `_tool_handlers` (the mcp.py:229-234
equality assertion enforces handler↔catalogue by construction); `invoke` joins
`_STATE_EVENT_OPS` with `_event_data` adding `action_id`; the `events_get` description
amends. HTML surface deliberately unchanged — the UI's control vocabulary is the
plugin-ui corpus's (STD-5; an action-button control kind starts main-side). §8 seam S3.

**The gates, mirroring the gateway's `_invoke_gate` I1–I5** (`otdp_bridge.py:719-806`)
in order, zero adapter calls: device_id guard (`not_found`) → degraded + connected
guards (`not_ready`) → **I1** capability (`unavailable` when the descriptor declares no
`invoke` operation or the pinned contract set did not resolve — the gateway's I1
message in substance, `reason: contracts_unresolved`) → **I2** declared action
(`invalid_request`, descriptor `actions` map) → **I3** catalog resolution
(`invalid_request`, "(M14)") → **I4** the pinned catalog's per-action input schema
(`invalid_request` at `json_path`) → **I5** the descriptor action's `input_constraints`
(compiled once per action, cached) → dispatch
`_execute("invoke", {action_id, input})` → **the RESULT gates, mirroring the
gateway's post-dispatch checks** (`otdp_bridge.py:1442-1480`, absent from rev 2 —
fold-wave item 2, the review's sharpest finding): the returned data must be
exactly `{action_id, result}` (closed — normative in the vendored
`operationResult` invoke branch, verified there); `action_id` must ECHO the
request's (uncorrelated refuses); `result` must pass the pinned catalog's
per-action `output_schema` — the `output_validator` rev 2 compiled into
`CompiledAction` and consumed by nothing — with the refusal naming `json_path`;
and a DATASET-SHAPED result is never laundered as a plain result: before PR-3's
admission path exists it refuses `unavailable` naming the absent admission
surface, and with PR-3 it must be admitted through that path (the gateway's
publication cross-check rides PR-3). Adapter failures keep their envelope in
`details` (SW-12). All under `_op_mutex`.

**The fork from rev 1 stands, with more evidence: the pinned profile catalog IS
available standalone** — the plugin bundles its pins (both sha256 verified against the
bytes); `verify_provider_pin` (`validation.py:749+`) and the classref vendor-catalog
walk (`classref.py:885+`) are in-tree precedent for digest-verifying `contracts[]`
pins; the vendored catalog + measurement schemas are reachable through
`contract_documents()`; `classref.py` already builds the closed `referencing` Registry;
`jsonschema`/`referencing` are core deps. New module `benchweave_sdk_server/
invoke_contracts.py` ports `resolve_otdp_contracts` (`registry/otdp_contracts.py:
271-410`): pin containment + digest (`profile_contract_missing:` /
`profile_contract_hash_mismatch:`), measurement by shape (`$id` urn + `$defs.dataset`),
catalog candidates validated against the vendored catalog schema, multi-catalog and
degenerate-dataset refusals, the closed registry, the load-time `$ref`/`$dynamicRef`
probe rooted where the runtime validators root, soft arms (absent path, half pair)
return `None` → verb-level `unavailable`. Compiled per-action validators feed I3/I4 and the RESULT gates (the load-time
probe roots include each action's OUTPUT schema, as the gateway's
`_probe_runtime_schemas` does — rev 2 probed inputs only). **Construction and
reload** (fold-wave item 8): the seam resolves at construction (CLI fail-fast,
exit 2), and `_complete_reload` resolves the INCOMING plugin's contracts BEFORE
the session swap — a hard refusal keeps the previous session loaded and answers
typed, never lane 2's F3 escape (an untyped 500 with the session already on the
new plugin and stale contracts — the exact shape that would falsify "never serve
stale schemas").
**I2+I5-only was rejected as SRF-3 weakening** — quantified: the real descriptor's
`configure_fpga.input_constraints` declares no `required` and no
`additionalProperties: false`, so `{}` and `{"ccf_path": "x", "junk": 1}` pass I5; a
catalog input schema refuses both. **No divergence — the resolver MATCHES the gateway exactly (the maintainer's
final ruling, 2026-11-06):** a pinned entry that is neither measurement-shaped nor
catalog-schema-valid refuses `profile_contract_invalid:` WHATEVER its URN. The
gateway's `resolve_otdp_contracts` has no URN carve-out and no skip path — its
single fork is measurement-by-shape, else catalog-validate, else
`ActivationRejected`, and its own docstring states the hard arm "is NOT gated on
the invoke capability: resolution runs for every descriptor that pins contracts".
The evidence that makes the hard arm safe HERE — the SEAM census, which is what
actually decides it: (a) no classref test constructs a host seam
(`StandaloneSeam`/`build_app`/`_build_seam` never appear in the classref modules;
seam construction is confined to `tests/server/`); (b) of the 45
`descriptor.contracts[]` entries under `tests/` (the team-lead's census; this
session spot-checked the first such fixture against the vendored catalog schema —
5 errors, corroborated), every CATALOG-INVALID non-OTDP row sits under
`tests/fixtures/classref/` — check-lane fixtures only — and the remaining entries
are measurement-by-shape or PATH-ABSENT (the soft unresolved arm, never a hard
refusal). So the hard arm refuses exactly the descriptors the gateway refuses and
breaks nothing in this suite. Lane 2's finding names the property neither of us
articulated, and it is why the skip can never return in any form: **the pin's
`id` is plugin-chosen**, so any skip keyed on the URN is a gate the plugin itself
operates — a descriptor pinning `{id: "https://vendor.example/x", path:
<catalog-invalid doc>}` beside a valid OTDP catalog and a measurement would LOAD
on a skipping host and SERVE `invoke`, while the gateway raises
`ActivationRejected` at load. That is a bypass of a gate, not an accommodation of
a fixture. The earlier convenience argument ("a blanket hard arm
would refuse every class-carrying plugin") was the census's right evidence used
for the wrong conclusion — those fixtures never reach a host. **The PARITY GUARD
is a test arm, not prose:** an `invoke_contracts` arm pins a catalog-invalid
document under a NON-OTDP URN through a real seam and asserts BOTH the typed
`profile_contract_invalid:` construction refusal AND that the document was never
compiled into any action registry (the never-compiled assertion, folded here from
the skip's guard) — the arm that reddens if anyone ever re-opens a skip path. The distinction still worth keeping for the next
reader: a vendor document under its own namespace is legitimately not a catalog
(where it may pin is a corpus question — R2); a profile document pinned where a
catalog is expected is a plugin defect — the real plugin's case, whose fix is the
reshape pairing row below, not an accommodation here.

**Blocking finding, plugin-side, NOT an SDK dependency — sharpened (the diagnosis,
measured: 21 schema errors):** the plugin pinned a PROFILE-SHAPED document where the
corpus requires a CATALOG. Its `logicport-profile.json` carries
`profile_id`/`title`/`description` and lacks the required `catalog_version` and
`profiles` array; its action rows carry `description`/`input_schema`/`output_summary`/
`side_effect` where the catalog schema requires `description`/`input_schema`/
`output_schema`/`lifecycle`/`side_effect` (the vendored corpus catalog itself is the
witness of the right shape: `catalog_version` + 12 `profiles` + 51 `actions`, every
action carrying the five required fields). The gateway declares
`CATALOG_SCHEMA_NAME = "device-profile-catalog.schema.json"` and validates every
non-measurement pin against it, so "the gateway would refuse this bundle at load"
follows from the shape mismatch, not merely from missing fields. Both sha256 pins
match the bytes, so these are the pinned bytes lying, not drift. invoke will refuse
`profile_contract_invalid:` naming the first finding until the plugin reshapes the
document. The plugin reshapes exactly ONE document — its measurement entry is exempt
by shape (`$id` urn + `$defs.dataset`), so the pairing row is a single item, not two. The plugin session is read-only and plans no changes, so this lands as: the
typed refusal is CORRECT on both hosts; the plugin-repo fix is a named pairing row and
MUST NOT become an SDK prerequisite. The same comment's plugin arithmetic corrections
(the "~1.4 s" upload figure, `CONFIG_BAUD` never transmitted) are plugin-repo rows,
explicitly NOT dependencies of any SDK PR.

### 3.2 The per-action contract, honoured generically (D8 + D9)

The descriptor's `actions` rows declare `timeout_ms`, `side_effect`,
`cancellable`, `retry` — the host reads none today (grep: zero occurrences).
Lane 2 killed the "unread contract" framing as a DEFECT: the gateway consumes
none of the four either (only I2's membership reads the actions map), so ignoring
them is parity, not weakening. The maintainer's REVISED ruling (fold-wave item
10): PR-2 honours **`timeout_ms`** (D8's only mitigation depends on it) and
**`retry: "never"` → `status: "unknown"` surfaced verbatim, never re-issued** (a
safety property), STATES `side_effect` and `cancellable` on the invoke event row
without inventing behaviour for them, and discloses in the guide and the PR body
that **the SDK is deliberately STRICTER than the gateway here** — so a reader
does not mistake strictness for divergence.

- **`timeout_ms` is the operation deadline, per action** — `HostOperationContext` for an
  invoke dispatch is minted with `actions[action_id].timeout_ms`, NOT
  `verb_timeout_ms("invoke")`. The wrong-keyed lookup cannot happen by construction
  (the action deadline is read from the action row; the verb budget is only consulted
  by the load-time check below). An overrun is the context's own expiry: the adapter's
  deadline path answers `TIMEOUT` → the seam maps `not_ready`; a retry the adapter
  cannot finish inside its deadline truncates visibly — the operator sees the timeout,
  never a silent overrun.
- **Load-time cross-field feasibility check (the widened D8) — MITIGATED, NOT
  PREVENTED, and the record says which is which.** The check that is possible and
  generic: for every declared action, `actions[a].timeout_ms` must be ≤ the serving
  verb's budget (`operations.invoke.timeout_ms`), refused at serve construction with
  `standalone_action_budget_infeasible:` naming the action, its timeout and the
  governing budget. **Run the reported case through it: the check does NOT close
  that case.** The plugin's `configure_fpga` declares `timeout_ms: 60000`; `invoke`
  declares 60000; `60000 <= 60000` passes. The infeasibility is `attempts` up to 20
  at ~22.96 s per upload (three attempts ≈ 69 s), and the cost per attempt is
  NOWHERE in the descriptor — no SDK-side check can see it without that data, stated
  plainly. What actually mitigates D8 is the honoured action deadline (the bullet
  above): a multi-attempt configure is truncated at its own 60 s with a typed TIMEOUT
  surfaced to the caller — the harm changes from a silent overrun into a visible
  failure. Worked example for the record: the real plugin's `configure_fpga` PASSES
  the construction check and still cannot complete three attempts — an honest
  demonstration that the check is a bound-coherence guard, not a completion
  guarantee. The cost-model residual is routed to the CORPUS issue stream as a named
  seam (S3): the descriptor could carry a per-attempt bound, or the corpus could
  constrain a retry-count parameter against a declared duration class — a normative
  change that belongs main-side under STD-5, not here. The plugin's `attempts` range
  is NOT narrowed — per-instrument workarounds are exactly what the red team
  retracted.
- **`side_effect` / `cancellable` — STATED, not re-interpreted** (the revised
  ruling drops rev 2's invented behaviour): both ride the invoke event row so a
  watcher sees which actions mutate and which cannot be torn down; the host adds
  no semantics of its own (the gateway adds none either — parity).
- **`retry: "never"` → `status: "unknown"` surfaced verbatim, never re-issued** —
  the one safety property kept; PR-2 implements no re-issue for any value, so
  the refusal to retry is the honest reading of both.

### 3.3 D9's identify honesty row

`_IDENTITY_RESULT` (`catalogue.py:164-178`) requires `serial` and `firmware` as
STRINGS; the plugin's identify answers `None` for both (firmware policy "commissioned").
Establishment (`PluginSession.connect`) validates the identify receipt against the
catalogue's own result schema and refuses `not_ready` naming the field — the receipt is
a contract (the #567 read-receipt precedent), and a `None` serial rendering as a
missing key on the wire is worse than a typed refusal at connect. (Plugins with nothing
to report answer empty strings; the guide row says so.)

### 3.4 D8's reset row

The `reset` verb is unreachable today (no operation dispatches it; mitigated in this
plugin because its init action runs its own init sequence). PR-2 adds catalogue row 25
`device_reset` — a thin handler dispatching verb `reset` under the DECLARED
`operations.reset` policy (`verb_timeout_ms("reset")` already reads it), same surfaces,
same event family. Generic: no device knowledge, only the descriptor's declaration.

---

## 4. PR-3 — Defects 4, 6, 7: the dataset admission path

**The one decision the red team named, and the PRINCIPAL HAS NOW RULED IT:
HOST-ADMISSION IS THE STANDARD.** Verified on #589, comment
`2026-11-06T12:24:22Z` ("Ruling: the host admits. The adapter does not publish."): a
plugin returns a dataset-shaped result, the host admits it, and a plugin does not call a
publish surface. The ruled reasoning, which this record adopts rather than paraphrases
loosely: storage policy is host policy, so a publish hop inside the adapter creates a
second authority that will drift from the host's; the gateway's current requirement is a
trap because it is enforced only at dispatch, after accepting a descriptor that promised
host-admission; and the dataset is already typed by the measurement schema, so a second
explicit publish is ceremony that can disagree with the payload it accompanies. The
plugin side does not change — `adapter.py:1216-1217`'s host-admission promise
**stands as written and is now the standard's rule**, not one plugin's preference.

**The ruling's condition, taken as an acceptance obligation.** "The host admits" without
a defined admission surface is exactly how D4 happened — the defect is not that the host
forgot to admit, it is that no surface exists to call. PR-3 therefore DEFINES admission,
four answers that the PR body must state and an arm must pin:
(a) **where the bytes land** — the capture-root family path and its row shape;
(b) **who may read them afterwards** — the authorisation check on the read path;
(c) **what `dataset_id` is minted over** — `"ds:" + operation_id`, per item 1 below;
(d) **what the host does when admission fails** — the typed refusal, and the guarantee
that no partial artifact becomes a successful dataset.

**The divergence is DISCLOSED, per the ruling, in three places — this is the standard's
requirement, not a local preference:** loud in this design record (§4, here); visible in
`host_info` (a named field stating that the standalone host admits on result while the
gateway still requires `dataset_publish`); and named in the refusal text when a
dataset-shaped result meets the old expectation. A disclosed divergence is a known gap;
an accidental one is the trap the ruling removes.

**This makes the data path INVOKE → dataset for every invoke-capable plugin,
device-generically.** The result path is PRIMARY and `dataset_publish` is never required:
the explicit surface stays in the protocol (declared, and used by upload actions to
inspect a dataset before reading payloads), but an adapter that only returns a
dataset-shaped result is conformant. Rev 6's framing — "the host admits inline snapshots
as datasets" — reached the right mechanism from the red team's evidence; the ruling
settles the authority question that framing could not, and removes the publish
requirement rather than copying it.

Mechanism (`benchweave_sdk_server/dataset_admission.py` + seam/session wiring):

1. **Mint (D4's core):** every invoke dispatch mints `context.dataset_id =
   "ds:" + operation_id` — the gateway's gate-I6 mint shape (`dataset_services.py:167`).
   The adapter's fetch action can build its manifest against a real id. A non-invoke
   verb's context keeps `dataset_id = None`, and an adapter that reaches for dataset
   services on a None id gets the typed refusal (`standalone_dataset_context_absent:`)
   — never a silent no-op.
2. **Admission, both shapes:**
   - INLINE: a successful invoke result that is dataset-shaped (carries the pinned
     measurement schema's `$defs/dataset` required keys — the `is_dataset_shaped`
     detector, `dataset_services.py:262`) is validated against the pinned measurement
     schema (compiled in PR-2's resolution — the dataset half of `InvokeContracts`
     finally consumed), cross-checked (channel ids against the descriptor's `channels`
     — D9's channels row; echo fields against the invoke input per M10's correlation
     subset), and PERSISTED under the capture-root family as a first-class data row.
   - EXPLICIT: the same validation path exposed as `dataset_publish` /
     `dataset_lookup` service members (the DatasetServices protocol's twelve-member
     shape is the contract; PR-3 implements the two base members inline over the
     capture root — the honest-no-implementation docstring and its pin flip, per that
     test's own instruction).
3. **Exposure:** admitted datasets appear in `capture_list` (a `dataset` surface row),
   serve `capture_series` and `report_export` through the SAME display path PR-4 fixes
   (one path, no second renderer), and pin like captures.
4. **D6's repair — the lying fallback is REMOVED:** `_resolve_capture_verb`'s
   `invoke` fallback (`seam.py:1758-1772`) passes capture arguments verbatim to a verb
   whose adapter contract is `{action_id, input}` — it can never work, and there is no
   declarative source for the action id. `capture_start` on a plugin with no `capture`
   verb now refuses `unavailable` with the honest direction ("this plugin serves data
   through its actions; invoke them" — the dataset path is the data route). A
   capture-over-class-actions composition (arm/fetch driven by the pinned catalog's
   profile declarations) is a real future path and is named as seam S2 — not built
   here, because the gateway's own class-capture composition is the reference surface
   and PR-3's dataset path already closes "no path to admit data".
5. **D7 under the dataset model:** "no capture verb" is the plugin's honest declaration
   (data via actions); artifact append/finalise members belong to streaming-capture
   plugins (unchanged); the inline snapshot IS admitted (row 2); `capture_stop` has no
   in-flight capture to stop for an invoke-only plugin — the device's own stop action
   is an invoke the operator issues, and PR-2's `cancellable` rule governs teardown.

---

## 5. PR-4 — Defect 5: the format path serves what the schema admits

**Decision (adopted, with the reason): the display path serves EVERY format the schema
admits — `raw_binary` renders.** The alternative (drop `raw_binary` from `_FORMATS`)
was rejected: `raw_binary` is the DEFAULT at `catalogue.py:304`, `mcp.py:99` and
`seam.py:1878`, so the schema cannot drop it without breaking the default path — the
host's default cannot be the unsupported one; and dropping it removes logic, bus and
counter devices from the capture surface wholesale. This is the red team's
recommendation and the team-lead's read, adopted with the default-path evidence that
makes it stronger than filed.

What `raw_binary` rendering IS, exactly (so the refusal moves to genuinely unrenderable
input only):

- `capture_series`: x = sample INDEX (0-based integer), y = byte value (0-255);
  `sample_interval_s`/`unit` have no renderable meaning for a byte stream and are NOT
  fabricated — the series row carries the honest index axis. Decimation unchanged
  (min/max per column over the byte values).
- `analysis.py` / `report_export`: the same index-space series; markers and
  assertions operate in index space (their `t` validated against the index grid
  exactly as they validate against the time grid today); the report's caption carries
  the format and the axis meaning, per the SRF-4 denominators discipline.
- `capture_stop`-side manifest fields already handle both formats
  (`_BYTES_PER_SAMPLE`, `_PRIMARY_SUFFIXES`, finalise's format branch) — untouched.
- The refusals that REMAIN: an UNKNOWN format (not in `_FORMATS`) refuses as today;
  a format the schema admits but no renderer serves cannot exist again — see A7.

**A7 as a gate, not a hope:** a test iterates `catalogue._FORMATS`' enum and, for EVERY
admitted format, drives series + analysis + report over a fixture capture of that
format — a format nothing renders reddens at admission time. The `_FORMATS` enum and
the renderer registry become single-source-linked (the renderer registry keyed by
format; the test asserts key-set equality both ways).

---

## 6. PR-5 — Defect 9 residual: descriptor literacy

Smallest PR, lands last: `required_features` verified at load against the vendored
served set / banked features (a plugin requiring a feature this SDK does not bank
refuses at serve construction — the load-time disclosure the field exists for);
`profiles` cross-checked against the pinned catalog's profile ids (a declared profile
that resolves nowhere is a load refusal); `read_policy.side_effect` honoured in the
read path (an escalated read records the escalation on the event bus beside the read —
the conservative over-classification stays the descriptor's business, the HOST's
business is not to be silent about it). Channels' cross-check rides PR-3's dataset
validation (M01's standalone analogue).

---

## 7. The PR stack (one issue #589, several dependent PRs, merged bottom-up)

| PR | Carries | Depends on | Notes |
|---|---|---|---|
| **PR-1** | D1 (selector + enumeration + diagnostics), the generality gate, D3's withdrawal record + LOW docstring/`_READ_CHUNK` row | — | Branch `fix/589-live-bringup-generic` exists; lands first (the gate must exist before the code it guards) |
| **PR-2** | D2 (invoke + I1–I5 + contracts resolution), D8 (action deadline + feasibility check + `device_reset`), D9's action contract + identify honesty | PR-1 (branch base; no code dependency) | The `profile_contract_invalid:` refusal is correct EVEN THOUGH the real plugin's catalog is presently invalid — that is the gate working on both hosts. PR-2's body must NOT describe `invoke` as unblocking bring-up (fold-wave item 11): `context.dataset_id` stays `None` until PR-3, and the plugin's failing action is its CLASS FETCH (`INVALID_ARGUMENT` without `context.dataset_id`) — its inline read action completes. The data path closes in PR-3, and the PR body says so plainly |
| **PR-3** | D4 (mint + admission + exposure), D6 (fallback removed + honest refusal), D7 (dataset model rows) | PR-2 (the contracts resolution compiles the measurement schema) | Closes the red team's headline: "the host has no path to admit data" |
| **PR-4** | D5 (raw_binary display path + A7 format-exhaustion gate) | PR-3 (datasets serve through the same path) | The self-contradiction (default format refused by display) dies here |
| **PR-5** | D9 residual (required_features, profiles, read_policy.side_effect) | PR-2 | Smallest; could ride PR-2 if review prefers fewer PRs — named separately so the row cannot be dropped silently |

Every filed defect is carried or withdrawn-with-evidence above; none is dropped. The
plugin-repo rows (pinned catalog validity, arithmetic corrections) are named pairing
rows and are NOT prerequisites of any SDK PR. TWO-1 unchanged per PR: pushed here
first, pointer commit after; PR bodies name gateway issue #589.

**Invariant impact across the stack:** STD-1/2/3/5/6 untouched (no vendored motion;
`sync-standards --check` green throughout). STD-4 grows:
`live_provider_device_ambiguous:`, `live_provider_interface_out_of_range:`,
`live_provider_selector_malformed:`,
`profile_contract_missing:`, `profile_contract_hash_mismatch:`,
`profile_contract_invalid:`, `standalone_action_budget_infeasible:`,
`standalone_dataset_context_absent:` — **every refusal a prefixed `ValueError` at
construction/reload and a prefixed `RuntimeError` at the connect boundary, per §2.2's
per-prefix pins** (`live_provider_device_ambiguous:`,
`live_provider_interface_out_of_range:` and `live_provider_selector_malformed:` are the
three `RuntimeError` members; the `profile_contract_*` family is `ValueError` at
construction and reload); every refusal fires before any write; no existing prefix
weakens. Rev 6's blanket "every refusal a prefixed `ValueError`" contradicted §2.2 one
section earlier (refute-fold) and mattered because the docs leg transcribes this
paragraph into `invariants.md`'s STD-4 entry — as written it would have documented the
wrong type for all three connect-time prefixes and taught an implementer to bury them. PKG untouched (no new deps). SRF: new draft row
(§ rev 1's SRF-6) "the standalone invoke gates agree with the gateway's I1–I5…" now
EXTENDED: "…and the per-action contract (timeout/side_effect/cancellable/retry) is
honoured from the descriptor, never assumed"; a second draft row for A7 ("a format the
schema admits is a format the display serves — pinned by exhaustion test").
`test_catalogue.py`'s closed-list pin amends twice (rows 24, 25); the vendored-set
intersection pin keeps holding (neither name is in the gateway REST catalog).
drift-and-obligations: obligation 1 moves each PR (CLI/guide/README, STE100 via
`document-writer`); README:249's two stale sentences (contradicting cli.py:247-264)
correct in PR-1's docs leg; a new obligation names the
catalogue↔handlers↔host_info↔events-description quintet for any future operation; the
generality gate gets its own obligation row. The scaffold and agent assets are
untouched (R-5b triangulation is cited→exists; additions stay green).

**Archetype fixtures (the generality proof's numerator — distinct device shapes the
suite exercises, ≥3):**
1. `scope-shaped` archetype on `waveform_f64le` — the CONTROL arm (the served path;
   modelled on `class-daq`/`class-oscilloscope`, invented name).
2. `bit-plane` archetype on `raw_binary` — the FAILING path that PR-4 fixes; the A6/A7
   proof; modelled on the logic-analyser byte plane (invented name).
3. `counter/dmm` archetype — invoke-heavy, scalar, non-waveform; exercises D6's
   argument shape and D9's channel mux; modelled on `class-dmm` (cheap: a third
   descriptor + small adapter over the same fixture machinery — added because D6/D9
   coverage otherwise rests on one archetype).
Plus the LIVE bench leg (marker `live_ftdi`): the attached device, scan → canonical
selector → connect over VID/PID → identify. The real plugin remains the live
integration witness for PR-2/3 (its catalog refusal is itself a live arm of the typed
refusal).

**Acceptance (pre-committed; numbers before any new test ran):**

- Per-PR mutation matrix (each mutation reddens its NAMED arms, both runs pasted):
  PR-1: M1 revert the fallback → OEM-ladder + VID/PID arms; M2 restore the old
  enumeration → enumeration arms; M3 drop the interface range check → the `/0` and
  out-of-range arms. PR-2: M4 skip I4 → I4 arm; M5 skip I5 → I5 arm; M6 hard-refusal →
  silent-None (the SRF-3 weakening) → construction arm; M7 ignore action timeout_ms
  (use verb budget) → the deadline arm; M8 drop the feasibility check → the load-arm.
  PR-3: M9 skip dataset minting → the mint arm; M10 admit without schema validation →
  the validation arm. PR-4: M11 restore the waveform-only gate → the raw_binary arms;
  M12 render raw_binary with a fabricated time axis → the honest-index-axis arm.
  Fold wave (rev 6): M13 skip the result gates → the envelope/echo/output-schema
  arms; M14 re-open a URN-keyed skip → the parity arm; M15 drop the serial from
  the fallback's filter → the round-trip arm; M16 drop the pre-swap reload
  resolution → the reload arm.
- The fold-wave arms join the pre-committed counts BEFORE any of them is written:
  12 arms — result envelope + echo + output-schema (3); type-at-the-boundary per
  prefix (1); numeric-serial round-trip (1); bare-VID-via-scan (1); nocache
  re-scan after a device-set change (1); malformed selector (1);
  construction-time `_op_<name>` pin (1); reload pre-swap (1); resolution-class
  gating — a busy-device failure must NOT reach the fallback (1); close-on-failure
  — no half-open claim after a failed open (1).
- A6 (the red team's criterion): the bit-plane archetype completes capture → dataset
  admission → storage → series → report export, all green — the arm EXISTS and names
  its class (logic-analyser byte-plane archetype; the counter archetype repeats the
  path for a scalar class).
- A7: the format-exhaustion gate (§5) — every `_FORMATS` enum member served by
  series+analysis+report in the suite.
- The generality gate's printed denominator: `files_scanned`, `literals_examined`,
  `allowlisted_entries` — asserted non-zero, allowlist length pinned.
- Live legs (`live_ftdi`, operator-run, CI-deselected): PR-1's scan/connect/identify;
  the suite never requires hardware to go green.
- Gates per PR: ruff; strict mypy (`files = ["src"]`); FULL `pytest -q` with the
  collected count read from the raw run; `sync-standards --check`; `--version` smoke.
- Kill directions: any mutation leaving its named arms green kills that PR's claim
  (fix the fake/mechanism, do not weaken the arm); the OEM arm green under M1 means
  the fake backend is not simulating the table gate — a measurement bug, not a code
  pass; a mutation reddening >3 arms outside its named set means coupled fixtures —
  re-slice before trusting any green; A6 failing on the bit-plane archetype while the
  scope archetype passes means PR-4's path is still waveform-shaped — do not merge.

---

## 8. Seams where a further defect attaches (the red team is still running)

- **S1 — the selector ladder** (`open_ftdi` + `_ftdi_scan_selectors`): any new
  transport-level defect (power management, suspend/resume, hot-plug staleness)
  attaches at the ladder or the executor registry without touching the invoke path.
- **S2 — capture-over-class-actions composition**: the deliberately-unbuilt streaming
  path (arm/fetch driven by the pinned catalog's profile declarations). A defect about
  long-running streaming capture attaches here as a new PR between PR-3 and PR-4.
- **S3 — the invoke handler's single switch points**: binding kinds (if the corpus
  admits a non-adapter kind) switch at dispatch; new per-action contract fields
  (if the corpus adds them) switch at the contract-honouring block in PR-2.
- **S4 — dataset admission**: new admission rules (payload streaming via the artifact
  members, quota) extend `dataset_admission.py` beside the inline path without
  touching the seam.
- **S5 — the renderer registry** (PR-4): a new capture format attaches as a renderer
  entry; A7's exhaustion test is the gate that forces it to serve.

A new defect therefore lands as: one ledger row here (status/evidence/PR), one arm in
the named PR, zero redesign of the stack.

## 9. Top risks, each with its falsifier

- **R1 — the fake backend drifts from pyftdi's real behavior** (the miniature lies).
  Falsifier: the live legs + CI's real-pyftdi B6 arm; a divergence is a test bug
  (M1's kill direction), never absorbed silently.
- **R2 — the classref↔loader contracts[] tension, and the parity guard.** The
  census (45 entries under `tests/`; 9 catalog-invalid non-OTDP, every one under
  `tests/fixtures/classref/`) was, in this record's own rev 2 and rev 4, the right
  evidence used for the wrong conclusion: those fixtures never construct a host
  seam, so matching the gateway's hard arm breaks nothing, and parity — what the
  SDK accepts is what the gateway accepts — is the stronger invariant. What the
  census EXPOSES is real and owned elsewhere: the classref check lane reads
  vendor-catalog, member-declaration and composed-class pins from `contracts[]`
  while the gateway's loader hard-refuses them, so a plugin author can be green on
  `check-ui` and dead at gateway load. Owner: a main-side corpus ruling — either
  vendor pinning moves out of `contracts[]`, or the loader carves it; STD-5
  territory, not an SDK decision. Guard: the parity test arm (§3.1 — a
  catalog-invalid non-OTDP pin through a seam refuses typed) reddens if a skip
  path ever returns; a review showing invoke serving from a skipped pin would be
  an SRF-3 breach — revert immediately.
- **R3 — the feasibility check's residual** (no cost model): an action whose declared
  timeout is unreachable via its parameter maxima still loads. Named in §3.2; the
  falsifier of the CHECK itself is M8; the residual is refuted only by a corpus cost
  model (a main-side motion, seam S3).
- **R4 — `add_custom_product` containment leaks, scope WIDENED by refute** (a
  registration observed for a device the operator did not name, a re-register
  `ValueError` on reconnect, **or the measured EFFECT: a persisted class-level entry that
  a later joker-URL enumeration sees**). Rev 6's scope covered only the act, and the leak
  is the effect — refute proved a single resolve makes `Ftdi.list_devices("ftdi:///1")`
  return the OEM pair, and pyftdi 0.57.2 ships no `del_custom_product`, so nothing
  removes it. The save/restore `finally` in §2.2 is the mitigation; the arm asserts
  restoration directly (joker-URL enumeration clean after resolve) AND that a second
  resolve still works, so the fix cannot be satisfied by breaking the feature. The
  unlocked check-then-insert is the standing residual, contained to one resolve.
- **R5 — the dataset path grows a second renderer** (series/report diverge between
  captures and datasets). Structural: PR-4's path is the ONLY renderer (S5), and A7's
  exhaustion test walks both source kinds; divergence reddens A7.
- **R6 — reload races** (invoke on the OLD catalog dispatching post-swap). `_op_mutex`
  serialization + the reload re-resolution are pinned; a reproduction falsifies the
  serialization claim.

## 10. Memory ledger

Proposed at session close via `node .claude/hooks/memory-propose.mjs` (source
`increment-designer`): (a) pyftdi 0.57.2's URL machinery is table-gated — OEM PIDs are
URL-inadmissible while `find_all`/`open(vid,pid,if)` work; (b) the enumeration
return-shape misuse and its venv-invisibility lesson (default-path code behind an
injection seam is untested by construction — prove it with a fake-backend seam);
(c) D3's withdrawal with its measurement (the fast-exit read path), so nobody re-files
it from the class table's inherited premise.

---

## Appendix (2026-11-07, PR-2 build): §3.1 census claim (a) is FALSE at the call level

**Correction by append, rev 7's frozen text unchanged above.** The seam census that
made the hard arm look free — "(a) no classref test constructs a host seam
(`StandaloneSeam`/`build_app`/`_build_seam` never appear in the classref modules; seam
construction is confined to `tests/server/`)" — is lexically true and call-level
FALSE: `verify_ui` → `benchweave_sdk.classref_gate_render.render_pages`
(`classref_gate_render.py:41`) constructs a real `StandaloneSeam` over the project and
drives its pages over in-process ASGI. The gate's own render half is a host.

**Measured cost, full classification (the PR-2 build lane, every failure read):** 71
main-lane failures + 9 loop-lane errors, ALL ONE CLASS (bucket (a) — the intended
typed refusal; zero PR-2 defects, zero pre-existing), split by pin: 49
`urn:veridian:vendor-catalog:1.0.0` (incl. 2 CLI-subprocess arms), 22
`urn:meridian:composed-burst:1.0.0` (incl. 8 loop-lane verify-ui arms), 3
`urn:meridian:member-declaration-smu:1.0.0`, 2
`urn:veridian:vendor-catalog-pair:1.0.0`, and one each of
`veridian:vendor-catalog-trio`, `veridian:refless-composed` and
`veridian:member-declaration`. The census's "breaks nothing in this suite" was wrong by
80 arms across 13 modules (`test_classref_acceptance/cli/composed/gate/
member_channels/member_datasets/member_join_ceiling/member_ledger/render_arms/residual/
trio/vendor_scale` + `test_standalone_dev_loop`).

**What this changes and does not change.** The RULING stands — the resolver matches the
gateway (its own loader refuses these pins at activation, `otdp_contracts.py:15,34`),
so the fixtures' "shippable" claims were false on both hosts and parity IMPROVED. What
the census understated is the cost: the vendor-catalog / composed-class /
member-declaration feature is now refused at verify-ui and at serve on both hosts
until the R2 corpus motion lands (vendor pinning moves out of `contracts[]`, main-side
— a named carrier with a named blocker, recorded in the PR body beside GW-1).

**The maintainer question, raised not decided:** `render_pages`' own comment says a
degraded load "refuses honestly and the pages render their disclosures alone — exactly
the unconnected face". A defensible alternative shape exists — a contract-invalid
plugin renders its disclosure pages and the gate REPORTS the refusal rather than
erroring — which would keep verify-ui useful for inspecting a broken plugin. Falsifier:
if the maintainer rules the render half must agree with activation (SRF-2 read
strictly), the current behavior is right and the fixtures invert; if the maintainer
rules verify-ui an inspection surface, the render half needs the degraded-load
treatment. NOT taken by the PR-2 build (it changes verify-ui's semantics; not a
builder call).

**Disposition executed:** the team-lead ruled option (1) — invert the bucket-(a)
fixtures to assert the typed refusal, own commit, no deletion. `test_classref_vendor_scale.py`
inverted as the pattern commit (renamed to its honest name, derivation half kept, gate
half asserting `profile_contract_invalid:` naming the pin); the remaining 12 modules
carry the same mechanical pattern with the per-module pin map above.
