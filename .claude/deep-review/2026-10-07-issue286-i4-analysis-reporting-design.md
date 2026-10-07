# Issue #286 — Standalone Web UI I4: analysis and reporting — design record

Date: 2026-10-07. Status: DESIGN (no code written). Repo: `benchweave-sdk`
(expected branch `feat/issue286-i4a-analysis-report`, created from `origin/main`).
Tracking: gateway issue #286 (single issue stream); PRD 11
(`docs/implementation-planning/11-standalone-web-ui-prd.md`, Draft v0.3, amended
2026-10-03) is the requirements authority. This record covers slice I4a (the
minimal first increment) and pre-commits the acceptance rules for I4b (the named
deferral), so neither slice tunes a rule after seeing numbers.

Design lane note: this record is the builder's commit 1 on the slice branch (I3's
precedent, `2026-10-04-issue285-i3-hardware-capture-design.md`). If the builder
finds the file already present in the checkout, it commits it verbatim; if it
finds only this text in the lane transcript, it writes these bytes first. Disclosed,
not silent.

Triage note (per this directory's README): this record is deliberately public —
it names no person, client, bench, device serial, commercial term or machine
specific. The one external repository it touches is cited once as the public
provenance PRD §5 already carries in the gateway tree; fixtures use invented
names (`fx-*`, `ref-adapter-b`). Honest negatives (the killed fork behaviours in
§0/§1) are first-class and stay public.

## 0. Verification of premises (done before designing)

- **PRD 11 read in full.** I4 is the terminal slice: "Analysis and reporting:
  fork Analyse features made generic, HTML report", requirements **SW-52–53**,
  exit gate "Fork's `app.js` deleted; second (non-ADC) adapter runs unmodified;
  Q8 ruled" (PRD §9). Issue #286's body agrees. SW-52 = "brush statistics (min,
  mean, max, RMS, peak-to-peak), edge timing (10–90%, settling), power modes with
  V/I pairing by descriptor quantity, A–Z markers with notes, zoom region,
  min/max assertions". SW-53 = "HTML report export: self-contained, inline SVG,
  same tokens, capture manifest digest printed on the report".
- **Premise correction (the dispatch named the wrong home).** The dispatch asked
  for "the gateway's Analyse capability that I4 forks generic — find it under
  `src/benchweave/`". There is no analyse capability in the gateway tree: a
  gortex text search for `analyse` scoped to `BenchWeave/src` returns **0 hits**,
  and the gateway CLI surface (`src/benchweave/cli/commands.py`, `evidence.py`,
  `report.py`, `retention.py`, `dispose.py`, `demo.py`, `atrest.py`) carries no
  analysis command. The features I4 makes generic are the **fork's Analyse tab**
  (PRD §5 row "Analyse tab … **Take, phase 2** … Generic over any numeric capture
  dataset"), which is where SW-52's feature list comes from. The fork (PRD §5's
  public provenance citation; read over the GitHub API on 2026-10-07 as I3's
  record did) implements it in two places:
  - `src/benchweave/web/static/app.js` (2,391 lines) — the Analyse tab state and
    maths: `regionStats` (l.1450: count/min/max/mean=sum/count/rms=sqrt(sumSq
    /count)/pp=max−min, nulls skipped), `edgeAnalysis` (l.2111: baseline/final =
    means of the first/last 15% of the region; flat guard `|step| < 0.005 ×
    max(|baseline|,|final|,1e-12)` → no transition; t10/t90 crossings of
    baseline+0.10/0.90·step; `riseTime = t90 − t10`; settle band = `settlePct`%
    of |step| around final; `settleTime` from t10 to the first sample after the
    last excursion), `powerPoints`/`trapezoid`/`powerRegionStats`/`integrateRegion`
    (l.1420–1506: per-sample V×I, trapezoidal integration with partial-span
    clipping, Ah/Wh), `powerMode` ∈ {battery, dc-dc, sleep, load-step} with
    `guessRailPairs`/`railStats` pairing by `unitKind` (l.37, 1543–1693),
    `analyseMarkers` = A–Z {label, t, note} with load/save annotations (l.25,
    1319–1375), `assertionSpec` per-channel min/max checks (l.39), zoom region
    chart (l.21, 198–258), and `generateReport()` (l.1376).
  - `src/benchweave/web/report.py` (860 lines) — the self-contained HTML report:
    `build_report(data, markers, lo, hi, power, assertions, zoom) -> str`
    (l.178), inline SVG (`_render_svg`, l.329, 900×420 dual-axis, `role="img"`
    aria-label), region shading + stats table (`_STAT_COLS` = Min/Mean/Max/RMS
    /Pk-Pk), zoom block, notes block. **`report.py` re-implements
    `_region_stats`/`_trapezoid`/`_power_points`/`_power_region_stats` in Python
    (l.65–148) — the fork computes every number twice (browser JS + server
    Python) and the two copies can drift.** I4's single-computation rule (§1)
    exists because of this.
  Two behaviours of the fork are **not carried** (killed on read): the null→0
  coercion in `powerPoints`/`powerRegionStats` (a missing sample silently
  becomes 0 W — an evidence-exactness defect), and the duplicated computation.
- **Landing state (builder-verified 2026-10-07; corrects the design lane's
  stale bullet — that lane read a checkout 43 commits behind).** SDK
  `origin/main` = `8b9f1a0` with **I3c MERGED** (PR #132, issue #285):
  `src/benchweave_sdk_server/retention.py`, the `GET /captures` library page
  over `capture_list`, and the pin/unpin/delete routes are LANDED — the
  capture picker (§1.4) builds on the landed `capture_list` route exactly as
  the captures page consumes it (`web.py::captures_page`). I3d (fork
  migration) is contributor-ruled (parkview self-migrates) and does NOT gate
  this slice: the exit gate's fork-side evidence rows ride I3d's own record
  either way. The design-lane premise this replaces: I3c/I3d "in flight",
  `retention.py` absent — true at `6fbc07e`, false at the build base.
- **The capture shape the analysis reads (the one structural finding).** The
  landed format is **single-stream**:
  - `capture.py::_waveform_fields` (l.214): `waveform_f64le` finalise metadata =
    `sample_count` (int ≥ 1), `sample_interval_s` (positive finite), `unit`
    (non-empty string) — one unit per capture.
  - `capture.py::StandaloneCaptureWriter.artifact_finalise` (l.358): manifest =
    `{capture_id, format, artifact_id: "art-<sha256>", byte_length, sha256,
    started_at}` + the waveform fields, with `byte_length == sample_count × 8`
    enforced against the real bytes; optional `x-standalone-renderings`.
  - `seam.py::StandaloneSeam._op_capture_series` (l.1949): serves that one
    stream, decimated by default through `plots.decimate_minmax` (max_points
    2,000; raw serving refused above `_RAW_SAMPLE_CEILING`); non-waveform
    formats are refused to `artifact_read`.
  - No channel concept exists anywhere in the standalone server (token census:
    `\bchannel\b` = 0 hits in `benchweave_sdk_server`). SW-54 metadata
    (`seam.py::_capture_metadata`, l.1561) carries device identity/firmware,
    plugin version, surface, operator, project, tags, notes, start configuration
    — no channel map.
  The fork's Analyse is **multi-series** (CSV columns). SW-52's power modes (V/I
  pairing) therefore cannot be expressed over one capture — §1's capture-set
  composition is the minimal bridge, and fork F-D puts the alternative to the
  owner. Everything else in SW-52/53 works on a single series.
- **Q-items.** Q1 is ruled (2026-10-02, issue #309: the host ships as
  `benchweave-sdk[server]`); Q12 is ruled (2026-10-01, issue #310: uPlot +
  host-side min/max decimation). Q5/Q7/Q13 are I3's forks (F-1..F-3 there).
  **Q8 (measurement profiles) is NOT ruled and the I4 exit gate requires it
  ruled** — see §7 F-A. It does not block this design's mechanism.
- **The gateway rubric (Step 1 + the #254 design-time tier call) and the SDK
  rubric (tier triggers) were read from `main`**; the tier call is §4.

## 1. Mechanism

Two slices. No slice touches `src/benchweave_sdk/` core (`capture.py`,
`interfaces.py` unchanged), `standards/` bytes, version strings, or
`pyproject.toml`/`uv.lock` (no dependency change — PKG-1/PKG-2 hold: the
`[server]` extra's dependency set is untouched; SVG and statistics are stdlib).

### The analysis dataset (the one structural decision)

An analysis request names **1..n published captures**; a loader extracts one
numeric series per capture (`waveform_f64le` primary → points, labelled with the
manifest `unit` + SW-54 metadata). This is the minimal bridge from the landed
single-stream format to the fork's multi-series Analyse — capture-set
composition, no on-disk format change. A future multi-variable capture format
slots in behind the same loader interface (fork F-D). Power-mode pairing keys on
**unit/quantity, never names** (PRD §5: "Power V/I pairing keys on descriptor
quantities (V, A) rather than channel names") — I4b.

### I4a — brush statistics + the HTML report (SW-52's stats family + SW-53)

1. **`src/benchweave_sdk_server/analysis.py`** (new, pure — no I/O beyond the
   published capture root, no plugin imports, no clock):
   - `load_series_set(root, capture_ids)` — chunked reads over published
     primaries (a `struct.unpack_from` chunk loop; never materialises the whole
     series; **never reads decimated points** — statistics over
     `capture_series`'s decimated output would be wrong by construction).
   - `region_stats(points, lo, hi)` and the per-set aggregation, per definition
     **`benchweave-analysis/1`** (printed on every report):
     - window inclusive `[lo, hi]` (the fork's `t < lo || t > hi` skip);
     - `null_count` = samples in window that are null; every statistic excludes
       nulls and the denominator is the non-null count (the fork's skip rule,
       made visible);
     - `count` = non-null samples in window; `min`, `max`, `pp = max − min`
       (exact in binary64); `mean = sum / count` in sample order;
       `rms = sqrt(sumSq / count)` (population RMS over the window's non-null
       samples — the fork's formula).
   Uncertainty/calibration disclosure follows `measurement/derivation.py`'s
   stance (the gateway's derived-variable engine, l. derived variable result):
   host-computed values are labelled with `uncertainty: unknown` semantics — a
   propagated bound would presume operand-error independence nothing here can
   evidence (A02). No analysis value ever carries a fabricated accuracy.
2. **`src/benchweave_sdk_server/report.py`** (new): `build_report(...)` renders
   ONE self-contained HTML document per SW-53:
   - inline `<style>` = the pinned `tokens.css` + `themes.css` bytes (SW-21's
     digest-checked assets served today by `assets.py` — same bytes, inlined so
     the document has no external dependency);
   - **inline SVG, no JS** (SW-53). uPlot cannot appear in a script-free
     document (it is canvas/JS), so the report carries a server-side SVG
     rendering of the same closed plot semantics SW-25 defines: labelled axes
     with units, visible legend with line form as well as colour, stated time
     basis, textual description, and min/max-per-pixel-column decimation via
     `plots.decimate_minmax` (lazy import, the same discipline
     `_op_capture_series` uses — `plots.py` pulls the ui-html extra at module
     level). The live plot stays uPlot (Q12's ruling); the report SVG is
     SW-53's own requirement, not a second live renderer;
   - region shading + per-series statistics table (the fork's `_STAT_COLS`);
   - **every processed-value block carries the `host-computed` label, the
     definition id `benchweave-analysis/1`, and its denominators** (count,
     null_count, window) — PRD §10's interim rule ("SW-53's report export must
     label processed values as host-computed until then") and the claim
     discipline (G4: every number carries its denominator and whose measurement
     it is);
   - every source capture's **manifest sha256 printed** (SW-53), plus plugin
     version + descriptor digest, and the ui-html pin version;
   - a mode line: `STANDALONE — no gateway` (SW-27) and **`SIMULATED` when any
     source capture's metadata records mock transport** (SW-72's banner rule
     generalised to the report — the gateway's `cli/report.py::SIMULATION_MARK`
     is the in-tree precedent for marking simulated reports);
   - **the rendered bytes are clock-free**: `generated_at` lives in the sidecar,
     so re-export of identical inputs is byte-identical (AR-4d — a report is
     re-derivable from its sources + params, the replay rule M15 applies to
     documents);
   - every interpolated string (operator, notes, device identity, unit, labels)
     is HTML-escaped; Jinja optional slots are guarded or carry absence arms
     (the None-slot class).
3. **Seam + catalogue**: one new row **`report_export`** — the only state change
   in I4a. It renders the document, writes `reports/rep-<sha256[:16]>.html` plus
   `reports/rep-<sha256[:16]>.json` (sidecar: source capture ids, their manifest
   digests, the params, the pinned asset versions, `generated_at`, and the
   report file's own sha256) under the capture root, and **pins every source
   capture** (SW-56: "Exporting a report pins its source captures"). REST and
   MCP follow structurally from the existing catalogue → route/tool machinery
   (`catalogue.py` `_spec` rows + `mcp.py`'s registration loop and
   `_tool_handlers` drift check — I2/I3b precedent). Wire failures use SW-11's
   codes (`not_found`, `invalid_request`, `payload_too_large`, `unavailable`);
   message prefixes follow the landed `standalone_*` refusal family (I3 record
   §3 posture); this record's names (`standalone_report_*`) are provisional —
   **the naming family I3b/I3c actually landed wins** at build time. The report
   id is content-addressed over the rendered bytes, so identical inputs produce
   one report, not duplicates.
   **Analysis reads are NOT catalogue rows in this slice** (§7 F-B): the Analyse
   view computes through `analysis.py` and the report embeds the same numbers
   from the same function; no processed value is exposed over REST/MCP as a
   measurement until the PRD §10 issue-4 question is answered.
4. **Web (`web.py` + `templates/`)**: the Analyse view — capture picker over
   I3c's landed captures list; the plot through the shared `benchweave-ui-html`
   wrapper; region interaction = a drag-brush in a small page-scoped static
   `analyse.js` (under the Q6 host-script budget) that POSTs the selection
   (`hx-post`), with a numeric lo/hi form as the no-JS path (progressive
   enhancement); stats partial swap; export button (CSRF-guarded POST per
   NFR-S3). Download route `GET /reports/{report_id}` served from the capture
   root under the resource-path rules (portable relative paths, no traversal —
   NFR-S9's discipline) with a **report-specific CSP `script-src 'none';
   style-src 'unsafe-inline'`** — scripts cannot run in a report document
   (stronger than NFR-S5's host CSP; the inline style the inlined tokens need
   is the one allowance).
5. **Tests** in `tests/server/` (`test_analysis.py`, `test_report.py`):
   the AR arms in §5 plus a per-refusal-path test for every new refusal
   (NFR-Q4).

### I4b — the rest of SW-52 (named deferral; acceptance rules pre-committed in §5)

- **Edge timing** (AR-2): 10–90% rise/fall and settling, per the fork's
  `edgeAnalysis` definition generalised: baseline/final = means of the first/
  last 15% of the region (min 1 sample); flat guard `|step| < 0.005 ×
  max(|baseline|,|final|,1e-12)` → `not_detected` (an honest negative, never a
  zero rise); t10/t90 = crossings of baseline + 0.10/0.90·step in the step
  direction; `riseTime = t90 − t10`; settle band = `settle_pct`% of |step|
  around final; `settleTime` = from t10 to the first sample after the last
  excursion outside the band. Region with < 3 samples → `not_detected`.
- **Power modes** (AR-3): V/I pairing by unit/quantity across the series set;
  per-sample power V×I; trapezoidal Ah/Wh integrals with partial-span clipping
  (the fork's `trapezoid`); the fork's four named modes (battery / dc-dc /
  sleep / load-step) as named rail pairings over generic series selection. Null
  samples are excluded and counted — the fork's null→0 coercion is not carried.
- **Min/max assertions**: per-series checks with `pass` / `fail` /
  `not_evaluated` (empty window is `not_evaluated`, never `pass`).
- **A–Z markers with notes**: request-carried at first (the export request takes
  marker rows), then persisted per capture in a new `analysis.json` sidecar in
  the event directory with the library index caching it (I3b's metadata.json
  atomic-rewrite precedent for overlays; the root stays the copy of record —
  SW-50's "never the only copy of anything"), plus click-to-place on the plot.
- **Zoom-region second chart** (the fork's report zoom block).

Also deferred, with triggers: **report retention rules** (reports are not
captures; capture retention does not govern `reports/` — reports pin their
sources so the evidence chain survives; reopen on the first operator complaint
or a disk-growth signal); **REST/MCP analysis reads** (gated on the PRD §10
issue-4 ruling — F-B); **a CLI report command** (the UI + MCP tool are the v1
surfaces; reopen if an operator asks for scripted exports); **the exit gate's
fork-side evidence** — the fork's `app.js` deletion rides I3d's migration PR
(I3d's record already holds that row), and the "second (non-ADC) adapter runs
unmodified" run is owner/bench evidence (AR-6's underpowered clause).

## 2. Precedent (proven in-tree mechanisms extended)

1. The fork's `web/report.py` — the self-contained HTML + inline SVG report
   shape, generalised off the ADC and moved to the **single** computation (the
   fork's duplicate JS/Python maths is the defect this avoids).
2. The fork's `static/app.js` Analyse tab — the feature inventory and the
   formula definitions (§0), so fork migrators see the same numbers.
3. `plots.decimate_minmax` (`plots.py`, Q12/#310's ruling) — the report SVG's
   decimation, the same min/max-per-column rule as the live plot.
4. The ui-html `tokens.css`/`themes.css` assets + `assets.py` digest-checked
   serving (SW-21) — inlined into the report (byte-identical styling).
5. The catalogue → REST/MCP pinning machinery (`catalogue.py`, `mcp.py`'s
   `_tool_handlers` drift check — I2/I3b) — `report_export` joins structurally.
6. `StandaloneCaptureWriter` published primaries + manifests (`capture.py`) —
   read-only for analysis; core untouched.
7. `library.py`'s rebuild-from-root index (I3b) — the report sidecar and the
   I4b `analysis.json` overlay follow the "root is the copy of record" rule.
8. The gateway's `cli/report.py::SIMULATION_MARK` — marking simulated reports.
9. The seam's `_fail(code, message, correlation)` + the STD-4 message-prefix
   posture (NFR-Q4) — the new refusal family joins it.
10. `measurement/derivation.py`'s disclosure stance — derived values carry
    `uncertainty: unknown` rather than a fabricated bound (A02); analysis values
    follow it.

## 3. Invariants and cross-surface impacts

- **SDK invariants**: STD-1..3 untouched (no vendored bytes move); **STD-4
  posture extended** with the `standalone_report_*`/`standalone_analysis_*`
  refusal family (Tier-3 trigger); PKG-1/2/3 hold (no dependency, no wheel
  target change); SRF-1..3 — the report becomes the **third** rendering of the
  plot semantics (React preview, HTMX live, report SVG); it implements the same
  closed rules and is pinned by structural arms (axes+units, legend, textual
  description present), not pixel parity (Q2's option-1 posture); TWO-1
  untouched.
- **New invariant row** (SDK `docs/internal/invariants.md`, one row; the
  maintainer assigns the ID at landing): *a processed value is never rendered
  without its definition id, its denominators (count, null_count, window) and
  the host-computed label* — pinned by AR-4(c). This is the evidence-exactness
  crux of a reporting slice: without it, a report number means whatever the
  reader assumes.
- **On-disk formats**: `reports/*.html` + `reports/*.json` (new persisted
  surface — Tier 3); `analysis.json` (I4b — Tier 3). Both are derivable: the
  report is a pure function of (source bytes + params + pinned asset versions)
  and re-export reproduces it byte-identically (AR-4d).
- **PRD §10 issue-4 trigger**: the report is the first surface that records
  processed values "in a … report" — the PRD's own trigger wording. The PRD's
  sanctioned interim is the host-computed label (implemented). The drafted
  upstream issue 4 (temporal processing and operator-defined math) should be
  raised on this increment's evidence — owner motion (F-B). Analysis reads stay
  off REST/MCP in slice 1 so no processed value is exposed there as a
  measurement.
- **Standards tripwire**: empty by design — no `standards/` bytes, no vendored
  edits, no version strings, no provider contracts authored. Verified at push
  per the standing rule.
- **SDK obligations** (`docs/internal/drift-and-obligations.md`): #6 behavioural
  tests land in `tests/server/`; #8 landing order (SDK commits push before any
  gateway pointer motion — the pointer is not this train's diff); #1 and #4 do
  not fire in I4a (no CLI or packaging change). Operator docs (user-guide
  sections for the Analyse view and the report) are a **named follow-up through
  the document-writer register (ASD-STE100)**, not this record's register.
- **Gateway surfaces**: none move in-tree. PRD 11 gains the Q8 ruling and an I4
  status note when the exit gate closes (owner PR, gateway side).

## 4. Review tier and the Step-1 keyword scan (#254 form)

Tier per slice (SDK rubric Step 1): **I4a Tier 3** — adds a refusal path (the
report family; the SDK rule "changes a refusal prefix or adds a refusal path")
and a new persisted format (`reports/`; the gateway form's persisted-format
rule). **I4b Tier 3** — adds refusal paths and a new persisted overlay
(`analysis.json`). Maximum tier across slices: **Tier 3** → two independent
adversary lanes per slice (standing rule for Tier-3).

Step-1 keyword scan (the gateway rubric's eight keywords) over the EXPECTED diff
text of I4a+I4b (docs and code alike; estimates from §1, to be re-derived at
review against the real diff):

| keyword | count | where |
| --- | --- | --- |
| `threading` | 0 | — |
| `asyncio` | ~8 | `report_export` op handler, web routes, tests |
| `subprocess` | 0 | — |
| `sha256` | ~10 | printed manifest digests, report sidecar digest, content-addressed report ids, AR arms |
| `hashlib` | ~3 | sidecar digest computation, tests |
| `migrate` | 0 | — |
| `recovery` | 0 | — |
| `protection` | 0 | — |

Under the gateway keyword rule any hit takes the deep lane — `asyncio` and
`sha256` both hit, so the keyword rule alone puts the whole expected diff in
Tier 3. Under the SDK's path rules the trigger is the refusal-path addition (and
the persisted format under the gateway form). Both routes agree: **Tier 3**.

## 5. Measurable proofs — pre-committed acceptance rules

Written before any measurement ran. All fixtures use invented names. These are
deterministic computations: "sample size" = fixture count × N (no stochastic
sampling; no power calculation applies). Float tolerance: **exact** for
count/min/max/pp; **≤ 4 ulp** vs the closed form for mean/rms (binary64). If
MORE THAN ONE fixture needs loosening past 4 ulp, the computation order is
wrong — that is a KILL, never a tolerance fix.

**AR-1 (I4a, statistics exactness over the full series).** Fixtures:
- `fx-const-zero` N=1,000 → min=max=mean=0, rms=0, pp=0;
- `fx-const-neg` N=1,000, value −3.5 → mean=−3.5, rms=3.5 (≤4 ulp), pp=0;
- `fx-twolevel` N=1,000 (500×0 + 500×2) → mean=1 exact, rms=√2 (≤4 ulp), pp=2;
- `fx-ramp` N=1,000 (0..999) → min=0, max=999, mean=499.5, pp=999;
- `fx-alt` N=10,000 (alternating 0/1) → mean=0.5, rms=0.5 (≤4 ulp), pp=1;
- `fx-nulls` N=1,000 with 100 nulls at known positions → count=900,
  null_count=100, remaining statistics over the known 900 with closed form;
- `fx-window` with known values inside and outside `[lo, hi]` → statistics over
  exactly the in-window subset (inclusive bounds);
- `fx-spike` N=10,000 (9,999 zeros + one 10) → count=10,000, mean=0.001.
RED control: neutralise the loader to consume decimated points
(`capture_series`'s default) → `fx-alt`/`fx-spike` count and mean arms go RED
(the arm can fail; a decimated-stats implementation is caught by count alone).
Ship: all eight green. Kill: any arm red.

**AR-2 (I4b, edge timing definition).** Step fixtures at 1 kHz
(`sample_interval_s` 1e-3), N=1,000: `fx-step-rise` (linear ramp between the
15% head/tail plateaus with computable t10/t90) → `riseTime` within 1 sample
interval of closed form; `fx-step-settle` (single excursion of known duration
above the 2% band) → `settleTime` within 1 interval (settle_pct=2);
`fx-step-fall` → `rising: false` with equal |riseTime|; a flat series →
`not_detected`; a region of 2 samples → `not_detected`. RED control: swap the
15% head/tail fractions in the implementation → the `fx-step-rise` arm goes
RED. Ship/Kill as written.

**AR-3 (I4b, power pairing and honest nulls).** A two-capture set whose series
names are deliberately swapped against their units → pairing by unit succeeds
(the names must be ignored); `fx-pair-const` (V=2, I=3 at 100 Hz, T=3.6 s) →
mean power 6 W, peak 6 W, energy 0.006 Wh (≤4 ulp); the same pair with one null
in V → that sample excluded (count 359), null_count=1, mean power still 6 W —
this arm distinguishes the honest rule from the fork's null→0 coercion (which
would report ≈5.983 W); a set with two V series and no A series → power rows
ABSENT with `power_unavailable: no current series`, never 0 W. Ship/Kill as
written.

**AR-4 (I4a, report integrity).** On ≥3 input sets (single capture, 2-capture
set, windowed export):
- (a) self-contained: zero external references (`src=`, `href=`, `url(`,
  `@import`) in the rendered document;
- (b) every printed source manifest sha256 equals the manifest's field AND the
  recomputed primary digest;
- (c) every processed-value block carries the host-computed label +
  `benchweave-analysis/1` + its denominators (count, null_count, window);
- (d) clock-free reproducibility: exporting the same inputs twice yields
  byte-identical HTML and the same report id;
- (e) escaping: fixture metadata (operator, notes, device identity, unit
  strings) containing `<script>` and `{{` renders escaped, with no literal
  `<script>` in the output.
RED controls: hand-edit a source manifest digest after export → (b) red;
remove the label from the template → (c) red; inject a timestamp into the
template → (d) red. Ship: a–e green. Kill: any red.

**AR-5 (I4a, export side effects).** `report_export` over a known set pins every
source (library pinned=true afterwards) and writes exactly one `.html` + one
`.json` sidecar naming source capture ids, their manifest digests, the params
and the report file's sha256; a second export of identical inputs writes nothing
new (content-addressed); an unknown capture id refuses `not_found` with an
EMPTY `reports/` directory afterwards (no orphans). RED control: neutralise the
pin call → the pin arm goes RED. Ship/Kill as written.

**AR-6 (I4a, genericity — the exit gate's code-level half).** The same analysis
and report code renders over (i) a single-series capture and (ii) a 2-capture
different-unit set; `analysis.py` and `report.py` contain zero tokens naming any
adapter or plugin (a census over the module text) and import nothing from any
plugin package. Ship: both green. Kill: any adapter coupling found.
**Underpowered clause:** this proves code-level genericity over datasets; the
exit gate's "second (non-ADC) adapter runs unmodified" additionally requires a
real adapter run. If that run cannot execute in this repo, the gate clause is
**INCONCLUSIVE from this increment's evidence and is disclosed at the gate,
never claimed from AR-6 alone.**

Kill-direction summary: **Ship** I4a = AR-1, AR-4, AR-5, AR-6 all green (each
with its RED control shown to fail without the mechanism). **Kill** = any arm
red at the fold. **Underpowered/mismeasured** = (i) more than one AR-1 fixture
needing >4 ulp (computation-order kill, not a tolerance fix); (ii) AR-6's
second-adapter run absent (gate clause inconclusive + disclosed).

## 6. Top risks (each with its falsifier)

1. **Multi-series input shape (F-D).** If the owner rules that multi-channel
   data must land as one native multi-variable capture, the capture-set API
   reshapes (the loader interface absorbs it; stats/report core unchanged).
   Falsifier: an owner ruling for the format route that invalidates set
   composition.
2. **Issue-4 politics (F-B).** If the owner rules that no surface may record
   processed values until issue 4 is a standard, SW-53 cannot ship as scoped.
   Falsifier: an owner statement to that effect (PRD §10's "label them
   host-computed until then" currently sanctions the interim).
3. **Report bytes coupled to the ui-html pin** — a pin bump changes every
   re-export digest (honest, but churn for anyone diffing reports). Falsifier:
   operator confusion at a pin bump; mitigated by the sidecar's recorded pin
   version.
4. **Large-capture render time** (10M samples in pure Python) — one chunked
   pass for stats + decimation; if a throwaway spike measures > ~5 s the view
   feels dead (spike is a one-off harness, never CI, per the standing rule).
   Falsifier: the spike's wall-clock; mitigation: single-pass computation,
   on-demand generation.
5. **XSS via capture metadata into the report.** Falsifier: any unescaped
   interpolation found by the adversary lanes (the admin-slice XSS class);
   pinned by AR-4(e).
6. **I3c/I3d landing shape** — I4a's picker builds on I3c's captures list as
   landed. Falsifier: I3c's merged shape differing from the I3 record; re-derive
   the view glue at build time.
7. **Brush interaction vs the shared plot wrapper's closed interface** — if
   uPlot's selection API makes clean capture awkward, the numeric region form
   ships alone (UX gap disclosed at the gate). Falsifier: the interaction spike.

## 7. Maintainer forks (decisions this design needs from the owner)

- **F-A (Q8, measurement profiles).** The I4 **exit gate requires Q8 ruled**;
  this design does **not** depend on the ruling — analysis keys on dataset
  unit/quantity, and gain/offset plus computed channels are plugin-side dataset
  content under the PRD's option 2 and absent under option 1. The PRD
  recommends option 2 with a sunset tied to the upstream contract; the ruling is
  the owner's. **The gate cannot close until it lands.**
- **F-B (PRD §10 issue 4).** This increment is the first to record processed
  values in a report (the PRD's trigger wording). The design implements the
  mandated host-computed labels and keeps analysis reads off REST/MCP in slice 1.
  Owner motion: raise the drafted upstream issue 4 (temporal processing and
  operator-defined math) citing this increment. Not resolvable by this design.
- **F-C (SW-10 catalogue delta).** SW-52/53 imply operations beyond SW-10's
  closed 18 (I3b disclosed the same class as its F-2: delete/pin/unpin). I4a
  adds `report_export`. Options: (1) add the row under the same disclosed-delta
  posture — **recommended**, it is the only way MCP parity (the success measure)
  and SW-56's pin side effect both hold; (2) keep export UI-only and drop the
  MCP tool — breaks the success measure.
  **ADOPTED (1)** — owner ruling 2026-10-07 at dispatch: `report_export` is
  catalogue row 22 under the disclosed-delta posture.
- **F-D (multi-series capture shape).** The landed format is single-stream
  (§0). Options: (1) **capture-set composition** — recommended for I4: no
  format change, works against today's writer; (2) a native multi-variable
  capture format — a separate format increment (writer, on-disk shape,
  corpus-adjacent work). Slice 1 is unaffected either way; I4b's power modes
  need one of them.
  **ADOPTED (1)** — owner ruling 2026-10-07 at dispatch: capture-set
  composition; the loader interface is where a native multi-variable format
  would slot in later.

## 8. Placement and branch

- Record: `benchweave-sdk/.claude/deep-review/2026-10-07-issue286-i4-analysis-reporting-design.md`
  (I3's placement precedent: `2026-10-04-issue285-i3-hardware-capture-design.md`).
- Slice branch: **`feat/issue286-i4a-analysis-report`** created from
  `origin/main` in the SDK repo; this record is commit 1 (I3's precedent). The
  builder re-derives §4's keyword counts against the real diff at review and
  keeps them as estimates in the PR body if they disagree with the table.
