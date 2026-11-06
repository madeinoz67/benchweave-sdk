# Design record — gateway issue #589, PR-4: the format path serves what the schema admits

Date: 2026-11-07. Parent authority: `.claude/deep-review/2026-11-06-589-live-bringup-design.md`
rev 7 (FROZEN), §5 (PR-4's section), §0 (the standing generality property), §1 row D5,
and the acceptance points A6/A7. This record pins PR-4's mechanism in the real code; where
it sharpens the parent's parentheticals it says so and why. The defect it closes:
**`raw_binary` is the DEFAULT capture format and every display surface refuses it** — the
SDK's most common path produces a capture the SDK itself will not show.

Triage: PUBLIC. Mechanisms, invariants and measurements only. No device identity, vendor,
bench or plugin-project name appears; fixtures use invented names.

Tooling note: the Gortex graph was unavailable for this checkout (probe returned
"checkout discovery unavailable: indexer: checkout mutation lane is busy … context
deadline exceeded"). All reads were `Read`/`grep`/`sed`. No daemon started, no tracking
changed.

Sources, first-hand: this repository at `f833bc1` (branch `pr7-589-builder` — main at
`75e6b4b`, PR-1 merged, plus PR-7's serial commits, which touch none of PR-4's surfaces)
and at `631db75` (`fix/589-live-bringup-generic`, the frozen record's own base — compared
where line numbers could drift; they do not on these paths). Every `src/`, `tests/` and
vendored-schema citation below was verified against that tree. The vendored standards were
read as bytes (`src/benchweave_sdk/standards/otdp/0.2.4/`), not from memory. **PR-2 is in
flight and PR-3 is adjacent and unbuilt** — this design assumes neither has landed and
names the reconciliation points (§7).

---

## 0. Root cause, verified — and it is one mechanism deeper than the gate

D5 as filed blames the display path. Read in the code, the defect is three layers, and
the third is the one that decides the design:

1. **The write side admits and DEFAULTS to `raw_binary`.** `_FORMATS`
   (`catalogue.py:270`) is `{"enum": ["waveform_f64le", "raw_binary"]}`; `format`
   defaults to `"raw_binary"` in `_CAPTURE_START_INPUT` (`catalogue.py:304`), in the MCP
   tool signature (`mcp.py:99`), and in the seam's own read of the argument
   (`seam.py:1878`). The vendored runtime schema's capture-verb branch admits both
   (`otdp-runtime.schema.json`, `operationRequest` capture `arguments.format` enum), and
   the vendored device-descriptor schema lets a device declare
   `capture_formats: ["raw_binary"]` ALONE (`otdp-device-descriptor.schema.json:181-190`,
   `minItems: 1`, no requirement that `waveform_f64le` be among them) — so a device whose
   only capture format is `raw_binary` is conformant today and display-dead today.
2. **The read side refuses by FORMAT STRING, twice, and hides the rows a third time.**
   `_op_capture_series` (`seam.py:2300-2306`): `if fmt != "waveform_f64le":` →
   `invalid_request` "capture_series serves waveform_f64le primaries; use artifact_read
   …". `_load_one` (`analysis.py:249-254`): same key, prefix
   `standalone_report_format_unsupported:`. Every analysis/report surface funnels through
   `load_series_set` → `_load_one` (`report_export`, `seam.py:2672`; the web Analyse
   view, `analysis_view`, `seam.py:2905`), so one gate refuses all of them. The web
   picker filters the rows out BEFORE any refusal is reachable
   (`web.py:1904-1909`, `row.get("format") == "waveform_f64le"` — "the picker never
   offers a row the analysis would refuse") — so in the UI a `raw_binary` capture is not
   refused, it is INVISIBLE, and the marker editor with it (`marker_capture` is chosen
   from `picker_ids`, `web.py:1910-1913`). The "no trace view" experience is a filter,
   which is the quietest possible failure mode.
3. **The manifest asymmetry is real, and it is not a bug — it is the vendored schema's
   own shape.** `_finalise_capture` writes `sample_count` / `sample_interval_s` / `unit`
   ONLY when `state["format"] == "waveform_f64le"` (`seam.py:3311-3318`). The vendored
   `captureManifest` (`otdp-runtime.schema.json` `$defs.captureManifest`) requires
   `byte_length` for EVERY format and requires the three timing fields only under the
   `waveform_f64le` branch (`allOf`/`if`-`then`, the same conditional shape as the
   SDK-side start schema at `catalogue.py:336-351`). So a `raw_binary` manifest carrying
   no timing is CONFORMANT; the dishonest party is the view that demands timing a byte
   stream does not have.

**The sharpening that changes the design:** removing the format gate alone does not
produce a render — it produces a lie. `capture_series` reads the grid with silent
defaults (`count = int(manifest.get("sample_count", 0))`,
`interval = float(manifest.get("sample_interval_s", 0.0))`, `seam.py:2307-2308`); a
gate-free `raw_binary` capture would serve an EMPTY series (count 0), and `analysis`
would refuse `standalone_report_manifest_incomplete:` (`analysis.py:255-272`) because
`sample_count >= 1` is required of a "waveform manifest". The fix is not "delete the
gate"; it is **derive each format's grid from the fields its own manifest honestly
carries** — for `waveform_f64le` the three declared fields, for `raw_binary` the
universally-required `byte_length` (1 byte per sample, index 0..N-1).

Also verified, for the A7 denominator's honesty: the plugin-side capture WRITER admits a
wider world than the host — `StandaloneCaptureWriter`'s declared format set is
constructor-configurable with `_DEFAULT_FORMATS = {"waveform_f64le", "raw_binary"}` and
`_FORMAT_EXTENSIONS` mapping `csv`/`txt`/`vcd` extensions
(`src/benchweave_sdk/capture.py:151-164`, `:446`). Those extension formats are reachable
only by a plugin embedding the writer directly, never through the host's
`capture_start` (the input enum refuses them), and they refuse at display exactly as
today (`_load_one`'s unknown-format arm). A7's denominator is the HOST's admitted set —
`catalogue._FORMATS` — and the writer's wider reach is named here so nobody mistakes it
for a hidden third format.

## 1. The decision, and what it beat

**Adopted (the parent's §5 ruling, now with the schema evidence that settles its open
question): the views render every format the schema admits; `raw_binary` renders on the
sample-INDEX axis; the manifest does not change.** The question the brief posed — fix the
manifest, or fix the views — is answered BY THE VENDORED SCHEMA, not by preference:
`captureManifest` normatively defines `raw_binary` as the no-timing format (timing
fields required only under the waveform branch) and `byte_length` as the
always-required field. Making `raw_binary` manifests carry timing would mean either
contradicting the vendored corpus from this repository (a STD-5 violation — normative
content never changes here first) or fabricating an interval/unit a byte stream does not
have, which the parent's M12 mutation exists to kill. **The manifest was never the
liar; the views were.** What the manifest-side alternative would have cost: a corpus
motion (main-side, standards-version increment, re-sync) to widen the `captureManifest`
conditional — plus every existing `raw_binary` capture on every bench becoming
retroactively incomplete, plus a fabricated-seconds axis for data that has none.

**`_FORMATS` keeps admitting `raw_binary`** — dropping it was rejected in the parent
record for the default-path reason and gains a second reason here: the vendored
device-descriptor schema admits a `capture_formats: ["raw_binary"]`-only device
(§0.1), so removing the format from the host's enum would strand a conformant device
class. The blast radius of dropping it (every omitted-`format` caller breaking, the
schema enum shrinking below the vendored runtime schema's own capture-verb enum — a
parity inversion where the SDK admits LESS than the corpus) is the compatibility
argument in its final form.

**The index axis is honest, not a fabricated time base.** For a `raw_binary` capture of
N bytes: `sample_count = byte_length`, the grid step is 1 (x = 0, 1, …, N-1 — x is the
0-based sample index, exactly the parent's §5 wording), the y value is the byte
(0-255), and `sample_interval_s`/`unit` are NOT invented. Markers and windows operate
in index units for index-axis sources, validated against `[0, N-1]` exactly as they
validate against `[0, (count-1) * interval]` today (`analysis.py:712,736`). The one
thing PR-4 must guarantee — and M12 exists to enforce — is that no surface ever PRINTS
an index axis as seconds: today the web figure hard-codes `"x_unit": "s"` and
`axes = f"s;{unit}"` (`web.py:220,229`), and the report prints `sample_interval_s` in
its manifest block (`report.py:393`). Both become axis-aware.

## 2. The mechanism

### 2.1 One format registry, the single source (seam S5)

The two format-keyed dicts in `seam.py` (`_BYTES_PER_SAMPLE`, `seam.py:145`;
`_PRIMARY_SUFFIXES`, `seam.py:190`) are the in-tree precedent: format vocabulary as
explicit data. PR-4 replaces them and the enum's independence with ONE registry in
`catalogue.py` — the module whose charter is "the one contract behind REST, HTML and
MCP" and which imports nothing beyond `dataclasses`/`typing` (verified), so it can be
imported by `analysis.py`, `seam.py` and `web.py` with no cycle (`catalogue.py` imports
neither):

```python
@dataclass(frozen=True)
class FormatSpec:
    """One admitted capture format: how its primary decodes and what its
    x axis means (S5). The single source behind the served enum, the
    write-side bound math and the display decoders."""
    format: str
    bytes_per_sample: int
    struct_code: str        # the per-sample unpack code: "d" (f64), "B" (byte)
    suffix: str             # the primary-artifact extension
    axis: str               # "time" | "index" — what x means for this format
    index_y_label: str | None  # the honest y label for index-axis formats;
                               # None for time-axis formats (the unit is the label)

_FORMAT_SPECS: dict[str, FormatSpec] = {
    "waveform_f64le": FormatSpec("waveform_f64le", 8, "d", ".f64", "time", None),
    "raw_binary":     FormatSpec("raw_binary", 1, "B", ".bin", "index", "byte value"),
}

#: The served format vocabulary, DERIVED (single source: the registry).
#: Insertion order is pinned (waveform first) so the served schema bytes
#: are unchanged by the derivation.
_FORMATS = {"enum": list(_FORMAT_SPECS)}
```

`seam.py`'s two dicts are DELETED; their use sites import the registry
(`_BYTES_PER_SAMPLE.get(fmt, 1)` at `seam.py:1879` becomes a spec lookup;
`_PRIMARY_SUFFIXES.get(...)` at `seam.py:2309,2510` becomes `spec.suffix`, with the
`".data"` fallback retained for the unknown-format artifact_read path, which must keep
serving raw bytes of any format — that is its charter). **The write side keeps its
honest conditional:** `_finalise_capture`'s waveform-only timing fields
(`seam.py:3311-3318`) are UNTOUCHED — the manifest asymmetry is the corpus's shape, and
an arm pins it so nobody "fixes" it here.

### 2.2 The loader: per-format grids, one decode method

`analysis.SeriesSource` gains three things: `axis: str` (from the spec; `"time"` or
`"index"`), `unit: str | None` (`None` exactly when `axis == "index"` — enforced by the
loader), and `spec: FormatSpec`. Two small accessors carry the labelling so no renderer
invents it: `x_label` (`"s"` for time, `"sample index"` for index) and `y_label` (the
unit for time formats; the spec's `index_y_label` for index formats). The four chunked
readers (`series_samples`, `scan_series`, `windowed_points`, `decimated_extent`) share
one decode change: `struct.unpack_from(f"<{len(chunk) // 8}d", chunk)` becomes a
`SeriesSource.unpack(chunk)` method wrapping `struct.unpack_from` with the spec's code
(and chunk reads become `_CHUNK_SAMPLES * spec.bytes_per_sample`). For an index-axis
source the loader sets `sample_interval_s = 1.0` — the grid STEP, never a seconds claim;
`x = index * 1.0` is bit-identical to the index, and every renderer's axis LABEL comes
from `x_label`, never from the number.

`_load_one` becomes spec-dispatched:

- **Unknown format** (`_FORMAT_SPECS.get(fmt)` is None): refuses
  `standalone_report_format_unsupported:` as today; the TEXT amends from "analysis
  serves waveform_f64le primaries" to name the admitted set — the prefix and its
  trigger class are unchanged (STD-4 intact; the old text would be a lie after PR-4).
- **`waveform_f64le`**: byte-for-byte today's validation — the three manifest fields,
  the `count * 8` length check, the `.f64` suffix (the spec's).
- **`raw_binary`**: `count = manifest["byte_length"]`, validated as `int >= 1` (a
  published capture cannot be empty — the writer refuses zero-byte finalise — so a
  hand-written 0 is `standalone_report_manifest_incomplete:` naming `byte_length`);
  `unit = None`; `axis = "index"`; the length check becomes
  `actual_length != count * 1` under the same `standalone_report_primary_length:`
  prefix (a contradiction means a hand-edited manifest — `conflict`, as today).

`resolve_markers` derives its grid the same way from the manifest's own `format`:
waveform rows run today's validation verbatim; `raw_binary` rows get
`count = byte_length`, `step = 1`, span `[0, count - 1]`, and `t` validated in index
units — the refusal prefix (`standalone_report_marker_invalid:`) and the duplicate/
label/note disciplines are unchanged; the "declares no usable sample grid" text names
`byte_length` for index formats. Stored overlays of index-format captures therefore
carry index-valued `t`, and re-export revalidates against the same derived grid.

`unit_kind` gains a None guard (`None` → `"other"`): byte planes are neither currents
nor voltages, so a `raw_binary` source can never form a power rail, and a
`raw_binary`-only power request gets the EXISTING honest reason
(`power_unavailable: no current series`, `analysis.py:1469`). No new power behaviour.

### 2.3 The seam and web surfaces

- **`_op_capture_series`** becomes spec-dispatched: unknown format refuses AS TODAY
  (same code, same message, per the parent's "refuses as today"); `raw_binary` reads
  `[: count]` bytes, unpacks `"B"`, and serves `x = index` (the grid step), `y = byte`.
  Decimation unchanged (`decimate_minmax` is format-agnostic). The response shape is
  UNCHANGED — no new wire field; the echoed `format` already lets a consumer pick the
  axis, and the catalogue row's `format` description amends to state the axis meaning
  (an SDK-side schema-description amendment, not a shape change).
- **`_op_capture_start`** gains the write-side mirror: an unknown `format` on a direct
  seam call (the REST/MCP schemas already refuse it; A-F8's settle_pct precedent is the
  discipline) refuses `invalid_request` with the one NEW prefix
  `standalone_capture_format_unknown:` naming the format and the admitted set. Today
  such a call publishes a display-dead capture (`_BYTES_PER_SAMPLE.get(fmt, 1)` silently
  defaults) — the D5 failure class surviving at a narrower door. The host should not
  publish what it cannot render.
- **The web picker** (`web.py:1904-1909`) filters on registry membership instead of the
  hard-coded waveform string — published captures of every ADMITTED format become
  selectable (the "never offers a row the analysis would refuse" discipline is
  preserved: a hand-edited unknown-format capture stays excluded).
- **The web figure** (`_figure_entry`, `web.py:197-235`): `payload`'s `"x_unit"` and
  the `axes` string become `entry["x_label"]`/`entry["y_label"]` — `analysis_view`'s
  in-process entry dict (web-only consumer, not a wire interface) gains those two keys.
  `x_unit: "s"` on an index-axis figure is exactly the M12 fabrication.
- **The report** (`report.py`): the two-distinct-units ceiling counts `y_label`s
  (a V + A + `raw_binary` export = three labels → `standalone_report_units_unsupported:`
  as today's ceiling refuses; a V + `raw_binary` export = two → renders); the caption
  and the manifest block print `y_label`/`x_label`, and `sample_interval_s` prints
  ONLY for time-axis sources (the honest absence `—` otherwise, `format_number`'s own
  convention). The caption carries the format, per the parent's SRF-4 denominators
  discipline.

### 2.4 A7 as a gate, not a hope

Three mechanical properties, one test module
(`tests/server/test_format_path.py`, seam construction lives under `tests/server/`):

1. **Single source with a re-hardcoding guard.** `_FORMATS` is DERIVED from
   `_FORMAT_SPECS`; the test asserts BOTH `list(_FORMATS["enum"]) == list(_FORMAT_SPECS)`
   and the set equality both ways. If anyone replaces the derivation with a literal and
   adds a format to it alone, this reddens (the registry lacks the spec → every
   registry-driven site would refuse the new format at runtime while the schema admits
   it — D5's exact resurrection).
2. **The exhaustion walk.** `@pytest.mark.parametrize("fmt", [*_FORMATS["enum"]])`
   drives, per format, one REAL fixture capture over the existing lifecycle machinery
   (`_patch_descriptor` declares both formats, `tests/server/test_capture_lifecycle.py:72-105`):
   `capture_start` → `capture_stop` → `capture_series` → `analysis_view` →
   `report_export`, asserting success and the honest axis. A format added to the
   registry is automatiically in the walk (the parametrize reads the derived enum) —
   and a registry entry with no live path reddens at admission time. This is what makes
   A7 a gate rather than the one-time sweep the brief forbids: the denominator is
   read from the same single source the renderer dispatches on.
3. **The dataset half is named, conditional on PR-3.** The parent's R5 requires A7's
   walk to cover BOTH source kinds (captures and datasets). PR-3 is adjacent and
   UNBUILT; until it lands there is no dataset-kind series to walk. The walk's
   dataset half therefore rides PR-3's landing as a NAMED reconciliation (§7): PR-3's
   dataset exposure must project its series through this same loader interface or
   refuse honestly — no second renderer (S5's whole point).

## 3. Refusal prefixes (STD-4) and their types

| Prefix | Status in PR-4 | Type and vehicle (unchanged) |
|---|---|---|
| `standalone_report_format_unsupported:` | REUSED — unknown formats only; text names the admitted set | `AnalysisRefusal(ValueError)` in the pure module → `_REPORT_REFUSAL_CODES["invalid_request"]` (already mapped, `seam.py:2531`) |
| `standalone_report_manifest_incomplete:` | REUSED — waveform branch unchanged; `raw_binary` branch fires on an invalid `byte_length` | same as today (`seam.py:2530`) |
| `standalone_report_primary_length:` | REUSED — multiplier from the spec (8 or 1) | same as today (`conflict`, `seam.py:2533`) |
| `standalone_report_marker_invalid:` | REUSED — grid derived per format; text names the format's own grid field | same as today (`seam.py:2538`) |
| `standalone_capture_format_unknown:` | **NEW — the write-side mirror at `_op_capture_start`** | `SeamError("invalid_request", …)` at the operation boundary, the `capture_services_incomplete:` message-carried-pattern; NOT construction/reload, NOT connect — so the parent's `ValueError`-at-construction / `RuntimeError`-at-connect pins are untouched by this slice |
| (the bare series unknown-format refusal) | unchanged as today, per the parent's §5 "refuses as today" | `SeamError("invalid_request")` |

No existing prefix weakens: every reused prefix keeps its trigger class; the only text
amendment is `format_unsupported`'s enumeration of the served set (the old text states
a falsehood after PR-4). The one NEW prefix is disclosed here for the parent §7 STD-4
list's amendment; if review kills the write-side mirror, the disclosed residual is
schema-only validation (REST/MCP refuse; a direct seam call can still publish a
display-refused capture — the incumbent posture, named).

## 4. What the generality gate sees

PR-4 adds `ast.Constant` string literals (`"sample index"`, `"byte value"`,
`standalone_capture_format_unknown:`, spec-field values) and moves none out — the
existing `"raw_binary"`/`"waveform_f64le"` literals reduce by consolidation into the
registry but the floors only rise, never narrow. Per the PR-3 correction's pattern:
`literals_examined`/`files_scanned` are FLOOR pins and move freely;
`allowlisted_entries`/`block_exemptions` stay exact and unchanged — PR-4 widens no
exemption and adds no device- or action-specific literal (format names are corpus
vocabulary, present in the vendored schema's own enum). Nothing device-specific enters
`src/`.

## 5. Minimal first slice

The registry (`catalogue.py`); the spec-dispatched loader, decoder and marker grid
(`analysis.py`); the series/start/artifact-read/asset sites (`seam.py`); the picker and
figure labels (`web.py`); the report's label-aware ceiling/captions (`report.py`);
`tests/server/test_format_path.py` (the A7 gate + the arms below); the amended pins
(`tests/server/test_analysis.py:294`, `tests/server/test_report_export.py:232` — the
raw_binary refusal arms INVERT to serving arms, the unknown-format arms stay); the
docs legs (guide §"Analyse page" `user_guide/plugin-sdk.qmd:869-871` rewritten via the
`document-writer` agent in STE100 register; the guide's capture section gains the
axis-meaning sentences near `:589-605`; `invariants.md` STD-4 + the A7 draft row the
parent §7 names; a drift-obligations row for the format registry: a new format touches
registry + exhaustion fixture + guide axis table together).

**File-touch set and merge order:** `catalogue.py`, `analysis.py`, `seam.py`, `web.py`,
`report.py`, the test modules, the docs. `seam.py` is the serialization point PR-2
holds and PR-3 will; PR-4's seam sites (`_op_capture_series`, `_op_capture_start`,
`_op_artifact_read`, the dict deletions) are disjoint from PR-2's invoke/contract sites
and PR-3's admission sites, and the slice rebases mechanically if the stack order
moves. Stack order stands (PR-3 → PR-4) because PR-3's datasets serve through this
path; **but PR-4 does not depend on PR-3 to build or merge** — every surface above is
capture-kind only, the dataset-kind walk half is the sole PR-3-conditional piece
(§2.4), and if PR-4 lands first its PR body says plainly that the dataset half of A7's
walk arms when PR-3 lands (the test module's dataset parametrize is a named follow-up
commit on PR-3's branch, or PR-3's own arm — the reconciliation either way).

## 6. Deferrals, each with its carrier and reopen trigger

- **The dataset-kind display path** (dataset manifests projected onto series/report):
  PR-3, per its own §3 boundary ("PR-4's unified display path; one path, no second
  renderer"). Reopen trigger: PR-3's merge — its exposure must route through
  `SeriesSource`/the registry or refuse honestly; the A7 walk grows its dataset half
  then.
- **A byte-plane trace presentation richer than the generic index plot** (per-lane
  digital views): the plugin-ui corpus already names the presentation — the
  `digital_lanes` plot kind (`user_guide/plugin-sdk.qmd:258`) — and corpus vocabulary
  moves main-side (STD-5). Carrier: a plugin-ui corpus row; reopen when it lands. The
  generic index-axis figure ships now and is the honest minimum.
- **The writer's extension formats (`.csv`/`.txt`/`.vcd`) as host-admitted display
  formats**: carrier is a CORPUS motion widening `captureManifest`'s enum (main-side,
  standards-version increment, re-sync); when it lands, the registry grows an entry and
  A7's walk forces its live path — the gate is already built for exactly that day.
- **Prefixing the series unknown-format refusal**: kept bare per the parent's "as
  today". Reopen trigger: a CI need to branch on it.
- **`capture_series`'s count-0 silent-empty posture** (incumbent for waveform too): not
  PR-4's motion; reopen if a hand-written-manifest fixture ever makes it bite.

## 7. PR-2/PR-3 reconciliation points

1. PR-2's invoke machinery adds seam surface near PR-4's sites; no shared lines are
   known (its sites are `_op_invoke`/contracts; PR-4's are `_op_capture_series`/
   `_op_capture_start`/`_op_artifact_read`). If PR-2's in-flight tree moved a cited
   line, the builder re-locates by symbol — semantics, not line numbers, carry.
2. PR-3's `capture_list` gains an optional `datasets` array (its record §3); PR-4's
   picker reads `captures` only and is blind to it by construction.
3. PR-3's dataset series (when it lands) must consume the registry — the named seam S5
   contract; if PR-3's builder projects dataset variables through a SECOND decode path,
   that is the R5 divergence and reddens the A7 walk's dataset half, which is the
   walk's purpose.

## 8. Acceptance — pre-committed, denominators and kill directions

Stated BEFORE any arm is written. New module `tests/server/test_format_path.py`;
amended: `tests/server/test_analysis.py`, `tests/server/test_report_export.py`,
`tests/server/test_capture_lifecycle.py` (a raw_binary lifecycle arm if none exists —
the existing arms default `format: "waveform_f64le"` at `:168`), the catalogue schema
pin. All arms hermetic (the lifecycle fixture machinery, mock transport); no new marker
partition; no new CI job.

**Fourteen arms:**

- **A1** `capture_series` over a `raw_binary` capture: points `x == [0.0, 1.0, …,
  N-1]` EXACTLY (no multiplier), `y ==` the fixture bytes, `format` echoed,
  `decimated: true` under a small `max_points`.
- **A2** `capture_series`/analysis over `waveform_f64le`: UNCHANGED — x ==
  `index * interval`, manifest fields read as today (the regression pin).
- **A3** `analysis_view` over `raw_binary`: stats over byte values with denominators;
  entry `x_label == "sample index"`, `y_label == "byte value"`, `unit is None`.
- **A4** `report_export` over `raw_binary`: succeeds; the caption/manifest block carry
  the format and `sample index` axis; `sample_interval_s` prints the honest absence for
  an index source; no `"s"` axis anywhere in the document.
- **A5** a mixed export (V + A + `raw_binary`) refuses `standalone_report_units_unsupported:`
  (three labels); a V + `raw_binary` export renders (two).
- **A6** (the parent's) the bit-plane archetype — an invented-name logic-analyser-shaped
  fixture — completes capture → series → analysis → report, all green.
- **A7** the exhaustion gate: the derived-enum both-ways/order assertion (§2.4.1) AND
  the parametrized walk green for every admitted format (2 formats × 3 surfaces = 6
  walk cells).
- **A8** markers on a `raw_binary` capture: `t` inside `[0, N-1]` stores and
  re-exports; `t` outside refuses `standalone_report_marker_invalid:`; the overlay
  survives a fresh export round-trip.
- **A9** a hand-written manifest with an UNKNOWN format (`"csv"`): `capture_series`
  refuses as today; `_load_one` refuses `standalone_report_format_unsupported:` naming
  the admitted set.
- **A10** `raw_binary` manifest with a missing/non-int `byte_length` →
  `standalone_report_manifest_incomplete:` naming it; primary length contradicting
  `byte_length` → `standalone_report_primary_length:`.
- **A11** `capture_start` with an unknown format through a DIRECT seam call →
  `standalone_capture_format_unknown:`; nothing published.
- **A12** the web picker lists a published `raw_binary` row; the figure's `x_unit` is
  the index label and `axes` carries `sample index;byte value`; an unknown-format row
  stays excluded.
- **A13** the power family with a `raw_binary` source present: no crash; the byte
  source forms no rail; a `raw_binary`-only power request answers the existing
  `power_unavailable` reason.
- **A14** the write path is untouched: a `waveform_f64le` manifest still carries the
  three timing fields, a `raw_binary` manifest still carries none (pin the asymmetry
  the corpus mandates).

**Mutations, each reddening its named arms (both runs pasted in the PR):** M11
(the parent's) restore the waveform-only gates → A1, A3, A4, A6, A12 and the walk's
`raw_binary` cells. M12 (the parent's) fabricate a time axis for `raw_binary` (x-unit
`"s"`, interval printed, or a non-unity multiplier) → A1 (x values), A4, A12. M21
decode `raw_binary` as f64 (drop the spec's code) → A1, A3. M22 re-harden `_FORMATS`
as a literal and append a phantom format → A7's both-ways arm. M23 drop the marker
grid derivation (read `sample_count` as today) → A8. M24 drop the capture_start
mirror → A11.

**Kill directions:** any mutation leaving its named arms green kills the claim — fix
the mechanism or the fixture, never the arm. A1 green under M12 means the fixture is
not asserting the x values it holds (a fixture bug, not a pass). A7 green under M22
means the derivation was not actually replaced (a measurement bug). A mutation
reddening more than three arms OUTSIDE its named set means coupled fixtures — re-slice
before trusting any green. A6 failing on the bit-plane archetype while A2's waveform
pin passes means the path is still waveform-shaped — do not merge. **Denominator:** the
raw `pytest -q` collected count (redirected output, never a filtered summary line),
pasted in the PR beside the arm count; the walk's stated denominator is
`len(_FORMATS["enum"])` × 3 surfaces, printed by the test itself. Gates: ruff; strict
mypy (`files = ["src"]`); full `pytest -q`; `sync-standards --check` (no vendored
motion — the corpus is READ, never edited); `--version` smoke. Underpowered-case rule:
if A7's walk passes but fewer than the stated 6 cells RAN (a collection or parametrize
silently skipped), the measurement is void — the count is part of the claim.

## 9. Top risks, each with its falsifier

- **R-A: the index axis leaks into a seconds label somewhere PR-4 missed.** The
  x-labelling sites are enumerated (`web.py:220,229`; `report.py:246-270,320,356-361,391-411`);
  the falsifier is M12 — if any axis-printing site survives the mutation red-free, the
  enumeration was incomplete and the arm set grows before merge.
- **R-B: the registry derivation changes served schema bytes** (enum order, a
  copy where a reference was expected). Falsifier: the catalogue schema pins
  (`test_catalogue`/`test_capture_catalogue`) reddening on the derivation commit — the
  derivation must be byte-identical, and the pins prove it.
- **R-C: PR-3's dataset exposure grows a second decoder** (R5's divergence). The A7
  walk's dataset half is the falsifier — it cannot pass against a second renderer that
  skips `SeriesSource`; if PR-3 lands without the walk half, PR-4's record obligation
  (§2.4.3) is the open row, named in the PR body, not silently dropped.
- **R-D: a downstream consumer parsed `points[].x` as seconds unconditionally.** The
  wire shape is unchanged and `format` was always echoed; the guide's axis-meaning
  amendment is the disclosure. Falsifier: none in-tree (the in-tree consumers are the
  web figure and the report, both fixed here); a downstream break would arrive as an
  issue against the release notes' BREAKING-or-not judgement — the release notes carry
  the axis sentence either way.
- **R-E: `raw_binary` captures up to the 16 MiB reservation ceiling strain the series
  path's read-then-slice.** This is the INCUMBENT posture for waveform (same code
  shape); the `_RAW_SAMPLE_CEILING` guard (`seam.py:186,2317`) already refuses
  unbounded raw serving. Falsifier: an A1-shaped arm at the ceiling staying green
  under the memory budget; if it cannot, the ceiling arm documents the bound rather
  than widening it.

## 10. Memory ledger (proposed at session close, source `increment-designer`)

(a) The vendored `captureManifest` schema itself defines `raw_binary` as the no-timing
format — `byte_length` required for all formats, timing fields required only under the
`waveform_f64le` branch; any host that demands timing of a raw byte stream is calling
conformant data incomplete (otdp-runtime.schema.json `$defs.captureManifest`).
(b) Deleting a format gate is not a render fix: `capture_series`'s grid reads default
silently (`sample_count` → 0), so a gate-free raw_binary capture would serve an empty
series — the fix must derive each format's grid from the fields its manifest honestly
carries (the index grid comes from `byte_length`, never an invented interval).
(c) The web picker's "never offer what analysis refuses" filter made D5 quieter than a
refusal — the rows were invisible, not rejected; a refusal that names itself beats a
filter that hides (the D12/D18 silently-empty pattern, third sighting).

---

## 11. Fold append (2026-11-07, post-build — append-only; the frozen bytes above stay as committed)

Two refute lanes ran against the build. Both agreed the served wire is defended —
every admitted format renders honestly on every surface, the index axis never wears a
seconds label, and both deleted tables were replaced without narrowing their call
sites. This section records the fold that resulted and the corrections that belong to
the record itself.

**The §2.3 misattribution, corrected (lane 1 F1, G4).** §2.3 says the series refusal
keeps "same code, same message, per the parent's 'refuses as today'". The parent
(`2026-11-06-589-live-bringup-design.md:871`) ruled BEHAVIOUR only — "an UNKNOWN
format (not in `_FORMATS`) refuses as today" — and never ruled on the message. The
build therefore rightly changed the text (it names the admitted set; the old text
stated a falsehood after PR-4). §6's deferral ("kept bare per the parent's 'as
today'") inherited the same misreading: the parent's silence was never a bare-message
ruling, so the deferral's premise was the child putting words in the parent.

**The series refusal joins the fifth prefix (maintainer adjudication).**
`standalone_capture_format_unknown:` — §3's row five, the one NEW prefix — now fires
at BOTH capture-family doors. Its layer ruling is unchanged:
`SeamError("invalid_request", …)` at the operation boundary (not construction, not
connect — the parent's `ValueError`-at-construction / `RuntimeError`-at-connect pins
stay untouched). The adjudication overrules §6's deferral on coherence grounds, not
by claiming its trigger ("a CI need to branch on it") fired: the same registry lookup
(`catalogue._FORMAT_SPECS.get`) refuses the same trigger class — a format outside the
registry — at two doors of one operation family, and STD-4 reaches `SeamError` paths
(the invariant's own list is full of them; the `_REPORT_REFUSAL_CODES` comment at the
seam says the prefix stays in the wire message), so a typed refusal carrying bare
prose is the thing the invariant forbids. One name, both doors; the series message
keeps its `artifact_read` guidance (read-side audience), the START door keeps its
own (write-side). Nothing in-tree branches on the bare text (grep: no test or source
matches it beyond the guidance substring A9 already pinned). `docs/internal/
invariants.md` STD-4 is amended to name both doors. A9 pins the prefix; RED at head
was the bare message: `'capture_series serves waveform_f64le, raw_binary primaries;
use artifact_read for a csv capture'.startswith('standalone_capture_format_unknown:')`
→ `False`.

**The A7 dataset half — the trigger fired unbuilt, and is now armed.** §2.4.3
conditioned the walk's dataset half on PR-3's landing; this branch's own base
(`8bf2304`) IS the PR-3 merge, so §7.3's falsifier ("reddens the A7 walk's dataset
half") named something that could not fire — R5 was unmet at the build. Served
reality, measured by lane 2: a dataset is manifest-only (inline values, no primary,
no format — `capture_list`'s datasets row carries neither), and every display surface
answers a dataset id with `not_found` / `no published capture: <id>` — the series
door via `_event_dir`'s manifest check, the analysis and export doors via
`_stale_row_refusal`. Nothing served is wrong; the property existed unpinned. The
fold arms it: `test_a7_dataset_half_a_dataset_id_refuses_honestly_on_every_surface`
admits a REAL dataset through the invoke machinery and asserts the honest
`not_found` on all three surfaces — the R-C falsifier a second decoder would redden,
finally able to fail. A dataset RENDERER (series from dataset variables) remains a
corpus motion; when it lands it must arrive through the registry (S5), and this arm
is the half that inverts then.

**Measured mutation named-sets (the fold's own three, executed one at a time; each
reddened exactly its named surface, so unlike PR-3's append nothing here supersedes
a §8 set):** M-R5a (a `ds:` branch in `_event_dir` resolving into the datasets
family — the second decoder's first step at the series door) reddened the SERIES
assert only: `'invalid_request' == 'not_found'` fails. M-R5b (`_stale_row_refusal`
skipping `ds:` ids) reddened the ANALYSIS assert via the message discriminator — the
CODE stayed `not_found` (`standalone_report_capture_unknown`, the loader's own
refusal, reached only because the skip moved the refusal site), proving the arm's
message pin is load-bearing, not decorative. M-R5c (the export loop skipping the
stale-row refusal) reddened the EXPORT assert the same way. Each run: one failure,
the named surface, nothing else.

**The units-ceiling wording (NIT).** §2.3's "the two-distinct-units ceiling counts
`y_label`s" described the mechanism correctly, but the served text still said "two
distinct units" while counting labels — and `byte value` is a label, not a unit. The
refusal now reads "two distinct y labels"; prefix and trigger class unchanged
(STD-4 untouched); the guide already said labels (`user_guide/plugin-sdk.qmd:1000`),
so the wire joins the prose rather than the reverse. A5 pins the wording.

**Left as adjudicated (the two accepts):** the record's `.data` charter sentence
stays as written — an unknown-format primary named with its own extension raises an
uncaught `FileNotFoundError` (byte-identical at base, pre-existing, unreachable
through the host's own writer). And both refute lanes' first-run `21 failed / 10
errors` symptoms were corrupted or raced venvs in their own scratch worktrees, not
this branch's code (lesson already in the ledger: never run `uv run` gates
concurrently with a suite).
