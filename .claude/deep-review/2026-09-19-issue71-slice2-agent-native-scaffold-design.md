# Design — issue #71 slice 2: the agent-native scaffold

Date: 2026-09-19. Status: design (pre-implementation). Companion to
`.claude/deep-review/2026-09-19-issue71-skill-role-design.md` (the run record:
slice map §0.2, dispositions §9, pointer §12). Slice 1 (registry `skill` role,
PATCH 0.1.1) is accepted as written and parks until #62 lands; this slice stacks
behind it. This record absorbs the former "slice 3" (skill content) per the
team-lead's 2026-09-19 scope: the seeded skills ship WITH their working content,
not as stubs.

Scope items (a)–(g) from the tasking map to sections: (a) §2–§4, (b) §3,
(c) §5, (d) §6, (e) §7, (f) §8, (g) §9.

## 1. Evidence base — what the real code says

Read, not assumed, from the SDK tree (`/Users/seaton/Documents/src/benchweave-sdk`)
and the main tree (`/Users/seaton/Documents/src/BenchWeave`):

- **Scaffold mechanics**: `scaffold.py:387–475` — `create_project` writes a fixed
  `contents` dict of inline string templates; the only parameterization is the
  package name (`TEST`'s `__PLUGIN__` substitution). The `--with-ui` variant is
  the generated-file-set precedent: `cli.py:66–70` calls `create_project` then
  `presentation.create_ui_resources` (`presentation.py:348`), which writes
  `UI-GUIDE.md` at the project root (`presentation.py:392`) — the existing
  precedent for a generated root-level agent-facing document.
- **No golden tree is committed**: `tests/sdk/test_sdk.py:102` asserts structure
  ("builds only in new directory and has tests"); `tests/sdk/test_presentation_cli.py:50–69`
  scaffolds into tmp directories at test time. There is no byte-pinned generated
  project anywhere in either repo today.
- **The wheel boundary is the cataloguing boundary**: the generated
  `pyproject.toml` sets `[tool.hatch.build.targets.wheel] packages =
  ["src/<package>"]` (`scaffold.py:438–439`) — files under `src/<package>/` ship
  in the plugin wheel; project-root files (README, AI-GUIDE, and the future
  CLAUDE.md) never do. The AI-GUIDE already states the rule: "Keep distributable
  resources inside src/<package>/ for inclusion in the wheel" (`scaffold.py:442`).
- **The scaffold emits no release-manifest surface today**: the file set is
  pyproject/README/AI-GUIDE/src-files/tests; the README instructs "Prepare the
  registry manifest" at release time (`scaffold.py:283–287`); `cli.py`'s
  `inventory` says "not a release manifest" (`cli.py:98`); `packaging.py:31`:
  "the caller assigns registry file roles."
- **No MCP machinery in the SDK** (`pyproject.toml` dependencies:
  click/jsonschema/referencing/rfc3339-validator/rfc3987/rich/textual). The
  gateway serves MCP (interface standard `mcp-tools.json`, `stg_v1_*` tools).
  The adapter is host-served over the five-method HostServices contract —
  `transfer(transaction, context)`, `monotonic()`, `utc_now()`,
  `close_transport(context)`, `record_evidence(entry, context)` — whose
  executable specification is `testing.py`'s `MockHost`/`MockContext`
  (`testing.py:18–106`), including the dispatch-marker-before-transmit and
  deadline/cancellation disciplines.
- **The full descriptor authoring surface** (from the vendored
  `otdp/0.2.0/otdp-device-descriptor.schema.json` `$defs`): enumerated in §4 —
  this is the corpus-derived question set the elicitation workflow uses.

## 2. (a) The seeded skills tree

Always-on inside `create_project`'s `contents` (no flag; every project gets it —
the fork settlement):

```
<project>/
  CLAUDE.md                                   # §3
  src/<package>/skills/
    develop-plugin/SKILL.md                   # the plugin-developer skill (§2.1)
    drive-device/SKILL.md                     # the device skill, seeded (§2.2)
```

Skills live under `src/<package>/` so they ship in the wheel and the release
bundle and are catalogued under the slice-1 `skill` role; harness-side
auto-discovery stays a client concern (the issue's boundary). Frontmatter is the
cross-harness convention the issue names — `name:` + `description:` — with
`name` parameterized by the package (`<package>-plugin-development`,
`<package>-device-operation`) so skills from multiple plugins cannot collide in
one harness skill directory.

### 2.1 `develop-plugin` — the plugin-developer skill

Five sections, refactoring and deepening the AI-GUIDE's five prompts
(`scaffold.py:247–287`) into skill form:

1. **Elicitation** — "ask all the right questions" before generating or wiring
   anything; the question set is §4's table, keyed to real authoring surfaces.
2. **Firmware development** — vendor source/checksum references and upgrade
   constraints under `firmware/` (the conventions the AI-GUIDE already names,
   `scaffold.py:236–239`), the `listed` vs `commissioning_required` decision,
   and the boundary: the SDK does no firmware discovery or flashing.
3. **Adapter creation** — implement `protocol.py`/`adapter.py` against the real
   Adapter surface (`open(descriptor, services, context)`, `execute(request,
   context)`, `next_event`, `close`), keep `create_plugin` no-argument, open free
   of device I/O, dispatch before transmit, honour monotonic deadlines and
   cancellation, preserve uncertain outcomes, relative/stdlib-only imports for
   the gateway loader — i.e. the AI-GUIDE prompt-2 discipline, with the
   MockHost exchanges as the reference test pattern.
4. **Standalone MCP** — §7's shape-(a) workflow.
5. **Release** — §6's manifest-entry mechanics.

### 2.2 `drive-device` — the device skill, seeded honest

Documents driving the synthetic demo (identify/read against the mock exchanges)
and states plainly that it is the template to rewrite for the real device — the
same honesty pattern as the synthetic `adapter.py`/`protocol.py` the author is
meant to replace. The motivating real-world case (a capture/decode bench device)
is represented in §4's channels/capture questions; no real device is named in
any generated content.

## 3. (b) CLAUDE.md at the plugin repo root

- **Content sources**: the scaffold's own facts — project purpose line, the
  check/build commands (`pytest`; `benchweave-sdk check` on the descriptor;
  `uv build`; `uv lock`), pointers to AI-GUIDE.md (the build-out prompts) and
  `src/<package>/skills/` (the seeded skills), and the safety rails the
  AI-GUIDE states (no hardware contact, flashing, energising outputs, or
  publication without owner review). Nothing invented; every claim is a fact of
  the generated project.
- **Static vs parameterized**: parameterized like `TEST` — `__PLUGIN__`
  substitution for the package name and the skill paths; everything else
  static. Generated by `create_project`, byte-stable, pinned by tests.
- **Cataloguing — recommendation: uncatalogued dev tooling by default.** The
  mechanical evidence: root-level files never enter the wheel
  (`packages = ["src/<package>"]`), so CLAUDE.md reaches a release payload only
  if the publisher's bundle step explicitly includes repo-root files. If a
  publisher ships it, slice 1's spec §4 text assigns it `documentation` — not
  `skill`, which the issue defines by the SKILL.md frontmatter format. The
  scaffold encodes the answer structurally: skills are distributable artifacts
  (inside the package); CLAUDE.md is developer tooling (root). The
  plugin-developer skill's release section says both sentences.
- **AI-GUIDE layout paragraph** (`scaffold.py:219–232`) updates in the same
  change to name CLAUDE.md and the skills tree (drift obligation 2).

## 4. The elicitation questions — enumerated from the corpus

Source: `otdp/0.2.0/otdp-device-descriptor.schema.json` (`properties` + `$defs`),
`device-profile-catalog.json`, `registry/0.1.1/release-manifest.schema.json`
(post-slice-1). Every question maps to a field that exists; the table is the
reviewable contract for "all the right questions" and the derivation source for
the §8 content test.

| Cluster | Questions (the skill asks) | Real surface |
|---|---|---|
| Device identity | Manufacturer and exact model? Aliases? Identity strategy — `scpi_idn` / `uart_identity` / `commissioned` / `adapter`? Firmware policy `listed` (which versions?) or `commissioning_required`? | `$defs.identity` |
| Transport | Which of the nine transports — `serial`, `uart_scpi`, `uart_json`, `lan_scpi`, `usbtmc`, `can`, `i2c`, `spi`, `custom`? Connection key? The type's settings (e.g. serial: `baud/data_bits/parity/stop_bits/rtscts/max_frame_bytes`; lan_scpi: `port/protocol/read_termination/write_termination/max_response_bytes`; can: `receive_id/fd/extended/payload_length`; i2c: `address`; spi: `mode/speed_hz/bits_per_word`; usbtmc: `vid/pid`)? | `$defs.*Transport` variants |
| Class & profiles | Which OTDP class(es) — the twelve in `device-profile-catalog.json`? Profile ids to declare in `profiles[]`? Action contracts to adopt? | catalog + descriptor `profiles`/`actions` |
| Operations | Which of the ten verbs — `identify`, `read`, `write`, `invoke`, `capture`, `reset`, `self_test`, `get_errors`, `stream_subscribe`, `stream_unsubscribe`? `capabilities` and `operations` must match (S01). Per verb: `timeout_ms`, `side_effect` (`none`/`state_change`), `retry` (`never`/`idempotent`), `cancellable`, `completion` (`dispatched`/`acknowledged`/`readback`/`physical`)? | `properties.operations` slots + `$defs.operationPolicy` |
| Parameters | Name/type (`float`/`int`/`bool`/`enum`/`string`)/access (`ro`/`wo`/`rw`)/semantic (`measurement`/`setpoint`/`state`/`configuration`)/unit? Range or enum values? String constraints? `hazard_class` (`unknown`/`none`/`low`/`high`)? `read_policy` (`max_age_ms`, `destructive`), `write_policy` (completion, effect, retry, tolerances, settling)? Binding kind? Unique names (S01), unreversed bounds (S02)? | `$defs.parameter` |
| Capture & streams (the capture/decode case) | Channels — `id`/`label`/`role`/`quantities`/`parameter_names`? Capture formats and limits? Stream limits? | `properties.channels`, `capture_formats`, `capture_limits`, `stream_limits` |
| Diagnostics | Self-test and error-reporting surface? | `properties.diagnostics`, verbs `self_test`/`get_errors` |
| Adapter | Entry point? API version? Dependencies? Permissions (e.g. `scoped_transport`)? | `$defs.adapter` |
| Evidence & provenance | Command sources (`provenance.sources[]` title/reference/revision)? Test vectors? Evidence level per report — `structural`/`simulated`/`hardware`? | descriptor `provenance`; manifest `evidence[].level` |
| Release | Package kind (`profile`/`descriptor`/`implementation`)? Implementation-kind payload must contain `implementation`+`sbom`+`build_provenance`+`dependency_lock`; skills under `skill`; permissions list? | manifest kind conditionals + role enum |
| Safety boundary | What must never be done without separate authority? | AI-GUIDE rails, carried forward |

## 5. (c) D4's ROLE_BY_SUFFIX + fixture skill file

Lands in slice 1 as accepted (`ROLE_BY_SUFFIX["SKILL.md"] = "skill"` +
`["CLAUDE.md"] = "documentation"`; the fixture lattice gains a skill member and
regenerates in slice 1's sweep — main record §1.3). Slice 2 adds nothing
registry-side. One coupling note: the fixture's SKILL.md content is invented
fixture content and stays decoupled from the scaffold template — the fixture
proves the ROLE (admission path), the template proves the SEEDING (generation
path); sharing bytes would couple two proofs to one edit.

## 6. (d) D3's manifest-entry mechanics — the honest shape

**The scaffold emits no manifest surface, and this slice keeps it that way.**
Evidence: the manifest is a release-time publisher record over the BUILT bundle
(payload archive digest, per-file digests of the unpacked payload, evidence,
ownership) — a repo-resident skeleton with zero hashes would be noise the
corpus's own labelled fixture already plays better, and a stale one is worse
than none. The scaffold's job is to make role assignment KNOWABLE at release
time, which this slice does with three generated-content facts:

1. `benchweave-sdk inventory` already emits the path/bytes/sha256 rows
   (`packaging.py` deliberately leaves roles to the caller).
2. The `develop-plugin` release section carries the file→role table for every
   generated file: skills → `skill`; descriptor/protocol/vectors/README → their
   roles per spec §4; CLAUDE.md → `documentation` if shipped, dev tooling
   otherwise; the implementation-kind quartet reminder.
3. The AI-GUIDE release prompt (§5 of the generated guide) already instructs
   preparing "the registry manifest, exact payload inventory/hashes, dependency
   locks, licence, provenance" — it gains the skill-role sentence.

If measurement later shows authors hand-writing the same manifest scaffolding
repeatedly, that is D5's trigger (the check-manifest lane), not a template file.

## 7. (e) Standalone-MCP fork — recommendation: shape (a), workflow-only

- **What the code supports today**: nothing SDK-side (no MCP dependency, no
  server, no template — §1). The gateway's MCP surface (interface standard)
  serves gateway-hosted tools; a standalone server is a different artifact.
- **Shape (a) — the skill workflow (THIS slice)**: the `develop-plugin`
  standalone-MCP section guides an agent to write a project-local MCP server:
  construct the adapter via `create_plugin()`, implement the five-method
  HostServices contract over a real transport (settings from the descriptor),
  expose the descriptor's verbs as MCP tools, keep the dispatch/deadline/
  uncertain-outcome disciplines. Cost: template prose only; zero new SDK
  machinery; zero new generated-runtime dependencies; matches the issue's
  client-side boundary. The plugin becomes usable standalone because an agent
  can BUILD the wrapper, not because we shipped one.
- **Shape (b) — machinery (held, with trigger)**: a generated `mcp_server.py`
  template and/or SDK reference host forces an MCP-library dependency decision
  onto every generated project, widens SRF-1, and needs its own check/preview
  story. Trigger to revisit: a real plugin project ships a hand-written
  standalone MCP server and its maintenance burden is measured against a
  template. Not this run.

## 8. (f) Golden regeneration and proving tests

**The file-set pin becomes the SRF-1 contract** (no byte-golden tree exists
today — §1; committing a full generated tree as goldens would double-maintain
every template). New main-side behavioral module `tests/sdk/test_scaffold_skills.py`
plus a content module, all RED on a pre-slice checkout:

- `test_new_seeds_skills_and_claude_md` — `create_project(tmp, "lumen_probe")`;
  assert `CLAUDE.md` at root and both SKILL.md paths. RED (absent) → GREEN.
- `test_scaffold_file_set_pinned` — generated project's sorted relative file
  set == the pinned list (the interface contract; future additions must edit
  the pin deliberately).
- `test_seeded_files_byte_stable` — regenerate into a second tmp dir; the new
  files' bytes are identical (template determinism).
- `test_seeded_skill_frontmatter_present` — each SKILL.md's leading block has
  `name:`/`description:` lines and the parameterized names carry the package
  (an OUTPUT pin on our own bytes; not a format rule — D2 stays deferred).
- `test_claude_md_references_real_commands` — names `pytest`, `uv build`,
  `benchweave-sdk check`, AI-GUIDE.md, and the skills paths as generated.
- `test_ai_guide_names_seeded_files` — the AI-GUIDE layout paragraph mentions
  CLAUDE.md and `skills/` (the obligation-2 pin).

**`tests/sdk/test_plugin_developer_skill_content.py`** (the honest measurement):

- `test_elicitation_covers_real_authoring_surfaces` — derive the expected terms
  FROM THE VENDORED SCHEMA at test time: the ten verb slots from
  `properties.operations.properties`; operationPolicy/parameter/identity/adapter
  field names from `$defs`; every transport variant's settings keys; the
  manifest role enum (incl. `skill`) and evidence-level enum from the vendored
  registry schema; the twelve class ids from `device-profile-catalog.json`.
  Assert each appears in the generated `develop-plugin/SKILL.md`. Deleting any
  real question → RED. **KILL the instrument** if the expected set must be
  hard-coded rather than derived (it would then pin prose, not the standard).
- `test_skill_states_safety_boundary` — both seeded skills carry the
  no-hardware/no-publication rails.
- Honest limit, unchanged: the invention direction (the skill naming fields
  that do not exist) is review-covered — parsing skill prose would standardise
  the format D2 defers. §4's table is the review checklist.

**Pre-committed acceptance rule.** SHIP iff: (1) all §8 tests RED on a
pre-slice checkout for absence reasons (files missing / terms missing against
the derived set) and GREEN after; (2) SDK CI and main `tests/sdk` green at the
stack tip; (3) a fresh `create_project` + `benchweave-sdk inventory` run lists
the seeded skill files; (4) no pre-existing generated file changed bytes except
the AI-GUIDE layout paragraph. KILL if: the content test needs a hard-coded
term set; the file-set pin cannot be satisfied additively (renames/removals —
an interface break beyond this design: escalate); any pre-existing file beyond
AI-GUIDE must change (R7). UNDERPOWERED if: the RED run shows only the
frontmatter/file-presence tests failing while the content test "passes" pre-slice
— that means the derivation is not exercising the schema (e.g. empty expected
set); require a non-empty derived set assertion in the RED evidence.

## 9. (g) SDK version — this slice carries the bump

The scaffold's output change IS the SRF-1 interface change, and the generated
test extra pins `benchweave-sdk=={__version__}` (`scaffold.py:437`) — the
version is the anchor downstream plugin repositories cite and diff against.
Assessment against the minimum-bumps directive: **one bump, 0.0.2 → 0.0.3, at
this slice's release commit** — the first output-changing merge is the honest
version boundary ("≥0.0.3 scaffolds skills"); slice 1 explicitly does not bump
(accepted, f5e05fa precedent); the docs slice rides 0.0.3; the D5/D6 slices
re-assess when their designs land. Alternative (single bump at run close) keeps
one bump but makes every intermediate merge of this slice ship under a version
whose meaning is ambiguous — not recommended. Flagged as the maintainer's call
with the release manager.

## 10. Landing, invariants, risks

- **Landing**: stacks on slice-1 SDK main (which itself parks until #62 lands —
  main record §6). SDK branch `feat/issue71-scaffold-skills`: one RED→GREEN
  commit per slice-2 unit (scaffold seeding; content; AI-GUIDE/docs-site
  content), SDK PR, one final main pointer + merge-result gate. The PR states
  the SRF-1 shape change and the file-set pin as the new contract.
- **Invariants**: SRF-1 TOUCHED (additive-only; file-set pin; the generated
  runtime keeps no SDK dependency — markdown only). PKG-1/2 unchanged (inline
  templates, no new deps — MCP shape (a) chosen partly for this). STD-4
  unchanged (no new refusal paths). TWO-1 (push before pointer). Obligations
  1–2 (README five-steps + user guide name the seeded skills — the docs slice).
- **Risks**: R7 scaffold blast radius (mitigation: additive-only + file-set
  pin; falsifier: any pre-existing file changing beyond the AI-GUIDE
  paragraph). R8 content invention (review-covered via §4; test covers
  omissions). R10 template non-determinism (byte-stable test). R11 the seeded
  device skill is mistaken for device qualification (mitigation: the honesty
  text in the skill itself, mirroring the synthetic adapter's labelling).
  R12 MCP shape drift (a client harness changes the skills convention — the
  frontmatter is deliberately the lowest common denominator; format
  standardisation remains D2).

---

**Addendum, 2026-09-20 (build time).** The stacking precondition recorded
above is satisfied: slice 1 landed via gateway PR #104 (merge 32db276,
issue #71 auto-closed) and SDK PR #31 (merge 41c7cc8) — registry 0.1.1
with the `skill` role is merged on both mains, and the
`ROLE_BY_SUFFIX`/fixture skill member landed with it (§5's coupling note
is therefore already resolved). This branch builds from the merged mains
(origin/main has since advanced with docs-only commits: the deferral-rule
port PR #30 on the SDK side and changelog regeneration on the gateway
side). The body above is otherwise untouched.
