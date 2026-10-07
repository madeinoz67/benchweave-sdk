# Issue #285 — I3c ruled defaults: the Q13 ruling lands — design record

Date: 2026-10-08. Status: DESIGN. Repo: `benchweave-sdk`, branch
`feat/issue285-i3c-defaults`, based on `origin/main` at `24c76fb`. A small
ruled-consequence increment: no new capability, no evaluator change — the
ruled defaults become the shipped default configuration.

Authority chain: the ruling is the owner's, recorded in the gateway PRD
(`docs/implementation-planning/11-standalone-web-ui-prd.md` §8 Q13, ruled
2026-10-07): "ui/rest captures kept until deleted; mcp captures kept 30 days
unless pinned; warn at 80% of the byte quota. These are the *defaults* when
no custom rule matches: per-SW-55 rules (by source and by project, keys
composable, unset key = wildcard) are additive on top, and pinned and
in-flight captures are never pruned whatever a rule says." The I3c record
(`.claude/deep-review/2026-10-04-issue285-i3c-retention-design.md` §8 F-3)
pre-committed the landing shape: "the ruled default rules document … lands
as a DOCUMENT the day the PRD rules it". This slice is that day.

## 0. Premises verified against the landed tree (surveyed, not assumed)

- The shipped default today IS keep-everything at both construction sites:
  `serve` leaves `retention = None` when `--retention-rules` is absent
  (cli.py:394-399) — no scheduler (web.py:115 arms it only when
  `seam.retention.rules` is non-empty) and no guard; `prune` sets
  `rules = ()` and `grace_s = 900.0` directly (cli.py:580-583) — an empty
  plan, only the sweep removes. Both help texts state it ("Without it the
  host keeps everything…" / "Without it the plan is empty (keep-everything)
  and only the orphan sweep can remove anything"), as do README.md:241-243,
  user_guide/plugin-sdk.qmd:429+451, the retention.py module docstring and
  the seam.py constructor comment.
- The 80% warning threshold ALREADY exists as `QUOTA_FRACTION = 0.8`
  (retention.py:50), edge-triggered per `max_bytes` rule by
  `QuotaLatch.crossings` (retention.py:554-565). The ruling names no default
  byte-quota NUMBER, and the I3c record's reserve fork holds (no un-ruled
  constant ships — A02): so the warning's threshold is confirmed-and-pinned,
  not re-wired, and the ruled default set carries NO `max_bytes` rule — the
  warning fires for a quota an operator configures, at the ruled 0.8.
- The composition semantics the ruling names ("additive on top", "never
  pruned whatever a rule says") are the evaluator's LANDED semantics:
  `plan()` is a union of selections over id-sorted rules with
  first-selecting-rule attribution, and pinned/in-flight rows are
  structurally excluded (retention.py:301-323). This slice does not touch
  the evaluator, the recorder, the sweep or the latch.
- `load_config(path)` (retention.py:164-206) validates one document; its
  duplicate-id refusal exists because "deterministic evaluation needs
  unique sort keys" — the cross-set merge inherits the same invariant.
- F-3 deviation, disclosed: F-3's letter says the ruled defaults land "as a
  DOCUMENT … no code change". Contact with the code: without a code change
  the host still keeps everything — the default construction sites are
  `None`/`()`, and nothing in the shipped tree loads a packaged document by
  default. The engine (loader semantics, evaluator, log, sweep) is
  unchanged; the minimal code the ruling needs to be the SHIPPED default is
  the wiring at those two construction sites plus the packaged document
  itself. That is what this slice builds — the DOCUMENT shape is honored
  (the ruled set is data, parsed by the same validator as an operator's
  document), the "no code change" letter is not.

## 1. Mechanism

- **`src/benchweave_sdk_server/retention-defaults.json`** — the ruled set as
  a packaged document (F-3's landing shape; data, not code):
  `{"rules": [{"id": "default-mcp-30d", "source": "mcp", "max_age_d": 30}]}`.
  ui/rest "kept until deleted" is the ABSENCE of a rule (the evaluator's
  keep-by-default); pinned/in-flight exclusion is structural, already
  landed; "unless pinned" rides the same structural exclusion. No
  `interval_s` (the scheduler's 86400 s default stands), no
  `orphan_grace_s` override (900 s stands), no `reserve_bytes` (no ruled
  reserve; the storage guard stays commissioned configuration — A02).
- **`retention.py`**:
  - `parse_config(text)` — the parse+validate body factored out of
    `load_config` (one validation implementation; `load_config(path)` =
    read + `parse_config`, signature and observable behavior unchanged).
  - `ruled_defaults()` — reads the packaged document beside the module and
    validates it through `parse_config`. An unreadable packaged document
    refuses with the `standalone_retention_rules_invalid:` prefix naming it
    (a packaging defect refuses loudly — never a silent fallback to
    keep-everything).
  - `effective_config(custom)` — the composition. `custom is None` → the
    defaults alone. Otherwise: `rules = defaults.rules + custom.rules`;
    a custom rule id colliding with a default rule id refuses (same
    prefix, the loader's duplicate-id family — deterministic evaluation
    needs unique sort keys across the merged set too);
    `interval_s`/`orphan_grace_s`/`reserve_bytes` are the custom document's
    knobs (operational, single-valued — custom wins). Union evaluation then
    makes custom rules strictly ADDITIVE, which is the ruled composition:
    a custom rule can select rows the defaults keep (it "overrides" the
    default-keep for the rows it matches); NOTHING can loosen the mcp-30d
    floor — pinning stays the keep-forever mechanism, exactly the ruling's
    "unless pinned".
- **`cli.py`**: `_retention_for(retention_rules)` — the one resolution
  point both `serve` and `prune` call: absent flag → `effective_config(None)`;
  a document → `effective_config(load_config(path))`; every refusal is exit 2
  with the prefix (STD-4, unchanged vocabulary). The seam keeps accepting
  `None` (direct constructors — tests, embedded hosts — keep the
  keep-everything posture; the shipped default is a host LAUNCH
  configuration concern and the CLI is the launch surface).
- **Observable flips**: `serve` without `--retention-rules` now arms the
  schedule (daily) under the ruled defaults — the root lock arms at the
  first evaluation exactly as any rules-bearing host already does (the I3c
  record's disclosed risk 5, unchanged); `prune` without a document now
  plans the ruled defaults' removals instead of an empty plan.
- **Prose corrections against the machine source** (prose defers to machine
  sources): README.md's two retention paragraphs, the guide's §"Capture
  retention and the library page" (its "The engine ships no default rules.
  A default arrives as a document, not as host constants." line), both CLI
  help texts, the retention.py module docstring, the seam.py constructor
  comment, and the two test docstrings that call keep-everything "the
  posture the engine ships".

Deferrals: the stdio `mcp` command constructs no retention configuration
today and has no scheduler loop; it keeps that posture (the CLI prune
covers stdio hosts) — wiring a schedule into stdio is a follow-up row if
the owner wants it. No version bump rides this branch (releases are their
own trains; the SDK-side order rule keeps release-cut separate). No
`standards/` bytes move (tripwires verified at push).

## 2. Pre-committed acceptance rules (RED-first)

- **RD-1 (the ruled set is the shipped default).** `effective_config(None)`
  carries exactly one rule — `RetentionRule("default-mcp-30d", "mcp", None,
  30.0, None, None)` — with `interval_s is None`, `orphan_grace_s == 900.0`,
  `reserve_bytes is None`, and the packaged document parses through
  `parse_config` (the same validation an operator's document passes). Over
  the existing golden corpus, a no-document `prune --dry-run --json` plans
  exactly `cap-alpha` and `cap-charlie` (the unpinned mcp rows older than
  30 d; 100 + 150 bytes), and a real prune removes exactly those two with
  `retention.log` rows under rule `default-mcp-30d`, trigger `cli` — while
  `cap-bravo` (mcp, 10 d), `cap-hotel` (mcp, pinned), EVERY ui/rest row
  (including the 80-day `cap-lima` and 60-day `cap-golf`) and `cap-mangle`
  (unparseable age) stand. A seam under `effective_config(None)` prunes the
  same two through `run_retention_once` (trigger `scheduled`, one
  `retention_pruned` event). RED control: with the packaged document
  neutralized to `{"rules": []}` (cp backup, not git checkout), every one
  of these arms fails.
- **RD-2 (the 80% threshold is the ruled warning, pinned).**
  `QUOTA_FRACTION == 0.8`; a usage at exactly 0.8 of its cap crosses
  (`>=`), 0.79 does not; and the ruled defaults carry no `max_bytes` rule —
  `quota_usages` over the defaults is empty (no default byte quota was
  ruled; the warning guards an operator-configured quota).
- **RD-3 (custom rules are additive on top).** A custom document
  `{"rules": [{"id": "a-ui-7d", "source": "ui", "max_age_d": 7}]}` composed
  through `effective_config` plans the defaults' set PLUS `cap-foxtrot`
  (ui, 20 d — a row the defaults keep), attributed to `a-ui-7d`. A custom
  mcp rule `{"id": "a-mcp-90d", "source": "mcp", "max_age_d": 90}` changes
  nothing: `cap-alpha`/`cap-charlie` are still selected, attributed to
  `default-mcp-30d` (union semantics — a custom rule cannot loosen the
  floor). The custom document's `interval_s`/`orphan_grace_s`/
  `reserve_bytes` ride through the composition.
- **RD-4 (collision refuses).** A custom rule id equal to a default rule id
  refuses with `standalone_retention_rules_invalid:` naming the duplicate
  family; at both CLI surfaces the refusal is exit 2 before any work (for
  `serve`: before any bind).
- KILL = any expectation loosened to make an arm pass, or any change to the
  evaluator's union/pinned/in-flight semantics.

## 3. Review tier

Tier 3 by the standing rubric (deletion-semantics surface + refusal paths;
STD-4 vocabulary unchanged — the existing prefix gains messages, not new
prefixes). The eight-keyword scan rides the review lanes against the real
diff.
