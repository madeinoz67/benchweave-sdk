# Changelog

All notable changes to this project will be documented in this file.

## [0.0.4] - 2026-09-20

### Bug Fixes

- Website version labels follow the release — v0.0.3 latest
- Resolve destination before writing; name symlink refusals in read_file

### Documentation

- Design record for issue #107 symlinked-destination fix
- Disclose that new canonicalizes symlinked destinations
- Review-driven corrections for the issue-107 fix
- Recall the memory vault before proposing or diagnosing

### Miscellaneous

- SDK 0.0.4 — the symlinked-destination fix
## [0.0.3] - 2026-09-20

### Bug Fixes

- ADAPTER_API_VERSION follows the 0.1.0 baseline (smoke-lane follow-up)
- Brand mark per public-site styleguide
- Assembly honesty guards, hermetic staging, website/README integration
- Un-double version selector trigger, link docs back to site root
- Anchor the site/ ignore to the repo root
- Point the Gateway links at the project website, not GitHub
- One extras sweep + stamp verification across every check lane (#9)
- ADAPTER_API_VERSION returns to the descriptor schema's 1.1 const (#20)
- Portable hook path in drift-guard test (#22)
- Vendor otdp 0.1.1 (byte-errata of 0.1.0, #45) (#23)
- Surface the S19 reason when the schema rejects first
- ASCII digit gate for the S19 tokenizer; census hardening
- Anchor sdist include globs — stop .claude/ and .gitignore leaking past the five-entry list
- Anchor /src and widen the VCS-exclusion drop to .hgignore
- Fold wave 1 — wheel-scope the CLAUDE.md claim, hyphenate skill names
- Register v0.0.3 in great-docs versions — release-time obligation the assembly gate enforces

### Documentation

- Repoint main-repo corpus links after the standards one-tree consolidation
- Authoring-brief and surface docstrings at 0.1.0 (review M12)
- Landing page + plugin authoring guide migrated into the site
- Docstrings for exported SDK symbols surfaced by the reference build
- Apply BenchWeave design system tokens + CLI-first nav
- Correct standards versions in prose (machine sources govern)
- Add Contributor Covenant 3.0 code of conduct
- Add SECURITY, CONTRIBUTING, SUPPORT and issue/PR templates
- Close-out — land docs-site spec and plan
- Report via private advisory, not personal email
- Add permanent Discord invite to README, SUPPORT and site
- SDK review rubric, hard invariants and drift obligations (#14)
- Track PR #9's new refusal prefixes in STD-4 (#16)
- Port the retrospective workflow rules from main #69
- GOVERNANCE is main-side only, not vendored or synced
- Presentation-guide deep link follows plugin-ui 0.2.0
- Align version prose to the vendored tree — registry 0.1.1, OTDP 0.2.0
- Port amended deferral rule from main #98 (#30)
- Issue #71 slice 2 — the agent-native scaffold record
- Name the seeded tree in README and guide; single issue stream
- Sync run-close step 8 from gateway #105

### Features

- Git-cliff config, seeded CHANGELOG.md, release-driven changelog job
- Great-docs site config with tag-keyed multi-version + dev
- Static public site from the public-site mockup
- CLI reference before API (assembly transform pending native ref_section_order)
- Refocus the static site on the SDK
- Align the SDK mark and tokens to public-site styleguide v0.2
- Star-on-GitHub header CTA with live count
- The build loop — agents, skills, drift guard, design records, constitution (#15)
- Vendor plugin-ui 0.1.1 channel_hints
- Vendor otdp 0.1.2 and add the S19 derived-variable checks
- Vendor OTDP 0.2.0 — averaging admission + sample_count bound
- Vendor plugin-ui 0.2.0 — lane-1 descriptor envelopes + orphan refusal
- Vendor registry 0.1.1 — skill payload-file role
- Seed the agent-native tree - CLAUDE.md + packaged skills

### Miscellaneous

- Remove stray 'standards-lock 2.json' artifact (review M-2)
- Re-vendor after the audit straggler sweep (URN $ids, catalog contract_version)
- Re-vendor after review fix wave 2
- Ignore gortex git-hook artifacts
- Ignore assembled docs site + assembly staging
- Refresh preview renderer for the C1-C4 fix wave
- Refresh preview renderer for the W1 hidden-claimant fix
- Refresh preview renderer for the FC1/FC2 fixes
- Bump preview renderer_version to 0.1.1
- Re-sync the vendored census (wave-3 hardening row)
- Reconcile with row C — dual-standard vendored tree
- SDK 0.0.3 — the scaffolds-skills version boundary
- Grant gortex read/query via official server pattern + disallowedTools

### Refactoring

- Vendored standards tree under <id>/<version> layout
- Standards reset to 0.1.0 baseline

### Style

- Trim assembly log line to lint width
- Drop the unused schema-error binding

### Ci

- Bump homebrew tap formula on release (go-rag pattern)
- True per-tag snapshot assembly, Pages deploy on main
- Serve site at root, docs under /docs/
- Fix empty --pr in preview notice (github.event.number, not github.event_number)
- Push CHANGELOG.md via changelog app token
## [0.0.2] - 2026-09-15

### Bug Fixes

- Derive __version__ from installed metadata; smoke asserts the tag version

### Miscellaneous

- 0.0.2

### Ci

- Smoke via RUNNER_TEMP - macOS /tmp symlink fails SDK path validation
## [0.0.1] - 2026-09-15

### Bug Fixes

- Scaffold a location-independent preview conformance test
- Enforce preview-server trust boundaries
- Harden generated-project creation
- Polish preview runtime surfaces
- Check exits nonzero on drift; vocabulary and deprecation reporting
- Sdk tag rides with at least one descriptive tag; document the hand-run base

### Documentation

- Show optional plugin feature directory layout
- Complete local UI preview developer loop
- Define SDK README banner design
- Plan SDK README banner implementation
- Add SDK README banner
- Feature SDK banner in README
- Point the matrix-staleness NOTE at the main repository gate
- Adopt the plugin SDK guide
- Sister-repository block linking the main repository
- Complete the refusal-prefix census and test-module menu
- Absolute links to main-repo documents
- Relicense the SDK package MIT for PyPI distribution
- Installation section with PyPI, brew and git channels
- Plugin guide install paragraph reflects PyPI publication
- Release cycle section reflects the PyPI publish workflow

### Features

- WP07 task 7 — two-phase admin changes with independently authenticated approvals
- Add SDK-aligned presentation contracts and presets
- Define deterministic preview fixture contract
- Validate preview fixtures and baseline states
- Serve deterministic preview API on loopback
- Add local preview-ui command
- Sync-standards import with lock and check mode
- Vendored standards tree and lock from first sync
- Self-contained check mode without a bundle
- Ledger with sdk-tagged proposals draining to the benchweave vault
- Reviewer agent, agent conventions and MCP wiring
- Tag-version guard with tests and a pytest CI lane

### Miscellaneous

- Ignore tool-generated state in the split repo
- Keep superpowers planning docs local
- Ignore local superpowers planning docs
- 0.0.1 - first PyPI publication

### Refactoring

- Align CLI with Click Rich and Textual
- Single-source preview constants

### Build

- Bundle versioned UI preview renderer
- Package the vendored standards tree from the lock

### Ci

- SDK check pipeline
- Build once, smoke the wheel on 4 os/arch lanes, publish to PyPI via Trusted Publishing

