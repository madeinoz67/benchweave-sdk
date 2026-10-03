# WS2 design — copier-backed `new` with updatable scaffolds (issue #347, increment 3)

Status: DESIGN, builder-ready. Tracking: madeinoz67/benchweave#347 (WS2). Ruled upstream by the
principal: copier 9.18.2, `template/` in this repo tagged with SDK releases (template version ==
SDK version), a `[scaffold]` extra, `upgrade` + `adopt` commands, managed-vs-owned file split.

Everything marked SPIKE below was executed against copier 9.18.2 on 2026-10-03 in throwaway
scratch (not committed); the builder re-proves the same facts as the first RED/GREEN arms.

---

## 1. Premise, verified against the code

`new` today (`src/benchweave_sdk/cli.py::new_command`) calls
`scaffold.create_project(destination, package)` (`src/benchweave_sdk/scaffold.py`, string
constants `ADAPTER`/`PROTOCOL`/`TEST`/`AI_GUIDE`/`CLAUDE_MD`/`DEVELOP_SKILL`/`DRIVE_SKILL` plus
f-string pyproject and `json.dumps` descriptor/vectors), then optionally
`presentation.create_ui_resources` for `--with-ui`. Two facts drive the design:

1. **No provenance.** The generated project records nothing about which SDK version produced it
   (WS2 audit, issue #347). A scaffold made at release N cannot be moved to N+1 mechanically.
2. **`--with-ui` is derived, not templated.** `create_ui_resources` (`presentation.py`) reads the
   rendered `descriptor.json` back, hashes its exact bytes, derives targets from the descriptor,
   stamps `active_version("plugin-ui")`, and decides at runtime whether a numeric observation
   target exists (plot example or disclosed absence). This cannot become Jinja without inventing
   hashing in templates — and must not: it stays SDK code.

### Spike results (copier 9.18.2, all reproduced in scratch)

| Question | Result |
|---|---|
| `copier copy` from a **non-git** directory (the wheel shape)? | Works, offline, no fetch. |
| Does copy write `.copier-answers.yml`? | **Only if the template ships a `.copier-answers.yml.jinja`** (we render `_copier_answers`). Without it, no provenance is written at all — a required template member, not optional. |
| Copy from local template, answers pinned to a **canonical repo path + tag name** as `_commit`? | Works: post-copy rewrite of `_src_path`/`_commit` (2 lines, deterministic); `copier update` resolved `_commit: v1` (a **tag**, not a SHA) and 3-way merged to v2. |
| Managed file (not in `_skip_if_exists`), author untouched, changed in template? | Updated to new bytes. |
| Owned file (`_skip_if_exists`), author-edited, **also changed in template**? | Untouched — author bytes preserved, no conflict. |
| `_skip_if_exists: src/*` glob against nested `src/pkg/adapter.py`? | Matches (fnmatch-style, crosses `/`). |
| Answers file after update? | Copier-maintained: `_commit` advanced, canonical `_src_path` preserved. |
| Author-modified **managed** file + update? | Real conflict markers (`<<<<<<< before updating` … `>>>>>>> after updating`) written into the file — loud, resolvable, no silent loss. |
| Dirty destination tree + update? | Copier refuses ("Destination repository is dirty"). |
| `--trust`/`--UNSAFE` needed? | No — the template carries **no `_tasks`/`_migrations`**, which stay banned by design. |
| `--no-input` flag? | Does not exist in 9.x — use `--defaults`. |

`copier update` requires the destination to be a **git repository with a clean committed tree**;
that constraint is inherent to the 3-way merge and becomes `upgrade`'s documented precondition.

---

## 2. The mechanism

### 2.1 Template tree (new, in this repo)

```
copier.yml                      # template config; lives at repo ROOT because copier looks there
template/                       # `_subdirectory: template`
  .copier-answers.yml.jinja     # {{ _copier_answers|to_nice_yaml }}  — provenance is template content
  AI-GUIDE.md                   # managed (no tokens; verbatim)
  pyproject.toml.jinja          # owned seed ({{ package_name }}, {{ sdk_version }})
  README.md.jinja               # owned seed
  CLAUDE.md.jinja               # owned seed
  tests/test_plugin.py.jinja    # owned seed
  src/{{ package_name }}/
    __init__.py.jinja           # owned seed
    adapter.py.jinja            # owned seed (the synthetic placeholder to rewrite)
    protocol.py.jinja           # owned seed
    descriptor.json.jinja       # owned seed ({{ otdp_version }}, {{ package_name }})
    protocol.md                 # owned seed (no tokens)
    vectors.json                # owned seed (no tokens)
    skills/develop-plugin/SKILL.md.jinja   # owned seed
    skills/drive-device/SKILL.md.jinja     # owned seed
```

`copier.yml` (root) essentials:

```yaml
package_name: {type: str, default: example_plugin}
with_ui: {type: bool, default: false}     # recorded for provenance; UI files are post-render
sdk_version: {type: str}                  # injected by new(): benchweave_sdk.__version__
otdp_version: {type: str}                 # injected by new(): served.active_version("otdp")
_subdirectory: template
_skip_if_exists: [pyproject.toml, README.md, CLAUDE.md, tests/*, src/*]
# No update scripts of any kind ship here: copier gates template scripts behind
# --trust/--UNSAFE, and this scaffold never requires them.
```

The `.jinja` suffix keeps ruff/mypy away without exclusion lists (no `*.py` files in the tree).

### 2.2 Managed vs owned (the split, as a concrete tree)

**SDK-managed** (replaced on update when the author has not modified them; author-modified ⇒
conflict markers, never silent loss):

- `AI-GUIDE.md` — SDK guidance whose improvements must reach existing projects.
- `.copier-answers.yml` — provenance; copier-maintained after the first update.

**Author-owned** (`_skip_if_exists`: never touched by update, whether edited or not; fresh
projects still receive current seeds):

- `pyproject.toml` (authors bump versions/deps — the `benchweave-sdk==N` pin is theirs to move),
  `README.md`, `CLAUDE.md` (agent notes), `tests/*`, everything under `src/<pkg>/` — adapter,
  protocol, descriptor, evidence, skills. The synthetic seeds exist to be rewritten for a real
  device; an update that pushed template bytes back over real device code would be actively
  harmful. **Template fixes to seeds reach new projects only; that is the intended semantics.**
- `--with-ui` output (`UI-GUIDE.md`, `presentation.json`, `binding-catalogue.json`,
  `ui/manifest.json`, `ui/fixtures/*`, the generated conformance test) — derived from the
  descriptor's exact bytes and therefore author-maintained by construction (the guide already
  instructs authors to keep hashes aligned after descriptor edits).

New files the template adds at N+1 land on update (they match no skip pattern); the acceptance
test pins the exact expected set so additions are deliberate.

### 2.3 `new` — copier front door, core wheel deps unchanged (PKG-2)

`scaffold.create_project(destination, package)` keeps its name, signature, and contract; the
implementation becomes:

1. Package-name guard — unchanged (`RESERVED_PACKAGE_NAMES`, regex, keyword check).
2. Locate the packaged template: `importlib.resources` on `benchweave_sdk/scaffold_template`
   (wheel force-include, §4), `as_file()` for zip safety.
3. Lazy `from copier import run_copy` inside the function. Absent extra ⇒
   `scaffold_extra_absent: project scaffolding needs the optional extra
   (pip install benchweave-sdk[scaffold])` — the `signing_extra_absent` precedent
   (`publishing.py::sign_manifest_bytes`, lazy import, refusal names the install command).
4. Pre-checks on destination/staging names (existing FileExistsError contracts, the dangling
   symlink case, the leftover-`.partial` refusal) — unchanged, run before copier so copier's
   own existing-directory behavior never becomes the surface.
5. `run_copy(src_path=<packaged template>, dst_path=<staging sibling>, data={
   package_name, with_ui, sdk_version: __version__, otdp_version: active_version("otdp")},
   defaults=True)` — non-interactive, offline, no AI or TTY in the loop.
6. **Post-render answers pin** (the one hand-authored moment): rewrite `_src_path` to
   `https://github.com/madeinoz67/benchweave-sdk` and set `_commit: v{__version__}` in the
   freshly rendered `.copier-answers.yml`. Two line-level rewrites on a file whose shape we
   just produced — no YAML dependency, no silent substitution. This is what makes a
   wheel-rendered project updatable against the tagged repo later.
7. Read back and `validate_descriptor` the rendered `descriptor.json` — the generate-time
   validation contract of today's `descriptor_for` moves to a post-render check, so a template
   edit that would generate an invalid descriptor fails before the rename.
8. Atomic rename staging → destination (unchanged; interrupted runs still leave nothing).
9. `--with-ui`: `create_ui_resources` runs after the rename, byte-identical behavior —
   **`presentation.py` is untouched.**

`with_ui` is recorded in the answers for provenance only; the template has no conditional files
in this slice.

### 2.4 `upgrade` — wraps `copier update`

`benchweave-sdk upgrade [DIRECTORY]` (default `.`):

- Refusals (snake_case prefixes, per STD-4 discipline): `upgrade_answers_missing:` (point at
  `adopt`), `upgrade_requires_git:` (init+commit instructions — `new` does not git-init in this
  slice), `upgrade_dirty_tree:` (commit or stash, checked by us so the message is ours, though
  copier refuses on its own too — belt and braces).
- Runs `run_update(dst, defaults=True, vcs_ref=f"v{__version__}")` — the **installed** SDK's
  version names the target template tag (template version == SDK version), so a wheel never
  pushes unreleased template state from `main`.
- Network: fetching the tagged template from the canonical repo is inherent to update and
  disclosed in the command help. A missing tag (dev install, unreleased version) fails loudly
  with "released templates only".
- Copier's exit status is read directly (no pipes in the wrapper's evidence path); on conflict
  markers the message names the marker lines and tells the author to resolve and commit.

### 2.5 `adopt` — provenance for pre-copier projects

`benchweave-sdk adopt [DIRECTORY] [--package NAME] [--scaffolded-at VERSION]`:

- Refuses if `.copier-answers.yml` already exists (`adopt_answers_present:`).
- Package inferred from the generated `pyproject.toml` (`packages = ["src/<pkg>"]` — the shape
  we generate); `--package` overrides; unresolvable ⇒ refuse.
- `--scaffolded-at` inferred from the generated test-extra pin (`benchweave-sdk==X` in
  `[project.optional-dependencies]`); unparseable or absent ⇒ refuse — an unknown base is never
  claimed silently. `--scaffolded-at` overrides for projects whose pin the author already moved.
- `with_ui` inferred from `UI-GUIDE.md` presence.
- Writes the same answers shape `new` writes: canonical `_src_path`, `_commit: vX`.
- Honesty: `adopt` claims "this tree equals template@vX render plus author edits". That claim is
  sound **because** the parity gate (R-2) proves template@N render == the string-constant
  output at the cutover release, and both were byte-stable before it. When the claim is wrong
  (older tree shapes), the failure direction is the safe one, verified in the spike: deltas are
  attributed to the author and preserved; managed updates may conflict loudly; nothing is lost.

---

## 3. Minimal FIRST slice, and the deferrals

**In (one PR, SDK repo only):** the template tree + root `copier.yml`; `create_project` ported
to the render path with answers pin and post-render descriptor validation; `[scaffold]` extra
(`copier>=9.18,<10`); `upgrade` and `adopt`; wheel/sdist packaging of the template +
`hatch_build.py` presence check; tests (§6); docs (README five-steps install line,
`user_guide/plugin-sdk.qmd`, this repo's CLAUDE.md usage pointer); `docs/internal/invariants.md`
PKG-2/SRF-1 amendments; `docs/internal/drift-and-obligations.md` CI-map row.

**Deferred, each with its home:**

1. Template-borne update scripts (`_tasks`/`_migrations`) — permanent non-goal (copier gates
   them behind `--trust`; the scaffold must never require trust). Home: this record §2.1; a
   future design pass would have to justify breaking it.
2. UI derived resources as template content / `UI-GUIDE.md` becoming managed — home: follow-up
   sub-issue under #347 if wanted after WS2 lands.
3. `upgrade --to <ref>` (pre-release channels, targeted downgrades) — home: follow-up under #347.
4. `new` convenience `git init` — home: follow-up under #347; `upgrade`'s pre-check covers the
   need loudly meanwhile.
5. Parent-repo (plugin-collection) update semantics — documented constraint on `upgrade`; home:
   follow-up under #347 if collections-in-one-repo is a real pattern.
6. Adopt-backreach for tree shapes older than the parity back-check window — disclosed
   limitation in `adopt` docs (safe failure direction), no code.

---

## 4. Invariant impacts

- **PKG-2 — AMENDED.** The wheel gains one more force-included data tree alongside
  `standards-lock.json`: `copier.yml` → `benchweave_sdk/scaffold_template/copier.yml` and
  `template/` → `benchweave_sdk/scaffold_template/template/`; sdist include adds `/copier.yml`,
  `/template`. Everything else in PKG-2 stands (`.claude/` etc. still in neither artifact —
  the template tree contains none of them). `hatch_build.py::CustomBuildHook.initialize` gains
  a presence check: packaging without the template root fails the build.
- **PKG-1 — held.** `new` renders from the packaged template via a filesystem path only; no
  parent-repo or network reach (local-template copy performs no fetch — spike-verified shape).
  `upgrade`'s network fetch names the canonical SDK repo, not any local checkout.
- **SRF-1 — AMENDED (interface change, stated in the PR).** The generated tree gains exactly one
  file, `.copier-answers.yml`, at the project root — outside `src/<pkg>/`, so it never enters a
  plugin wheel and the generated runtime keeps zero SDK dependency. Downstream repos diffing
  generated output see one added file and otherwise byte-identical content (R-2 enforces it).
  The AI-GUIDE/test-extra-pin clauses of SRF-1 are unchanged in substance; their carrier moves
  from string constants to template files.
- **TWO-1 — held, with a named pairing.** This slice lands SDK-side only. When the gateway's
  `packages/sdk` pointer later advances, the gateway's scaffold-content pins
  (`tests/sdk/test_plugin_developer_skill_content.py`, `tests/sdk/test_scaffold_skills.py`,
  `tests/sdk/test_presentation_cli.py`) run against the new code — they double as an
  independent parity check and must stay green with only the answers file added to any
  full-tree expectations. The pointer PR runs the gateway suite; no gateway bytes move first.
- **STD-4 — extended by discipline.** New refusal prefixes join the machine-matchable surface:
  `scaffold_extra_absent:`, `upgrade_answers_missing:`, `upgrade_requires_git:`,
  `upgrade_dirty_tree:`, `adopt_answers_present:`, `adopt_provenance_unknown:` (pinned by
  tests; the prefix list in invariants.md gains them).
- **No vendored standards bytes move.** The template stamps `otdp_version` from the served lock
  at render time exactly as `descriptor_for` does today; `standards/` and `standards-lock.json`
  are untouched (the standing tripwire stays green).
- **Surfaces that must move:** SDK README + `user_guide/plugin-sdk.qmd` (new/upgrade/adopt +
  `[scaffold]` install), `docs/internal/invariants.md` (PKG-2, SRF-1, prefix list),
  `docs/internal/drift-and-obligations.md` (CI map), website "five steps" copy if it names the
  bare install. MCP/REST/openapi: not applicable — SDK surface only.

**On-disk format/schema involved:** yes — the generated project tree (an interface per SRF-1)
and the `.copier-answers.yml` file format (keys: `_src_path`, `_commit`, `package_name`,
`with_ui`, `sdk_version`, `otdp_version`). This is part of why the slice is Tier 3.

**CI cost:** `sdk` job syncs `--extra scaffold` and grows one test module (throwaway-git-repo
update test, ~seconds — tiny repos); per-push R-4 uses the CI checkout's own git history
(offline); per-release smoke against real tags rides the existing publish/release flow
(network, one run per release). No new job lanes.

---

## 5. Precedent

- Optional-extra capability with loud absence: `[signing]` +
  `signing_extra_absent:` (`publishing.py::sign_manifest_bytes`, `pyproject.toml` comment) —
  `[scaffold]` copies the shape exactly.
- Packaged data in the wheel behind force-include: `standards-lock.json` →
  `benchweave_sdk/standards-lock.json` (PKG-2) — the template tree rides the same mechanism.
- Atomic staging + rename + refusal contracts: `scaffold.create_project` today — kept verbatim.
- Refusal-prefix discipline: STD-4 — the five new prefixes follow it.
- Byte-parity gates across surfaces: the UI==REST parity and byte-stability precedents — R-2 is
  the same shape (render vs committed fixture; plus the gateway content pins as the independent
  cross-repo check at pointer advance).

Nothing here invents architecture: copier is the third-party mechanism the principal ruled in;
the SDK contribution is the packaging seam, the answers pin, and the guard rails.

---

## 6. Measurable proof and the PRE-COMMITTED acceptance rule

### R-2 (port parity) — every commit

Test renders the packaged template with fixed data and diffs the whole tree against a committed
fixture (`tests/fixtures/scaffold_expected/`, both `with_ui` arms: base tree from the render,
UI files from `create_ui_resources`). Must be **byte-identical** to the pre-change
`create_project`/`create_ui_resources` output plus exactly one new file,
`.copier-answers.yml`. One-time back-check at cutover: the fixture equals the output of the
last pre-copier release (this is what makes `adopt --scaffolded-at` honest, §2.5).

### R-4 (the update promise) — pre-committed BEFORE any run

Protocol: scaffold project P from template@BASE (per push: BASE = `HEAD~1` of this repo's own
CI checkout, offline; per release: real tag v(N−1) against the canonical GitHub URL, in the
release smoke). Author then edits three owned files (appends lines to `README.md`,
`CLAUDE.md`, `src/<pkg>/adapter.py`), `git init` + commit. Between BASE and HEAD the template
changes one managed file (`AI-GUIDE.md`) and, when the per-push lane has a real template delta,
an owned seed too. Then `benchweave-sdk upgrade` (release lane) / `run_update` with
`vcs_ref=HEAD` (push lane). Assertions:

- **A1 managed:** `AI-GUIDE.md` == template@HEAD render, byte-equal (equality, not
  "changed", so a no-delta push still asserts meaningfully).
- **A2 owned:** every `_skip_if_exists` file byte-identical to the author state (`git diff`
  shows only the author's lines — even for seeds the template also changed).
- **A3 provenance:** answers `_commit` == target ref; `_src_path` canonical.
- **A4 health:** `benchweave-sdk check P/src/<pkg>/descriptor.json` exits 0 in the same env.
- **A5 no strays:** clean `git status` post-update; no `<<<<<<<` markers anywhere; the file set
  equals expected exactly.

Sample: the full generated file set (exhaustive byte assertion, not a sample), both `with_ui`
arms, one cycle per push and per release pair.

**Ships iff** A1–A5 hold in both arms.
**Killed if** any owned file differs by one byte from the author state, a managed file misses
its update, markers appear, or `check` regresses — fix the mechanism; never weaken an assertion.
**Inconclusive, not pass:** if the update lane cannot run (copier error, git absent, tag
missing), the run is held — a green result with the update step skipped is a failed run.
**RED controls (must be demonstrated in the PR):** (i) delete `_skip_if_exists` from the test's
copier.yml ⇒ A2 fails (owned clobbered); (ii) drop the answers pin from `new` ⇒ update cannot
resolve the base ⇒ R-4 red. A test that cannot fail these two ways is not the proof.

---

## 7. Review tier and the Step-1 keyword scan

**Tier 3** (this repo's rubric, three independent triggers): touches `scaffold.py` output
shape; adds a dependency (`pyproject.toml` — the `[scaffold]` extra); touches `hatch_build.py`.
G6 second adversarial reviewer mandatory; per the standing retro rule, two independent
adversary lanes.

**Keyword scan (#254 discipline) over the expected diff text** (docs and code: template files,
copier.yml, scaffold.py, cli.py, pyproject.toml, hatch_build.py, tests, the four docs files) —
the eight gateway keywords: `threading` 0, `asyncio` 0, `subprocess` 0 (copier is invoked via
its Python API; no shell-outs are added), `sha256` 0, `hashlib` 0, `migrate` 0 (the copier.yml
comment says "update scripts", not the keyword), `recovery` 0, `protection` 0. Tier 3 stands on
the path rules alone; the keyword lane adds nothing — recorded so the review re-derives it.

---

## 8. Top risks, each with its falsifier

1. **Jinja/whitespace drift breaks byte-parity** (json.dumps indent=2, f-string seams,
   trailing newlines). Falsifier: R-2 red during the port. If a file cannot be made
   byte-exact, that file's generation stays in SDK code (create_ui_resources already does) —
   the parity gate decides, taste does not.
2. **Copier 9.x behavior drift** (answers-file template handling, tag resolution, skip globs).
   Pin `copier>=9.18,<10`; the per-push update test runs against whatever resolves, so a future
   copier release reddens CI rather than user machines. Residual: users pinning newer copier
   themselves — disclosed in the extra's help.
3. **Tag-as-`_commit` vs SHA**: a re-tagged release would move the 3-way base. Releases here
   never re-tag (convention); if that ever changes, the release smoke catches it. A build-time
   SHA stamp was rejected as unnecessary machinery: the tag is derivable from `__version__`
   with no build hook.
4. **Windows path/glob behavior** (skip patterns, `as_file` extraction): the CI Windows leg
   runs the update test — Windows is CI-corroborated by standing practice, not blocked on.
5. **The extra-absent refusal strands a workflow** mid-five-steps: the refusal names the exact
   install command (signing precedent) and README/qmd lead with `benchweave-sdk[scaffold]`.
6. **Interrupted-run guarantee weakens** because copier, not `Path.write_text`, does the
   writing — the existing monkeypatch injection point disappears. The contract (interrupted
   run leaves nothing) is kept by re-anchoring the test's failure injection at `run_copy`;
   the PR shows RED with the old injection removed and the new one failing.
7. **`upgrade` on projects inside parent repos** (plugin collections): git operations address
   the enclosing repo; clean-tree then means the parent's tree. Documented constraint +
   `upgrade_dirty_tree:` refuses; deeper support deferred (§3.5).

No hard blocker found; the mechanism is spike-proven end to end. **BUILD.**
