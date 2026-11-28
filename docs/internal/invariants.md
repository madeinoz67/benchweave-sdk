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
  (`scaffold.py`, `scaffold_update.py`, the copier render/update path); the
  migrate-ui lane (issue #460) adds `migrate_ui_ahead:`,
  `migrate_ui_version_absent:`, `migrate_ui_stamp_unlocatable:` and
  `migrate_ui_invalid_after_stamp:` — every refusal before the write step,
  so a refused migration writes nothing (`presentation.py`); ordinary
  descriptor schema-shape failures keep the existing
  descriptor-validation error surface. The standalone host's stdio shim
  (issue #440) adds three, each naming its resolving action in the
  message: `standalone_supervision_unknown:`,
  `standalone_host_unproxyable:`,
  `standalone_capture_root_held:` (`benchweave_sdk_server/shim.py`). The
  live FTDI transport's selector ladder (issue #589) adds three more —
  `live_provider_device_ambiguous:`,
  `live_provider_interface_out_of_range:` and
  `live_provider_selector_malformed:` — and these three are pinned as
  **`RuntimeError`, not `ValueError`**: they fire inside
  `PluginSession.connect`'s services factory, where a `RuntimeError`
  passes through unwrapped and maps `not_ready` with the message verbatim
  while any other type arrives buried in a
  `standalone_plugin_connect: ValueError:` wrapper (`session.py`'s
  connect re-raise; the boundary arms in
  `tests/server/test_ftdi_selector.py` pin all three). Construction- and
  reload-time refusals stay `ValueError` — the type is part of each
  prefix's contract at the seam where it fires.
  The invoke lane (issue #589 PR-2) adds four at seam construction and at
  reload, all `ValueError` (the CLI maps them to exit 2):
  `profile_contract_missing:`, `profile_contract_hash_mismatch:`,
  `profile_contract_invalid:` (the pinned-contract family — a pinned entry
  that is neither measurement-shaped nor catalog-schema-valid refuses
  whatever its URN; the resolver matches the gateway's, whose loader
  raises for the same bytes) and `standalone_action_budget_infeasible:`
  (an action row's `timeout_ms` above the serving invoke verb's budget — a
  bound-coherence guard, not a completion guarantee: the per-attempt cost
  is nowhere in the descriptor) — anchors:
  `benchweave_sdk_server/invoke_contracts.py`,
  `benchweave_sdk_server/seam.py` (construction and the pre-swap reload
  resolution). The dataset admission lane (issue #589 PR-3) adds four more:
  `standalone_dataset_context_absent:` (`ValueError` at the services
  boundary — a `dataset_publish` reached with a null `context.dataset_id`,
  a non-invoke dispatch), `standalone_dataset_invalid:` (admission
  validation refusal: `SeamError("invalid_request", …)` at the invoke
  operation boundary with the pinned schema's `json_path` and the D10
  divergence sentence in the message, `ValueError` when raised through the
  services member — every refusal fires before any filesystem call),
  `standalone_dataset_unknown:` (`ValueError` at the services member — a
  `dataset_lookup` for an id this host process did not admit; a build-time
  reconciliation, disclosed: the design record §4's table names three
  prefixes and no lookup row, and STD-4 forbids bare-prose refusal paths,
  so the lookup miss carries its own honest prefix rather than borrowing
  the schema refusal's), and `standalone_capture_verb_undeclared:`
  (`SeamError("unavailable", …)` — `capture_start` with no `capture`
  operation declared; the D6 repair removed the lying `invoke` fallback
  and moved the verb check BEFORE the capture-services duck-check:
  declaration precedes host capability) — anchors:
  `benchweave_sdk_server/dataset_admission.py`,
  `benchweave_sdk_server/seam.py`.
  The dataset identity binding (ADR 0606, gateway issue #606) adds five
  more, all `ValueError` at the services boundary and each raised before any
  admission or index write: `standalone_dataset_id_mismatch:` (the context
  carries a dataset id the active invoke did not mint),
  `standalone_dataset_operation_mismatch:` (the context names an operation
  that is not the invoke the call was made in, or the call was not made in
  that active invoke),
  `standalone_dataset_invoke_closed:` (the invoke has closed — it finished,
  errored or was cancelled — and its dispatch record is history, not
  authority), `standalone_dataset_not_dispatched:` (this controller has no
  dispatch record for the operation and no active invoke for it) and
  `standalone_dataset_input_absent:` (the dispatch record carries no
  captured input: the dispatch had none, or the host could not copy it, so
  there is nothing to check the manifest's echo fields against; a caller's
  object is never used in its place) — anchor:
  `benchweave_sdk_server/dataset_admission.py`, pinned by the T3, T4 and
  fold arms of `tests/server/test_dataset_identity_binding.py`.
  The format path (issue #589 PR-4)
  adds one more, `standalone_capture_format_unknown:`
  (`SeamError("invalid_request", …)` at BOTH capture-family doors — a
  format outside `catalogue._FORMAT_SPECS`: at `_op_capture_start` on a
  direct handler call, where the served schema's enum DERIVES from the
  same registry, so schema-validated callers refuse earlier, and the
  mirror is the A-F8 settle_pct posture (the host does not publish a
  capture every display surface refuses); and at `_op_capture_series`,
  where a published manifest whose format is outside the registry
  refuses with the SAME prefix (the fold adjudication, 2026-11-07: same
  trigger class, one name for both doors of the operation family).
  The registry itself — `FormatSpec` plus
  `_FORMAT_SPECS`, with `_FORMATS` derived — is the single source behind
  the served enum, the write-side bound math and the display decoders;
  the exhaustion walk in `tests/server/test_format_path.py` pins the
  derivation both ways and drives every admitted format over every
  display surface) — anchor: `benchweave_sdk_server/catalogue.py`,
  `benchweave_sdk_server/seam.py`. The preset homes (issue #589 PR-6)
  add two more, both `ValueError`: `standalone_preset_home_conflict:`,
  refusing a preset id that exists in BOTH documented homes (a
  `config/presets` file stem equal to a presentation-manifest preset
  asset id) — the scaffold's one-authoritative-copy rule, mechanically
  enforced — at seam construction and at reload against the INCOMING
  plugin before the session swap (the `profile_contract_*`
  construction/reload convention), and at the authoring `preset_put`
  before any byte is written, where the same prefix rides `AuthoringError`
  (a `ValueError` subclass carrying `code`, `authoring.py`) and the tool
  wrapper translates it to a typed error result — the authoring door's
  authority is that translation, not the construction convention; and
  `standalone_presentation_unreadable:`, refusing a presentation whose
  already-validated documents cannot be walked for preset assets — its
  live doors are the reload PRE-SWAP walk and direct helper calls; at
  seam construction it is SHADOWED by `HostPresentation`'s own `check_ui`
  reading the same documents first, where drift surfaces as
  `preview_invalid_presentation: digest_mismatch`, a symlinked component
  as `path_symlink_component:`, and unparseable bytes as a bare
  `DocumentError` — a `ValueError` subclass but unprefixed (pre-existing,
  not this diff's change; the disclosed row in the PR-6 fold record) —
  the silent-empty class D12 died from, one lane over.
  Every apply-lane refusal REUSES existing surfaces: invoke's I2/I4/I5
  codes, `_stageable`'s messages, the firmware gate's `conflict`, the
  digest-mismatch findings — anchor: `benchweave_sdk_server/seam.py`,
  `benchweave_sdk_server/presentation.py`,
  `benchweave_sdk_server/authoring.py`.
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
  The provider-kind slice (issues #568 and #570, bullet 4) adds
  `unsupported_transaction_kind:` at the three section 8.1 field-set
  refusals — `serial.py` (`SerialCaptureServices.transfer`),
  `transport.py` and `replay.py` — because the seam forwards the
  `ValueError` text to the wire verbatim (`seam.py`), so bare prose reached
  the operator un-branchable. Anchor: `tests/server/test_serial_conformance.py`,
  `tests/server/test_mock_bytestream_host.py` and `tests/server/test_replay.py`
  each pin the prefix. Pure prepend: the old sentence stays byte-present
  inside the message, so every existing `match=` arm in both repositories
  keeps matching.
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
with permanent planted-violation arms R-5c). Since gateway issue #596 the
interface also carries the generated `.github/workflows/ci.yml` (jobs `lint` and
`tests`; expression-free and byte-identical across every arm — rendered by
verbatim copy, never jinja), the `lint` extra carrying the explicitly-selected
minimal ruff set, and a `test` extra. **Each arm's generated `test` extra must
install everything that arm's generated suite imports.** Since gateway issue #597
(ADR 0001) every arm renders the same plain pin, `benchweave-sdk==<version>`: the
provider arm's shipped-double tests drive `ftdi_plugin_session` through an
injected driver factory, and that connection path validates the plugin contract
without importing pyftdi. The pyftdi preflight stays on `verify_ftdi_plugin` —
serve construction, discovery and the default-driver connection — and refuses
with `live_provider_backend_missing` and the `[server]` install command (its
arms are the ADR 0001 section of `tests/server/test_ftdi.py`). The plain pin is
EXECUTED at PR time by this repository's `ci.yml` generated-workflow step
(ubuntu-only, every push, against the wheel under test via `UV_FIND_LINKS`): a
fresh scaffold of each arm must pass BOTH job commands its own workflow ships
(3 arms × 2 jobs), and the provider test leg carries three assertions that each
red on their own — the generated test extra is EXACTLY the plain pin, the pin
resolves to the wheel under test, and pyftdi is not importable in the
environment the suite ran in, so its ≥8 passed were earned without the backend.
What the step does not catch: a generated suite that reaches the backend on a
path its own tests never take. The template and the wheel ship together, and the
pin names the version that rendered it: `upgrade` never rewrites `pyproject.toml`
(`_skip_if_exists` in `copier.yml`, pinned by
`tests/test_scaffold_update.py::test_skip_list_is_load_bearing_on_update`), so a
project scaffolded from a version without the split keeps its `[server]` pin and
the wheel that needs it. Pinned offline by
`tests/test_scaffold_copier.py::test_new_project_tree_matches_fixture_provider`
(the rendered pin, byte-exact against the fixture) and
`::test_the_generated_provider_suite_runs`; the workflow and the lint set by
`tests/test_scaffold_copier.py::test_the_generated_workflow_carries_the_lint_and_test_jobs`
and `::test_each_arm_passes_the_lint_set_its_pyproject_declares`; end-to-end
by `tests/test_standalone_dev_loop.py`, whose installed-wheel scaffold asserts a
dot-directory survives the wheel. The generated plugin runtime has **no dependency on this SDK**. *A defect
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
- **[SRF draft]** (issue #589 PR-6; the maintainer assigns the final ID at landing) The
  host serves a plugin's declared presets from BOTH documented homes — `config/presets`
  and the presentation manifest's preset assets — and refuses an id duplicated across
  them at construction, at reload before the swap, and at the authoring write: the
  scaffold's one-authoritative-copy rule, mechanically enforced. A preset applies through
  the lane its own document declares (a corpus action input-schema `$id` resolves to the
  action lane; a custom `$id` applies no envelope and rides the parameter lane) —
  anchors: `benchweave_sdk_server/seam.py` (`_preset_rows`, `_preset_bytes`,
  `_op_preset_apply`), `benchweave_sdk_server/presentation.py`
  (`manifest_preset_assets`), pinned by `tests/server/test_preset_homes.py`.
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
- **[SRF-6]** (the #589 PR-3 design record's new row; the maintainer assigns
  the final ID at landing) The standalone dataset admission path validates
  what the gateway's `dataset_publish` validates — identity (for BOTH
  admission paths, the explicit member and the inline admission, and only as
  the amendment below states it: **for ACTIVE host invokes only**; the
  manifest's `dataset_id` equals the host-minted `"ds:" + operation_id`,
  minted per
  invoke dispatch at context construction), idempotency (a byte-identical
  manifest under a used id returns the admitted manifest; a divergent one
  refuses naming immutability), the pinned measurement schema (read through
  PR-2's contract resolution, never re-derived in `src/`), the M01–M04
  structural checks including the channels cross-check against the
  descriptor, the M10 echo subset, and M11 scope stated honestly (no
  payload lane ships: artifact-backed variables refuse naming the absent
  surface) — minus the payload lane. Validation precedes any filesystem
  call: a refusal leaves zero bytes under the capture root's `datasets/`
  family, and the one write is atomic. Anchors:
  `benchweave_sdk_server/dataset_admission.py` (the core),
  `benchweave_sdk_server/seam.py::_invoke_core` (the inline call, the
  mint's observe hook), pinned by the A1–A20 arms in
  `tests/server/test_dataset_admission.py` and the mutation matrix in the
  design record §9. *The parity arms pin the gateway code as read at the
  design; the decisive cross-repo control is GW-1's main-side test (a
  named pairing row, not an SDK prerequisite).*
  **Amendment (ADR 0606, gateway issue #606) — admission identity binding
  for ACTIVE host invokes only.** Before it, the identity clause above was
  true of the explicit publisher only in the sense that the id had been
  minted by the host: `dataset_publish` read it from `context.dataset_id`,
  a plain attribute the adapter can rewrite. The clause now claims exactly
  what the arms enforce, and no more:
  1. Both admission paths — the explicit member and the inline admission of
     a dataset-shaped result — read ONE captured value per dispatch: the
     operation id, the minted dataset id, the action id and the input, taken
     before the adapter runs, the input as a private copy. Neither path
     takes what it compares against from the context object or from the
     input object the adapter holds —
     `test_t3_a_rewritten_context_dataset_id_is_refused`,
     `test_fold_f1a_the_inline_result_cannot_move_m10_by_mutating_the_input`,
     `test_fold_f1b_the_inline_result_echoing_the_original_input_stands_under_mutation`,
     `test_fold_f3_an_awkward_value_does_not_move_the_echo_check_on_either_path`.
  2. The capture is a copy the caller cannot reach, and the adapter
     cannot reach through the public services members it is handed (they
     return copies: true by inspection, not by an arm), for an input JSON
     cannot express as well (NaN, Infinity, bytes, a plain object). Reaching
     the controller's internals is outside the guarantee; see "What this
     amendment does NOT claim". The arms cited here pin the caller's object
     and the `dispatch_state` reader. None of them pins that the adapter
     cannot reach the capture. An adapter that reads
     `services._admission._dispatch[<its own operation>].input` holds the
     capture, moves the echo check, and is admitted. There is no capture
     when copying the input raises an Exception (the handler catches
     `Exception`: a `MemoryError` included; a `KeyboardInterrupt` or
     `SystemExit` is not caught), or when the copy is the input itself.
     Admission then refuses with `standalone_dataset_input_absent:` and never
     falls back to the caller's object —
     `test_fold_f3_an_awkward_value_does_not_put_the_explicit_publisher_back_on_the_live_object`,
     `test_fold_f3_an_input_the_host_cannot_copy_refuses_with_a_typed_prefix`,
     `test_fold_f1e_the_dispatch_record_holds_a_copy_the_caller_cannot_reach`,
     `test_fold_f1e_the_record_does_not_hand_out_its_copy_by_reference`,
     `test_fold_w3_a_dict_that_copies_to_itself_leaves_no_capture`.
     The limit is stated by one pin,
     `test_pin_the_documented_limit_code_that_reads_host_internals_moves_the_echo_check`.
     It asserts the admission. It is no evidence of a guarantee.
  3. With no dispatch record for the operation, the inline admission
     refuses with `standalone_dataset_not_dispatched:` before any write —
     `test_fold_f1c_with_no_dispatch_record_the_inline_result_is_refused`.
  4. The context's `operation_id` and `dataset_id` are correlation checks
     against the capture, never authority. A rewritten dataset id, another
     operation's id, an operation never dispatched, a closed invoke, and an
     invoke active on another controller of this process each refuse. One
     operation can no longer take another's mint and deny it its own
     dataset — `test_t3_another_operations_id_is_refused`,
     `test_t3_an_undispatched_operation_is_refused`,
     `test_t3_a_closed_scope_is_refused`,
     `test_t3_a_forged_mint_cannot_deny_its_operation_its_own_dataset`,
     `test_t3_another_controllers_invoke_grants_no_authority_here`.
  5. Every refusal above precedes any admission or index write: the
     this-run registry, the persisted manifests and the library index are
     byte-identical before and after the refused call —
     `test_t4_no_state_on_refusal`, with
     `test_t4_the_snapshot_is_stable_at_rest_and_sees_one_admission` as
     the snapshot's own control. The fold arms that end in a refusal take
     the same snapshot. Where an arm drives a refusal and then a legitimate
     admission, it asserts that the refusal admitted nothing.
  6. The scope is local to its dispatch, not a last-dispatch slot: two
     scopes open on one controller at once each resolve only their own
     mint — `test_t2_overlapping_admission_scopes_each_see_only_their_own_mint`.
     That arm drives the private `_invoke_core` from two tasks, because the
     per-seam mutex serializes public dispatches; it is not a public-seam
     arm.
  7. Revocation. The scope closes on the operation id the host captured
     before the adapter ran, when the adapter span ends — on success, on
     error and on cancellation. A rewrite of `context.operation_id` inside
     `execute` cannot keep the scope open and cannot close another
     operation's scope. A task that inherited the scope is refused
     `standalone_dataset_invoke_closed:` after the invoke closed, also when
     it puts the real id back on the context —
     `test_fold_f2_a_rewritten_operation_id_cannot_keep_the_scope_alive`,
     `test_fold_f2e_a_rewritten_operation_id_cannot_close_another_operation`,
     `test_t3_an_inherited_scope_cannot_borrow_the_active_invoke`.
  8. The binding changes admission only. The per-seam mutex still
     serializes the public invoke and preset-apply paths
     (`test_t1_a_second_public_invoke_waits_for_the_first`, a pin, green
     before the binding: removing the mutex from either path turns it red),
     and the honest publication and the honest result are still admitted
     (`test_t3_the_control_publishes_under_its_own_mint`,
     `test_fold_control_the_repro_arms_keep_their_outcomes`: controls).
  Every test named above is in `tests/server/test_dataset_identity_binding.py`.
  **Compatibility, as the arms enforce it.** A publication from a bare
  worker thread has no dispatch context, so it refuses: while its invoke is
  open it is `standalone_dataset_operation_mismatch:`, because that call is
  not made in the active invoke. `asyncio.to_thread` copies the dispatch
  context into the worker, so a publication through it is the invoke's own.
  No thread support is added —
  `test_pin_publishing_from_a_bare_worker_thread_fails_closed`, a pin that
  is true before and after the fold.
  **What this amendment does NOT claim.** It is not process isolation: the
  binding holds at the services boundary, inside one host process and one
  dispatch context, and does not reach code that bypasses
  `dataset_publish` or reads host internals. Reading host internals is one
  attribute chain: the controller is reachable from the services object the
  adapter is handed, as `services._admission`, and its record holds the
  capture. Python is not a sandbox, and the ADR excludes that reach. The
  dispatch record (`dispatch_state`) is correlation history, never
  authority. That ONE captured object serves the record and the scope is
  true by construction (`record_dispatch` builds it once); no arm can tell
  it from two equal copies, and none claims to. `close_dispatch` is not
  guarded against a different `Context` that holds the same scope: called
  from a child task that inherited the scope, its variable reset raises
  `ValueError`, and by then the scope is already closed and removed. That
  cannot happen on the host path, where the closer runs in the context that
  opened the scope, and no arm tests it. And it is a statement about the
  standalone host alone: it claims nothing about the gateway's publish path
  or its selection policy (gateway issue #608 is the gateway's own record).
  **The record of this binding's own review.** The first version of it
  closed the explicit member and left two paths open, and its wording here
  read as though the inline path were safe. The inline admission ran its
  M10 echo check against the input object the adapter could mutate (F1,
  F3), and the scope's closer read the operation id from the context when
  the span ended, so a rewritten id kept a scope alive and could close
  another operation's (F2). The fold arms above are the proof that both are
  closed. `test_t3_pin_the_inline_result_already_refused_a_rewritten_context`
  pins one thing only: that the inline path admits against the captured
  MINT. It says nothing about the echo check. Arms named `test_pin_...` in
  the module are green before the binding; a pin guards behaviour and is no
  evidence for the binding. Anchors:
  `benchweave_sdk_server/dataset_admission.py` (`record_dispatch`,
  `close_dispatch`, `active_invoke`, `admit_active`, `admit_result`,
  `_admit_captured`), `benchweave_sdk_server/session.py::PluginSession.execute`
  (the adapter span's `finally`),
  `benchweave_sdk_server/seam.py::_invoke_core` (the observe hook, which
  reads each context attribute once, before the adapter runs, and returns
  the closer bound to the operation id it captured).

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
