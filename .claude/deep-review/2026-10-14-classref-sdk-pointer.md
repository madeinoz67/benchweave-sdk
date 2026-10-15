# Class-reference SDK pointer — logic_analyser vertical slice

**Date:** 14 October 2026
**Authoritative record:** `madeinoz67/benchweave` `.claude/deep-review/2026-10-14-classref-logic-analyser-design.md`
(branch `feat/classref-gw-c7k2`, Landing 1) — schema, reference content, expansion
semantics, gate method, acceptance rules A1–A8, deferral table D-1…D-8. This file only
binds the SDK side; where the two disagree, the gateway record wins.

## What the SDK builds (Landing 2, gateway issue #463 rows 1–2 + the gate)

1. **Ingest the standard.** `plugin-ui-class-reference/0.1.0` (schema +
   `class-logic_analyser.json`) arrives through `sync-standards` into the vendored tree
   and `standards-lock.json`. Build-time verification: if any SDK surface enumerates
   standard families, the new row lands in the same change.
2. **Expander** — new module (`classref.py` shape): descriptor + reference → the three
   plugin-ui documents at `active_version("plugin-ui")` (0.3.1 today), plus
   `ui/settings/configure.schema.json` materialised from the configure action's
   EFFECTIVE schema (catalogue ∧ `input_constraints` — the real mechanism is
   conjunctive validation; the expander derives per-field effective admittance for
   controls: numeric-bounds intersection, enum/const, `pattern` only when enumerable,
   anything else marks the field inexpressible → L0 deviation while existing lanes
   keep enforcing it), plus the numeric expectation document (gateway record §3),
   plus the `plugin-ui-class-reference:layout` extension block (gateway record §2.6:
   namespaced, family-schema'd, riding the 0.3.1 `extensions` seam — the canonical
   validator is extension-blind, verified; NO plugin-ui bump, NO ui-html change).
   Fail-closed prefixes: `classref_no_lanes:`, `classref_lane_ceiling:`,
   `classref_required_action_absent:`, `classref_unknown_action:`,
   `classref_target_version:`, `classref_invalid_reference:`,
   `classref_expect_expression:`, `classref_constraint_unsupported:`,
   `classref_effective_schema_conflict:`, `classref_effective_schema_empty:`,
   `classref_layout_invalid:`.
3. **Overlay composition (D12b)** — `ui/manifest.json` is derived wholesale (dirty-tree
   refusal without `--force`); `ui/manifest.overrides.json` is the author-owned overlay
   (merge by stable id; `overlay_delete_refused:`, `overlay_immutable_field:`; composed
   result must pass the canonical validator); `ui/class-reference.json` is the author's
   conformance declaration + deviation ledger (`classref_unknown_expectation:`).
4. **Effective capability (D13)** — per action, the effective schema = catalogue
   `input_schema` ∧ descriptor `input_constraints` (closed intersection vocabulary:
   type-within-family, enum, const, min/max/exclusive*/multipleOf; unknown keywords
   refuse `classref_constraint_unsupported:`; type-family conflicts
   `classref_effective_schema_conflict:`; empty admittance on a required field
   `classref_effective_schema_empty:`). Bounds/enums/consts of every rendered control
   come from that intersection; `const` renders read-only. Multi-profile descriptors
   merge their references under one manifest (first profile bare, later profiles
   `{slug}-` prefixed; `classref_profile_slot_conflict:` on double-claimed URNs).
5. **Coverage + Device features (D14)** — the reachability ladder (L1 button / L2
   numeric staging / L3 preset-mediated / L4 dataset; L0 = declared deviation) derived
   per action from the effective schema minus `host_supplied` names; a
   `vendor_actions` slot renders unclaimed URNs (vendor profiles from the descriptor's
   pinned catalogs) as a §E-only "Device features" page; the gate's coverage arm is
   ALWAYS ON (`classref_gate_uncovered:`) and is wired into the generated project test
   so plugin CI runs it.
6. **Gate (D5)** — `benchweave-sdk verify-ui`: validate → derive → render through
   `benchweave_sdk_server.web.build_app` over in-process ASGI (httpx; no subprocess) on
   the `[server]` extra's exact `benchweave-ui-html` pin → census via stdlib
   `html.parser` keyed ONLY on ui-contract §E.1 surfaces (class hooks +
   data-attributes) → assert the numeric expect, apply declared deviations, fail
   undeclared divergence (`classref_gate_missing/excess/forbidden/undeclared:`).
7. **Host consumption of the layout block (D12a roll-in)** — `benchweave_sdk_server`
   composes the `plugin-ui-class-reference:layout` block by grouping and ordering the
   §E.1 partials it ALREADY renders (panels, buttons, staging pairs); the ui-html
   package, its contract harness and the vendored canonical validator are untouched;
   a host that does not know the namespace ignores the block (degrade-by-ignoring).
   The extension-blindness control (a layout-bearing manifest passes the canonical
   validator unchanged) is pinned by a test — it is the load-bearing fact the seam
   rests on.
8. **CLI** — `derive-ui`, `verify-ui` (names free at v0.12.0).
9. **Docs (D8)** — the expander prints `cannot_derive` rows; AI-GUIDE/UI-GUIDE carry
   them (thresholds, arm-safety, lane-names, presets, decode-settings — gateway
   record §2.3).
10. **Tests** — acceptance A1–A11 (gateway record §6) over the synthetic fixture set
   (F1 two-channel class descriptor, F2 32-channel "Veridian LA-32" d-series
   `d0`..`d31`, the F3a/F3b narrow-vs-programmable capability pair (F3b at 34
   channels carrying the partial-group arm), four refusal fixtures, the banked
   baseline fixture, the overlay fixture, the vendor-catalog fixture, the
   hand-authored layout manifest); the D2 string-trace test; RED-first per the repo
   gates.
11. **Release** — `make release-cut` so the gateway pointer can advance to a tag
    (Landing 3).

## Program scope (owner ruling "all in", 2026-10-14)

Every row-call row rolled into the train — nothing defers. This record's build list
is LANDING 2 of the program sequence (gateway record §7A) and now also carries:

- the `decode_annotated` overlay — decoder-lane derivation for the annotation form
  when the descriptor pins decoder declarations (same expander code surface);
- preset SCAFFOLD derivation (A12): the expander emits the preset document structure
  with `preset_asset_ids` wiring; commissioning values are authored through
  check-preset (A02 unamended — values are never derived).

Later landings with SDK-side work, per the program sequence: L5 (plugin-ui
0.3.1→0.4.0 §E.1 input components — the `contracts.py` version-literal edit paid
once; D4 amended for that row only), L6/L7 (#460 upgrade artifact migration, #461
venv symlink damage — own design records), L8–L10 (#463 rows 3/7/8 — own records),
L11–L21 (the class sweep, dc_psu first). The umbrella tracker stays gateway #463.

Disclosures that are not deferrals: the overlay/declaration files ship inert in the
wheel; preview carries no bench policy (A02 — the intersection there is catalogue ∧
constraints, disclosed in the gate output).

## Tier

Tier 3 (rubric rule 1 — JSON Schema bytes in the vendored tree — and the `sha256`/
`hashlib` keyword rule in expander + tests). The gateway record §9 carries the scan
table; the SDK diff's own scan re-derives at review.
