# Design record — gateway issue #589, PR-3: the dataset admission surface

Date: 2026-11-06. Parent authority: `.claude/deep-review/2026-11-06-589-live-bringup-design.md`
rev 7 (FROZEN), §4 and ledger rows D4, D6, D7, D10. This record pins PR-3's mechanism in
the real code; where it sharpens rev 7's parentheticals it says so and why. It is the
record the ruling's condition demands: **"the host admits" without a defined admission
surface is exactly how D4 happened** — the defect is not that the host forgot to admit,
it is that no surface exists to call.

Triage: PUBLIC. Mechanisms, invariants and measurements only. No device identity, vendor,
package name or bench identifier appears; the plugin this is measured against is "a real
plugin project" whose repo rows are named in the parent record and are not prerequisites.

Tooling note: the Gortex graph was unavailable for this checkout (probe returned
"repository not tracked"; checkout discovery timeouts). All reads were `Read`/`grep`.
No daemon started, no tracking changed.

Sources, first-hand: this SDK checkout at `631db75` on `fix/589-live-bringup-generic`
(every `src/` and `tests/` line number below was verified against this tree); the gateway
checkout READ ONLY for reference semantics (`content/dataset_services.py`,
`host/otdp_bridge.py` — design verification only, PKG-1 unaffected: nothing in any PR
reads the gateway checkout at test or runtime); the ruling comment read directly from
issue #589 (`2026-11-06T12:24:22Z`). PR-1 is landed in `.worktrees/pr1-builder-7f3a`;
PR-2 is IN FLIGHT in `.worktrees/pr2-builder-b41c` at baseline — every statement below
about PR-2's shapes cites rev 7 §3.1/§3.2 as its authority and names the reconciliation
point rather than assuming unwritten code. The vendored standards were read as bytes
(`otdp/0.2.4/`), not from memory.

---

## 0. The ruling, and what this record owes it

The principal ruled (issue #589, comment `2026-11-06T12:24:22Z`, read this session):
**host-admission is the standard.** A plugin returns a dataset-shaped result; the host
admits it; a plugin does not call a publish surface. Reasoning adopted verbatim: storage
policy is host policy (a publish hop inside the adapter is a second authority that
drifts); the gateway's dispatch-time requirement is a trap (it fires after accepting a
descriptor that promised host-admission); the dataset is already typed by the
measurement schema (a second publish is ceremony that can disagree with its payload).
The plugin's own generated `adapter.py` declares host-admission (`:1216-1217` observed in
one plugin; the scaffold generates that file, so this pins an observation and not a path
in this repository). That promise stands as written and is now the standard's rule. The
plugin does not change.

The ruling carries one condition, discharged by this record: **define admission** —
(a) where the bytes land, (b) who may read them afterwards, (c) what `dataset_id` is
minted over, (d) what the host does when admission fails. §2 answers each against real
code.

## 1. Root cause, verified

**D4** — `HostOperationContext.dataset_id` is declared (`session.py:964`, the class
docstring at `session.py:952-965` documents it as "Host-reserved dataset correlation
id") and assigned `None` in `__init__` and NOWHERE else (grep: the only write is the
constructor's `= None`). No `DatasetServices` implementation exists anywhere under
`src/` (`interfaces.py:188-194` ships the honest no-implementation docstring; the pin
is `tests/test_dataset_services.py:70-85`). The adapter-side consequence, relayed by the
team-lead and consistent with the protocol note at `interfaces.py:26-31`: a fetch action
that builds its manifest against `context.dataset_id` refuses on `None`. The defect is
exactly the ruling's shape: no surface exists to call.

**D6** — `_resolve_capture_verb` (`seam.py:1758-1772`) resolves `capture` first, then
falls back to `invoke`; `_op_capture_start` then dispatches via
`self._session.begin_verb(verb, {"capture_id": …, **capture_arguments})`
(`seam.py:1932-1942`) — the capture arguments verbatim. The invoke adapter contract is
`{action_id, input}` (rev 7 §3.1; the vendored runtime schema's invoke request branch),
and `begin_verb` (`session.py:1153-1171`) passes `arguments` through untouched. There
is no generic source for `action_id`: the descriptor's `actions` map is keyed by action
id and the capture request carries none. The fallback can never produce a valid invoke
dispatch — it is dead code that lies.

**D7** — four clauses, split by the dataset model. "No capture verb" is an honest
plugin declaration (data via actions) — the host's job is to say so (D6's refusal).
"Artifact append/finalise members" are the streaming-capture lane, implemented
(`capture.py:247+`, `StandaloneCaptureWriter`) and driven only by the capture lifecycle
for plugins that declare a capture verb. "Inline snapshot never admitted" is D4's core
— PR-3 admits it. "`capture_stop` never stops the device" is vacuous for an invoke-only
plugin: `_op_capture_stop` (`seam.py:2072-2080`) refuses `not_found` ("no capture in
flight") — already honest; the device's own stop is an invoke the operator issues, and
PR-2's `cancellable`/`retry` rules govern teardown. **PR-3 lands D7's data half
(inline admission) and changes nothing in the streaming half.**

**D10** — the gateway still requires `dataset_publish`: `otdp_bridge.py:1462-1479`
raises `InvalidInvokeResult` unless the dataset-shaped result byte-equals a manifest
admitted THIS operation through the dataset services. Verified this session. The SDK
side closes here; the gateway side is GW-1 (gateway repo), task #9, still ownerless per
the parent record §1 — **PR-3 must not close while GW-1 is unopened.** Until it merges,
the divergence is disclosed in the three places the ruling names (§5).

**Citations from the parent record, verified against the gateway checkout:**
- Gate I6 mint, `dataset_services.py:167-186`: `dataset_id = f"ds:{operation_id}"` —
  VERIFIED. **The mint is per OPERATION (per dispatch occurrence), not per
  acquisition.** The controller's own docstring (`:86-88`) pins it: "``ds:`` dataset
  ids per dispatch — unique per occurrence-keyed operation id"; the bridge mints at
  context construction for every invoke dispatch when the dataset lane is armed
  (`otdp_bridge.py:424-440`). The acquisition is named INSIDE the manifest
  (`acquisition_id`, an M10 echo field), never by the id. Consequence adopted: retries
  and re-dispatches get NEW dataset ids; the manifest's `acquisition_id` is the durable
  correlation.
- `is_dataset_shaped`, `dataset_services.py:262-268`: VERIFIED —
  `isinstance(result, dict) and (dataset_required_keys <= set(result))`. Required keys
  only, so a shaped-but-schema-invalid result is distinguished from an unshaped one
  (the honest refusal names the schema miss, `dataset_shape_note`, `:270-282`).

---

## 2. Admission, defined — the ruling's four answers

### (a) Where the bytes land

**Module:** new `src/benchweave_sdk_server/dataset_admission.py` (rev 7 §4 names it).
**Store: the existing capture root and the existing `CaptureLibrary` — extended, not
duplicated.** The capture artifact writer is `StandaloneCaptureWriter`
(`src/benchweave_sdk/capture.py:247`); the store is `CaptureLibrary`
(`src/benchweave_sdk_server/library.py:219`): a stdlib sqlite index
(`<root>/library.sqlite3`) rebuilt from the root's event directories, `manifest.json`
presence as the publication marker (`capture.py:202-211`), `metadata.json` as the
annotation/pin authority, one lockfile per root (`library.py:249-274`).

**Path template:** `<capture-root>/datasets/<segment>/manifest.json`, where `segment`
is the dataset id with its single `:` replaced by `-` (`ds:op-ab12cd34` →
`ds-op-ab12cd34`). The mapping is injective over host-minted ids (every minted id
starts `ds:`); the segment is validated by the EXISTING `_valid_capture_segment`
(`capture.py:112-130`, reused — the alphabet already admits lowercase-hex-and-hyphen
and refuses traversal, device names and trailing dots); the stored manifest carries the
TRUE `dataset_id` field, and every read path verifies the stored id equals the
requested one (a caller-supplied `ds-op-…` forgery finds the directory and refuses on
the id check).

**Why a `datasets/` family under the same root, not top-level sibling directories:**
`CaptureLibrary.rebuild` (`library.py:286-321`) indexes EVERY root-level directory
carrying a `manifest.json` as a capture row. A dataset manifest at top level would be
indexed as a capture with `format: ""`, `byte_length: 0`, `sha256: ""` (`_row_of`
coercions, `library.py:200-216`) — a lie in a closed 13-key row. Under `datasets/`,
the capture walk is naturally blind to it (the walk visits `datasets/`, finds no
`datasets/manifest.json`, skips — verified against the walk's code), and the dataset
family gets its own honest row shape.

**Row shape — a sibling of the capture row, own column set.** New table in the SAME
`library.sqlite3` (the file persists across processes; a second table avoids migrating
the existing `captures` table's schema under `CREATE TABLE IF NOT EXISTS`):

```
datasets(dataset_id TEXT PRIMARY KEY, kind TEXT NOT NULL, started_at TEXT NOT NULL,
         status TEXT NOT NULL, action_id TEXT, sha256 TEXT NOT NULL,
         surface TEXT, operator TEXT, project TEXT,
         pinned INTEGER NOT NULL DEFAULT 0, tags TEXT NOT NULL DEFAULT '[]',
         notes TEXT NOT NULL DEFAULT '')
```

`sha256` is over the CANONICAL manifest bytes (the row's integrity pin, the same
discipline a capture's `sha256` serves over its primary). `metadata.json` inside the
dataset event directory is the annotation/pin authority — the capture sidecar pattern
verbatim (`library.py:178-197`), so `capture_pin`-style machinery composes later.
`CaptureLibrary` gains `list_datasets()`, `get_dataset(dataset_id)` (id-verified read),
`record_dataset(dataset_id, manifest, metadata)` (the runtime insert, mirroring
`record_published`, `library.py:343-354`), and the rebuild grows a second walk of
`root/datasets/`. **The index stays query acceleration: everything is rebuildable from
the root** (AR-6's discipline, extended to the second family).

**No new store is needed.** The capture root's resolution, package-tree refusal and
environment contract (`capture.py:62-109`) apply unchanged; the one-library-per-root
lockfile covers the whole root, so admission (through the seam's lazy `_library()`,
`seam.py:1680-1697`) introduces no second writer.

### (b) Who may read them afterwards

Three read paths, each with its existing authorization, none assuming a fixed operator:

1. **Host operations** (`capture_list`, and PR-4's series/report over datasets): the
   standalone host's guard model — per-launch bearer token, CSRF on HTML mutations,
   trusted-Host (DNS-rebinding) refusal, loopback bind (`security.py:69-118`
   `GuardPolicy`; the bearer check arms the API surfaces). Identity = **the holder of
   this process's launch token**. The 2026-09-23 owner directive (three developers;
   single-operator assumptions retired) is honored by construction: nothing names "the
   operator" as one person — the row RECORDS provenance (`operator` via
   `getpass.getuser()` at admission, `project`, `surface`) exactly as captures do
   (`seam.py:1788-1791`), and authorization is the host's guard model, not a principal
   lookup.
2. **Services members** (`dataset_lookup`): **this-run scope** — the admitted registry
   of the current host process, plus the persisted manifests it admitted. Unknown or
   not-this-run ids refuse typed. This is deliberate gateway parity:
   `dataset_services.py:749-763` scopes lookup to this run's publishes and names the
   cross-principal model as the gateway's own deferral ("design row 2's deferral").
   The SDK mirrors the honest scope rather than inventing a per-principal model no
   surface asks it for.
3. **The files**: whoever's OS identity can read the capture root — the standing
   standalone posture, identical to captures today.

### (c) What `dataset_id` is minted over

`"ds:" + operation_id`, **per invoke dispatch, at the context mint, before the adapter
runs** — the gateway's I6 shape (`otdp_bridge.py:424-440`, `dataset_services.py:167`).
Mechanically:

- `HostOperationContext.__init__` (`session.py:960-967`) gains
  `dataset_id: str | None = None`; the constructor assigns it directly. Every existing
  mint site is unchanged (the default).
- The INVOKE dispatch — the single context site PR-2 introduces for the action-deadline
  context (rev 7 §3.2: "minted with `actions[action_id].timeout_ms`, NOT
  `verb_timeout_ms('invoke')`") — passes `dataset_id=f"ds:{operation_id}"`. This is
  PR-3's one-line edit at PR-2's site; **reconciliation point at build time**: adapt to
  the site's actual shape (a `begin_verb` keyword or an invoke-specific mint helper),
  but the mint must precede task creation — the adapter reads `context.dataset_id`
  DURING execute, so a post-`create_task` assignment would be a race even though the
  single event loop defers the task to the next await.
- **Non-invoke verbs keep `dataset_id = None`** — gateway parity (the bridge mints only
  for `invoke`, and only when the dataset lane is armed). Capture dispatches publish
  through the capture lane; an adapter that reaches for `dataset_publish` on a None id
  gets `standalone_dataset_context_absent:` (§4, the prefix already frozen in rev 7
  §7's STD-4 list).
- The seam's `_op_invoke` records the dispatch state `{dataset_id, action_id, input}`
  in the admission controller — the M10-correlation source, mirroring the bridge's
  `mint_dataset_id(..., action_id=…, input=…)` recording.

### (d) What the host does when admission fails

The validation order is load-bearing and mirrors the gateway's publish path
(`dataset_services.py:480-513`): **identity → idempotency → pinned schema →
M-structural (incl. channels) → M10-correlation → M11-scope — and only THEN the
write.** Validation precedes any filesystem call; the write is ONE atomic
`manifest.json` (temp + `os.replace`, the `_write_manifest` precedent,
`capture.py:202-211`), and manifest presence IS the publication marker. Consequences:

- A validation refusal leaves **zero bytes** under `datasets/` — there is no staging to
  leak. The atomicity is structural, not cleanup-dependent: the only states on disk are
  "no event directory" and "complete published manifest" (the capture writer's own
  crash-posture, `capture.py:22-26`).
- A WRITE failure (disk error mid-replace) leaves at most a temp remnant and possibly
  an empty directory; the admission refuses, the directory is removed best-effort, and
  — because operation ids never repeat — a leftover can wedge nothing.
- The invoke OPERATION returns the typed refusal: `SeamError("invalid_request", …)`
  carrying the machine prefix `standalone_dataset_invalid:`, the pinned schema's
  `json_path` and message (the I4 posture), and the divergence sentence (§5). The
  dataset-shaped result is never laundered as a plain result — PR-2's interim
  `unavailable` refusal (rev 7 §3.1's "before PR-3" branch) is REPLACED by admission;
  admission failure is still a refusal.

---

## 3. The mechanism, end to end

**Detection.** The port of `is_dataset_shaped`: `isinstance(result, dict) and
(dataset_required_keys <= set(result))`, where `dataset_required_keys` comes from the
PLUGIN'S PINNED measurement document (`$defs.dataset.required` — 11 keys at 0.2.4:
`dataset_id, kind, configuration_id, acquisition_id, started_at, clock, axes,
variables, trigger, status, context`; verified against the vendored bytes), exposed by
PR-2's contracts resolution (the dataset half of `InvokeContracts`, rev 7 §3.1 —
**second reconciliation point**: PR-3 consumes `dataset_validator` + 
`dataset_required_keys` from PR-2's resolved-contracts object under whatever names it
ships; the gateway's controller properties to mirror are
`dataset_services.py:128-135`). No required-key list is hardcoded in `src/` — the
pinned document supplies it at runtime, so a corpus sync moves nothing.

**Inline admission (the ruled path).** In PR-2's invoke RESULT-gate block (after the
closed-envelope, echo and output-schema gates), the dataset-shaped branch calls the
admission core with `(manifest, operation_id, dispatch_state)`. On success the
admitted manifest is recorded (per-operation and per-dataset-id — idempotency and
lookup, mirroring `record_admitted`, `dataset_services.py:293-308`), the library row is
recorded, and a `dataset_admitted` event rides the bus (`{dataset_id, kind,
action_id}` — the `capture_started` precedent, `seam.py:1976-1984`). The invoke result
itself is unchanged (the closed envelope; admission is a host side-effect, not a
result mutation).

**The validation core (both paths share it):**
1. manifest is an object; `context.dataset_id` non-null (else
   `standalone_dataset_context_absent:`); `manifest["dataset_id"]` equals it.
2. Idempotency: a byte-identical manifest (canonical JSON compare) under a used
   dataset id returns the admitted manifest, no new rows; a divergent one refuses
   naming immutability (`dataset_services.py:494-502` parity).
3. Pinned measurement schema: first error at `json_path` (compiled by PR-2's
   resolution).
4. M-structural (the M01–M04 port, `dataset_services.py:577-688`): unique axis and
   variable ids; dimensions naming axes; explicit-coordinate length agreement;
   inline-value count = product of axis lengths (scalar product one; the
   derived-invalid suspension carried verbatim); dtype↔encoding pairing for
   artifact-backed variables; inline finiteness. **Channels cross-check (D9's row):**
   every `variable.channel_ids` entry must be an id the descriptor's `channels`
   declares (`dataset_services.py:609-614` parity; the channels are read from the
   loaded descriptor at controller construction — the shape `build_dataset_services`
   derives them from the raw descriptor, `:415-419`).
5. M10-correlation subset: `configuration_id` / `acquisition_id` must echo the invoke
   input's same-named fields WHEN the dispatched action's pinned input schema declares
   the field (`dataset_services.py:690-715` parity — exactly those two fields, exactly
   that gate).
6. M11-scope: every referenced payload artifact must be one THIS operation finalised.
   Standalone, no payload lane ships (below) — the finalise registry is empty, so an
   artifact-backed variable refuses with the M11 message naming the absent payload
   surface honestly. **Inline-valued manifests — what an invoke-only plugin returns —
   are unaffected.**
7. Persist: atomic `manifest.json` under `datasets/<segment>/`, `metadata.json`
   sidecar with provenance, library row, admitted registry, bus event.

**Explicit admission (the protocol surface stays).** The same core exposed as the two
base `DatasetServices` members, composed onto the connected session's services object:
`attach_dataset_members(services, *, controller, contracts, channels)` returns a
transparent delegating wrapper adding `dataset_publish` and `dataset_lookup` (member
detection by presence is the ecosystem's established capability probe —
`LinkControlServices`' "the member check is the whole test", `interfaces.py:362-367`).
The composition point: `PluginSession` gains a late-bound `services_wrapper`
attribute the SEAM installs at construction (beside the `link_event_publisher`
precedent, `session.py:1011-1017`, installed at `seam.py:231`); `connect` applies it at
the one services mint site (`session.py:1092`): `services =
wrapper(self._services_factory())`. Transport-agnostic — every factory (mock, serial,
replay, ftdi) composes through the same line; the wrapper delegates `__getattr__`, so
the capture duck-checks (`seam.py:1848-1875`) still resolve and the capture lane is
unbroken through it. The wrapper is installed only when the invoke lane is armed
(contracts resolved ∧ descriptor declares `invoke`) — the base pair attaches
unconditionally within that gate, mirroring the gateway's "base members always"
(`dataset_services.py:396-400`); the permission-gated payload members are NOT attached
(no `adapter_permissions` parsing ships — that rides the payload lane).

Why attach at all, rather than a host-internal core: the protocol docstring flip (§6)
must be TRUE — a `dataset_publish` an adapter cannot call is not an implementation.
The named consumer is real: upload actions inspect a dataset before reading payloads
(`interfaces.py:236-238`), and pre-ruling plugins that publish stay conformant
standalone. The wrapper is ~5 lines of session surface; the rejected alternative
(post-connect mutation of the adapter's held services) is a race.

**Exposure.** `_CAPTURE_LIST_RESULT` (`catalogue.py:411-413`, closed
`{captures: […]}`) gains an OPTIONAL `datasets` array with its own closed row schema
(`dataset_id, kind, started_at, status, action_id, surface, operator, project, pinned,
tags, notes` — the index row's shape). `_op_capture_list` appends
`library.list_datasets()`. Existing consumers are unaffected (optional key, closed
schema otherwise unchanged). **This sharpens rev 7 §4 item 3's "a `dataset` surface
row"**: reusing the 13-key capture row was rejected because `format` / `byte_length` /
`sha256` are primary-artifact fields a manifest does not carry — the schema witness is
`_row`'s own field semantics (`seam.py:2150-2178`) — and an optional sibling array
keeps `capture_list` the one inventory surface without lying about shapes. Flagged for
the maintainer as a deliberate refinement of the frozen record's parenthetical, not a
contradiction of its mechanism.

**Boundary with PR-4 (D5) — named, not crossed.** PR-3 makes a dataset DISCOVERABLE
(listed) and its manifest RETRIEVABLE this-run (`dataset_lookup`); `capture_get`,
`capture_series` and `report_export` over dataset manifests are PR-4's unified display
path (rev 7 §5: one path, no second renderer; S5/R5). PR-3 adds no renderer and no
second one can grow (the seam is named).

**D6 — the lying fallback is REMOVED.** `_resolve_capture_verb` loses the `invoke`
branch: capture verbs are `capture` only; no declaration refuses `unavailable` with
the machine prefix `standalone_capture_verb_undeclared:`, naming the descriptor's
declared operations and the honest direction ("this plugin serves data through its
actions; invoke them" — the dataset path IS the data route). Two accompanying moves:
(a) the verb check moves BEFORE the capture-services duck-check in `_op_capture_start`
(declaration precedes host capability): today an invoke-only plugin over the mock
transport gets `capture_services_incomplete` — the wrong cause for a plugin that never
declared capture, and the dishonest ordering would make the D6 arm unreachable on the
primary fixture transport. The reorder follows the seam's own wrong-cause discipline
(the acceptance review's B, `seam.py:1843-1847`). (b) No `action_id` synthesis — the
descriptor's `actions` map is keyed by action id and a capture request carries none;
inventing one would dispatch an unvalidated action through a gate built to validate
declared ones. The capture-over-class-actions composition is seam S2 (rev 7 §8),
deliberately unbuilt.

**D7 — the split, precisely.** Lands in PR-3: inline dataset admission (above). Does
NOT land: the streaming-capture half — the artifact members, the capture lifecycle
that drives them, and `capture_stop` all belong to plugins that declare a capture verb
and are unchanged; for an invoke-only plugin `capture_stop` already refuses
`not_found` honestly (`seam.py:2077-2080`) and teardown is PR-2's `cancellable` rule.

---

## 4. Refusal prefixes (STD-4) and their types

| Prefix | Fires at | Type | Vehicle |
|---|---|---|---|
| `standalone_dataset_context_absent:` | `dataset_publish` reached with a null `context.dataset_id` (non-invoke dispatch) | `ValueError` (services boundary; the gateway's `DatasetServiceRejected(ValueError)`, `dataset_services.py:73`) | already frozen in rev 7 §7's list |
| `standalone_dataset_invalid:` | admission validation refusal (schema or M-check) | `SeamError("invalid_request", …)` at the operation boundary; `ValueError` when raised through the services member | new — this record |
| `standalone_capture_verb_undeclared:` | `capture_start` with no `capture` operation declared | `SeamError("unavailable", …)` | new — this record |

The seam-side types follow the closed code vocabulary (`errors.py:26-40` —
`SeamError.__init__` refuses codes outside it), and the message-carried machine prefix
is the established pattern (`capture_services_incomplete:`, `standalone_storage_reserve:`
inside `SeamError` messages, `seam.py:1724-1754`). Every refusal fires before any
write. No existing prefix weakens.

---

## 5. The D10 disclosure, in the three named places

1. **The design record:** this file, §0/§1/§5, and the parent record §4 — the
   standalone host admits on result; the gateway still requires `dataset_publish`
   until GW-1 merges; GW-1 is a named carrier (task #9) and PR-3 does not close while
   it is unopened.
2. **`host_info`:** `_HOST_INFO_RESULT` (`catalogue.py:81-149`) and `_op_host_info`
   (`seam.py:493-520`) gain a `dataset_admission` field — a closed two-string object:
   `{"standard": "host-admits-on-invoke-result", "gateway_divergence": "the gateway
   still requires dataset_publish until GW-1 (issue #589 row D10)"}`. The schema is
   closed (additionalProperties false), the field required once present — a consumer
   cannot miss it.
3. **The refusal text:** every `standalone_dataset_invalid:` refusal appends one
   sentence stating the divergence, so an operator staring at a refused manifest knows
   publish-vs-admit is not the question: the standalone host admitted-or-refused on
   the result itself; the gateway would additionally have required the plugin to
   publish.

---

## 6. The DatasetServices protocol, member by member

The protocol composes **twelve** members — seven own over the five-member
`HostServices` base — pinned by `tests/test_dataset_services.py:46-53`
(`len(_members(DatasetServices)) == 12`). (The dispatching brief said "thirteen"; the
corpus's own count and pin test say twelve. No member is added or removed.)

| Member | PR-3 verdict |
|---|---|
| `dataset_publish` | **IMPLEMENTED** — the standalone admission core over the capture root (§3), attached when the invoke lane is armed. Validation parity with the gateway's steps 1–6 (§2d) minus the staged-writer routing (see delta below). |
| `dataset_lookup` | **IMPLEMENTED** — this-run admitted registry plus persisted manifests; unknown/not-this-run refuses typed (gateway scope parity, `dataset_services.py:749-763`). |
| `artifact_read` | **DECLARED-ONLY** — the payload lane (S4). Note the name collision with the HOST operation `artifact_read` (catalogue row, `catalogue.py:920-933`) — distinct surfaces, both already in-tree; no change to either. |
| `payload_create` | **DECLARED-ONLY** — permission-gated payload lane (S4). |
| `payload_append` | **DECLARED-ONLY** — S4. |
| `payload_finalise` | **DECLARED-ONLY** — S4. |
| `payload_abort` | **DECLARED-ONLY** — S4 (and degenerate for inline admission: validation precedes the single write, so there is no staging to abort). |

**Contract changes:** none to signatures or the member set. The docstring
(`interfaces.py:188-194`) flips per its own pin's instruction
(`tests/test_dataset_services.py:70-85`: "When an implementation lands, this pin flips
with the wording — the same motion test_capture_writer applies"): it becomes the
`CaptureServices` precedent's shape — "First partial implementation:
`benchweave_sdk_server.dataset_admission` implements the two base members of this
twelve-member protocol over the capture root… the payload members await their
permission-gated composition (the gateway's dataset path remains their first full
implementation)." The pin test's assertions are amended to pin the NEW honesty (the
two implemented members named; the payload members' absence stated) — not deleted.

**Disclosed deviation from the gateway's publish path (one):** the gateway routes the
manifest bytes through the staged writer so the published `art-<sha256>` row is the
manifest's storage path and quota/rollback ride one transaction
(`dataset_services.py:514-562`). Standalone, the single atomic `manifest.json` write
IS the storage row and there is no quota ledger — the row's `sha256` preserves the
integrity discipline. Named here rather than silently diverged.

---

## 7. Minimal first slice and explicit deferrals

**The slice ships:** `dataset_admission.py` (controller + validation core +
`attach_dataset_members` + the detector port); the `HostOperationContext.dataset_id`
parameter and the invoke-site mint; the dispatch-state recording in `_op_invoke`; the
admission call in the result-gate branch (replacing PR-2's interim refusal); the
library's `datasets` table, second rebuild walk, and three methods; the
`capture_list` `datasets` array; the `dataset_admitted` event; the `host_info` field;
the D6 fallback removal + reorder; the `PluginSession.services_wrapper` hook; the
docstring flip; the invariants/drift/docs legs; the arms below.

**Deferrals, each with its carrier:**
- The four payload members + services-side `artifact_read` (and the
  `adapter_permissions` parsing they gate on) — **seam S4** (rev 7 §8); artifact-backed
  manifests refuse at M11 naming the absent surface.
- Dataset rendering through `capture_get`/`capture_series`/`report_export` — **PR-4**
  (the unified display path; this record's §3 boundary).
- Capture-over-class-actions composition — **seam S2**.
- A dataset retention/pruning policy (datasets are invisible to the capture retention
  sweep — deliberate: no dataset policy exists and inventing a bench constant violates
  A02; manifests are small inline JSON in practice) — **S4/GW-1's corpus question**,
  disclosed in the guide.
- A manifest byte cap — same reasoning (A02: no host constant where no declaration
  exists); the web layer's body cap bounds request size, not adapter results — **S4**.
- Cross-principal dataset authorization — the **gateway's own deferral**, mirrored
  (§2b).
- A main-side cross-repo admission-parity test (SDK validator vs gateway validator
  over the same fixtures) — **GW-1's PR** names it as its pairing row
  (`tests/sdk/` in the gateway checkout, the `test_presentation_packaging` precedent);
  PKG-1 forbids it living here.

---

## 8. Invariant and cross-surface impact

- **STD-1/2/3/5/6:** untouched — no vendored motion; `sync-standards --check` green
  throughout; the pinned measurement schema is READ through PR-2's resolution, never
  copied into `src/`.
- **STD-4:** grows three message prefixes (§4). `invariants.md`'s STD-4 entry amends
  with them, types pinned per boundary.
- **PKG:** no new dependencies; wheel contents unchanged.
- **SRF:** (i) new draft row: "the standalone admission path validates what the
  gateway's `dataset_publish` validates (identity, idempotency, pinned schema,
  M01–M04 incl. channels, M10 subset, M11-scope-honest), minus the payload lane —
  pinned by parity arms"; (ii) `capture_list`'s result schema gains an optional
  `datasets` key — an interface change to a served shape, DISCLOSED (optional;
  existing consumers unaffected); (iii) `HostOperationContext.__init__` gains a
  defaulted parameter and `PluginSession` a late-bound `services_wrapper` — both
  additive. Scaffold output unchanged (the template is silent on datasets — verified;
  the R-2 golden fixture does not move).
- **Drift obligations:** 6 (behavior change → tests here, §9 names the modules);
  obligation 1-adjacent (the user guide gains the dataset-admission section and the
  disclosure, via the `document-writer` agent in the STE100 register — the register
  rule's own scope: user-facing published guidance); 8 (GW-1 is the named main-side
  counterpart; landing order unchanged — SDK pushed first, pointer after). The README
  five-steps and CLI surface are unchanged (no flag, no subcommand).
- **CI cost:** none beyond the suite — full `pytest -q` (raw collected count), ruff,
  strict mypy (`files = ["src"]`), `sync-standards --check`, `--version` smoke. No new
  CI job, no marker partition (all arms hermetic; the live leg below is
  operator-run).

---

## 9. Acceptance — pre-committed, with denominators and kill directions

Stated BEFORE any arm is written. New module `tests/server/test_dataset_admission.py`
(seam construction lives under `tests/server/` per the rev-7 census), using the
existing starter-project machinery (`tests/server/conftest.py:252-297`,
`_patch_descriptor` at `tests/server/test_capture_lifecycle.py:72-107`) plus one
invented-name fixture adapter whose invoke action returns a dataset-shaped manifest
built against `context.dataset_id` (the real plugin's shape in miniature). Amended:
`tests/test_dataset_services.py` (pin flip), the capture-lifecycle module (D6 arms),
`tests/server/test_library.py` (dataset table/rebuild), `tests/server/test_catalogue.py`
(list-result schema), the host_info-pinning arm wherever the closed key set is pinned
(builder locates by red).

**Twenty arms, pre-committed:**

Mint (D4's core): **A1** invoke over the fixture; the adapter-observed
`context.dataset_id` equals `"ds:" + operation_id` and the dataset is admitted.
**A2** a non-invoke dispatch leaves `dataset_id` None. **A3** `dataset_publish` on a
None context refuses `ValueError` with `standalone_dataset_context_absent:`.
Detection: **A4** a dataset-shaped result is admitted; the same manifest minus one
required key is NOT detected (passes as a plain result — the detector's negative
control). Validation: **A5** schema violation (e.g. a `kind` outside the corpus enum)
→ `invalid_request` + `standalone_dataset_invalid:` + `json_path` + the divergence
sentence, and NO directory under `datasets/`. **A6** M01-channels: an undeclared
`channel_id` → refused, no directory. **A7** M02: inline values ≠ product → refused.
**A8** M10: `configuration_id` diverging from the invoke input (the action schema
declares it) → refused; when the action schema does NOT declare it, the same manifest
admits (the gate's both directions). **A9** M11: an artifact-backed variable refuses
naming the absent payload surface. **A10** idempotency: byte-identical republish
returns the admitted manifest with one row; a divergent second refuses naming
immutability. **A11** no-partial-atomicity: a manifest passing the schema but failing
M01 leaves ZERO bytes under `datasets/` (filesystem assert, not just the refusal) —
the D4-condition's own acceptance arm. Persistence: **A12** admit → a FRESH
`CaptureLibrary` over the root rebuilds the dataset row from files (AR-6 for
datasets). Exposure: **A13** `capture_list` serves the `datasets` row in the closed
shape; `captures` unchanged. **A14** `host_info` carries `dataset_admission` with the
divergence text. **A15** the `dataset_admitted` event rides the bus with
`{dataset_id, kind, action_id}`. D6: **A16** an invoke-only descriptor (no `capture`
operation): `capture_start` refuses `unavailable` + `standalone_capture_verb_undeclared:`
+ names invoke as the data route, and NO adapter dispatch occurred (the fixture
adapter records calls). **A17** the same plugin over the MOCK transport (no capture
services) gets the VERB refusal, not `capture_services_incomplete` — pins the reorder.
Attach: **A18** `dataset_lookup` returns the this-run admitted manifest; an unknown id
refuses typed. **A19** the wrapper is transparent: the wrapped services still resolves
the capture members (duck-checks pass through). **A20** the protocol pin: the member
set still composes twelve; the attached wrapper carries `dataset_publish` and
`dataset_lookup` as coroutine functions.

**Mutations (each reddens its named arms, both runs pasted in the PR):** M9 skip the
mint (rev 7's) → A1. M10 admit without schema validation (rev 7's) → A5–A9. M17
restore the `invoke` fallback → A16 (a dispatch occurs, or the refusal differs) and
A17. M18 reorder to write-before-validate → A11 (and A5/A6's no-directory asserts).
M19 admit without recording the library row → A12/A13. M20 drop the wrapper (attach
nothing) → A18–A20.

**Kill directions:** any mutation leaving its named arms green kills the claim — fix
the mechanism or the fixture, never weaken the arm. A1 green under M9 means the
fixture adapter is not reading the context (a fixture bug, not a pass). A11 green
under M18 means the reorder mutation never applied (a measurement bug). A mutation
reddening more than three arms OUTSIDE its named set means coupled fixtures — re-slice
before trusting any green. The suite denominator is the raw `pytest -q` collected
count (read from redirected output, never a filtered summary line — the rtk lesson),
pasted in the PR beside the arm count.

**CORRECTION, 2026-11-06 (pre-build, append-only — the sentence this replaces said
"the generality gate's own denominators are unchanged (PR-3 adds no literals; the gate
keeps holding by absence)". That is wrong twice and its own wording is the record of
how it was wrong.)** First, PR-3 **does** add literals: `standalone_dataset_invalid:`
and `standalone_capture_verb_undeclared:` are `ast.Constant` strings in `src/`, and the
gate counts **every** `ast.Constant` in every scanned `.py`, so `literals_examined`
moves. Second, "unchanged" is not the property that holds any more. PR-1 (merged,
`75e6b4b`) pinned `files_scanned` and `literals_examined` as **floors** and left
`block_exemptions` / `allowlisted_entries` **exact** precisely so that a later PR adding
a module or a refusal-prefix string does not redden a gate it has nothing to do with.
So the correct statement is the inverse of the original: **the pins move with any added
module or literal, and it is the floor assertion that makes that non-reddening.** A
count-equality pin here would have reddened PR-3 for adding a refusal prefix, which is
the false positive that earns gates exemptions. Expect `literals_examined` to rise by
at least the two prefixes and `files_scanned` by one if a module is added; both are
expected movements, and the exemption counts staying exact is the thing to defend.

**MEASURED MUTATION NAMED-SETS, 2026-11-07 (post-build, append-only — two independent
refute lanes ran the §9 mutation matrix by execution; this section records what the
mutations ACTUALLY reddened and supersedes the matrix's named sets above by date. The
frozen matrix bytes stay as committed; the arms themselves are unaffected — each still
pins its behavior and passes on the real code. What was wrong was the blast-radius
prediction, not the acceptance.)** M10 (skip schema validation) reddened **A5 only**,
not A5–A9: A6–A9 refuse in the M-checks, which the mutation does not skip. M17 (restore
the `invoke` fallback) reddened **A16 only**, not A16+A17. M19 (skip the library row)
reddened **A13 only**, not A12/A13 — A12's fresh library REBUILDS the row from the
files, so a skipped runtime row record is invisible to it by design (AR-6 working as
intended). M20 (drop the wrapper) reddened **A18+A20**, not A18–A20 — A19 passes
because it attaches the wrapper itself over its own `_CaptureCapable` instance, so the
seam never installing one does not reach it. M18 (write-before-validate) reddened
**A11+A6 plus A8**. M9 (skip the mint) reddened **A1** — but with a twelve-arm blast
radius, which is past this record's own ">3 arms outside the named set means coupled
fixtures" threshold; the threshold's instruction (re-slice before trusting any green)
applies to whoever next mutates the mint.

**Live leg (operator-run, marker-partitioned, NOT gating):** the real plugin remains
the integration witness — its catalog reshape is a plugin-repo pairing row (parent
record §3.1), not an SDK prerequisite; after it lands, an invoke fetch → admitted
dataset on hardware is the end-to-end witness. Until then the typed
`profile_contract_invalid:` refusal on both hosts is itself the parity witness.

---

## 10. Top risks, each with its falsifier

- **R-A: PR-2's shipped shapes diverge from rev 7 §3.1/§3.2 at the two named
  reconciliation points** (the invoke context site; the contracts object's dataset
  validator/required-keys surface). Falsifier: the build-time reconciliation itself —
  PR-3's builder adapts names, not semantics; if the semantics differ (e.g. no
  compiled dataset validator ships), PR-3 BLOCKS on PR-2, and this record says so
  rather than papering over a re-implementation.
- **R-B: the wrapper breaks a transport's services assumption** (an adapter or host
  path type-checks the concrete class rather than duck-probing). Falsifier: A19 plus
  the full suite over serial/replay/ftdi fixtures; a failure means the wrapper needs
  the gateway's mixin-attach shape instead — a mechanism swap, not a redesign.
- **R-C: admission's validation drifts from the gateway's** (a check ported wrong).
  Falsifier: the parity arms are shape-identical porting tests; the decisive control
  is main-side (GW-1's cross-repo test, §7's deferral). Until GW-1, the arms pin the
  gateway code as read this session — each arm's refusal text cites the
  `dataset_services.py` line it mirrors.
- **R-D: the optional `datasets` key in `capture_list` surprises a closed-schema
  consumer.** Falsifier: the suite's catalogue and web consumers reddening on the
  amended schema; additionalProperties-false on the OUTER object with the new key
  declared means consumers that re-validate inputs see it declared, not alien.
- **R-E: dataset growth is unpruned (no retention).** Disclosed (§7); the falsifier
  of the DISCLOSURE is the guide section naming it. The residual is bounded in
  practice by inline-manifest sizes; if a bench outgrows it, S4 owns the policy.

## 11. Memory ledger (proposed at session close, source `increment-designer`)

(a) The gateway mints `ds:` dataset ids PER DISPATCH (occurrence-keyed operation id),
not per acquisition — `acquisition_id` lives inside the manifest as an M10 echo field;
any host mirroring the mint must not "fix" it to per-acquisition (dataset_services.py:167,
otdp_bridge.py:424-440).
(b) `ds:` ids are not valid capture-root path segments (the alphabet refuses `:`);
the standalone family sanitizes `:`→`-` once and verifies the stored manifest's id on
every read — the pattern for any future `:`-bearing id under the root.
(c) The seam's refusal ordering is a wrong-cause discipline: plugin-declaration
refusals precede host-capability refusals (the D6 reorder) — the same lesson as the
"blamed the mock even on a provider transport" fold.
