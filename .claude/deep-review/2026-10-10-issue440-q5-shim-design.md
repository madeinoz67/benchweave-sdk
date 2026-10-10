# Issue #440 — the stdio MCP shim (Q5 ruled option 2): design record

**Date:** 2026-10-10
**Issue:** madeinoz67/benchweave#440 (carrier; PRD 11 §8 Q5, ruled option 2, owner word 2026-10-10)
**Verdict:** BUILD — one slice, SDK-repo only, no gateway bytes
**Status:** design record — the build dispatch follows review of this document
**Grounded on:** benchweave-sdk `origin/main` @ `16d53e2`; every code claim below was read at that tree. Pre-flight clean: `git fetch origin` shows no remote branch touching `src/benchweave_sdk_server/mcp.py`, `cli.py`'s `mcp` command, or `tests/server/test_mcp*` (active sibling lanes are `fix/issue427-vendored-tamper` and docs lanes; disjoint paths).

---

## 0. Premise corrections the code forced (read this first)

1. **The existing stdio entry is the full in-process host, not a reduced mock.**
   `benchweave-sdk-server mcp <project>` (`src/benchweave_sdk_server/cli.py:684-721`)
   builds a complete `StandaloneSeam` via `_build_seam(project, unattended=…)` and runs
   `build_mcp(seam, authoring=…)` over stdio — every catalogue operation, the same
   refusal model, capture support, and the NFR-O1 settle-on-exit. The transport defaults
   to mock (no `--transport` flag exists on this command), which is why it reads as "a
   mock seam": the seam is real, the transport is the scripted mock. This IS PRD 11
   SW-03's option-1 shape, shipped. The ruling re-shapes this entry into the shim and
   keeps exactly this body as the disclosed fallback.
2. **Who uses it today: the README paragraph and nothing else in-tree.**
   `README.md:219` carries the claim ("`benchweave-sdk-server mcp <project>` runs the
   same MCP server over stdio, with no HTTP listener"); the wheel METADATA mirrors the
   README (derived, moves with it). The user guide never cites the command (verified by
   text search across `user_guide/` and `docs/`); the agent-asset template does not cite
   it (R-5b reconciliation unaffected). Tests pin two properties:
   `tests/server/test_cli.py:73` (builds the full tool set without binding a port) and
   `:143` (graceful refusal without the `[server]` extra). No `.mcp.json` example exists
   in-tree — the shim's `.mcp.json` shape is new documentation, not a migration.
3. **The fork's two-writer hazard is already named in-tree as this exact pair.**
   `src/benchweave_sdk_server/library.py`'s module docstring: "A lockfile in the capture
   root (`library.lock`, `O_CREAT | O_EXCL` with a JSON pid payload) refuses a second
   host process over the same root — the **`serve` and stdio-`mcp` entry points must not
   become the fork's two-writers hazard**." The lock is the existing mitigation for the
   hazard this shim exists to remove structurally. The design keeps the lock (defense in
   depth) and removes the second-writer *path*: in proxy mode the shim opens no capture
   root at all.
4. **Foreground `serve` is invisible to the supervision family — by design.**
   The pidfile and `<bindings>.tokens` are written only under `--supervised`
   (`cli.py:506-537`); a foreground serve prints the bearer to stdout and writes no
   family sidecars. A foreground host therefore cannot be discovered *or* authenticated
   to (its token is unrecoverable). The discovery lattice below treats this class
   explicitly instead of pretending it away.
5. **fastmcp ships the proxy mechanism.** `fastmcp/server/providers/proxy.py`
   ("ProxyProvider … proxies components from a remote MCP server via a client factory")
   is maintained library machinery in the same dependency the host already serves
   through. The shim composes it; it does not invent frame-level stdio↔HTTP plumbing.
   Version honesty: the lock pins `fastmcp==4.0.11` (`uv.lock`; main merged the bump at
   `16d53e2`) while the local venv still holds 4.0.3 — the composition is verified
   against 4.0.11 at build time by arm SH0, and the design's plan B (§2.6) does not
   depend on provider internals.
6. **The MCP-over-HTTP auth contract is exact.** `McpGuard`
   (`src/benchweave_sdk_server/security.py:254-278`) requires
   `Authorization: Bearer <per-launch token>` on every `/mcp` request and refuses
   non-loopback `Origin` when one is sent. A stdio client sends no `Origin`, so the
   bearer alone is the shim's credential. The token reaches the started-mode host
   through the 0600 `<bindings>.tokens` sibling (`lifecycle.deliver_tokens`,
   `lifecycle.py:750-783`), whose payload carries `pid`, `bearer_token`, `url`, and
   `written_wall` — url and credential in one file, written BEFORE the pidfile (the
   S7 ordering: readiness implies deliverability).

## 1. Why (one paragraph)

PRD 11 §8 Q5, ruled 2026-10-10: the stdio entry is a shim that proxies to the running
HTTP host; UI and agent share one session; option 1 (the in-process host, today's `mcp`
command) stays the fallback when no host runs, with the disclosed cost that no browser
can attach in fallback mode. The safety property is ONE session owner per device — the
shim holds no state and opens no store. The failure mode being killed is the reference
fork's shape: two processes both writing the same capture root (the fork shared SQLite;
the SDK's `library.lock` already refuses that pair at the root — this slice removes the
path instead of relying on the lock to catch it).

## 2. The mechanism

### 2.1 The command surface (open call 4)

The entry point is the existing console script and subcommand — **`benchweave-sdk-server
mcp <project> [--bindings <doc>] [--authoring] [--unattended]`** — reshaped in place.
Existing `.mcp.json` entries that already invoke this shape upgrade with no migration.
`<project>` remains required: the fallback needs it, and it names which plugin a
fallback would serve.

`--bindings` joins the command with the **family-anchor meaning** it already carries on
`start`/`stop`/`restart`/`status` ("the bindings document the supervision family anchors
beside") — NOT the serial-binding-document meaning it has on `serve` (drift-2's one
flag one meaning is per-command; the lifecycle verbs are the precedent the shim joins).
The shim never passes it into `_build_seam`. Default resolution unchanged:
`--bindings` → `BENCHWEAVE_STANDALONE_BINDINGS` → `device-bindings.json` under the
working directory (`binding.bindings_path`, resolved once via
`cli._effective_bindings_path`).

### 2.2 Discovery (open call 2)

A new module `src/benchweave_sdk_server/shim.py` owns a pure-read function:

```
discover(bindings: Path) -> Discovery
# Discovery ∈
#   ProxyTarget(url, bearer, pid)            — proxy
#   NoHost(reason ∈ {absent, dead})          — fallback, disclosed
#   Refuse(prefix, detail, action)           — typed refusal, exit non-zero
```

The lattice, in order (all reads; the shim never writes, steals, or clears any family
file — `stop`/`status` own cleanup):

1. `lifecycle.verify_identity(bindings)` — the landed twin lattice
   (`lifecycle.py:311-339`): `ours` requires probe + start-ticks match.
2. verdict `absent` or `dead` → **fallback** (no host holds the family).
3. verdict `unknown` or `not-ours` → **refuse** typed
   (`standalone_supervision_unknown:`), conservative, mirroring `lifecycle.start`'s
   own posture on `unknown` — the shim neither proxies nor forks beside a process it
   cannot verify. The refusal names `benchweave-sdk-server status` as the resolving
   action.
4. verdict `ours` → read `<bindings>.tokens`. Usable iff: file parses, `bearer_token`
   and `url` present, and `tokens.pid == pidfile.pid`. Usable → **proxy**. Unusable
   (absent, unreadable — including a 0600 file owned by another user — stale pid, or
   payload-incomplete) → **refuse** typed (`standalone_host_unproxyable:`): a live host
   IS the family's owner; falling back beside it is the fork's shape, so the shim
   refuses and names the action ("stop/restart the host under the reading user:
   `benchweave-sdk-server stop` then `start`"). The S7 tokens-before-pidfile ordering
   makes tokens-absent-while-ours a real anomaly worth refusing on, not a race to
   retry.

The `status` VERB is not consulted — the shim calls the same functions `status` calls.
Both sources (tokens file and pidfile lattice) must agree; there is no precedence
between them because the combined predicate is a conjunction.

### 2.3 The fork guard (open call 3, second half)

Before ANY fallback engages, the shim resolves the capture root the fallback would use
(`BENCHWEAVE_CAPTURE_DIR` → `captures/` under cwd — the same resolution the seam
applies, read here without opening anything) and reads `<root>/library.lock` if present
(reusing `library`'s lock-name constant and its pid payload reader; a small read-only
helper `library.read_lock(root)` is added beside the writer — it parses and probes,
never steals). A LIVE foreign pid in that lock → **refuse** typed
(`standalone_capture_root_held:` naming the pid and the action: run a supervised host
with `benchweave-sdk-server start`, or stop the foreground host holding the root). This
is what prevents a browser-owning operator from being silently forked into a second
host: the two classes of operator host the shim cannot proxy to (foreground serve; a
started host whose tokens are unreadable) are exactly the classes that DO hold the
capture root once they capture — and the ones that never captured hold nothing the
fallback could corrupt (§2.7 residual names this honestly).

### 2.4 Proxy mode

`build_shim_proxy(target)` constructs the stdio server as the host's own MCP machinery
composed over a remote client:

- `FastMCP("benchweave-sdk-server", instructions=<proxy marker text>)` — serverInfo
  keeps the distribution name (the #309 F1 rule: the name is wire-visible and names the
  distribution it rides, not the transport).
- A `ProxyProvider` whose client factory builds `Client` over the streamable-HTTP
  transport to `target.url` with the per-launch bearer in the `Authorization` header —
  the one header `McpGuard` requires; no other credential channel exists or is needed
  (stdio sends no `Origin`).
- The tool set, schemas, descriptions, and call results are the HOST's, forwarded —
  the shim adds no tool, subtracts none, and pins nothing itself (the host's catalogue
  pin, `mcp.py::_pin_all`, already governs what `/mcp` serves; the proxy forwards it).
- Plan B (if the 4.0.11 provider composition drops or mangles pinned schemas — SH0
  falsifies): a thin forwarding registrar in the `mcp.py` shape — handlers that
  `await client.call_tool(...)` and a pin pass whose schemas are read from the host's
  `tools/list` instead of the local catalogue. Same wire behavior; no provider
  internals. Frame-level stdio↔HTTP plumbing is NOT an option at any stage.

The shim process holds one client connection for its lifetime and closes it on stdio
shutdown. No pidfile, no journal row, no tokens write, no capture-root open, no
bindings write — the §5 declaration's "no store, no runs" for the SDK surface extends
to the shim unchanged (the shim is a family CONSUMER: tokens file + lattice + typed
refusals are the standard's affordances applied, not extended).

### 2.5 Fallback mode (open call 1 and 3, first half)

**No auto-start.** The shim never spawns a host. Reasons, in weight order:

- **A04 (promotion):** an MCP client connection is an ordinary operation; a `.mcp.json`
  entry loads at agent startup. Auto-start would let that ordinary event mint a
  detached, supervised, long-lived host process as a side effect — the
  client-silent-promotion shape the constitution refuses. `start` is an operator
  affordance (the §5 declaration grants it to the CLI, gated by its pre-spawn checks);
  the shim claiming it would be the weakest caller in the system holding the strongest
  lever.
- **A06 (evidence/ownership):** an agent-minted host has no operator to own its
  lifetime — it would outlive the agent session holding the port, the family, and
  possibly a bound serial endpoint, with nobody accountable for stopping it.
- **The ruling itself:** option 1 is the ruled fallback when no host runs. Auto-start
  would re-open the exact question the owner closed.

Fallback is therefore: verdict `absent`/`dead` AND the fork guard clean → run today's
in-process body verbatim (`_build_seam(project, unattended=…)` over the mock transport,
`build_mcp`, `run()`, the NFR-O1 settle-on-exit finally block). One property changes —
disclosure:

- **stderr line at startup** (stderr, never stdout — stdout is the protocol channel):
  `benchweave-sdk-server: no running host beside <bindings> (verdict: <v>); serving
  the in-process fallback — no browser can attach to this session`.
- **On the wire:** the shim's `instructions` carry a mode sentence. Proxy mode:
  "stdio shim: proxying to the running host at <url> (pid <n>); the browser session
  and this agent share one host." Fallback: "in-process fallback host: no other
  surface can attach; no browser session shares this process." The two marker
  sentences are pinned by a literal test (SH9) and are mutually exclusive. `host_info`
  CANNOT carry this marker: the host is shared with the browser in proxy mode and its
  bytes are the parity subject — identical whether the agent arrives direct or through
  the shim. The initialize-level marker is the only layer the shim owns in both modes.

**Serial capability arrives through the proxy for free:** a discovered host on serial
transport serves the agent identically (the HTTP host does the I/O). The fallback stays
mock-only — today's behavior, unchanged, disclosed by the marker (the fallback text
names the scripted mock transport).

### 2.6 Authoring flags in proxy mode

`--authoring`/`--unattended` keep their fallback meaning. In proxy mode they become
requests the host answers: if the host was not started `--authoring`, its tool list
simply lacks the authoring tools (NFR-S8's absent-not-refused posture) and the shim
prints one stderr disclosure ("authoring requested; the running host does not serve
authoring tools — restart it with --authoring"). The connection is not refused: a
degraded session beats no session, loudly. `--unattended` without `--authoring`
remains the existing usage error.

### 2.7 Disclosed residual (named, not hidden)

A foreground `serve` that (a) never captured — so no `library.lock` exists — and
(b) binds a non-default port is undetectable by any in-tree mechanism: its token went
to stdout only and it holds no family sidecar. Against such a host the shim falls back
with full disclosure. What bounds the harm: the fallback's marker tells the agent it is
NOT on the operator's session (it can never mistake the fallback for the shared host);
the mock fallback cannot touch the foreground host's serial port or capture root; and
the serial fallback case does not exist (fallback is mock-only). A port-probe of the
default port was considered and left out: it detects only default-port hosts, adds a
false-positive class (any loopback listener), and the residual it would close is
already disclosed. An adversary lane is invited to disagree.

## 3. The minimal first slice

**Ships:** `shim.py` (discovery + fork guard + proxy builder + marker texts), the `mcp`
command reshape in `cli.py` (flags + the three-outcome body), `library.read_lock`,
`tests/server/test_mcp_shim.py` (the §6 bank), the README paragraph rewrite, and a
short user-guide subsection beside the serve/prune content (the `.mcp.json` example,
both modes, the one-session property).

**Defers (each with its landing place):**

| # | Deferral | Lands where |
|---|---|---|
| D1 | Server→client notification forwarding through the proxy (host log messages to the agent's stdio client) | A follow-up slice on #440 if agent sessions show a need; the host's `events_get` tool already covers event observation |
| D2 | `--transport serial` on the FALLBACK (a serial in-process stdio host) | Never, unless a hardware-authoring use case surfaces — proxy mode already serves serial; reopening this re-opens the two-writer class |
| D3 | An auto-start flag (`--start-if-absent`) | Ruled out (§2.5); reopened only by the owner, with the A04 argument answered |
| D4 | A typed refusal when `--authoring` is requested in proxy mode (today: loud stderr degrade) | #440 follow-up if agents trip on the silent-list shape; the degrade is tested either way |
| D5 | PRD 11 SW-03's sentence rewrite ("runs the same app in-process" → the shim-with-fallback shape) | The build PR's gateway-side docs amendment (the §8 Q5 Ruled paragraph and the §9 I-table amendment already carry the ruling; SW-03's own text is the stale remainder) |
| D6 | Gateway pointer commit + TWO-1 walk | The build train (never this design commit) |
| D7 | Shim-specific `doctor` hooks (inc4's surface may deepen the refusal texts) | #422 increment 4 |

## 4. Precedent (extend, don't invent)

- **The supervision twins** (`lifecycle.py`, #422 inc3, landed): the shim consumes
  `verify_identity`, the tokens file, and the family resolver exactly as `stop`/`status`
  do — zero new supervision semantics, one new consumer.
- **The graceful-degrade guard** (`_require_server_extra`): the shim's imports ride the
  same lazy-import discipline so a default install keeps a typed refusal, not a
  traceback (pinned by the existing `test_mcp_without_the_server_extra_refuses_gracefully`,
  extended to the discovery path).
- **`library.lock`**: the fork guard reuses the lock's own payload reader and probe
  semantics; the guard adds a read, not a rule.
- **fastmcp composition**: the host already serves MCP by composing FastMCP in-process
  (`web.py` mounts it at `/mcp`; `mcp.py` pins schemas over it). The proxy is the same
  library's client+provider composition — no new protocol code.
- **The in-process fallback**: today's `mcp` body, verbatim — the oldest precedent in
  this slice is the thing being kept.

## 5. Invariant and drift impacts

- **STD-4 (refusal prefixes are the contract): EXTENDED by amendment** — three new
  machine-matchable prefixes enter the enumerated surface:
  `standalone_supervision_unknown:`, `standalone_host_unproxyable:`,
  `standalone_capture_root_held:`. Each names its resolving action in the message.
  The amendment lists them in the invariant's enumerated set at the build PR.
- **New invariant row (the maintainer assigns the final ID at landing, per the SRF-4
  precedent):** *the stdio MCP entry holds no state and never spawns: it proxies to
  the verified running host, or serves the disclosed in-process fallback, or refuses
  typed — it writes no pidfile, no journal row, no tokens file, no bindings byte, and
  no capture-root byte, and a live host it cannot authenticate to is a refusal, never
  a fallback.* Anchored on `shim.py::discover` + the `mcp` command body; pinned by
  SH2/SH5/SH6.
- **PKG-1/PKG-2: untouched.** No parent-path reach; `shim.py` rides
  `src/benchweave_sdk_server` (already packaged); no dependency changes — `fastmcp`
  is already the `[server]` extra's exact pin. The Tier-3 dependency-repin rule does
  not fire.
- **SRF-2: untouched** (the fallback path uses the same loader it always did).
- **TWO-1: applies at landing** (SDK commit pushed first, gateway pointer after —
  the build train, not this record).
- **Gateway invariants: none move.** Zero bytes under `src/benchweave/`,
  `standards/`, or any schema. The #422 record's §5 declaration is UNCHANGED — the
  shim is a consumer of the declared affordances.
- **Drift surfaces (SDK `docs/internal/drift-and-obligations.md`):** README (the
  line-219 paragraph, obligation row 1's spirit), `user_guide/plugin-sdk.qmd` (new
  subsection beside the serve/prune server-CLI content), the wheel METADATA (derived
  from README — moves with it, no separate action). The R-5b agent-asset check is
  unaffected (verified: no template asset cites the command). No on-disk format or
  schema changes — the review rubric's Tier-3 persisted-format rule does not fire.
- **CI cost:** one new test module on the `sdk` job. Real-subprocess arms: one
  module-scoped started host (readiness-bounded, the existing `test_lifecycle.py`
  harness shape) + one shim subprocess arm; the parity breadth runs in-process
  (`Client(shim_server)`, the `test_mcp.py` pattern). Expected addition ≈ 15-25 s on
  the SDK job, inside the existing lifecycle-test cost class. Windows legs corroborate
  per the W1 doctrine; the stdio-subprocess arm is POSIX-first with the CI Windows leg
  as its Windows evidence.

## 6. Pre-committed acceptance rule

Written BEFORE any code exists. Counts read from `--junitxml` attributes or exit codes,
never an output-filter summary (the rtk rule). Every arm names its expected TYPED
outcome. New module `tests/server/test_mcp_shim.py` + the two amended arms noted.

**Arms (one started host, module-scoped, mock transport, starter plugin, free port —
the `test_lifecycle.py` S1 harness):**

| # | Arm | Expected typed outcome |
|---|---|---|
| SH0 | Composition spike: shim proxy object over the live host; `tools/list` via the shim vs via a direct streamable-HTTP client with the bearer | name/parameters/output_schema/description lists EQUAL under canonical-JSON sort — any difference fails the arm and forces plan B (§2.4) |
| SH1 | One-session parity, agent→host→browser: through a real shim SUBPROCESS (stdio client): `bws_v1_parameter_stage` + `bws_v1_parameter_apply`; then read the same device over REST with the delivered bearer (the page's data path) and `bws_v1_events_get` | REST shows the applied value; the event pair arrives with `surface: "mcp"`; the value the browser would render changed because the agent acted |
| SH1b | One-session parity, browser→host→agent: apply over REST (bearer); read via the shim | the shim's `parameter_read` returns the REST-applied value |
| SH2 | No-second-writer: after SH1's run, the family is untouched — pidfile still names the HOST pid; tokens file byte-identical before/after; no journal row added; and with `BENCHWEAVE_CAPTURE_DIR` pointed at a fresh empty dir for the SHIM's env only, that dir is still absent/empty | all four hold (the shim wrote nothing anywhere) |
| SH3 | Token hygiene: grep the shim subprocess's full stdout+stderr for the bearer value and the literal `Bearer ` | zero occurrences (kill-on-sight arm) |
| SH4 | Fallback engages: empty family dir (no pidfile, no tokens) → shim serves | stderr carries the fallback line naming the verdict `absent`; instructions carry the in-process marker; a stage/apply succeeds on the local mock; `host_info` answers `mode: "standalone"` |
| SH5 | Fork guard: hand-write `<capture-root>/library.lock` with a LIVE foreign pid (an exited-later child), empty family → shim start | exit non-zero, typed `standalone_capture_root_held:` naming the pid; no server served |
| SH6 | Host-ours-unproxyable: started host, then chmod 000 the tokens file → shim start | exit non-zero, typed `standalone_host_unproxyable:` naming the stop/start action; NOT a fallback (the live host keeps serving — a follow-up REST read succeeds) |
| SH7 | Stale family: (a) pidfile naming a dead pid, (b) tokens.pid ≠ pidfile.pid | both fall back WITH the disclosure line naming the reason; neither proxies |
| SH8 | Authoring degrade: host started WITHOUT `--authoring`, shim with it | tool list has no authoring tools; stderr carries the mismatch disclosure; connection serves |
| SH9 | Mode markers: proxy-mode instructions name the host URL; fallback-mode instructions carry the in-process marker — literal pinned, mutually exclusive | both assertions hold |
| AM1 | `test_cli.py:73` amended: the build-without-listener arm now asserts the fallback construction path still yields the full tool set | green under the reshaped command |
| AM2 | `test_cli.py:143` amended: no-extra graceful refusal now covers the discovery import path too | green |

**RED controls (one neutralization site each; red-then-green):**

- (a) **Discovery bypass** (point the resolver at an empty dir while the host runs):
  SH1 FAILS (the stage/apply lands on a local seam; the host's REST read shows the OLD
  value) and SH9's proxy marker is absent.
- (b) **Authorization unwired** (drop the bearer from the client factory): SH0/SH1 FAIL
  (the host's `standalone_mcp_token_required` surfaces through the shim).
- (c) **Fork guard removed**: SH5 FAILS (the shim falls back and serves beside the
  live pid).
- (d) **Mode marker unwired**: SH9 FAILS (both modes read identical instructions).

**SHIP =** all 12 rows green with typed outcomes as tabled + all four controls
red-then-green + the fast lane (bare `ruff check .`, fresh-cache bare `mypy`, focused
pytest) and the full battery green on the SDK repo. Deterministic arms, N=1 each; the
flake bound mirrors the 422 record's F14 discipline: one flake re-run per arm, a SECOND
consecutive flake on the same arm is a KILL.

**KILL =** any arm failing after its one flake re-run; any control staying green while
neutralized (the arm tests nothing — redesign the arm); SH0/SH1 showing ANY canonical
difference between shim-forwarded and direct tool bytes; or SH3 finding the bearer in
any shim output byte (kill-on-sight, no re-run); or the fallback ever serving beside a
verdict-`ours` host (SH6's shape — a manufactured second writer).

**UNDERPOWERED =** a real-subprocess arm cannot run in a lane's sandbox (no signalable
processes or no loopback bind): that arm rides the POSIX CI leg only, the Windows leg
corroborates per W1, and the degradation is disclosed on the PR — never silently
dropped. SH0's in-process variant substitutes if the subprocess shape cannot run at
all in a lane.

## 7. Review tier + Step-1 keyword scan (#254)

**Tier 3**, by the SDK repo's own rubric first: the slice **adds refusal paths** —
three new `snake_case:` machine-matchable prefixes (the rubric's "changes a refusal
prefix or adds a refusal path" rule names exactly this surface). The gateway rubric's
keyword rule agrees: the expected diff carries the async keyword (the fallback body's
`asyncio.run` settle, the async client/test harness) and the spawn keyword (the test
harness reuses `test_lifecycle.py`'s subprocess helpers). First-match-wins fires on
either; both fire. Two independent adversary lanes are therefore mandatory
(2026-09-24 retro R3 standing rule) — justified here beyond the letter: the shim
handles a credential and a process-identity lattice.

Keyword legend (numbered so this table does not perturb its own counts):
1=`threading` 2=`asyncio` 3=`subprocess` 4=`sha256` 5=`hashlib` 6=`migrate`
7=`recovery` 8=`protection`.

Scan result, MEASURED over this record at design time
(`grep -oiw <kw> <record> | wc -l`, the legend's one occurrence per keyword
excluded; the hyphenated test-harness compound matches the word form and is
counted): 1: 0 · 2: 1 · 3: 8 · 4: 0 · 5: 0 · 6: 0 · 7: 0 · 8: 0. Expected-diff estimate (the design's own code sketches and test plan):
2 fires in `cli.py`'s unchanged-by-intent fallback tail + `shim.py` imports (≥1);
3 fires in `test_mcp_shim.py`'s harness reuse (≥1); 1/4/5/6/7/8 absent by design —
the shim spawns nothing, digests nothing, migrates nothing, protects nothing (the
protective vocabulary belongs to the gateway surface this slice never touches).
First-match-wins: keyword 2 fires → Tier 3. The build record re-measures and states
its OWN scan over the real diff — that number gates.

## 8. Top risks, each with its falsifier

- **R1 fastmcp 4.0.11's provider composition mangles pinned schemas or drops
  `is_error` result semantics.** Falsifier: SH0 (canonical equality) and SH1 (the
  error ToolResult path — a refused stage surfaces identically through shim and
  direct). Plan B is named (§2.4) and bounded.
- **R2 Long calls (a bounded capture round-trip) fail across the stdio↔HTTP hop
  (session or timeout semantics).** Falsifier: SH1 is extended with one
  `capture_start`/`capture_stop`/`capture_list` round-trip through the shim against
  the live host (mock transport captures are real captures — the library lock is the
  host's, never the shim's; SH2 re-asserts after).
- **R3 The bearer leaks through a client-library error path** (an exception that
  embeds request headers). Falsifier: SH3 greps ALL shim output bytes, not just our
  own prints — kill-on-sight.
- **R4 The undetectable foreground host (§2.7).** No complete falsifier exists — that
  is why it is a DISCLOSED residual with its bounding properties stated (marker,
  mock-only fallback, no shared writable surface). An adversary lane is invited to
  break the bounding argument.
- **R5 A verdict-`ours` host dies between discovery and first call** (the proxy
  targets a corpse). Falsifier: an arm in SH7's family — stop the started host after
  discovery, before the shim's first tool call: the shim surfaces the transport
  failure honestly (the agent sees a connection error, never a silent fallback
  mid-session; the shim does not re-discover after start).
- **R6 Windows stdio/spawn quirks.** W1 doctrine: land and let the CI Windows leg
  corroborate; the doorbell/poll precedent says the file-based family reads are the
  portable spine.
- **R7 The shim becomes a second authoring authority in fallback** (an agent edits
  contracts in-process while an operator's host serves different bytes). Falsifier:
  SH4's fallback is a fresh seam by construction; the authoring-degrade disclosure
  (SH8) covers the proxy case; an adversary lane should attack the fallback+foreground
  combination explicitly — it is §2.7's residual wearing an authoring hat.

## 9. Forks ruled here (owner may veto cheaply; none block the build dispatch)

1. **No auto-start** — ruled OUT on A04 promotion grounds (§2.5). This is the call
   most worth an owner glance: if agent-first workflows prove to need it, it reopens
   only by owner word with the A04 argument answered (D3).
2. **`ours`-but-unproxyable refuses rather than falls back** (SH6). Ruled for the
   no-second-writer property: a live family owner makes every fallback a fork
   candidate. Cost: an operator running a started host under another user gets a
   refusal naming the fix instead of a degraded session.
3. **The mode marker lives in the shim's initialize instructions, not in
   `host_info`** (§2.5). Ruled because the host's bytes are the parity subject — the
   host cannot know a shim fronts it, and any host-side marker would break the
   identical-bytes property the ruling's "one session" implies.
