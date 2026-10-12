# Hard invariants

Testable assertions a PR must never violate. Anchors are on `main`. When an anchor's line
number drifts, the symbol name is the source of truth — re-locate by grep, don't trust the
number. If the live code disagrees with an assertion here, the code wins: flag the stale
invariant, don't enforce it.

Format: **[ID]** assertion — `file:anchor` — *why it matters / what breaks if violated.*

The SDK is the offline authoring and conformance tooling for OTDP device plugins. Its
weight-bearing surfaces are the standards sync, the scaffold, the preview, and the wheel —
the invariants below anchor there.

---

## Standards & packaging invariants

- **[STD-1]** **Lock ↔ vendored tree ↔ stamps**: every file in
  `src/benchweave_sdk/standards/` is recorded in `standards-lock.json` by sha256 or carries
  a `_GENERATED.txt` stamp; a file that is neither is `unexpected_vendored_file` drift, a
  missing stamp is `stamp_missing`, a byte change against the lock is `hash_mismatch` —
  the standards-sync check, `src/benchweave_sdk/` (refusals from `sync-standards`). *The
  lock is what makes "vendored" mean pinned rather than copied; an unrecorded file in the
  tree ships in the wheel with nobody's hash behind it.*
- **[STD-2]** A vendored content change without a standards version increment is refused
  (`standards_version_required`), and hashes are recomputed from the bundle's files on
  disk — never read from the bundle's own manifest claims — `standards_sync.py`. *A
  manifest that vouches for itself is not a pin; and content must move version-first, not
  hash-only.*
- **[STD-3]** The stray/stamp gates are **symmetric across all three check lanes**:
  `sync-standards --check` without a bundle (the committed state alone), bundle-mode
  `--check`, and the `hatch_build.py` packaging hook. A change that tightens or loosens one
  lane without the others is drift — the lanes exist so the same tree is verified identically
  before sync, after sync, and at packaging time. *Three lanes checking three different
  things is three different standards, which is none.*
- **[STD-4]** **Refusal prefixes are the contract**: every refusal path raises a
  `snake_case:`-prefixed `ValueError` (`bundle_required`, `bundle_manifest_missing`,
  `bundle_manifest_invalid`, `bundle_version_unsupported`, `bundle_path_invalid`,
  `bundle_file_missing`, `lock_invalid`, `lock_missing`, `lock_version_unsupported`,
  `standards_version_required`, `hash_mismatch`, `not_synced`, `stamp_missing`,
  `unexpected_vendored_file`, `sync_requires_repo_checkout`, `sync_staging_blocked`, `unknown_contract_schema`,
  `provider_feature_missing`, `provider_transport_undeclared`, `unknown_otdp_feature`,
  `provider_contract_missing`, `provider_contract_hash_mismatch`,
  `provider_contract_invalid` — the last six are the 0.2.1 transport-provider lane;
  `scaffold_extra_absent`, `scaffold_template_missing`, `scaffold_answers_missing`
  and `upgrade_answers_missing`, `upgrade_requires_git`, `upgrade_dirty_tree`,
  `upgrade_tag_missing`, `adopt_answers_present`, `adopt_provenance_unknown` —
  the WS2 scaffold lane
  (`scaffold.py`, `scaffold_update.py`, the copier render/update path); ordinary
  descriptor schema-shape failures keep the existing
  descriptor-validation error surface. The standalone host's stdio shim
  (issue #440) adds three, each naming its resolving action in the
  message: `standalone_supervision_unknown:`,
  `standalone_host_unproxyable:`,
  `standalone_capture_root_held:` (`benchweave_sdk_server/shim.py`).
  Known wound, disclosed: the provider
  pin's read inherits the SDK-wide bounded-file cap
  (`presentation.INPUT_BYTE_LIMIT`), so a corpus-valid contract above the cap
  refuses with `provider_contract_invalid:` — the cap is an SDK resource
  bound, not a semantic disagreement with the contract). A new refusal path that raises
  bare prose breaks the machine-matchable surface CI and scripts branch on —
  `standards_sync.py`, `cli.py` (the sync lane's checkout-detection refusal),
  `validation.py` (the descriptor lane's unknown-schema refusal and the
  provider lane's six prefixes). *The prefixes
  are an API even though they live in error text.*
- **[STD-5]** The stamps say *generated — do not edit*: a hand-edit to a vendored file is
  wrong no matter how good the edit is; the change belongs in the main repository's
  canonical corpus, re-exported and re-synced. Normative standards changes start main-side
  — `src/benchweave_sdk/standards/`. *Two owners for one file means the lock always loses.*
- **[STD-6]** The lock's `compatibility.notes` is operator-authored state: the sync writer
  carries it verbatim from the committed lock and never authors, updates, or clears it —
  hand-editing the lock is the only writer, and a malformed value (a non-string `notes`, a
  non-object block) is a `lock_invalid` refusal from the one shared lock reader —
  raised in `standards_sync.py::_read_lock_file`, which `_preserved_notes` reaches via
  `_read_lock` — pinned by the compat-notes cells in
  `tests/test_standards_sync.py`. *Every import sync regenerates the lock, and one member
  of `compatibility` is prose a machine cannot derive — the #170 erasure of a filled note
  is the evidence; regenerating it could only ever produce the placeholder null.*
- **[PKG-1]** **Self-containment**: this repository's CI checks out with no submodules and
  never reads the gateway checkout; nothing at test or runtime may reach for the parent
  repository's paths — `.github/workflows/ci.yml`. *The submodule mount makes parent paths
  exist on a developer machine and not in CI, so the breakage is invisible exactly where
  it matters most.*
- **[PKG-2]** The wheel packages `src/benchweave_sdk` only, plus the force-included copier
  template (root `copier.yml` + `template/` → `benchweave_sdk/scaffold_template/`, issue #347
  WS2 — the repository root IS the copier template, and an installed SDK renders `new` from
  the packaged copy offline. The template's own `CLAUDE.md.jinja`/`pyproject.toml.jinja`
  members — and, since WS3, `template/AGENTS.md.jinja` and
  `template/.claude/skills/**` — are generated-project content riding that carve-out:
  template-borne scaffold content is PRODUCT content inside the force-included template,
  not this repository's agent config or build config, which still never ship) alongside the root `standards-lock.json` placed at
  `benchweave_sdk/standards-lock.json` so an installed SDK can verify its vendored tree
  offline; the sdist include list is explicit (`src`, `pyproject.toml`, `README.md`,
  `hatch_build.py`, `standards-lock.json`, `copier.yml`, `template`); this repository's
  OWN `.claude/`, `.mcp.json`, `AGENTS.md` and `CLAUDE.md` at their repo-root locations
  must never appear in either artifact — the template-borne copies under `template/` are
  the carve-out above (WS3); `hatch_build.py` validates
  the vendored standards and the scaffold template's presence **before** packaging —
  `pyproject.toml` `[tool.hatch...]`, `hatch_build.py` `CustomBuildHook.initialize`.
  *A wheel that ships agent config or an unverified tree is a supply-chain event, not a
  packaging nit.*
- **[PKG-3]** **Renderer freshness — CLOSED at 0.7.0** (issue #308): the frozen
  renderer bundle (`src/benchweave_sdk/preview_assets/`) is deleted; there is no
  renderer build to keep fresh and no bundle bytes to drift — previews render through
  the standalone host and `benchweave-ui-html`, whose freshness is the EXACT pin in
  the `[server]` extra (it moves only by a pin bump in this repository). The row
  stays as the closed record. Its former enforcement (the gateway `ui` job's
  `git -C packages/sdk diff` over the tree) no longer exists in gateway CI either
  (verified absent at the 0.7.0 design). *Freshness moved from a committed-bytes
  check to a pinned dependency — the same guarantee, one mechanism fewer.*

## Surface & conformance invariants

- **[SRF-1]** Scaffold output is an interface: entry points, the generated `pyproject.toml`,
  the explicitly-synthetic protocol placeholder and its warnings, the AI-GUIDE text, and
  the test extra that pins the SDK version reproduce into every downstream plugin
  repository — the carriers live in the copier template (`template/`), rendered by
  `scaffold.create_project` and pinned byte-for-byte against the committed fixture
  (`tests/fixtures/scaffold_expected/`, the R-2 gate). Since WS2 the generated tree gains
  exactly one file, `.copier-answers.yml` at the project root (outside `src/<pkg>/`, never
  in a plugin wheel), recording the canonical template source and the SDK version's
  template tag. Since WS3 it also gains the six managed agent-asset files —
root `AGENTS.md` plus `.claude/skills/benchweave-*/SKILL.md` — all outside
`src/<pkg>/` and never in a plugin wheel: refreshed by `upgrade` (with the
installed SDK's stamp, R-5d), conflict-marked when author-edited, and their
factual claims (cited refusal codes, subcommands, guide headings) reconciled
against SDK source and the user guide by `tests/test_agent_assets.py` (R-5b,
with permanent planted-violation arms R-5c). The generated plugin runtime has **no dependency on this SDK**. *A defect
  here multiplies across every plugin authored from the scaffold, and downstream repos
  diff generated output, so shape changes are interface changes.*
- **[SRF-2]** **Host-loader ↔ check-ui agreement** (amended at 0.7.0, issue #308): the
  standalone host loads a plugin's presentation through
  `load_validated_preview_inputs` — the same loader `check-ui` validates with — so
  the host accepts exactly what `check-ui` accepts; a host that serves what the
  conformance check rejects (or the reverse) is the cross-surface bug — anchors:
  `presentation.py` (the one loader), `benchweave_sdk_server/session.py::
  load_plugin_project` (the host's refusing consumer), `fixtures.py` (the projections
  behind both); standards are read from the vendored tree and nowhere else. The
  pinning suite lives in THIS repository — the standalone distribution's own tests
  (the projection arms in `tests/test_preview_fixtures.py`, the both-directions
  agreement arm in `tests/server/test_adapter_failure.py`), resolving
  `benchweave_sdk` from the installed environment, never a `sys.path` checkout
  (R-10). *A host that disagrees with the checker trains plugin authors to ship
  what the gateway will refuse.*
- **[SRF-3]** Conformance and validation encode, offline, the standards the gateway
  enforces at load: a weakening here silently greenlights a non-conformant plugin. When
  reviewing a rule, compare it against the vendored standard text in
  `src/benchweave_sdk/standards/` — never against memory of what the standard says —
  `conformance.py`, `validation.py`, `fixtures.py`. *Confident recall of a standard is how
  a wrong rule ships.*
- **[SRF-4]** (the I4a design record's new row; the maintainer assigns the final ID at
  landing) A processed value is never rendered without its definition id, its
  denominators (count, null_count, window) and the `host-computed` label — anchors:
  `benchweave_sdk_server/analysis.py` (the statistics carry their own denominators;
  I4b.1 extends the same rule to the edge-timing and assertion families under
  `benchweave-edge/1` and `benchweave-assert/1`; I4b.2 extends it to the power family
  under `benchweave-power/1`, whose integral rows additionally carry their coverage —
  `integrated_span_s` and `dropped_segments` beside Ah/Wh, a gapped integral is
  visibly partial), `report.py` (every statistics, edge, assertion and power block's
  caption), `templates/analyse-results.html`
  (the view's same caption discipline); pinned by the AR-4(c) arms in
  `tests/server/test_report.py`. *Without it, a report number means whatever the reader
  assumes — the evidence-exactness crux of a reporting slice.*
- **[SRF-5]** (row id per the SRF-4 convention: the maintainer assigns the final ID at
  landing) **The stdio MCP entry holds no state and never spawns** (issue #440): it
  proxies to the verified running host, or serves the disclosed in-process fallback
  over an isolated ephemeral capture root, or refuses typed — it writes no pidfile, no
  journal row, no tokens file, no bindings byte, and no AMBIENT capture-root byte; and
  a live host it cannot authenticate to is a refusal, never a fallback. Anchors:
  `benchweave_sdk_server/shim.py::discover` + the `mcp` command body
  (`benchweave_sdk_server/cli.py`); pinned by the SH2/SH5/SH6 arms AND
  `TestR5FallbackIsolation` (the isolation clause's only pin) in
  `tests/server/test_mcp_shim.py`. *Two hosts on one bench is the reference fork's
  shape — the entry point that cannot hold state cannot become the second one.*
- **[TWO-1]** **Two-repo discipline**: an SDK change lands as a commit in this repository
  (pushed), then a pointer commit in the main repository; the main repository's
  `make sync-sdk-standards` refuses to run against a submodule HEAD that differs from the
  committed pointer — that refusal is the discipline working, not a bug to route around.
  WS2 pairing note: when the pointer advances past the copier-template port, the gateway's
  scaffold-content pins (`tests/sdk/test_plugin_developer_skill_content.py`,
  `tests/sdk/test_scaffold_skills.py`, `tests/sdk/test_presentation_cli.py`) must stay green
  with exactly the answers file added to any full-tree expectations — they double as the
  independent parity check. *An unpushed submodule commit is invisible to main CI, which
  checks out by SHA.*

---

## Known open wounds

Some invariants sit next to known-imperfect code. Track the individual issue in the repo
tracker and cite it in review rather than building a consolidated weakness list here — a
one-stop map is more useful to an attacker than to a reviewer, who is only ever looking at
one diff. If a PR touches a wound, fix it or at least do not widen it, and say which.
