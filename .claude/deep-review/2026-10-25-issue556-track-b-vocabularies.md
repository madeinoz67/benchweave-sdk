# Issue #556 Track B: the six vocabularies composed (closing parent record D1)

Status: designed 2026-10-25 in `.wt/556-lane-b-r8w2` (branch
`feat/556-vocabularies`, base `origin/main` `99ecd774`; SDK submodule pin
`88dcc4d` = benchweave-sdk 0.21.0, whose vendored family tree already serves
`plugin-ui-class-reference` 0.4.0 as active). Parent record:
`.claude/deep-review/2026-10-22-issue541-classref-composition.md` §6 row D1
(the reopen trigger this track answers), §3 (the three layers), §4 (the
honesty mechanism). Track A (gateway mirror for composed/residual actions,
task #170) is a concurrent lane; this track serializes behind it on the
mirror leg only (B7 below).

Triage check (`.claude/deep-review/README.md`): public. Invented fixture
names only (Meridian M-400, Veridian); the motivating community plugin is
cited by issue reference per CLAUDE.md §4.

**Zero deferrals within the six.** Every vocabulary below lands a layer-2
declaration path and a layer-3 residual rule in this run, or lands an
honest terminal state with the evidence for why a surface would be
dishonest (V5's decoder-on-analog case). The one thing this track refuses
to invent — vendor-minted PAGES — is not one of the six; it is the
parent record's existing D2 (the reference-less device, fork F1, owner
ruling pending), and this record extends D2's boundary by exactly one
sentence rather than reopening it.

## 0. Premise check — what reading the code says about issue #556's framing

The premise ("the six vocabularies each need what the action vocabulary
has") holds, with two corrections the design carries:

1. **The six are not six symmetric gaps.** Four of them (procedures,
   settings idioms, datasets, channels) have members that are ACTIONS or
   channel declarations — and the action vocabulary's post-#541 machinery
   already derives a control for every declared action without refusal
   (SDK `classref.py::_derive_controls`, plan rows `resolution:
   catalog|composed|custom`; `tests/test_classref_acceptance.py::test_a2_every_declared_action_resolves`).
   What none of them can do today is compose a MEMBER SURFACE — a
   procedure/configuration/dataset binding and target, a second channel
   role's lanes, a hosted decoder lane, a computed variable in the dataset
   shape. Surfaces come from the corpus reference's `slots`/`pages`, which
   a vendor cannot extend, and the canonical validator admits
   non-observation targets only for actions a served profile row lists
   (`src/benchweave/presentation/contracts.py::_target_findings:472-481`:
   `action not in profile.required_actions + optional_actions` →
   `capability_mismatch`). So the gap is structural, not a renderer gap.
2. **The honest seam already exists in the validator.** `_target_findings`
   builds its profile map from EVERY document in `documents`
   (`contracts.py:449-456`) — the served catalog AND the pinned,
   digest-verified plugin documents (the #446 slice-2 `profile_shadow`
   rule exists precisely because pinned documents may carry profile rows).
   And the descriptor's `profiles[]` is namespace-open
   (`standards/otdp/0.2.4/otdp-device-descriptor.schema.json`:
   `items: {type: string, minLength: 1}`, no pattern; the corpus-owned
   namespace closure is scoped to `otdp.*` identifiers —
   `benchweave_sdk/validation.py:534-543`, gateway
   `control/documents.py:864-895`). A vendor profile row in a pinned
   document plus the descriptor claiming that profile id admits vendor
   targets under the EXISTING rule — no validator weakening, no
   plugin-ui schema change. This is the track's key extension point and
   its risk #1 (the first build commit must pin it with a fixture arm;
   see §9).

The measured trigger (parent §6 D1, fired by the Meridian M-400 scope
arms, `tests/test_classref_acceptance.py:562-810`) is confirmed exactly as
the brief states: a computed measurement (`derived_variables[]`) declares
without refusal and derives no surface
(`test_scope_computed_measurement_declares_without_refusal_but_no_surface`);
a custom decoder on a waveform-plot device builds lanes no plot carries
and renders no lane
(`test_scope_custom_decoder_declares_without_refusal_but_no_lane`). Both
are disclosed today by R10's `deferred_members` channel
(`classref.py::deferred_members:1604-1639`, gate rows at
`classref_gate.py:818-822, 978-986`). Neither is composed. And one silence
R10 does NOT cover was found while tracing (§2 V3): a channel whose role
matches no channels slot is dropped without any disclosure.

## 1. Where each vocabulary lives today (file:line)

All SDK paths `packages/sdk/src/benchweave_sdk/` on origin/main @
`88dcc4d` (the pin); all gateway paths in this worktree. "Residual member"
= a declared member no served class and no served catalog covers.

| # | Vocabulary | Declaration surface (descriptor) | Derivation path (SDK) | Today, residual |
|---|---|---|---|---|
| V1 | procedures | `actions{}` (a run-verb action, e.g. `com.x.sweep/1.0.0`); slot semantics live in the reference's `slots[key].kind: "procedure"` (`standards/plugin-ui-class-reference/0.4.0/class-reference.schema.json` slot oneOf branch 2) | procedure target+binding loop `classref.py::_finish:1990-2009`; plan page via `page_for_slot`; button via `_complete_authored_buttons:2493-2537` | derives an L1/L2 control on device-features through the ACTION vocabulary (honest, `resolution: custom`) — but NO procedure binding/target (targets need a profile row, `contracts.py:472-481`); a slot naming an unserved URN refuses (D4, stays) |
| V2 | observation variables | `derived_variables[]` (`standards/otdp/0.2.4/otdp-device-descriptor.schema.json`, measurement-model.md §8, M15/S19); tile members are (channel, quantity) pairs over `channels[].quantities` + `parameters[]` | readings expansion `classref.py::_finish:1858-1917` (tiles per named readable parameter, `_resolve_parameters:2587-2621`); dataset shape `_dataset_shape:1760-1766` | a computed measurement derives NOTHING (`rms_v` absent from manifest and catalogue, the scope arm at acceptance:562-587); R10-disclosed as deferred |
| V3 | channels and decoders | `channels[]` (id/label/role/quantities/parameter_names — role enum closed at 11 values); `decoders[]` (id/path/sha256 pins) | lanes `_resolve_channels:1525-1543` (ONE channels slot, the first; channels filtered by `where_role`); decoder lanes `_finish:1800-1838`, hosted only by a `digital_lanes` plot (`:2126-2138`; the plugin-ui manifest `$defs.plot` bans `decoder_lanes` on analog kinds) | a channel matching no slot's role is dropped SILENTLY (no lanes, no disclosure — verified: nothing else reads `descriptor.channels` in either derivation); a decoder whose lanes no digital-lanes plot hosts renders nothing, R10-disclosed |
| V4 | datasets and capture shapes | `actions{}` (a capture verb) + `capture_formats[]` (closed enum `waveform_f64le\|raw_binary`) + the measurement contract pin; slot semantics `kind: "dataset"` | dataset target+binding `_finish:1768-1781, 1839-1850`; variables from `_dataset_shape` keyed by the PAGE's plot kind | a vendor capture verb derives a control only (no dataset binding/target); a computed shape member is V2; the dataset's variable shape is DERIVED from the plot kind, never declared — a spectrum-class dataset (the OTDP measurement model admits NINE kinds: `scalar_set, waveform, digital_trace, spectrum, iq, table, event_log, network_parameters, image`, `standards/otdp/0.2.4/otdp-measurement.schema.json` `$defs.dataset.kind`) has no presentation kind at all |
| V5 | plot kinds | none vendor-declarable — the kind lives in the reference's page template `plot.kind` (enum `digital_lanes\|time_series\|waveform`, family schema `:230-234`) mirrored by the plugin-ui manifest `$defs.plot` enum | `plot_kind_for_slot` from page templates `_finish:1709-1716`; emission per kind `:2063-2139` | a vendor cannot choose a plot kind; the corpus reference dictates it; a dataset slot whose page hosts no plot derives no plot and — for a class action — the page-level L4 coverage (`classref_gate.py:494-501`) would fail, but no such page exists in the corpus today (every dataset page carries a plot) |
| V6 | settings idioms | `actions{}` (a configuration verb); slot semantics `kind: "configuration"` + `schema_source: "input_schema"` | configuration arm `_finish:1918-1989`: settings schema asset, preset scaffold (provenance `synthetic`, A02), configuration target+binding, data-table via L3 layout | a vendor configuration verb derives L2 staged controls on device-features — honest, but never the settings idiom (no schema asset, no preset scaffold, no settings-page surface; same profile-row wall as V1) |

Gateway mirror state: `src/benchweave/presentation/classref.py` mirrors the
PRE-#541 derivation (it still raises `classref_unknown_action` for a
descriptor-declared action absent from every served catalog at
`:1768-1773` — D9, Track A's target). Every mirror statement below is
scoped behind Track A landing.

## 2. What the D1 trigger measured, mapped to the vocabularies

- computed measurement → V2 (disclosed, derives nothing).
- custom decoder on a waveform-plot device → V3 (disclosed, renders no
  lane; the schema BANS decoder lanes on analog plots — composing them
  there is impossible without a plugin-ui family widening, which is
  exactly the dishonest surface this track refuses).
- the silent channel (role matches no slot) → V3 (NOT disclosed today —
  found while tracing; `deferred_members` covers derived_variables and
  decoders only, `classref.py:1627-1639`).

## 3. The shared mechanism — one composed-member declaration

**Mechanism, one paragraph:** a **composed member declaration** is a
vendor-authored, versioned JSON document (new sibling schema
`composed-member-declaration.schema.json`, dialect `0.1.0`, in the family's
0.5.0 copy under copy-never-move) that rides the SAME
`descriptor.contracts[]` path+sha256 pin seam as composed action classes
and vendor catalogs, discriminated by document shape in the SAME
`_vendor_documents` walk (a document carrying `members` is a member
declaration; carrying `urn`+`claims` is an action class; carrying `actions`
is a vendor catalog; any overlap of these key sets is the R2 ambiguity
refusal), and states exactly two things: (a) optionally, ONE vendor
profile row — `id`, `title`, `channel_roles`, `required_actions` (the
declared members), `optional_actions` — in the device-profile-catalog's
own row shape verbatim (`standards/otdp/0.2.4/device-profile-catalog.schema.json`
profiles items), which the descriptor makes claimable by listing the
profile id in its namespace-open `profiles[]`; and (b) `members[]`, each
`{slot, kind ∈ {channels, dataset, configuration, procedure}, claims[],
where_role?, when_declared?, schema_source?, host_supplied?, page, plot?}`
— every closed set lifted VERBATIM from the reference schema's own slot
vocabulary (`class-reference.schema.json` `$defs.slot`) and page-template
plot spec, `page` naming an EXISTING reference page id, `plot.kind` from
the EXISTING three-kind enum. It is layer 2 in the action pattern's exact
sense: it supplies the reference side (slots and placement) the served
corpus does not, injects after `_merge_references` into
`merged["slots"]`/`page_for_slot`/`plot_kind_for_slot`, and the EXISTING
derivation arms (the procedure loop, the configuration arm, the dataset
arm, `_resolve_channels` generalized to per-slot lanes, `_build_layout`)
run unchanged on the injected rows. No new component, no new page, no new
plot kind, no new node kind — the s2 record's rule ("the component
inventory is the existing one, applied by the existing rule") extended
from controls to slots.

**Which vocabularies cannot share it, said honestly:**

- **V2 (observation variables) does not need the document.** Its member
  declaration already exists and is descriptor-owned: the
  `derived_variables[]` row IS the layer-2 declaration (id, quantity,
  unit, expression — a closed vocabulary OTDP owns). A pinned document
  restating it would be redundant structure with a drift risk and no
  reader. V2 shares only the track's provenance/ledger/REPORTED channel.
- **V5 (plot kinds) shares the document but not a derivation.** Its
  layer 2 is one field (`plot`) on a dataset member; its layer 3 is a
  disclosure-only terminal state (§4 V5), because inventing a plot kind
  outside the enum is a dual-family standards motion (family reference
  schema AND `plugin-ui/0.4.0/ui-manifest.schema.json` `$defs.plot`)
  whose consuming arms do not exist — the s2 record's standing rule: a
  widening ships its consumer. The three-kind inventory IS this track's
  component inventory.
- **V3's decoder half composes only where the schema permits.** A
  decoder's lanes host ONLY in a `digital_lanes` plot (the manifest
  schema bans `decoder_lanes` on analog kinds, verified
  `standards/plugin-ui/0.4.0/ui-manifest.schema.json` `$defs.plot`
  allOf). On an LA-class device a composed channels/decode slot composes
  lanes; on a waveform/time_series device the honest terminal state is
  the disclosure (rendering them on the analog plot would assert a
  surface the schema forbids — the dishonesty V3 refuses). This is a
  designed outcome with a structural reason, not a deferral: the
  alternative is a plugin-ui family widening with no consuming host arm.

**The generalized honesty rules (the action track's four, extended):**

1. **Provenance, one writer, applied set.** `DerivedUI` gains
   `composed_members` — per vocabulary, the APPLIED member set (a member
   applies when its claim is declared by this descriptor — the R1 rule
   carried over verbatim). Only the composed-member walk writes
   `composed_member` provenance; the ledger records the applied set, and
   a pin whose members apply nowhere is a REPORTED row
   (`composed member declaration <path> applied nowhere`), never drift.
2. **The ledger gains one inventory key, read back both directions with
   the mapping** (the B6/R6 discipline — sets alone were proven
   insufficient once already): `ui/class-reference.json` gains
   `composed_members: {procedures: [...], settings: [...], datasets:
   [...], channels: [...]}`; the gate compares authored vs derived, both
   directions AND per-member slot mapping, every mismatch REPORTED. The
   key rides the D8 no-schema-yet posture (no schema governs the ledger's
   key set; the 0.5.0 README extends the prose the same way 0.4.0's did).
3. **R10 generalizes from "deferred" to vocabulary-named residual rows.**
   `deferred_members` becomes `residual_members`: a declared member that
   derives NO surface of its vocabulary gets
   `<kind> <member>: derives no <vocabulary> surface (no declaration; the
   generic action control renders on device-features)` — and the row
   DISAPPEARS when the member derives (the R10 decoder direction
   preserved). V3's silent channel joins this channel (the new closure —
   RED-checkable, M4 below).
4. **Integrity and conflict refusals are unchanged in kind:** digest
   mismatch/unreadable/non-object pins refuse with the walk's existing
   codes; a composed member whose slot key or claimed action collides
   with a reference slot, another member, or a composed action class's
   claim refuses `classref_composed_slot_conflict` (new code, the
   parent §8 refuse-never-merge family); a `page` naming no existing
   page refuses the same code; an ambiguous pin (key-set overlap)
   refuses the R2 code.

## 4. Per-vocabulary design

Format per the brief: today's residual behavior; the layer-2 closed set
and conflict rule; the layer-3 residual rule and its surface; provenance;
REPORTED row; widening question.

### V1 — procedures

- **Layer 2:** member `{slot, kind: "procedure", claims: [<urn>],
  page: "capture", host_supplied?: [...], when_declared?: bool}`. Closed
  set: the reference schema's procedure slot branch verbatim (action,
  when_declared, host_supplied) + `page`. Conflict: slot key or action
  claimed by a reference slot / another member / an action class →
  refuse. Injection: `merged["slots"][slot]` joins; the procedure loop
  (`_finish:1990-2009`) composes the target with
  `profile_ids = [vendor profile id]` (the seam, §0.2) and the binding;
  the plan row's page comes from `page_for_slot`, so the button derives
  on the named page through `_complete_authored_buttons` (authored
  pages) or `_build_layout` (derived pages) — both existing arms.
- **Layer 3:** no declaration → the action vocabulary's control on
  device-features (already lands post-#541; behind Track A gateway-side)
  — the honest generic surface. A declared procedure member always
  derives SOMETHING (its control), so V1's derives-nothing state does
  not exist; its residual disclosure is the action track's
  `custom|composed: <urn>` row. Stated plainly: **V1's REPORTED
  vocabulary row exists only in the negative direction — the gate
  reports a composed member declaration that applied nowhere (rule 3.1)
  and nothing else.**
- **Provenance:** plan row keeps `resolution` (catalog/composed/custom
  from the action track); the member's slot provenance is the ledger row
  `composed_members.procedures: [{slot, action, page, class?}]` — one
  writer (the member walk).
- **Widening needed:** NONE. Slot kind, target kind, binding kind,
  button node all exist.

### V2 — observation variables

- **Layer 2 (already exists, descriptor-owned):** the
  `derived_variables[]` row — id/quantity/unit/expression, closed by
  OTDP. This track adds no document; the design says so rather than
  inventing a redundant one.
- **Layer 3:** a computed variable derives into EVERY dataset target's
  variable set as `{id, type: "number", unit, shape: "scalar"}` (the
  measurement model's rule: the host computes it INTO the dataset — the
  wire carries it, so the derived shape asserting it is honest), riding
  the `numeric_variables` series rule on time_series/waveform plots as a
  y series. It derives NO observation tile, ever: a tile is an
  observation target and the canonical validator requires
  `parameter_id` naming a declared readable parameter
  (`contracts.py:411-419`) — a computed variable has no parameter, and a
  tile would assert a data path that does not exist (the exact
  dishonesty the parent's KILL (d) names). NOT a manifest byte change:
  the variable row shape (`$defs.variable`) is untouched — the computed
  variable is an ordinary value variable; its provenance lives in the
  ledger and the REPORTED row, not on the manifest row (adding a field
  there would be a plugin-ui family widening — refused, D3's discipline).
- **Provenance:** ledger `composed_members.observations` is NOT minted
  (no declaration); instead the R10 row flips: the REPORTED row becomes
  `observation variable <id>: computed variable derives into dataset
  variables (no tile; no parameter to read)` — a composed-state
  disclosure, not "derivation deferred". The scope arms in
  `test_classref_acceptance.py` flip with it (a deliberate, documented
  test edit — the arms' own docstrings say "a later slice that adds the
  surface must move them deliberately").
- **Widening needed:** NONE.

### V3 — channels and decoders

- **Layer 2:** member `{slot, kind: "channels", where_role: <role>,
  page: "capture"}` — closed set: the reference schema's channels branch
  (where_role/key/label) + `page`. `_resolve_channels` generalizes from
  "the first channels slot" to per-slot resolution
  (`{slot_key: lanes}`); the committed fixtures are byte-stable (every
  corpus reference declares exactly one channels slot — asserted).
  Lanes render into the named page's plot ONLY when that plot's kind is
  `digital_lanes`; otherwise the member derives its binding and the
  lanes disclose (below). The decode form: a dataset member over a
  decode action (`kind: "dataset"`, V4) gives the decoder lanes their
  binding host where the class has a decode slot; the LA-class fixture
  (`descriptor-f1-da.json`) is the composing arm.
- **Layer 3 — the silence closes:** a channel whose role matches no
  resolved channels slot (reference or composed) gets a REPORTED row
  every run: `channel <id> (role <role>): resolves to no lanes surface`.
  A decoder whose lanes no derived plot carries keeps today's R10 row,
  reworded to the residual vocabulary (`custom decoder <id>: no lane
  host (this class's plot is <kind>; lanes host in digital_lanes
  plots alone)`). Neither is a findings failure, ever.
- **Provenance:** decoder lanes already carry `decoder: <pin id>` (the
  pin is the vendor's own declaration — structurally self-provenancing);
  composed channels slots: ledger row `composed_members.channels:
  [{slot, where_role, page}]`.
- **Widening needed:** NONE for the composition. Decoder lanes on
  analog plots would need the plugin-ui `$defs.plot` widening — REFUSED
  (no consuming host arm; the s2 standing rule). The refusal is the
  design, not a deferral.

### V4 — datasets and capture shapes

- **Layer 2:** member `{slot, kind: "dataset", claims: [<capture urn>],
  page: "capture", plot?: {kind, over_slot: <self>, series:
  "numeric_variables"}}`. The dataset loop composes target+binding with
  `profile_ids = [vendor profile id]` and `measurement_schema_id` = the
  descriptor's pinned measurement contract (the existing
  `measurement_id` resolution). Derivation refinement, stated for the
  builder: `_dataset_shape` for a slot with no plot spec of its own
  INHERITS the binding page's plot kind (today a plot-less slot falls to
  the founding `digital_lanes` string-lane shape — `[x_var, *lane_vars]`
  — which for a vendor capture bound beside a waveform plot would
  mis-derive the wire shape; the inheritance rule fixes exactly that).
  A member whose action the descriptor does not declare applies nowhere
  (REPORTED, rule 3.1).
- **Layer 3:** a capture-shaped declared action with no member
  declaration derives its action control only, plus the REPORTED row
  `dataset member <urn>: no dataset surface declared (the action's
  control renders on device-features)`. A computed shape (V2's variable)
  derives per V2. The nine-kind measurement vocabulary beyond the three
  presentation kinds: a dataset NO kind hosts composes through the
  member's `plot` choice among the existing three or derives the V5
  residual disclosure — the honest mapping, stated as the terminal rule
  (a new kind is a dual-family motion outside this track, §3 V5).
- **Provenance:** ledger `composed_members.datasets: [{slot, action,
  page, plot_kind?}]`; the L4 plan row's `rendered_by` claim follows the
  R9 stamp discipline — a composed dataset row advertises a rendering
  only when a derived plot carries its binding (the stamp lands after
  plot construction, exactly where R9 put the decode-annotated stamp).
- **Widening needed:** NONE.

### V5 — plot kinds

- **Layer 2:** the `plot` field on a dataset member (V4) — the vendor
  chooses among the EXISTING three kinds for a page that hosts no plot
  template (a page hosts one plot; a page with a template keeps the
  class's). The plot spec is validated against the family schema's own
  plot def verbatim (the conditional rules — no group machinery on
  analog kinds — apply unchanged).
- **Layer 3:** a dataset slot whose page hosts no plot derives no plot;
  the member's REPORTED row (V4's) carries it. A member whose chosen
  kind's per-kind rules the derivation cannot satisfy (e.g. an over-16
  analog y) refuses typed (`classref_series_ceiling`, the existing
  fail-closed-arm-the-derivation-lacks precedent).
- **Provenance:** the plot row in the derived manifest is
  indistinguishable from a class plot BY DESIGN (the manifest is
  wire-shaped, not provenance-carrying); the provenance surface is the
  ledger's `composed_members.datasets[].plot_kind` and the gate's
  read-back. Stated as the vocabulary's honest limit.
- **Widening needed:** NONE in this track. A fourth kind is a
  standards motion of its own (family + plugin-ui + host render arm),
  recorded here as the named boundary, not scheduled.

### V6 — settings idioms

- **Layer 2:** member `{slot, kind: "configuration", claims: [<urn>],
  page: "configuration", schema_source: "input_schema"}`. The
  configuration arm (`_finish:1918-1989`) composes the settings schema
  asset (the effective schema — D13 runs with the composed action
  class's `input_schema` or the residual constraints as the catalogue
  side, unchanged), the preset scaffold, the configuration target
  (`profile_ids = [vendor profile id]`) and binding, and the L3
  data-table — the existing idiom, driven by the composed slot.
  **A02 carries unchanged:** the preset surface's birth deviation
  (presets are commissioned evidence) rides every composed settings
  member exactly as it rides a class slot's (`_build_declaration`'s
  preset-deviation arm keyed on slot kind, not on slot origin).
- **Layer 3:** a configuration-shaped declared action with no member
  declaration derives L2 staged controls on device-features plus the
  REPORTED row `settings member <urn>: no settings surface declared
  (controls render staged on device-features)`.
- **Provenance:** ledger `composed_members.settings: [{slot, action,
  page}]`; the settings schema asset is derived (data, not provenance).
- **Widening needed:** NONE.

### The per-vocabulary table the brief asked for

| vocabulary | today, residual | layer-2 home | layer-3 surface | provenance value | REPORTED row | needs widening? |
|---|---|---|---|---|---|---|
| procedures | action control on device-features; no procedure binding/target (validator wall `contracts.py:472-481`) | composed member declaration, kind `procedure` (family 0.5.0 sibling schema) | the action control (existing), disclosed via action provenance | ledger `composed_members.procedures` | applied-nowhere row only (no derives-nothing state exists) | no |
| observation variables | derives NOTHING; R10 "derivation deferred" | the descriptor's own `derived_variables[]` (no new document — stated) | dataset value variable + plot series; NEVER a tile (no parameter — validator + honesty) | REPORTED/ledger vocabulary only (no manifest byte) | `observation variable <id>: computed variable derives into dataset variables (no tile...)` | no |
| channels and decoders | unmatched-role channel SILENT; unhosted decoder R10-disclosed | composed member declaration, kind `channels` (+ dataset member for the decode binding) | lanes where a digital_lanes plot hosts; disclosure otherwise (schema bans analog decoder lanes) | lanes carry `decoder` id; ledger `composed_members.channels` | `channel <id> (role <r>): resolves to no lanes surface`; decoder no-host row | no (analog-lane hosting would need the plugin-ui plot widening — refused, no consumer) |
| datasets and capture shapes | capture verb derives a control only; shape mis-derives to string lanes when plot-less (the `_dataset_shape` founding fall-through) | composed member declaration, kind `dataset` (+ optional `plot`) | dataset binding+target; shape inherits the page's plot kind | ledger `composed_members.datasets`; `rendered_by` per R9 | `dataset member <urn>: no dataset surface declared...` | no |
| plot kinds | vendor cannot choose; kind is corpus-fixed | the member's `plot` field, existing three-kind enum | a plot where the page hosts none; disclosure otherwise | ledger `plot_kind` (the manifest row stays wire-shaped by design) | rides the dataset member's row | no (a fourth kind is a named-outside motion) |
| settings idioms | staged controls on device-features; never the idiom | composed member declaration, kind `configuration` | the full existing idiom: schema asset + preset scaffold + data-table; A02 birth deviation unchanged | ledger `composed_members.settings` | `settings member <urn>: no settings surface declared...` | no |

## 5. Slice plan (each vocabulary its own reviewable unit, on a shared spine)

Ordering by dependency and risk; "serialize" = same-code-surface ordering,
never parallel lanes in one file.

| slice | content | repo | serializes behind |
|---|---|---|---|
| **B1** | V2 + V3 layer 3, standards-free: computed variables derive into dataset shapes; the channel silence closes; `deferred_members` → `residual_members`; the acceptance scope arms flip (documented test edits) | SDK | nothing (lands first; no schema dependency) |
| **B2** | the standards motion: `composed-member-declaration.schema.json` (dialect 0.1.0) + family bump 0.4.0→0.5.0 (copy-never-move; every closed set derived from an existing owner — §3) + README section + cross-constraints row | gateway (standards) | nothing; the SDK leg consumes it via `sync-sdk-standards` |
| **B3** | the composed-member walk (shape discrimination, conflict refusals, the injection seam, `composed_members` on `DerivedUI`) + V3 layer 2 (per-slot channels; the LA fixture arm) + ledger key + gate read-back. FIRST COMMIT: the vendor-profile seam arm (risk #1) | SDK | B2 (schema), B1 (residual channel) |
| **B4** | V1 procedures + V6 settings idioms layer 2 (slot-kind injections through the existing arms) + their REPORTED rows; the M-400 fixture extended (a vendor configure slot and a sweep procedure slot) | SDK | B3 (same `_finish` region — serialize) |
| **B5** | V4 datasets + V5 plot kinds layer 2 (the dataset member, the `plot` field, `_dataset_shape` inheritance, the R9 stamp) + their REPORTED rows; the wheel/install arms (the A3 shape over the extended fixture) | SDK | B4 (same `_finish` region — serialize) |
| **B6** | migrate-ui + drift arithmetic over `composed_members` (applied-set keying); user-guide leg (plugin-sdk.qmd's composed authoring contract extended — the D7 discipline) | SDK | B4, B5 |
| **B7** | the gateway mirror: composed-member resolution + residual disclosures in `src/benchweave/presentation/classref.py`; B8 fixture regeneration; equivalence census arms | gateway | **Track A's mirror merge** (same file; hard serialization) + B5 |
| **B8** | docs + close-out: composition note §"the six vocabularies", parent record §6 D1 marked closed (trigger answered), this record's scan re-run on the committed diff | gateway | B7 |

The vendor-profile seam arm (risk #1) is B3's FIRST commit: a descriptor
declaring `com.meridian.m400/1.0.0` in `profiles[]`, a pinned document
carrying the profile row, `validate_presentation` green over a vendor
target — before any derivation code moves.

## 6. Pre-committed acceptance rule

Written before any arm ran; the only numbers looked at while designing are
the quoted file:line evidence above. Metric surface: the real derive path
(`derive_ui`), the real gate (`verify_ui`), the real standalone host
(`render_pages`) over the extended Meridian M-400 fixture and the LA
fixture — never a mock, never a test-side reimplementation.

**SHIPS if all six hold:**

1. **M1 — every declared member derives a surface or a
   vocabulary-named REPORTED row.** Denominator, per vocabulary, stated
   by assertion over the fixture descriptor (never a literal):
   procedures/settings/datasets = the declared action set partitioned by
   member declarations; channels = `descriptor.channels`; decoders =
   `descriptor.decoders`; observations = `descriptor.derived_variables`.
   Numerator: members with EITHER a derived surface asserted present in
   the derived documents (binding/target/variable/lane — checked by
   membership, not by count) OR a REPORTED row naming the vocabulary.
   Required: 100% on both fixtures, and a fixture with ZERO declarations
   still passes M1 through its REPORTED rows alone.
2. **M2 — no refusal for the recoverable case; the survivors intact.**
   The extended fixture derives with zero `classref_*` refusals beyond
   the parent §8 survivors; digest-mismatch, unreadable-pin,
   ambiguous-pin, claim-conflict, slot-conflict and empty-admittance
   refusals each still fire (one arm each, distinct codes).
3. **M3 — the layers are distinguishable, per vocabulary.** For one
   member of each of V1/V3/V4/V6: the same member derives class-served
   (a corpus slot's twin on the LA/DAQ fixtures), composed (the member
   declaration) and residual (no declaration) — three distinguishable
   states, each asserted through the ledger and the REPORTED channel;
   and a forged ledger row (a member the derivation did not apply)
   REPORTS on the read-back (the B6/R6 mapping rule).
4. **M4 — the silence closure is RED-checkable.** A fixture channel with
   an unmatched role yields its REPORTED row; neutralize the closure
   (a `cp` backup of the residual-members walk) and the row disappears —
   the arm reds. Restore, green. The R10 decoder direction re-pins the
   same way (a hosted decoder yields no row).
5. **M5 — A02 and D13 carry.** A composed settings member's preset
   surface carries the birth deviation exactly as a class slot's
   (asserted on the ledger), and a composed member's effective schema
   still narrows (the intersection path unchanged — the composed action
   class's `input_schema` plays the catalogue side; an empty admittance
   still refuses).
6. **M6 — committed-pair byte stability.** The founding fixtures
   (f1/f2/f1-da/f5-trio/f6-smu) derive byte-identical before/after B3's
   per-slot channel generalization (the one-class-one-channels-slot
   invariance, asserted by digest over the derived triples).

**KILLS if any of:** (a) a clean arm needs an existing gate assertion
weakened or a corpus byte edited — owner escalation, not a test to tune;
(b) any declared member of any vocabulary is silent on every surface;
(c) an integrity or conflict refusal is weakened; (d) a composed surface
is dishonest about what it admits — an observation tile for a computed
variable, a decoder lane on an analog plot, a settings surface without
the A02 deviation, or a dataset shape contradicting the member's declared
plot kind.

**UNDERPOWERED, not conclusive:** a clean arm reds because a HOST cannot
render a schema-admitted surface (the standalone host or the gateway
page) — a discovered host defect; it escalates and the rule is never
tuned to pass.

## 7. Invariant and drift impacts

- **No CTL/STO/CON/REG invariant changes.** A02 is strengthened (the
  birth deviation rides composed settings members); the CON-5 composition
  inventory (the L4 amendment's row) gains its Track B entries in the
  B7 record addendum, the B4-fold pattern. CON-7 (repin-only rewrites)
  and GOVERNANCE copy-never-move govern the 0.5.0 bump. CON-12's mirror
  obligation extends: the equivalence census gains composed-member arms
  when B7 lands.
- **On-disk formats/schemas:** one NEW schema file (a standards motion,
  B2, stated as such): family 0.4.0 → 0.5.0 under copy-never-move — the
  0.4.0 tree and its 27 rows frozen; the 0.5.0 copy re-stamps its
  version-bearing lines (the s2 §4 method, applied with its own §9
  correction: the version-literal census is a BARE-VERSION scan, and
  completeness is proved by the full battery, never by the scan appearing
  exhaustive). The ledger's new key rides the D8 no-schema posture (the
  0.5.0 README extends the prose; no manifest byte moves).
- **Surfaces that move:** SDK (`classref.py`, `classref_gate.py`,
  `presentation.py` migrate legs, tests, vendored tree via
  `sync-sdk-standards`, a MINOR version, user_guide/plugin-sdk.qmd);
  gateway (`standards/` + both manifests, `src/benchweave/presentation/classref.py`,
  `tests/presentation/classref_fixtures/` regeneration,
  `docs/internal/class-reference-composition.md`, the parent record's D1
  row). The #408 order governs every SDK↔gateway leg (SDK PRs merge →
  release cut → pointer PR; gitlink + pin in one commit).
- **CI cost:** no new job, no browser, no network. New arms are
  unit-shaped plus the two existing fixture harnesses. The composition
  gate's pair set is unchanged (byte-identical class files in the 0.5.0
  copy).
- **Obligations walked:** #408 order; `make check-sdk-standards` on the
  pointer PR; `sdk-drift` green with pin == released tag; drift-guard
  rows for the touched docs; the name screen over every commit.

## 8. Tier statement and Step-1 keyword scan (#254)

**Tier 3 — the maximum across slices; the scan below covers each slice's
expected diff.** First match, per slice: B2/B8 touch `standards/` and add
a JSON Schema file; B3–B6 advance the `packages/sdk` submodule pointer
and carry `sha256` (the pin seam) and `migrate` (migrate-ui) diff text;
B7 mirrors them. The standards-governor pass is mandatory on B2 and B8
regardless; the Tier-3 adversary pass runs two independent lanes (#181
R3) on B2 (the schema slice) and one on B3 (the walk + seam).

Keyword scan over this record's own text (the design-time portion of the
expected diff; the build legs re-run the scan over each committed diff,
and the review re-derives the tier independently). Counts, measured over
the committed file (each keyword, whole-word, `grep -o | wc -l`):
`threading` 1, `asyncio` 1, `subprocess` 1, `sha256` 5, `hashlib` 1,
`migrate` 7, `recovery` 1, `protection` 1. Every 1-count is this
paragraph's own enumeration of the eight-word set (self-fire by
construction — the rubric's intended interplay); the two real counts are
the mechanism's own vocabulary — `sha256` names the contracts[] pin seam
the declaration rides (prose and code names alike), `migrate` names the
migrate-ui ledger contract slice B6 states. *Correction, made at
authoring before any build leg ran:* the first draft of this paragraph
estimated the counts rather than measuring them, and was wrong; the
numbers above are the measured ones, corrected the way the s2 record
corrected its A4 — before the measurement is relied on, never after. The tier is 3
by path rules regardless of the scan.

## 9. Top risks, each with its falsifier

1. **The vendor-profile seam is narrower than it reads.**
   `_target_findings` reading profile rows from pinned documents is
   verified (`contracts.py:449-481`), and the descriptor's `profiles[]`
   is schema-open — but a semantic check I did not find (SDK or gateway
   admission) may refuse a descriptor profile id that is neither
   corpus-known nor `otdp.*`-namespaced. Falsifier: B3's first commit
   (the seam arm) — if it refuses, the seam widens by the
   transport-provider closure pattern (the pinned document's profile row
   SATISFIES the closure the way a provider object does), or the design
   escalates; it never weakens the check.
2. **The per-slot channel generalization moves committed bytes.**
   Falsifier: M6 (digest equality over the five founding fixture triples).
   The generalization is per-slot keyed; one-slot references are
   invariant by construction — but the assertion, not the construction,
   is the gate.
3. **The ledger read-back repeats the B6 mistake** (sets compared, mapping
   forgotten). Falsifier: M3's forged-row arm — a ledger row naming a
   member with the wrong slot REPORTS. The design mandates the mapping
   comparison from birth (the R6 rule), and the refute lane's first job
   on B3 is to try the B6 shape again.
4. **The family bump's version-literal census is incomplete again** (the
   s2 record's census was wrong twice in one arc). Falsifier: the full
   battery + `matrix --check` + `make check-sdk-standards` on the pointer
   PR; the census method is the corrected one (bare-version scan over
   source and fixtures; `count_version_literals`' REGISTER extended in
   the same change).
5. **Track A and this track collide on the mirror file.** B7 serializes
   behind Track A's merge (stated in §5); the falsifier is a rebase
   conflict on `presentation/classref.py`, which the serialization makes
   a non-event. If Track A slips, B7 rebases onto its branch tip, never
   around it.
6. **The L4 page-level coverage test launders an unrendered composed
   dataset slot** (the R9 lesson: building is not rendering). Falsifier:
   the R9 stamp rule on composed dataset rows (M1's surface membership
   check reads the DERIVED plot's bindings, never the page census) — a
   composed slot on a plot-bearing page whose plot does not carry the
   binding must REPORT, not pass on the neighbor's plot.

## 10. What the maintainer must decide

- **The one-document-for-five choice.** V1/V3/V4/V5/V6 share a single
  composed-member declaration document and one 0.5.0 bump. The
  alternative — per-vocabulary documents and bumps — costs three-plus
  standards motions and six discriminators for no reader benefit; this
  record recommends the single document on the s2 record's
  one-family-one-motion precedent, but the bump count is the owner's
  call.
- **D2's boundary sentence.** This track composes into EXISTING pages
  only. Vendor-minted pages remain D2 (fork F1, the owner's pending
  ruling). If the owner wants page minting in this run, it is a design
  amendment to THIS record, not a seventh vocabulary quietly added.
- **The V5 terminal state.** A fourth plot kind (spectrum, image) is a
  named-outside motion (dual family + host arm). If the owner wants it
  in-run, the track grows a B5b slice and a plugin-ui family bump —
  flagged now so "no deferrals" is decided with the cost visible.

## Addenda

Corrections to a committed record are addenda, never retrofits.

### 2026-10-25 — F4: the arm-move pre-authorization's actual location

§4 V2 says the acceptance scope arms' pre-authorization is "the arms'
own docstrings". It is not. The sentence lives in the section header
comment above the scope arms — `tests/test_classref_acceptance.py`
lines 553–559 at the B1 fold base (`65c1e5a`) — quoted verbatim:

> Scope arms — the issue's other two custom members, measured. These are
> the honest negative results (project principle 11): the vocabulary
> admits the declaration, the derivation refuses nothing, and no surface
> comes out. They pin that state so a later slice that adds the surface
> must move them deliberately. Not the acceptance claim — named in the
> report as NOT proved.

The individual arms' docstrings describe their own measurements; the
authorization sentence is the section comment's. No code or behaviour
changes with this correction.

### 2026-10-25 — F2: a pre-existing ceiling defect, recorded and not touched

Measured while folding B1's refute findings. B1 added a road — a
descriptor's `derived_variables[]` compose into the dataset shape and,
on time_series/waveform plots, into `y` — and a composed series past the
manifest schema's `y.maxItems: 16` breached the schema, escaping
`verify_ui` as an unhandled `PluginLoadError`. **The class pre-exists on
`origin/main` (`dc6e429`) independently of B1:** a descriptor with more
analogue channels than the kind admits derives that many trace variables
and breaches the same ceiling. Measured on the B1 worktree with a
Meridian M-400-shaped descriptor carrying 17 `analogue_input` channels:
`plot waveform y count: 17`; `verify_ui` raised
`benchweave_sdk_server.session.PluginLoadError:
standalone_plugin_invalid: preview_invalid_presentation:
invalid_document: ui-manifest: Document does not satisfy its schema`.

B1's fold fixes only the road it added: a composed overflow is dropped
from the plot and disclosed on the REPORTED channel, and the class's own
traces are never dropped. The pre-existing class — a class whose own
traces exceed the kind's ceiling — stays as-is; dropping class-declared
traces is a behaviour change outside this slice's licence. Recorded here
so the known defect is a disclosure, not a silent drop. Tagged
PRE-EXISTING, outside B1's scope.

### 2026-10-25 — the capacity-versus-declaration boundary (maintainer ruling)

B1's fold surfaced a fork between two slices of this track. §4 V5
pre-commits that a composed member whose chosen plot kind cannot satisfy
its own per-kind rules "refuses typed (`classref_series_ceiling`)", while
B1's fold handled the same physical situation — a plot whose series count
exceeds the kind's ceiling — by dropping the overflow and disclosing it.
The same condition, two dispositions, in one vocabulary. Ruled before B5
so the vocabulary does not fork silently.

**The boundary is not the situation; it is whose error it is.** A refusal
is for a **declaration conflict the schema cannot express**: a slot key or
claimed action colliding with a reference slot, another member or a
composed action class; a page that does not exist; an ambiguous pin; a
`side_effect` outside the closed set. Every one of those is a malformed
declaration, and only a malformed declaration reaches it. A **capacity
limit is not the vendor's error**: the declaration is admissible, the
derivation simply cannot render all of it, so it drops what it cannot
render and discloses each drop on the REPORTED channel.

**Consequence for B5:** `classref_series_ceiling` is retired as a
pre-committed refusal. A composed plot that would exceed its kind's ceiling
drops the overflow and discloses it, in the same wording family B1 minted.
If B5 finds a case where a member's own declaration is *malformed* rather
than merely oversized, that is a declaration conflict and refuses under the
existing conflict codes, not a capacity rule.

### 2026-10-25 — the bound tie: the exclusive end wins (M5/D13 narrowing)

An adversarial lane on the gateway mirror reproduced a **widening** in
`_intersect_property`'s bound selection, and the SDK carries the identical
defect. The side is chosen by comparing `(value, exclusive)` tuples: the
low side used `max()` and the high side `min()`. On a value TIE the tuple
ordering puts the INCLUSIVE end first for both, so `max()` happened to pick
the exclusive low end (correct) while `min()` picked the inclusive high end
(wrong). A catalogue `maximum: 5` met by a constraint `exclusiveMaximum: 5`
therefore produced an effective `maximum: 5`, admitting `5` — a value the
plugin's own constraint refuses. That is the one direction D13 does not
tolerate, and neither `_check_admittance` (which only sees both-ends ties)
nor a span test catches it. The docstring's "the tighter end of each side
wins" was false on the high side.

**The fix** replaces tuple ordering with an explicit comparator pair used by
both sides, so one restatement cannot drift from the other:
`_tighter_low` keeps the larger value and, on an equal value, the exclusive
end; `_tighter_high` keeps the smaller value and, on an equal value, the
exclusive end. Before: `low = max(cat, con)`, `high = min(cat, con)`. After:
`low = _tighter_low(cat, con)`, `high = _tighter_high(cat, con)`.

**Arms (2, both through `derive_ui`'s real effective-schema path on
`tests/fixtures/classref/descriptor-f3b.json`):**
`test_m6_high_bound_tie_takes_the_exclusive_end` — catalogue
`sample_count` (`minimum: 1, maximum: 1000000`) met by a constraint
`exclusiveMaximum: 1000000`; the row must carry `exclusiveMaximum`, and the
test's own row-admittance predicate admits `999999` and refuses `1000000`.
`test_m6_low_bound_tie_takes_the_exclusive_end` — the mirrored floor tie;
same predicate, admits `2`, refuses `1`. RED on the unmodified production
file: the high arm raised `KeyError: 'exclusiveMaximum'` (the inclusive
`maximum` survived); `tests=2 failures=1 errors=0`. The low arm passed
pre-fix, because the low side was already correct — the mirror arm is a
regression guard on the restated comparator, not a second defect. Both arms
were separately shown live by neutralizing the tie rule to prefer the
inclusive end on BOTH sides (`cp` backup, never `git checkout`):
`tests=2 failures=2 errors=0`, each raising the corresponding
`KeyError`; restore, then `tests=2 failures=0 errors=0`. The focused
classref suite (`test_classref_effective`, `_composed`, `_residual`,
`_acceptance`) is green at 140 passed. The arms cover value ties at a
single property's numeric bounds; they do not re-derive every catalogue
field, and no fixture byte moves.

**Mirror obligation (recorded, dated).** BOTH halves carry the fix in this
arc: the SDK in this commit, and the gateway on its own branch — `7f715e33`
on `feat/556-gateway-mirror`, whose `_tighter_bound` states the same
exclusive-wins-tie rule through one comparator for both sides. CON-12
mirrors the two sources rather than one leading the other, so once both
pull requests merge, gateway main and SDK main agree on the intersection.
The remaining divergence is against the PINNED ARTIFACT only:
benchweave-sdk v0.21.0 still ships the old tuple comparison until the
release cut and the pointer PR — the ordinary pin lag every pointer closes,
not a semantic split between merged sources. Recorded so a differential run
against the pin reads it as scheduled convergence rather than a regression.

**Census.** This repository carries no committed gateway-versus-SDK
equivalence census; the only one is the gateway's
`tests/sdk/test_descriptor_equivalence.py`, and it carries no
effective-schema bound arm today, so no census expectation moves with this
commit. Because that file is the differential vehicle between the two
halves, it is where the tie case must be noted when it gains
effective-schema arms — with the same future-fix framing (an expected
divergence until the pointer advances), so a differential run does not
rediscover the tie as an unexplained failure. Recording that requirement
here is the SDK-side half of the obligation; the note itself belongs with
the next change to that census, which this arc does not make.

### 2026-10-25 — B3 fold: the join half of the capacity boundary, the per-member applied-nowhere row, and two inventory corrections

The adversarial lane on B3 confirmed the walk's predicate, M6, the refusal
classes and the gate's mapping read-back, and found two defects plus two
inventory drifts; all four fold in one commit with per-finding RED
evidence, recorded here because two of them are rules, not code.

**F1 (MEDIUM-HIGH) — the page-level lane join is bounded, and the capacity
boundary gains its join half.** Per-slot `_resolve_channels` bounds each
slot alone at `_LANE_CEILING` (64), but the join in `_lanes_for_page` —
the first slot's lanes plus every placed member slot's — bounded nothing:
a 32-lane reference role beside a 40-lane composed role derived a
72-entry `y` against the manifest schema's 64 with zero disclosures, and
the real `verify_ui` raised
`PluginLoadError: standalone_plugin_invalid: preview_invalid_presentation:
invalid_document: ui-manifest: Document does not satisfy its schema`
(reproduced by the fold's arm before any fix; the neutralized bound
reproduces it after). The fix extends today's capacity ruling by its
missing half, stated as ONE boundary in two clauses:

- **A single slot over the cap REFUSES** (`classref_lane_ceiling`, the
  per-slot arm in `test_classref_expand.py`, unchanged): a lane has no
  surface other than the plot, so truncating one slot's own declaration
  would misrepresent the capture — and the author can fix the
  declaration, which is what a refusal asks.
- **A joined page over the cap DISCLOSES AND DROPS**: the sum of
  admissible declarations is not an authoring error — no single
  declaration is at fault, so no refusal names one. The overflow drops
  from the PLOT alone (the wire shape keeps every joined lane — the B1
  fold's discipline, `dropped from the PLOT alone: the wire still carries
  it`), and each dropped lane lands a REPORTED row:

  `composed lane <id> (role <role>): no lane surface on page <page> (the
  page's channels slots join to <n> lanes; the plot's y admits 64)`

  At exactly 64 joined lanes nothing drops and no row appears (armed);
  at 65 the tail lane drops and reports (armed at 72/8-dropped, with the
  gate rendering clean over the bounded plot — the census counts the 64
  the plot carries, and the channel closure stays quiet because every
  dropped lane's role RESOLVED: the dropped lane's own row is the
  disclosure, not a second one). The overflow is structurally composed
  lanes — the first slot's own count is inside the per-slot ceiling and
  the join order puts it first — which is why the row kind is `composed
  lane` and the class's own lanes never drop.

**F2 (MEDIUM) — a member that applies nowhere inside a partially-applied
pin is no longer silent.** The applied-nowhere disclosure was pin-level
only: a members document with one applying member and one dead one
reported nothing about the dead one — no refusal, no row, no ledger
entry. The fold adds the per-member REPORTED row, in the pin-level row's
wording family, naming the member's slot and the reason; the pin-level
row stays and stays quiet exactly when the pin applied:

`composed member declaration <pin> member <slot> applied nowhere (its
claims name no action this descriptor declares)` — the claim half
mirrors the composed-class row's own wording; the channels half reads
`(no declared channel carries role <role>)`. Both gate arms carry it
(the B6/B7/R3 discipline); `DerivedUI` and
`coverage_plan_without_reference` grow the parallel
`unapplied_members` structure (the coverage tuple is now 8 wide).

**F3 (LOW) — `classref_invalid_member_declaration` joins this record's
committed inventory.** The walk introduced a typed refusal the design's
enumerations did not carry: §3 rule 4 lists the conflict refusals and the
integrity codes but not the member-declaration SCHEMA-validation refusal
(the `_validate_member_declaration` arm, firing on a document carrying
`members` that fails the vendored `composed-member-declaration.schema`
— the `_invalid_composed_class` precedent exactly: a schema-invalid
pinned class document refuses `classref_invalid_composed_class` under
the same posture). §3 rule 4's enumeration extends to name it; it is a
SURVIVOR (M2's "parent §8 survivors" set gains this code alongside the
walk's other integrity refusals — the parent §8 row itself is
gateway-side and rides B7/B8's mirror legs). Fixed by inventory, not by
code: the code keeps its name.

**F4 (LOW) — the gate's `composed_members` read-back reports unknown
keys.** The read-back iterated the closed four-vocabulary set, so
authored junk under any other key (`composed_members.observations`,
anything outside the four) was ignored silently. An unknown key now
REPORTs in the read-back's own wording —
`composed members mismatch: the authored declaration's composed_members
carries key '<k>', which is no composed vocabulary (procedures,
settings, datasets, channels)` — REPORTED, never a findings failure (the
D8 no-schema-yet posture). The four now live in one named constant
(`_MEMBER_LEDGER_VOCABULARIES`) shared by the writer, the read-back and
the unknown-key row: the read-back's loop literal was the third copy of
the four, and a third copy is how the four drift.

**NITs.** The same-document member-slot duplicate now says "declared by
two members in the same pinned document (<pin>)" instead of printing the
pin twice ("<pin> and <pin>"); the two-document form is unchanged. The
R2 ambiguity message stays as committed — the arms assert substrings,
rewording buys nothing and risks the arms (the refute's own note).

**Recorded for the next slice (B4), two facts this fold surfaced:**

1. **The seam does not yet reach production.** The B3 first-commit arm
   proves the validator, the vendored schema and the pinned merge agree
   (`merge_pinned_documents` over `_pinned_schemas` in the test), and
   the negative control proves the seam load-bearing — but
   `presentation.py::validate_presentation` still passes
   `schema_documents=_pinned_schemas(descriptor)` alone, so a vendor
   target would still fail the REAL `check-ui` with
   `capability_mismatch` until the pinned-document merge is wired into
   that path. B4 wires it, and B4 must carry an arm at the real
   `check-ui` path rather than the test's manual merge — the seam arm
   proves the validator, not the production call.
2. **M1's denominator will not catch an F2-shaped silence.** A dead
   member inside an applied pin is in neither M1's numerator (it derives
   no surface) nor any residual row (a member that applies nowhere
   injects nothing, so no vocabulary's residual walk sees it) — the
   per-member REPORTED row this fold adds IS the guard, and M1's
   100%-coverage claim must not be read as covering it.

### 2026-10-25 — B4: the seam wired into production, the two admission refusals, and the V6 classifier

B4 landed in four motions. The corrections the code forced, recorded here
because two are rules, not code:

**The seam rides the production call (the B3 fold's fact 1, answered).**
`presentation.validate_presentation` gains `pinned_documents` — the
descriptor's digest-verified plugin contract documents, read by
`pinned_contract_documents` with the classref walk's own integrity codes
(plus one strict improvement: a pin that is not valid JSON refuses typed
here, where the walk lets the bare decoder error escape — the walk's own
gap is not changed in this slice). `_load_ui_candidate` reads the pins
beside the descriptor and passes them, so `check-ui`, every preview built
from it and the gate's own render carry the merged set. The arm drives
the SHIPPED `check_ui` call from disk; the negative control (the same
package, the member-declaration pin absent from the descriptor) still
reports `capability_mismatch`, so the pinned row is load-bearing in
production, not decorative.

**Two admission refusals, both application-scoped.** An APPLIED
procedure or configuration member composes a target with two admission
requirements the canonical validator enforces: a vendor profile row
naming the claim, and a catalogue side for `input_schema_id`. The walk
refuses the missing half under existing codes — `classref_invalid_member_declaration`
for a declaration with no profile row (a cross-array conditional the
0.1.0 dialect schema cannot express; NOT caught: a row whose
required/optional actions omit the claim — the validator's
`capability_mismatch` finding at check-ui), and `classref_unknown_action`
for a claim no served or pinned catalog describes (the D4 rule's member
half — without the catalogue side the derived target carries
`input_schema_id: None` and the validator refuses it twice over, so the
derivation refuses at the claim instead of emitting a document the
validator rejects). Both refusals are APPLICATION-scoped: a member that
applies nowhere composes nothing and stays the applied-nowhere
disclosure, so the B3 dead-member arms are untouched. Dataset members
are exempt from both until B5 composes their targets; the exemption is
stated where it is enforced.

**V6's residual classifier is the derived state — a design correction.**
§4 V6 says the row fires for "a configuration-shaped declared action";
OTDP types no verbs, and no descriptor-side signal distinguishes a
configuration verb from a run verb. The classifier is what the
derivation can honestly read: unclaimed by any slot (plan page
device-features) AND level L2 (staged). This also names class run-verbs
that stage on device-features (`otdp.smu.arm`, `otdp.smu.fetch` in the
render arms) — accepted because the row's STATEMENT is true of
everything it names and the row is advisory REPORTED, never a failure;
the alternative was silence on a real gap. The row disappears when a
settings member claims the action (armed).

**Binding resolution consults slot keys.** `_urn_for_binding` resolved
by action slug alone — the class convention binding id == slug — so a
member slot named anything else rendered no control while a sibling
data-table satisfied the per-page L3 coverage check (the laundering
shape risk #6 names, L3 flavor; the pooled `data-table` expect caught it
because B4's arithmetic counts composed members). The slot-keyed map now
wins; the slug scan stays the founding fallback.

**Both writers write every settings asset.** `create_ui_resources` and
the CLI's `derive-ui` each carried a single hardcoded
`settings/configure.schema.json` write; with a second configuration
surface the manifest named an asset no writer produced (a check-ui
`unresolved_reference` and a host-load refusal). Both now write one
asset per surface from `DerivedUI.settings_schemas` (slot-keyed, the
map mirroring `preset_scaffolds`); `settings_schema` keeps the founding
single-slot semantics for single-surface consumers.

**V1's REPORTED surface, stated plainly (§4 V1's own instruction):** a
declared procedure member always derives at least its control, so V1
carries NO derives-nothing residual row and none was invented — its
disclosure surface is the applied-nowhere family alone (the walk's rows)
plus the action track's `custom|composed` rows.

**The M-400 fixture extension** carries a vendor configure slot
(`vendor-configure`, naming `com.meridian.m400.profile_mode/1.0.0`) and
a sweep procedure slot (`sweep`, naming `com.meridian.m400.sweep/1.0.0`)
on one descriptor, with the vendor catalog pin beside the member
declaration — the production shape the refusals above describe. The
acceptance arms that moved are marked in place; both new B4 arms drive
the real derive, the real gate, the real host render and the production
`check_ui` over the derived package.

### 2026-10-26 — the B4 refute fold: five findings, one commit

One adversarial lane reviewed the slice; it confirmed the seam is
production-reachable and load-bearing, found no kill condition, and raised
one MEDIUM-HIGH plus four lower findings. All five fold here, each with a
RED arm quoted in the commit message.

**F1 (MEDIUM-HIGH) — the binding-id map hijacked slug-minted nodes.** The
B4 slot-keyed map (the M-400's `vendor-configure` fix) resolved by binding
id ALONE, so an unclaimed vendor action whose slug spells a reference slot
key (`capture`, `configure`: natural vendor verbs) had its
device-features button re-resolved to the SLOT's action, and the
ladder-numeric insert welded the slot action's numeric fields onto the
vendor button — the arm shows `otdp.logic_analyser.fetch`'s `max_bytes`
riding `com.meridian.m400.capture`'s button beside its own `shots`. The
mint sites know their own URN, so the fix records it: the unclaimed-slug
loop and `_complete_authored_buttons` write a per-page
`minted: binding_id -> urn` consumed FIRST by `_insert_ladder_numerics`,
and the slot-key map a page's nodes resolve through is scoped to the slot
keys PLACED on that page (`_urn_for_binding` keeps the founding slug scan
for authored nodes). Byte stability held: all nine derivations
identical.

**F2 (MEDIUM) — the pooled data-table count laundered coverage, two
shapes.** (a) Strip the member's table, pad a data-table node on another
page: the pooled expect row re-satisfied, check-ui clean, gate clean. (b)
The logic_analyser class carries no `data-table` expect row at all, and
its L3 coverage rows ride the A02 birth deviation — stripping every
configuration table left the gate clean. The fix follows the L2
precedent (`staged_control_ids` censuses per action, the gateway #463 RC
fold): the render attributes every data-table to its binding
(`data-bw-binding`, the numeric-branch flags precedent in `web.py`), the
census collects `data_table_bindings`, and the gate's new
`_data_table_surface_findings` compares (page, binding) SETS against the
derived layout's own minted surfaces — never sums. The MISSING direction
is not ledger-downgradable (the W6 ruling: an overlay that drops what the
derivation minted does not clear the debt); the EXCESS direction
downgrades under a declared `data-table` expectation row like every
additive count drift (A6). The L3 coverage row keeps its per-page test —
the per-surface arm is the teeth, not a rewrite of the coverage question.
The `test_red_sanity_neutralized_detector` arm now neutralizes BOTH
detectors, with the move marked in its docstring: the per-surface arm
reds the function_generator strip independently of `_assert_expect`, so
neutralizing the count detector alone would prove nothing about either.

**F3 (LOW-MEDIUM) — derive and check-ui disagreed on colliding pinned
`$id`s.** Two pinned catalogs sharing an input-schema `$id` derived green
(the walk keys actions by URN and never read `$id`s) while check-ui's
vendored merge refused `pinned_id_shadow`. The walk now runs the SAME
vendored guard (`merge_pinned_documents` through
`presentation.check_pinned_id_shadows`) over exactly the accepted pin
set, under the guard's own code — one shared enforcement point for both
composition surfaces, as the vendored docstring already intended.
Inventory note: `pinned_id_shadow` joins this record's committed refusal
inventory as a walk-side code that is NOT `classref_*`-prefixed — it
names the vendored guard's own code so the two surfaces agree by
construction; the walk's integrity codes stay prefixed as they were.

**F4 (LOW-MEDIUM) — an ignored pin still contributed a profile row.** A
digest-verified document matching no pin shape was disclosed as having
contributed nothing, yet its profile row landed in the validator's
admission map and a target naming that profile validated — the
disclosure's claim was false at check-ui. The shape discriminator now
lives in ONE place (`classref._pin_shape_groups`) shared by the walk and
`pinned_contract_documents`, and the reader drops ignored-shape pins: only
documents the walk accepts may contribute anywhere. The declaration shape
(`members`, with its optional profile row) is what carries a row.
Residual, named: an AMBIGUOUS pin (two shape groups) refuses the derive
but would still merge at check-ui — pre-existing, unchanged by this fold,
and unreachable from a green derive.

**F5 (LOW) — the V6 classifier named class run-verbs as vendor settings
members.** `otdp.smu.arm` and `otdp.smu.fetch` reported as settings
members on every SMU plugin. The served profile row's required/optional
actions are the one honest class-action signal: an action a claimed
profile's served row lists is a class action, never a vendor settings
member, whatever its derived level. The motion is measured: the smu
fixture's `residual_members` digest moves
`3da8f5d5a1eb963b -> 37517e5f3dc66819` (the family's empty-residual
digest) and every other derivation is byte-identical — the keep direction
(the logic_analyser's `com.veridian-labs.auto-threshold`, the M-400's
staged vendor actions) still reports.

**NIT.** `check_ui`'s `Raises:` docstring lists the pinned-document
`ValueError` (`classref_vendor_catalog_*:`) the B4 motion 1 wiring added.

**Test-harness motions, named:** `helpers_classref.build_classref_project`
writes every settings asset from the per-slot map (the single-slot
convenience pins the WRONG bytes on a composed project — the M-400's
manifest digests the map's bytes, not the convenience's), and
`_check_ui_clean` feeds the production pinned-document seam plus every
settings asset — a composed package cannot be check-ui-clean through the
bytes-only call without them. `test_classref_member_seam._check_ui_package`
gains `descriptor`/`extra_pins` substitution so variant packages stay
internally digest-consistent.

### 2026-10-26 — B5, motion by motion: what the code forced, stated where the design was silent

**The dataset member's admission refusals split by target shape.** The B4
admission pair (profile row + catalogue side) does not transfer to the
dataset kind as a pair: the profile-row refusal DOES (an applied dataset
member composes a target naming the declaration's vendor row — the seam —
so a row-less declaration is malformed for the surface it requests, under
`classref_invalid_member_declaration` exactly as for procedure and
configuration), while the catalogue-side refusal does NOT and never will:
the dataset target carries `measurement_schema_id` (the descriptor's pinned
measurement contract), never `input_schema_id`, so there is no catalogue
side for the claim to need. The B4 sentence "Dataset members are exempt
until B5 composes their targets" resolves to this split, stated where it is
enforced.

**The V4 layer-3 classifier is the derived state — the V6 precedent.**
§4 V4's "a capture-shaped declared action" has no descriptor-side signal:
OTDP types no verbs, and `capture_formats[]` is device-level (read by
nothing in the SDK — measured). The classifier is what the derivation can
honestly read: unclaimed (plan page device-features) AND level L1 (the
bare-button shape; L2 is the settings vocabulary's own row, and L0 renders
nothing so "its control renders on device-features" would be false of it),
under the same class-listed exclusion B4's F5 minted (a served profile
row's listing is the one honest class-action signal). Measured before
implementation: no committed fixture carries an unclaimed L1 action, so
the founding residual digests do not move — the row's statement is true of
everything it names (advisory REPORTED, never a failure), and it
disappears when a dataset member claims the action.

**Two placement rows, one wording family.** The 2026-10-25
capacity-versus-declaration boundary ruled the already-hosted-plot case
(B3's row). B5 adds its sibling the boundary implies but had not named: a
member `plot` naming a page whose KIND the manifest schema admits no plot
on (configuration; the family's own plot def carries no page-kind rule,
so the member schema cannot refuse it at the pin) derives nothing and
discloses — `composed plot <slot>: page <page> admits no plot (plots
render on dataset and readings pages alone)`. The B3 interim arm that
asserted no row for any plot-less page moved with it (marked in place).

**The lanes plot binds its over-slot's own dataset.** The founding
digital_lanes emission bound `capture_binding_id` — correct for the corpus,
where every lanes plot's over-slot IS the capture slot, but dishonest for a
composed lanes plot over a member's slot: the plot's y names lane string
variables, which the class capture's waveform shape does not carry. The
emission now binds the over-slot's own binding; on every committed fixture
the two are the same id, so all eight founding derivations are
byte-identical (proved by digest at this slice's commits: manifest
9d744557d304ff8e daq, 8764b42c16878880 f1/logic_analyser, and the other
six unchanged from the B4 base).

**Risk #6's falsifier is a REPORTED row plus a stamp discipline.** A
composed dataset slot on a plot-bearing page whose plot does not carry its
binding: the L4 census on that page still covers it (plots >= 1), and the
row that keeps the coverage honest is `composed dataset <slot>: no plot
carries its binding (the plot on page <page> binds <over_slot>)` —
REPORTED, never a finding — beside the `rendered_by: "the page plot"`
stamp that lands ONLY when a derived plot carries the member's binding
(the R9 site, after plot construction). Both directions armed: the row
disappears and the stamp lands when the member's own plot derives.
