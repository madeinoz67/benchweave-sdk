# Gateway issue #392 — alias port spellings still re-probe the connected port (design)

Verdict up front: **BUILD** — a one-predicate fix at two call sites in
`serial.py`, with the trust-2 branch byte-untouched. This record is the
pre-committed acceptance rule; it is the first commit on the branch so
pre-commitment is provable from the git log.

Code verified at `origin/main` tip `b457873` (the brief cited `1d26497`;
main has moved — the content is unchanged at the cited lines). One
correction to the brief: the trust-2 drop is not "immediately above" the
connected compare — it is the FIRST statement INSIDE that branch
(`serial.py:1639-1646`), so every alias-aware route into the skip passes
through it. That placement is why this fix is safe, and also why fixing
only the skip compare would make one input class WORSE than today (§3).

## 1. Root cause, traced to the line

The byte-equality assumption lives in **two** places, not one:

1. **The connected skip** — `src/benchweave_sdk_server/serial.py:1638`:
   `if connected_device is not None and name == connected_device:`. A
   non-byte-equal spelling falls to `_confirm_by_identify` (`serial.py:1658`
   → `serial.py:1510`), which opens the port — the #389 symptom persists.
2. **The mint-time serial lookup** — `_enumerated_serial_at`
   (`serial.py:1314-1324`, the byte-compare at `serial.py:1321`), called by
   the services factory (`serial.py:1382`). When the session's `--device`
   spelling does not byte-equal any enumerated name, the lookup returns
   `None` and `note_minted_serial(None)` records **"unit has no iSerial"
   (`last_serial=None, last_serial_known=True`) for a unit that has one**.

`connected_device` is `minted.last_resolution` (`seam.py:686-695`) — the
resolver's RAW string (`serial.py:1373-1375`: `path = resolver()` …
`resolver.last_resolution = path`), never canonicalized. So both sites
byte-compare the operator's spelling against the enumeration's spelling.

**The compound defect:** patch site 1 alone and an aliased connected path
enters the skip branch with mint serial `None`/known; if the enumerated
row carries a real serial, the trust-2 compare at `serial.py:1639-1641`
mismatches and the connected row is DROPPED as a chimera. Today that
operator at least gets a row (after the offending re-open). A one-site fix
is therefore a regression for the by-id/tty operator — the design MUST
move both sites to one shared predicate. This is the first-ranked risk
(§8).

Precedent for the fix's shape: the code comment at `cli.py:327-332` already
names this exact follow-up ("Alias spellings of the same physical port
(cu vs tty, by-id symlinks) do not match and still re-probe — the
alias-matching follow-up owns that").

## 2. The equivalence question, settled on evidence

### 2.1 What the aliases actually are (observed, not recalled)

- **macOS cu/tty pairs are distinct device nodes, not symlinks.** Observed
  on the design machine: `/dev/cu.Bluetooth-Incoming-Port` is char
  `9,3` and `/dev/tty.Bluetooth-Incoming-Port` is char `9,2` — same major
  (one driver instance), adjacent minors (the BSD dialin/callout split).
  `realpath` resolves nothing here; the two nodes are peers. The pairing
  is per driver instance: one physical (or virtual) serial device, one
  kernel driver instance, exactly two `/dev` nodes `cu.<stem>` and
  `tty.<stem>` sharing the stem.
- **pyserial on darwin enumerates ONLY the `cu.` spelling.** Observed:
  `comports()` on this machine returns three rows, all `/dev/cu.*`, while
  `/dev` carries both spellings. So the macOS arm of #392 is the operator
  whose `--device` spells `tty.*` (copied from another tool): enumeration
  yields the `cu.` peer, the compare misses, discovery opens the live
  port's sibling node.
- **Linux by-id/by-path are symlinks to the real node.** `/dev/serial/`
  does not exist on darwin (observed); on Linux, udev maintains
  `/dev/serial/by-id/<usb-…-if00-port0>` symlinks pointing at
  `/dev/ttyUSB*`/`/dev/ttyACM*`, which is what pyserial enumerates.
  `os.path.realpath` resolves this class on either side of the compare.
- **The issue's suggested mechanism (match off comports metadata) does not
  carry the weight.** Observed on this machine: non-USB-metadata rows carry
  `location: None` and `hwid: 'n/a'` — the metadata fields are optional
  per platform and per device class, so a metadata-keyed identity has no
  key for exactly the cheap-adapter population #392 is about. It also does
  not remove the name problem: the mint-time recording
  (`_enumerated_serial_at`) must find the enumeration ROW for the path the
  factory opened, and the opened spelling is a name — a metadata match
  cannot substitute for that lookup. Matching on `serial_number` alone is
  worse, not better: same-serial twins (documented in the FTDI lane's
  fold K-2) would both collapse onto the connected identity, and
  serial-LESS units would make EVERY serial-less candidate match
  `None == None`.

### 2.2 The equivalence adopted

Two rules, because the two alias classes are different KINDS of alias:

1. **Byte equality** (today's rule, kept as the first clause).
2. **Darwin stem equality**: both spellings are under `/dev/cu.` or
   `/dev/tty.` and their remainders after the prefix are byte-equal.
   Requires BOTH sides to carry a darwin prefix, so it cannot fire on
   Linux `/dev/ttyUSB0` (not under `/dev/tty.` — the literal prefix
   includes the dot) or Windows `COM3` spellings.
3. **Resolved-node equality**: `os.path.realpath(a) == os.path.realpath(b)`
   (Linux by-id/by-path, and any operator-managed symlink alias, either
   direction).

One module-private predicate in `serial.py` — name it
`_ports_name_same_node(a, b)` — evaluated at exactly the two call sites
(`serial.py:1321` and `serial.py:1638`). The name states the claim
precisely: NODE-level equivalence (is this spelling the same device node
the session opened). UNIT-level identity (is the occupant the same unit)
stays trust-2's serial reconciliation, untouched. Cost: at most two
`realpath` calls per non-byte-equal candidate per scan — bounded by
enumeration size and noise against the 1000 ms-class identify timeouts.
`os.path.realpath` never raises on missing paths (non-strict): test fakes
like `/dev/match-a` resolve to themselves and simply do not match.

## 3. Failure mode, argued honestly

**The accepted failure mode:** if a rule wrongly equates two spellings
that are in fact different units, the scan serves the connected session's
identity for that row and skips its identify — a genuinely different
device's row is silently omitted from that scan. The lead's stated
worst-case; accepted with the following bounds.

- **When the rule is wrong, trust-2 catches it whenever serials are
  known.** The wrong-unit case is precisely "the enumerated row's serial
  differs from the mint serial" — the existing drop at `serial.py:1639-1646`
  fires (a positive identity check already in the loop, not a new one).
- **Residual exposure:** serial-LESS units (no iSerial) or endpoints minted
  without an enumeration (`connected_serial_known=False`) — equivalence is
  purely name-based there and a wrong equivalence is invisible in the scan.
  This is disclosed as the accepted residual.
- **How wrong can the stem rule actually be?** It equates `cu.X` with
  `tty.X` only. For that to equate two UNITS, the kernel would have to
  register two distinct driver instances under one stem — devfs node names
  are unique per registered instance, and the dialin/callout pair is
  created BY one instance. No such shape was found on darwin; the residual
  risk is stated, not proven absent (this repository has no hardware CI,
  §6).
- **Uncertainty fails toward today's behaviour.** Every clause that does
  not positively equate falls through to `_confirm_by_identify` — the
  pre-fix path. The rules can only ADD skips for spellings the OS itself
  says name the same node (symlinks) or the same driver instance (stem
  pairs); they cannot remove a skip today's byte rule already makes.
- **Realpath over-match is not a two-device collapse.** Two paths whose
  realpaths are equal ARE the same node by the OS's own resolution — the
  "second device" would be unreachable through that spelling anyway
  (opening it opens the same node).

What the code does when uncertain: nothing new — identify, as today.

## 4. The minimal first slice

**Scope (all of it):**

1. `_ports_name_same_node(a, b)` in `serial.py` (three clauses, §2.2). No
   new imports — `os` is already imported (`serial.py:38`).
2. Site 1: `serial.py:1638` compare becomes
   `_ports_name_same_node(name, connected_device)` (guarding the
   `connected_device is not None` shape it already has).
3. Site 2: `serial.py:1321` compare inside `_enumerated_serial_at` becomes
   the same predicate.
4. Docstring amendments on `_enumerated_serial_at` and
   `discover_serial_devices` naming the alias classes (the endpoint-field
   §1.2 contract and the trust-2 text otherwise untouched).
5. Test arms §5 in `tests/server/test_serial_discovery.py` (scan arms) and
   `tests/server/test_binding_flow.py` (mint arm, extending
   `test_the_factory_records_the_mint_time_serial`'s construct at
   `test_binding_flow.py:643-653`).
6. `docs/internal` legs: none move (§7).

**Deferred, each with a home and a reopen trigger** (trigger contract per
the main gateway repo's `.claude/deep-review/README.md`):

| # | Deferral | Home | Reopen trigger (observable) |
|---|----------|------|------------------------------|
| D1 | The FTDI lane's byte-identical shape: `discover_ftdi_devices`' `connected_url` compare (`ftdi.py:1970`) has the same byte-equality posture over `ftdi://` URL spellings (index/serial/description forms). | This record's deferral table; NOT filed as a new gateway issue (it may be empty — the #589 canonical-URL fold may already normalize). | A fixture or operator trace showing a connected-era FTDI scan opening a candidate whose URL is a re-spelling of `connected_url`. Disclosed weak form: subject inspectable (the trace), firing needs someone to look. |
| D2 | Windows `\\.\COM10` vs `COM10` spelling (documented Windows arcana for ports ≥ 10; pyserial accepts both, byte-compare misses). Not covered: adding a fourth clause without any Windows-hardware evidence would be the heuristic-without-evidence this design refuses. | This record's deferral table. | An operator report or a Windows CI-able fixture exhibiting that spelling class re-probing. |
| D3 | Live-bench verification of the darwin stem pairing and by-id resolution against real adapters (the platform invariants in §2 are argued from OS structure plus this machine's `/dev`; no hardware CI exists here). | This record's deferral table; a `live_*`-marker arm is the natural vehicle if taken (CI-deselected, bench-run — the `live_ftdi` precedent, `ci.yml`). | A live bench scan trace showing either (a) a skip that omitted a genuinely different device, or (b) an open of an alias-spelled connected port. Either outcome is decidable from the trace. |
| D4 | Row-shape/dedup policy IF any platform ever enumerates BOTH spellings of one node (darwin does not — §2.1; the fix serves one row there, same as today's byte arm). | This record's deferral table. | A pyserial release or platform whose `comports()` yields both spellings for one device — observable as a duplicated `port_path` pair in one scan's rows. |
| D5 | A user-guide note on alias spellings in discovery (no `cu/tty`/`by-id` mention exists in `user_guide/plugin-sdk.qmd` today — grep-verified; behaviour is host-side and self-explaining in the row's `port_path`). | This record's deferral table. | Disclosed weak/judgement form: an operator question on the tracker about which spelling to pass as `--device`. |

## 5. The measurable proof — acceptance rule pre-committed

All arms hardware-free (injected `SerialPortHooks` / `open_port` doubles —
the module's standing posture; the suite must not depend on a device
being present). Fixture names invented (`usbmodem-DEMO01`, `SER-A`).

**RED arms — must FAIL at HEAD (this is the premise check):**

- **R1 (darwin stem class):** enumeration lists ONLY
  `CandidatePort("/dev/cu.usbmodem-DEMO01", vid, pid, serial_number="SER-A")`;
  `connected_device="/dev/tty.usbmodem-DEMO01"`, `connected_identity` set,
  `connected_serial="SER-A"`, `connected_serial_known=True`. Assert: the
  connected row is served with `usb_serial == "SER-A"` AND
  `fx["opened"] == []` (never opens). At HEAD the candidate is not skipped
  and `open_port` fires → RED on the `opened` assertion.
- **R2 (symlink class):** in `tmp_path`, create a regular file `node` and
  `os.symlink("node", "by-id-link")`; enumeration lists
  `CandidatePort(str(node), …, serial_number="SER-A")`;
  `connected_device=str(by-id_link)`, serial known `"SER-A"`. Assert row
  served AND `opened == []`. At HEAD → RED. Arm skips
  (`pytest.skip`) where `os.symlink` raises `OSError` (Windows CI without
  symlink privilege) — the cu/tty arms carry the darwin-class proof
  without filesystem involvement.
- **R3 (mint recording, the second site):** `serial_plugin_session` with
  `endpoint=SerialEndpoint("/dev/tty.usbmodem-DEMO01")` (and a by-id twin
  arm), injected `open_port`, `enumerate_ports` listing the `cu.` spelling
  with `serial_number="SER-A"`; connect; assert
  `endpoint.last_serial == "SER-A"` and `last_serial_known is True`. At
  HEAD the lookup misses and records `None` → RED. (Construct precedent:
  `test_binding_flow.py:643-653`.)

**GREEN arms — behaviour that must stay byte-identical:**

- **G1:** the existing byte-equal skip (`test_serial_discovery.py:185-211`)
  and the unconnected scan suite unchanged.
- **G2:** the trust-2 drop at a byte-equal path
  (`test_serial_discovery.py:214-244`, `test_binding_flow.py:656`) —
  the drop branch's bytes and behaviour untouched.
- **G3 (new pin, the critical non-regression):** alias-equivalent name
  (`cu.`/`tty.` pair) with `connected_serial_known=True` and a MISMATCHING
  live serial → row dropped, nothing opened. Today this case cannot reach
  the drop (it falls to identify); after the fix it enters the skip and
  MUST still drop. This is the arm that kills the one-site regression of §1.
- **G4 (equivalence precision):** two different stems
  (`/dev/cu.usbmodem-DEMO01` vs `/dev/cu.usbmodem-DEMO02`) → no skip,
  identify as today (`opened` records the candidate). Pins against
  over-matching.

**RED control (mechanism-kill):** with the change in place, disable one
clause at a time — comment the stem clause → R1 and R3's tty arm fail;
comment the realpath clause → R2 fails; revert site 2 only → R3 fails and
G3 alone cannot detect it (disclosing that G3 covers the scan side, R3 the
mint side — both are needed).

**Pre-committed acceptance rule (written before any of the above ran —
this commit precedes the build branch's code):**

- **SHIPS iff:** R1, R2 (where not skipped), R3 are RED at HEAD and GREEN
  with the change; G1–G4 green before and after; full
  `uv run pytest tests/server/test_serial_discovery.py tests/server/test_binding_flow.py -q`
  green with a collected count > 0 read from the raw run; repo gates
  (`ruff check .`, bare `uv run mypy`, `sync-standards --check`,
  `--version` smoke) green.
- **KILLS:** any R arm already passing at HEAD (the premise is wrong —
  investigate, do not build); any G1/G2 arm changing in any way (a
  byte-identical clause moved — redesign); the stem clause requiring
  platform-sniffing (`sys.platform` gates) to pass — the rule must be
  spelling-shape-only, or it is the wrong rule.
- **UNDERPOWERED, not conclusive:** R2 skipped on every CI leg (symlink
  privilege absent everywhere) — then the symlink class is bench-verified
  only and D3's trigger is load-bearing; state it in the build report.

**Value claim and its falsifier:** "a connected-era scan opens no port
whose spelling is an alias of the connected port." Falsified by any arm
showing `opened` non-empty for an alias spelling, or by a live trace of
D3's kind.

## 6. What cannot be tested here

Stated plainly: the darwin kernel's stem-pairing invariant and Linux udev
by-id resolution against real adapters (D3); Windows behaviour beyond the
string-level arms (the CI Windows leg runs the cu/tty arms as pure string
comparisons — valid, since the clause is spelling-shape-only). Everything
else in §5 is hardware-free by construction.

## 7. Invariant, standards and drift impact

- `docs/internal/invariants.md`: no row moves. The no-re-probe clause is a
  test-pinned behaviour (SW-62 lineage), not an STD/PKG/SRF invariant; no
  new row is proposed (the predicate is intra-module; when the maintainer
  wants a numbered row for "node-level vs unit-level identity", that lands
  with the build PR, per the SRF-4 row-id convention).
- Standards: the vendored corpus has no discovery/port content
  (grep-verified — no `discover` match under `src/benchweave_sdk/standards/`).
  `standards-lock.json` and the vendored tree DO NOT MOVE. Not Tier 3 on
  the standards surface.
- `docs/internal/drift-and-obligations.md`: no path-shaped obligation rows
  name `serial.py` or the two test modules (grep-verified); the CI map row
  is unchanged — no new markers, no new jobs; CI cost is the added arms
  only.
- Public-facing surfaces: none move — no scaffold, no CLI surface, no
  schema, no generated output. `port_path` row spelling is unchanged
  (§1.2 contract: the row names the enumerated candidate).

**Review tier: Tier 2** (Python logic under `src/`, no refusal prefix
added or changed, no lock/scaffold/packaging/dependency surface —
`docs/internal/review-rubric.md` Step 1). **G0 keyword scan run** over
this record's text and the expected diff vocabulary (predicate name, the
two call sites, arm names): no secret-shaped strings (keys, tokens,
hosts, install-specific paths); fixture device names are invented
(`usbmodem-DEMO01`, `SER-A`); the platform-evidence device names cited
are the OS's own built-ins, not this install's bench devices.

## 8. Top risks, first-ranked

1. **The one-site regression (§1):** patching only `serial.py:1638` makes
   the by-id/tty operator's row DROPPED (trust-2 mismatch on a
   `None`-recorded mint serial) instead of merely re-probed. Falsified
   by R3: if the mint site cannot be driven alias-aware, the whole design
   is wrong and the kill rule fires.
2. **Stem-rule over-match on an unobserved platform shape** (§3): accepted
   residual; guarded by trust-2 when serials known; D3's trace is the
   detector.
3. **realpath cost/behaviour drift across platforms** (e.g. a future
   platform resolving `/dev` itself): bounded — worst case the clause
   under- or over-matches exactly the symlink class, G4 plus R2 pin the
   observed behaviour.
4. **The `None`-serial conflation's history:** rows recorded before this
   fix (long-lived sessions) carry `None`/known mint serials for aliased
   spellings; after the fix their NEXT mint records correctly. A scan in
   between may drop the connected row once (trust-2 firing on stale
   evidence) — self-healing on reconnect, disclosed here so it is not
   reported as a new defect.
