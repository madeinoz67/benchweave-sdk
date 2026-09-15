# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Features

- Git-cliff config, seeded CHANGELOG.md, release-driven changelog job

### Ci

- Bump homebrew tap formula on release (go-rag pattern)
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

