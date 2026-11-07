# Issue #571 — readings-page per-parameter isolation (design record)

Gateway issue #571 (single issue stream; no SDK-side issue by design). Design only —
this record is the increment's authority; the build agent implements against it.

## 0. Verification of the premise (re-read at current main)

The issue was verified at `39043cc`; current `origin/main` is `ff87c76` (verified
`git rev-parse`; the worktree for this design sits on it). Two slices merged in
between touched `seam.py`, `catalogue.py`, `presentation.py`, `authoring.py` — none
changed the anchors' behavior; line numbers shifted ~15 down. Re-verified anchors:

- `_gather_readings` — `src/benchweave_sdk_server/web.py:870-901` (issue said
  855-886). The early `return` at the first `SeamError` is `web.py:895-900`.
- `readable_parameters` — `src/benchweave_sdk_server/session.py:141-147`, exact.
- `templates/readings.html:1-5` — exact; and the template's `{% elif readings %}`
  at line 5 makes notice and table mutually exclusive, so rows gathered before the
  refusal are dropped twice over (once by the early return, once by the branch).
- Polled partial — `web.py:946-962` (`readings_partial`; issue said 931-947).

The premise holds. A third consumer the issue does not name has the same shape:
`_page_reading_state` (`web.py:966-1030`, early return at `web.py:998-1005`) feeds
the manifest pages and the `/pages/{page_id}/readings` partial. Its disposition is
§5 D1 (deferred, with the divergence named).

Tooling note: the gortex daemon reports no graph access for this checkout
(`view_building`); all reads were native Read/Grep against the worktree at
`ff87c76`.

## 1. Root cause, established

`_gather_readings` loops the descriptor's readable parameters (`ro` and `rw`,
`session.py:141-147`) and treats ANY `SeamError` from `seam.call("parameter_read",
…)` as terminal for the whole page: `web.py:895-900` returns
`(partial_readings, error_dict)` at the first refusal. `readings.html` then renders
the refusal notice INSTEAD of the table (`{% if readings_error %}` precedes
`{% elif readings %}`), so the successfully-read rows vanish from the page. The
defect is the gather's single failure class: it does not distinguish "this
parameter's read was refused" from "the session cannot read anything".

Both HTML surfaces share the one gather: the device page includes `readings.html`
inline (`device.html:87-92`, inside the `hx-get`/`hx-trigger="every 2s"` poll
region) and the polled partial renders the same template from the same gather —
so one refusing parameter blanks the device page's table, every 2-second poll, and
the direct partial fetch alike. REST and MCP were never affected (each
`parameter_read` there is an independent call).

## 2. Failure-class enumeration — from the real raise sites, not the issue's examples

Every `SeamError` the gather can see on `parameter_read`, with its true origin.
The vocabulary is the closed seven-code set (`errors.py:26-36`), so this
enumeration is total.

Pre-dispatch gates (`seam.py:824-844`):

| Class | Code | Origin | Nature |
|---|---|---|---|
| Degraded load | `not_ready` | `_refuse_degraded` (`seam.py:478-486`), `details.load_diagnostic` set | Session-level: every operation refuses identically |
| Not connected | `not_ready` | `seam.py:832-833` | Session-level state |
| No such device | `not_found` | `seam.py:827-830` | Page premise (route already 404s on mismatch, `web.py:942-943`, `950-951`; reachable only across a mid-request reload) |
| No such readable parameter | `not_found` | `seam.py:839-844` | Unreachable in the gather (names come from the same set) except across a mid-gather reload |

Dispatch and post-dispatch (`seam.py:4062-4131`, `851-860`):

| Class | Code | Origin | Nature |
|---|---|---|---|
| Adapter `UNSUPPORTED` / `INVALID_ARGUMENT` | `invalid_request` | `_ADAPTER_CODE_MAP` (`seam.py:115-127`), `details.adapter` verbatim | **Per-parameter**: the ask for THIS parameter is refused |
| Adapter `DEVICE_REJECTED` | `conflict` | same map (`seam.py:122`) | **Per-parameter**: the device said no against its own state for THIS read — the issue's reproduction class |
| Adapter `TIMEOUT` | `not_ready` | same map (`seam.py:123`) | Page-level: a slow/dead link must not be polled N more times; each further attempt costs the declared deadline |
| Adapter `TRANSPORT_ERROR` | `not_ready` | same map (`seam.py:124`) | Page-level: the issue names transport loss itself |
| Adapter `PROTOCOL_ERROR` | `unavailable` | same map (`seam.py:125`) | Page-level: a desynchronized protocol stream |
| Adapter `INTERNAL_ERROR` | `internal_error` | same map (`seam.py:126`) | Page-level: unknown plugin failure class |
| Transport `ConformanceError` (incl. the exhausted mock, `transport.py:323,328`) | `unavailable` | `seam.py:4090-4095` | Page-level: transport health |
| Transport `TimeoutError`/`ConnectionError` | `not_ready` | `seam.py:4096-4099` | Page-level: transport health |
| Any other exception | `internal_error` | `seam.py:4102-4107` | Page-level: unknown |
| Read-receipt contract refusal | `unavailable` | `seam.py:851-856` (`read_receipt_invalid:`, issue #567 row 13) | Per-parameter in NATURE (the adapter answered; THIS receipt violates the contract) — but indistinguishable from transport `unavailable` by code. Deferred (D2) |
| `payload_too_large` | — | no raise site on this path (no byte arguments; receipts bounded by the transport ceiling) | Page-level by the default rule, for totality |

**The rule (total over the closed set, fail-closed toward today's behavior):**

- **Per-parameter** (record the refused row, continue the loop) ⇔
  `exc.code in ("invalid_request", "conflict")` AND `seam.session.connected` is
  still `True`.
- **Page-level** (stop, refuse the page as today) ⇔ everything else
  (`not_ready`, `not_found`, `unavailable`, `internal_error`,
  `payload_too_large`), or the session object reports disconnected.

Why the two-code membership is safe: on the read path `invalid_request`'s only
sources are the `UNSUPPORTED`/`INVALID_ARGUMENT` adapter envelopes (the schema-
validation refusal at `seam.py:591` cannot fire for the gather's arguments — the
name is a non-empty string coerced from the descriptor at `web.py:882`), and
`conflict`'s only read-path source is `DEVICE_REJECTED` (the connect-time
"already connected" conflict is a different operation). Why the connected-check
rides along: it is cheap and honest — if the session says disconnected, the page
premise is gone regardless of what class the refusal wore. Its limit is stated:
`session.connected` is cleared only by `close()` (`session.py:1260-1269`), NOT by
transport death — transport death is caught by the `not_ready`/`unavailable`
codes, not by this flag. A dead device therefore cannot render as "a page of
healthy rows with one refusal": a dead link produces `not_ready`/`unavailable`,
which stay page-level, and the loop stops at the first one (no N×deadline poll
cost — the per-parameter classes are fast adapter-envelope answers, not
deadlines).

Direction of default: an unmapped or future class falls page-level — today's
behavior — so isolation only widens for the two classes whose semantics are
unambiguously about one read. A future change to `_ADAPTER_CODE_MAP` that lands a
session-level meaning on `invalid_request`/`conflict` is the residual (R1).

## 3. The mechanism (what the build agent writes)

### 3.1 `_gather_readings` (`web.py:870-901`)

Keep the loop and the row construction; replace the early return:

```python
except SeamError as exc:
    if exc.code not in ("invalid_request", "conflict") or not seam.session.connected:
        return readings, {
            "code": exc.code,
            "message": exc.message,
            "adapter": exc.details.get("adapter"),
        }
    readings.append(
        {
            "name": name,
            "value": None,
            "unit": parameter.get("unit"),
            "quality": "",
            "refusal": {
                "code": exc.code,
                "message": exc.message,
                "adapter": exc.details.get("adapter"),
            },
        }
    )
```

`readings_error` remains exclusively the page-level channel; the refused row's
`refusal` dict mirrors the notice's three fields exactly (`code`, `message`,
`adapter`) so no refusal information is lost in the row-level rendering. No
silent swallow: every refusal stays visible somewhere on the page.

### 3.2 `templates/readings.html`

Inside the existing row loop, a refused-row branch; the notice and `{% else %}`
arms are untouched:

```jinja
{% if row.refusal %}
<td class="value refused" colspan="3">refused — {{ row.refusal.code }}: {{ row.refusal.message }}{% if row.refusal.adapter %} (device answered {{ row.refusal.adapter.code }} / {{ row.refusal.adapter.dispatch_state }}){% endif %}</td>
{% else %}
… the current three cells …
{% endif %}
```

The refused row keeps the four-column table shape (header `parameter | value |
unit | quality`; the last three cells merge), reuses the notice's adapter-detail
sentence verbatim (SW-12 distinctness survives — the author still sees WHICH
refusal), and the marker word is `refused` so substring assertions stay natural.
One CSS rule rides in `ui_assets/standalone.css` beside `.notice-refused`
(line 77): `.readings td.refused { color: var(--bw-status-critical-text); }` —
token-referenced, the notice's own precedent.

### 3.3 The served wire, and what an existing consumer sees

The page-level wire is unchanged: `readings_error` set ⇒ the same notice, same
fields. The per-parameter change is additive inside the table: a consumer that
parses the current page sees, for a refusing parameter, the same `<tr>` with the
parameter name in the row header and `refused — <code>: <message>` (plus the
adapter sentence when the adapter spoke) where the value was; healthy rows are
byte-identical to today. The htmx poll swaps `innerHTML` and is shape-agnostic.
REST/MCP JSON is untouched.

### 3.4 Both surfaces agree — structurally, and pinned

The device page and the polled partial render the SAME template from the SAME
gather (`device.html:91` includes `readings.html`; `readings_partial` renders it
directly; both call `_gather_readings`). The agreement is by construction, not
convention, and acceptance arm A3 pins it against a future fork of either side.
Note the device page's gather guard (`web.py:911-915`: gathers only when
connected AND no presentation) — the both-surfaces arm uses a presentation-free
project (§4 fixture).

## 4. Option 2 (descriptor rule) — rejected as a fix, with the vendored text as authority

- The vendored OTDP 0.2.4 descriptor schema defines exactly
  `"access": {"enum": ["ro", "wo", "rw"]}` and nothing more
  (`src/benchweave_sdk/standards/otdp/0.2.4/otdp-device-descriptor.schema.json`).
  No readability promise exists in the machine authority.
- `parameter_read` is not an interface-catalog operation (the 0.1.1 catalog lists
  the gateway's 19; verified) — it lives in the host's closed SW-10 catalogue,
  described only as "Read one readable parameter from a connected device"
  (`catalogue.py:946-954`). "Readable" is the declaration property (`ro`/`rw`),
  not a device-behavior promise.
- There is no offline enforcement point. `check` validates documents; a device's
  runtime refusal is not knowable from documents. The provider-dialect walk
  (`session.py:645+`) rehearses reads against the plugin's OWN corpus — the
  plugin's claim, not the device's answer; a corpus whose reads rehearse cleanly
  can still meet a device that rejects a read in some states (exactly the #562
  row-16 shape). A conformance rule that cannot fire on the defect it names is
  prose, not a rule.
- The guide already carries the doctrine in the neighboring direction:
  `user_guide/plugin-sdk.qmd` line 885 — a `wo` read "is refused by definition",
  and `parameter_read` serves `ro`/`rw` (line 883). Adding "rw promises the
  device answers reads" would promise something neither the schema nor the
  catalogue nor any executable check stands behind.
- The issue itself concedes the host must still serve the page under option 2 —
  so option 1 is necessary regardless; option 2 adds no mechanism. REJECTED.
  What survives of it is one honest guide sentence (§7 docs leg): a parameter
  whose read the device refuses is marked refused on the readings page without
  blanking the other rows — a statement about the HOST, which is true and
  enforced by A1.

## 5. Scope: the minimal increment and its deferrals

**In scope:** `_gather_readings` (`web.py`), `templates/readings.html`,
`ui_assets/standalone.css` (one rule), the test arms (§6), the guide sentence,
this record. Nothing in `seam.py`, `session.py`, the catalogue, the scaffold, the
standards tree, or packaging moves.

**Refusal contract (STD-4):** this design adds, renames, or re-vehicles NO
refusal. No new prefix exists to state. The per-row `refusal` dict is template
context, not a raised error; every underlying `SeamError` keeps its existing
code, message, and details end to end (the REST/MCP surfaces see identical
bytes).

Deferrals, each with its carrier:

| ID | Deferred | Why | Carrier / reopen trigger |
|---|---|---|---|
| D1 | `_page_reading_state` (manifest pages + `/pages/{page_id}/readings` partial) keeps first-refusal-aborts | Different machinery (bindings, tiles, severities, staged echo, no-data disclosure) and different pinned tests (`test_parity.py:277-282`, `test_web.py:112-121`); the issue names the readings page only. **The named consequence: after this increment the two surfaces diverge for the same underlying refusal — the readings table isolates per-row, the manifest page keeps the notice.** | Follow-up row on gateway issue #571. Reopen: an author reports tile-blanking on a manifest page, or the next slice that touches page rendering |
| D2 | The read-receipt `unavailable` stays page-level | Indistinguishable from transport-conformance `unavailable` by code; splitting needs a `reason` detail on the receipt refusal (`seam.py:851-856`) — a seam change outside this increment's minimal scope. Consequence: a plugin with ONE malformed-receipt parameter still blanks the page (today's behavior, disclosed) | Same follow-up row; the marker candidate is the existing `read_receipt_invalid:` message prefix riding `details.reason` |
| D3 | No `rw`-readability conformance rule | Rejected, §4 — no authority, no enforcement point | Closed by this record unless the corpus gains text |

## 6. Acceptance arms — pre-committed

Deterministic mechanism: the acceptance is enumeration with denominators, not
estimation. Written before any arm ran (this record precedes the build).

**Fixture (shared by A1/A3):** a presentation-free project (scaffold via
`create_project`, then the `test_web.py:86-99` no-ui copytree pattern: delete
`presentation.json`, `binding-catalogue.json`, `ui/`) whose descriptor declares
three readable parameters — `a` (`ro`), `b` (`rw`), `c` (`ro`) — and whose
adapter (the `_ReceiptAdapter` shape from `tests/server/test_read_receipt_gate.py`,
extended to answer per parameter) returns standard ok-receipts for `a` and `c`
(the `_receipt()` canned shape passes `validate_read_receipt`) and
`{"status": "error", "error": {"code": "DEVICE_REJECTED", "message": …,
"dispatch_state": "dispatched"}}` for `b`. The adapter ignores the mock transport;
the precedent proves the shape loads, connects (identify), and reads.

- **A1 — isolation (the fix).** Connected fixture; `GET /devices/{id}/readings`.
  Denominator: 3 declared readable parameters. Ship iff: exactly 3 `<tr>` rows;
  rows `a` and `c` render their values; row `b` carries `refused`, `conflict`,
  `DEVICE_REJECTED`, and `dispatched`; the string `Readings refused` occurs ZERO
  times. **Kill:** the notice present, OR any healthy row missing, OR `b`'s row
  absent. **Underpowered discriminator:** if the fixture cannot refuse exactly
  one parameter without modifying `seam.py`, the arm measures the fixture, not
  the mechanism — stop and report; do not widen the seam to save the arm.
- **A2 — page-level classes still refuse the page.** Three sub-arms, all must
  hold: (a) the severed-script fixture (`test_acceptance_b.py:128-151`'s shape)
  → partial renders `Readings refused` + `unavailable`; (b) a degraded-load
  plugin → partial renders `Readings refused` + `not_ready` (the classification's
  direct pin on this surface; the existing degraded arms are REST-level); (c) the
  existing exhausted-transport arms stay green. **Kill:** any of the three
  renders rows/marks instead of the notice (a session-level failure laundered
  into per-row marks — the exact regression the issue warns about).
- **A3 — both surfaces agree.** Same fixture; fetch `GET /devices/{id}` (the
  inline copy — the fixture is presentation-free so the device page gathers) and
  the partial; assert the three row-name sets are equal, the refused name is `b`
  on both, and `a`/`c`'s values appear on both. **Kill:** any divergence between
  the two renders.
- **A4 — the scenario sweep composes.** The nine-scenario acceptance sweep
  (`tests/server/test_acceptance_b.py`) green with exactly one updated
  expectation: the `device_rejected` arm now asserts the refused-row rendering
  (all rows refused — the scenario rejects every read — with `DEVICE_REJECTED`
  visible) instead of `Readings refused`. Denominator: 9 scenarios. **Kill:** any
  of the other eight scenarios' expectations change.

**RED control (pre-committed):** A1 is red at the current head (it is the
issue's reproduction). After implementation, revert ONLY the gather's
classification (restore the early return) — A1 and A3 redden, A2 stays green —
then restore. The template branch alone cannot green A1 (the gather never
delivers the refused row), which is what makes the control meaningful.

**What breaks (interface changes, named):**

- `tests/server/test_device_rejection.py:60-69`
  (`test_the_html_refused_state_shows_the_adapter_code`): `Readings refused`
  assertion becomes the refused-row marker; `DEVICE_REJECTED` and `dispatched`
  assertions are KEPT (SW-12 distinctness, new home). Interface change: the
  page-level notice no longer occurs for per-parameter classes.
- `tests/server/test_acceptance_b.py` device_rejected arm (~line 107-112): same
  change, inside the sweep.
- Unchanged and must stay green: `test_web.py:112-121` (exhausted transport —
  PAGE partial, D1), `test_parity.py:277-282` (request-rejected on the MANIFEST
  page, D1), `test_read_receipt_gate.py` (seam-level, D2), `test_web.py:77-103`
  (healthy no-ui table), `test_scenario_selection.py:126` (healthy),
  `test_nowrite.py` / `test_mock_bytestream.py` (poll exercising, value-agnostic).

## 7. Invariant and drift impacts

- **STD-1/2/3/5/6, PKG-1/2/3, TWO-1, SRF-1/2/3:** untouched — no vendored byte,
  no lock motion, no scaffold output, no packaging set, no loader/check-ui
  surface. Not Tier 3: the vendored tree and lock are not involved.
- **STD-4:** no new refusal path (§5). The row `refusal` dict is presentation,
  not a raised error.
- **Drift obligations:** row 6 (behavioral suite lives here — modules named in
  §6: `tests/server/test_device_rejection.py` carries A1/A2(b)/A3;
  `tests/server/test_acceptance_b.py` carries A4's update). No CLI/scaffold/
  standards/packaging surface moves, so rows 1-5, 7-11 do not apply. Row 10: no
  version literal moves.
- **Docs:** one sentence in the guide's access-parameters section
  (`user_guide/plugin-sdk.qmd`, beside lines 883-885). Operator-facing published
  documentation — ASD-STE100 register applies; dispatch the `document-writer`
  agent for that leg. Technical content (the code names, the behavior) is fixed
  by this record; the register shapes only the prose.
- **CI cost:** zero new lanes; ~4 new test arms in existing modules.

## 8. Top risks, each with its falsifier

- **R1 — misclassification by future code-map motion.** Someone maps a new
  adapter code with a session-level meaning onto `invalid_request`/`conflict`,
  and a dead link starts rendering per-row marks. Falsifier/mitigation: the
  classification is total and fail-closed; the risk lives in `_ADAPTER_CODE_MAP`
  review, not here. Stated residual, not eliminated.
- **R2 — the connected-check is not a transport-death detector.** Transport
  death keeps `session.connected` true; the codes carry that class. If a future
  transport clears the flag on error, the check becomes stronger — no action
  needed now. Falsified only by A2 going red.
- **R3 — all-rows-refused reads differently.** The `request-rejected` scenario
  page becomes a table of refused rows rather than one notice — strictly more
  information (which parameters, which code), but a visible change. A4 pins the
  composition; if review judges the notice better for the all-refused case, that
  is a template-only follow-up (a count-based notice), not a mechanism change.
- **R4 — mid-gather reload race.** A reload swapping the plugin between
  iterations can make later names `not_found` → page-level by the rule — honest,
  and identical to today's outcome for the first such refusal. No new exposure.
- **R5 — HTML consumer drift.** Only tests and the htmx innerHTML swap parse the
  partial; the browser-axe lane (`test_browser_axe.py`) covers gross markup
  breakage; `colspan="3"` in a four-column table is valid. Falsified by A1/A4
  substring assertions.

## 9. What this record does not do

No code, no commit, no PR (the increment-designer's boundary). Gates were not
run — nothing was built to gate. The build agent runs the §3 arms RED-first
against this record, then the standard battery
(`ruff check .`, `mypy`, `sync-standards --check`, `--version` smoke, raw-count
pytest) per CLAUDE.md §3.

## Fold amendments — 2026-11-07, from the two refute lanes

Both lanes returned DEFENDED (mechanism, served wire). These are claim-precision corrections,
append-only; no mechanism change. Each names the sentence it supersedes.

**A1 — §2's poll-cost claim is FALSE as written and must not be repeated.** The record says:

> no N×deadline poll cost — the per-parameter classes are fast adapter-envelope answers, not deadlines

That is an unenforced assumption about plugin behaviour, not a property of this change. Nothing
wall-clock-bounds an adapter on the read path: `session.py:1226-1238` mints an *advisory* deadline
and there is no `wait_for`. Measured with an adapter sleeping 0.4s and then answering
`DEVICE_REJECTED`, over 3 parameters: **pre-fix 0.41s** (the first refusal aborts), **post-fix
1.21s**. Corrected statement: per-parameter isolation makes an all-refusing page cost
**N × per-read latency**; a healthy page already costs N × D, so the regression is only against the
aborting behaviour, not against a healthy page.

**A2 — §2 omits a real operational consequence: per-poll dispatch multiplication.** Measured over 5
polls with 3 parameters, an all-refusing bench goes from **1 to 3 reads dispatched per poll**, and
refused events on the unbounded EventBus from **5 to 15**. On serial or FTDI benches each of those is
a wire transaction, re-issued every 2 seconds against a device that keeps saying no. Pre-fix the first
refusal aborted the poll; post-fix every parameter is attempted. This is a consequence of the fix
working as designed, not a defect in it, and it belongs in the record rather than in a reviewer's
notes.

**A3 — §3.2's CSS sentence overstates. The rule is inert.** The record says the refused row is
marked by "one CSS rule … token-referenced, the notice's own precedent". It is token-referenced and
the token **does not exist**: `standalone.css:78` references `--bw-status-critical-text`, and
`grep -rn "^\s*--bw-status-" src/` returns **zero definitions**, so the rule computes to nothing in
every theme and refused rows render in the same colour as healthy rows. This is PRE-EXISTING —
`.notice-refused` at `standalone.css:77` has carried the identical dead pair since the #309 fold.
The marker is textual, so no information is lost and WCAG 1.4.1 holds. **The rule is deliberately
NOT switched to a live token in this slice**: the intended colour measures **5.47:1 / 4.53:1** while
the currently inherited colour measures **14.85:1 / 11.32:1**, so making it live would trade
readability for colour coding. Defining the `--bw-status-*` tokens is its own row.

**A4 — §3.3's "byte-identical" is wrong at the byte level; the right word is content-identical.**
Rendering the pre and post templates through the same Jinja environment with identical context shows
**every row, healthy included, gains one whitespace line** between the row header and the first cell,
because of the `{% if %}`/`{% else %}` newlines. No consumer diffs host-page bytes — the tests are
substring-based and the htmx swap is shape-agnostic — so this is a wording defect, not a wire defect.

**A5 — the guide sentence shipped unconditioned where the mechanism is class-conditioned.** The
landed sentence ("A device can refuse the read of a parameter … and still shows the other rows") is
true only for the rejection vocabulary (`DEVICE_REJECTED`, `INVALID_ARGUMENT`, `UNSUPPORTED`). A
device refusing the same read by `TIMEOUT`, `PROTOCOL_ERROR` or a malformed receipt still blanks the
page, and the page-level error dict (`web.py:903-907`) carries only `{code, message, adapter}` with
**no name field**, so the notice cannot even say which parameter did it. Corrected in
`user_guide/plugin-sdk.qmd` to condition the promise and name the three exceptions.

**A6 — R1 is wider than the record states, and the widening is worth naming.** R1 covers future
`_ADAPTER_CODE_MAP` motion. It should also cover today's plugin-authored vocabulary: the
classification reads the CODE, which the plugin authors, not the CAUSE. A driver that desyncs and
answers `UNSUPPORTED` for every read renders a page of refused rows rather than a page refusal. Host
machinery cannot produce this — every host-side `INVALID_ARGUMENT`/`UNSUPPORTED` raise site is
unreachable from the gather — and each row still shows its refusal verbatim, so nothing looks healthy
that is not. Recorded as the same residual wearing different clothes, not as a new hole.

**What the amendments do NOT change:** the two-code membership, the fail-closed default, the
total enumeration, the `session.connected` guard, or the rendered output. Totality is enforced
structurally — `SeamError.__init__` refuses any code outside the closed seven (`errors.py:69-70`) —
and an unknown adapter code was driven live and fell to `internal_error`.
