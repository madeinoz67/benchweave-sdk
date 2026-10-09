# Issue #286 — Standalone Web UI I4b: the rest of SW-52 — design record

Date: 2026-10-08. Status: DESIGN (no code written). Repo: `benchweave-sdk`
(expected branch `feat/issue286-i4b-analysis-extensions`, created from
`origin/main` = `24c76fb`, the I4a merge). Tracking: gateway issue #286
(single issue stream); PRD 11 (`docs/implementation-planning/11-standalone-web-ui-prd.md`
in the gateway tree, Draft v0.3 amended 2026-10-07) is the requirements
authority. This record is the **I4b slice design**: it takes the I4 design
record (`2026-10-07-issue286-i4-analysis-reporting-design.md`, committed with
I4a) as its pre-committed base — that record's §1 I4b mechanism sketch and its
AR-2/AR-3 acceptance rules stand — verifies every premise against the LANDED
tree, and specifies what I4b builds.

Design lane note: this record is the builder's commit 1 on the slice branch
(I3/I4a's precedent). If the builder finds the file already present in the
checkout, it commits it verbatim; if it finds only this text in the lane
transcript, it writes these bytes first. Disclosed, not silent.

Triage note (per this directory's README): this record is deliberately public —
it names no person, client, bench, device serial, commercial term or machine
specific. The one external repository it draws definitions from is cited the
way the parent record cited it — "the fork", with the public provenance PRD §5
already carries in the gateway tree. Fixtures use invented names (`fx-*`).
Honest negatives (the fork behaviours not carried) are first-class and stay
public.

## 0. Verification of premises (done before designing)

Everything the dispatch flagged as "landed since the record was written" was
re-verified on `24c76fb` (native Read over the SDK standalone checkout — the
gortex daemon tracks only the gateway repo in this workspace
(`workspace repos` = `BenchWeave`), so the SDK tree is unserved by the graph
and the disclosed native route applies; the fork's definitions were re-read
from its public bytes on 2026-10-08):

- **`analysis.windowed_points` is incremental and self-verifying** — confirmed
  (`analysis.py:282–332`): the window list refuses the moment it would exceed
  its `limit` (l.319–324, the ceiling binds the allocation) and the SECOND
  primary read re-hashes and refuses `standalone_report_primary_mismatch`
  (l.325–331). I4b's marker placement and zoom rendering read points only
  through this path (or the new streaming reducer in §1.5), never raw.
- **The Analyse view shares export's admission** — confirmed
  (`seam.py::analysis_view`, l.2549–2567: `_stale_row_refusal` before load;
  `_stale_row_refusal` itself at l.2204–2224 self-heals stale index rows and
  refuses `not_found`). Every I4b surface that names a capture id reuses it.
- **The brush IS the zoom** — confirmed (`ui_assets/analyse.js:41–53`): the
  hook reads `plot.scales.x` inside uPlot's own `setScale` (the vendored
  defaults carry `drag.setScale = true`), so the dragged region IS the zoomed
  extent and the form re-submits it as `lo`/`hi`. **This is the fact that
  redefines the zoom-region feature** — §1.5.
- **`report.py`'s landed honesty posture** — confirmed: union-extent per-unit
  y scales (l.301–327), non-finite samples as gaps never coordinates
  (l.367–375, plus the B-F8 `n/a (non-finite)` mark in `format_number`,
  l.81–93), window shading (l.357–365), clock-free bytes with `generated_at`
  only in the sidecar (`seam.py:2485–2487`).
- **Retention/reserved surfaces** — confirmed: `_RESERVED_ROOT_DIRS =
  {"reports"}` (`retention.py:471`) and the sweep skips any directory with a
  `manifest.json` (l.513). Reports pin sources on EVERY export (`seam.py:2500–2505`).
- **The I4a fold waves changed the shape I4b builds on** (all confirmed in the
  tree): the union-extent fix (a same-unit series can no longer escape the
  viewBox), the escaping discipline on EVERY attribute slot
  (`web.py:208–213`), the non-finite window admission (`web.py:1175–1198`,
  `seam.py:2404–2421`), the no-orphans rule (a refused export leaves no
  `reports/`), and the closed-set/twin-census pin bump for row 22 and the two
  new modules (commit `1500e8f`).

### The definitional re-derivation against the fork (the AR-3 contradiction)

The parent record's AR-2/AR-3 were pre-committed from a first read of the
fork. This lane re-read the fork's actual functions. One pre-committed figure
is arithmetically wrong and is amended below with its contradiction cited;
everything else holds.

- **Edge timing — AR-2 CONFIRMED.** The fork's `edgeAnalysis` (app.js
  l.2111–2145) matches the parent's summary line for line: `n < 3` → null
  (l.2113); head/tail `max(1, floor(n × 0.15))` means (l.2115–2118); flat
  guard `|step| < 0.005 × max(|baseline|, |final|, 1e-12)` (l.2121–2122);
  `t10`/`t90` = interpolated crossings of `baseline + 0.10/0.90·step` in the
  step direction (`crossTime`, l.2098–2109); `riseTime = t90 − t10` (l.2128);
  settle band = `settlePct`% of |step| **around final** (l.2130–2132);
  `settleTime` from `t10` to the first sample after the last out-of-band
  sample (l.2133–2142). Three details the parent left implicit are pinned in
  §5 AR-2 as **precisions** (not amendments): the region count is the
  NON-NULL in-window count (fork `regionPoints` l.2081–2087 drops nulls before
  the `n < 3` check); a missing `t10` or `t90` yields `riseTime: null`, never
  0; and `settleTime` has two edge outcomes the parent did not write down —
  0 when nothing ever left the band, and `null` ("not settled within the
  region") when the region's last sample is still outside it (fork l.2141–2142).
- **Power — AR-3 CONFIRMED except one figure, AMENDED.** The fork's
  `trapezoid` (app.js l.1432–1448) integrates over SAMPLE TIMESTAMPS with
  partial-span clipping (`a = max(t0, lo)`, `b = min(t1, hi)`, linear
  interpolation at the clipped bounds). The landed time base is
  `t = index × sample_interval_s` (`analysis.py:191–203`, printed on every
  report at `report.py:160–161`). Therefore `fx-pair-const` as the parent
  wrote it (V = 2, I = 3, 100 Hz, "T = 3.6 s") holds **N = 360 samples
  spanning t = 0 … 3.59 s**, and the fork's own trapezoid yields
  `6 × 3.59 / 3600 = 0.0059833… Wh` — not the parent's stated `0.006 Wh`.
  `0.006 Wh` is the naive `6 W × (N × interval)` product; the trapezoid spans
  `(N − 1) × interval`. The parent's own null arm (`count 359`) pins N = 360,
  so the two figures in that one fixture contradict each other under the
  fork's definition. **Amendment (§5 AR-3): the energy figure becomes
  `6 × (N − 1) × interval / 3600 Wh` = 0.0059833… Wh (≤ 4 ulp vs the closed
  form); `count 359` and `mean power 6 W` stand unchanged.** Citation for the
  contradiction: fork `trapezoid` l.1432–1448 vs the parent's
  `energy 0.006 Wh (≤4 ulp)`; the landed time base at `analysis.py:202`.
  The honest-null arm also stands as written — the fork's null→0 coercion
  (`powerPoints` l.1425–1426, `powerRegionStats` l.1477–1478) really would
  report ≈5.983 W, so that arm discriminates exactly as designed.
- **Pairing keys on unit/quantity — CONFIRMED, and the fork's own role-guess
  is NOT carried.** The fork classifies quantity by unit string
  (`unitKind` l.1569–1574: lowercased, µ/μ→u; `{a, ma, ua, na}` → current;
  `{v, mv, uv, kv}` → voltage; else other) and uses series NAMES only to
  disambiguate dc-dc in/out roles (`pickBy` regexes l.1584–1589,
  `guessRailPairs` l.1615–1617), falling back to index order. Q8's ruling 2
  ("pairing keys on unit/quantity, never names") closes the name route: the
  name regexes join the not-carried list (§6), and roles come from explicit
  operator selection over a deterministic default (§1.4).
- **The four power modes — captured** (each block's exact arithmetic, for
  AR-11): `battery` (app.js l.1922–1935: Ah = `trapezoid(I)/3600`, Wh from
  V×I, I avg/peak, V avg/min, P avg/peak, runtime = `capacity_ah / mean I`),
  `dc-dc` (l.1938–1952: per-rail `railStats` l.1591–1604, η = `pout/pin × 100`
  only when `|pin| > 1e-9`), `sleep` (l.1954–1987: threshold split, duty %,
  class means), `load-step` (l.1989–2016: 15% head/tail means on V and I,
  ΔV, ΔI, `R = −ΔV/ΔI` only when `|ΔI| > 1e-9`). Two fork defaults are
  NOT carried (§6): the sleep threshold's midpoint fallback (l.1962) and the
  empty-class mean coerced to 0 (l.1973–1974).
- **Markers — captured** (`placeMarker` l.1319–1329: A–Z label, replace-on-
  duplicate, sorted by label, `{label, t, note}`; per-capture
  `PUT /api/captures/{stem}/annotations` l.1357–1374). The fork persists
  rails by series NAME (l.1735–1737) — ours key on `capture_id`.
- **Assertions — captured** (`assertionSpec` l.39 = `[{name, min, max}]`;
  evaluation is server-side returning `{passed, checks, results}` with
  `found: false` = "no matching channel"; pass = actual min/max within the
  given bounds; `checklistText` l.1868–1891 is the report-facing why). Ours
  keys on `capture_id`, adds `not_evaluated` (the parent's honesty upgrade),
  and refuses an assertion naming a capture outside the request set.
- **The report zoom block — captured** (fork `web/report.py` l.257–276): the
  report's main chart covers the FULL series with region shading, and the
  zoom block is a SECOND SVG over the zoom span with y ranges recomputed over
  that span and markers filtered into it. The fork's UI carries THREE regions
  (brush `brushStart/End`, power `powerLo/Hi` l.1543–1557, zoom
  `zoomLo/Hi` l.32–34) — see §1.5 for what survives that in the landed
  single-region tree.

### SW-50's shape (the markers home)

PRD SW-50: "The SQLite index (projects, tags, annotations, markers, analysis
settings) is rebuildable from the capture root and never the only copy of
anything." Markers and analysis settings are named index content whose copy
of record lives in the root. The landed index (`library._row_of`,
l.151–167) has 12 columns and no markers/analysis column; the rebuild
(l.237–272) reads `manifest.json` + `metadata.json` only. That is the
contradiction behind the one other amendment (§5 AR-8's companion note):
the parent's "the library index caching it" is **deferred**, because
SW-50's load-bearing clause ("never the only copy of anything") holds as soon
as `analysis.json` is the root copy of record, while the cache is pure
acceleration whose schema motion the parent's parenthetical did not price.
Trigger to reopen: the first list surface that needs marker/analysis state in
a row (e.g. a captures-page badge).

## 1. Mechanism

Two build sub-slices, one code layer each. **Cut line: single-series ×
single-region vs cross-series pairing.** Everything in I4b.1 works on one
series over the one window; I4b.2 is the only family that composes two
series. This splits `analysis.py`'s growth into two coherent layers (per-series
region machinery, then pairing machinery) and keeps each PR reviewable —
I4a's one slice already took three fold waves, and I4b as one diff would take
more than twice that. (The alternative cut — markers with power as a
"stateful" pair — was rejected: those two share no mechanism.) Neither
sub-slice touches `src/benchweave_sdk/` core, `standards/` bytes, version
strings, or `pyproject.toml`/`uv.lock` (PKG-1/2/3 hold; SVG, statistics and
JSON are stdlib).

**I4b.1 (this branch builds):** edge timing (AR-2), min/max assertions
(AR-7), A–Z markers with notes (AR-8: `analysis.json` overlay + annotate-
family row + click-to-place), and the report's zoom/context pair (AR-9).
**I4b.2 (named deferral, immediate successor):** power modes with V/I pairing
(AR-3 amended, AR-10, AR-11). The I4 record pre-committed all five families
as one "I4b"; this record keeps every pre-committed rule and moves AR-3/AR-10/
AR-11 onto the successor slice's build. If the maintainer prefers one PR, the
mechanisms and rules below stand unchanged — the split is a review-size call,
not a design fork.

### 1.1 Edge timing (`analysis.py`, pure) — I4b.1

`edge_analysis(samples, *, lo, hi, settle_pct) -> EdgeTiming` over the
window's **non-null** samples in acquisition order (the fork's
`regionPoints` semantics — nulls drop out before the count):

- `n < 3` → `detected: false` (an honest negative; the parent's `not_detected`).
- `head_n = max(1, floor(n × 0.15))`, `tail_n` likewise; `baseline`/`final` =
  means of the first/last `head_n`/`tail_n` samples.
- `step = final − baseline`; flat guard `|step| < 0.005 ×
  max(|baseline|, |final|, 1e-12)` → `detected: false`.
- `t10`/`t90` = first interpolated crossings of `baseline + 0.10/0.90·step`
  in the step direction (linear between bracketing samples; a level the
  region never crosses yields `None` for that crossing).
- `rise_time = t90 − t10` when both crossings exist, else `None`.
- settle band = `settle_pct/100 × |step|` around **final**; scanning from
  `t10` (or the region start when `t10` is missing), `last_outside` = the last
  in-band-scope sample outside the band; `settle_time` = 0 when no sample
  left the band, `t[last_outside + 1] − t0` when such a sample follows
  (`t0 = t10` else region start), and `None` when the region's last sample is
  still outside ("not settled within the region").
- Every row carries definition id `benchweave-edge/1`, the `host-computed`
  label and its denominators: `n`, `head_n`, `tail_n`, `settle_pct`, `lo`,
  `hi` (SRF-4's rule extended to the new computation families; the maintainer
  may re-family the id at landing, SRF-4's provisional-ID posture).

`settle_pct` is an operator-editable display default of 2 (the fork's
fallback, app.js l.2182) — a statistical band parameter printed on every
block, explicitly **not** a commissioned envelope (A02 posture: nothing
protective keys on it).

### 1.2 Min/max assertions (`analysis.py`, pure) — I4b.1

`evaluate_assertions(spec, entries) -> list[AssertionResult]` where each spec
row is `{capture_id, min?: float, max?: float}` with **at least one bound**:

- The target must be one of the request's source captures (else the request
  refuses `invalid_request` — make the miss unrepresentable rather than
  rendering `found: false` forever); bounds must be finite (the B-F4 family,
  refused at admission like the window).
- The verdict reads the entry's window `RegionStats`: `pass` iff
  (`min` absent or `actual_min ≥ min`) and (`max` absent or `actual_max ≤ max`);
  `fail` otherwise with machine-readable `reasons` (`below_min`, `above_max`);
  `not_evaluated` when `count == 0` (empty window — **never `pass`**, the
  parent's honesty rule) or when the target series contributed no samples.
- Verdicts carry definition id `benchweave-assert/1`, `host-computed`, and
  denominators (window, `count`, `null_count`).

### 1.3 A–Z markers with notes (`analysis.json` overlay) — I4b.1

**The overlay.** Per event directory, `analysis.json`:

```json
{
  "format": "standalone-analysis/1",
  "markers": [{"label": "A", "t": 0.512, "note": "load applied"}]
}
```

- Labels are single uppercase `A`–`Z` (the fork's own regex shape,
  `/^[A-Z]$/`); one marker per label (replace-on-duplicate, the fork's
  `placeMarker`); rows sorted by label on write so re-export is stable.
- `t` is finite and must lie inside the capture's own time base
  `[0, (sample_count − 1) × sample_interval_s]` — a marker that names no
  point the capture can display is refused (`standalone_report_marker_invalid:`).
- `note` is free text (the `capture_annotate` notes precedent — no invented
  cap), HTML-escaped everywhere it renders (AR-4e's arm extended to notes).
- Absent or unparseable `analysis.json` reads as `{}` — the library's
  honest-defaults rule (`library._read_metadata` l.129–140 is the precedent);
  it is never a load precondition.

**The write.** One new catalogue row **`capture_analysis`** — the fifth
disclosed delta beyond SW-10's closed 18, under F-C's adopted posture
(SW-50 names the capability; the closed list omits it). It takes
`{capture_id, markers}` and rewrites `analysis.json` with
`library`-style temp-write + `os.replace` (`_write_metadata` l.143–148 is the
exact precedent). Admission is `_stale_row_refusal` (the `capture_annotate`
shape, `seam.py:2226–2243`). The result echoes the stored rows (operator
annotations are input, not processed values — #423's exposure boundary is
about processed values and is unaffected; processed-value READS stay off
REST/MCP exactly as in I4a). REST and MCP pick the row up through the
existing catalogue loops (`web.py:182–187`; `mcp.py`'s registration +
`_tool_handlers` drift check). **One overlay per call:** a request carrying
both `notes`/`tags` and `markers` refuses `invalid_request` (each call
rewrites exactly one authority file, so every rewrite is atomic —
`metadata.json` stays SW-54's start-fixed-plus-notes surface, untouched).

**Amendment to the parent's marker bullet:** "with the library index caching
it" is **deferred** (see §0's SW-50 discussion). The index gains no column in
I4b; `analysis.json` is the copy of record and `library.remove` (rmtree of the
event dir, l.328–338) takes it with the capture exactly like `metadata.json`
(SW-57's together-rule — a pruned capture takes its annotations; an exported
report keeps the rendered notes in its own bytes).

**The view.** Marker rows join the analyse form (label/t/note fields, the
existing no-JS path); **click-to-place** fills the selected label's `t` from
a plot click (extending the page-scoped `analyse.js` against the same closed
uPlot surface it already uses — `plot.scales.x` pixel→value via the uPlot
`valToPos`/scale API, or the numeric field alone if the spike says the
wrapper stays closed; the numeric path is complete either way). A "Save
markers" submit POSTs to a small page route over the `capture_analysis` row;
the htmx stats POST carries rows as form state.

### 1.4 Power modes with V/I pairing (`analysis.py`, pure) — I4b.2

**Pairing (Q8 ruled 2): by unit/quantity, never names.** Each loaded source's
manifest `unit` classifies through the fork's own vocabulary
(`unitKind`: lowercased, µ/μ→u; current `{a, ma, ua, na}`, voltage
`{v, mv, uv, kv}`, else `other`). A capture set's default pairing is
deterministic: the first voltage-class and first current-class source in
request order form rail 1; `dc-dc` takes a second pair from the next of each
class. The operator may reassign rails explicitly (the fork's `railSelect`
UX, re-keyed on `capture_id`); the export request carries the **resolved**
pairing (`power.rails: [{v: capture_id, i: capture_id}]`) and the sidecar
records it, so the report is re-derivable. Name-regex role guessing is not
carried (§6).

**Per-sample power and integrals.** Power at a sample is `V × I` defined only
where BOTH are non-null (the null→0 coercion is not carried, the parent's
kill). `trapezoid_integral(points, lo, hi)` follows the fork's definition
(app.js l.1432–1448): per-segment trapezoid clipped to the window with linear
interpolation at the clipped bounds — with the gap rule added: **a segment
whose either endpoint is excluded is dropped** (never interpolated across
missing data), and every integral row reports `integrated_span_s` (the summed
`b − a` of counted segments) and `dropped_segments` beside `Ah`/`Wh`, so a
gapped integral is visibly partial (AR-10). The fork's `t1 − t0 || 1`
zero-span fallback (l.1442) is not carried — the uniform interval is known;
no silent one-second substitution.

**Rows per rail** (`benchweave-power/1`, host-computed, denominators = window,
pair count, null-pair count, dropped segments, integrated span):
`mean`/`peak` power over the paired samples (the fork's `powerRegionStats`
shape, honest-null), `Ah` from the current series alone (the fork's
`railStats` l.1596), `Wh` from the paired power series. **Partial-pair
honesty:** a current series with no voltage partner still yields `Ah`, with
`wh: null` and `power_unavailable: no voltage series` beside it; a set with no
current series yields **no power rows at all** and the reason
`power_unavailable: no current series` — never 0 W (AR-3's arm).

**The four modes are named rail-pairing presentations** over those rows
(AR-11 pins each block's arithmetic): `battery` (Ah/Wh + I avg/peak + V
avg/min + P avg/peak + `runtime_h = capacity_ah / mean_I` when the operator
supplied `capacity_ah`, labelled with its denominators), `dc-dc` (two rails;
η = `pout/pin × 100` only when `|pin| > 1e-9`, else η absent), `sleep`
(threshold split: duty %, per-class means and counts — threshold ABSENT →
`not_evaluated: no threshold`, never the fork's midpoint default), `load-step`
(15% head/tail means on both series, ΔV, ΔI, `R = −ΔV/ΔI` only when
`|ΔI| > 1e-9`, else `R` absent). The fork's separate power region
(`powerBounds` l.1543–1557) is not carried: **the one window is the region**
for every analysis family (§6).

### 1.5 The zoom region, post-brush — what SW-52's fifth item becomes

The parent's I4b bullet is "Zoom-region second chart (the fork's report zoom
block)". The landed brush changed what "zoom region" can mean: drag already
zooms the live plot to the dragged region (`analyse.js:41–53`) and re-submits
it as the analysis window — a second live pane rendering the same `[lo, hi]`
would be literally redundant. The call:

- **Live (already shipped, disclosed):** the drag-brush IS the zoom-region
  interaction (uPlot `setScale`), with the numeric fields as the no-script
  path. No second live chart is built. The fork's z-key third region
  (`zKeyHeld`, app.js l.32–36) is not carried — the landed model has exactly
  one region, and reintroducing a parallel zoom state would fork the UX again.
- **Report (this slice's build):** the fork's two-scale reading survives as
  the report's **context + zoom pair**. `build_report` gains a
  **full-extent context chart** (every source's whole series, decimated to
  `REPORT_PLOT_COLUMNS` via the new streaming reducer below, the analysis
  window shaded, markers drawn) and the existing windowed chart becomes the
  labelled **zoom section** ("Zoom lo → hi") — the fork's zoom block shape
  (its `report.py` l.257–276) with the zoom span = the analysis window. The
  zoom section renders **iff the window is a proper subset** of the sources'
  extent; on a full-extent export only the context chart renders (never two
  identical charts). Each chart keeps SW-25's closed semantics (axes+units,
  legend by form as well as colour, stated time basis, textual description —
  structural arms, SRF-1's no-pixel-parity posture).

**The streaming full-extent reducer** (`analysis.decimated_extent(source,
columns)`): one chunked pass (the `series_samples` chunk discipline) reducing
to per-column (min, max) pairs with `decimate_minmax`'s exact tie-break rules
(first min, last max, single-point column emits one point —
`plots.py:111–126`), O(columns) memory, digest-verified like
`windowed_points`. It exists because the context chart must span captures up
to `_RAW_SAMPLE_CEILING` (10M, `seam.py:185`) without materialising them —
`REPORT_PLOT_SAMPLE_CEILING` (2M) bounds the WINDOWED path and cannot bound a
full-extent path. Parity with `decimate_minmax(list(points), columns)` is an
AR-9 arm (same input, same output — the tie-breaks are load-bearing).

The fork's independent `zoom` request parameter (a third region in
`generateReport`, app.js l.1402–1405) is **not carried**: the export request
keeps `{capture_ids, lo, hi}` as its region, and the resolved marker rows
ride along. If an operator later asks for a pinned detail pane beside a live
full-extent chart, that request reopens the z-key region as a named feature —
the trigger is the ask.

### 1.6 Report, export and request shape (both sub-slices)

`report_export`'s input schema (`catalogue.py:493–516`) grows optional keys —
I4b.1: `markers` (resolved rows; absent → the sources' overlays), `assertions`
(spec rows), `settle_pct` (default 2); I4b.2: `power` (`mode`, `rails`,
`capacity_ah`, `threshold`). The sidecar records the **effective** params
(resolved markers included) so re-export from the sidecar reproduces the
document (AR-4d extended). All new blocks follow the landed caption
discipline (SRF-4): `host-computed` + definition id + denominators. The
rendered bytes stay clock-free; `report_id` stays content-addressed over the
bytes, so marker/assertion/power changes mint new reports and identical
inputs re-export to the same id.

### 1.7 Tests

`tests/server/test_analysis.py`, `test_report.py` grow the §5 arms (and the
per-refusal-path test for every new refusal, NFR-Q4's rule); the
`capture_analysis` row joins the seam/catalogue/MCP parity tests; the
closed-set and twin-census pins bump for row 23 exactly as `1500e8f` did for
row 22. RED controls are named per AR.

## 2. Precedent (proven in-tree mechanisms extended)

1. `analysis.py`'s pure-module discipline (chunked passes, `AnalysisRefusal`
   with `standalone_report_*` prefixes, honest `None` statistics) — edge,
   assertion, power and the streaming reducer extend it in place.
2. `library._write_metadata`'s temp-write + `os.replace` (l.143–148) and
   `_read_metadata`'s honest-defaults read (l.129–140) — `analysis.json`.
3. `capture_annotate`'s catalogue row + `_stale_row_refusal` admission
   (`seam.py:2204–2243`) — the `capture_analysis` row is this shape for a
   second overlay file.
4. `report.py`'s block structure, `_text` escaping and `format_number`'s
   absence/non-finite split — every new block joins; AR-4e extends to notes.
5. `plots.decimate_minmax` (Q12/#310's ruling) — the context chart via a
   streaming entry point with identical tie-breaks.
6. The catalogue → REST/MCP pinning machinery (`catalogue.py`,
   `mcp.py`'s drift check) — row 23 joins structurally.
7. The fork's closed definitions (`edgeAnalysis`, `trapezoid`, `unitKind`,
   `placeMarker`, the report zoom block, the assertion checklist) — the
   migration-compatibility reference, with §6's not-carried list.
8. The seam's `_fail` + `standalone_report_*` message-prefix posture (STD-4) —
   the new refusals extend the SAME prefix family (no new prefix family).
9. `measurement/derivation.py`'s disclosure stance — every new derived value
   keeps `uncertainty: "unknown"` and its denominators (A02/G4).

## 3. Invariants and cross-surface impacts

- **SRF-4 amends** (the processed-value labelling row, ID provisional): its
  anchor set extends to the edge/assertion/power blocks and their definition
  ids (`benchweave-edge/1`, `benchweave-assert/1`, `benchweave-power/1`); the
  rule text already says "its denominators" generically, so only the anchor
  list moves. The report's zoom/context charts are presentation, not
  processed values (the decimation disclosure already covers them).
- **STD-4 posture extended** with the marker/assertion refusals inside the
  landed `standalone_report_*` family (Tier-3 trigger: new refusal paths).
- **On-disk format:** `analysis.json` per event dir (Tier-3 persisted class —
  the parent record's §3 already named it). Derivable content: it holds
  operator annotations only (no computed values), and its write is atomic.
- **Catalogue delta:** row 23 `capture_analysis` under F-C's disclosed-delta
  posture; MCP/REST parity is automatic through the existing loops; the
  closed-set/twin-census test pins bump (the `1500e8f` mechanism).
- **#423 boundary unchanged:** processed values render only in the Analyse
  view and the report; no analysis READ becomes a catalogue operation. The
  marker overlay's write/echo is operator annotation, not a processed-value
  exposure (stated here so the review can check the claim, not the intent).
- **Retention interplay (the `feat/issue285-i3c-defaults` check):** I4b
  touches **no** retention surface — no `retention.py` edit, no
  `_RESERVED_ROOT_DIRS` change (no new root directory), and the sweep never
  sees event dirs (they carry `manifest.json`). `analysis.json` is removed
  with its capture (`library.remove` rmtree) exactly like `metadata.json`;
  the Q13 default-flip branch's surfaces (policy defaults, quota warn) are
  disjoint. Reports pin their sources on every export (already landed), so
  exported marker notes survive capture pruning inside the report bytes.
- **Standards tripwire:** empty by design — no `standards/` bytes, no version
  strings, no provider contracts. Verified at push per the standing rule.
- **Two-repo discipline:** SDK-only; no gateway pointer motion (TWO-1's order
  note: nothing pairs main-side).
- **Operator docs** (Analyse view additions, the report's new blocks) remain
  the named follow-up through the document-writer register (ASD-STE100) —
  not this record's register (carried from I4a).

## 4. Review tier and the Step-1 keyword scan (#254 form)

**Tier per sub-slice (SDK rubric Step 1): Tier 3 both.** Triggering rules:
"changes a refusal prefix or adds a refusal path" — I4b.1 adds the marker and
assertion refusals; I4b.2 adds the pairing/power refusals — and, under the
gateway's form, the persisted-format rule (`analysis.json`). **Maximum tier
across the slices: Tier 3** → two independent adversary lanes per sub-slice
(standing rule for Tier-3).

Step-1 keyword scan (the gateway rubric's eight keywords) over the EXPECTED
diff text of each sub-slice (docs and code alike; estimates from §1, to be
re-derived at review against the real diff — the builder keeps them as
estimates in the PR body if they disagree):

| keyword | I4b.1 | I4b.2 | where |
| --- | --- | --- | --- |
| `threading` | 0 | 0 | — |
| `asyncio` | ≈8 | ≈6 | new/extended `async def` seam op + web routes + tests |
| `subprocess` | 0 | 0 | — |
| `sha256` | ≈12 | ≈8 | this record's AR text, digest-verified reads, sidecar/digest arms, schema key `html_sha256` adjacency |
| `hashlib` | ≈3 | ≈2 | the streaming reducer's hasher, tests |
| `migrate` | 0 | 0 | — |
| `recovery` | 0 | 0 | — |
| `protection` | 0 | 0 | — |

`asyncio` and `sha256` both hit, so the keyword rule alone puts each expected
diff in Tier 3; the SDK path rules agree (refusal-path additions; the
persisted overlay). Both routes: **Tier 3**.

## 5. Measurable proofs — acceptance rules

AR-1, AR-4, AR-5 and AR-6 are I4a's and re-run as regression (the suite does
this anyway). **AR-2 and AR-3 are the parent record's pre-committed rules:
AR-2 stands as written (two precisions pinned); AR-3 stands as written except
one figure, amended with its contradiction cited in §0. AR-7–AR-11 are new and
are written now, before any measurement ran** — that is this record's own
pre-commitment. Fixtures use invented names. Float tolerance: exact for
counts and binary64-exact differences; **≤ 4 ulp** vs the closed form for
computed floats; if more than one fixture needs loosening past 4 ulp, the
computation order is wrong — a KILL, never a tolerance fix.

**AR-2 (I4b.1, edge timing) — CONFIRMED as pre-committed** (1 kHz step
fixtures; `fx-step-rise` riseTime within 1 sample interval of closed form;
`fx-step-settle` settleTime within 1 interval at settle_pct=2; `fx-step-fall`
→ `rising: false` with equal |riseTime|; flat series → `detected: false`;
region of 2 samples → `detected: false`; RED: swap the 15% head/tail
fractions → `fx-step-rise` goes red). **Precisions pinned here (they tighten
the definition, they change no pre-committed arm):**
- the region count is the count of NON-NULL in-window samples (fork
  `regionPoints` semantics) — `fx-step-nullpad` (a rise fixture with nulls in
  both plateaus) still detects and matches the null-free closed form;
- `rise_time` is `null` when either crossing is absent — `fx-step-nocross`
  (a region whose values reach only the 10% level) reports `rise_time: null`,
  never 0;
- `settle_time` is 0 when nothing left the band, and `null` when the region's
  last sample is still outside it — `fx-step-settle-open` reports `null`.
Ship: all arms green. Kill: any arm red.

**AR-7 (I4b.1, min/max assertions) — new, pre-committed.**
- `fx-assert-pass` (min/max both satisfied) → `pass`;
- `fx-assert-low` (`actual_min < min`) → `fail` with `below_min` named;
- `fx-assert-high` → `fail` with `above_max` named; `fx-assert-both` fails with
  both reasons when both bounds break;
- `fx-assert-min-only` / `fx-assert-max-only` → the absent bound is never
  consulted (pass/fail follows the single bound);
- **`fx-assert-empty` (window containing no samples) → `not_evaluated`, and
  the pass count does NOT include it** — the honesty crux;
- an assertion naming a capture outside the request set → `invalid_request`
  with an EMPTY result set afterwards; a non-finite bound → `invalid_request`.
RED controls: neutralise the subset check → the out-of-set arm goes red;
flip the empty-window arm to `pass` when `count == 0` → `fx-assert-empty` goes
red. Ship: all green. Kill: any red.

**AR-8 (I4b.1, the markers overlay) — new, pre-committed.**
- save → reload round-trip through `capture_analysis` preserves
  `{label, t, note}` rows and stores them sorted by label;
- replace-on-duplicate: saving label `A` twice stores ONE row with the second
  `t` (the fork's `placeMarker` semantics);
- refusals: label `AA`/`a`/empty → `standalone_report_marker_invalid`;
  non-finite `t`; `t` outside `[0, (sample_count − 1) × interval]`;
  a request carrying both `notes`/`tags` and `markers` → `invalid_request`;
- absent/invalid `analysis.json` reads as no markers (honest default, never
  an error); after `capture_delete`, no `analysis.json` survives (no orphan);
- the rewrite leaves no `.tmp` behind and the target is valid JSON after
  every write (the atomic-rewrite shape, mirroring the metadata precedent).
RED controls: drop the label regex → the `AA` arm goes red; write rows in
arrival order → the sorted-order arm goes red. Ship: all green. Kill: any red.

**AR-9 (I4b.1, report blocks + the zoom/context pair) — new, pre-committed.**
On ≥3 input sets (single capture; 2-capture set; a windowed export):
- (a) markers: every in-window marker renders as a labelled glyph on the
  charts and a notes row; a fixture note containing `<script>` and `{{`
  renders escaped (AR-4e extended); out-of-window markers appear in the notes
  list but not on a chart they cannot reach;
- (b) edge and assertion blocks carry `benchweave-edge/1` /
  `benchweave-assert/1`, `host-computed`, and their denominators (SRF-4);
- (c) the zoom section renders **iff** the window is a proper subset of the
  sources' extent — a full-extent export renders one chart, never two equal
  charts;
- (d) both charts are structurally complete (axes with units, legend
  distinguishing by line form as well as colour, time basis, textual
  description — SRF-1's structural arms);
- (e) `decimated_extent(source, columns)` equals
  `decimate_minmax(list(series_samples(source)), columns)` point-for-point on
  `fx-alt` and `fx-spike` (tie-break parity — the spike's single point stays);
- (f) clock-free re-export with markers and assertions in the params is
  byte-identical (AR-4d extended).
RED controls: remove the context chart's window shade → (a) or (d) goes red;
render the zoom section unconditionally → (c) goes red; flip the streaming
reducer's tie-breaks → (e) goes red. Ship: a–f green. Kill: any red.

**AR-3 (I4b.2, power pairing and honest nulls) — CONFIRMED except one figure,
AMENDED** as §0 documents:
- pairing-by-unit arm stands (names swapped against units → pairing still
  succeeds; names are ignored);
- `fx-pair-const` (V = 2, I = 3, 100 Hz, N = 360, t = 0 … 3.59 s) → mean power
  6 W, peak 6 W, and **energy = 6 × (N − 1) × interval / 3600 Wh =
  0.0059833… Wh (≤ 4 ulp vs `6.0 * (360 - 1) * 0.01 / 3600.0`)** — the
  parent's `0.006 Wh` figure is withdrawn for the reason in §0 (the fork's
  own trapezoid spans (N−1) intervals over the landed time base);
- the one-null arm stands unchanged: the sample is excluded (count 359,
  null_count 1), mean power still 6 W (the fork's coercion would report
  ≈5.983 W — the arm still discriminates);
- the no-current arm stands: two V series and no A series → power rows ABSENT
  with `power_unavailable: no current series`, never 0 W.
Ship/Kill as amended. RED controls as pre-committed.

**AR-10 (I4b.2, pairing honesty and gap integrals) — new, pre-committed.**
- `fx-pair-const-null` (AR-3's one-null fixture): the energy integral drops
  the two segments touching the null and reports `integrated_span_s = 3.57`
  (357 counted segments × 0.01 s), `dropped_segments = 2`, energy
  = `6 × 3.57 / 3600 Wh` = 0.00595 Wh (≤ 4 ulp) — the gap is visible in the
  row, never interpolated across;
- a current-only set → `Ah` present (trapezoid of I), `wh: null`, reason
  `power_unavailable: no voltage series`;
- unit vocabulary: `µA`/`mA` classify current, `mV` classifies voltage, `W`
  classifies `other` (unpairable) — `fx-units` shows the classification;
- deterministic default pairing follows request order (shuffling the request
  order changes which sources pair — and the resolved pairing is recorded in
  the sidecar, so the report names what it used);
- the fork's `t1 − t0 || 1` zero-span substitution is absent by construction:
  `fx-dup-t` (impossible on the landed uniform time base — the loader's
  interval is per-capture constant) is not needed; the claim is the
  structural one, stated as *is refused unless* (non-positive/non-finite
  intervals already refuse at load, `analysis.py:155–168`).
RED controls: restore null→0 in the power point rule → the
`integrated_span_s` arm goes red; pair by capture-id sort instead of request
order → the ordering arm goes red. Ship: all green. Kill: any red.

**AR-11 (I4b.2, the four mode blocks) — new, pre-committed.**
- `battery`: `capacity_ah = 2`, mean I = 0.5 A over the window →
  `runtime_h = 4` (≤ 4 ulp) with denominators (capacity, mean, window);
  no `capacity_ah` → no runtime row (never a default capacity);
- `dc-dc`: `fx-dcdc` (known in/out powers) → η = `pout/pin × 100` within
  4 ulp; a fixture with `|pin| ≤ 1e-9` → η absent (never inf or 0);
- `sleep`: `fx-sleep` (known threshold, known duty) → duty % and class means
  match closed form; **no threshold → `not_evaluated: no threshold`** (the
  fork's midpoint default is not carried — this arm is the A02 posture);
  an empty class reports its count and an absent mean (never 0 A);
- `load-step`: `fx-loadstep` (known ΔV/ΔI) → `R = −ΔV/ΔI` (≤ 4 ulp);
  `|ΔI| ≤ 1e-9` → `R` absent.
RED controls: restore the midpoint threshold default → the no-threshold arm
goes red; coerce an empty class mean to 0 → the empty-class arm goes red.
Ship: all green. Kill: any red.

**AR-6 (genericity — carried to both sub-slices).** The extended
`analysis.py`/`report.py` contain zero tokens naming any adapter or plugin (a
census over the module text) and import nothing from any plugin package; the
same code renders over single-series and 2-capture different-unit sets.
**Underpowered clause stands as written in the parent record:** the exit
gate's "second (non-ADC) adapter runs unmodified" is owner/bench evidence and
is INCONCLUSIVE from these arms alone — disclosed at the gate, never claimed.

**Kill-direction summary.** Ship I4b.1 = AR-2, AR-7, AR-8, AR-9 green (each
RED control shown to fail without its mechanism) with AR-6's census green;
Ship I4b.2 = AR-3 (amended), AR-10, AR-11 green likewise. **Kill** = any arm
red at the fold. **Underpowered/mismeasured** = (i) more than one fixture
needing >4 ulp (computation-order kill); (ii) AR-6's second-adapter clause
inconclusive (disclosed); (iii) if the click-to-place interaction spike fails
against the closed wrapper and the numeric marker path ships alone, the UX
gap is disclosed at the gate (the data path is complete either way).

## 6. Fork behaviours not carried (honest negatives, each with its reason)

1. **null→0 coercion** in `powerPoints`/`powerRegionStats` (app.js
   l.1425–1426, 1477–1478) — evidence-exactness defect (the parent's kill);
   replaced by exclusion-and-count with gap-visible integrals (AR-10).
2. **Duplicated JS/Python computation** (the fork computes every number
   twice) — the parent's single-computation rule; I4b keeps one pure module.
3. **Name-based rail role guessing** (`pickBy`/`guessRailPairs` regexes,
   l.1584–1589, 1615–1617) — Q8 ruled 2: pairing keys on unit/quantity,
   never names; roles come from operator selection over request order.
4. **Rails persisted by series name** (`savePowerState` l.1735–1737) — ours
   key on `capture_id` (the landed identity).
5. **Sleep threshold midpoint default** (l.1962) — A02: a missing requirement
   blocks the computation (`not_evaluated`), it never defaults.
6. **Empty-class mean coerced to 0** (l.1973–1974) — honest absence instead.
7. **The three-region model** (brush / power / zoom regions) — one region
   (the window) for every family; the report's context+zoom pair preserves
   the two-scale reading without parallel live state.
8. **`trapezoid`'s `t1 − t0 || 1` fallback** (l.1442) — silent unit
   substitution; the interval is known and validated at load.
9. **Assertion spec keyed by channel name** (l.39) — ours key on
   `capture_id`; an unknown target refuses rather than rendering
   `found: false` forever.
10. **The live second zoom chart** (`analyseZoomChart`) — superseded by the
    landed drag-zoom; the report keeps the second chart (AR-9c).

## 7. Maintainer forks

**None open.** The parent record's F-A (Q8) is ruled (option 2, plugin-side
profiles with the #423 sunset — PRD §8 amended 2026-10-07; this design's
pairing rests on the ruling and reads it as "never names"); F-B (#423) is
raised and this slice obeys its boundary; F-C is adopted (row 23 under the
same disclosed-delta posture as row 22); F-D is adopted (capture-set
composition). The two judgment calls this lane took are recorded as design
decisions, not forks: the zoom reinterpretation (§1.5) and the split cut line
(§1) — each names its reopen trigger.

## 8. Top risks (each with its falsifier)

1. **The AR-3 figure amendment reads as post-hoc tuning.** It is not — the
   wrong figure was found by re-deriving the pre-commit against the fork's own
   code and the landed time base before any fixture ran, and the amendment is
   cited (§0). Falsifier: a builder's measurement that `6 × 3.59 / 3600` is
   not what the specified trapezoid returns (that would mean this record
   misread the fork); mitigated by AR-3's ≤4 ulp arm against the closed form
   named in the rule.
2. **Click-to-place against the closed wrapper.** The wrapper is closed
   (`plots.py` header: no plugin-supplied plot options); the brush already
   reaches the uPlot instance (`host._bwPlot`). Falsifier: the interaction
   spike cannot read a click's `t` through the existing surface; mitigation:
   the numeric marker fields are the complete no-script path (disclosed UX
   gap per §5's underpowered clause).
3. **The streaming reducer drifts from `decimate_minmax`.** Two reductions of
   one rule can diverge silently. Falsifier: AR-9e reddening; mitigation: that
   arm is point-for-point parity on the spike and alternating fixtures, and
   the tie-break rules are copied with their line cites.
4. **Marker `t` bounds reject legitimate annotations.** A marker "just after
   the last sample" is refused by `[0, (N−1)×interval]`. Falsifier: an
   operator complaint; mitigation: the bound is the displayable time base
   (the fork placed markers only at plotted times), and widening it later is
   additive.
5. **The context chart's cost on 10M-sample captures.** One streaming pass at
   O(columns) memory is the design; Falsifier: a throwaway spike measuring
   > ~5 s wall-clock (spike is a one-off harness, never CI — the standing
   rule); mitigation: the pass is the same chunk discipline `scan_series`
   already runs per export.
6. **`analysis.json` vs future "analysis settings".** The overlay is named
   `format: standalone-analysis/1` with a `markers` key; assertions/settle/
   power settings are deferred. Falsifier: a successor slice needing
   persisted settings that the format cannot grow into; mitigation: the
   format is ours (one file, additive keys), and the fork's per-capture power
   persistence (app.js l.1732–1748) is the named follow-up shape.
7. **Row 23 churns the census pins again.** Falsifier: a red closed-set or
   twin-census lane at the fold; mitigation: the `1500e8f` pin-bump mechanism
   rides the branch (already priced in §3).

## 9. Placement and branch

- Record: `benchweave-sdk/.claude/deep-review/2026-10-08-issue286-i4b-analysis-extensions-design.md`
  (the parent record's placement precedent).
- Slice branch: **`feat/issue286-i4b-analysis-extensions`** created from
  `origin/main` (`24c76fb`) in the SDK repo; this record is commit 1. I4b.2
  (power) builds as the immediate successor branch
  (`feat/issue286-i4b2-power-modes`) carrying a pointer note to this record's
  §1.4/§5 AR-3/AR-10/AR-11 — or as a second commit series on this branch if
  the maintainer prefers one PR (§1's cut line is a review-size call).
- The builder re-derives §4's keyword counts against the real diff at review
  and keeps them as estimates in the PR body if they disagree with the table.
