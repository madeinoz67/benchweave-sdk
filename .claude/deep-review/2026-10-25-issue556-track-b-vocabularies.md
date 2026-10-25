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
