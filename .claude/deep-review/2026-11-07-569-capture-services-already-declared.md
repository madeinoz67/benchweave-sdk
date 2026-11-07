# #569 — the capture services surface: DON'T-BUILD (already declared)

**Date:** 2026-11-07
**Issue:** madeinoz67/benchweave#569 — "SDK: the capture services surface is undeclared — the
host duck-checks methods no Protocol names"
**Verdict:** **DON'T-BUILD.** The premise is true as filed and false at `origin/main`. The
declaration, the typed refusal and the guide sentence all landed in PR #221 before this
dispatch. Nothing in this repository should change. The issue should close against that
evidence.

Base: `origin/main` @ `228cd30`, worktree branch `design-569-974ef5d0`.

---

## 1. The claim, tested

The issue's stated mechanism has three factual clauses. Two are false at `origin/main`.

| Issue clause | Status at `228cd30` | Evidence |
|---|---|---|
| "Neither method appears in any Protocol in `src/benchweave_sdk/interfaces.py`" | **FALSE** | `interfaces.py:137` (`configure_capture`) and `interfaces.py:158` (`capture_progress`), both direct members of `class CaptureServices(HostServices, Protocol)` at `interfaces.py:114` |
| "The only implementation is the built-in serial backend (`serial.py:450`, `serial.py:481`)" | **FALSE** | `serial.py:516`/`serial.py:547`, `replay.py:852`, `ftdi.py:1121` — three transport services classes, not one |
| "At capture start the host duck-checks … and refuses … when either is missing" | **TRUE in mechanism, moved and widened** | `seam.py:2451` (`required = ("configure_capture", "capture_progress", "artifact_finalise")`), `seam.py:2465-2478` (`callable(getattr(...))` + typed refusal). The issue's cited `seam.py:1741-1747` is stale; the seam has grown ~700 lines since |

### Why the issue was not wrong when written

- Issue opened `2026-10-28T08:49Z`.
- Declaration commit `bc168e5` authored `2026-10-28T04:43Z` on the #568 branch, but that
  branch reached `main` only in **PR #221, merged `2026-10-29T05:42Z`**.

So at filing time `main` genuinely lacked the declaration. The row was correct then and was
closed substantively by the #568 arc, whose commit message records the owner directive "no
deferrals" — the #569 work rode into #568's PR. The tracker row was never closed with it.

## 2. The duck-typed access sweep (all of it)

Every `getattr`/`hasattr`/`callable(getattr(...))` reach in `src/benchweave_sdk_server/`
against an object the host did not construct itself, or against the services object:

| Attribute | Access | Code path | Declared by a Protocol? |
|---|---|---|---|
| `configure_capture` | `seam.py:2466` | `_op_capture_start` gate | **Yes** — `interfaces.py:137` |
| `capture_progress` | `seam.py:2466` | `_op_capture_start` gate | **Yes** — `interfaces.py:158` |
| `artifact_finalise` | `seam.py:2466` | `_op_capture_start` gate | **Yes** — `interfaces.py:168` |
| `capture_progress` (soft read) | `seam.py:2799` | `_capture_progress` → watchdog + finalise rows | **Yes**; the `getattr` fallback is a belt after the gate, not the contract |
| `link_state` | `seam.py:472` | `_link_state` → `host_info` / `device_get` | **No** — see §5 (out of scope) |
| `open`, `execute` | `session.py:1103-1105` | plugin load gate | **Yes** — `Adapter`, `interfaces.py:445`/`:464` |
| `<factory_name>` | `session.py:868` | module entry-point read | Convention named by the descriptor's `integration.adapter.entry_point`; not a Protocol member by design |
| `port.serial_number` / `vid` / `pid` / `device` | `serial.py:1290,1433,1440,1605`; `seam.py:1305-1346` | enumeration / identity | Third-party pyserial/pyftdi objects, not plugin-provided |

**Claim 1 as a whole: falsified for the capture surface.** The two methods the host demands
at capture start are declared members of `CaptureServices`, and the demanded set is a
subset of the declared set (verified at runtime below).

### Required vs optional — the contract shape

`configure_capture` and `capture_progress` are **required members within `CaptureServices`**,
not optional ones probed with `hasattr`. The *capability* is optional at the base: a host
without capture hands adapters plain `HostServices` (`interfaces.py:127-129`), the same
capability model `LinkControlServices` uses. That is the correct shape — an optional method
the host silently skips would be a different (and wrong) contract, because a capture with no
progress surface is not a degraded capture, it is an undeclared one.

## 3. What already satisfies the acceptance bullets

| #569 acceptance | Evidence | Pinned by |
|---|---|---|
| "A plugin that implements the declared Protocol passes the capture-start check without any duck-typed surprise" | the demanded set is a subset of the declared set; the gate is `callable(getattr(...))`, which any Protocol implementer satisfies | `tests/test_sdk.py:236-252` (declaration); `tests/test_guide_serial_host.py:91-99` (a composed host carries all ten members) |
| "A plugin that omits the methods receives a typed refusal naming the missing protocol member" | `seam.py:2469-2478` — message prefix `capture_services_incomplete:`, `details.reason == "capture_services_incomplete"`, `details.missing == [...]`; code stays the standard's closed vocabulary `unavailable`, the prefix carries the specificity | `tests/server/test_capture_lifecycle.py:181-227` |
| "The guide's capture section names both methods and points at the Protocol declaration" | `user_guide/plugin-sdk.qmd:625` — "The host also demands two host-lifecycle members at capture start: `configure_capture` and `capture_progress`. The `CaptureServices` protocol in `benchweave_sdk.interfaces` declares both beside the artifact methods." Plus a full composition example implementing both at `user_guide/plugin-sdk.qmd:818-831`, and the refusal prefix documented at `:576` | guide text (published docs surface) |

Runtime check on `228cd30` (denominator: the 10 public members of `CaptureServices`):

```
CaptureServices members: artifact_abort, artifact_append, artifact_finalise,
  capture_progress, close_transport, configure_capture, monotonic,
  record_evidence, transfer, utc_now   (count = 10)
seam required set: artifact_finalise, capture_progress, configure_capture
required ⊆ declared: True
```

## 4. Pre-committed acceptance rule (written before the mutations ran)

The build this record would have specified is already in the tree. The rule below is what
that build must satisfy; it is recorded here so the verdict is checkable rather than
asserted. Each arm runs on this worktree; a mutation that fails to redden its arm means the
arm does not pin what it claims.

| Arm | Test | Mutation that MUST redden it | Pre-committed outcome |
|---|---|---|---|
| **A1 — declaration** | `tests/test_sdk.py::test_capture_services_declares_the_capture_lifecycle_members` | rename `configure_capture` → `_configure_capture` in `interfaces.py` | red (`assert None is not None`) |
| **A2 — typed refusal** | `tests/server/test_capture_lifecycle.py::test_capture_start_refuses_without_capture_services` | change the refusal prefix `capture_services_incomplete:` → any other string | red (`startswith` assertion) |
| **A3 — composed host carries the pair** | `tests/test_guide_serial_host.py::test_the_host_carries_all_ten_members_and_the_context_all_of_its_own` | delete either member from `CaptureServices` (drops the count below ten) or from the guide's `Host` example (breaks the subset assert) | red |

All three arms were run **green** on the unmutated tree (3 passed in 3.22s, denominator 3).
A1 and A2 were then mutated: both reddened as specified. Both files were restored with `cp`
backups before the arms were re-run; the tree is clean.

**Kill direction:** if any arm stays green under its mutation, the arm is worthless and the
verdict would need a different proof. None did.

## 5. Residual observations, each with its disposition

- **R1 — `link_state` is genuinely undeclared (`seam.py:472`).** It is a duck-check on the
  services object with no Protocol member anywhere. **Disposition: ACCEPT, out of #569's
  scope.** It is not the capture surface, it is host-owned (the serial transport builds those
  services; a plugin never composes them), and the fallback is `None` — a declared absence,
  not a refusal that could surprise an implementer. If the interface corpus ever grows a
  `LinkStateServices` capability it belongs there; do not attach it to `CaptureServices`.
- **R2 — the seam's local `_CaptureCapable` mirror (`seam.py:96-111`) drifts from the SDK
  Protocol by omission** (it names 4 of the 10 members). It exists only as a `cast` target
  for the capture path, and the cast cannot detect drift. **Disposition: ACCEPT.** mypy does
  not check a `cast`, but the runtime gate at `:2465` is the actual contract and A2 pins it.
  Closing the gap would need a typed narrowing refactor with no behaviour change — not worth
  a PR on its own; note it if that region is touched for another reason.
- **R3 — the host polls `capture_progress` and coalesces rows at `_PROGRESS_WINDOW_S`
  (`seam.py:163-165`, `:3834`), and the Protocol docstring does not state the polling loop.**
  **Disposition: ACCEPT.** The implementer-facing contract is complete: return staged bytes,
  zero for an unknown id. The cadence is a host scheduling constant that may change without
  notice, so pinning it in the Protocol would create a claim the host is free to break. If
  the maintainer wants the loop narrated, a sentence belongs in the guide, not the Protocol,
  and it is not worth a design record.

None of R1-R3 reopens #569: its three acceptance bullets are met and pinned.

## 6. Cross-surface impact of the (non-)change

**None, because there is no change.** For the record, the surfaces that moved when the work
landed, and what a future Protocol-member change here would cost:

| Surface | Involved in the landed fix? | A new member would cost |
|---|---|---|
| `interfaces.py` (Protocol) | Yes — `bc168e5` | Tier 3 (two refute lanes) |
| `seam.py` refusal path | Yes — typed refusal | Tier 3 |
| Vendored standards tree / `standards-lock.json` | **No** — `interfaces.py` is hand-written SDK code, not generated; `sync-standards --check` is untouched | Not applicable |
| Scaffold output / `AI-GUIDE` | **No** — `scaffold.py` and `conformance.py` contain no reference to these members (grep: zero hits). No SRF-1 change | SRF-1 if `scaffold.py` ever emits a services skeleton — it does not today |
| Guide | Yes — `user_guide/plugin-sdk.qmd:576, 625, 818-831` | Docs leg |
| Main-repository gateway corpus | **No** — nothing normative changed; no re-sync, no version increment | Only if the canonical interface corpus names the member set |
| Main-repo behavioural suite | **No** — the three-way agreement test's documented-gap rows are unchanged | Would need a row |

## 7. Risks of this verdict

- **The row could be partially open in a way this sweep missed.** Falsifier: a duck-typed
  access on a *plugin-composed* services object outside the files swept, or a services
  member the host calls unconditionally with no `getattr`. The sweep covered
  `seam.py`, `session.py`, `serial.py`, `replay.py`, `ftdi.py`, `lifecycle.py`; it did not
  read `web.py`, `mcp.py`, `library.py`, `retention.py`, `dataset_admission.py`,
  `binding.py`, `analysis.py`, `plots.py`, `scenarios.py`, `shim.py` line by line.
  Confidence that none of them duck-checks the capture surface: high — the capture gate is
  the only entry point, and the other modules consume `Seam.call`, not the services object.
- **A contributor reading only the issue would redo this work.** Mitigation: close #569 with
  this record's evidence and a pointer to PR #221 rather than leaving it open.

## 8. What was checked, and by whose measurement

All measurements are mine, taken on this worktree at `228cd30` on 2026-11-07:

- 3/3 acceptance arms green unmutated; 2/2 mutated arms red; files restored, `git status`
  clean.
- Member-set runtime probe: 10 declared members, 3 required, subset holds.
- Grep sweep over the server modules listed in §7.

Not checked: a live gateway run (no gateway checkout in this repository by design — PKG-1),
and the main-repo three-way agreement test (main-side; nothing here changes its inputs).
