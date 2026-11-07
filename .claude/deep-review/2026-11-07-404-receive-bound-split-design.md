# #404 — the serial receive bound: a frame-scale descriptor bound applied to a transfer-scale receive

Status: design. Reproduced at `origin/main` = `228cd30`. Measurements below are local
loopback on the design worktree, 2026-11-07, with a fake port; no hardware is claimed.

Tracker: gateway issue #404 (single issue stream; no SDK-side issue by design).

## 0. Verdict

The issue's mechanism is **right** and I reproduced it. The issue's *proposed fix* is
**half right**: the split it asks for changes nothing where it is currently applied, and
it is genuinely breaking where it would matter. The minimal correct increment is
**mode-scoped**, not a straight swap of one bound for another.

Build this. Do not build the issue's full split in this increment.

## 1. Root cause, traced

The clamp is one expression, and it is applied on four hosts.

`src/benchweave_sdk_server/serial.py:737`

```python
self._ceiling = min(link.transfer_ceiling, max_frame_bytes)
```

`self._ceiling` is the only ceiling the shared receive ladder sees —
`serial.py:796` → `_stream_receive_bounds(t, self._ceiling)` at `serial.py:101`. The
ladder refuses before any I/O:

`serial.py:111-116`

```python
    if (
        not isinstance(max_bytes, int)
        or isinstance(max_bytes, bool)
        or not 1 <= max_bytes <= ceiling
    ):
        raise ValueError(f"max_bytes must be 1..{ceiling}")
```

So `max_frame_bytes`, a **descriptor declaration of the largest single frame**, becomes
the ceiling on **how much one receive may pull**. `max_bytes` is simultaneously the frame
bound and the transfer bound, because in terminator mode a receive *is* a frame
(`SerialLink.take` returns at the first terminator, `serial.py:381-383`).

The same collapsed clamp is minted independently on the other hosts:

| Host | Line | Expression |
|---|---|---|
| serial (+ ftdi subclass) | `serial.py:737` | `min(link.transfer_ceiling, max_frame_bytes)` |
| byte-stream mock | `transport.py:246` | `min(max_frame_bytes, TRANSFER_CEILING)` |
| replay host | `replay.py:805` | `min(max_frame_bytes, TRANSFER_CEILING)` |
| replay load-time ladder | `replay.py:521` | `TRANSFER_CEILING` **flat** — *not* clamped |

The last row is a **second latent defect, pre-existing and independent**: a journal row
carrying a bulk receive (`max_bytes` ≤ 64 KiB) *loads* fine at `replay.py:521` and then
*refuses at runtime* at `replay.py:1063` against a small descriptor. Load and runtime
already disagree about the same row.

## 2. Reproduction (measured, not read)

Harness: a scratch pytest module outside the tree (`/tmp`, never committed), building a
real `SerialCaptureServices` over a fake `Transport` that blocks 2 ms when empty (a fake
port returning `b""` instantly hot-spins `SerialLink._drain` — my first harness did, and
it hung; that is a harness defect, not a mechanism finding).

**Arm A — the clamp is live.** `max_frame_bytes=23`, `stream_receive`
`{max_bytes: 65536, exact_bytes: 65536}`:

```
[A] bulk receive REFUSED: ValueError('max_bytes must be 1..23')
[A] link.transfer_ceiling    = 65536
[A] services._ceiling        = 23
```

1 case, 1 host. The transfer ceiling is 64 KiB and the receive is refused at 23 B.

**Arm B — a modest multi-frame receive is refused too.** `{max_bytes: 2048,
termination: 'lf'}` → `ValueError('max_bytes must be 1..23')`. So 89 frames' worth is
refused, not only an implausible 64 KiB pull.

**Arm C — three drains of one identical feed.** Feed = 13,356 frames × 23 B = **307,188 B**
= one second at the 3 Mbps 8N1 byte rate (300 kB/s, #393's rate class). Receive counts are
deterministic; no timing assertion.

| leg | descriptor | receive strategy | receives | bytes |
|---|---|---|---|---|
| 1 | `max_frame_bytes=23` | `exact_bytes=23` (the clamp's only shape) | **13,356** | 307,188 |
| 2 | `max_frame_bytes=65536` | terminator mode, `max_bytes=65536` | **13,356** | 307,188 |
| 3 | `max_frame_bytes=65536` | `exact_bytes=65536` (bulk) | **5** | 307,188 |

```
leg1 / leg3 = 2671x   the clamp's call amplification
leg1 / leg2 = 1.00x   does over-declaring help TERM mode?
```

**Leg 2 is the design-critical row.** Over-declaring the descriptor changes the terminator-
mode call count by **exactly zero** — because a terminator-mode receive returns at the
first terminator regardless of the ceiling. So *relaxing the bound in terminator mode
fixes nothing*. Only the `exact_bytes` bulk path is actually blocked.

**Arm D — per-receive wall cost.** Same loopback, no hardware claim. 3,000 receives
(leg 1) and 200 receives (leg 3), feed kept under the 512 KiB ring so nothing is dropped:

```
leg1  max_frame=23     exact=23     41.9 us/receive   23 B/call    -> 535 KiB/s
leg3  max_frame=65536  exact=1472   40.6 us/receive 1472 B/call    -> 35,444 KiB/s
wire requirement                     300 KiB/s (3 Mbps 8N1)
leg1 dispatch for 1 s wire = 0.56 s of one core (13,356 calls)
leg3 dispatch for 1 s wire = 0.0084 s of one core (208 calls)
```

The cost is the `asyncio.to_thread` + condition-wait round trip (~42 µs), essentially
independent of payload size. At the clamp's only shape, one second of wire costs **56% of
one core** in pure receive dispatch before the adapter, the capture writer or a slower host
is counted. The honest local ceiling is 535 KiB/s against a 300 KiB/s requirement — it
fits, with no headroom.

**Correction to the issue's own number.** The issue says "~19,000 calls/s". At the 23 B
frame the issue itself declares, the honest figure is **13,356/s** (300 × 1024 ÷ 23). ~19,000/s
corresponds to a ~16 B frame (307,200 ÷ 16 = 19,200). The mechanism holds; the cited number
does not match the cited frame size.

## 3. What the fix actually is

`exact_bytes` is the transfer-scale operation — "give me N bytes, framing is mine". It
must be bounded by the **transfer** ceiling. Terminator mode is the frame-scale operation —
"give me one frame" — and must stay bounded by **both**, because a receive that returns at
a terminator *is* a frame.

So the rule is mode-scoped:

- `exact_bytes` absent or zero → **frame mode** → `1 <= max_bytes <= min(transfer_ceiling, max_frame_bytes)` (**unchanged**)
- `exact_bytes` positive → **bulk mode** → `1 <= max_bytes <= transfer_ceiling`, and `0 <= exact_bytes <= max_bytes` (**the frame bound no longer applies**)

### The minimal first increment

1. `serial.py:101` — `_stream_receive_bounds(t, ceiling)` gains a second bound and picks
   per mode. One shared definition stays one shared definition (#394's precedent):

   ```python
   def _stream_receive_bounds(
       t, *, frame_ceiling, transfer_ceiling
   ) -> tuple[int, bytes, int]:
       ...
       bulk = isinstance(exact, int) and not isinstance(exact, bool) and exact > 0
       ceiling = transfer_ceiling if bulk else frame_ceiling
       if (... not 1 <= max_bytes <= ceiling):
           raise ValueError(f"max_bytes must be 1..{ceiling}")
   ```

   `bulk` is computed from a *valid* positive int so a malformed `exact_bytes` stays in
   frame mode and hits the existing `exact_bytes must be None or 0..max_bytes` refusal —
   the current validation ordering is preserved for every malformed input.

2. Each host keeps both bounds separately instead of collapsing them at construction:
   - `serial.py:737` — keep `self._ceiling` (frame) as today; add `self._transfer_ceiling = link.transfer_ceiling`.
   - `transport.py:246`, `replay.py:805` — keep `self._ceiling` (frame) as today; `self._transfer_ceiling = TRANSFER_CEILING`.
   - `replay.py:521` — load-time ladder becomes `frame_ceiling=TRANSFER_CEILING, transfer_ceiling=TRANSFER_CEILING`, which is what it already computes, and it now agrees with runtime.

3. Three call sites pass both bounds: `serial.py:796`, `transport.py:399`, `replay.py:1063`.

4. Docs leg (in the slice): `user_guide/plugin-sdk.qmd:768-777` carries a third copy of the
   ladder in the copy-into-your-project example, executed and pinned by
   `tests/test_guide_serial_host.py`. It must gain the bulk-mode rule in the same commit;
   a guide left teaching the old rule trains authors into the defect.

No new module, no new abstraction, no new prefix.

### Explicit deferrals

| # | Deferred | Why | Reopen trigger |
|---|---|---|---|
| D1 | The issue's full split: let `max_bytes` exceed `max_frame_bytes` in **terminator** mode | Measured **zero** benefit (leg1/leg2 = 1.00×) and genuinely breaking: a plugin declaring `max_frame_bytes: 23` could then be handed a 64 KiB multi-frame run as one "frame" | A real plugin project's capture path must move a **terminator-delimited** multi-frame burst in one call and cannot compute `exact_bytes` (e.g. no length prefix) |
| D2 | Unifying the three descriptor fallbacks (`transport_ceiling` 4096, `mock_exchanges` 128, `scenarios._frame_bound` 128) | Pre-existing divergence, not caused by this defect; changing it changes the mock's scripted `max_bytes` | A parity arm finds a host disagreement traceable to the fallback |
| D3 | Full ladder unification across load/runtime and all four hosts | This slice makes the replay load/runtime pair agree; a single ladder object is a larger refactor | A fifth host appears |
| D4 | The unprefixed refusals in `_stream_receive_bounds` (`max_bytes must be 1..N`, `termination must be …`, `exact_bytes must be …`) | A **pre-existing STD-4 deviation** — STD-4 requires a `snake_case:` prefix. Fixing it is a refusal-text change on a landed surface, forbidden in this slice | Maintainer ruling (see §8) |
| D5 | Rewriting the guide's capture narrative beyond the example's ladder | Docs scope; the example's correctness is what the slice owes | A guide reader reports the old semantics |

## 4. Precedent

The shared `_stream_receive_bounds` definition is the precedent, created by #394 for
exactly this reason — "outcome parity is pinned, not hoped: one definition cannot drift"
(`serial.py:101-107`). This slice **extends that one definition** with a mode-scoped
ceiling rather than adding a second ladder per host. `transport_ceiling()`
(`session.py:166-174`) is the single-derivation precedent and is unchanged: the
descriptor bound still derives the frame ceiling.

This is not new architecture. The only new concept is "which bound applies depends on the
receive mode", which the §8.1 grammar already implies — `exact_bytes` takes precedence
over `termination` (`serial.py:377`, `take()` at `serial.py:377-386`).

## 5. Is this breaking?

**The minimal slice is additive, not breaking.** Nothing that works today stops working:

- terminator-mode receives: `max_bytes` bound is byte-identical, same refusal text
  (`max_bytes must be 1..{min(transfer, frame)}`).
- bulk receives at or below the frame bound: still accepted.
- bulk receives above the frame bound: **start** succeeding. That is the defect being
  fixed; no plugin can have depended on the refusal.

Four in-tree pins **must stay green unchanged** — they are the proof the slice is not
breaking. All four are terminator-mode (`exact_bytes: None` via `_exchange`/`_receive`,
`tests/server/test_mock_bytestream_parity.py:117-136`):

- `test_mock_bytestream_parity.py:364` — `max_bytes must be 1..128` (F2)
- `test_mock_bytestream_parity.py:393` — `max_bytes must be 1..128` (F9)
- `test_mock_bytestream_parity.py:433` — `max_bytes must be 1..65536` (P2, descriptor over-declare clamped by transfer)
- `test_mock_bytestream_parity.py:462` — `max_bytes must be 1..4096` (F4, silent descriptor)

If any of these changes verdict, the deferred breaking half has leaked in.

**The full split (D1) is breaking** and needs a migration story: it changes what
`stream_receive` returns for a descriptor that under-declares its frame size. That is
precisely why it is deferred — and the measurement says it buys nothing.

## 6. Every reader of both bounds

Verified by grep at `228cd30`; `file:line` each.

### `max_frame_bytes` (descriptor-declared; vendored schema `type: integer, minimum: 1`, required for `serial`/`uart_scpi`/`uart_json`)

| # | Reader | Effect | Moves in this slice |
|---|---|---|---|
| 1 | `session.py:166-174` `transport_ceiling()` | derives frame ceiling `min(declared or 4096, 65536)` | no |
| 2 | `session.py:380` `mock_exchanges` | `max_bytes = declared or 128` for scripted exchanges (`:395`) | no |
| 3 | `scenarios.py:133-136` `_frame_bound()` | same, fallback 128 (`:144`) | no (D2) |
| 4 | `serial.py:736-737` | frame ceiling `min(link.transfer_ceiling, declared)` | **split into two fields** |
| 5 | `transport.py:246` | `min(declared, TRANSFER_CEILING)` | **split into two fields** |
| 6 | `replay.py:805` | `min(declared, TRANSFER_CEILING)` | **split into two fields** |
| 7 | `ftdi.py:2008`, `ftdi.py:2109` | `transport_ceiling(settings)` into `FtdiCaptureServices` (inherits serial's clamp, `ftdi.py:1080-1090`) | follows #4 |
| 8 | `serial.py:1481` | discovery's `_confirm_by_identify` mints services with `transport_ceiling(...)` | follows #4 |

### `transfer_ceiling` / `TRANSFER_CEILING`

| # | Reader | Effect |
|---|---|---|
| 1 | `session.py:163` | the definition, 64 KiB |
| 2 | `session.py:174` | clamps the declared frame bound |
| 3 | `serial.py:52,182` | `SerialLink` constructor default |
| 4 | `serial.py:194-199` | validation, prefix `standalone_serial_link_transfer_ceiling` |
| 5 | `serial.py:233-235` | the `transfer_ceiling` property |
| 6 | `serial.py:1017,1109` | `reconfigure_link` carries it onto the new link |
| 7 | `serial.py:737` | half of the frame ceiling |
| 8 | `transport.py:38,246` | the mock's clamp |
| 9 | `replay.py:93,521,805` | import; **flat** load-time ladder; host clamp |
| 10 | `test_serial_link.py:89,93-94` | pins the 64 KiB default and the typed refusal |
| 11 | `test_mock_bytestream_parity.py:404-413` | pins `transport_ceiling`'s four-case resolution |

### Tests that pin today's behaviour

| Test | What it pins | Fate |
|---|---|---|
| `test_mock_bytestream_parity.py:364,393,433,462` | the clamp, dual-leg | **must stay green unchanged** |
| `test_mock_bytestream_parity.py:404-413` | `transport_ceiling` resolution | unchanged |
| `test_serial_conformance.py:850-854` | M3 mutant killed by "max_bytes above the ceiling must refuse" (`_cell_c10`) | **moves** — the arm becomes mode-scoped: terminator mode still refuses, bulk mode does not |
| `test_serial_conformance.py:740-757` | a third copy of the ladder inside the M3 mutant | moves with M3 |
| `test_serial_link.py:89-94` | `transfer_ceiling` default + validation | unchanged |
| `test_serial_soak.py:25,95` | a per-frame capture at 200 KiB/s (`max_bytes=_FRAME, exact_bytes=_FRAME`) | **control — must stay green**: a real per-frame capture path is unaffected |
| `test_serial_services.py:28,389,427,564,577` | `max_frame_bytes` 128 / 64 terminator-mode arms | unchanged |
| `test_serial_session.py:106` | descriptor round-trip `max_frame_bytes == 128` | unchanged |
| `test_guide_serial_host.py` | executes the guide example | moves with the guide leg |
| `test_claim_probes.py:206,281`, `test_ftdi.py` (many), `test_reconfigure_folds.py`, `test_mock_bytestream_cycle.py` | construct with `max_frame_bytes=4096`/`128` | unchanged (frame ceiling identity preserved) |

## 7. Standards, invariant and drift impact

**Vendored corpus: NOT involved.** `max_frame_bytes` is a descriptor schema property
(`otdp-device-descriptor.schema.json`, `$defs/{serial,uart_scpi,uart_json}Transport/
properties/settings/properties/max_frame_bytes`) whose entire normative content is
`{"type": "integer", "minimum": 1}`. A grep over the vendored tree for prose
(`src/benchweave_sdk/standards/**/*.md`, `*.txt`) returns **nothing** — the vendored corpus
states the property's *shape*, not its *meaning*. The schema shape does not change, so
there is **no corpus change, no `standards-lock.json` motion, no re-sync, and no standards
version increment**. On the review rubric's Step 1 this does **not** trigger the Tier-3
lock ↔ tree ↔ stamps rule.

Honest gap: because the corpus carries no semantics text, this slice's justification rests
on the descriptor schema (a declared frame bound) plus the §8.1 receive contract (one
complete receive), not on a citable standard clause. If the maintainer wants the semantics
*written*, that is a main-repository corpus prose change and **cannot land first from here**
— and it would make this Tier 3.

**Invariants:** no invariant changes and no new invariant is needed.
- STD-1/STD-2/STD-3/STD-5 — untouched (no vendored bytes, no lock, no stamps, one tree).
- STD-4 — **no prefix added, renamed or removed.** The refusal text keeps its existing
  unprefixed shape; `max_bytes must be 1..{ceiling}` is already the string the parity pins
  match (`:433` pins `1..65536`). The pre-existing unprefixed rows remain a known deviation
  (§8, D4).
- SRF-3 — the slice does not weaken a conformance rule. It corrects a rule that is wrong
  for one receive mode, and the four unchanged terminator pins are the evidence.
- SRF-1 — **no scaffold output change.** The generated descriptor keeps
  `max_frame_bytes: 128`; `tests/fixtures/scaffold_expected/` does not move. No golden diff.
- PKG-1/PKG-2 — no parent path, no wheel-content change.

**Drift obligations (`docs/internal/drift-and-obligations.md`):**
- Row 1 (guide prose) — `user_guide/plugin-sdk.qmd` moves: the example ladder `:768-777`
  and the §8.1 outcome sentence `:661`. In the slice.
- Row 2 (scaffold/template) — no motion.
- Row 4 (packaging) — no motion.
- Row 5 (vendored bytes) — no motion.
- Rows 9/10 (release-managed prose) — no version literals move.

**CI cost:** no new lane. The arms are deterministic and unmarked, so they ride the
existing `pytest -q` `-n auto` leg; nothing is added to the serial `timing` or the ubuntu
`loop` legs. The measurement arms construct a link and a fake port — the same shape as
`test_serial_soak.py` without the 10-second sleep.

**Cross-repo obligation (cannot be proven here).** The SDK's one-line promise is "what the
SDK accepts is what the gateway accepts". If the gateway's own runtime applies the old
clamp, this slice makes the SDK accept a bulk receive the gateway refuses. That is the
promise broken. I **cannot read the gateway checkout from here** (self-containment; Gortex
unavailable to this agent), so this must be verified main-side before the SDK half lands,
or a pairing row added under the gateway's `tests/sdk/`. Recorded as an honest negative,
not assumed green.

## 8. Pre-committed acceptance rule

Written **before** any implementation number is taken. The reproduction numbers in §2 are
properties of *current main*, not of the fix.

**Metric M** — the number of `stream_receive` calls required to drain one fixed byte
stream, counted from the harness call counter. Feed: 13,356 frames × 23 B = 307,188 B
(one second at the 3 Mbps 8N1 byte rate, #393's class). Denominator stated per arm.

**Arms** (each run on **both** the serial backend and the byte-stream mock — 2 hosts):

| Arm | Descriptor | Receive | Predicted | Mutation that must redden it |
|---|---|---|---|---|
| A1 | `max_frame_bytes=23` | `{max_bytes: 1472, exact_bytes: 1472}` | **succeeds**, returns 1472 B | restore `min(transfer, frame)` unconditionally → refused |
| A2 | `max_frame_bytes=23` | `{max_bytes: 1472, termination: 'lf', exact_bytes: None}` | **refused** `max_bytes must be 1..23` | apply the full split (D1) → succeeds |
| A3 | `max_frame_bytes=65536` | `{max_bytes: 70000, exact_bytes: 70000}` | **refused** `max_bytes must be 1..65536` | drop the transfer clamp → succeeds |
| A4 | `max_frame_bytes=23` | bulk drain, `exact_bytes=1472` + tail | **≤ 209 calls** | restore the clamp → 13,356 calls |
| A5 | `max_frame_bytes=23` | balanced drain, `exact_bytes=23` | **= 13,356 calls** | — (the control) |
| A6 | — | the four existing parity pins `:364,:393,:433,:462` | **unchanged verdict + text** | apply D1 → they change |

Sample size: A4/A5 run **3 repeats per host** (2 hosts × 2 arms × 3 = 12 drains). The
count is deterministic, so all repeats within an arm must be identical; any variance is a
harness defect.

Effect size: **A5 / A4 ≥ 60×** (13,356 ÷ 209 = 63.9).

**SHIPS** only if all of:
- A1 succeeds on both hosts; its mutation reddens it on both.
- A2 refuses on both hosts; its mutation (D1 applied) reddens it on both.
- A3 refuses on both hosts; its mutation reddens it on both.
- A4 ≤ 209 on all 3 repeats of both hosts; A5 = 13,356 on all 3 repeats of both hosts.
- A6 unchanged — all four pins keep their verdict **and** their exact message text.
- `uv run pytest tests/server -q` and `tests/test_guide_serial_host.py` green with raw
  counts read from the run.

**KILLED** if any of:
- A4 > 209 on any host — the bulk path is not delivering the claimed reduction.
- A4's mutation does **not** raise it to 13,356 — the frame clamp is not the cause, and the
  whole design premise is wrong.
- A5 moves away from 13,356 in either direction — terminator semantics changed, i.e. the
  deferred breaking half leaked in.
- Any of A6 changes verdict or text.
- Either host's arms disagree with the other's in verdict — the shared definition drifted.

**UNDERPOWERED — not evidence either way, do not ship:** repeats within an arm disagree;
or an arm's byte total ≠ 307,188 B (the feed is being dropped — the ring is 512 KiB and a
bulk drain can overflow it); or a host leg cannot drain the feed in one attempt. In that
case the measurement is re-designed and re-committed before any conclusion is drawn.

## 9. Top risks

| # | Risk | What would falsify it |
|---|---|---|
| R1 | The gateway's runtime keeps the old clamp, so the SDK accepts what the gateway refuses | A main-side pairing arm under the gateway's `tests/sdk/` showing the gateway refusing a bulk receive the SDK accepts. **Not checked here.** |
| R2 | The bulk path invites an unbounded pull and overflows the 512 KiB ring during a real capture | A soak arm at the #393 rate with bulk receives showing `dropped_bytes > 0`. The ring capacity is unchanged by this slice; the risk is pre-existing but newly reachable. |
| R3 | A malformed `exact_bytes` picks the wider ceiling before being refused, naming a different ceiling in its message | The A2/A3 message text assertions above; the `bulk` predicate uses a valid positive int only |
| R4 | Host drift — serial fixed, mock or replay left on the old clamp | A1/A2/A3/A4 run dual-host and must agree; the mutation matrix reddens each host separately |
| R5 | The guide example is left teaching the old rule | `tests/test_guide_serial_host.py` extended with a bulk-mode arm; a missing guide leg reddens it |
| R6 | The `replay.py:521` load/runtime agreement is claimed but not pinned | A journal row with `max_bytes` > frame bound must load **and** replay; an arm for it is in the slice |

## 10. Ordering and tier

**Tier 2, own increment, own refute lane.** The rubric's Step 1 rules: it touches no lock,
no vendored tree, no `hatch_build.py`, no scaffold shape, no `conformance.py`/`validation.py`/
`fixtures.py`, no dependency, and no new refusal path — so it is **not Tier 3**, despite
being a semantics change on a landed surface. Its own refute lane is nevertheless required
by the risk profile, not the rubric: the failure mode is four hosts drifting apart, and a
lane is the cheap control for it. The issue's framing that this "must ship as its own
increment with its own refute rather than folded into #393" is **correct**, for that reason
rather than for the breaking-change reason it gives.

Order: SDK design (this) → refute on the design (R1 and R3 are the live questions) →
implementation with the arms above → main-side gateway parity check → pointer commit.
The gateway half cannot be skipped: a green SDK with a refusing gateway breaks the
promise at the top of this repository's README.

## 11. Open decisions for the maintainer

1. **D4 — the STD-4 tension.** `_stream_receive_bounds` raises three unprefixed
   `ValueError`s (`max_bytes must be 1..N`, `termination must be …`, `exact_bytes must be …`)
   while STD-4 requires `snake_case:` prefixes. This slice is forbidden from adding or
   renaming prefixes, so the deviation persists. Rule whether it is fixed in its own
   increment (it is a public refusal-text change) or amended in STD-4 as a grandfathered row.
2. **R1 — where the gateway parity proof lives.** If the gateway's runtime is a separate
   implementation, this slice needs a main-side pin before it can ship. Choose the venue.
3. **The semantics gap.** The vendored corpus defines `max_frame_bytes` only as
   `integer >= 1`. If the meaning should be normative, that is a main-repository corpus
   prose change, which makes the next touch of this surface Tier 3.
