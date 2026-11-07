# Gateway #568 + #570 — "provider kind": split decision against the delivered tree, and the one remaining slice

**Date:** 2026-11-08
**Scope:** settle whether gateway issues #568 (live provider execution) and #570
(scaffold + mock double for provider kinds) are one increment or two, which lands
first, and design what still remains — against the code at `origin/main`, not
against the issue prose.
**Verdict up front:** **the design question is overtaken by the tree.** Both
issues' primary scopes are DELIVERED and green at `origin/main` `7671e6c`
(PR #221 `9796d84` and the #570 commits riding the same branch). They were ONE
delivery increment spanning two issue numbers — the #570 record itself is the
amendment of record on top of #568's (its §7 narrows two landed #568 arms).
Re-building any of it is wrong. What remains buildable is exactly one small
slice — **the typed-refusal row of #568's acceptance** (acceptance bullet 4):
three bare-prose §8.1 grammar refusals that survive at HEAD
(`serial.py:838`, `transport.py:407`, `replay.py:1078`). That slice is designed
in §4. Everything else that remains open is bench-gated or gateway-side and is
DON'T-BUILD here, each row carrying its recorded home and reopen trigger (§5).

**Triage:** PUBLIC. The tracker issues name a real instrument the owner holds;
this record does not — "the reference bit-bang instrument" throughout, invented
fixture names only. File:line anchors and public issue numbers only. Engineering
register (internal design record; the ASD-STE100 register does not apply).

---

## 0. Grounding — every anchor re-verified at `origin/main` = `7671e6c`

The dispatch brief and both issue bodies were written against `main` at
`39043cc` (pre-#568-build). Every anchor was re-read this session at `7671e6c`
(v0.24.0). Table: brief claim → verdict at HEAD.

| Brief / issue claim | Verdict at `7671e6c` | Anchor |
|---|---|---|
| `cli.py`'s `new` asks directory, package, UI only | **STALE** — `new` also takes `--provider-transport` | `src/benchweave_sdk/cli.py:73-80` |
| `copier.yml` asks four questions, none about transport | **STALE** — five questions; `provider_transport` (row f) | `copier.yml:19-21` |
| Template hard-renders `transport: {type: "serial"}` | **STALE** — conditional: provider arm renders `type: "custom"` + the provider pin (banked 1.1.0 contract, sha256); serial arm byte-unchanged | `template/src/{{package_name}}/descriptor.json.jinja:29-54` |
| Mock accepts only `stream_exchange`/`send_receive` | **STALE** — `_DIALECTS` has the third member `provider` ("added by issue #570") | `src/benchweave_sdk_server/session.py:182`, selector `:696-729` |
| Live backend refuses every kind outside the three stream kinds | **TRUE but no longer the whole story** — the refusal stands (see next row), and a THIRD transport (`ftdi.py`, 2136 lines, "the #568 live FTDI provider transport") dispatches provider kinds against real hardware through an injectable driver protocol | `src/benchweave_sdk_server/ftdi.py:1-46` |
| `serial.py:729` / `transport.py:378` unprefixed refusals | **TRUE at drifted lines** — `serial.py:836-838`, `transport.py:405-407`, plus a third instance the issue did not name: `replay.py:1078`. All three raise bare prose `not a section 8.1 stream transaction: [...]` | grep, this session |
| Replay is the only provider-kind lane; rehearsal needs a journal | **STALE** — `provider` dialect rehearses from a grammar-validated `vectors.json` on `--transport mock`; the shipped `ScriptedFtdiDriver` double proves the executor ladder one boundary down | `session.py:182`, `ftdi.py:14-32` |

Delivery evidence, from git this session: PR #221 `feat/568-live-provider-transport`
merged at `9796d84` with a 20+-commit refute/fold wave (rows a/c/e landed by owner
expansion 2026-10-28); #570's dialect landed at `881946c` + `8569cb0` on the same
branch. Suite health at HEAD, this lane's runs, raw counts from the unfiltered
output: `tests/server/test_ftdi.py + test_mock_provider.py +
test_mock_bytestream_host.py + test_replay.py + test_ftdi_selector.py` —
**203 passed**; `tests/test_scaffold_copier.py` — **16 passed**. The guide
carries #570 scope 3 (which rehearsal to reach for: `user_guide/plugin-sdk.qmd:510`;
the scaffold provider arm at `:366`) and states honestly "The live-device
acceptance is not complete" (`:582`).

Gortex was unavailable to this subagent (daemon checkout-discovery busy, no graph
access granted); all source reads fell back to `Read` on this worktree. Bash was
used for git and pytest only.

---

## 1. The shared model, from the code

A provider-kind execution path on this host is: **one pinned contract, compiled
once, with a per-mode dispatch home and a hard grammar gate at every home that
does not serve it.** The contract bytes are pinned three ways (banked
`src/benchweave_sdk/providers/ftdi-control-{1.0.0,1.1.0}.json`, the scaffold
template's copy, the fixture's copy — cross-pinned byte-equal), digest-verified
against the banked instance (the anti-laundering bind: a feature-id prefix alone
does not admit a lookalike), and compiled to a grammar of kinds/ops
(`replay.py`'s `_grammar`). Each transport mode then owns its dispatch:
replay serves journal rows through the compiled grammar; the ftdi transport
serves BOTH families against a real device through the injectable
`FtdiDriver` protocol (provider kinds via control calls, §8.1 stream kinds via
the data pipe — `ftdi.py`'s transfer grafts replay's dispatch in front of the
inherited serial ladder); the mock's `provider` dialect serves a
grammar-validated vectors corpus at the transaction boundary. The boundary
between scripted rehearsal and live execution is the #564 refute wave's F2
finding, kept as a constraint: **one transport, one grammar — a mode refuses
what it does not serve, and those refusals ARE the mode boundary.** A serial
transport told to replay refuses; the stream dialects of the mock refuse
provider kinds; the ftdi transport refuses an unpinned (stream) plugin at
connect (`live_provider_plugin_unpinned:`, `ftdi.py:1362-1371`). That is why
the three surviving §8.1 grammar refusals are load-bearing — they are the
negative control B1 of the #568 record — and also why their bare-prose form is
the one remaining defect: the seam maps a transfer-time `ValueError` to
`invalid_request` with `str(exc)` verbatim (`seam.py:1055-1057` and siblings),
so the boundary refusal reaches the wire as prose no caller can machine-match
(STD-4's exact rationale, in the issue's own words: "no caller can match on it
and no test can pin it").

---

## 2. The split decision, and the order

**They are two surfaces of one root, and they were delivered as ONE increment
spanning two issue numbers — the order already happened.** The owner's
2026-10-28 ruling (issue #568 comments) settled the architecture question the
issues posed: option 2, a third transport; mock rehearsal stays in #568; the
scaffold variant becomes #570. The delivery then ran on one branch
(`feat/568-live-provider-transport`) through one PR (#221), with the #570
commits riding the same tip and the #570 design record explicitly amending the
#568 record (its §7: "the #568 record is frozen history; this record's §1 and
§7 are the amendment of record"). Execution-first ordering was correct and is
already embodied in the tree: the mock dialect compiles against the same
`_grammar` the executor dispatches through, and the scaffold's provider arm
emits a corpus that only the dialect can serve — authoring (#570) is
downstream of the execution model (#568) by construction.

**What remains splits cleanly by buildability, and only one piece is
designable here:**

1. **The typed-refusal row** (#568 acceptance bullet 4) — buildable, hardware-
   free, designed in §4. Lands first (it is the only thing that can).
2. **The live-device acceptance leg** (#568 acceptance bullet 1) — owner-
   deferred twice with an explicit closure condition ("one real-bench run
   through `serve --transport ftdi`, its evidence recorded then"). No
   hardware-free arm can close it; designing it here would be motion without
   a measurement. **DON'T-BUILD in this repo's slices.**
3. Gateway-side commissioned runtime (#568 row d), MPSSE shapes (row g), the
   not-wanted baud-renegotiation posture (row h), #570's D1/D2 bounds — all
   carry recorded homes and reopen triggers in the landed records. Leave them.

---

## 3. Why the delivered scope must not be re-touched (SRF-1 enumeration)

The remaining slice touches no scaffold surface. For the record, the golden
fixtures and shape tests any scaffold change would move — none of which this
design touches: `tests/fixtures/scaffold_expected/{base,ui,provider}` (three
arms), `tests/test_scaffold_copier.py` (16 arms incl. the generated-workflow
and per-arm lint-set pins), `tests/test_agent_assets.py` (R-5b factual-
reconciliation, permanent planted-violation arms), `tests/test_standalone_dev_loop.py`
(installed-wheel scaffold), the CI generated-workflow step (3 arms × 2 jobs),
and the main-side pins named in TWO-1 (`tests/sdk/test_plugin_developer_skill_content.py`,
`tests/sdk/test_scaffold_skills.py`, `tests/sdk/test_presentation_cli.py`).
The serial arm's byte-identity is unchanged by §4 because §4 edits only
refusal strings in `benchweave_sdk_server`.

---

## 4. The minimal first slice — prefix the three §8.1 grammar refusals

**Mechanism.** Pure prepend at three raise sites; no logic, no signature, no
behavior change:

```
unsupported_transaction_kind: not a section 8.1 stream transaction: {sorted(transaction)}
```

- `src/benchweave_sdk_server/serial.py:838` (the live serial backend's grammar
  gate; the ftdi transport's fallthrough inherits it, since `ftdi.transfer`
  delegates non-provider kinds to `super().transfer`).
- `src/benchweave_sdk_server/transport.py:407` (`ByteStreamMockHost` — the
  mock's stream dialects).
- `src/benchweave_sdk_server/replay.py:1078` (the replay transport's serve-time
  gate; the loader-side sibling at `replay.py:463` is already prefixed
  `replay_journal_kind:` and is NOT touched).

One name for one defect class — "this transport does not serve that
transaction kind" — at every site that raises it. A pure prepend is provably
churn-free: every existing `pytest.raises(match=...)` arm is a regex SEARCH
against a substring that remains byte-present, so all seven existing arms
(`tests/server/test_replay.py:236`, `tests/server/test_mock_provider.py:182`,
`tests/server/test_mock_bytestream_host.py:188,192`, `tests/server/test_ftdi.py:175,189,727`)
stay green with zero edits. Verified this session: no other matcher on the old
text exists in this repository (grep over `src/` and `tests/` = the four
sites + seven arms above), and none in the gateway checkout's `src/` or
`tests/` (grep this session, zero matches).

**Precedent.** The PR-4 fold of 2026-11-07 did exactly this move one lane over:
"prefix the bare `capture_series` format refusal" (`standalone_capture_format_unknown:`
— the fold adjudication's one-name-for-both-doors ruling). STD-4's own text is
the standing rule; this slice is the same repair applied to the transport
grammar gate. No new architecture.

**Docs legs in the slice** (the F6 fold precedent: reachable prefixes get
named in the guide): one sentence per transport section in
`user_guide/plugin-sdk.qmd` naming `unsupported_transaction_kind:` as the
refusal an unserved transaction kind meets on serial/mock/replay; and the
STD-4 list in `docs/internal/invariants.md` gains the prefix (one line).

**Deferrals, each with a home and an observable reopen trigger:**

| Deferred | Home | Reopen trigger |
|---|---|---|
| Splitting the prefix per site (e.g. a mock-specific name) | this record | a caller demonstrates a need to distinguish the mock's grammar refusal from the live backend's by machine (none exists today; the seam maps both to `invalid_request`) |
| A wire-level arm asserting the prefix rides the seam's `invalid_request` reason | this record | any change to the seam's ValueError mapping at `seam.py:1055-1057` (the unit arms pin the raise; the mapping is generic and already pinned) |
| The live-device leg, rows d/g/h, #570 D1/D2 | the landed #568/#570 records' own tables | their recorded triggers (unchanged) |

**CI cost:** negligible — three unit arms added to existing files; no new job,
dependency, or fixture.

---

## 5. Pre-committed acceptance rule

Written before any measurement of the post-change tree ran. All arms
deterministic, hardware-free; all measurements are this lane's, on this
machine, in this worktree.

**RED (must fail at HEAD `7671e6c`, before the edit):** three new arms, one per
site, each asserting the prefixed form —
`pytest.raises(ValueError, match="unsupported_transaction_kind:")` with the
same driving transactions the neighboring substring arms already use:
- R-1 the live serial backend's gate, direct (home: `tests/server/test_serial_link.py`,
  beside the ladder tests — note the serial site is today pinned only through
  ftdi's inheritance; this arm pins it directly for the first time);
- R-2 `ByteStreamMockHost` (home: `tests/server/test_mock_bytestream_host.py`,
  beside `:188`);
- R-3 the replay transport's serve-time gate (home: `tests/server/test_replay.py`,
  beside `:236`).
All three fail at HEAD because the prefix does not exist.

**GREEN (must pass after the edit):**
- G-1 the three RED arms pass;
- G-2 **the no-churn control**: the five existing-arm files run FULL, zero
  edits, all green — `test_replay.py`, `test_mock_provider.py`,
  `test_mock_bytestream_host.py`, `test_ftdi.py`, `test_ftdi_selector.py`
  (expected: the 203 of this session's baseline, +3);
- G-3 the mutation control: revert the prefix at any one site (cp backup, not
  stash — shared stash stack) → that site's RED-turned-GREEN arm reddens again;
  restore → green (the mechanism is the prefix and nothing else);
- G-4 gates: `uv run ruff check .`, `uv run mypy` (strict), `uv run
  benchweave-sdk sync-standards --check`, `benchweave-sdk --version` — all
  green, counts read from raw output.

**Ship direction:** R-1..3 red at HEAD; G-1..4 all green with the counts above.
**Kill direction:** any existing arm needs its match string edited (the prepend
was not pure — the design's churn-free claim is false and the slice stops for
re-design), or any gate reddens (a prefix is not a behavior change; a red gate
means it was).
**Underpowered direction:** if G-2 is run on a `-k` subset instead of the five
files in full, the no-churn claim is unproven rather than passed — the full
files are the rule. Cross-repo: if the gateway's `tests/sdk` suite is not run
main-side at PR time, the no-main-side-matcher claim (verified by grep once,
this session) is untested against future drift — the PR body names
`uv run pytest tests/sdk` from the gateway checkout as the pairing leg, per
TWO-1 and the drift-and-obligations CI map.

---

## 6. Invariant and cross-surface impact

- **STD-4** — gains one prefix, `unsupported_transaction_kind:`, at three
  sites; the invariants list gains the line. The #568 record's B1 control is
  strengthened, not weakened: its arms still pass (substring), and the
  boundary refusal becomes machine-matchable as the issue demanded.
- **SRF-1** — no motion. No template byte, no golden fixture, no scaffold
  test changes (enumerated in §3). The serial arm stays byte-identical.
- **PKG-1** — no parent-path reads; everything in-tree.
- **TWO-1** — lands here first, pushed, then the pointer commit main-side;
  the PR notes the single-issue-stream convention (no SDK-side issue).
- **Tier:** normal review tier — no vendored-tree, lock, or standards motion.

## 7. Top risks, first-ranked, each with its falsifier

1. **The B1 control's meaning shifts** (the #568 record treats these refusals
   as its negative control; a reader may read the prefix as the control
   moving). Falsifier: G-2 runs the B1 arms specifically; the record note in
   the PR body states the control now matches on the prefix.
2. **A hidden matcher on the exact old text breaks.** Falsified this session
   for both repos by grep (zero matches outside the enumerated arms); the
   standing control is the main-side `tests/sdk` run at PR time.
3. **Prefix-name regret** (`unsupported_transaction_kind:` is broad; a future
   non-§8.1 grammar might want it). Falsifier: it fires only at the three
   §8.1 grammar gates, and the guide sentence scopes it there; a second
   meaning appearing would be a STD-4 review catch, not silent.

## 8. Could not verify, stated plainly

- The daemon's graph tools were unavailable to this subagent (checkout
  discovery busy) — all reads were `Read` on the worktree, per the dispatch's
  fallback protocol.
- The gateway checkout was grepped read-only for matchers on the old text
  (none found); its full suite was NOT run from here, and the gateway
  checkout's own branch state was not audited — the pairing leg is the PR's.
- The live-device leg's feasibility on a real bench is outside this
  repository's proof by design (owner-deferred; guide states it incomplete).
