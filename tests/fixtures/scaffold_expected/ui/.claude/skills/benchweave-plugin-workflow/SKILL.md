---
name: benchweave-plugin-workflow
description: Use when you work through the five plugin steps — doctor,
  tests, check, build, inventory — or move a project between SDK versions
  with upgrade or adopt.
---

# The plugin workflow as commands

Run every command from the directory that contains `pyproject.toml`.

## Set up and diagnose

- `uv pip install -e '.[test]'` — install the project and its test
  dependencies.
- `pytest` — run the plugin tests.
- `benchweave-sdk doctor` — compare the SDK pin in `pyproject.toml` with the
  installed SDK. `doctor` is a report, never a failure: a version mismatch is
  reported, not an error, and the command works offline. `doctor` never
  replaces the conformance gate.

## The gate

- `benchweave-sdk check src/example_plugin/descriptor.json` — the offline
  descriptor check. Exit code 0 is the gate. The check is partial: it covers
  the descriptor schema and the S01, S02 and S04 checks. It does not cover all
  S01–S18, C01–C12 and M01–M14 obligations.

## Build and inventory

- `uv build` — build the wheel and the source distribution.
- `benchweave-sdk inventory <directory>` — print the file rows for a prepared
  bundle: path, size in bytes and hash value. The rows are not a registry
  manifest.

## Move between SDK versions

- `benchweave-sdk upgrade` — move the project to the installed SDK's released
  template tag. Run it on a committed and clean git tree. The upgrade
  refreshes a managed file that you did not edit. When your edits and the
  template's changes touch the same lines of a file, the upgrade writes
  conflict markers; resolve both sides, then commit. Files the template no
  longer carries: your own files are kept and reported; managed files are
  removed, and git history keeps them.
- `benchweave-sdk adopt` — write the provenance record for a project made
  before the copier port. `adopt` infers the package name and base version
  from `pyproject.toml` and refuses a project whose provenance it cannot
  establish.

## Read the docs

The plugin SDK guide covers the full cycle in section "1. Install the SDK and
generate your project" and section "5. Prepare the release, then approve
publication".

---
Maintained by benchweave-sdk 0.7.0; `benchweave-sdk upgrade`
refreshes this skill.
