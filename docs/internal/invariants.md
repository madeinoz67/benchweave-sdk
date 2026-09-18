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
  `unexpected_vendored_file`, `sync_requires_repo_checkout`). A new refusal path that raises
  bare prose breaks the machine-matchable surface CI and scripts branch on —
  `standards_sync.py`, `cli.py` (the sync lane's checkout-detection refusal). *The prefixes
  are an API even though they live in error text.*
- **[STD-5]** The stamps say *generated — do not edit*: a hand-edit to a vendored file is
  wrong no matter how good the edit is; the change belongs in the main repository's
  canonical corpus, re-exported and re-synced. Normative standards changes start main-side
  — `src/benchweave_sdk/standards/`. *Two owners for one file means the lock always loses.*
- **[PKG-1]** **Self-containment**: this repository's CI checks out with no submodules and
  never reads the gateway checkout; nothing at test or runtime may reach for the parent
  repository's paths — `.github/workflows/ci.yml`. *The submodule mount makes parent paths
  exist on a developer machine and not in CI, so the breakage is invisible exactly where
  it matters most.*
- **[PKG-2]** The wheel packages `src/benchweave_sdk` only; the sdist include list is
  explicit (`src`, `pyproject.toml`, `README.md`, `hatch_build.py`,
  `standards-lock.json`); `.claude/`, `.mcp.json`, `AGENTS.md` and `CLAUDE.md` must never
  appear in either artifact; `hatch_build.py` validates the vendored standards and the
  preview assets **before** packaging — `pyproject.toml` `[tool.hatch...]`, `hatch_build.py`
  `CustomBuildHook.initialize`. *A wheel that ships agent config or an unverified tree is a
  supply-chain event, not a packaging nit.*
- **[PKG-3]** **Renderer freshness**: a fresh renderer build must leave the committed
  `src/benchweave_sdk/preview_assets/` unchanged — enforced main-side by the `ui` job's
  `git -C packages/sdk diff --exit-code -- src/benchweave_sdk/preview_assets`. *Source drift
  would otherwise ship silently in the wheel; hatch's inventory check only proves
  committed-bytes consistency.*

## Surface & conformance invariants

- **[SRF-1]** Scaffold output is an interface: entry points, the generated `pyproject.toml`,
  the explicitly-synthetic protocol placeholder and its warnings, the AI-GUIDE text, and
  the test extra that pins the SDK version reproduce into every downstream plugin
  repository — `scaffold.py`. The generated plugin runtime has **no dependency on this
  SDK**. *A defect here multiplies across every plugin authored from the scaffold, and
  downstream repos diff generated output, so shape changes are interface changes.*
- **[SRF-2]** **Preview ↔ check-ui agreement**: the preview renders plugin-ui surfaces
  against the vendored plugin-ui contracts and must accept exactly what `check-ui`
  accepts — a preview that happily renders what the conformance check rejects (or the
  reverse) is the cross-surface bug — `preview_server.py`, `preview_models.py`,
  `presentation.py`; the preview reads standards from the vendored tree and nowhere else.
  *A preview that disagrees with the checker trains plugin authors to ship what the
  gateway will refuse.*
- **[SRF-3]** Conformance and validation encode, offline, the standards the gateway
  enforces at load: a weakening here silently greenlights a non-conformant plugin. When
  reviewing a rule, compare it against the vendored standard text in
  `src/benchweave_sdk/standards/` — never against memory of what the standard says —
  `conformance.py`, `validation.py`, `fixtures.py`. *Confident recall of a standard is how
  a wrong rule ships.*
- **[TWO-1]** **Two-repo discipline**: an SDK change lands as a commit in this repository
  (pushed), then a pointer commit in the main repository; the main repository's
  `make sync-sdk-standards` refuses to run against a submodule HEAD that differs from the
  committed pointer — that refusal is the discipline working, not a bug to route around.
  *An unpushed submodule commit is invisible to main CI, which checks out by SHA.*

---

## Known open wounds

Some invariants sit next to known-imperfect code. Track the individual issue in the repo
tracker and cite it in review rather than building a consolidated weakness list here — a
one-stop map is more useful to an attacker than to a reviewer, who is only ever looking at
one diff. If a PR touches a wound, fix it or at least do not widen it, and say which.
