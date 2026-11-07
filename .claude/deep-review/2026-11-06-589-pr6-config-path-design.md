# Design record — gateway issue #589, PR-6: the config and channel path (fold rows D12–D15)

Date: 2026-11-06. Parent authority: `.claude/deep-review/2026-11-06-589-live-bringup-design.md`
rev 7 (FROZEN), §0 (the standing generality property), §1 (the ledger), §7 (the PR stack),
§8 (the seams). This record carries the four rows the team-lead's fold comment assigned to a
config-and-channel slice: **D12** (the preset home disagrees), **D13** (no host route sets the
sample rate), **D14** (the read-back excludes `threshold_v`), **D15** (the decoder extension
point declares JSON and ships no runner). Verification of those four rows was the first job
and outranks the design; §0 is that verification, and two of the four rows do not survive it
as filed.

Triage: PUBLIC. Mechanisms, invariants and measurements only. The plugin this was measured
against is "a real plugin project"; its vendor, package name, repository URL and descriptor
carried serial appear nowhere. The corpus action names cited (`otdp.logic_analyser.configure`,
`otdp.logic_analyser.decode_annotated`) are the vendored corpus's own identifiers — class
vocabulary, not device identity — and none of them appears in `src/` by design (§0.3 of the
parent record; PR-6 adds none).

Tooling note: the Gortex graph was unavailable for this checkout (probe returned "repository
not tracked"; checkout discovery timeouts, the same condition the parent and PR-3 records
report). All reads were `Read`/`grep`/`sed`/`python3 -c` over JSON. No daemon started, no
tracking changed.

Sources, first-hand: this SDK checkout at `631db75` on `fix/589-live-bringup-generic` — every
`src/`, `tests/`, `template/` and vendored-tree line number below was verified against this
tree this session, and the eight files this record cites most heavily were byte-compared
against the PR-1 worktree's committed state (`.worktrees/pr1-builder-7f3a`, which carries
PR-1 plus folds B and C): identical, so the citations hold on both trees. The gateway
checkout was read READ ONLY for reference semantics
(`/Users/seaton/Documents/src/BenchWeave/src/benchweave/host/otdp_bridge.py`, grep-level
only) — PKG-1 unaffected: nothing in any PR reads the gateway checkout at test or runtime.
The vendored standards were read as bytes (`src/benchweave_sdk/standards/otdp/0.2.4/`,
`standards/plugin-ui/0.4.0/`), never from memory. PR-2 is IN FLIGHT in
`.worktrees/pr2-builder-b41c` with no `_op_invoke` in its seam yet (grep: absent) — every
statement below about PR-2's shapes cites rev 7 §3.1/§3.2 as authority and names the
reconciliation point rather than assuming unwritten code. The fold comment's claims about
the real plugin's shipped tree are RELAYED by the team-lead; this record verifies the SDK
half directly and marks the plugin half as relayed wherever it matters.

---

## 0. Verification verdicts — the four rows, before any design

| Row | Verdict | One-line evidence (all verified this session) |
|---|---|---|
| D12 | **Real, and three-way, not one-way** — the host's runtime preset lane and the SDK's own authoring/presentation pipeline disagree on the HOME, the SETTINGS SCHEMA, and the APPLY SEMANTICS | Host reads `config/presets` (`seam.py:1217`) and applies settings through the PARAMETER lane (`_stageable`, `seam.py:1423-1424`); the SDK's derivation writes presets to `ui/presets` (`cli.py:585-588`) pinning per-slot settings schemas that ARE the configuration ACTION's input schema (`classref.py:3142-3147`); the scaffold's AI-GUIDE documents both homes and tells UI-plugin authors to keep ONE authoritative copy under `ui/` (`template/AI-GUIDE.md.jinja:45-47,64-66`); no runtime consumer of `ui/presets` exists in the standalone stack (grep: `preset_asset_ids` appears only in the check lanes) |
| D13 | **Real today, carried by PR-2, closed at the preset layer by this PR** — the rate slot EXISTS in the vendored catalog as the `configure` action's input; no host route can reach it until `invoke` exists; the host must never name it | `otdp.logic_analyser.configure/1.0.0` input schema: `sample_rate_hz` REQUIRED (`device-profile-catalog.json`, read this session); the host's only configure routes are the generic parameter lane (`parameter_stage`/`parameter_apply`, descriptor `parameters` — `seam.py:1058-1115`) and `preset_apply`; `sample_rate_hz` appears in `src/` only against presentation declarations (`plots.py:416`, `web.py:1244-1251`) — never in a device-configure route, exactly as the fold said |
| D14 | **NOT a defect — withdrawn with evidence** (the row the verification was for): the read filter is DESCRIPTOR-DRIVEN; `threshold_v` is not a parameter, it is per-channel INPUT vocabulary of the `configure` action, and its read-back home is that action's OUTPUT | `parameter_read` filters by `readable_parameters` = descriptor `parameters` rows with `access` in (`ro`,`rw`) (`session.py:141-147`) — no variable name anywhere in `src/` (grep: `threshold_v` absent; every `threshold` hit is power-analysis or web-form vocabulary); the catalog's configure input carries `channels[].threshold_v` as a REQUIRED per-channel field and the OUTPUT carries `effective_configuration.channels[].threshold_v` + `sample_rate_hz` (both schemas read this session) |
| D15 | **A BOUNDARY for the runner — do not build one — plus one real, separable offline gap this PR defers** | The vendored decoder schema says "Structure only… the consuming action is side_effect none over a completed retained acquisition" (`otdp-decoder.schema.json:5`); the corpus prose names the decode ACTION as the only consumer and the host as the renderer (`protocol-decoders.md` §1, §3, main-side 0.2.3 read read-only); the SDK's check lanes carry ZERO decoder validation (grep: `decoders` absent from `validation.py` and `conformance.py`; `classref.py:2944-2953` reads decoder documents for lane derivation only and SILENTLY SKIPS one that fails to load) |

The two withdrawals are first-class results (CLAUDE.md principle 11): D14 is not a defect,
and D15's runner is not a gap. What IS a defect in D15's neighbourhood — the missing offline
PD validation — is real but separable, and §4 defers it with a named carrier rather than
folding it into this slice.

---

## 1. Root causes, verified

### 1.1 D12 — one document type, two homes, two apply semantics

**The host's lane.** `preset_list`/`preset_apply` are catalogue operations
(`catalogue.py:828-838`) served over REST, MCP (`mcp.py:84-90`) and the device page
(`web.py:909-911`, `templates/device.html:53-68`). The list is built from
`_pin_presets` (`seam.py:1214-1221`): every `*.json` under
`package_dir / "config" / "presets"`, digest-pinned at seam CONSTRUCTION
(`seam.py:290`) and re-verified against the bytes on every list/apply
(`seam.py:1261-1268`, `1312-1319`). When the directory is absent the pin set is empty and
`preset_list` returns `{"presets": []}` — **silently** (the fold's worry, confirmed: no
refusal, no warning, nothing names the expected home). `_preset_bytes` on an unknown id
refuses `not_found` "no such preset: {id}" (`seam.py:1294-1297`) — also without naming the
home. The apply path (`_op_preset_apply`, `seam.py:1327-1435`): firmware gate →
`validate_preset` against `descriptor.json` + **`config/settings.schema.json`**
(`seam.py:1370-1373`) → every `settings` key through `_stageable` (**descriptor
PARAMETER** validation, `seam.py:1058-1115`) → `_apply_batch` (write verb + read-back per
parameter, `seam.py:1141-1192`).

**The authoring/presentation lane.** `derive-ui` writes per-configuration-slot settings
schemas under `ui/settings/<slot>.schema.json` and preset scaffolds under `ui/presets/`
(`cli.py:577-588`; `presentation.py:1535-1538`); the user guide documents exactly this
(`user_guide/plugin-sdk.qmd:146`). The derived settings schema is not a parameter schema —
it is the **configuration action's input schema**, effective over the pinned catalog row
tightened by the descriptor's `input_constraints`, carrying the corpus action input `$id`
(`classref.py:3138-3147`: `$id: catalogue_input.get("$id", f"urn:otdp:action:{urn}:input")`).
The preset scaffold pins that schema by `{id, sha256}` and carries `settings: {}` for the
author to commission (`classref.py:3161-3185`). `check-preset` validates such a document
and reports the resolved envelope ("envelope applied: {action}", `cli.py:426-442`) — the
vendored resolver is exact, not heuristic: a settings schema whose `$id` equals a corpus
action's input-schema `$id` resolves to that action; a custom `$id` resolves to `None` and
"lane 1 applies no envelope" (`standards/plugin-ui/contracts.py:142-176`, read this
session). The manifest wires presets as ASSETS: configuration targets carry
`preset_asset_ids`; bindings expose a subset; `check-ui` refuses a binding naming a preset
the target does not declare (`contracts.py:784-796`).

**The three disagreements**, each SDK-side (the plugin did what the SDK's own generated
guidance says):

1. **Home.** The scaffold's AI-GUIDE documents both homes and splits them by audience:
   "For configuration without UI, use `src/<package>/config/` with `settings.schema.json`
   and `presets/`. When UI presents those settings, keep one authoritative copy under
   `ui/settings/` and `ui/presets/` rather than duplicating it"
   (`template/AI-GUIDE.md.jinja:45-47`). A UI plugin that follows its own generated guide
   therefore NEVER populates `config/presets` — and the host's entire preset surface
   (device-page picker, REST, MCP) serves that plugin an empty list, silently. The fold's
   report (the plugin ships `ui/presets`; the list comes back empty) is this mechanism
   observed live. The seam's own docstring calls `config/presets` "the scaffold's
   documented configuration home" (`seam.py:1240-1241`) — true for the no-UI audience,
   false for the UI audience the scaffold also addresses.
2. **Settings schema.** The host validates against ONE fixed document,
   `config/settings.schema.json` (`seam.py:1370-1373`, `authoring.py:400-401`); the
   derivation writes PER-SLOT assets under `ui/settings/` pinned inside each preset
   document (`classref.py:3148-3159`, `3173-3178`). There is no path by which the derived
   per-slot schemas reach the host's validator.
3. **Apply semantics.** The host applies `settings` through `_stageable` — descriptor
   PARAMETER names. A commissioned preset's settings are the configuration ACTION's input
   envelope (`configuration_id`, `channels[].threshold_v`, `sample_rate_hz`,
   `sample_count`, `trigger` for the corpus logic-analyser action — the catalog's own
   required set). Copying such a preset into `config/presets` does NOT make it applicable:
   `_stageable` refuses the first action-shaped key with "no such writable parameter"
   (`seam.py:1063-1067`). The validator passes (the vendored validator checks the settings
   against the PINNED schema, which the action-shaped settings satisfy) and the apply then
   refuses at the parameter gate — a validated-but-inapplicable document, the worst shape
   a conformance surface can have.

**One validator, already shared.** Both lanes validate through
`benchweave_sdk.presentation.validate_preset` → the vendored plugin-ui contracts validator
— "the same bytes the gateway runs" (`presentation.py:354-406`, `authoring.py:429`,
`seam.py:1387-1392`). The document TYPE is one; only the homes and the apply semantics
forked.

**No gateway parity constraint.** The gateway's bridge has NO preset surface at all (grep
of `otdp_bridge.py`: zero `preset` matches; its configure verbs are the generic
`read {parameter}` / `write {parameter, value}` at `:343-344`). The standalone preset lane
is this SDK's own surface, which also means the SDK owns its repair outright.

**Runtime serving is possible with in-tree machinery.** The host loads the presentation
through the SRF-2 loader at plugin load (`session.py:894-912` — an invalid presentation
refuses the load) and projects it once (`HostPresentation`, `server/presentation.py:459-537`),
which exposes the validated `manifest` and `resource_root` — the manifest's asset rows
(id, path, sha256) resolve under that root through the bounded reader (the `preview.css`
precedent, `server/presentation.py:516-524`). Nothing new must be invented to serve the
manifest's preset assets at runtime.

### 1.2 D13 — the rate slot exists; the route is invoke; the host must not know the name

- **The slot exists in the corpus**, not in any descriptor or host constant: the vendored
  catalog's `otdp.logic_analyser.configure/1.0.0` input schema REQUIRES `sample_rate_hz`
  (`number > 0`) beside `channels[]` (each `{channel, threshold_v}`, required),
  `sample_count` and `trigger` (`device-profile-catalog.json`, read this session). The
  catalog row is what a plugin PINS; the host reads it through PR-2's contracts
  resolution.
- **The host's existing configure routes are generic and intact**: the parameter lane
  (`parameter_stage`/`parameter_apply`) dispatches `write {parameter, value}` verbatim
  (`seam.py:1168-1174`) — no host-side slot to decode, no vocabulary. If a plugin declares
  a writable parameter for its rate, the lane already serves it. The fold's other half —
  "the rate write refuses because the rate payload slot is not decoded" — is
  **UNVERIFIED and plugin-side**: nothing in `src/` decodes or refuses any rate payload
  by name; the only host-side refusal such a write can meet is `_stageable`'s "no such
  writable parameter", which fires when the DESCRIPTOR declares no such parameter. What
  the real plugin's descriptor declares is relayed, not read, here.
- **The route that reaches the slot is `invoke`** (PR-2, rev 7 §3.1): `{action_id, input}`
  dispatch with I4 validating the input against the pinned catalog's per-action schema.
  That is where a generic host attaches without knowing any device's vocabulary — the
  catalog knows `sample_rate_hz`; the host never does. The generality directive is
  satisfied by construction: PR-6 adds no action name, no parameter name, no field name
  to `src/` (the archetype arms use invented or corpus-URN vocabulary only).
- **The display-side rate is a different row.** `sample_rate_hz` on the lanes DECLARATION
  (`plots.py:416`, `web.py:1244-1251`) is the composer's rendering rate; the SDK never
  populates it today (`build_lanes_declaration`, `plots.py:257-320`, sets no rate;
  `LanesDeclaration.sample_rate_hz` defaults `None` — `benchweave_ui_html/lanes.py:84`,
  venv read). Populating it from a capture's `sample_interval_s` is display-path work and
  is deferred with its carrier (§7).

### 1.3 D14 — descriptor-driven filter; the vocabulary belongs to the action surface

`parameter_read` (`seam.py:705-741`) builds its known set from
`session.plugin.readable_parameters` — the descriptor's `parameters` rows with `access` in
(`ro`, `rw`) (`session.py:141-147`) — and refuses `not_found` "no such readable
parameter" otherwise. There is NO hardcoded variable list anywhere in the path (grep:
`threshold_v` absent from `src/`; the `threshold` hits are power-analysis parameters and
web form fields — `web.py:257-285`, `analysis.py:1079-1138` — unrelated vocabulary). The
bigger finding the team-lead feared (a device variable name hardcoded in `src/`) does not
exist.

`threshold_v` is per-channel INPUT vocabulary of the corpus `configure` action (required
per channel, catalog input schema) and its read-back home is that action's OUTPUT:
`effective_configuration.channels[].threshold_v` (plus `sample_rate_hz`, `sample_count`)
— the catalog's own output schema, read this session. Surfacing that output is invoke's
job (PR-2's result gates serve the closed envelope verbatim). A plugin that ALSO wants
`threshold_v` readable as a parameter declares it in `parameters` with `access: ro|rw` —
and the host serves it with zero changes. **The row is withdrawn; the guide gains one
clarifying row** (§3) so the next operator does not re-file it.

One residual this verification surfaced, disclosed rather than fixed (§3): the descriptor
schema's access enum admits `wo` (`otdp-device-descriptor.schema.json` `$defs.parameter`,
enum `['ro','wo','rw']` read this session), and the host can operate NO `wo` parameter —
writes are refused because only `rw` stages ("a write-only parameter could never produce
the read-back SW-23 requires", `seam.py:1058-1062`), reads are refused by definition. A
declared-but-unreachable parameter class is the honest cost of SW-23's every-write-is-
read-back rule and stays a disclosed posture, not a defect.

### 1.4 D15 — the boundary is the corpus's own architecture

The vendored declaration schema's description is normative and self-describing
(`otdp-decoder.schema.json:5`): "**Structure only.** A decoder declaration names the
annotation classes and rows a generic renderer draws from, plus the channels and options
the decode action validates against. It grants no authority and gates no physical access:
the consuming action is side_effect none over a completed retained acquisition
(protocol-decoders.md)." The corpus prose (main-side 0.2.3, read read-only; the vendored
0.2.4 schema description carries the same sentences) completes it: the only consumer is
the decode ACTION (`decode/1.0.0` closed trio; `decode_annotated/1.0.0` the
declared-decoder path — both IN the vendored catalog with full input/output schemas, read
this session), its output is a measurement-schema dataset in the annotation event_log
form, and "Only a consuming host proves the **render**" (§7) — the host renders, the
action runs. A host-side runner is not missing machinery; it would be a SECOND authority
the corpus deliberately does not have, and the fold's own note that local decoders inside
the plugin remain possible is the corpus's shape observed correctly. **DON'T-BUILD the
runner.** What the boundary forecloses is recorded in §4.

The real gap in D15's neighbourhood is offline, not runtime: the corpus assigns offline
checks the declaration's well-formedness ("Offline checks prove a declaration
**well-formed and self-consistent**: the schema shape, the row resolution, the pin
resolving inside the package to bytes that hash to `sha256`" — §7), and THIS SDK — the
offline half of the ecosystem — checks none of it: `validation.py` and `conformance.py`
carry zero decoder logic (grep), the descriptor schema validates only the pin's SHAPE
(`otdp-device-descriptor.schema.json` `properties.decoders`, read this session), and
`classref.py:2944-2953` reads decoder documents for lane derivation while SILENTLY
SKIPPING any that fail to load (`except … → line_ids = [] → continue`) — the same
silent-empty class as D12's worry, one lane over. §4 defers this with a named carrier.

---

## 2. The mechanism — one preset lane, both homes, apply through the resolved lane

PR-6 makes the host serve the presets the plugin actually has, and apply each through the
lane its own document declares. One mechanism carries D12 and D13 together: serving
`ui/presets` rows without the action-lane apply would produce a list whose every row
refuses at apply — a lying surface worse than the empty one — so the two rows are one
slice.

### 2.1 Serving (D12): both homes, rows carrying `home`, collisions typed

- **`_preset_rows`** (`seam.py:1239-1290`) gains a second source: the validated
  presentation's manifest. For every manifest target with `kind == "configuration"`, for
  every id in its `preset_asset_ids`, the manifest's asset row (id, path, sha256) resolves
  under the presentation resource root through the bounded reader; the row's `sha256` is
  verified against the bytes on disk at list time (the manifest's own CON-1 pin — the
  same posture the config lane's construction pin serves). Each served row gains
  `home`: `"config"` (file stem under `config/presets`, exactly as today) or `"ui"`
  (the manifest asset id). `_PRESET_ROW` (`catalogue.py:242-250`) gains `home` as an
  OPTIONAL enum key — a disclosed, additive interface change (PR-3's optional
  `datasets`-array precedent).
- **A small helper, not a second loader.** The manifest rows are read by one helper in
  `server/presentation.py` (beside `HostPresentation`, which already exposes the validated
  `manifest` and `resource_root`, `server/presentation.py:506-524`):
  `manifest_preset_assets(package_dir) -> mapping[asset_id, {path, sha256, schema_asset_id, action_id}]`,
  walking configuration targets and their assets. The seam calls it; the FULL validation
  has already run at plugin load (`session.py:894-912`) — the helper reads a validated
  manifest, it does not re-validate the presentation.
- **Collisions typed at construction.** `_pin_presets` (`seam.py:1214-1221`) keeps its
  config-only digest pin and gains one check: a config file stem equal to a manifest
  preset asset id refuses seam CONSTRUCTION with `standalone_preset_home_conflict:`
  naming both homes and the id — the AI-GUIDE's "keep one authoritative copy rather than
  duplicating it" made mechanical (`template/AI-GUIDE.md.jinja:46-47`). The refusal also
  fires at RELOAD against the INCOMING plugin, before the session swap (rev 7 §3.1's
  reload discipline — a conflicted incoming plugin never becomes the served session).
  Construction-time, so `ValueError` — the `profile_contract_*` convention (§5 of this
  record; rev 7 §2.2 pins the convention's reason).
- **The silent empty dies at the source, not by refusing emptiness.** A plugin with no
  presets in either home keeps an honest empty list — an empty preset set is a legal
  state and refusing it would be wrong. What made the emptiness poisonous was that the
  plugin's REAL presets (declared, validated, wired) were invisible; after PR-6 they are
  served. `_preset_bytes`' unknown-id refusal (`seam.py:1294-1297`) amends its message to
  name both homes searched — the diagnosis the fold wanted a week earlier.

### 2.2 Applying (D12+D13): the lane the document declares

`_op_preset_apply` (`seam.py:1327-1435`) keeps its shape and splits at one seam:

1. Firmware gate — unchanged (`seam.py:1344-1357`), before any dispatch, both lanes.
2. Resolve the preset bytes by home (`_preset_bytes` gains home resolution: config stem
   path as today; manifest asset through the helper).
3. Validation source per home: the config lane keeps `config/settings.schema.json`
   (`seam.py:1370-1373`); the ui lane uses the TARGET's settings schema asset
   (`target.schema_asset_id`, resolved through the same manifest helper) — the very
   document the preset's own `{id, sha256}` pin names (`classref.py:3173-3178`). The
   validator call is unchanged: `validate_preset(raw, descriptor_raw,
   settings_schema_raw, firmware)` — the one shared vendored validator.
4. **The lane split** — one call to the already-exported resolver
   (`presentation.py:409-427`):
   - `resolve_preset_action(document, descriptor_raw=…)` resolves → **the action lane**:
     dispatch through PR-2's invoke core with `{action_id: resolved, input: settings}`.
     I1–I5, the result gates, the action deadline and the dataset admission all run — a
     commissioned preset rides exactly the surface a hand-written invoke does. A preset
     whose schema pins an action the descriptor does not declare refuses with invoke's
     own I2 message naming the action (the honest cause — the composition reuses the
     gate, it does not duplicate it). Coherence worth stating: a preset that passed
     `check-preset` was validated against the DERIVED effective schema (catalog input +
     `input_constraints`, `classref.py:3138-3140`), and I4+I5 validate against that same
     composition at dispatch — the offline check and the runtime gate are one rule.
   - resolves to `None` (custom `$id`) → **the parameter lane, exactly as today**:
     `_stageable` per key, `_apply_batch`, read-back rows ("lane 1 applies no envelope"
     — the corpus's own words for this branch).
5. Result: the parameter lane returns `{device_id, preset_id, applied: […]}` unchanged;
   the action lane returns `{device_id, preset_id, action_id, invoke_result: <the closed
   invoke envelope>}` — `_PRESET_APPLY_RESULT` gains both keys OPTIONAL (closed schema
   otherwise; one lane fills one shape, never both).
6. The event row gains `home` and, on the action lane, `action_id`; the
   events-description text amends with the catalogue descriptions.

**The one hard requirement on PR-2's shape (the reconciliation point).** `_op_preset_apply`
holds `_op_mutex` across its whole span (`seam.py:1336`) and `asyncio.Lock` is not
reentrant: PR-6 must call an UNLOCKED invoke core, not the `_op_invoke` handler. PR-2
should therefore factor `_op_invoke` as mutex-plus-argument-validation over an inner
`_invoke_core(action_id, input, correlation)` — rev 7 §3.1 already implies this factoring
when it routes the operation through gates-then-dispatch. If PR-2 ships differently, PR-6
does the factoring itself as its first commit and says so in the PR body; calling the
locked handler instead would DEADLOCK the first action-lane preset apply. The deadlock is
the falsifier of the wrong composition (A11, §7).

### 2.3 What PR-6 deliberately does NOT do

- No new operation, no CLI flag, no subcommand — the catalogue rows, REST routes, MCP
  handlers and HTML forms that exist are the surfaces that change behaviour.
- No AI-GUIDE change: its text stays true after PR-6 (both homes documented; the
  one-copy rule now mechanically enforced). Verified against `template/AI-GUIDE.md.jinja:36-47,64-66`.
- No authoring-lane change: `preset_put`/`preset_get` (`authoring.py:496-528`) keep the
  `config/presets` home — an authoring write into `ui/` would drift the manifest the
  presentation validates against; the ui lane's authoring path already exists offline
  (`derive-ui` scaffolds, `check-preset` commissions, the manifest wires). Deferred
  explicitly (§7).
- No host knowledge of any device vocabulary: the corpus URNs live in the vendored
  catalog and the plugin's pins; `src/` gains none. The generality gate holds by
  absence (PR-6 adds no literals; the gate's denominators do not move).

---

## 3. D14 — the withdrawal record and the disclosure row

The row is withdrawn on the evidence of §1.3. Two carries land with PR-6's docs leg:

1. **The guide row**: the user guide's parameters/readings section gains one paragraph
   naming the TWO read surfaces and their vocabulary homes — `parameter_read` serves
   descriptor-declared `parameters` (access `ro`/`rw`); action-declared configuration
   (the corpus `configure` action, per-channel thresholds and the sample rate among its
   inputs) is read back through that action's `effective_configuration` OUTPUT, served by
   `invoke`. An operator who knows this does not re-file D14.
2. **The `wo` disclosure**: the same section states that `wo` parameters are
   declared-valid per the descriptor schema and unreachable through this host — writes
   require the SW-23 read-back, which a write-only parameter cannot produce. A
   write-without-read-back surface is a deliberate non-goal; if the corpus ever wants
   `wo` operable, that is a main-side ruling (STD-5), not an SDK decision.

No new arm pins D14 beyond the existing behavior (the filter is already pinned by the
seam suite; `tests/server/test_seam.py` and `tests/server/test_control.py` carry the
parameter arms) — the acceptance for D14 is this section's citations plus the guide row
landing in the docs leg.

---

## 4. D15 — the boundary record, and the deferred offline check

**The boundary, stated so it can be cited:** the standalone host NEVER executes a
protocol decoder. A decoder declaration is interpretive METADATA (annotation classes,
rows, channels, options) pinned by digest; the decode ACTION — plugin-side, catalogued,
`side_effect: none`, over a completed retained acquisition — is the only runner; the host
renders the annotation event_log the action returns, using the declaration's
`annotation_rows` for grouping (the corpus's renderer contract). The carriers that make
this boundary FUNCTIONAL are already in the stack: PR-2's `invoke` dispatches the decode
actions (both are in the vendored catalog with full schemas); PR-3's admission persists
their dataset outputs; PR-4's display path renders them. PR-6 adds nothing here and
correctly so.

**What the boundary forecloses** (recorded, not apologized for): a plugin that ships
decoder declarations but no decode action cannot be decoded on any host — its
declarations are render-hints for output nothing produces; the host will never grow a
"decode locally" convenience without a corpus change (STD-5), and the corpus's own
reopen triggers (binary emission PD6, decoder stacking, sample-exact coordinates —
`protocol-decoders.md` §6) are the only doors. Local decoders inside the plugin — the
principal's named option — are exactly the compliant shape: the action may run whatever
library it likes behind its catalogued contract.

**The deferred offline check, with its consumer named.** The consumer that breaks
without it is the plugin AUTHOR whose decoder pin drifts or whose declaration is
schema-invalid: today `check`/`check-ui` pass (no decoder validation exists — §1.4), the
classref derivation silently skips the unloadable document (`classref.py:2950-2953`), the
host renders no decoder lanes with no refusal anywhere, and the gateway's named slice-2
admission mirrors (`protocol-decoders.md` §2, §6) will refuse the same plugin at load the
first time it is presented. That is a silent-empty class defect in the CHECK lane —
SRF-3 territory (the offline encoding must not greenlight what load will refuse) — but
it is SEPARABLE from this slice and adding a new check-lane refusal surface (a STD-4
prefix, conformance fixtures, a prefix-pinning arm) would double PR-6's review surface.
**Deferral with carrier**: a sibling SDK PR on the same issue carrying the offline PD
subset — pin digest verification (package-relative, inside the bundle), validation
against the vendored `otdp-decoder.schema.json`, PD2 row resolution — in the check lane
where `contracts[]` pins are already digest-verified (`validation.py:749+`,
`verify_provider_pin`, the precedent), plus one line making the classref derivation's
skip LOUD (a `cannot_derive`-class row naming the unreadable decoder instead of a silent
`continue`). The main-side slice-2 mirror remains the gateway's own row. PR-6's body
names this deferral so the row cannot be dropped silently.

---

## 5. seam.py and the merge sequence

**PR-6 depends on PR-2** (the invoke core) and is disjoint from **PR-3** (dataset
admission, capture verbs, the services wrapper) and **PR-4** (the display path). It can
land any time after PR-2 merges; it touches none of PR-3's code.

The complete touch list in `seam.py` — one contiguous block plus two one-line neighbours:

| Function | Change |
|---|---|
| `_pin_presets` (`seam.py:1214-1221`) | keep config digests; ADD the construction-time collision check against the manifest asset ids (via the new helper) |
| `_preset_rows` (`seam.py:1239-1290`) | add the manifest lane (rows with `home: "ui"`, sha256 verified against the manifest pin at list time); config rows carry `home: "config"` |
| `_preset_bytes` (`seam.py:1292-1320`) | resolve by home (config stem path / manifest asset through the helper); unknown-id message names both homes |
| `_op_preset_apply` (`seam.py:1327-1435`) | per-home validation source; the `resolve_preset_action` lane split; the action lane composes the invoke core; result keys |
| `seam.py:290` (`__init__`) | unchanged call, new refusal can escape it — construction now raises `standalone_preset_home_conflict:` |
| `seam.py:1623` (`_complete_reload`) | the collision check re-runs against the INCOMING plugin before the session swap (same call site, already re-pins) |

Outside `seam.py`: `server/presentation.py` (the `manifest_preset_assets` helper),
`catalogue.py` (`_PRESET_ROW` + `_PRESET_APPLY_RESULT` optional keys, two descriptions),
`mcp.py` (nothing — the handlers pass arguments verbatim), `web.py` (nothing — the device
picker consumes the list as-is), `invariants.md` (STD-4 entry), `user_guide/plugin-sdk.qmd`
(obligation 1 + the D14 rows), the events description. PR-2 owns the invoke block and the
new contracts module; PR-3 owns `_resolve_capture_verb`, `_op_capture_*`, the session
wrapper — no overlap with the preset block (`seam.py:1214-1435`).

---

## 6. Invariant and cross-surface impact

- **STD-1/2/3/5/6**: untouched — no vendored motion; the vendored catalog, decoder
  schema and plugin-ui contracts are READ (through pins and the shared validator),
  never copied into `src/`; `sync-standards --check` green throughout.
- **STD-4**: grows ONE prefix — `standalone_preset_home_conflict:` — a `ValueError` at
  seam construction and at reload-before-swap (the `profile_contract_*` convention; NOT
  a connect-boundary `RuntimeError` — it is not a connect-time failure, and rev 7 §7's
  type table stays two-convention). Every apply-lane refusal REUSES existing surfaces:
  invoke's I2/I4/I5 codes and `_stageable`'s messages, the firmware gate's `conflict`,
  `_preset_rows`' existing `digest_mismatch`/`invalid_request` findings. `invariants.md`'s
  STD-4 entry amends with the new prefix and its type pin.
- **SRF**: (i) `preset_list`'s row schema gains optional `home` and `preset_apply`'s
  result gains optional `action_id`/`invoke_result` — disclosed interface changes to
  served shapes, additive-optional, existing consumers unaffected (PR-3's R-D posture);
  (ii) SRF-2 unchanged and reinforced — the ui-lane bytes the host now serves are the
  same bytes `check-ui` validated, read through the loader-validated manifest; (iii) a
  draft row for the next invariants pass: "the host serves a plugin's declared presets
  from BOTH documented homes and refuses an id duplicated across them — the scaffold's
  one-authoritative-copy rule, mechanically enforced".
- **PKG**: no new dependencies; wheel contents unchanged.
- **Scaffold output**: UNCHANGED — no template byte moves, the R-2 golden fixture does
  not move (verified: the AI-GUIDE text PR-6 enforces is already the committed text).
- **Drift obligations**: 1 (user guide — the preset/parameters sections and the D14
  rows, via the `document-writer` agent in the STE100 register); 6 (behavior change →
  the arms of §7 name the modules); the catalogue↔handlers↔events-description
  descriptions amend (no new operation, so no new quintet row); README and CLI surface
  unchanged.
- **CI cost**: none beyond the suite — full `pytest -q` (raw collected count), ruff,
  strict mypy (`files = ["src"]`), `sync-standards --check`, `--version` smoke. No new
  job, no marker partition; all arms hermetic over the starter-project machinery
  (`tests/server/conftest.py::starter_project`).

---

## 7. Acceptance — pre-committed, with denominators and kill directions

Stated BEFORE any arm is written. New module `tests/server/test_preset_homes.py` (seam
construction lives under `tests/server/` per the rev-7 census), over the starter-project
machinery (`tests/server/conftest.py:252-297` in the PR-3 record's citation;
`_patch_descriptor` for descriptor surgery). The fixture plugin carries a presentation
whose manifest declares one configuration target with one preset asset and one settings
schema asset — the derivation's own output shape (`classref.py:3142-3186`) written as
fixture bytes; the configuration action is the vendored corpus's own `configure` URN with
its catalog input schema as the settings schema, so `resolve_preset_action` resolves
exactly as it does for a real commissioned preset (the resolver matches corpus
input-schema `$id`s — `contracts.py:142-176`; an invented `$id` would resolve to `None`
and turn every action-lane arm into a parameter-lane arm, which is precisely the
fixture-bug kill direction). The adapter is a recording fake: it captures invoke
dispatches and parameter writes. Amended: `tests/server/test_seam.py` (construction
collision, unknown-id message), `tests/server/test_catalogue.py` (both schema changes),
`tests/server/test_control.py` (parameter-lane regression), the events-description pin
wherever its text is pinned.

**Twelve arms, pre-committed:**

- **A1** (D12 union): the fixture plugin (manifest preset, NO `config/presets` directory):
  `preset_list` returns ONE row, `home: "ui"`, `sha256` equal to the manifest asset row's
  pin, and the bytes on disk hash to it.
- **A2** (D12 config regression): a plugin with only `config/presets` (no presentation):
  the list serves `home: "config"` rows with construction-pinned digests, exactly as
  today — the existing preset arms in `tests/server/test_seam.py` / `test_control.py`
  stay green unamended except for the row's new key.
- **A3** (D12 collision): the same id in both homes (a config stem equal to a manifest
  asset id): seam construction refuses `standalone_preset_home_conflict:` (a
  `ValueError`, message naming both homes and the id); at reload, the incoming
  conflicted plugin refuses BEFORE the swap and the previous session keeps serving.
- **A4** (D12 drift): a ui-lane preset whose bytes drift from the manifest pin: list and
  apply both refuse (`digest_mismatch` finding), and no apply dispatch occurred.
- **A5** (D12+D13 action lane): a commissioned manifest preset (settings = the corpus
  action's input, validated by `check-preset`'s own validator in the fixture setup):
  `preset_apply` returns `action_id` + `invoke_result` (the closed envelope), the
  adapter recorded ONE invoke dispatch `{action_id, input: settings}` verbatim, and ZERO
  parameter writes occurred.
- **A6** (D13 genericity): the same arm's assertion set — the input field values
  (rate-equivalent included) reached the adapter VERBATIM through a host that nowhere
  names them; the arm's fixture vocabulary is corpus-URN or invented, never the real
  device's.
- **A7** (parameter lane regression): a config-lane preset with a custom-`$id` schema
  (no envelope): applies through `_stageable` + `_apply_batch` with read-back rows, as
  today.
- **A8** (validation parity): a ui-lane preset whose settings fail its pinned schema:
  `invalid_request` with the validator's findings; nothing dispatched, no bytes written.
- **A9** (honest cause): a preset pinning a corpus action schema for an action the
  descriptor does NOT declare: the refusal is invoke's I2 shape naming the action (the
  composition reuses the gate).
- **A10** (firmware gate, both lanes): a firmware-mismatched preset refuses `conflict`
  before ANY dispatch, on the action lane as on the parameter lane.
- **A11** (the deadlock falsifier): `preset_apply` over the action lane completes while
  the op mutex is held across the span (the arm's own completion inside the test
  timeout IS the control — calling the locked invoke wrapper deadlocks it).
- **A12** (D14 pin): the descriptor-driven filter stays pinned — a `ro` parameter is
  readable, a `wo` parameter is in NO readable set and REFUSES staging with the
  existing message (the disclosure row's anchor, so the `wo` posture cannot drift
  silently).

**Mutations (each reddens its named arms; both runs pasted in the PR):**

- **M-A** revert the manifest lane in `_preset_rows`/`_preset_bytes` → A1, A4, A5, A6,
  A9 (every ui-lane arm); A2/A7 stay green — the config lane is isolated.
- **M-B** drop the construction collision check → A3.
- **M-C** route the action lane through `_stageable` (the pre-PR-6 behaviour) → A5, A6,
  A9 redden ("no such writable parameter" — the lying-surface refusal this PR removes).
- **M-D** call the locked `_op_invoke` handler instead of the core → A11 (timeout/
  deadlock).
- **M-E** skip the firmware gate on the action lane → A10.

**Kill directions:** any mutation leaving its named arms green kills the claim — fix the
mechanism or the fixture, never weaken the arm. A1 green under M-A means the fixture's
config home leaked a row (a fixture bug, not a pass). A5 green under M-C means the
fixture dispatches through parameters anyway (fixture bug). A9 green under M-C would mean
the I2 refusal fires from the parameter path — inspect before trusting. A mutation
reddening more than three arms OUTSIDE its named set means coupled fixtures — re-slice
before trusting any green. **D14 and D15 accept no new mechanical arms**: D14's acceptance
is §1.3's citations plus the guide row landing; D15's is §4's boundary record plus the
named deferral — an honest negative, first-class.

**Denominators:** the raw `pytest -q` collected count (read from redirected output, never
a filtered summary line — the rtk lesson), pasted in the PR beside the twelve-arm count
and the amended-module list. The generality gate's own denominators do not move (PR-6
adds no literals under `src/`; the gate keeps holding by absence — and A6's fixture
vocabulary discipline is what keeps the gate's absence honest at the test layer).

**Live leg (operator-run, NOT gating):** the real plugin, after its plugin-repo pairing
rows land (its catalog reshape is a plugin-repo row per the parent record §3.1): its
commissioned `ui/presets` documents appear in `preset_list` and one applies end-to-end
through the configure action — the fold's original complaint observed fixed. Until the
plugin's rows land, the fixture arms are the proof and the typed
`profile_contract_invalid:` posture (parent record) is unchanged by this PR.

---

## 8. Top risks, each with its falsifier

- **R-1: PR-2's invoke ships without a lock-free core** (the §2.2 requirement). PR-6
  BLOCKS on PR-2's merge and does the factoring itself if needed — the deadlock (A11) is
  the falsifier of shipping the wrong composition; a review finding PR-6 calling a
  locked handler is an immediate revert.
- **R-2: the manifest helper diverges from the loader's manifest** (the seam reads
  `ui/manifest.json` while `HostPresentation` reads the envelope's manifest — a path or
  envelope/manifest confusion). Falsifier: the helper is built beside `HostPresentation`
  over the same validated inputs, and A1's sha256 equality against the MANIFEST's OWN row
  is the control — a wrong-path read hashes different bytes or finds no file.
- **R-3: an optional-key schema change surprises a closed-schema consumer.** Same class
  as PR-3's R-D; falsifier: the catalogue and web consumers in the suite reddening on the
  amended schemas (both keys declared, outer objects stay `additionalProperties: false`).
- **R-4: the collision check false-positives a legitimate dual home.** The guide's
  one-copy rule says there is no such thing; the refusal names both homes so the operator
  resolves it in one look. If a real plugin legitimately needs the same id in both homes,
  THAT is the evidence to re-open the row — not to widen the check.
- **R-5: action-lane presets launder a stale configuration** (a preset commissioned
  against an older descriptor applies to a newer device). Guarded by layers that already
  exist and are not PR-6's to weaken: the SRF-2 load revalidates the presentation against
  the CURRENT descriptor (a stale preset can refuse the whole load — the standing
  posture), the firmware gate runs before dispatch, and I4/I5 validate the input against
  the CURRENT pinned catalog at dispatch. Falsifier for the layering claim: A8/A10.

---

## 9. Memory ledger (proposed at session close, source `increment-designer`)

(a) The SDK documents TWO preset homes with an audience split (`config/` no-UI,
`ui/` with-UI — `template/AI-GUIDE.md.jinja:45-47`) while the standalone host served only
`config/` — every UI-conformant plugin got a silently empty preset surface; the repair
serves both and types the collision (PR-6). The pattern: when a scaffold documents two
homes for one document type, some runtime surface is already reading only one.

(b) A plugin-ui preset document's `settings` are the CONFIGURATION ACTION's input
envelope (the derived settings schema IS the catalog action input schema with its `$id`,
`classref.py:3142-3147`) — not parameter settings; any host applying presets through a
parameter lane refuses every commissioned preset. The corpus's own resolver
(`resolve_preset_action`) is the lane selector: corpus `$id` → action lane; custom `$id`
→ parameter lane ("lane 1 applies no envelope").

(c) D14 withdrawn, with the reason worth keeping: `threshold_v` and `sample_rate_hz` are
INPUT vocabulary of the corpus `configure` action and their read-back home is its
`effective_configuration` OUTPUT — `parameter_read`'s descriptor-driven filter excluding
them is correct, not a bug; the host-side genericity proof is that `src/` names neither.

(d) The decoder boundary in one sentence: the declaration is structure, the decode ACTION
is the runner, the host renders (otdp-decoder.schema.json:5, protocol-decoders.md §1/§3/§7)
— and the SDK's offline PD checks are still absent while the classref derivation silently
skips unloadable decoder documents (classref.py:2950-2953): a silent-empty defect one lane
over from D12, deferred with a named carrier.

---

## 10. Build record (2026-11-07, append-only; the frozen bytes above stay as committed)

Head: `pr6-589-config`, built on `origin/pr4-589-format` (`975cbd5`). The mechanism
shipped as §2 designs it — both homes served, rows carrying `home`, the collision typed
at three doors, the lane split through the exported resolver composing the lock-free
`_invoke_core`, the catalogue keys additive-optional, the guide row landed (§3's two D14
carries and the homes/lane prose, STE register). What the real code corrected:

1. **The prefixes, and their count.** Two prefixes minted, not one:
   `standalone_preset_home_conflict:` (a `ValueError` at seam construction, at reload
   against the incoming plugin BEFORE the swap, and at the authoring `preset_put` before
   any byte is written) and `standalone_presentation_unreadable:` (a `ValueError` when
   the manifest walk cannot read documents the load already validated — bytes drifted or
   a symlinked component appeared). §6 said "grows ONE prefix"; the alternative to the
   second was a bare-prose `ValueError` (a STD-4 break) or a silent `{}` (D12's own
   defect class). A package with NO presentation returns `{}` without refusal — the
   honest empty, distinct from an unwalkable one.
2. **The collision check's reload site is NOT "the same call site, already re-pins"
   (§5).** In the real `_complete_reload`, the `_pin_presets()` re-pin runs AFTER the
   session swap — a refusal there leaves the conflicted plugin as the served session,
   exactly what §2.1 forbids. The check is therefore hoisted into the PRE-swap block
   beside `resolve_invoke_contracts`/`check_action_budget_feasibility`, whose existing
   `except ValueError` wraps it as the typed "reload refused, the previous version
   stays loaded" refusal. The post-swap re-pin still runs (defests + manifest rows).
3. **"Manifest target" is "binding-catalogue target".** Configuration targets live in
   `binding-catalogue.json` (`catalogue["targets"]`); the ui-manifest carries assets,
   bindings and pages. The walk reads targets from the catalogue and asset rows from
   the manifest — the mechanism §2.1 describes, the document names corrected.
4. **The parameter lane's result gains `home`.** §2.2.5 said the parameter lane returns
   its shape "unchanged", but §2.2.6 requires the EVENT row to carry `home`, and
   `_event_data` derives "from the operation's own result — never a second source of
   truth". The honest resolution: both lanes' results carry `home` (schema-declared,
   optional; consumers unaffected), and the event row copies it. One lane still fills
   one lane-shape — `applied` or `action_id`+`invoke_result`, never both.
5. **A8 realized as schema-asset drift.** The load-time presentation check validates
   every target-declared preset against the target's schema with firmware `None`, so a
   PRISTINE ui-lane preset whose settings fail its pinned schema cannot pass a load —
   the pristine-invalid case is unconstructible by design. The reachable drift is the
   schema asset's bytes after construction; the arm tampers them and the SHARED
   validator answers `invalid_request` with its findings (digest_mismatch naming
   `preset.settings_schema.sha256`), nothing dispatched.
6. **A9 realized on the config home.** A presentation target referencing an
   undeclared action is itself a load refusal (`capability_mismatch` in the vendored
   check), so a UI-lane A9 cannot exist either. The arm commissions a CONFIG-lane
   preset pinning the corpus configure input `$id` against a descriptor that declares
   invoke + contracts but not the configure action: the resolver still resolves the
   corpus `$id` (it reads the SERVED corpus, not the pin), the lane composes
   `_invoke_core`, and I2 refuses naming the action — the composition reusing the gate,
   exactly §7's claim, from the other home.
7. **The fixture pins the vendored corpus pair verbatim, with the corpus's own pin
   ids.** A plugin-authored pin id (`urn:example:...`) on the vendored catalog trips
   the #556 `pinned_id_shadow` refusal at load (the catalog's embedded action `$id`s
   shadow the served corpus). The corpus examples' own convention — `urn:otdp:`-prefixed
   pin ids, which the presentation's pinned-document merge skips by design — carries
   the vendored pair into the invoke resolution without shadowing. The fixture's
   descriptor also switches to `firmware_policy: "commissioned"` (no descriptor-side
   list): the load-time preset check judges with firmware `None`, and a listed policy
   refuses that arm.
8. **A third collision door beyond §2's touch list.** `preset_put` (the authoring
   writer) could create the dual-home state at runtime, falsifying the mechanical
   enforcement §6's SRF draft row claims. The guard is one check in `_preset_put`
   (before the write, raising `AuthoringError` carrying the prefix) plus a mirror in
   `repin_preset` (the seam's own writer) and a public `manifest_preset_ids()`; the
   arm pins refuse-and-nothing-written. §2.3's "no authoring-lane change" meant the
   authoring HOME stays `config/presets` — it stays.
9. **`manifest_preset_assets(package_dir)` as §2.1 wrote it**, reading the three
   documents the loader validated (envelope → manifest under the resource root →
   binding catalogue) through the bounded reader. The row gains `schema_path` (the
   target's settings-schema asset resolved) — §2.2.3's "resolved through the same
   manifest helper" needs the bytes' path, not only the id.

The adapter fixture gained `INVOKE_ARGUMENTS` (the verbatim invoke dispatch arguments,
beside the verb `CALLS` list) — verb names alone cannot prove A6's verbatim claim.

---

## 11. Fold record (2026-11-07, append-only; the frozen bytes above stay as committed)

Three independent review lanes ran against head `91e5a25`; this section is the
single fold wave answering every finding. New head after the fold: the commits
atop `91e5a25` on `pr6-589-config` (this section travels with them).

### 11.1 The HIGH — the swap window and the unserialized authoring write

**Mechanism (reviewer-observed, reproduced deterministically).**
`_complete_reload` awaits mid-swap (`seam.py:2149` → `session.py:1278`,
`await self.close()` inside `reload_plugin`), while the authoring `preset_put`
(`authoring.py`, synchronous, no lock) can land in that window: its collision
guard reads the STALE pre-swap `self._manifest_presets`, writes
`config/presets/<colliding-id>.json`, and `repin_preset` pins it against the
same stale rows. After the swap, the re-walk (`seam.py:2164`) plus
`self._preset_digests = self._pin_presets()` (`seam.py:2167`, OUTSIDE the
pre-swap `try`) re-ran the collision check over a FRESH glob — the interleaved
file is now in it — and raised the raw `ValueError` AFTER the session swap:
the `except SeamError` in `reload_plugin` never runs (no `refused` event,
`reload_state` stays `None`), the session IS the new plugin,
`_manifest_presets` IS the new walk while `_preset_digests` keeps the stale
pin set plus the repinned id — and `preset_list` then serves that id from BOTH
homes with different sha256s, the exact state the prefix exists to forbid.

**Fix, both halves as adjudicated:**

1. **The post-swap section is now incapable of refusing.** The re-walk is
   DELETED — `self._manifest_presets = incoming_presets` reuses the pre-swap
   walk (the served plugin IS the walked plugin; same object, same
   `package_dir`) — and `_pin_presets(stems=incoming_stems)` pins only the
   stems the pre-swap scan already cleared: no collision check on that path
   (the scan cleared exactly those stems), and a stem whose file vanished or
   grew unreadable in the window is simply not pinned. What that does not
   catch, stated: a config preset DROPPED into the window (by an external
   filesystem writer) is likewise not pinned and stays unserved until the
   NEXT reload, whose pre-swap scan refuses the collision typed.
2. **The authoring write is serialized.** `StandaloneSeam.op_mutex` exposes
   the op-vs-reload lock; `_preset_put` is now `async` and holds that mutex
   across its whole span (guard → validation → write → re-pin), so it cannot
   interleave with the swap; after a reload it waits, then reads the
   POST-swap manifest rows and refuses typed with nothing written.

**Arms (in `tests/server/test_preset_homes.py`, appended after the authoring
arm):**

- **F1** (`test_f1_swap_window_collision_neither_escapes_nor_serves_both_homes`):
  a deterministic injection — the session's `reload_plugin` (the swap call the
  seam awaits) writes the colliding config preset as the swap begins, exactly
  between the pre-swap scan and the post-swap re-pin. RED on `91e5a25`: the
  raw `ValueError: standalone_preset_home_conflict: …` escaped from
  `seam.py:2167`. GREEN after: status `reloaded`, `reload_state` set, the id
  served exactly once (`home: "ui"`), and the FOLLOW-UP reload refuses typed
  (the window-written file is not silently accepted forever).
- **F2** (`test_f2_preset_put_serializes_against_the_reload_swap`): the
  migration shape — the on-disk presentation is rewritten to declare a NEW
  preset asset id (`migrated-capture.json`, a second `_build`'s digest-chained
  presentation bytes over the same descriptor; the fixture builders gained a
  `preset_id` parameter), the reload parks INSIDE the window, and a valid
  `preset_put` of the new id runs concurrently. RED on `91e5a25`: the put
  SUCCEEDED against the stale guard, the file landed, and the post-swap
  `_pin_presets()` raised the raw conflict (`seam.py:2167`) after the swap.
  GREEN after: the put waits for the reload, refuses
  `standalone_preset_home_conflict` with nothing written, and the list serves
  the migrated id once from `ui` beside the config-home `seed` row. A
  mutation check (the `async with seam.op_mutex` neutralized, `cp`-backed)
  reddens F2 with the put landing — the mutex is the load-bearing half.
  F2's first draft (two projects via distinct package dirs) PASSED on
  `91e5a25` — the post-swap glob never sees a write into a different
  package — and was rebuilt as the single-project migration above.
- **F3** (`test_f3_event_row_counts_only_what_a_lane_measures`): see 11.3.

The pre-existing `self._presentation = self._presentation.__class__(…)` at
`seam.py:2150` (unchanged by PR-6, present before it) also runs `check_ui`
post-swap and can raise; it is the same family as the disclosed row in 11.6
and is carried there, not fixed here.

### 11.2 MEDIUM — record corrections (the code is right; the record overstated)

**The `applied` demotion is a breaking change for schema-promised consumers,
not "additive-optional … consumers unaffected"** (§6 SRF(i) and build record
item 4 both say so; item 4's phrasing "consumers unaffected" is the error).
`_PRESET_APPLY_RESULT` previously REQUIRED `applied`; a consumer written
against that advertised schema was promised `applied` always, and action-lane
results omit it. The demotion itself is CORRECT (the action lane has no
applied rows; requiring it would force a fabricated empty array) — but the
honest classification is: an additive-optional REQUIRING set change that
breaks closed-schema consumers keyed on `applied`, the same class PR-3's R-D
named. Consumers must branch on `action_id`/`invoke_result` presence. The
frozen sections stand as committed; this paragraph is the correction of
record.

**The STD-4 parenthetical** (`docs/internal/invariants.md`): the entry cited
the `profile_contract_*` construction/reload convention while listing the
authoring `preset_put` door in the same breath. That convention is pinned to
construction/reload (`invoke_contracts.py`); the authority covering the
authoring site is `AuthoringError` — a `ValueError` subclass carrying `code`
(`authoring.py:50`) — translated to a typed error result by the tool wrapper.
The parenthetical now says so; the code was already correct.

### 11.3 LOW — dispositions

1. **`templates/device.html` apply hint** claimed every apply "writes and
   re-reads each setting" — false for action-lane presets (one `invoke`, zero
   parameter writes). Replaced with a two-sentence hint naming both lanes.
   Host UI prose, not scaffold output: no golden fixture moves (grep: no test
   pins the sentence).
2. **`events_get`'s catalogue description** now carries the §2.2.6-promised
   amendment: "a preset row names its home and, on the action lane, the
   dispatched action id". The family enumeration test
   (`test_events.py::test_events_get_description_names_every_published_family`)
   stays green — the family words are unchanged.
3. **`applied_count` on action-lane event rows** made honest by omission: the
   parameter lane keeps `applied_count` (the count it measures); the action
   lane carries `action_id` and NO `applied_count` — a zero there asserted a
   measurement the lane never made (one dispatch, zero write/read-back rows),
   which is worse than absence because a watcher reading that field alone
   reads "nothing happened". Pinned by **F3** (action lane: `action_id`
   present, `applied_count` absent; parameter lane over the setpoint fixture:
   `applied_count == 1`, `action_id` absent). RED on `91e5a25`: the action
   lane's row carried `applied_count`.
4. **`standalone_presentation_unreadable:` documented surface corrected**
   (invariants STD-4 + the helper docstring in `presentation.py`): it does
   NOT fire on construction drift — `HostPresentation`'s `check_ui` reads the
   same documents first (drift answers `preview_invalid_presentation:`, a
   symlinked component `path_symlink_component:`, unparseable bytes a bare
   `DocumentError`). Its live doors are the reload PRE-SWAP walk and direct
   helper calls; the construction call site serves it only for bytes that
   change between those two calls. The prefix itself STAYS (an earlier
   deletion decision was reversed).
5. **§2.3's dangling "(§7)" deferral pointer**: this record's §7 is the
   acceptance section and carries no authoring deferral — §4 carries the D15
   offline-PD deferral and §1.2 defers the display-rate with its own carrier.
   The posture "runtime `preset_put` writes only the config home" is carried
   HERE (this section) plus the parent record's §7 PR stack (rev 7), where a
   ui-home authoring-write slice is an unassigned row on the same issue; the
   collision guard PR-6 added (build item 8) enforces the one-copy rule at
   that door without widening the write home.
6. **Drift-obligations row 14** now names the operator-facing templates and
   the events description's preset sentence in the move-as-one-motion list,
   so the next lane-semantics slice cannot miss them (this fold fixed exactly
   that miss).
7. **The collision refusal remedy wording** (all four messages) amended from
   "keep one authoritative copy" to "keep one authoritative copy — delete a
   duplicate, or rename one of two distinct presets": the old wording
   presumed duplication, but the migration case is id-equality between two
   DIFFERENT presets, whose honest fix is a rename. Short, true, both cases.

### 11.4 ACCEPT with recorded note (no behaviour change)

1. **The generated AI-GUIDE** teaches "keep one authoritative copy" as
   ADVICE without the load-refusal consequence. Noted; the scaffold is SRF-1
   pinned and unchanged by design. The guide's operator-facing counterpart
   (`user_guide/plugin-sdk.qmd` §preset-homes, PR-6's rows) DOES state the
   refusals, so the consequence is documented where prose moves are cheap.
2. **`manifest_preset_assets` resolves first-wins silently** when two
   configuration targets declare the SAME preset asset id, making the
   target-schema association binding-catalogue-order-dependent (the preset
   validates at load against EVERY declaring target's schema —
   `session.py`'s load-time check — so apply-time is a subset; the
   order-dependence is which target's `schema_asset_id`/`action_id` ride the
   served row). Accepted as disclosed behaviour, recorded here; if a real
   plugin ever declares one preset under two configuration targets, THAT is
   evidence to reopen, not to widen the walk.
3. **`repin_preset`'s guard raises a bare `ValueError`** that the authoring
   tool's `except AuthoringError` would not catch if it fired post-write —
   unreachable in-process today because no `await` sits between the put's own
   guard and the write+repin inside the mutex-held span. Recorded as
   defence-in-depth only; not widened to `AuthoringError` (the seam is not an
   authoring module and the value would be cosmetic at this door).

### 11.5 Explicitly NOT this slice's work

A pre-existing STD-4 gap, recorded as its own row with a named carrier: a
bare unprefixed `DocumentError` (the vendored contracts module's parse
failure) escapes `StandaloneSeam.__init__` when presentation bytes are
unparseable — `HostPresentation`'s `check_ui`/`load_validated_preview_inputs`
raise it before any seam-level translation. It PRE-DATES PR-6 (the seam
construction path and its call site are PR-6 context, not PR-6 hunks), is not
caused by PR-6, and the correct motion is to type the layer that FIRES — wrap
the `HostPresentation` construction call site in `seam.py` (`__init__` and
`_complete_reload:2150`, the same wrapper serving both) with a typed
translation. Carrier: a sibling SDK row on gateway issue #589, alongside the
D15 offline-PD slice; NOT fixed here.

### 11.6 Verification (this fold)

RED on `91e5a25` (raw, quoted in the lane report): F1 and F2 each end in
`ValueError: standalone_preset_home_conflict: …` escaping from
`src/benchweave_sdk_server/seam.py:2167`; F3 in
`AssertionError: assert 'applied_count' not in {…action_id…}`. GREEN after the
fix: `tests/server/test_preset_homes.py` 15 passed (12 prior arms + F1–F3).
Gates and the full battery ran serially from the worktree root with
`UV_PROJECT_ENVIRONMENT=venv`; raw counts in the lane report. The generality
gate's floors hold with counters risen naturally (no gate edit).

### 11.7 Addendum (2026-11-07, later the same day): the lane-1 repros, read as evidence

Lane 1's scratch repros (`/private/tmp/refute1_pr6/`, outside the branch by
instruction) were read after the fold landed. `attack_reload_race.py`'s
instrument patches `seam._session.close` with a signaling wrapper that sleeps
50 ms — WIDENING the real window (the `await adapter.close(context)` inside
`PluginSession.close`), not creating it, as the reviewer stated. The F2 arm's
instrument is the SAME injection point held deterministically: it parks the
seam's swap await (a patched `session.reload_plugin`) on an `asyncio.Event`
with no sleep, and its scenario shape (single project grown in place to
declare a new manifest id — their `midrace.json`, this fold's
`migrated-capture.json` — with a valid `preset_put` of that id inside the
window) is the repro's shape arrived at independently after the two-project
draft failed to redden. `attack_window.py`'s W1-W7 probes are the evidence
behind §11.3.4's mapping; the two files that carry it verbatim
(`docs/internal/invariants.md` and the `manifest_preset_assets` docstring)
were tightened after the fold to name the shadowing shapes exactly:
`preview_invalid_presentation: digest_mismatch` for drift,
`path_symlink_component:` for a symlinked component, and a bare
`DocumentError` (a `ValueError` subclass but unprefixed, pre-existing) for
unparseable bytes. The prefix is KEPT and the walk is NOT reordered ahead of
`HostPresentation` (declined). Two probe observations sit outside this fold's
findings and are named here only so they are not lost: W7 (a parseable,
readable manifest whose bytes were tampered without re-pinning the envelope)
constructs and serves, because the helper does not verify the manifest
against the envelope pin — the SRF-2 load-time validation is the layer that
owns envelope-pin agreement; and attack 5 (a preset pinning the corpus input
`$id` while the target's schema asset bytes are a permissive custom schema)
was a load-time disagreement probe. Both were adjudicated by the review wave,
not by this fold.
